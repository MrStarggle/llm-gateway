"""项目与 API Token Pydantic 校验模型"""
from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class ProjectCreate(BaseModel):
    """新建项目"""
    project_name: str = Field(..., min_length=1, max_length=128, description="项目/团队名称")
    status: str = Field(default="active", pattern=r"^(active|disabled)$", description="状态")
    daily_call_limit: int | None = Field(default=None, ge=0, description="每日调用次数上限；null=不限")
    monthly_call_limit: int | None = Field(default=None, ge=0, description="每月调用次数上限；null=不限")
    daily_token_limit: int | None = Field(default=None, ge=0, description="每日Token上限；null=不限")
    monthly_token_limit: int | None = Field(default=None, ge=0, description="每月Token上限；null=不限")
    daily_cost_limit: float | None = Field(default=None, ge=0, description="每日成本上限；null=不限")
    monthly_cost_limit: float | None = Field(default=None, ge=0, description="每月成本上限；null=不限")
    cost_currency: str = Field(default="USD", max_length=8, description="成本币种")
    remarks: str | None = Field(default=None, description="备注")

    @field_validator("cost_currency")
    @classmethod
    def normalize_currency(cls, v: str) -> str:
        value = (v or "USD").strip().upper()
        if not value:
            return "USD"
        if len(value) > 8 or not value.isalnum():
            raise ValueError("cost_currency 只能是 2-8 位字母或数字")
        return value


class ProjectUpdate(BaseModel):
    """更新项目（只更新传入字段；显式传 null 表示清空限额）"""
    project_name: str | None = Field(default=None, min_length=1, max_length=128)
    status: str | None = Field(default=None, pattern=r"^(active|disabled)$")
    daily_call_limit: int | None = Field(default=None, ge=0)
    monthly_call_limit: int | None = Field(default=None, ge=0)
    daily_token_limit: int | None = Field(default=None, ge=0)
    monthly_token_limit: int | None = Field(default=None, ge=0)
    daily_cost_limit: float | None = Field(default=None, ge=0)
    monthly_cost_limit: float | None = Field(default=None, ge=0)
    cost_currency: str | None = Field(default=None, max_length=8)
    remarks: str | None = None

    @field_validator("cost_currency")
    @classmethod
    def normalize_currency(cls, v: str | None) -> str | None:
        if v is None:
            return None
        value = v.strip().upper()
        if not value:
            return "USD"
        if len(value) > 8 or not value.isalnum():
            raise ValueError("cost_currency 只能是 2-8 位字母或数字")
        return value


class TokenCreate(BaseModel):
    """新建项目 Token"""
    name: str = Field(..., min_length=1, max_length=128, description="Token 名称，如 web-prod")
    allowed_models: list[str] | None = Field(
        default=None, max_length=50, description="允许的模型，支持 fnmatch 通配；null=不限",
    )
    expires_at: datetime | None = Field(default=None, description="过期时间；null=不过期")
    remarks: str | None = Field(default=None, description="备注")

    @field_validator("allowed_models")
    @classmethod
    def validate_allowed_models(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        result: list[str] = []
        for item in v:
            pattern = (item or "").strip()
            if not pattern:
                continue
            if len(pattern) > 128:
                raise ValueError("allowed_models 中的模式长度不能超过 128")
            if pattern not in result:
                result.append(pattern)
        return result or None


class TokenRotate(BaseModel):
    """轮换 Token（可选更新名称/过期时间，不传则沿用原值）"""
    name: str | None = Field(default=None, min_length=1, max_length=128)
    expires_at: datetime | None = Field(default=None, description="新的过期时间；null=沿用原值")
    remarks: str | None = None
