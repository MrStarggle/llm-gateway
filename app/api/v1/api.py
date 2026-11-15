from fastapi import APIRouter
from app.api.v1.controller import (
    model_manage_controller,
    call_manage_controller,
    auth_controller,
    project_manage_controller,
    health_manage_controller,
)


# 创建主路由器
api_router = APIRouter()

# 管理端登录（环境变量管理员账号）
api_router.include_router(
    auth_controller.router,
    prefix="/auth",
    tags=["管理端登录"]
)

# 模型管理
api_router.include_router(
    model_manage_controller.router,
    prefix="/model-manage",
    tags=["模型管理"]
)

# 项目与 API Token 管理
api_router.include_router(
    project_manage_controller.router,
    prefix="/project-manage",
    tags=["项目管理"]
)

# 渠道健康与路由
api_router.include_router(
    health_manage_controller.router,
    prefix="/health-manage",
    tags=["渠道健康"]
)

# LLM 调用管理
api_router.include_router(
    call_manage_controller.router,
    prefix="/call-manage",
    tags=["LLM调用管理"]
)

