"""集群路由配置 ORM 模型"""
from sqlalchemy import Column, Float, Integer, String, TIMESTAMP, func

from app.config.database import Base


class ClusterRoutingConfig(Base):
    __tablename__ = "cluster_routing_config"

    async_type = Column(String(8), primary_key=True, nullable=False, comment="集群：async1..async9")
    strategy = Column(String(16), nullable=False, server_default="round_robin",
                      comment="路由策略：round_robin/cost_first/latency_first")
    retry_max = Column(Integer, nullable=False, server_default="1",
                       comment="首次之外的重试次数（总尝试 <= 1+retry_max，上限3）")
    failure_threshold = Column(Integer, nullable=False, server_default="5",
                               comment="连续失败多少次熔断")
    cooldown_seconds = Column(Integer, nullable=False, server_default="60",
                              comment="熔断冷却秒数")
    output_ratio = Column(Float, nullable=False, server_default="0.3",
                          comment="成本估算假设的输出占比")
    enabled = Column(Integer, nullable=False, server_default="1", comment="是否启用健康路由：1是0否")
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(),
                        onupdate=func.current_timestamp(), comment="更新时间")
