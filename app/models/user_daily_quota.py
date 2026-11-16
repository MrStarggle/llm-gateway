"""每日调用与 Token 计数表（配额/统计口径，与 token 用量明细分离）

- 本表按 user_id + 日期累计调用次数与 token 数，用于管理台统计与用户级 Token 配额；
- user_token_info 保存每次调用的 token 明细，用于用量与调用记录；
- 两表独立写入，任一方失败不影响 LLM 响应返回。
"""
from sqlalchemy import BigInteger, Column, String, Integer, Date, TIMESTAMP, UniqueConstraint, func
from app.config.database import Base


class UserDailyQuota(Base):
    __tablename__ = "user_daily_quota"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="自增主键")
    user_id = Column(String(64), nullable=False, comment="用户ID")
    quota_date = Column(Date, nullable=False, comment="计数日期（按天归零）")
    call_count = Column(Integer, nullable=False, server_default="0", comment="当日 LLM 调用次数")
    total_tokens = Column(BigInteger, nullable=False, server_default="0",
                          comment="当日token总数（配额口径）")
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(),
                        onupdate=func.current_timestamp(), comment="更新时间")

    __table_args__ = (
        UniqueConstraint("user_id", "quota_date", name="uq_user_daily_quota_user_date"),
    )
