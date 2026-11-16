"""钻石计费 业务逻辑层（按「一次生成」聚合结算）

口径：
- 实际成本（美元）先乘 3，再按 1 美元 = 50 钻石折算：``钻石 = ceil(成本 × 150)``；
- 同一次 AI 生成触发的所有 LLM 调用共用 ``X-Generation-Id``，结算时汇总再一次取整；
- 允许欠费：余额可扣成负数；余额为负时由 ``precheck`` 拦截下一次生成；
- 结算幂等：``generation_billing.diamonds_charged`` 记录累计目标值，重复/增量结算只扣差额。
"""
import logging
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_CEILING

from sqlalchemy import case, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.generation_billing import GenerationBilling
from app.models.user_info import UserInfo
from app.models.user_token_info import UserTokenInfo

logger = logging.getLogger(__name__)

_USER_ID_MAX_LEN = 64
_GENERATION_ID_MAX_LEN = 64

#: 1 美元 = 50 钻石（1 钻石 = 0.02 美元）
USD_PER_DIAMOND = Decimal("0.02")
#: 实际 token 成本翻 3 倍计费
COST_MARKUP = Decimal("3")
#: 成本（美元）→ 钻石的换算系数：3 / 0.02 = 150
DIAMOND_FACTOR = COST_MARKUP / USD_PER_DIAMOND

#: 预检时回补结算的窗口：只捞近几天的未结算生成，避免全表扫描
OPEN_SETTLE_LOOKBACK_DAYS = 3
#: 单次预检最多回补的未结算生成数
OPEN_SETTLE_LIMIT = 20


def normalize_user_id(user_id: str | None) -> str:
    return (user_id or "")[:_USER_ID_MAX_LEN]


def normalize_generation_id(generation_id: str | None) -> str:
    return (generation_id or "")[:_GENERATION_ID_MAX_LEN]


def diamonds_for_cost(cost_usd) -> int:
    """美元成本 → 应扣钻石数（向上取整）。0/负数/非法值返回 0。"""
    try:
        cost = Decimal(str(cost_usd or 0))
    except (TypeError, ValueError, ArithmeticError):
        cost = Decimal("0")
    if cost <= 0:
        return 0
    return int((cost * DIAMOND_FACTOR).to_integral_value(rounding=ROUND_CEILING))


async def _ensure_ledger(db: AsyncSession, generation_id: str, user_id: str) -> None:
    """确保台账行存在；并发首次插入撞主键时回滚（另一事务已建行）。"""
    exists = await db.get(GenerationBilling, generation_id)
    if exists is not None:
        return
    db.add(GenerationBilling(generation_id=generation_id, user_id=user_id))
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        logger.debug("生成台账行已存在: generation_id=%s", generation_id)


async def settle_generation(
        db: AsyncSession,
        user_id: str,
        generation_id: str,
) -> dict | None:
    """结算一次生成的钻石消耗（幂等，可重复调用补扣）。

    Returns:
        ``{"generationId", "costUsd", "diamonds", "totalDiamonds", "balance"}``；
        generation_id/user_id 为空或用户不存在时返回 None。
    """
    uid = normalize_user_id(user_id)
    gid = normalize_generation_id(generation_id)
    if not uid or not gid:
        return None

    await _ensure_ledger(db, gid, uid)

    # 锁台账行：同一 generation_id 的并发结算串行化
    ledger = (await db.execute(
        select(GenerationBilling)
        .where(GenerationBilling.generation_id == gid)
        .with_for_update()
    )).scalar_one_or_none()
    if ledger is None:
        return None

    # 汇总本次生成的全部用量（只认同 user 的调用，防跨用户串账）
    # 成本只累加 USD 口径：钻石单价按 1 美元 = 50 钻石定义，混入其他币种会放大扣费。
    usd_cost = or_(
        UserTokenInfo.cost_currency.is_(None),
        func.upper(UserTokenInfo.cost_currency) == "USD",
    )
    row = (await db.execute(
        select(
            func.count(UserTokenInfo.id),
            func.coalesce(func.sum(UserTokenInfo.total_tokens), 0),
            func.coalesce(func.sum(case((usd_cost, UserTokenInfo.estimated_cost), else_=0)), 0),
        ).where(
            UserTokenInfo.user_id == uid,
            UserTokenInfo.generation_id == gid,
        )
    )).one()
    call_count = int(row[0] or 0)
    total_tokens = int(row[1] or 0)
    cost = Decimal(str(row[2] or 0))

    target = diamonds_for_cost(cost)
    already = int(ledger.diamonds_charged or 0)
    delta = max(0, target - already)

    if delta > 0:
        non_usd = (await db.execute(
            select(func.count(UserTokenInfo.id)).where(
                UserTokenInfo.user_id == uid,
                UserTokenInfo.generation_id == gid,
                UserTokenInfo.cost_currency.isnot(None),
                func.upper(UserTokenInfo.cost_currency) != "USD",
            )
        )).scalar()
        if non_usd:
            logger.warning(
                "结算跳过非 USD 成本行: user=%s generation=%s rows=%s"
                "（model_manage_info.price_currency 需配置为 USD 才会计入钻石）",
                uid, gid, non_usd,
            )

    balance_row = (await db.execute(
        select(UserInfo.point_balance).where(UserInfo.user_id == uid)
    )).first()
    if balance_row is None:
        logger.warning("结算跳过：用户不存在 user_id=%s generation_id=%s", uid, gid)
        await db.rollback()
        return None

    if delta > 0:
        # 允许欠费：不设余额下限
        await db.execute(
            update(UserInfo)
            .where(UserInfo.user_id == uid)
            .values(point_balance=UserInfo.point_balance - delta)
        )

    ledger.call_count = call_count
    ledger.total_tokens = total_tokens
    ledger.cost_usd = cost
    ledger.diamonds_charged = max(target, already)
    ledger.settled_at = datetime.now()
    await db.commit()

    balance = (await db.execute(
        select(UserInfo.point_balance).where(UserInfo.user_id == uid)
    )).scalar()

    logger.info(
        "钻石结算: user=%s generation=%s calls=%d tokens=%d cost=%.8f "
        "diamonds=+%d(total=%d) balance=%s",
        uid, gid, call_count, total_tokens, float(cost), delta,
        ledger.diamonds_charged, balance,
    )
    return {
        "generationId": gid,
        "costUsd": float(cost),
        "diamonds": delta,
        "totalDiamonds": int(ledger.diamonds_charged or 0),
        "balance": int(balance or 0),
    }


async def settle_open_generations(
        db: AsyncSession,
        user_id: str,
        *,
        limit: int = OPEN_SETTLE_LIMIT,
) -> int:
    """回补结算该用户最近的生成（应用侧漏结算/进程中断/后台链迟到用量兜底）。

    不筛 ``settled_at``：已结算的生成若有迟到用量（总结链等），结算函数会按
    累计目标值只扣差额；无新增用量时 delta=0，不产生余额变动。
    """
    uid = normalize_user_id(user_id)
    if not uid:
        return 0

    generation_ids = (await db.execute(
        select(UserTokenInfo.generation_id)
        .where(
            UserTokenInfo.user_id == uid,
            UserTokenInfo.generation_id.isnot(None),
            UserTokenInfo.generation_id != "",
            UserTokenInfo.record_date >= date.today() - timedelta(days=OPEN_SETTLE_LOOKBACK_DAYS),
        )
        .group_by(UserTokenInfo.generation_id)
        .order_by(func.max(UserTokenInfo.created_at).desc())
        .limit(limit)
    )).scalars().all()

    settled = 0
    for gid in generation_ids:
        try:
            result = await settle_generation(db, uid, gid)
            if result is not None:
                settled += 1
        except Exception as e:  # noqa: BLE001 - 单条结算失败不阻断预检
            await db.rollback()
            logger.warning("回补结算失败: user=%s generation=%s error=%s", uid, gid, e)
    return settled


async def precheck(db: AsyncSession, user_id: str) -> dict:
    """生成前预检：先回补结算旧生成，再判断余额是否已欠费。

    规则：余额 >= 0 放行（允许本次扣成负数）；余额 < 0 拦截。
    """
    uid = normalize_user_id(user_id)
    if not uid:
        return {"userId": "", "balance": 0, "blocked": False, "message": ""}

    settled = await settle_open_generations(db, uid)
    balance = (await db.execute(
        select(UserInfo.point_balance).where(UserInfo.user_id == uid)
    )).scalar()

    if balance is None:
        # 用户不存在（网关只读共享表）：按 0 放行，由后续结算自然处理
        logger.warning("钻石预检：用户不存在 user_id=%s", uid)
        return {"userId": uid, "balance": 0, "blocked": False,
                "message": "", "settled": settled}

    balance = int(balance or 0)
    blocked = balance < 0
    return {
        "userId": uid,
        "balance": balance,
        "blocked": blocked,
        "message": (f"钻石余额不足（当前 {balance} 钻），请充值后再生成"
                    if blocked else ""),
        "settled": settled,
    }
