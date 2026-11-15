"""管理端 JWT 鉴权

管理类 API 通过 ``Authorization: Bearer <jwt>`` 校验身份。
JWT 由 ``POST /api/v1/auth/login`` 使用环境变量管理员账号签发：

- ``ADMIN_USERNAME`` / ``ADMIN_PASSWORD``：管理员账号密码
- ``JWT_SECRET_KEY``：JWT 签名密钥（生产环境必须设置）

开源版为单管理员模型；如需多管理员/角色权限，可在企业版中扩展。
"""
import logging
import os

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

logger = logging.getLogger(__name__)

SECRET_KEY = os.getenv("JWT_SECRET_KEY", "dev-only-change-me")
ALGORITHM = "HS256"

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin")

if not os.getenv("JWT_SECRET_KEY"):
    logger.warning("JWT_SECRET_KEY 未设置，使用开发默认值；生产环境请务必注入随机密钥")
if ADMIN_PASSWORD.strip().lower() in ("", "admin", "change-me"):
    logger.warning(
        "ADMIN_PASSWORD 为空或仍是默认值，管理台等于无保护；"
        "公开部署前请务必修改 ADMIN_USERNAME / ADMIN_PASSWORD"
    )

security = HTTPBearer(auto_error=False)


def decode_token(token: str) -> dict | None:
    """解码 JWT，失败返回 None"""
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError as e:
        logger.warning("JWT 解码失败: %s", e)
        return None


def verify_admin_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> str:
    """校验 Bearer JWT，通过则返回管理员标识，失败抛 401。

    用法：
        @router.get("/list")
        async def list_models(admin: str = Depends(verify_admin_token)):
            ...
    """
    if credentials is None:
        raise HTTPException(status_code=401, detail="未提供认证 Token，请先登录")

    payload = decode_token(credentials.credentials)
    if payload is None:
        raise HTTPException(status_code=401, detail="Token 无效或已过期")

    user_id = payload.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Token 缺少用户标识")

    return user_id
