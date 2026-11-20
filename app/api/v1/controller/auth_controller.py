"""管理端登录接口

使用环境变量配置的管理员账号换取 JWT，不依赖业务用户表，方便独立部署。
账号可来自旧版 ``ADMIN_USERNAME`` / ``ADMIN_PASSWORD`` 或 ``ADMIN_USERS``
多账号配置（详见 ``app.utils.admin_auth``），每个账号绑定一个管理角色。
"""
import logging
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.utils.admin_auth import authenticate, create_access_token, verify_admin_token
from app.utils.rbac import AdminIdentity
from app.utils.response import ResponseFactory

logger = logging.getLogger(__name__)

router = APIRouter()


class LoginRequest(BaseModel):
    username: str = Field(..., max_length=64)
    password: str = Field(..., max_length=256)


@router.post("/login")
async def login(body: LoginRequest) -> dict[str, Any]:
    """管理员登录：账号 + 密码 → JWT"""
    username = body.username.strip()
    if not username or not body.password:
        return ResponseFactory.bad_request(message="账号和密码不能为空")

    account = authenticate(username, body.password)
    if account is None:
        logger.warning("[AdminAuth] 登录失败: username=%s", username)
        return ResponseFactory.ok(data={"success": False, "message": "账号或密码错误"})

    identity = AdminIdentity(username=account.username, role=account.role)
    logger.info(
        "[AdminAuth] 登录成功: username=%s role=%s",
        account.username, account.role.value,
    )
    return ResponseFactory.ok(
        data={
            "success": True,
            "message": "登录成功",
            "token": create_access_token(account),
            "user": identity.to_public_dict(),
        }
    )


@router.get("/me")
async def me(identity: AdminIdentity = Depends(verify_admin_token)):
    """当前登录身份 + 角色 + 权限列表（前端据此显隐操作）"""
    return ResponseFactory.ok(data=identity.to_public_dict(), message="查询成功")
