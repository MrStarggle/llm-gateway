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

# 与 StarggleCom 共享同一个 JWT 密钥。
# 注意：未设置 JWT_SECRET_KEY 时会使用代码内默认值（仅限本地开发），
# 生产环境必须通过环境变量注入随机密钥，否则任何拿到源码的人可伪造 token。
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "stargglechat_jwt_secret_2026")
if not os.getenv("JWT_SECRET_KEY"):
    logger.critical(
        "未设置 JWT_SECRET_KEY，正在使用代码内默认密钥！"
        "生产环境任何用户可伪造 token，请立即通过环境变量注入随机密钥。"
    )
ALGORITHM = "HS256"

# 管理员白名单（逗号分隔的 user_id）。
# 设置后，/user-manage 等管理端点仅允许白名单内用户访问；
# 未设置时回落为"任何有效登录用户"，仅建议本地开发使用。
ADMIN_USER_IDS = {
    uid.strip() for uid in os.getenv("ADMIN_USER_IDS", "").split(",") if uid.strip()
}
if not ADMIN_USER_IDS:
    logger.critical(
        "未设置 ADMIN_USER_IDS，管理端接口对全部登录用户开放！"
        "生产环境请设置管理员用户ID白名单（逗号分隔）。"
    )

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


async def require_admin_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> str:
    """管理端点专用依赖：在 verify_admin_token 基础上校验 ADMIN_USER_IDS 白名单。

    白名单为空时拒绝所有管理请求（fail-closed），避免“任何登录用户都是管理员”。
    生产环境必须通过环境变量配置管理员 user_id。
    """
    user_id = verify_admin_token(request, credentials)
    if user_id not in ADMIN_USER_IDS:
        logger.warning("非管理员访问管理端点被拒绝: user_id=%s", user_id)
        raise HTTPException(status_code=403, detail="无管理员权限")
    return user_id
