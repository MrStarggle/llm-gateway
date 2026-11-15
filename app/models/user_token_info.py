"""用户 Token 消耗记录表（每次 LLM 调用一行明细）"""
from sqlalchemy import Column, String, Integer, Date, Numeric, TIMESTAMP, func
from app.config.database import Base


class UserTokenInfo(Base):
    __tablename__ = "user_token_info"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="自增主键")
    user_id = Column(String(64), nullable=False, index=True, comment="用户ID")
    model = Column(String(128), nullable=False, server_default="", comment="模型名称")
    purpose = Column(String(16), nullable=False, server_default="main", comment="用途: main/async/async1..async13（异步分路）")
    feature_code = Column(String(64), nullable=False, server_default="uncategorized", index=True, comment="功能码（用量分组统计用）")
    is_stream = Column(Integer, nullable=False, server_default="0", comment="是否流式: 1是0否")
    prompt_tokens = Column(Integer, nullable=False, server_default="0", comment="输入token")
    completion_tokens = Column(Integer, nullable=False, server_default="0", comment="输出token")
    total_tokens = Column(Integer, nullable=False, server_default="0", comment="总token")
    prompt_cache_hit_tokens = Column(Integer, nullable=False, server_default="0", comment="缓存命中token")
    prompt_cache_miss_tokens = Column(Integer, nullable=False, server_default="0", comment="缓存未命中token")
    estimated_cost = Column(Numeric(18, 8), nullable=True, comment="本次调用成本（估算或上游返回）")
    cost_currency = Column(String(8), nullable=True, comment="成本币种")
    cost_source = Column(String(16), nullable=True, comment="成本来源：estimate/provider")
    record_date = Column(Date, nullable=False, comment="记录日期（按天聚合用）")
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp(), comment="创建时间")
