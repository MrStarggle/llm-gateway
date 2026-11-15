"""用量统计 业务逻辑层

数据来源：
- user_daily_quota：每次 LLM 调用的计数，用于「调用次数」
- user_token_info：每次调用的 token 明细，用于 token 用量 / 按模型统计 / 调用记录
"""
import logging
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_daily_quota import UserDailyQuota
from app.models.user_token_info import UserTokenInfo

logger = logging.getLogger(__name__)

_MAX_DAYS = 90
_DEFAULT_PAGE_SIZE = 20
_MAX_PAGE_SIZE = 100


def _range_start(days: int) -> date:
    """把「最近 N 天」（含今天）换算为起始日期"""
    days = max(1, min(days, _MAX_DAYS))
    return date.today() - timedelta(days=days - 1)


async def get_usage_overview(db: AsyncSession, days: int = 7) -> dict:
    """用量总览：汇总卡片 + 每日趋势 + 按模型分布（一次查询返回，供管理页一块展示）"""
    days = max(1, min(days, _MAX_DAYS))
    start = _range_start(days)

    token_rows = (await db.execute(
        select(
            UserTokenInfo.record_date,
            func.count(UserTokenInfo.id),
            func.coalesce(func.sum(UserTokenInfo.prompt_tokens), 0),
            func.coalesce(func.sum(UserTokenInfo.completion_tokens), 0),
            func.coalesce(func.sum(UserTokenInfo.total_tokens), 0),
            func.coalesce(func.sum(UserTokenInfo.prompt_cache_hit_tokens), 0),
        )
        .where(UserTokenInfo.record_date >= start)
        .group_by(UserTokenInfo.record_date)
    )).all()

    quota_rows = (await db.execute(
        select(
            UserDailyQuota.quota_date,
            func.coalesce(func.sum(UserDailyQuota.call_count), 0),
        )
        .where(UserDailyQuota.quota_date >= start)
        .group_by(UserDailyQuota.quota_date)
    )).all()

    user_count = (await db.execute(
        select(func.count(func.distinct(UserTokenInfo.user_id)))
        .where(UserTokenInfo.record_date >= start)
    )).scalar() or 0

    token_map = {
        row[0]: {
            "requests": int(row[1] or 0),
            "promptTokens": int(row[2] or 0),
            "completionTokens": int(row[3] or 0),
            "totalTokens": int(row[4] or 0),
            "cacheHitTokens": int(row[5] or 0),
        }
        for row in token_rows
    }
    quota_map = {row[0]: int(row[1] or 0) for row in quota_rows}

    daily: list[dict] = []
    cursor = start
    while cursor <= date.today():
        token = token_map.get(cursor, {})
        daily.append({
            "date": cursor.isoformat(),
            "calls": quota_map.get(cursor, 0),
            "requests": token.get("requests", 0),
            "promptTokens": token.get("promptTokens", 0),
            "completionTokens": token.get("completionTokens", 0),
            "totalTokens": token.get("totalTokens", 0),
        })
        cursor += timedelta(days=1)

    model_rows = (await db.execute(
        select(
            UserTokenInfo.model,
            func.count(UserTokenInfo.id),
            func.coalesce(func.sum(UserTokenInfo.prompt_tokens), 0),
            func.coalesce(func.sum(UserTokenInfo.completion_tokens), 0),
            func.coalesce(func.sum(UserTokenInfo.total_tokens), 0),
        )
        .where(UserTokenInfo.record_date >= start)
        .group_by(UserTokenInfo.model)
        .order_by(func.coalesce(func.sum(UserTokenInfo.total_tokens), 0).desc())
        .limit(20)
    )).all()

    by_model = [
        {
            "model": row[0] or "-",
            "calls": int(row[1] or 0),
            "promptTokens": int(row[2] or 0),
            "completionTokens": int(row[3] or 0),
            "totalTokens": int(row[4] or 0),
        }
        for row in model_rows
    ]

    total_tokens = sum(d["totalTokens"] for d in daily)
    summary = {
        "days": days,
        "startDate": start.isoformat(),
        "endDate": date.today().isoformat(),
        "calls": sum(d["calls"] for d in daily),
        "requests": sum(d["requests"] for d in daily),
        "users": int(user_count),
        "promptTokens": sum(d["promptTokens"] for d in daily),
        "completionTokens": sum(d["completionTokens"] for d in daily),
        "totalTokens": total_tokens,
        "cacheHitTokens": sum(t.get("cacheHitTokens", 0) for t in token_map.values()),
    }

    return {"summary": summary, "daily": daily, "byModel": by_model}


async def list_call_records(
        db: AsyncSession,
        page: int = 1,
        page_size: int = _DEFAULT_PAGE_SIZE,
        user_id: str = "",
        model: str = "",
        purpose: str = "",
        start_date: str = "",
        end_date: str = "",
) -> tuple[list[dict], int]:
    """调用记录分页列表（user_token_info 明细，左连用户表补充用户名/邮箱）"""
    page = max(page, 1)
    page_size = max(1, min(page_size, _MAX_PAGE_SIZE))

    conditions = []
    if user_id:
        conditions.append(UserTokenInfo.user_id.like(f"%{user_id}%"))
    if model:
        conditions.append(UserTokenInfo.model.like(f"%{model}%"))
    if purpose:
        conditions.append(UserTokenInfo.purpose == purpose)
    if start_date:
        try:
            conditions.append(UserTokenInfo.record_date >= date.fromisoformat(start_date))
        except ValueError:
            logger.warning("调用记录查询：忽略非法开始日期 %r", start_date)
    if end_date:
        try:
            conditions.append(UserTokenInfo.record_date <= date.fromisoformat(end_date))
        except ValueError:
            logger.warning("调用记录查询：忽略非法结束日期 %r", end_date)

    total = (await db.execute(
        select(func.count(UserTokenInfo.id)).where(*conditions)
    )).scalar() or 0

    rows = (await db.execute(
        select(UserTokenInfo)
        .where(*conditions)
        .order_by(UserTokenInfo.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )).scalars().all()

    records = []
    for row in rows:
        records.append({
            "id": row.id,
            "userId": row.user_id,
            "model": row.model,
            "purpose": row.purpose,
            "isStream": row.is_stream,
            "promptTokens": int(row.prompt_tokens or 0),
            "completionTokens": int(row.completion_tokens or 0),
            "totalTokens": int(row.total_tokens or 0),
            "cacheHitTokens": int(row.prompt_cache_hit_tokens or 0),
            "cacheMissTokens": int(row.prompt_cache_miss_tokens or 0),
            "recordDate": row.record_date.isoformat() if row.record_date else None,
            "createdAt": row.created_at.isoformat() if row.created_at else None,
        })
    return records, int(total)
