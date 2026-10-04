"""用户管理 业务逻辑层（管理端，与 StarggleCom 共享数据库）"""
import logging
from datetime import date

from sqlalchemy import delete, desc, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.membership import tier_of_balance
from app.models.user_info import UserInfo
from app.models.order_info import OrderInfo
from app.models.user_daily_quota import UserDailyQuota
from app.utils.SnowflakeIDGenerator import get_snowflake_id

logger = logging.getLogger(__name__)


def effective_level_of(user: UserInfo) -> str:
    """根据积分余额计算实际生效等级（余额即等级）"""
    return tier_of_balance(user.point_balance)["level"]


async def list_users(
    db: AsyncSession,
    keyword: str = "",
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[UserInfo], int]:
    """分页查询用户（支持关键字模糊匹配 user_id/email/user_name/login_id）"""
    filters = []
    if keyword:
        like = f"%{keyword}%"
        filters.append(or_(
            UserInfo.user_id.ilike(like),
            UserInfo.email.ilike(like),
            UserInfo.user_name.ilike(like),
            UserInfo.login_id.ilike(like),
        ))

    count_stmt = select(func.count()).select_from(UserInfo)
    if filters:
        count_stmt = count_stmt.where(*filters)
    total = int((await db.execute(count_stmt)).scalar() or 0)

    stmt = select(UserInfo)
    if filters:
        stmt = stmt.where(*filters)
    stmt = stmt.order_by(desc(UserInfo.created_at))
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    users = (await db.execute(stmt)).scalars().all()
    return list(users), total


async def get_today_usage_map(db: AsyncSession, user_ids: list[str]) -> dict[str, int]:
    """批量查询多个用户今日 LLM 调用次数（限额口径，读 user_daily_quota 计数表）.

    2026-10-04 起与 token 用量明细（user_token_info）分离：本函数供限额展示与
    重置回读，来源=计数表；明细统计走 token 表.
    """
    if not user_ids:
        return {}
    rows = await db.execute(
        select(UserDailyQuota.user_id, UserDailyQuota.call_count)
        .where(
            UserDailyQuota.quota_date == date.today(),
            UserDailyQuota.user_id.in_(user_ids),
        )
    )
    return {uid: int(cnt or 0) for uid, cnt in rows.all()}


async def reset_today_call_count(db: AsyncSession, user_id: str) -> int | None:
    """管理员手动重置用户今日 LLM 调用次数：只清 user_daily_quota 当日计数行.

    2026-10-04 起限额与用量明细分离：重置只删计数表当日行（额度归零），
    user_token_info 的 token 用量明细**完整保留**，统计不受影响。
    返回删除行数；用户不存在返回 None（调用方转 400）。
    """
    user = await _get_user(db, user_id)
    if not user:
        return None
    result = await db.execute(
        delete(UserDailyQuota).where(
            UserDailyQuota.user_id == user_id,
            UserDailyQuota.quota_date == date.today(),
        )
    )
    await db.commit()
    deleted = int(result.rowcount or 0)
    logger.info("重置今日调用次数（仅计数表，明细保留）: user_id=%s deleted=%d",
                user_id, deleted)
    return deleted


async def grant_points(
    db: AsyncSession,
    user_id: str,
    points: int,
    remark: str | None = None,
) -> tuple[OrderInfo, UserInfo] | None:
    """管理员手动充值/扣减积分：创建一笔 paid 订单并更新余额，失败返回 None。

    业务规则：
    - points 正数为充值、负数为扣减，0 视为无效
    - 扣减后余额不得为负（抛 ValueError，调用方转成 400 提示）
    - 余额更新使用带条件的原子 UPDATE，防并发下丢失更新/扣成负数
    """
    if points == 0:
        raise ValueError("积分变动量不能为 0")

    user = await _get_user(db, user_id)
    if not user:
        return None

    # 原子扣减/充值：条件不满足（余额不足）时 rowcount 为 0
    result = await db.execute(
        update(UserInfo)
        .where(
            UserInfo.user_id == user_id,
            UserInfo.point_balance + points >= 0,
        )
        .values(point_balance=UserInfo.point_balance + points)
    )
    if result.rowcount == 0:
        raise ValueError(f"积分余额不足：当前 {user.point_balance}，无法扣减 {-points}")
    await db.flush()
    await db.refresh(user)

    order = OrderInfo(
        order_no=str(get_snowflake_id()),
        user_id=user_id,
        plan="points",
        amount_cents=points,
        currency="PTS",
        status="paid",
        channel="manual",
        remark=remark or ("管理员手动充值" if points > 0 else "管理员手动扣减"),
    )
    db.add(order)

    await db.commit()
    await db.refresh(order)
    logger.info("管理端手动充值积分: order_no=%s user_id=%s points=%s new_balance=%s",
                order.order_no, user_id, points, user.point_balance)
    return order, user


async def list_orders(
    db: AsyncSession,
    user_id: str = "",
    status: str = "",
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[OrderInfo], int]:
    """分页查询订单（支持按用户ID/状态筛选）"""
    filters = []
    if user_id:
        filters.append(OrderInfo.user_id == user_id)
    if status:
        filters.append(OrderInfo.status == status)

    count_stmt = select(func.count()).select_from(OrderInfo)
    if filters:
        count_stmt = count_stmt.where(*filters)
    total = int((await db.execute(count_stmt)).scalar() or 0)

    stmt = select(OrderInfo)
    if filters:
        stmt = stmt.where(*filters)
    stmt = stmt.order_by(desc(OrderInfo.created_at))
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    orders = (await db.execute(stmt)).scalars().all()
    return list(orders), total


async def _get_user(db: AsyncSession, user_id: str) -> UserInfo | None:
    result = await db.execute(select(UserInfo).where(UserInfo.user_id == user_id))
    return result.scalar_one_or_none()
