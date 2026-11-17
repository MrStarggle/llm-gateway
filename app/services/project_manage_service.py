"""项目与 API Token 业务逻辑

- 项目 CRUD（只停用，不物理删除）
- Token 生成/校验/吊销/轮换，只保存 SHA-256
- 项目级配额检查与每日用量原子累计
"""
import hashlib
import json
import logging
import os
import secrets
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from fnmatch import fnmatchcase

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project_info import ProjectInfo
from app.models.project_token_info import ProjectTokenInfo
from app.models.project_usage_daily import ProjectUsageDaily
from app.services import usage_manage_service
from app.utils.SnowflakeIDGenerator import get_snowflake_id

logger = logging.getLogger(__name__)

TOKEN_PREFIX = "sk-gw-"
TOKEN_TOUCH_INTERVAL = timedelta(minutes=5)
GATEWAY_TOKEN_REQUIRED = os.getenv("GATEWAY_TOKEN_REQUIRED", "0").strip().lower() in (
    "1", "true", "yes", "on",
)

_ZERO = Decimal("0")
_COST_QUANT = Decimal("0.00000001")


class GatewayAuthError(Exception):
    """网关 Token 鉴权失败."""

    def __init__(self, message: str, *, status_code: int = 401, code: str = "invalid_api_key"):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code


class ProjectQuotaError(Exception):
    """项目配额超限."""

    def __init__(self, message: str, *, code: str = "project_quota_exceeded"):
        super().__init__(message)
        self.message = message
        self.code = code


@dataclass(frozen=True)
class GatewayIdentity:
    token_id: str
    project: ProjectInfo
    allowed_models: tuple[str, ...]
    last_used_at: datetime | None


@dataclass(frozen=True)
class ProjectUsageSnapshot:
    today_calls: int
    today_tokens: int
    today_cost: Decimal
    month_calls: int
    month_tokens: int
    month_cost: Decimal

    def to_dict(self) -> dict:
        return {
            "todayCalls": self.today_calls,
            "todayTokens": self.today_tokens,
            "todayCost": float(self.today_cost or 0),
            "monthCalls": self.month_calls,
            "monthTokens": self.month_tokens,
            "monthCost": float(self.month_cost or 0),
        }


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _generate_token() -> tuple[str, str, str, str]:
    raw = f"{TOKEN_PREFIX}{secrets.token_urlsafe(32)}"
    return raw, _hash_token(raw), raw[:12], raw[-4:]


def _to_decimal(value) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def _utcnow() -> datetime:
    """当前 UTC 时间（naive，数据库列不带时区）."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _normalize_dt(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _parse_allowed_models(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ()
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        logger.warning("项目 Token allowed_models 不是合法 JSON，按不限制处理")
        return ()
    if not isinstance(value, list):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())


def _serialize_allowed_models(patterns: list[str] | None) -> str | None:
    if not patterns:
        return None
    return json.dumps(patterns, ensure_ascii=False)


def _empty_usage() -> dict:
    return {"calls": 0, "tokens": 0, "cost": _ZERO}


def _usage_to_dict(value: dict) -> dict:
    return {
        "calls": int(value.get("calls") or 0),
        "tokens": int(value.get("tokens") or 0),
        "cost": float(value.get("cost") or 0),
    }


def project_to_dict(
        project: ProjectInfo,
        *,
        today: dict | None = None,
        month: dict | None = None,
        token_count: int = 0,
) -> dict:
    return {
        "projectId": project.project_id,
        "projectName": project.project_name,
        "status": project.status,
        "dailyCallLimit": project.daily_call_limit,
        "monthlyCallLimit": project.monthly_call_limit,
        "dailyTokenLimit": project.daily_token_limit,
        "monthlyTokenLimit": project.monthly_token_limit,
        "dailyCostLimit": None if project.daily_cost_limit is None else float(project.daily_cost_limit),
        "monthlyCostLimit": None if project.monthly_cost_limit is None else float(project.monthly_cost_limit),
        "costCurrency": project.cost_currency,
        "today": _usage_to_dict(today or _empty_usage()),
        "month": _usage_to_dict(month or _empty_usage()),
        "tokenCount": int(token_count or 0),
        "remarks": project.remarks,
        "createdAt": project.created_at.isoformat() if project.created_at else None,
        "updatedAt": project.updated_at.isoformat() if project.updated_at else None,
    }


def token_to_dict(token: ProjectTokenInfo) -> dict:
    """公开字段，绝不返回 token_hash."""
    return {
        "tokenId": token.token_id,
        "projectId": token.project_id,
        "name": token.name,
        "tokenPrefix": token.token_prefix,
        "tokenSuffix": token.token_suffix,
        "allowedModels": list(_parse_allowed_models(token.allowed_models)),
        "expiresAt": token.expires_at.isoformat() if token.expires_at else None,
        "status": token.status,
        "lastUsedAt": token.last_used_at.isoformat() if token.last_used_at else None,
        "remarks": token.remarks,
        "createdAt": token.created_at.isoformat() if token.created_at else None,
    }


# ==================== 项目 CRUD ====================


async def list_projects(db: AsyncSession, keyword: str = "") -> list[dict]:
    stmt = select(ProjectInfo).order_by(ProjectInfo.created_at.desc(), ProjectInfo.project_id.desc())
    if keyword:
        stmt = stmt.where(ProjectInfo.project_name.like(f"%{keyword}%"))
    projects = list((await db.execute(stmt)).scalars().all())
    if not projects:
        return []

    ids = [p.project_id for p in projects]
    today = date.today()
    month_start = today.replace(day=1)

    usage_rows = (await db.execute(
        select(ProjectUsageDaily).where(
            ProjectUsageDaily.project_id.in_(ids),
            ProjectUsageDaily.usage_date >= month_start,
        )
    )).scalars().all()

    usage_map: dict[str, dict[str, dict]] = {
        pid: {"today": _empty_usage(), "month": _empty_usage()} for pid in ids
    }
    for row in usage_rows:
        bucket = usage_map.setdefault(row.project_id, {"today": _empty_usage(), "month": _empty_usage()})
        bucket["month"]["calls"] += int(row.call_count or 0)
        bucket["month"]["tokens"] += int(row.total_tokens or 0)
        bucket["month"]["cost"] += Decimal(row.cost_amount or 0)
        if row.usage_date == today:
            bucket["today"]["calls"] += int(row.call_count or 0)
            bucket["today"]["tokens"] += int(row.total_tokens or 0)
            bucket["today"]["cost"] += Decimal(row.cost_amount or 0)

    token_counts = {
        pid: int(count or 0)
        for pid, count in (await db.execute(
            select(ProjectTokenInfo.project_id, func.count(ProjectTokenInfo.token_id))
            .where(ProjectTokenInfo.project_id.in_(ids), ProjectTokenInfo.status == "active")
            .group_by(ProjectTokenInfo.project_id)
        )).all()
    }

    return [
        project_to_dict(
            p,
            today=usage_map.get(p.project_id, {}).get("today"),
            month=usage_map.get(p.project_id, {}).get("month"),
            token_count=token_counts.get(p.project_id, 0),
        )
        for p in projects
    ]


async def get_project(db: AsyncSession, project_id: str) -> ProjectInfo | None:
    return await db.get(ProjectInfo, project_id)


async def create_project(db: AsyncSession, data) -> ProjectInfo:
    name = (data.project_name or "").strip()
    if not name:
        raise ValueError("项目名称不能为空")

    project = ProjectInfo(
        project_id=get_snowflake_id(),
        project_name=name,
        status=data.status or "active",
        daily_call_limit=data.daily_call_limit,
        monthly_call_limit=data.monthly_call_limit,
        daily_token_limit=data.daily_token_limit,
        monthly_token_limit=data.monthly_token_limit,
        daily_cost_limit=_to_decimal(data.daily_cost_limit),
        monthly_cost_limit=_to_decimal(data.monthly_cost_limit),
        cost_currency=data.cost_currency or "USD",
        remarks=data.remarks,
    )
    try:
        db.add(project)
        await db.commit()
        await db.refresh(project)
    except IntegrityError:
        await db.rollback()
        raise ValueError("项目名称已存在")
    return project


async def update_project(db: AsyncSession, project_id: str, data) -> ProjectInfo | None:
    project = await db.get(ProjectInfo, project_id)
    if project is None:
        return None

    values = data.model_dump(exclude_unset=True)
    if "project_name" in values:
        name = (values["project_name"] or "").strip()
        if not name:
            raise ValueError("项目名称不能为空")
        values["project_name"] = name
    if "cost_currency" in values:
        values["cost_currency"] = values["cost_currency"] or "USD"
    for field in ("daily_cost_limit", "monthly_cost_limit"):
        if field in values:
            values[field] = _to_decimal(values[field])

    for field, value in values.items():
        setattr(project, field, value)

    try:
        await db.commit()
        await db.refresh(project)
    except IntegrityError:
        await db.rollback()
        raise ValueError("项目名称已存在")
    return project


# ==================== Token ====================


async def create_token(
        db: AsyncSession,
        project_id: str,
        data,
) -> tuple[ProjectTokenInfo, str]:
    project = await db.get(ProjectInfo, project_id)
    if project is None:
        raise ValueError("项目不存在")

    name = (data.name or "").strip()
    if not name:
        raise ValueError("Token 名称不能为空")
    expires_at = _normalize_dt(data.expires_at)
    if expires_at is not None and expires_at <= _utcnow():
        raise ValueError("过期时间必须晚于当前时间")

    raw, token_hash, prefix, suffix = _generate_token()
    token = ProjectTokenInfo(
        token_id=get_snowflake_id(),
        project_id=project_id,
        name=name,
        token_hash=token_hash,
        token_prefix=prefix,
        token_suffix=suffix,
        allowed_models=_serialize_allowed_models(data.allowed_models),
        expires_at=expires_at,
        status="active",
        remarks=data.remarks,
    )
    try:
        db.add(token)
        await db.commit()
        await db.refresh(token)
    except IntegrityError:
        await db.rollback()
        raise ValueError("同一项目下已存在同名 Token")
    return token, raw


async def list_tokens(db: AsyncSession, project_id: str) -> list[dict]:
    rows = (await db.execute(
        select(ProjectTokenInfo)
        .where(ProjectTokenInfo.project_id == project_id)
        .order_by(ProjectTokenInfo.created_at.desc(), ProjectTokenInfo.token_id.desc())
    )).scalars().all()
    return [token_to_dict(row) for row in rows]


async def revoke_token(db: AsyncSession, token_id: str) -> ProjectTokenInfo | None:
    token = await db.get(ProjectTokenInfo, token_id)
    if token is None:
        return None
    if token.status != "revoked":
        token.status = "revoked"
        await db.commit()
        await db.refresh(token)
    return token


async def rotate_token(
        db: AsyncSession,
        token_id: str,
        data=None,
) -> tuple[ProjectTokenInfo, str] | None:
    """吊销旧密钥并在同一行换发新密钥（token_id 不变，历史归属不断）."""
    token = await db.get(ProjectTokenInfo, token_id)
    if token is None:
        return None
    if token.status != "active":
        raise ValueError("Token 已吊销，请新建 Token")

    if data is not None:
        if data.name is not None:
            name = data.name.strip()
            if not name:
                raise ValueError("Token 名称不能为空")
            token.name = name
        if data.expires_at is not None:
            expires_at = _normalize_dt(data.expires_at)
            if expires_at is not None and expires_at <= _utcnow():
                raise ValueError("过期时间必须晚于当前时间")
            token.expires_at = expires_at
        if data.remarks is not None:
            token.remarks = data.remarks

    raw, token_hash, prefix, suffix = _generate_token()
    token.token_hash = token_hash
    token.token_prefix = prefix
    token.token_suffix = suffix
    token.last_used_at = None
    token.status = "active"

    try:
        await db.commit()
        await db.refresh(token)
    except IntegrityError:
        await db.rollback()
        raise ValueError("同一项目下已存在同名 Token")
    return token, raw


async def resolve_gateway_token(db: AsyncSession, raw: str) -> GatewayIdentity:
    """校验 sk-gw Token，返回项目身份；失败抛 GatewayAuthError."""
    token_hash = _hash_token((raw or "").strip())
    token = (await db.execute(
        select(ProjectTokenInfo).where(ProjectTokenInfo.token_hash == token_hash)
    )).scalar_one_or_none()
    if token is None:
        raise GatewayAuthError("Invalid API key", code="invalid_api_key")
    if token.status != "active":
        raise GatewayAuthError("API key has been revoked", code="api_key_revoked")
    if token.expires_at is not None and token.expires_at <= _utcnow():
        raise GatewayAuthError("API key has expired", code="api_key_expired")

    project = await db.get(ProjectInfo, token.project_id)
    if project is None:
        raise GatewayAuthError("Project not found", code="project_not_found")
    if project.status != "active":
        raise GatewayAuthError("Project is disabled", status_code=403, code="project_disabled")

    return GatewayIdentity(
        token_id=token.token_id,
        project=project,
        allowed_models=_parse_allowed_models(token.allowed_models),
        last_used_at=token.last_used_at,
    )


def model_allowed(identity: GatewayIdentity, model_name: str) -> bool:
    patterns = identity.allowed_models
    if not patterns:
        return True
    name = (model_name or "").strip()
    if not name:
        return False
    return any(fnmatchcase(name, pattern) for pattern in patterns)


def filter_allowed_models(identity: GatewayIdentity, models: list) -> list:
    if not identity.allowed_models:
        return list(models)
    return [m for m in models if model_allowed(identity, m.ai_model_name)]


# ==================== 配额 ====================


async def get_usage_snapshot(db: AsyncSession, project_id: str) -> ProjectUsageSnapshot:
    today = date.today()
    month_start = today.replace(day=1)
    rows = (await db.execute(
        select(ProjectUsageDaily).where(
            ProjectUsageDaily.project_id == project_id,
            ProjectUsageDaily.usage_date >= month_start,
        )
    )).scalars().all()

    month_calls = month_tokens = 0
    month_cost = _ZERO
    today_calls = today_tokens = 0
    today_cost = _ZERO
    for row in rows:
        calls = int(row.call_count or 0)
        tokens = int(row.total_tokens or 0)
        cost = Decimal(row.cost_amount or 0)
        month_calls += calls
        month_tokens += tokens
        month_cost += cost
        if row.usage_date == today:
            today_calls += calls
            today_tokens += tokens
            today_cost += cost

    return ProjectUsageSnapshot(
        today_calls=today_calls,
        today_tokens=today_tokens,
        today_cost=today_cost,
        month_calls=month_calls,
        month_tokens=month_tokens,
        month_cost=month_cost,
    )


def check_project_quota(project: ProjectInfo, snapshot: ProjectUsageSnapshot) -> None:
    """超限抛 ProjectQuotaError；NULL=不限，0=禁止."""
    checks = (
        ("Daily call quota exceeded", "daily_call_quota_exceeded",
         project.daily_call_limit, snapshot.today_calls),
        ("Monthly call quota exceeded", "monthly_call_quota_exceeded",
         project.monthly_call_limit, snapshot.month_calls),
        ("Daily token quota exceeded", "daily_token_quota_exceeded",
         project.daily_token_limit, snapshot.today_tokens),
        ("Monthly token quota exceeded", "monthly_token_quota_exceeded",
         project.monthly_token_limit, snapshot.month_tokens),
        ("Daily cost quota exceeded", "daily_cost_quota_exceeded",
         project.daily_cost_limit, snapshot.today_cost),
        ("Monthly cost quota exceeded", "monthly_cost_quota_exceeded",
         project.monthly_cost_limit, snapshot.month_cost),
    )
    for label, code, limit, used in checks:
        if limit is None:
            continue
        if Decimal(str(used)) >= Decimal(str(limit)):
            raise ProjectQuotaError(f"{label} ({used}/{limit})", code=code)


async def increment_project_usage(
        db: AsyncSession,
        project_id: str,
        *,
        project_currency: str = "USD",
        calls: int = 1,
        tokens: int = 0,
        cost=None,
        cost_currency: str | None = None,
) -> None:
    """成功请求后原子累计项目当日用量.

    成本只累计与项目币种一致的记录；其他币种不计入项目成本配额，避免隐式汇率换算。
    """
    today = date.today()
    cost_value = _ZERO
    if cost is not None:
        if (cost_currency or "").upper() == (project_currency or "USD").upper():
            cost_value = Decimal(str(cost)).quantize(_COST_QUANT)
        else:
            logger.info(
                "项目成本币种不一致，跳过成本累计: project=%s project_currency=%s record_currency=%s",
                project_id, project_currency, cost_currency,
            )

    calls = max(0, int(calls or 0))
    tokens = max(0, int(tokens or 0))
    where = (
        ProjectUsageDaily.project_id == project_id,
        ProjectUsageDaily.usage_date == today,
    )
    try:
        result = await db.execute(
            update(ProjectUsageDaily).where(*where).values(
                call_count=ProjectUsageDaily.call_count + calls,
                total_tokens=ProjectUsageDaily.total_tokens + tokens,
                cost_amount=ProjectUsageDaily.cost_amount + cost_value,
            )
        )
        if result.rowcount == 0:
            db.add(ProjectUsageDaily(
                project_id=project_id,
                usage_date=today,
                call_count=calls,
                total_tokens=tokens,
                cost_amount=cost_value,
            ))
        await db.commit()
    except IntegrityError:
        await db.rollback()
        try:
            await db.execute(
                update(ProjectUsageDaily).where(*where).values(
                    call_count=ProjectUsageDaily.call_count + calls,
                    total_tokens=ProjectUsageDaily.total_tokens + tokens,
                    cost_amount=ProjectUsageDaily.cost_amount + cost_value,
                )
            )
            await db.commit()
        except Exception as e:
            await db.rollback()
            logger.error("项目用量累计失败: project_id=%s error=%s", project_id, e)
    except Exception as e:
        await db.rollback()
        logger.error("项目用量累计失败: project_id=%s error=%s", project_id, e)


async def touch_token(
        db: AsyncSession,
        token_id: str,
        *,
        last_used_at: datetime | None = None,
) -> None:
    """更新 Token 最后使用时间；5 分钟内不重复写."""
    now = _utcnow()
    if last_used_at is not None:
        last = _normalize_dt(last_used_at)
        if last is not None and now - last < TOKEN_TOUCH_INTERVAL:
            return
    try:
        await db.execute(
            update(ProjectTokenInfo)
            .where(ProjectTokenInfo.token_id == token_id)
            .values(last_used_at=now)
        )
        await db.commit()
    except Exception as e:
        await db.rollback()
        logger.warning("更新 Token 最后使用时间失败: token_id=%s error=%s", token_id, e)


# ==================== 项目用量 ====================


async def get_project_dashboard(db: AsyncSession, project_id: str, days: int = 30) -> dict | None:
    project = await db.get(ProjectInfo, project_id)
    if project is None:
        return None
    snapshot = await get_usage_snapshot(db, project_id)
    overview = await usage_manage_service.get_usage_overview(
        db, days, ["model", "feature_code"], project_id=project_id,
    )
    return {
        "project": project_to_dict(project),
        "quota": snapshot.to_dict(),
        "usage": overview,
    }
