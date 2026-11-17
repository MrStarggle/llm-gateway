"""渠道健康与集群路由

- 一个 model_manage_info 行 = 一个渠道
- 健康状态持久化在 channel_health_info；计数按天懒重置
- 路由策略：round_robin / cost_first / latency_first
"""
import asyncio
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import case, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.channel_health_info import ChannelHealthInfo
from app.models.cluster_routing_config import ClusterRoutingConfig
from app.models.model_manage_info import ModelManageInfo

logger = logging.getLogger(__name__)

VALID_ASYNC_TYPES = tuple(f"async{i}" for i in range(1, 10))
VALID_STRATEGIES = ("round_robin", "cost_first", "latency_first")

_DEFAULT_CONFIG = {
    "strategy": "round_robin",
    "retry_max": 1,
    "failure_threshold": 5,
    "cooldown_seconds": 60,
    "output_ratio": 0.3,
    "enabled": 1,
}

_rr_idx: dict[str, int] = {async_type: 0 for async_type in VALID_ASYNC_TYPES}
_rr_lock = asyncio.Lock()


def _utcnow() -> datetime:
    """当前 UTC 时间（naive，数据库列不带时区）."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


@dataclass(frozen=True)
class RoutingConfig:
    async_type: str
    strategy: str
    retry_max: int
    failure_threshold: int
    cooldown_seconds: int
    output_ratio: float
    enabled: bool

    def to_dict(self) -> dict:
        return {
            "asyncType": self.async_type,
            "strategy": self.strategy,
            "retryMax": self.retry_max,
            "failureThreshold": self.failure_threshold,
            "cooldownSeconds": self.cooldown_seconds,
            "outputRatio": self.output_ratio,
            "enabled": 1 if self.enabled else 0,
        }


def _config_from_row(async_type: str, row: ClusterRoutingConfig | None) -> RoutingConfig:
    if row is None:
        return RoutingConfig(async_type=async_type, **_DEFAULT_CONFIG)
    return RoutingConfig(
        async_type=async_type,
        strategy=row.strategy if row.strategy in VALID_STRATEGIES else _DEFAULT_CONFIG["strategy"],
        retry_max=int(row.retry_max if row.retry_max is not None else _DEFAULT_CONFIG["retry_max"]),
        failure_threshold=int(
            row.failure_threshold if row.failure_threshold is not None else _DEFAULT_CONFIG["failure_threshold"]
        ),
        cooldown_seconds=int(
            row.cooldown_seconds if row.cooldown_seconds is not None else _DEFAULT_CONFIG["cooldown_seconds"]
        ),
        output_ratio=float(row.output_ratio if row.output_ratio is not None else _DEFAULT_CONFIG["output_ratio"]),
        enabled=bool(row.enabled if row.enabled is not None else _DEFAULT_CONFIG["enabled"]),
    )


async def get_routing_config(db: AsyncSession, async_type: str) -> RoutingConfig:
    row = await db.get(ClusterRoutingConfig, async_type)
    return _config_from_row(async_type, row)


async def list_routing_configs(db: AsyncSession) -> list[dict]:
    rows = (await db.execute(select(ClusterRoutingConfig))).scalars().all()
    by_cluster = {row.async_type: row for row in rows}
    return [
        _config_from_row(async_type, by_cluster.get(async_type)).to_dict()
        for async_type in VALID_ASYNC_TYPES
    ]


async def update_routing_config(db: AsyncSession, async_type: str, data) -> RoutingConfig:
    if async_type not in VALID_ASYNC_TYPES:
        raise ValueError("非法集群类型，可选 async1..async9")
    row = await db.get(ClusterRoutingConfig, async_type)
    if row is None:
        row = ClusterRoutingConfig(async_type=async_type)
        db.add(row)
    row.strategy = data.strategy
    row.retry_max = data.retry_max
    row.failure_threshold = data.failure_threshold
    row.cooldown_seconds = data.cooldown_seconds
    row.output_ratio = data.output_ratio
    row.enabled = data.enabled
    await db.commit()
    await db.refresh(row)
    return _config_from_row(async_type, row)


# ==================== 选择 ====================


async def get_health_map(db: AsyncSession, model_ids: list[str]) -> dict[str, ChannelHealthInfo]:
    if not model_ids:
        return {}
    rows = (await db.execute(
        select(ChannelHealthInfo).where(ChannelHealthInfo.model_id.in_(model_ids))
    )).scalars().all()
    return {row.model_id: row for row in rows}


def _avg_latency(health: ChannelHealthInfo | None) -> float | None:
    if health is None:
        return None
    successes = int(health.success_count or 0)
    if successes <= 0:
        return None
    return int(health.latency_sum_ms or 0) / successes


def _is_available(health: ChannelHealthInfo | None, now: datetime) -> bool:
    if health is None:
        return True
    if health.state != "open":
        return True
    if health.cooldown_until is None:
        return True
    return health.cooldown_until <= now


async def _rotated(models: list[ModelManageInfo], async_type: str) -> list[ModelManageInfo]:
    if not models:
        return []
    async with _rr_lock:
        current = _rr_idx.get(async_type, 0)
        idx = current % len(models)
        _rr_idx[async_type] = current + 1
    return models[idx:] + models[:idx]


def _unit_price(model: ModelManageInfo, output_ratio: float) -> Decimal | None:
    if model.input_price_per_1m is None or model.output_price_per_1m is None:
        return None
    return (
        Decimal(str(model.input_price_per_1m))
        + Decimal(str(model.output_price_per_1m)) * Decimal(str(output_ratio))
    )


async def plan_candidates(
        db: AsyncSession,
        models: list[ModelManageInfo],
        async_type: str,
        *,
        exclude_ids: set[str] | None = None,
) -> list[ModelManageInfo]:
    """按健康状态与策略返回尝试顺序，最多 1+retry_max 个（上限 3）."""
    if not models:
        return []

    exclude_ids = exclude_ids or set()
    config = await get_routing_config(db, async_type)
    now = _utcnow()
    health_map = await get_health_map(db, [m.ai_model_id for m in models])

    if config.enabled:
        eligible = [
            m for m in models
            if m.ai_model_id not in exclude_ids
            and _is_available(health_map.get(m.ai_model_id), now)
        ]
        if not eligible:
            # 全部熔断：仍然尝试，避免全渠道同时故障时直接失败
            eligible = [m for m in models if m.ai_model_id not in exclude_ids]
            if eligible:
                logger.warning("集群 %s 所有渠道均处于熔断状态，降级为全量尝试", async_type)
    else:
        eligible = [m for m in models if m.ai_model_id not in exclude_ids]

    if not eligible:
        return []

    eligible = await _rotated(eligible, async_type)

    if config.strategy == "cost_first":
        eligible.sort(key=lambda m: (
            0 if _unit_price(m, config.output_ratio) is not None else 1,
            _unit_price(m, config.output_ratio) or Decimal(0),
            _avg_latency(health_map.get(m.ai_model_id)) or float("inf"),
        ))
    elif config.strategy == "latency_first":
        eligible.sort(key=lambda m: (
            0 if _avg_latency(health_map.get(m.ai_model_id)) is not None else 1,
            _avg_latency(health_map.get(m.ai_model_id)) or float("inf"),
        ))

    max_attempts = min(1 + max(0, config.retry_max), 3)
    return eligible[:max_attempts]


# ==================== 健康记录 ====================


async def _apply_update_with_insert(db: AsyncSession, model_id: str, values: dict, insert_values: dict) -> int:
    """先原子 UPDATE；行不存在则 INSERT；并发撞唯一键时重试 UPDATE."""
    try:
        result = await db.execute(
            update(ChannelHealthInfo).where(ChannelHealthInfo.model_id == model_id).values(**values)
        )
        if result.rowcount == 0:
            db.add(ChannelHealthInfo(model_id=model_id, **insert_values))
        await db.commit()
        return int(result.rowcount or 0)
    except IntegrityError:
        await db.rollback()
        try:
            result = await db.execute(
                update(ChannelHealthInfo).where(ChannelHealthInfo.model_id == model_id).values(**values)
            )
            await db.commit()
            return int(result.rowcount or 0)
        except Exception as e:
            await db.rollback()
            logger.warning("渠道健康更新失败: model_id=%s error=%s", model_id, e)
            return 0
    except Exception as e:
        await db.rollback()
        logger.warning("渠道健康更新失败: model_id=%s error=%s", model_id, e)
        return 0


async def record_success(db: AsyncSession, model_id: str, latency_ms: float) -> None:
    now = _utcnow()
    today = date.today()
    latency = max(0, int(latency_ms or 0))
    same_day = ChannelHealthInfo.stat_date == today
    values = {
        "stat_date": today,
        "success_count": case((same_day, ChannelHealthInfo.success_count + 1), else_=1),
        "failure_count": case((same_day, ChannelHealthInfo.failure_count), else_=0),
        "latency_sum_ms": case((same_day, ChannelHealthInfo.latency_sum_ms + latency), else_=latency),
        "consecutive_failures": 0,
        "consecutive_successes": case(
            (same_day, ChannelHealthInfo.consecutive_successes + 1), else_=1,
        ),
        "state": "closed",
        "cooldown_until": None,
        "last_error": None,
        "last_success_at": now,
    }
    await _apply_update_with_insert(
        db, model_id, values,
        {
            "stat_date": today,
            "success_count": 1,
            "failure_count": 0,
            "latency_sum_ms": latency,
            "consecutive_failures": 0,
            "consecutive_successes": 1,
            "state": "closed",
            "last_success_at": now,
        },
    )


async def record_failure(
        db: AsyncSession,
        model_id: str,
        latency_ms: float,
        error_tag: str,
        *,
        failure_threshold: int = 5,
        cooldown_seconds: int = 60,
) -> None:
    now = _utcnow()
    today = date.today()
    same_day = ChannelHealthInfo.stat_date == today
    values = {
        "stat_date": today,
        "success_count": case((same_day, ChannelHealthInfo.success_count), else_=0),
        "failure_count": case((same_day, ChannelHealthInfo.failure_count + 1), else_=1),
        "latency_sum_ms": case((same_day, ChannelHealthInfo.latency_sum_ms), else_=0),
        "consecutive_failures": case(
            (same_day, ChannelHealthInfo.consecutive_failures + 1), else_=1,
        ),
        "consecutive_successes": 0,
        "last_error": (error_tag or "unknown")[:200],
        "last_failure_at": now,
    }
    await _apply_update_with_insert(
        db, model_id, values,
        {
            "stat_date": today,
            "success_count": 0,
            "failure_count": 1,
            "latency_sum_ms": 0,
            "consecutive_failures": 1,
            "consecutive_successes": 0,
            "state": "closed",
            "last_error": (error_tag or "unknown")[:200],
            "last_failure_at": now,
        },
    )

    try:
        row = await db.get(ChannelHealthInfo, model_id)
        if row is None:
            return
        await db.refresh(row)
        should_open = int(row.consecutive_failures or 0) >= max(1, failure_threshold)
        if not should_open and row.state in ("open", "half_open"):
            # 半开探针失败 / 冷却后仍失败
            should_open = True
        if should_open:
            row.state = "open"
            row.cooldown_until = now + timedelta(seconds=max(0, cooldown_seconds))
            await db.commit()
    except Exception as e:
        await db.rollback()
        logger.warning("渠道熔断状态更新失败: model_id=%s error=%s", model_id, e)


async def reset_channel(db: AsyncSession, model_id: str) -> bool:
    try:
        result = await db.execute(
            update(ChannelHealthInfo)
            .where(ChannelHealthInfo.model_id == model_id)
            .values(
                state="closed",
                consecutive_failures=0,
                cooldown_until=None,
                last_error=None,
            )
        )
        await db.commit()
        return int(result.rowcount or 0) > 0
    except Exception as e:
        await db.rollback()
        logger.warning("重置渠道熔断失败: model_id=%s error=%s", model_id, e)
        return False


# ==================== 看板 ====================


async def get_health_overview(db: AsyncSession) -> dict:
    models = (await db.execute(
        select(ModelManageInfo)
        .where(ModelManageInfo.is_using == "1")
        .order_by(ModelManageInfo.async_type, ModelManageInfo.ai_model_name)
    )).scalars().all()
    health_map = await get_health_map(db, [m.ai_model_id for m in models])
    now = _utcnow()

    cluster_map = {
        async_type: {"asyncType": async_type, "total": 0, "healthy": 0, "open": 0, "halfOpen": 0}
        for async_type in VALID_ASYNC_TYPES
    }
    channels = []
    for model in models:
        health = health_map.get(model.ai_model_id)
        state = health.state if health else "closed"
        if state == "open" and health and health.cooldown_until and health.cooldown_until <= now:
            state = "half_open"
        successes = int(health.success_count or 0) if health else 0
        failures = int(health.failure_count or 0) if health else 0
        total = successes + failures
        avg_latency = (int(health.latency_sum_ms or 0) / successes) if health and successes else None
        cooldown_remaining = 0
        if health and health.cooldown_until and health.cooldown_until > now:
            cooldown_remaining = int((health.cooldown_until - now).total_seconds())

        bucket = cluster_map.setdefault(
            model.async_type,
            {"asyncType": model.async_type, "total": 0, "healthy": 0, "open": 0, "halfOpen": 0},
        )
        bucket["total"] += 1
        if state == "closed":
            bucket["healthy"] += 1
        elif state == "open":
            bucket["open"] += 1
        else:
            bucket["halfOpen"] += 1

        channels.append({
            "modelId": model.ai_model_id,
            "modelName": model.ai_model_name,
            "providerName": model.com_name,
            "asyncType": model.async_type,
            "state": state,
            "todaySuccess": successes,
            "todayFailure": failures,
            "successRate": round(successes * 100.0 / total, 1) if total else None,
            "avgLatencyMs": round(avg_latency, 1) if avg_latency is not None else None,
            "consecutiveFailures": int(health.consecutive_failures or 0) if health else 0,
            "cooldownRemainingSeconds": cooldown_remaining,
            "lastError": health.last_error if health else None,
            "lastSuccessAt": health.last_success_at.isoformat() if health and health.last_success_at else None,
            "lastFailureAt": health.last_failure_at.isoformat() if health and health.last_failure_at else None,
        })

    return {
        "clusters": list(cluster_map.values()),
        "channels": channels,
        "routing": await list_routing_configs(db),
        "generatedAt": now.isoformat(),
    }
