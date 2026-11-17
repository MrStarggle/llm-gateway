"""运行期系统配置：LLM 报文日志开关

- 持久化在 system_config 表，默认开启
- 每个进程内存缓存；后台定时从数据库刷新，多 worker/多实例下也能生效
"""
import asyncio
import logging

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.database import AsyncSessionLocal
from app.models.system_config import SystemConfig

logger = logging.getLogger(__name__)

LOG_PAYLOAD_KEY = "log_payload_enabled"
DEFAULT_LOG_PAYLOAD_ENABLED = True
REFRESH_INTERVAL_SECONDS = 15

_enabled = DEFAULT_LOG_PAYLOAD_ENABLED


def _parse_bool(value: str | None) -> bool:
    if value is None:
        return DEFAULT_LOG_PAYLOAD_ENABLED
    return value.strip().lower() in ("1", "true", "yes", "on")


def is_payload_logging_enabled() -> bool:
    """调用链路上的热路径检查：只读内存，不查库。"""
    return _enabled


async def load(db: AsyncSession) -> bool:
    """从数据库加载开关；缺省时写入默认值（默认开启）。"""
    global _enabled
    row = await db.get(SystemConfig, LOG_PAYLOAD_KEY)
    if row is None:
        row = SystemConfig(config_key=LOG_PAYLOAD_KEY, config_value="1")
        db.add(row)
        try:
            await db.commit()
        except IntegrityError:
            # 其他进程已经写入，回滚后重新读取
            await db.rollback()
            row = await db.get(SystemConfig, LOG_PAYLOAD_KEY)
        else:
            _enabled = True
            return _enabled
    _enabled = _parse_bool(row.config_value if row else None)
    return _enabled


async def get_enabled(db: AsyncSession) -> bool:
    """读取数据库中的当前值，供管理台展示。"""
    row = await db.get(SystemConfig, LOG_PAYLOAD_KEY)
    if row is None:
        return await load(db)
    return _parse_bool(row.config_value)


async def set_enabled(db: AsyncSession, enabled: bool) -> bool:
    """写入数据库并立即更新当前进程缓存。"""
    global _enabled
    row = await db.get(SystemConfig, LOG_PAYLOAD_KEY)
    value = "1" if enabled else "0"
    if row is None:
        db.add(SystemConfig(config_key=LOG_PAYLOAD_KEY, config_value=value))
    else:
        row.config_value = value
    try:
        await db.commit()
    except IntegrityError:
        # 并发首次写入：另一个进程已插入，回滚后改为更新
        await db.rollback()
        row = await db.get(SystemConfig, LOG_PAYLOAD_KEY)
        if row is not None:
            row.config_value = value
            await db.commit()
    _enabled = enabled
    logger.info("LLM 报文日志已%s", "开启" if enabled else "关闭")
    return _enabled


async def refresh_loop(interval_seconds: float = REFRESH_INTERVAL_SECONDS) -> None:
    """定时从数据库刷新，避免多进程下开关状态长期不一致。"""
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            async with AsyncSessionLocal() as db:
                await load(db)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 - 刷新失败不影响主流程
            logger.debug("刷新 LLM 报文日志开关失败: %s", e)
