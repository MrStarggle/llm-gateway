import os
from pathlib import Path
from urllib.parse import quote_plus, urlsplit, urlunsplit

from dotenv import load_dotenv
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

# ==================== 路径配置 ====================
BASE_DIR = Path(__file__).parent.parent.parent  # 项目根目录
load_dotenv(BASE_DIR / ".env")
DATA_DIR = BASE_DIR / "data"
SQL_SCHEMA_FILE = BASE_DIR / "app" / "db" / "schema.sql"

# ==================== 数据库选择 ====================
# DB_BACKEND=sqlite（默认）：零配置，数据落在 data/gateway.db
# DB_BACKEND=mysql：使用下方 MYSQL_* 配置
# DATABASE_URL：显式指定时优先，支持任意 SQLAlchemy 异步驱动
DB_BACKEND = os.getenv("DB_BACKEND", "sqlite").strip().lower()

MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
MYSQL_PORT = os.getenv("MYSQL_PORT", "3306")
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "llm_gateway")


def _build_database_url() -> str:
    explicit = os.getenv("DATABASE_URL", "").strip()
    if explicit:
        return explicit
    if DB_BACKEND in ("mysql", "mariadb"):
        return (
            f"mysql+aiomysql://{MYSQL_USER}:{quote_plus(MYSQL_PASSWORD)}"
            f"@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}?charset=utf8mb4"
        )
    sqlite_path = Path(os.getenv("SQLITE_PATH", str(DATA_DIR / "gateway.db")))
    return f"sqlite+aiosqlite:///{sqlite_path.as_posix()}"


DATABASE_URL = _build_database_url()
IS_SQLITE = DATABASE_URL.startswith("sqlite")


def _safe_database_url(url: str) -> str:
    """打印用：隐藏 URL 中的密码."""
    try:
        parts = urlsplit(url)
        if parts.password:
            host = parts.hostname or ""
            if parts.port:
                host = f"{host}:{parts.port}"
            netloc = f"{parts.username}:***@{host}"
            return urlunsplit(parts._replace(netloc=netloc))
    except ValueError:
        pass
    return url


print(f" 数据库 URL: {_safe_database_url(DATABASE_URL)}")

# SQLite 默认单机使用；多 worker / 多实例请改用 MySQL
if IS_SQLITE:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _engine_options = {"echo": False, "connect_args": {"timeout": 30}}
else:
    _engine_options = {
        "echo": False,
        "pool_size": 10,
        "max_overflow": 20,
        "pool_pre_ping": False,      # aiomysql 不兼容 pool_pre_ping，使用 pool_recycle 兜底
        "pool_recycle": 3600,
    }

engine = create_async_engine(DATABASE_URL, **_engine_options)

if IS_SQLITE:
    # PRAGMA 是连接级设置，必须每条新连接都应用一次
    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, connection_record):  # noqa: ARG001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()


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


async def _configure_sqlite() -> None:
    """WAL + NORMAL：提升并发读性能，降低写事务 fsync 开销."""
    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA journal_mode=WAL"))
        await conn.execute(text("PRAGMA synchronous=NORMAL"))
        await conn.execute(text("PRAGMA busy_timeout=5000"))


async def _ensure_sqlite_schema() -> None:
    """SQLite 存量库补列（create_all 不会修改已存在的表）."""
    async with engine.begin() as conn:
        columns = {
            row[1] for row in (await conn.execute(text("PRAGMA table_info(user_token_info)"))).fetchall()
        }
        if "feature_code" not in columns:
            await conn.execute(text(
                "ALTER TABLE user_token_info "
                "ADD COLUMN feature_code VARCHAR(64) NOT NULL DEFAULT 'uncategorized'"
            ))
            await conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_user_token_info_feature_code "
                "ON user_token_info (feature_code)"
            ))
            print(" SQLite 迁移执行成功: user_token_info.feature_code")


async def _init_mysql_schema() -> None:
    """MySQL：执行建表脚本（已有表跳过）."""
    if not SQL_SCHEMA_FILE.exists():
        print(f" SQL 文件不存在，跳过: {SQL_SCHEMA_FILE}")
        return
    with open(SQL_SCHEMA_FILE, "r", encoding="utf-8") as f:
        sql_script = f.read()

    async with engine.begin() as conn:
        for stmt in _split_sql_statements(sql_script):
            try:
                await conn.execute(text(stmt))
            except Exception as e:
                print(f"  SQL 语句跳过（可能已存在）: {stmt[:60]}... ({e})")
    print(" SQL 脚本执行完成")


async def _list_tables() -> list[str]:
    async with engine.connect() as conn:
        if IS_SQLITE:
            result = await conn.execute(text(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ))
        else:
            result = await conn.execute(
                text(
                    "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES "
                    "WHERE TABLE_SCHEMA = :db AND TABLE_TYPE = 'BASE TABLE'"
                ),
                {"db": MYSQL_DATABASE},
            )
        return [row[0] for row in result.fetchall()]


async def init_database():
    """应用启动时初始化数据库：建表 +（MySQL）迁移"""
    try:
        # 1. ORM 模型建表（SQLite 与 MySQL 共用同一套模型）
        from app.models.llm_provider_info import LlmProviderInfo  # noqa: F401
        from app.models.model_manage_info import ModelManageInfo  # noqa: F401
        from app.models.user_daily_quota import UserDailyQuota  # noqa: F401
        from app.models.user_token_info import UserTokenInfo  # noqa: F401
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        print(" ORM 表结构检查完成")

        if IS_SQLITE:
            await _configure_sqlite()
            await _ensure_sqlite_schema()
        else:
            await _init_mysql_schema()
            await run_migrations()

        tables = await _list_tables()
        print(f" 数据库中的表 ({len(tables)} 个): {tables}")
        return True

    except Exception as e:
        print(f" 数据库初始化失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def run_migrations():
    """MySQL 存量库迁移（SQLite 新库由 ORM 直接建表，无需迁移）."""
    if IS_SQLITE:
        print(" SQLite 模式：表结构由 ORM 创建，跳过 MySQL 迁移")
        return

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
        # 用量分组统计：功能码（调用方通过 X-Feature-Code 声明）
        "ALTER TABLE user_token_info ADD COLUMN feature_code VARCHAR(64) NOT NULL DEFAULT 'uncategorized' COMMENT '功能码（用量分组统计用）'",
        "ALTER TABLE user_token_info ADD INDEX idx_user_token_feature_code (feature_code)",
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
