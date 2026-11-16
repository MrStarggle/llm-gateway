"""按「一次生成」聚合的钻石计费台账（幂等结算）

- 每个 generation_id 一行：同一次 AI 生成触发的所有 LLM 调用共用该 ID；
- 结算可重复执行：已扣钻石数只增不减，后续迟到/补记的用量按差额补扣；
- 口径：实际成本（美元）× 3 后再按 1 美元 = 50 钻石折算，向上取整。
"""
from sqlalchemy import BigInteger, Column, DateTime, Index, Integer, Numeric, String, TIMESTAMP, func

from app.config.database import Base


class GenerationBilling(Base):
    __tablename__ = "generation_billing"

    generation_id = Column(String(64), primary_key=True, nullable=False,
                           comment="生成ID（同一次AI生成的所有LLM调用）")
    user_id = Column(String(64), nullable=False, comment="用户ID")
    call_count = Column(Integer, nullable=False, server_default="0",
                        comment="本次生成已记账的LLM调用次数")
    total_tokens = Column(BigInteger, nullable=False, server_default="0",
                          comment="本次生成累计token")
    cost_usd = Column(Numeric(18, 8), nullable=False, server_default="0",
                      comment="本次生成累计成本（美元）")
    diamonds_charged = Column(Integer, nullable=False, server_default="0",
                              comment="已扣钻石数（累计向上取整后的目标值）")
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp(), comment="创建时间")
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(),
                        onupdate=func.current_timestamp(), comment="更新时间")
    settled_at = Column(DateTime, nullable=True, comment="最后结算时间")

    __table_args__ = (
        Index("idx_generation_billing_user", "user_id"),
        Index("idx_generation_billing_settled", "settled_at"),
    )
