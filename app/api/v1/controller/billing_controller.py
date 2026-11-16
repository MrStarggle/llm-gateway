"""钻石计费 控制器（内部调用：生成前预检、生成后结算）

- POST /billing/precheck  生成前预检：回补旧账后判断余额；余额为负返回 code=402；
- POST /billing/settle    按 generation_id 汇总本次生成成本并扣钻（幂等）。

安全边界：与 chat/completions 相同，信任内部调用方传入的 user_id，网关不应直接暴露公网。
"""
import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.database import get_db
from app.services import billing_service
from app.utils.response import ResponseFactory

logger = logging.getLogger(__name__)

router = APIRouter()


class PrecheckBody(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=64, description="用户ID")


class SettleBody(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=64, description="用户ID")
    generation_id: str = Field(..., min_length=1, max_length=64,
                               description="生成ID（同一次AI生成的所有LLM调用）")


@router.post("/precheck")
async def precheck(body: PrecheckBody, db: AsyncSession = Depends(get_db)):
    """生成前预检：余额 >= 0 放行，余额 < 0 返回 402（HTTP 仍为 200，码在 body.code）。"""
    result = await billing_service.precheck(db, body.user_id)
    if result.get("blocked"):
        return ResponseFactory.custom(
            402, False, result.get("message") or "钻石余额不足", data=result)
    return ResponseFactory.ok(data=result)


@router.post("/settle")
async def settle(body: SettleBody, db: AsyncSession = Depends(get_db)):
    """结算一次生成：汇总该 generation_id 的所有调用成本，×3 后折算钻石扣除。"""
    result = await billing_service.settle_generation(
        db, body.user_id, body.generation_id)
    if result is None:
        return ResponseFactory.bad_request(
            message="结算失败：用户或生成记录不存在",
            data={"userId": body.user_id, "generationId": body.generation_id})
    return ResponseFactory.ok(data=result)
