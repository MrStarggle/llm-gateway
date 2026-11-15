"""模型管理 业务逻辑层"""
import logging
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.model_manage_info import ModelManageInfo
from app.schemas.model_manage import ModelManageCreate, ModelManageUpdate, ModelManageQuery
from app.utils.SnowflakeIDGenerator import snowflake_id_generator

logger = logging.getLogger(__name__)


def _to_decimal(value: float | None) -> Decimal | None:
    """金额/单价转 Decimal，避免 float 精度问题"""
    return None if value is None else Decimal(str(value))


async def get_model_list(
        db: AsyncSession,
        query: ModelManageQuery | None = None,
) -> list[ModelManageInfo]:
    """获取模型列表，支持多条件筛选"""
    stmt = select(ModelManageInfo)

    if query:
        if query.provider_id:
            stmt = stmt.where(ModelManageInfo.provider_id == query.provider_id)
        if query.com_name:
            stmt = stmt.where(ModelManageInfo.com_name.like(f"%{query.com_name}%"))
        if query.ai_model_name:
            stmt = stmt.where(ModelManageInfo.ai_model_name.like(f"%{query.ai_model_name}%"))
        if query.is_using:
            stmt = stmt.where(ModelManageInfo.is_using == query.is_using)
        if query.async_type:
            stmt = stmt.where(ModelManageInfo.async_type == query.async_type)
        if query.ai_model_type:
            stmt = stmt.where(ModelManageInfo.ai_model_type == query.ai_model_type)

    stmt = stmt.order_by(ModelManageInfo.created_at.desc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_model_by_id(db: AsyncSession, model_id: str) -> ModelManageInfo | None:
    """根据 ID 获取单个模型"""
    stmt = select(ModelManageInfo).where(ModelManageInfo.ai_model_id == model_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def _resolve_provider_config(
        db: AsyncSession,
        provider_id: str,
) -> tuple[str, str, str]:
    """按提供商回填 (com_name, com_url, api_key)；提供商不存在时抛 ValueError"""
    from app.services import llm_provider_service

    provider = await llm_provider_service.get_provider_by_id(db, provider_id)
    if provider is None:
        raise ValueError("提供商不存在")
    return provider.provider_name, provider.api_url, provider.api_key


async def create_model(db: AsyncSession, data: ModelManageCreate) -> ModelManageInfo:
    """新增模型：优先按 provider_id 回填运营商名称/地址/密钥"""
    if data.provider_id:
        com_name, com_url, api_key = await _resolve_provider_config(db, data.provider_id)
    else:
        if not (data.com_name and data.com_url and data.api_key):
            raise ValueError("请选择大模型提供商（或完整填写运营商名称、URL、API Key）")
        com_name, com_url, api_key = data.com_name, data.com_url, data.api_key

    model_id = snowflake_id_generator.next_id_str()
    model = ModelManageInfo(
        ai_model_id=model_id,
        ai_model_name=data.ai_model_name,
        provider_id=data.provider_id,
        com_name=com_name,
        com_url=com_url,
        api_key=api_key,
        ai_model_type=data.ai_model_type,
        is_using=data.is_using,
        is_think=data.is_think,
        is_stream=data.is_stream,
        async_type=data.async_type,
        temperature=data.temperature,
        top_p=data.top_p,
        top_k=data.top_k,
        max_tokens=data.max_tokens,
        input_price_per_1m=_to_decimal(data.input_price_per_1m),
        output_price_per_1m=_to_decimal(data.output_price_per_1m),
        price_currency=data.price_currency or "USD",
        price_source="manual" if (data.input_price_per_1m is not None or data.output_price_per_1m is not None) else None,
        price_updated_at=datetime.now() if (data.input_price_per_1m is not None or data.output_price_per_1m is not None) else None,
        extra_config=data.extra_config,
        remarks=data.remarks,
    )
    db.add(model)
    await db.commit()
    await db.refresh(model)
    logger.info(f"新增模型: id={model_id} name={data.ai_model_name} com={data.com_name}")
    return model


async def update_model(db: AsyncSession, model_id: str, data: ModelManageUpdate) -> ModelManageInfo | None:
    """更新模型（部分更新，只修改传入的字段）；模型不存在返回 None

    传入 provider_id 时同步回填运营商名称/地址/密钥，保证模型与提供商配置一致。
    """
    update_data = data.model_dump(exclude_unset=True)
    if not update_data:
        return await get_model_by_id(db, model_id)

    provider_id = update_data.get("provider_id")
    if provider_id:
        com_name, com_url, api_key = await _resolve_provider_config(db, provider_id)
        update_data["com_name"] = com_name
        update_data["com_url"] = com_url
        update_data["api_key"] = api_key

    price_fields = {"input_price_per_1m", "output_price_per_1m"}
    if price_fields & update_data.keys():
        for field in price_fields:
            if field in update_data:
                update_data[field] = _to_decimal(update_data[field])
        update_data["price_source"] = "manual"
        update_data["price_updated_at"] = datetime.now()
    if "price_currency" in update_data and not update_data["price_currency"]:
        update_data["price_currency"] = "USD"

    update_data["updated_at"] = datetime.now()
    stmt = (
        update(ModelManageInfo)
        .where(ModelManageInfo.ai_model_id == model_id)
        .values(**update_data)
    )
    result = await db.execute(stmt)
    await db.commit()

    if result.rowcount == 0:
        logger.warning(f"更新模型失败（不存在）: id={model_id}")
        return None

    logger.info(f"更新模型: id={model_id} fields={list(update_data.keys())}")
    return await get_model_by_id(db, model_id)


async def delete_model(db: AsyncSession, model_id: str) -> bool:
    """删除模型，返回是否删除成功"""
    model = await get_model_by_id(db, model_id)
    if not model:
        return False
    await db.delete(model)
    await db.commit()
    logger.info(f"删除模型: id={model_id} name={model.ai_model_name}")
    return True


async def get_model_count(db: AsyncSession) -> int:
    """获取模型总数"""
    stmt = select(func.count(ModelManageInfo.ai_model_id))
    result = await db.execute(stmt)
    return result.scalar() or 0
