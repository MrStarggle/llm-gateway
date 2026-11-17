"""渠道（模型行）健康状态 ORM 模型

一个 model_manage_info 行视为一个渠道。计数按天懒重置：
更新时若 stat_date 不是今天，则在同一条 SQL 内重置为 1。
"""
from sqlalchemy import BigInteger, Column, Date, DateTime, Integer, String, TIMESTAMP, func

from app.config.database import Base


class ChannelHealthInfo(Base):
    __tablename__ = "channel_health_info"

    model_id = Column(String(64), primary_key=True, nullable=False, comment="模型ID（ai_model_id）")
    stat_date = Column(Date, nullable=True, comment="统计日期")
    success_count = Column(Integer, nullable=False, server_default="0", comment="今日成功次数")
    failure_count = Column(Integer, nullable=False, server_default="0", comment="今日失败次数")
    latency_sum_ms = Column(BigInteger, nullable=False, server_default="0",
                           comment="今日延迟总和（流式为TTFB）")
    consecutive_failures = Column(Integer, nullable=False, server_default="0", comment="连续失败次数")
    consecutive_successes = Column(Integer, nullable=False, server_default="0", comment="连续成功次数")
    state = Column(String(16), nullable=False, server_default="closed", index=True,
                   comment="状态：closed/open/half_open")
    cooldown_until = Column(DateTime, nullable=True, comment="冷却结束时间")
    last_error = Column(String(200), nullable=True, comment="最后错误标识（不含上游报文）")
    last_success_at = Column(DateTime, nullable=True, comment="最后成功时间")
    last_failure_at = Column(DateTime, nullable=True, comment="最后失败时间")
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(),
                        onupdate=func.current_timestamp(), comment="更新时间")
