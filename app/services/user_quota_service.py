"""用户级 Token 配额与访问封禁 业务逻辑层

- 策略表 user_quota_policy：每个 user_id 一行，限额语义 NULL=不限、0=禁止；
- 用量口径：user_daily_quota.total_tokens 按天累计，月用量 = 当月求和；
- 与项目配额保持同样的软限额语义：请求前 used >= limit 才拒绝。
"""
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_daily_quota import UserDailyQuota
from app.models.user_quota_policy import UserQuotaPolicy

logger = logging.getLogger(__name__)

STATUS_ACTIVE = "active"
STATUS_BLOCKED = "blocked"
VALID_STATUSES = (STATUS_ACTIVE, STATUS_BLOCKED)

_USER_ID_MAX_LEN = 64


class UserTokenQuotaError(Exception):
    """用户 Token 配额超限（code 供网关错误响应使用）"""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.message = message
        self.code = code


@dataclass(frozen=True)
class UserUsageSnapshot:
    """用户当日/当月用量快照（token 口径）"""

    today_calls: int = 0
    today_tokens: int = 0
    month_calls: int = 0
    month_tokens: int = 0


def normalize_user_id(user_id: str | None) -> str:
    """统一 64 字符上限，保证策略、计数、明细三处 key 一致."""
    return (user_id or "")[: _USER_ID_MAX_LEN]


async def get_quota_policy(db: AsyncSession, user_id: str) -> UserQuotaPolicy | None:
    """查询单个用户策略；不存在返回 None."""
    uid = normalize_user_id(user_id)
    if not uid:
        return None
    return await db.get(UserQuotaPolicy, uid)


async def get_quota_policy_map(
        db: AsyncSession, user_ids: Iterable[str],
) -> dict[str, UserQuotaPolicy]:
    """批量查询用户策略（管理端列表用，避免 N+1）."""
    ids = [normalize_user_id(uid) for uid in user_ids if uid]
    if not ids:
        return {}
    rows = (await db.execute(
        select(UserQuotaPolicy).where(UserQuotaPolicy.user_id.in_(ids))
    )).scalars().all()
    return {row.user_id: row for row in rows}


def is_blocked(policy: UserQuotaPolicy | None) -> bool:
    """封禁判断：只有明确 status=blocked 才拦截，缺省/active 放行."""
    if policy is None:
        return False
    return (policy.status or "").strip().lower() == STATUS_BLOCKED


def has_token_limits(policy: UserQuotaPolicy | None) -> bool:
    """策略是否存在任一非 NULL 的 Token 上限（用于跳过无谓的用量查询）."""
    if policy is None:
        return False
    return policy.daily_token_limit is not None or policy.monthly_token_limit is not None


async def upsert_quota_policy(
        db: AsyncSession,
        user_id: str,
        *,
        daily_token_limit: int | None,
        monthly_token_limit: int | None,
        access_status: str = STATUS_ACTIVE,
        remark: str | None = None,
) -> UserQuotaPolicy:
    """新增或更新用户策略（管理端保存）.

    并发首次保存撞主键时回滚并按更新路径重试一次，避免管理端双击/多人同时
    保存返回 500。
    """
    uid = normalize_user_id(user_id)
    if not uid:
        raise ValueError("用户ID不能为空")

    status = (access_status or STATUS_ACTIVE).strip().lower()
    if status not in VALID_STATUSES:
        raise ValueError(f"非法访问状态: {access_status}")

    def _apply(policy: UserQuotaPolicy) -> None:
        policy.daily_token_limit = daily_token_limit
        policy.monthly_token_limit = monthly_token_limit
        policy.status = status
        policy.remark = remark or None

    policy = await db.get(UserQuotaPolicy, uid)
    if policy is None:
        policy = UserQuotaPolicy(user_id=uid)
        db.add(policy)
    _apply(policy)

    try:
        await db.commit()
    except IntegrityError:
        # 并发首次插入：另一事务已建好该行，改为更新
        await db.rollback()
        policy = await db.get(UserQuotaPolicy, uid)
        if policy is None:
            raise
        _apply(policy)
        await db.commit()

    await db.refresh(policy)
    logger.info(
        "保存用户配额策略: user_id=%s daily=%s monthly=%s status=%s",
        uid, daily_token_limit, monthly_token_limit, status,
    )
    return policy


async def _load_month_rows(
        db: AsyncSession, user_ids: list[str],
) -> tuple[date, list[tuple[str, date, int, int]]]:
    """查询指定用户当月（自然月）每日计数行；月用量按需在内存求和.

    上限截止到 today，避免时钟漂移/手工写入的未来日期行虚增当月用量。
    """
    today = date.today()
    month_start = today.replace(day=1)
    rows = (await db.execute(
        select(
            UserDailyQuota.user_id,
            UserDailyQuota.quota_date,
            UserDailyQuota.call_count,
            UserDailyQuota.total_tokens,
        ).where(
            UserDailyQuota.user_id.in_(user_ids),
            UserDailyQuota.quota_date >= month_start,
            UserDailyQuota.quota_date <= today,
        )
    )).all()
    return today, list(rows)


def _aggregate(user_id: str, rows: list, today: date) -> UserUsageSnapshot:
    today_calls = today_tokens = month_calls = month_tokens = 0
    for row_user_id, quota_date, call_count, total_tokens in rows:
        if row_user_id != user_id:
            continue
        calls = int(call_count or 0)
        tokens = int(total_tokens or 0)
        month_calls += calls
        month_tokens += tokens
        if quota_date == today:
            today_calls += calls
            today_tokens += tokens
    return UserUsageSnapshot(
        today_calls=today_calls,
        today_tokens=today_tokens,
        month_calls=month_calls,
        month_tokens=month_tokens,
    )


async def get_user_usage_snapshot(
        db: AsyncSession, user_id: str,
) -> UserUsageSnapshot:
    """单个用户的当日/当月用量快照."""
    uid = normalize_user_id(user_id)
    if not uid:
        return UserUsageSnapshot()
    today, rows = await _load_month_rows(db, [uid])
    return _aggregate(uid, rows, today)


async def get_usage_snapshot_map(
        db: AsyncSession, user_ids: Iterable[str],
) -> dict[str, UserUsageSnapshot]:
    """批量查询用户用量快照（管理端列表用，避免 N+1）."""
    ids = [normalize_user_id(uid) for uid in user_ids if uid]
    if not ids:
        return {}
    today, rows = await _load_month_rows(db, ids)
    return {uid: _aggregate(uid, rows, today) for uid in ids}


def check_user_token_limits(
        policy: UserQuotaPolicy | None, snapshot: UserUsageSnapshot,
) -> None:
    """超限抛 UserTokenQuotaError；NULL=不限，0=禁止（与项目配额一致）."""
    if policy is None:
        return
    checks = (
        ("Daily token quota exceeded", "daily_token_quota_exceeded",
         policy.daily_token_limit, snapshot.today_tokens),
        ("Monthly token quota exceeded", "monthly_token_quota_exceeded",
         policy.monthly_token_limit, snapshot.month_tokens),
    )
    for label, code, limit, used in checks:
        if limit is None:
            continue
        if int(used) >= int(limit):
            raise UserTokenQuotaError(f"{label} ({used}/{limit})", code=code)
