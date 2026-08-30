import os
from pathlib import Path
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy import text
import sys

# ==================== 路径配置 ====================
BASE_DIR = Path(__file__).parent.parent.parent  # 项目根目录
DATA_DIR = BASE_DIR / "data"
SQL_SCHEMA_FILE = BASE_DIR / "app" / "db" / "starggle_main.sql"

# ==================== MySQL 连接配置 ====================
MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
MYSQL_PORT = os.getenv("MYSQL_PORT", "3306")
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "Yang@123")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "starggle_main")

# URL 编码密码中的特殊字符（如 @）
from urllib.parse import quote_plus
_encoded_password = quote_plus(MYSQL_PASSWORD)

DATABASE_URL = (
    f"mysql+aiomysql://{MYSQL_USER}:{_encoded_password}"
    f"@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}"
    f"?charset=utf8mb4"
)

print(f" 数据库 URL: mysql+aiomysql://{MYSQL_USER}:***@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}")

# ==================== 数据库引擎配置 ====================
engine = create_async_engine(
    DATABASE_URL,
    echo=False,                     # SQL 日志由应用层 logging 控制
    pool_size=10,                   # 连接池大小
    max_overflow=20,                # 最大溢出连接数
    pool_pre_ping=False,            # aiomysql 不兼容 pool_pre_ping，使用 pool_recycle 兜底
    pool_recycle=3600,              # 1 小时后回收连接
)

# 创建异步会话工厂
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)

# 声明基类（用于 ORM 模型）
Base = declarative_base()


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


# ==================== 数据库初始化 ====================

def _split_sql_statements(sql_script: str) -> list[str]:
    """将 SQL 脚本按分号拆分为独立语句，过滤空行和注释"""
    statements = []
    for statement in sql_script.split(";"):
        # 去掉前导的注释行和空行（否则 -- 注释头 + CREATE TABLE 的整块会被误过滤）
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
        from app.models.model_manage_info import ModelManageInfo  # noqa: F401
        from app.models.user_token_info import UserTokenInfo  # noqa: F401
        from app.models.user_info import UserInfo  # noqa: F401
        from app.models.order_info import OrderInfo  # noqa: F401
        from app.models.async_manage_info import AsyncManageInfo  # noqa: F401
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        print(" ORM 表结构检查完成")

        # 2. 读取并执行 SQL 建表脚本
        if not SQL_SCHEMA_FILE.exists():
            print(f" SQL 文件不存在，跳过: {SQL_SCHEMA_FILE}")
        else:
            with open(SQL_SCHEMA_FILE, 'r', encoding='utf-8') as f:
                sql_script = f.read()

            statements = _split_sql_statements(sql_script)
            async with engine.begin() as conn:
                for stmt in statements:
                    try:
                        await conn.execute(text(stmt))
                    except Exception as e:
                        # 表/索引已存在等预期错误，跳过
                        print(f"  SQL 语句跳过（可能已存在）: {stmt[:60]}... ({e})")
            print(" SQL 脚本执行完成")

        # 3. 数据库迁移
        await run_migrations()

        # 3.5 异步LLM总控种子数据（13 路固定配置，只补缺失行）
        from app.services.async_manage_service import seed_async_manage_configs
        await seed_async_manage_configs()

        # 4. 验证表列表
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES "
                    "WHERE TABLE_SCHEMA = :db AND TABLE_TYPE = 'BASE TABLE'"
                ),
                {"db": MYSQL_DATABASE}
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
    """执行数据库迁移，为现有表添加新字段"""
    migrations = [
        # 积分制：新增积分余额字段（共享表，列由本系统负责迁移，重复执行自动跳过）
        "ALTER TABLE user_info ADD COLUMN point_balance INT NOT NULL DEFAULT 0 COMMENT '积分余额（余额即会员等级）'",
        # 会员系统：新增到期时间 / 订阅ID / 套餐ID 字段（与 StarggleCom 迁移保持一致，重复执行自动跳过）
        "ALTER TABLE user_info ADD COLUMN membership_expire_at DATETIME NULL COMMENT '会员到期时间（免费档为空）'",
        "ALTER TABLE user_info ADD COLUMN subscription_id VARCHAR(128) NULL COMMENT '支付渠道订阅ID（Creem 用）'",
        "ALTER TABLE user_info ADD COLUMN plan_id VARCHAR(64) NULL COMMENT '支付渠道套餐ID（Creem 用）'",
        # 会员等级默认值修正 + 历史数据归一（与 StarggleCom 一致）
        "ALTER TABLE user_info MODIFY COLUMN membership_level VARCHAR(32) NULL DEFAULT 'free' COMMENT '会员等级: free/plus/pro'",
        "UPDATE user_info SET membership_level = 'free' WHERE membership_level = '1'",
        "UPDATE user_info SET membership_level = 'plus' WHERE membership_level = '2'",
        # 异步LLM总控：is_think 改为三态（1强制开/0强制关/NULL跟随客户端不注入），存量 '0'/'1' 语义不变
        "ALTER TABLE async_manage_info MODIFY COLUMN is_think VARCHAR(1) NULL DEFAULT '0' COMMENT '请求级思考模式：1强制开/0强制关/NULL跟随客户端（不注入）'",
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
            else:
                print(" 数据库连接测试失败")
                return False
    except Exception as e:
        print(f" 数据库连接失败: {e}")
        import traceback
        traceback.print_exc()
        return False
