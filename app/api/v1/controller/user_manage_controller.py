"""用户管理 控制器（管理端，需要 JWT 鉴权）

- GET /user-manage/list            用户列表（含积分余额、等级、今日用量）
- POST /user-manage/recharge-points 手动充值/扣减积分
- GET /user-manage/orders          订单列表
"""
import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.database import get_db
from app.services import user_manage_service
from app.utils.response import ResponseFactory
from app.utils.admin_auth import require_admin_user

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(require_admin_user)])


class RechargePointsBody(BaseModel):
    """手动充值/扣减积分请求体（points 正数为充值、负数为扣减）"""
    user_id: str = Field(..., min_length=1, max_length=64, description="用户ID")
    points: int = Field(..., ge=-10_000_000, le=10_000_000, description="积分变动量（正充负扣）")
    remark: str | None = Field(default=None, max_length=255, description="备注")


def _user_row(user, today_usage: int) -> dict:
    """序列化单条用户记录"""
    level = user_manage_service.effective_level_of(user)
    return {
        "userId": user.user_id,
        "userName": user.user_name,
        "email": user.email,
        "loginId": user.login_id,
        "pointBalance": int(user.point_balance or 0),
        "membershipLevel": level,
        "todayUsed": today_usage,
        "createdAt": user.created_at.isoformat() if user.created_at else None,
    }


@router.get("/list")
async def list_users(
    page: int = 1,
    page_size: int = 20,
    keyword: str = "",
    db: AsyncSession = Depends(get_db),
):
    """用户列表（分页 + 关键字模糊搜索）"""
    page = max(page, 1)
    page_size = max(1, min(page_size, 100))

    users, total = await user_manage_service.list_users(db, keyword, page, page_size)
    usage_map = await user_manage_service.get_today_usage_map(db, [u.user_id for u in users])

    data = [_user_row(u, usage_map.get(u.user_id, 0)) for u in users]
    return ResponseFactory.ok(data={"list": data, "total": total}, message="查询成功")


@router.post("/recharge-points")
async def recharge_points(
    body: RechargePointsBody,
    db: AsyncSession = Depends(get_db),
):
    """管理员手动充值/扣减积分（创建一笔 paid 订单 + 更新余额）"""
    try:
        result = await user_manage_service.grant_points(
            db, body.user_id, body.points, body.remark
        )
    except ValueError as e:
        return ResponseFactory.bad_request(message=str(e))
    if result is None:
        return ResponseFactory.bad_request(message="用户不存在")

    order, user = result
    return ResponseFactory.ok(data={
        "orderNo": order.order_no,
        "userId": user.user_id,
        "points": body.points,
        "pointBalance": int(user.point_balance or 0),
    }, message="充值成功" if body.points > 0 else "扣减成功")


@router.get("/orders")
async def list_orders(
    user_id: str = "",
    status: str = "",
    page: int = 1,
    page_size: int = 20,
    db: AsyncSession = Depends(get_db),
):
    """订单列表（可按用户ID/状态筛选）"""
    page = max(page, 1)
    page_size = max(1, min(page_size, 100))

    orders, total = await user_manage_service.list_orders(db, user_id, status, page, page_size)

    def _order_row(o):
        return {
            "orderNo": o.order_no,
            "userId": o.user_id,
            "plan": o.plan,
            "amountCents": o.amount_cents,
            "currency": o.currency,
            "status": o.status,
            "channel": o.channel,
            "providerOrderId": o.provider_order_id,
            "remark": o.remark,
            "createdAt": o.created_at.isoformat() if o.created_at else None,
        }

    return ResponseFactory.ok(data={"list": [_order_row(o) for o in orders], "total": total}, message="查询成功")
