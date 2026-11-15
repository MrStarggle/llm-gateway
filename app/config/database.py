import os
from pathlib import Path
from urllib.parse import quote_plus

from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

# ==================== 路径配置 ====================
BASE_DIR = Path(__file__).parent.parent.parent  # 项目根目录
load_dotenv(BASE_DIR / ".env")
SQL_SCHEMA_FILE = BASE_DIR / "app" / "db" / "schema.sql"

# ==================== MySQL 连接配置 ====================
MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
MYSQL_PORT = os.getenv("MYSQL_PORT", "3306")
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "starggle_main")

DATABASE_URL = (
    f"mysql+aiomysql://{MYSQL_USER}:{quote_plus(MYSQL_PASSWORD)}"
    f"@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}"
    f"?charset=utf8mb4"
)

print(f" 数据库 URL: mysql+aiomysql://{MYSQL_USER}:***@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}")

# ==================== 数据库引擎配置 ====================
engine = create_async_engine(
    DATABASE_URL,
    echo=False,                     # SQL 日志由应用层 logging 控制
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=False,            # aiomysql 不兼容 pool_pre_ping，使用 pool_recycle 兜底
    pool_recycle=3600,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

Base = declarative_base()


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


# ==================== 数据库初始化 ====================

def _split_sql_statements(sql_script: str) -> list[str]:
    """将 SQL 脚本按分号拆分为独立语句，过滤空行和注释"""
    statements = []
    for statement in sql_script.split(";"):
        lines = statement.strip().split("\n")
        content_start = 0
        for line in lines:
            s = line.strip()
            if s and not s.startswith("--"):
                break
            content_start += 1
        if content_start < len(lines):
            stmt = "\n".join(lines[content_start:]).strip()
            if stmt:
                statements.append(stmt)
    return statements


async def init_database():
    """应用启动时初始化数据库：建表 + 执行 SQL 脚本 + 迁移"""
    try:
        # 1. ORM 模型建表
        from app.models.llm_provider_info import LlmProviderInfo  # noqa: F401
        from app.models.model_manage_info import ModelManageInfo  # noqa: F401
        from app.models.order_info import OrderInfo  # noqa: F401
        from app.models.user_daily_quota import UserDailyQuota  # noqa: F401
        from app.models.user_info import UserInfo  # noqa: F401
        from app.models.user_token_info import UserTokenInfo  # noqa: F401
        # 项目 Token / 配额 / 渠道健康
        from app.models.project_info import ProjectInfo  # noqa: F401
        from app.models.project_token_info import ProjectTokenInfo  # noqa: F401
        from app.models.project_usage_daily import ProjectUsageDaily  # noqa: F401
        from app.models.channel_health_info import ChannelHealthInfo  # noqa: F401
        from app.models.cluster_routing_config import ClusterRoutingConfig  # noqa: F401
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        print(" ORM 表结构检查完成")

        # 2. 读取并执行 SQL 建表脚本
        if not SQL_SCHEMA_FILE.exists():
            print(f" SQL 文件不存在，跳过: {SQL_SCHEMA_FILE}")
        else:
            with open(SQL_SCHEMA_FILE, "r", encoding="utf-8") as f:
                sql_script = f.read()

            statements = _split_sql_statements(sql_script)
            async with engine.begin() as conn:
                for stmt in statements:
                    try:
                        await conn.execute(text(stmt))
                    except Exception as e:
                        print(f"  SQL 语句跳过（可能已存在）: {stmt[:60]}... ({e})")
            print(" SQL 脚本执行完成")

        # 3. 数据库迁移
        await run_migrations()

        # 4. 验证表列表
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES "
                    "WHERE TABLE_SCHEMA = :db AND TABLE_TYPE = 'BASE TABLE'"
                ),
                {"db": MYSQL_DATABASE},
            )
            tables = [row[0] for row in result.fetchall()]
            print(f" 数据库中的表 ({len(tables)} 个): {tables}")

        return True

    except Exception as e:
        print(f" 数据库初始化失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def run_migrations():
    """执行数据库迁移，为已有表补充字段（幂等，重复执行自动跳过）"""
    migrations = [
        # 大模型提供商：模型关联 llm_provider_info（地址/密钥统一配置，模型表保留冗余副本供调用链路直读）
        "ALTER TABLE model_manage_info ADD COLUMN provider_id VARCHAR(64) NULL COMMENT '提供商ID（指向 llm_provider_info）'",
        "ALTER TABLE model_manage_info ADD INDEX idx_model_provider_id (provider_id)",
        # 集群类型：原 is_base 两池语义迁移为 async1/async2，迁移后删除旧字段
        "ALTER TABLE model_manage_info ADD COLUMN async_type VARCHAR(8) NOT NULL DEFAULT 'async1' COMMENT '集群类型：async1..async9'",
        "UPDATE model_manage_info SET async_type = 'async2' WHERE is_base = '1'",
        "ALTER TABLE model_manage_info DROP COLUMN is_base",
        "ALTER TABLE model_manage_info ADD INDEX idx_model_async_type (async_type)",
        # 模型级请求参数（NULL=沿用客户端值）
        "ALTER TABLE model_manage_info ADD COLUMN temperature FLOAT NULL COMMENT '覆盖请求体temperature；NULL=不覆盖（沿用客户端值）'",
        "ALTER TABLE model_manage_info ADD COLUMN top_p FLOAT NULL COMMENT '覆盖请求体top_p；NULL=不覆盖（与temperature互斥）'",
        "ALTER TABLE model_manage_info ADD COLUMN top_k INT NULL COMMENT '覆盖请求体top_k；NULL=不覆盖（部分厂商不支持）'",
        "ALTER TABLE model_manage_info ADD COLUMN max_tokens INT NULL COMMENT '覆盖请求体max_tokens；NULL=不覆盖（沿用客户端值）'",
        # 思考模式语义：0跟随请求/1强制开启/2强制关闭
        "ALTER TABLE model_manage_info MODIFY COLUMN is_think VARCHAR(1) NULL DEFAULT '0' COMMENT '思考模式：0跟随请求，1强制开启，2强制关闭'",
        # 计费单价（每 1M token）与价格来源
        "ALTER TABLE model_manage_info ADD COLUMN input_price_per_1m DECIMAL(18,6) NULL COMMENT '输入单价（每 1M token）'",
        "ALTER TABLE model_manage_info ADD COLUMN output_price_per_1m DECIMAL(18,6) NULL COMMENT '输出单价（每 1M token）'",
        "ALTER TABLE model_manage_info ADD COLUMN price_currency VARCHAR(8) NOT NULL DEFAULT 'USD' COMMENT '价格币种'",
        "ALTER TABLE model_manage_info ADD COLUMN price_source VARCHAR(16) NULL COMMENT '价格来源：manual/provider'",
        "ALTER TABLE model_manage_info ADD COLUMN price_updated_at DATETIME NULL COMMENT '价格更新时间'",
        # 用量归属与成本快照
        "ALTER TABLE user_token_info ADD COLUMN feature_code VARCHAR(64) NOT NULL DEFAULT 'uncategorized' COMMENT '功能码（用量分组统计用）'",
        "ALTER TABLE user_token_info ADD INDEX idx_user_token_feature_code (feature_code)",
        "ALTER TABLE user_token_info ADD COLUMN estimated_cost DECIMAL(18,8) NULL COMMENT '本次调用成本（估算或上游返回）'",
        "ALTER TABLE user_token_info ADD COLUMN cost_currency VARCHAR(8) NULL COMMENT '成本币种'",
        "ALTER TABLE user_token_info ADD COLUMN cost_source VARCHAR(16) NULL COMMENT '成本来源：estimate/provider'",
        "ALTER TABLE user_token_info ADD COLUMN project_id VARCHAR(64) NULL COMMENT '项目ID'",
        "ALTER TABLE user_token_info ADD INDEX idx_user_token_project_id (project_id)",
        "ALTER TABLE user_token_info ADD COLUMN token_id VARCHAR(64) NULL COMMENT '项目Token ID'",
        "ALTER TABLE user_token_info ADD INDEX idx_user_token_token_id (token_id)",
        "ALTER TABLE user_token_info ADD COLUMN channel_id VARCHAR(64) NULL COMMENT '实际服务的模型ID'",
        "ALTER TABLE user_token_info ADD INDEX idx_user_token_channel_id (channel_id)",
        "ALTER TABLE user_token_info ADD COLUMN request_id VARCHAR(64) NULL COMMENT '请求ID'",
        "ALTER TABLE user_token_info ADD INDEX idx_user_token_request_id (request_id)",
        "ALTER TABLE user_token_info ADD COLUMN retry_count INT NOT NULL DEFAULT 0 COMMENT '网关内部重试次数'",
        # 积分制：积分余额（共享表，列由本系统负责迁移，重复执行自动跳过）
        "ALTER TABLE user_info ADD COLUMN point_balance INT NOT NULL DEFAULT 0 COMMENT '积分余额（余额即会员等级）'",
        # 会员系统：到期时间 / 订阅ID / 套餐ID（与 StarggleCom 迁移保持一致）
        "ALTER TABLE user_info ADD COLUMN membership_expire_at DATETIME NULL COMMENT '会员到期时间（免费档为空）'",
        "ALTER TABLE user_info ADD COLUMN subscription_id VARCHAR(128) NULL COMMENT '支付渠道订阅ID（Creem 用）'",
        "ALTER TABLE user_info ADD COLUMN plan_id VARCHAR(64) NULL COMMENT '支付渠道套餐ID（Creem 用）'",
        "ALTER TABLE user_info MODIFY COLUMN membership_level VARCHAR(32) NULL DEFAULT 'free' COMMENT '会员等级: free/plus/pro'",
        "UPDATE user_info SET membership_level = 'free' WHERE membership_level = '1'",
        "UPDATE user_info SET membership_level = 'plus' WHERE membership_level = '2'",
    ]
    async with engine.begin() as conn:
        for sql in migrations:
            try:
                await conn.execute(text(sql))
                print(f" 迁移执行成功: {sql[:60]}...")
            except Exception as e:
                print(f"  迁移跳过（可能已存在）: {sql[:60]}... ({e})")

    print(" 数据库迁移检查完成")


async def check_database_connection():
    """检查数据库连接"""
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT 1"))
            data = result.scalar()
            if data == 1:
                print(" 数据库连接正常")
                return True
            print(" 数据库连接测试失败")
            return False
    except Exception as e:
        print(f" 数据库连接失败: {e}")
        import traceback
        traceback.print_exc()
        return False
