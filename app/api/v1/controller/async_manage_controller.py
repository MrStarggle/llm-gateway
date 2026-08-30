"""异步LLM总控 控制器

13 路异步LLM请求（async1..async13）的路由/参数配置管理：
- GET  /list        全量列表（固定 13 行，按 purpose 排序）
- GET  /{purpose}   单路详情
- PUT  /{purpose}   更新单路配置（部分更新）
"""
import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.database import get_db
from app.schemas.async_manage import AsyncManageUpdate
from app.services import async_manage_service
from app.utils.response import ResponseFactory
from app.utils.admin_auth import verify_admin_token

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(verify_admin_token)])


@router.get("/list")
async def list_configs(db: AsyncSession = Depends(get_db)):
    """获取全部异步LLM总控配置（固定 13 行）"""
    configs = await async_manage_service.get_config_list(db)
    return ResponseFactory.ok(
        data={"list": configs, "total": len(configs)},
        message="查询成功",
    )


@router.get("/{purpose}")
async def get_config(purpose: str, db: AsyncSession = Depends(get_db)):
    """按 purpose 获取单路配置详情"""
    config = await async_manage_service.get_config_by_purpose(db, purpose)
    if not config:
        return ResponseFactory.not_found(message="配置不存在")
    return ResponseFactory.ok(data=config, message="查询成功")


@router.put("/{purpose}")
async def update_config(purpose: str, data: AsyncManageUpdate, db: AsyncSession = Depends(get_db)):
    """更新单路配置（部分更新）—— 服务层为单一真实来源，不存在则返回 404"""
    config = await async_manage_service.update_config(db, purpose, data)
    if not config:
        return ResponseFactory.not_found(message="配置不存在")
    return ResponseFactory.ok(data=config, message="更新成功")
