"""LLM 调用管理 业务逻辑层

提供基于数据库的模型选择与轮询功能：
- 查询 model_manage_info 表中 is_using="1" 的模型
- 按 is_base 字段区分主 LLM 模型（is_base="0"）与异步/默认模型（is_base="1"）
- 协程安全的轮询（round-robin）调度
"""
import asyncio
import logging
from datetime import date

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.membership import DEFAULT_LEVEL
from app.models.model_manage_info import ModelManageInfo
from app.models.user_daily_quota import UserDailyQuota
from app.models.user_token_info import UserTokenInfo

logger = logging.getLogger(__name__)

# ── 轮询计数器（模块级，asyncio 安全） ──
_async_idx: int = 0       # is_base="1" 异步/基础模型
_primary_idx: int = 0     # is_base="0" 主 LLM 模型
_lock = asyncio.Lock()


async def get_active_models(
    db: AsyncSession,
    is_base: str | None = None,
) -> list[ModelManageInfo]:
    """获取使用中的模型列表.

    Args:
        db: 数据库会话.
        is_base: None 返回所有使用中的模型；
                 "1" 仅返回基础默认模型（异步 LLM 用）；
                 "0" 仅返回非基础模型（主 LLM 用）.

    Returns:
        ModelManageInfo 列表，按创建时间降序排列.
    """
    stmt = select(ModelManageInfo).where(ModelManageInfo.is_using == "1")
    if is_base is not None:
        stmt = stmt.where(ModelManageInfo.is_base == is_base)
    stmt = stmt.order_by(ModelManageInfo.created_at.desc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def next_model(
    models: list[ModelManageInfo],
    counter_type: str,
) -> ModelManageInfo:
    """从模型列表中轮询选择下一个模型（协程安全）.

    Args:
        models: 可选模型列表（调用方保证非空）.
        counter_type: "async" 使用异步计数器，"primary" 使用主 LLM 计数器.

    Returns:
        选中的 ModelManageInfo.

    Raises:
        ValueError: models 为空时抛出.
    """
    if not models:
        raise ValueError("models 列表为空")

    global _async_idx, _primary_idx
    async with _lock:
        if counter_type == "async":
            idx = _async_idx % len(models)
            _async_idx += 1
        else:
            idx = _primary_idx % len(models)
            _primary_idx += 1

    selected = models[idx]
    logger.info(
        "轮询选择模型: type=%s idx=%d/%d model=%s url=%s",
        counter_type, idx, len(models), selected.ai_model_name, selected.com_url,
    )
    return selected


async def incr_today_call_count(db: AsyncSession, user_id: str) -> None:
    """限额计数 +1（user_daily_quota 表，与 token 用量明细分离）.

    2026-10-04 起限额口径 = 本表当日 call_count，不再数 user_token_info 行——
    管理端重置额度只清本表，用量明细保留。非关键路径：失败仅记日志（fail-open，
    少计一次比打断已完成的 LLM 响应更可接受）。并发下唯一键冲突按更新重试一次。
    """
    today = date.today()
    try:
        row = (await db.execute(
            select(UserDailyQuota).where(
                UserDailyQuota.user_id == user_id,
                UserDailyQuota.quota_date == today,
            )
        )).scalar_one_or_none()
        if row is not None:
            row.call_count = (row.call_count or 0) + 1
        else:
            db.add(UserDailyQuota(user_id=user_id, quota_date=today, call_count=1))
        await db.commit()
    except Exception:
        await db.rollback()
        try:
            result = await db.execute(
                update(UserDailyQuota)
                .where(UserDailyQuota.user_id == user_id,
                       UserDailyQuota.quota_date == today)
                .values(call_count=UserDailyQuota.call_count + 1)
            )
            if result.rowcount == 0:
                db.add(UserDailyQuota(user_id=user_id, quota_date=today, call_count=1))
            await db.commit()
        except Exception as e:
            await db.rollback()
            logger.error("限额计数失败（fail-open 放行）: user_id=%s error=%s", user_id, e)


async def record_token_usage(
    db: AsyncSession,
    user_id: str,
    model: str,
    purpose: str,
    is_stream: bool,
    usage: dict,
) -> None:
    """记录一次 LLM 调用：限额计数 +1（user_daily_quota）与 token 明细一行（user_token_info）.

    2026-10-04 拆分：两表职责分离——计数是限额判定源（重置只清计数），明细是统计。
    非关键路径：任一失败仅记录日志，绝不影响 LLM 响应的返回.
    只要调用发生（user_id 存在）计数即 +1；明细仍要求 usage 非空.
    """
    if not user_id:
        return
    await incr_today_call_count(db, user_id)

    if not usage:
        return
    record = UserTokenInfo(
        user_id=user_id[:64],
        model=(model or "")[:128],
        purpose=(purpose or "main")[:16],
        is_stream=1 if is_stream else 0,
        prompt_tokens=int(usage.get("prompt_tokens") or 0),
        completion_tokens=int(usage.get("completion_tokens") or 0),
        total_tokens=int(usage.get("total_tokens") or 0),
        prompt_cache_hit_tokens=int(usage.get("prompt_cache_hit_tokens") or 0),
        prompt_cache_miss_tokens=int(usage.get("prompt_cache_miss_tokens") or 0),
        record_date=date.today(),
    )
    try:
        db.add(record)
        await db.commit()
    except Exception as e:
        await db.rollback()
        logger.error("记录 token 用量失败: user_id=%s error=%s", user_id, e)


async def get_effective_membership(
    db: AsyncSession,
    user_id: str,
) -> str:
    """查询用户实际生效的会员等级（积分制：余额即等级，未知用户回落 free）.

    Args:
        db: 数据库会话.
        user_id: 用户ID.

    Returns:
        "free" / "silver" / "gold" / "diamond".
    """
    from app.models.user_info import UserInfo
    from app.config.membership import tier_of_balance

    if not user_id:
        return DEFAULT_LEVEL

    result = await db.execute(
        select(UserInfo.point_balance).where(UserInfo.user_id == user_id)
    )
    row = result.first()
    if not row:
        return DEFAULT_LEVEL

    return tier_of_balance(row[0])["level"]


async def get_today_call_count(db: AsyncSession, user_id: str) -> int:
    """查询用户今日 LLM 调用次数（限额口径，读 user_daily_quota 计数表）.

    2026-10-04 起与 token 用量明细（user_token_info）分离：重置额度只清计数表，
    明细保留供统计。无记录返回 0.
    """
    stmt = (
        select(UserDailyQuota.call_count)
        .where(
            UserDailyQuota.user_id == user_id,
            UserDailyQuota.quota_date == date.today(),
        )
    )
    result = await db.execute(stmt)
    return int(result.scalar() or 0)
