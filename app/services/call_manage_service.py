"""LLM 调用管理 业务逻辑层

提供基于数据库的模型选择与轮询功能：
- 查询 model_manage_info 表中 is_using="1" 的模型
- 按 async_type 字段（async1..async9）划分集群，请求方通过
  X-Async-Type 指定集群
- 每个集群独立维护协程安全的轮询（round-robin）计数
"""
import asyncio
import logging
from datetime import date

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.model_manage_info import ModelManageInfo
from app.models.user_daily_quota import UserDailyQuota
from app.models.user_token_info import UserTokenInfo

logger = logging.getLogger(__name__)

# ── 集群类型（与 model_manage_info.async_type 固定取值一致） ──
VALID_ASYNC_TYPES: tuple[str, ...] = tuple(f"async{i}" for i in range(1, 10))

# ── 轮询计数器：每个集群独立计数（模块级，asyncio 安全） ──
_cluster_idx: dict[str, int] = {async_type: 0 for async_type in VALID_ASYNC_TYPES}
_lock = asyncio.Lock()


async def get_active_models(
    db: AsyncSession,
    async_type: str | None = None,
) -> list[ModelManageInfo]:
    """获取使用中的模型列表.

    Args:
        db: 数据库会话.
        async_type: None 返回所有使用中的模型；"async1".."async9" 仅返回该集群模型.

    Returns:
        ModelManageInfo 列表，按创建时间降序排列.
    """
    stmt = select(ModelManageInfo).where(ModelManageInfo.is_using == "1")
    if async_type is not None:
        stmt = stmt.where(ModelManageInfo.async_type == async_type)
    stmt = stmt.order_by(ModelManageInfo.created_at.desc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def next_model(
    models: list[ModelManageInfo],
    async_type: str,
) -> ModelManageInfo:
    """从指定集群的模型列表中轮询选择下一个模型（协程安全）.

    Args:
        models: 可选模型列表（调用方保证非空）.
        async_type: 集群类型 async1..async9，各集群独立计数.

    Returns:
        选中的 ModelManageInfo.

    Raises:
        ValueError: models 为空时抛出.
    """
    if not models:
        raise ValueError("models 列表为空")

    async with _lock:
        current = _cluster_idx.get(async_type, 0)
        idx = current % len(models)
        _cluster_idx[async_type] = current + 1

    selected = models[idx]
    logger.info(
        "轮询选择模型: cluster=%s idx=%d/%d model=%s url=%s",
        async_type, idx, len(models), selected.ai_model_name, selected.com_url,
    )
    return selected


async def incr_today_call_count(db: AsyncSession, user_id: str) -> None:
    """当日调用计数 +1（user_daily_quota 表，与 token 用量明细分离）.

    计数用于管理台「调用次数」统计。非关键路径：失败仅记日志（fail-open，
    少计一次比打断已完成的 LLM 响应更可接受）。

    使用数据库原子自增而非“先读再写”，避免并发请求丢计数；首次插入并发
    撞唯一键时回滚并按自增更新重试一次。
    """
    today = date.today()
    where = (
        UserDailyQuota.user_id == user_id,
        UserDailyQuota.quota_date == today,
    )
    try:
        result = await db.execute(
            update(UserDailyQuota).where(*where)
            .values(call_count=UserDailyQuota.call_count + 1)
        )
        if result.rowcount == 0:
            db.add(UserDailyQuota(user_id=user_id, quota_date=today, call_count=1))
        await db.commit()
    except IntegrityError:
        # 并发首次插入撞唯一键：另一事务已建好当天行，改为原子自增
        await db.rollback()
        try:
            await db.execute(
                update(UserDailyQuota).where(*where)
                .values(call_count=UserDailyQuota.call_count + 1)
            )
            await db.commit()
        except Exception as e:
            await db.rollback()
            logger.error("限额计数失败（fail-open 放行）: user_id=%s error=%s", user_id, e)
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
    feature_code: str = "uncategorized",
) -> None:
    """记录一次 LLM 调用：当日计数 +1（user_daily_quota）与 token 明细一行（user_token_info）.

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
        feature_code=(feature_code or "uncategorized")[:64],
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


