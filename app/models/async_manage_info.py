"""异步LLM总控 ORM 模型

13 路异步LLM请求（async1..async13）各自的路由/参数配置表：
- purpose 为主键，13 行固定种子数据（见 app/services/async_manage_service.py ASYNC_PURPOSE_SEED）
- ai_model_id 为空或 is_using="0" 时该路回落到 model_manage_info.is_base="1" 模型池轮询
- temperature/max_tokens 为 NULL 时表示不覆盖请求体中的客户端值
"""
from sqlalchemy import Column, String, Text, TIMESTAMP, Float, Integer, func
from app.config.database import Base


class AsyncManageInfo(Base):
    __tablename__ = "async_manage_info"

    # 主键：用途标识（业务键，客户端 X-Starggle-Purpose 头原值）
    purpose = Column(String(16), primary_key=True, nullable=False, comment="用途标识: async1..async13")
    request_name = Column(String(64), nullable=False, comment="用途中文名（管理页展示）")
    ai_model_id = Column(String(64), nullable=True, comment="绑定模型ID（指向 model_manage_info.ai_model_id，逻辑引用不建外键）；空=回落is_base=1轮询")
    # 注意：本字段是「请求级思考模式」，与 model_manage_info.is_think（模型属性：0默认/1思考模型/2混合）语义不同
    is_think = Column(String(1), nullable=True, default="0", comment="请求级思考模式：1强制开/0强制关/NULL跟随客户端（不注入）")
    temperature = Column(Float, nullable=True, comment="覆盖请求体temperature；NULL=不覆盖（沿用客户端值）")
    max_tokens = Column(Integer, nullable=True, comment="覆盖请求体max_tokens；NULL=不覆盖（沿用客户端值）")
    is_using = Column(String(1), nullable=False, default="0", comment="是否启用该路配置：1是0否（0=回落轮询）")
    remarks = Column(Text, comment="备注")
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp(), comment="创建时间")
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(),
                        onupdate=func.current_timestamp(), comment="更新时间")
