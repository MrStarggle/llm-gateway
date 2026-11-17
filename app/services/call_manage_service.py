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
from decimal import Decimal

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
    input_price_per_1m: float | Decimal | None = None,
    output_price_per_1m: float | Decimal | None = None,
    price_currency: str = "USD",
    provider_cost: float | Decimal | None = None,
    project_id: str = "",
    token_id: str = "",
    channel_id: str = "",
    request_id: str = "",
    retry_count: int = 0,
) -> dict | None:
    """记录一次 LLM 调用：当日计数 +1 与 token 明细一行.

    返回本次调用的用量摘要（供项目配额计数使用）；user_id 为空时返回 None.
    成本优先级：上游 provider_cost > 模型单价估算 > 不记录.
    """
    if not user_id:
        return None
    await incr_today_call_count(db, user_id)

    if not usage:
        return {
            "totalTokens": 0,
            "cost": None,
            "costCurrency": None,
            "costSource": None,
        }

    prompt_tokens = int(usage.get("prompt_tokens") or 0)
    completion_tokens = int(usage.get("completion_tokens") or 0)
    total_tokens = int(usage.get("total_tokens") or 0)

    cost_value: Decimal | None = None
    cost_currency: str | None = None
    cost_source: str | None = None
    if provider_cost is not None:
        cost_value = Decimal(str(provider_cost)).quantize(Decimal("0.00000001"))
        cost_currency = "USD"
        cost_source = "provider"
    elif input_price_per_1m is not None or output_price_per_1m is not None:
        input_price = Decimal(str(input_price_per_1m or 0))
        output_price = Decimal(str(output_price_per_1m or 0))
        cost_value = (
            Decimal(prompt_tokens) * input_price + Decimal(completion_tokens) * output_price
        ) / Decimal("1000000")
        cost_value = cost_value.quantize(Decimal("0.00000001"))
        cost_currency = (price_currency or "USD")[:8]
        cost_source = "estimate"

    record = UserTokenInfo(
        user_id=user_id[:64],
        project_id=project_id[:64] or None,
        token_id=token_id[:64] or None,
        channel_id=(channel_id or "")[:64] or None,
        request_id=(request_id or "")[:64] or None,
        retry_count=max(0, int(retry_count or 0)),
        model=(model or "")[:128],
        purpose=(purpose or "main")[:16],
        feature_code=(feature_code or "uncategorized")[:64],
        is_stream=1 if is_stream else 0,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        prompt_cache_hit_tokens=int(usage.get("prompt_cache_hit_tokens") or 0),
        prompt_cache_miss_tokens=int(usage.get("prompt_cache_miss_tokens") or 0),
        estimated_cost=cost_value,
        cost_currency=cost_currency,
        cost_source=cost_source,
        record_date=date.today(),
    )
    try:
        db.add(record)
        await db.commit()
    except Exception as e:
        await db.rollback()
        logger.error("记录 token 用量失败: user_id=%s error=%s", user_id, e)
        return None

    return {
        "totalTokens": total_tokens,
        "cost": cost_value,
        "costCurrency": cost_currency,
        "costSource": cost_source,
    }


# 流式请求的用量写入不能依赖请求级 DB Session：客户端断开时生成器会被取消，
# finally 里的 await 可能中断。这里用独立任务 + 独立 Session 落盘。
_background_tasks: set[asyncio.Task] = set()


def schedule_background(coro) -> None:
    """调度一个不阻塞响应、且不随请求任务取消的后台协程."""
    try:
        task = asyncio.create_task(coro)
    except RuntimeError:
        # 事件循环已关闭
        close = getattr(coro, "close", None)
        if close:
            close()
        logger.error("后台任务调度失败：事件循环已关闭")
        return
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def record_stream_usage_background(
    *,
    user_id: str,
    model: str,
    purpose: str,
    usage: dict,
    feature_code: str = "uncategorized",
    input_price_per_1m=None,
    output_price_per_1m=None,
    price_currency: str = "USD",
    provider_cost=None,
    project_id: str = "",
    project_currency: str = "USD",
    token_id: str = "",
    token_last_used_at=None,
    channel_id: str = "",
    request_id: str = "",
    retry_count: int = 0,
) -> None:
    """流式请求结束后，用独立 Session 记录用量与项目计数."""
    from app.config.database import AsyncSessionLocal
    from app.services import project_manage_service

    try:
        async with AsyncSessionLocal() as db:
            result = await record_token_usage(
                db, user_id, model, purpose,
                is_stream=True, usage=usage,
                feature_code=feature_code,
                input_price_per_1m=input_price_per_1m,
                output_price_per_1m=output_price_per_1m,
                price_currency=price_currency,
                provider_cost=provider_cost,
                project_id=project_id,
                token_id=token_id,
                channel_id=channel_id,
                request_id=request_id,
                retry_count=retry_count,
            )
            if project_id and result is not None:
                try:
                    await project_manage_service.increment_project_usage(
                        db, project_id,
                        project_currency=project_currency,
                        tokens=int(result.get("totalTokens") or 0),
                        cost=result.get("cost"),
                        cost_currency=result.get("costCurrency"),
                    )
                except Exception as e:
                    logger.warning("流式项目用量计数失败: project_id=%s error=%s", project_id, e)
            if token_id:
                try:
                    await project_manage_service.touch_token(
                        db, token_id, last_used_at=token_last_used_at,
                    )
                except Exception as e:
                    logger.warning("更新 Token 最后使用时间失败: token_id=%s error=%s", token_id, e)
    except Exception as e:
        logger.error("流式用量后台记录失败: user_id=%s error=%s", user_id, e)


