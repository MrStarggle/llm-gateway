"""测试基类：独立 SQLite 文件 + 每个测试重置表结构，无需 pytest 依赖."""
import atexit
import os
import unittest
from pathlib import Path

TEST_DB = Path(__file__).resolve().parent.parent / "data" / "unittest_gateway.db"

# 必须在导入 app.config.database 之前设置
os.environ["DATABASE_URL"] = ""
os.environ["DB_BACKEND"] = "sqlite"
os.environ["SQLITE_PATH"] = str(TEST_DB)
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["ADMIN_PASSWORD"] = "testpass"
os.environ["JWT_SECRET_KEY"] = "test-secret"
os.environ["GATEWAY_TOKEN_REQUIRED"] = "0"
os.environ["USAGE_RETENTION_DAYS"] = "0"

from app.config.database import DATABASE_URL, Base, engine  # noqa: E402

# 安全护栏：测试绝不能落到 data/gateway.db
assert TEST_DB.as_posix() in DATABASE_URL, f"测试数据库配置错误: {DATABASE_URL}"
from app.models.channel_health_info import ChannelHealthInfo  # noqa: F401,E402
from app.models.cluster_routing_config import ClusterRoutingConfig  # noqa: F401,E402
from app.models.llm_provider_info import LlmProviderInfo  # noqa: F401,E402
from app.models.model_manage_info import ModelManageInfo  # noqa: F401,E402
from app.models.project_info import ProjectInfo  # noqa: F401,E402
from app.models.project_token_info import ProjectTokenInfo  # noqa: F401,E402
from app.models.project_usage_daily import ProjectUsageDaily  # noqa: F401,E402
from app.models.user_daily_quota import UserDailyQuota  # noqa: F401,E402
from app.models.user_token_info import UserTokenInfo  # noqa: F401,E402


async def _reset_database() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)


class GatewayTestCase(unittest.IsolatedAsyncioTestCase):
    """每个测试使用独立事件循环，并在结束后释放连接池."""

    async def asyncSetUp(self):
        await engine.dispose()
        await _reset_database()

    async def asyncTearDown(self):
        await engine.dispose()


def _cleanup_db_files() -> None:
    for suffix in ("", "-wal", "-shm"):
        path = Path(str(TEST_DB) + suffix)
        if path.exists():
            path.unlink()


for _suffix in ("", "-wal", "-shm"):
    _path = Path(str(TEST_DB) + _suffix)
    if _path.exists():
        _path.unlink()
atexit.register(_cleanup_db_files)
