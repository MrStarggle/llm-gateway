"""大模型提供商 业务逻辑层

提供商是 API 地址与密钥的唯一配置源。model_manage_info 仍保留
com_name / com_url / api_key 三个冗余字段（调用链路直接读取，避免运行时联表），
在提供商新增/更新时由本模块负责同步，模型新建/编辑时由模型服务回填。
"""
import logging

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.llm_provider_info import LlmProviderInfo
from app.models.model_manage_info import ModelManageInfo
from app.schemas.llm_provider import ProviderCreate, ProviderUpdate
from app.utils.SnowflakeIDGenerator import snowflake_id_generator

logger = logging.getLogger(__name__)


async def list_providers(db: AsyncSession, keyword: str = "") -> list[LlmProviderInfo]:
    """提供商列表（按名称模糊搜索，创建时间升序）"""
    stmt = select(LlmProviderInfo)
    if keyword:
        stmt = stmt.where(LlmProviderInfo.provider_name.like(f"%{keyword}%"))
    stmt = stmt.order_by(LlmProviderInfo.created_at.asc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_provider_by_id(db: AsyncSession, provider_id: str) -> LlmProviderInfo | None:
    """按 ID 查询提供商"""
    stmt = select(LlmProviderInfo).where(LlmProviderInfo.provider_id == provider_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_provider_by_name(db: AsyncSession, provider_name: str) -> LlmProviderInfo | None:
    """按名称查询提供商（名称唯一）"""
    stmt = select(LlmProviderInfo).where(LlmProviderInfo.provider_name == provider_name)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_model_counts(db: AsyncSession) -> dict[str, int]:
    """各提供商关联的模型数量 {provider_id: count}"""
    stmt = (
        select(ModelManageInfo.provider_id, func.count(ModelManageInfo.ai_model_id))
        .where(ModelManageInfo.provider_id.is_not(None))
        .group_by(ModelManageInfo.provider_id)
    )
    result = await db.execute(stmt)
    return {row[0]: int(row[1] or 0) for row in result.all()}


async def create_provider(db: AsyncSession, data: ProviderCreate) -> LlmProviderInfo:
    """新增提供商；名称重复时抛 ValueError"""
    if await get_provider_by_name(db, data.provider_name):
        raise ValueError("提供商名称已存在")

    provider = LlmProviderInfo(
        provider_id=snowflake_id_generator.next_id_str(),
        provider_name=data.provider_name,
        api_url=data.api_url.strip(),
        api_key=data.api_key.strip(),
        remarks=data.remarks,
    )
    db.add(provider)
    await db.commit()
    await db.refresh(provider)
    logger.info("新增提供商: id=%s name=%s", provider.provider_id, provider.provider_name)
    return provider


async def update_provider(
        db: AsyncSession,
        provider_id: str,
        data: ProviderUpdate,
) -> LlmProviderInfo | None:
    """更新提供商，并把名称/地址/密钥级联同步到关联模型；不存在返回 None"""
    provider = await get_provider_by_id(db, provider_id)
    if provider is None:
        return None

    update_data = data.model_dump(exclude_unset=True)
    if not update_data:
        return provider

    new_name = update_data.get("provider_name")
    if new_name and new_name != provider.provider_name:
        exists = await get_provider_by_name(db, new_name)
        if exists is not None:
            raise ValueError("提供商名称已存在")

    for field, value in update_data.items():
        if isinstance(value, str):
            value = value.strip()
        setattr(provider, field, value)

    # 关联模型保留冗余字段以供调用链路直读，此处同步保持一致
    await db.execute(
        update(ModelManageInfo)
        .where(ModelManageInfo.provider_id == provider_id)
        .values(
            com_name=provider.provider_name,
            com_url=provider.api_url,
            api_key=provider.api_key,
        )
    )
    await db.commit()
    await db.refresh(provider)
    logger.info("更新提供商: id=%s fields=%s（已级联同步关联模型）", provider_id, list(update_data.keys()))
    return provider


async def delete_provider(db: AsyncSession, provider_id: str) -> tuple[bool, str]:
    """删除提供商；仍有关联模型时拒绝删除.

    Returns:
        (是否删除成功, 失败原因)
    """
    provider = await get_provider_by_id(db, provider_id)
    if provider is None:
        return False, "提供商不存在"

    count = (await db.execute(
        select(func.count(ModelManageInfo.ai_model_id))
        .where(ModelManageInfo.provider_id == provider_id)
    )).scalar() or 0
    if count > 0:
        return False, f"该提供商下仍有 {count} 个模型，请先删除或迁移这些模型"

    await db.execute(delete(LlmProviderInfo).where(LlmProviderInfo.provider_id == provider_id))
    await db.commit()
    logger.info("删除提供商: id=%s name=%s", provider_id, provider.provider_name)
    return True, ""
