"""模型管理 Pydantic 校验模型"""
import json

from pydantic import BaseModel, Field, field_validator


class ModelManageCreate(BaseModel):
    """新增模型

    新流程通过 provider_id 关联大模型提供商，由服务端回填 com_name/com_url/api_key；
    仅传 com_name/com_url/api_key 的旧调用方式仍然兼容。
    """
    ai_model_name: str = Field(..., min_length=1, max_length=128, description="模型名称")
    provider_id: str | None = Field(default=None, min_length=1, max_length=64, description="提供商ID")
    com_name: str | None = Field(default=None, min_length=1, max_length=128, description="运营商名称")
    com_url: str | None = Field(default=None, min_length=1, max_length=512, description="运营商URL")
    api_key: str | None = Field(default=None, min_length=1, max_length=512, description="运营商API-Key")
    ai_model_type: str = Field(default="0", pattern=r"^[01]$", description="0文本模型，1语音模型")
    batch_no: int | None = Field(default=None, description="排序批次号；复制模型时传入源模型批次")
    is_using: str = Field(..., pattern=r"^[01]$", description="是否使用中：1是0否")
    is_think: str = Field(default="0", pattern=r"^[012]$", description="0跟随请求，1强制开启，2强制关闭")
    is_stream: str = Field(default="1", pattern=r"^[01]$", description="流式：1是0否")
    async_type: str = Field(default="async1", pattern=r"^async[1-9]$", description="集群类型：async1..async9")
    temperature: float | None = Field(default=None, ge=0, le=2, description="覆盖请求体temperature；null=不覆盖（与top_p互斥）")
    top_p: float | None = Field(default=None, ge=0, le=1, description="覆盖请求体top_p；null=不覆盖（与temperature互斥）")
    top_k: int | None = Field(default=None, ge=1, le=1000, description="覆盖请求体top_k；null=不覆盖（部分厂商不支持）")
    max_tokens: int | None = Field(default=None, ge=1, le=100000, description="覆盖请求体max_tokens；null=不覆盖")
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
    provider_id: str | None = Field(default=None, min_length=1, max_length=64, description="提供商ID（传入则同步地址与密钥）")
    com_name: str | None = Field(default=None, min_length=1, max_length=128, description="运营商名称")
    com_url: str | None = Field(default=None, min_length=1, max_length=512, description="运营商URL")
    api_key: str | None = Field(default=None, min_length=1, max_length=512, description="运营商API-Key")
    ai_model_type: str | None = Field(default=None, pattern=r"^[01]$", description="0文本模型，1语音模型")
    is_using: str | None = Field(default=None, pattern=r"^[01]$", description="是否使用中：1是0否")
    is_think: str | None = Field(default=None, pattern=r"^[012]$", description="0跟随请求，1强制开启，2强制关闭")
    is_stream: str | None = Field(default=None, pattern=r"^[01]$", description="流式：1是0否")
    async_type: str | None = Field(default=None, pattern=r"^async[1-9]$", description="集群类型：async1..async9")
    temperature: float | None = Field(default=None, ge=0, le=2, description="覆盖请求体temperature；null=不覆盖（与top_p互斥）")
    top_p: float | None = Field(default=None, ge=0, le=1, description="覆盖请求体top_p；null=不覆盖（与temperature互斥）")
    top_k: int | None = Field(default=None, ge=1, le=1000, description="覆盖请求体top_k；null=不覆盖（部分厂商不支持）")
    max_tokens: int | None = Field(default=None, ge=1, le=100000, description="覆盖请求体max_tokens；null=不覆盖")
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
    provider_id: str | None = Field(default=None, description="按提供商ID筛选")
    com_name: str | None = Field(default=None, description="按运营商模糊搜索")
    ai_model_name: str | None = Field(default=None, description="按模型名称模糊搜索")
    is_using: str | None = Field(default=None, pattern=r"^[01]$", description="按使用状态筛选")
    async_type: str | None = Field(default=None, pattern=r"^async[1-9]$", description="按集群类型筛选")
    ai_model_type: str | None = Field(default=None, pattern=r"^[01]$", description="按模型类型筛选")
