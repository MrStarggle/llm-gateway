"""渠道健康与路由配置 Pydantic 校验模型"""
from pydantic import BaseModel, Field


class RoutingConfigUpdate(BaseModel):
    """集群路由配置"""
    strategy: str = Field(default="round_robin", pattern=r"^(round_robin|cost_first|latency_first)$")
    retry_max: int = Field(default=1, ge=0, le=2, description="首次之外的重试次数，总尝试 <= 3")
    failure_threshold: int = Field(default=5, ge=1, le=100, description="连续失败熔断阈值")
    cooldown_seconds: int = Field(default=60, ge=0, le=3600, description="熔断冷却秒数")
    output_ratio: float = Field(default=0.3, ge=0, le=1, description="成本估算输出占比")
    enabled: int = Field(default=1, ge=0, le=1, description="是否启用健康路由")


class LogSettingsUpdate(BaseModel):
    """LLM 报文日志开关"""
    enabled: bool
