"""模型管理 业务逻辑层"""
import logging
from datetime import datetime

from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.model_manage_info import ModelManageInfo
from app.schemas.model_manage import ModelManageCreate, ModelManageUpdate, ModelManageQuery
from app.utils.SnowflakeIDGenerator import snowflake_id_generator

logger = logging.getLogger(__name__)


async def get_model_list(
        db: AsyncSession,
        query: ModelManageQuery | None = None,
) -> list[ModelManageInfo]:
    """获取模型列表，支持多条件筛选"""
    stmt = select(ModelManageInfo)

    if query:
        if query.com_name:
            stmt = stmt.where(ModelManageInfo.com_name.like(f"%{query.com_name}%"))
        if query.ai_model_name:
            stmt = stmt.where(ModelManageInfo.ai_model_name.like(f"%{query.ai_model_name}%"))
        if query.is_using:
            stmt = stmt.where(ModelManageInfo.is_using == query.is_using)
        if query.is_base:
            stmt = stmt.where(ModelManageInfo.is_base == query.is_base)
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


async def create_model(db: AsyncSession, data: ModelManageCreate) -> ModelManageInfo:
    """新增模型"""
    model_id = snowflake_id_generator.next_id_str()
    model = ModelManageInfo(
        ai_model_id=model_id,
        ai_model_name=data.ai_model_name,
        com_name=data.com_name,
        com_url=data.com_url,
        api_key=data.api_key,
        ai_model_type=data.ai_model_type,
        is_using=data.is_using,
        is_think=data.is_think,
        is_stream=data.is_stream,
        is_base=data.is_base,
        extra_config=data.extra_config,
        remarks=data.remarks,
    )
    db.add(model)
    await db.commit()
    await db.refresh(model)
    logger.info(f"新增模型: id={model_id} name={data.ai_model_name} com={data.com_name}")
    return model


async def update_model(db: AsyncSession, model_id: str, data: ModelManageUpdate) -> ModelManageInfo | None:
    """更新模型（部分更新，只修改传入的字段）；模型不存在返回 None"""
    update_data = data.model_dump(exclude_unset=True)
    if not update_data:
        return await get_model_by_id(db, model_id)

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
