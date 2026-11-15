"""项目每日用量聚合表

用于项目级配额检查与项目管理页汇总。成本只累计与项目 cost_currency
一致的调用记录，不做跨币种换算。
"""
from sqlalchemy import BigInteger, Column, Date, Integer, Numeric, String, TIMESTAMP, UniqueConstraint, func

from app.config.database import Base


class ProjectUsageDaily(Base):
    __tablename__ = "project_usage_daily"
    __table_args__ = (
        UniqueConstraint("project_id", "usage_date", name="uq_project_usage_daily"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True, comment="自增主键")
    project_id = Column(String(64), nullable=False, index=True, comment="项目ID")
    usage_date = Column(Date, nullable=False, index=True, comment="统计日期")
    call_count = Column(Integer, nullable=False, server_default="0", comment="成功调用次数")
    total_tokens = Column(BigInteger, nullable=False, server_default="0", comment="Token 总数")
    cost_amount = Column(Numeric(18, 8), nullable=False, server_default="0",
                        comment="成本合计（项目币种）")
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(),
                        onupdate=func.current_timestamp(), comment="更新时间")
