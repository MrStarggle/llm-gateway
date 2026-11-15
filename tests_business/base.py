"""business-sync 集成测试基类：独立 SQLite + 依赖覆盖，不连接 MySQL."""
import unittest
from pathlib import Path

import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine, AsyncSession

from app.config.database import Base, get_db
from app.models.channel_health_info import ChannelHealthInfo
from app.models.cluster_routing_config import ClusterRoutingConfig
from app.models.model_manage_info import ModelManageInfo
from app.models.project_info import ProjectInfo
from app.models.project_token_info import ProjectTokenInfo
from app.models.project_usage_daily import ProjectUsageDaily
from app.models.user_daily_quota import UserDailyQuota
from app.models.user_token_info import UserTokenInfo
from app.utils.admin_auth import require_admin_user
from main import app

TEST_DB = Path(__file__).resolve().parent.parent / "data" / "business_unittest.db"

TABLES = [
    ModelManageInfo.__table__,
    UserTokenInfo.__table__,
    UserDailyQuota.__table__,
    ProjectInfo.__table__,
    ProjectTokenInfo.__table__,
    ProjectUsageDaily.__table__,
    ChannelHealthInfo.__table__,
    ClusterRoutingConfig.__table__,
]


def _cleanup_db() -> None:
    for suffix in ("", "-wal", "-shm"):
        path = Path(str(TEST_DB) + suffix)
        if path.exists():
            path.unlink()


class BusinessGatewayTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        _cleanup_db()
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{TEST_DB.as_posix()}")
        self.Session = async_sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False,
        )
        async with self.engine.begin() as conn:
            await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=TABLES))

        async def override_get_db():
            async with self.Session() as session:
                yield session

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[require_admin_user] = lambda: "test-admin"
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test",
        )

    async def asyncTearDown(self):
        await self.client.aclose()
        app.dependency_overrides.clear()
        await self.engine.dispose()
        _cleanup_db()
