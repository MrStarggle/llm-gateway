"""大模型提供商配置 ORM 模型

模型配置（model_manage_info）不再各自维护 com_url / api_key：
同一提供商的地址与密钥只在这里配置一次，模型通过 provider_id 关联。
提供商更新时由 llm_provider_service 级联刷新关联模型的冗余字段，
保证调用链路（call_manage_controller）读取 model_manage_info 的既有逻辑不变。
"""
from sqlalchemy import Column, String, Text, TIMESTAMP, func
from app.config.database import Base


class LlmProviderInfo(Base):
    __tablename__ = "llm_provider_info"

    provider_id = Column(String(64), primary_key=True, nullable=False, comment="提供商ID（雪花ID）")
    provider_name = Column(String(128), nullable=False, unique=True, comment="提供商名称")
    api_url = Column(String(512), nullable=False, comment="API 地址")
    api_key = Column(String(512), nullable=False, comment="API Key")
    remarks = Column(Text, comment="备注")
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp(), comment="创建时间")
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(),
                        onupdate=func.current_timestamp(), comment="更新时间")
