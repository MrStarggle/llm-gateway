"""管理端登录接口

使用环境变量配置的管理员账号（ADMIN_USERNAME / ADMIN_PASSWORD）换取 JWT，
不依赖任何业务用户表，方便独立部署。
"""
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter
from jose import jwt
from pydantic import BaseModel

from app.utils.admin_auth import ADMIN_PASSWORD, ADMIN_USERNAME, ALGORITHM, SECRET_KEY
from app.utils.response import ResponseFactory

logger = logging.getLogger(__name__)

router = APIRouter()

ACCESS_TOKEN_EXPIRE_HOURS = 24 * 7  # 7 天


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/login")
async def login(body: LoginRequest) -> dict[str, Any]:
    """管理员登录：账号 + 密码 → JWT"""
    username = body.username.strip()
    if not username or not body.password:
        return ResponseFactory.bad_request(message="账号和密码不能为空")

    # compare_digest 两边都会执行，避免通过耗时差异推测账号/密码
    username_ok = secrets.compare_digest(username, ADMIN_USERNAME)
    password_ok = secrets.compare_digest(body.password, ADMIN_PASSWORD)
    if not (username_ok and password_ok):
        logger.warning("[AdminAuth] 登录失败: username=%s", username)
        return ResponseFactory.ok(data={"success": False, "message": "账号或密码错误"})

    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {
            "user_id": "admin",
            "user_name": ADMIN_USERNAME,
            "iat": now,
            "exp": now + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS),
        },
        SECRET_KEY,
        algorithm=ALGORITHM,
    )

    logger.info("[AdminAuth] 登录成功: username=%s", ADMIN_USERNAME)
    return ResponseFactory.ok(
        data={
            "success": True,
            "message": "登录成功",
            "token": token,
            "user": {
                "userId": "admin",
                "userName": ADMIN_USERNAME,
            },
        }
    )
