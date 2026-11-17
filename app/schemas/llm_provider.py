"""大模型提供商 Pydantic 校验模型"""
from pydantic import BaseModel, Field


class ProviderCreate(BaseModel):
    """新增提供商"""
    provider_name: str = Field(..., min_length=1, max_length=128, description="提供商名称")
    api_url: str = Field(..., min_length=1, max_length=512, description="API 地址")
    api_key: str = Field(..., min_length=1, max_length=512, description="API Key")
    remarks: str | None = Field(default=None, description="备注")


class ProviderUpdate(BaseModel):
    """更新提供商（全部字段可选，只更新传入的字段）"""
    provider_name: str | None = Field(default=None, min_length=1, max_length=128, description="提供商名称")
    api_url: str | None = Field(default=None, min_length=1, max_length=512, description="API 地址")
    api_key: str | None = Field(default=None, min_length=1, max_length=512, description="API Key")
    remarks: str | None = Field(default=None, description="备注")
