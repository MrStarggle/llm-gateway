"""模型管理 Pydantic 校验模型"""
import json

from pydantic import BaseModel, Field, field_validator


class ModelManageCreate(BaseModel):
    """新增模型"""
    ai_model_name: str = Field(..., min_length=1, max_length=128, description="模型名称")
    com_name: str = Field(..., min_length=1, max_length=128, description="运营商名称")
    com_url: str = Field(..., min_length=1, max_length=512, description="运营商URL")
    api_key: str = Field(..., min_length=1, max_length=512, description="运营商API-Key")
    ai_model_type: str = Field(default="0", pattern=r"^[01]$", description="0文本模型，1语音模型")
    is_using: str = Field(..., pattern=r"^[01]$", description="是否使用中：1是0否")
    is_think: str = Field(default="0", pattern=r"^[012]$", description="0默认，1思考模型，2混合模型")
    is_stream: str = Field(default="1", pattern=r"^[01]$", description="流式：1是0否")
    is_base: str = Field(default="0", pattern=r"^[01]$", description="基础默认模型：1是0否")
    extra_config: str | None = Field(default=None, description="语音模型JSON配置")
    remarks: str | None = Field(default=None, description="备注")

    @field_validator("extra_config")
    @classmethod
    def validate_extra_config_json(cls, v: str | None) -> str | None:
        if v is not None and v.strip():
            try:
                json.loads(v)
            except json.JSONDecodeError as e:
                raise ValueError(f"extra_config 必须是有效的 JSON: {e}")
        return v


class ModelManageUpdate(BaseModel):
    """更新模型（全部字段可选，只更新传入的字段）"""
    ai_model_name: str | None = Field(default=None, min_length=1, max_length=128, description="模型名称")
    com_name: str | None = Field(default=None, min_length=1, max_length=128, description="运营商名称")
    com_url: str | None = Field(default=None, min_length=1, max_length=512, description="运营商URL")
    api_key: str | None = Field(default=None, min_length=1, max_length=512, description="运营商API-Key")
    ai_model_type: str | None = Field(default=None, pattern=r"^[01]$", description="0文本模型，1语音模型")
    is_using: str | None = Field(default=None, pattern=r"^[01]$", description="是否使用中：1是0否")
    is_think: str | None = Field(default=None, pattern=r"^[012]$", description="0默认，1思考模型，2混合模型")
    is_stream: str | None = Field(default=None, pattern=r"^[01]$", description="流式：1是0否")
    is_base: str | None = Field(default=None, pattern=r"^[01]$", description="基础默认模型：1是0否")
    extra_config: str | None = Field(default=None, description="语音模型JSON配置")
    remarks: str | None = Field(default=None, description="备注")

    @field_validator("extra_config")
    @classmethod
    def validate_extra_config_json(cls, v: str | None) -> str | None:
        if v is not None and v.strip():
            try:
                json.loads(v)
            except json.JSONDecodeError as e:
                raise ValueError(f"extra_config 必须是有效的 JSON: {e}")
        return v


class ModelManageQuery(BaseModel):
    """查询模型列表参数"""
    com_name: str | None = Field(default=None, description="按运营商模糊搜索")
    ai_model_name: str | None = Field(default=None, description="按模型名称模糊搜索")
    is_using: str | None = Field(default=None, pattern=r"^[01]$", description="按使用状态筛选")
    is_base: str | None = Field(default=None, pattern=r"^[01]$", description="按基础模型筛选")
    ai_model_type: str | None = Field(default=None, pattern=r"^[01]$", description="按模型类型筛选")
