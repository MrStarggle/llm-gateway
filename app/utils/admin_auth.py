"""JWT 鉴权依赖（与 StarggleCom 共享密钥和用户表）

管理类 API 通过 Authorization: Bearer <jwt> 校验身份。
JWT 由登录接口 /api/v1/auth/login 签发，或复用 StarggleCom 已登录的 token。
"""
import os
import logging

from fastapi import HTTPException, Request, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt

logger = logging.getLogger(__name__)

# 与 StarggleCom 共享同一个 JWT 密钥
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "stargglechat_jwt_secret_2026")
ALGORITHM = "HS256"

security = HTTPBearer(auto_error=False)


def decode_token(token: str) -> dict | None:
    """解码 JWT token，失败返回 None"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError as e:
        logger.warning(f"JWT 解码失败: {e}")
        return None


def verify_admin_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> str:
    """校验 Bearer JWT，通过则返回 user_id，失败抛 401。

    用法：
        @router.get("/list")
        async def list_models(user_id: str = Depends(verify_admin_token)):
            ...
    """
    if credentials is None:
        raise HTTPException(status_code=401, detail="未提供认证 Token，请先登录")

    token = credentials.credentials
    payload = decode_token(token)
    if payload is None:
        raise HTTPException(status_code=401, detail="Token 无效或已过期")

    user_id = payload.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Token 缺少用户标识")

    return user_id
