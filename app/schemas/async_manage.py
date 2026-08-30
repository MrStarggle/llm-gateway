"""异步LLM总控 Pydantic 校验模型

13 行固定种子数据（purpose 为业务主键），只提供更新，不提供新增/删除。
"""
from pydantic import BaseModel, Field


class AsyncManageUpdate(BaseModel):
    """更新异步LLM总控（全部字段可选，只更新传入的字段）"""
    request_name: str | None = Field(default=None, min_length=1, max_length=64, description="用途中文名")
    # 空串表示清空绑定（service 层归一为 NULL 落库）→ 该路回落 is_base=1 轮询
    ai_model_id: str | None = Field(default=None, max_length=64, description="绑定模型ID；空串=清空绑定回落轮询")
    is_think: str | None = Field(default=None, pattern=r"^[01]$", description="请求级思考模式：1强制开/0强制关/null跟随客户端（不注入，与 model_manage_info.is_think 模型属性不同义）")
    temperature: float | None = Field(default=None, ge=0, le=2, description="覆盖请求体temperature；null=不覆盖")
    max_tokens: int | None = Field(default=None, ge=1, le=100000, description="覆盖请求体max_tokens；null=不覆盖")
    is_using: str | None = Field(default=None, pattern=r"^[01]$", description="是否启用该路配置：1是0否")
    remarks: str | None = Field(default=None, description="备注")
