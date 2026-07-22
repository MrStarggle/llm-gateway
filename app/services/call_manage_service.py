"""LLM 调用管理 业务逻辑层

提供基于数据库的模型选择与轮询功能：
- 查询 model_manage_info 表中 is_using="1" 的模型
- 按 is_base 字段区分主 LLM 模型（is_base="0"）与异步/默认模型（is_base="1"）
- 协程安全的轮询（round-robin）调度
"""
import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.model_manage_info import ModelManageInfo

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
