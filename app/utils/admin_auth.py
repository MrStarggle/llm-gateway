"""管理端 JWT 鉴权与角色校验。

管理类 API 通过 ``Authorization: Bearer <jwt>`` 校验身份，JWT 由
``POST /api/v1/auth/login`` 使用环境变量中的管理员账号签发。

账号来源（两种可同时使用）：

1. 旧版单管理员：``ADMIN_USERNAME`` / ``ADMIN_PASSWORD``，固定为 admin 角色。
2. 多账号 + 角色：``ADMIN_USERS``，JSON 对象::

       ADMIN_USERS={"alice": {"password": "s3cret", "role": "admin"},
                    "bob":   {"password": "s3cret", "role": "developer"},
                    "carol": "s3cret"}

   值为字符串时等价于只提供密码，角色按最小权限记为 viewer；角色名大小写
   不敏感，可选 admin / operator / developer / viewer。``ADMIN_USERS`` 非空但
   不是合法 JSON 时服务会启动失败，避免静默退回默认 admin/admin。

JWT 有效期 7 天，载荷包含 ``role``；但每次请求都会以当前账号表为准重新解析
角色，因此在 env 中调整角色或移除账号后，重启服务即刻生效。

``JWT_SECRET_KEY`` 为 JWT 签名密钥（生产环境必须设置）。
"""
import json
import logging
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from app.utils.rbac import (
    ROLE_LABELS,
    AdminIdentity,
    Role,
    has_permission,
    parse_role,
)

logger = logging.getLogger(__name__)

SECRET_KEY = os.getenv("JWT_SECRET_KEY", "dev-only-change-me")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24 * 7  # 7 天

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin")
ADMIN_USERS_JSON = os.getenv("ADMIN_USERS", "")

# 明显不安全的密码，启动时给出告警
_WEAK_PASSWORDS = {"", "admin", "change-me", "password", "123456"}

security = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AdminAccount:
    """env 中配置的管理员账号"""

    username: str
    password: str
    role: Role


def build_accounts(
    admin_username: str,
    admin_password: str,
    users_json: str = "",
) -> dict[str, AdminAccount]:
    """构建账号表：``ADMIN_USERS`` 优先，旧版单管理员账号做兜底。"""
    accounts: dict[str, AdminAccount] = {}

    if users_json and users_json.strip():
        try:
            raw = json.loads(users_json)
        except json.JSONDecodeError as e:
            # 鉴权配置写错时宁可启动失败，也不要静默退回默认 admin/admin
            raise ValueError(f"ADMIN_USERS 不是合法 JSON: {e}") from e
        if not isinstance(raw, dict):
            raise ValueError("ADMIN_USERS 必须是 {username: {password, role}} 对象")

        for name, spec in raw.items():
            username = str(name).strip()
            if not username:
                continue

            role_raw: str | None = None
            if isinstance(spec, str):
                password = spec
            elif isinstance(spec, dict):
                password = str(spec.get("password") or "")
                role_raw = spec.get("role")
            else:
                logger.warning("ADMIN_USERS 中 %s 的配置格式无效，已忽略", username)
                continue

            if not password:
                logger.warning("ADMIN_USERS 中 %s 未配置密码，已忽略", username)
                continue

            role = parse_role(role_raw)
            if role is None:
                if role_raw:
                    logger.warning(
                        "ADMIN_USERS 中 %s 的角色 %r 无效，按只读角色处理",
                        username, role_raw,
                    )
                role = Role.VIEWER
            accounts[username] = AdminAccount(username, password, role)

    legacy_username = admin_username.strip()
    if legacy_username and legacy_username not in accounts:
        accounts[legacy_username] = AdminAccount(
            legacy_username, admin_password, Role.ADMIN,
        )

    for account in accounts.values():
        if account.password.strip().lower() in _WEAK_PASSWORDS:
            logger.warning(
                "账号 %s（%s）为空密码或默认密码，公开部署前请务必修改",
                account.username, ROLE_LABELS.get(account.role, account.role.value),
            )

    return accounts


ACCOUNTS: dict[str, AdminAccount] = build_accounts(
    ADMIN_USERNAME, ADMIN_PASSWORD, ADMIN_USERS_JSON,
)

if not os.getenv("JWT_SECRET_KEY"):
    logger.warning("JWT_SECRET_KEY 未设置，使用开发默认值；生产环境请务必注入随机密钥")


def authenticate(username: str, password: str) -> AdminAccount | None:
    """校验账号密码，成功返回账号（含角色），失败返回 None"""
    account = ACCOUNTS.get(username.strip())
    if account is None:
        # 账号不存在时也执行一次比较，避免通过耗时差异枚举账号
        secrets.compare_digest(password.encode("utf-8"), b"dummy-password")
        return None
    # compare_digest 对非 ASCII 的 str 会抛 TypeError，统一按 UTF-8 字节比较
    if not secrets.compare_digest(
        password.encode("utf-8"), account.password.encode("utf-8"),
    ):
        return None
    return account


def create_access_token(account: AdminAccount) -> str:
    """签发 JWT，载荷带 username 与 role"""
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "user_id": account.username,
            "user_name": account.username,
            "role": account.role.value,
            "iat": now,
            "exp": now + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS),
        },
        SECRET_KEY,
        algorithm=ALGORITHM,
    )


def decode_token(token: str) -> dict | None:
    """解码 JWT，失败返回 None"""
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError as e:
        logger.warning("JWT 解码失败: %s", e)
        return None


def verify_admin_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> AdminIdentity:
    """校验 Bearer JWT，通过则返回当前管理员身份，失败抛 401。

    角色以账号表为准（而非 Token 里的 role），这样在 env 中降级或移除账号
    后无需等待 Token 过期。旧版单管理员 Token（无 role 字段）只要用户名仍
    在账号表中即可继续使用。

    用法：
        @router.get("/list")
        async def list_models(admin: AdminIdentity = Depends(verify_admin_token)):
            ...
    """
    if credentials is None:
        raise HTTPException(status_code=401, detail="未提供认证 Token，请先登录")

    payload = decode_token(credentials.credentials)
    if payload is None:
        raise HTTPException(status_code=401, detail="Token 无效或已过期")

    username = str(
        payload.get("user_id") or payload.get("user_name") or "",
    ).strip()
    if not username:
        raise HTTPException(status_code=401, detail="Token 缺少用户标识")

    account = ACCOUNTS.get(username)
    if account is None:
        raise HTTPException(status_code=401, detail="账号不存在或已被移除，请重新登录")

    return AdminIdentity(username=account.username, role=account.role)


def require_permission(permission: str):
    """依赖工厂：要求当前管理员具备指定权限，否则返回 403。

    用法：
        @router.post("/", dependencies=[Depends(require_permission(Perm.MODELS_WRITE))])
    """

    def checker(identity: AdminIdentity = Depends(verify_admin_token)) -> AdminIdentity:
        if not has_permission(identity.role, permission):
            label = ROLE_LABELS.get(identity.role, identity.role.value)
            raise HTTPException(
                status_code=403,
                detail=f"当前角色（{label}）无权执行该操作",
            )
        return identity

    return checker
