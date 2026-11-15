"""订单表 ORM 模型（与 StarggleCom 共享数据库，只读映射）

管理端 user_manage.html 通过它查询订单记录。
"""
from sqlalchemy import Column, String, Integer, Text, TIMESTAMP, func
from app.config.database import Base


class OrderInfo(Base):
    """订单信息表（与 StarggleCom 共用同一张表）"""
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="自增主键")
    order_no = Column(String(64), nullable=False, unique=True, index=True, comment="业务订单号")
    user_id = Column(String(64), nullable=False, index=True, comment="用户ID")
    plan = Column(String(32), nullable=False, comment="套餐等级: free/plus/pro")
    amount_cents = Column(Integer, nullable=False, default=0, comment="金额（分）")
    currency = Column(String(8), nullable=False, server_default="USD", comment="币种")
    status = Column(String(24), nullable=False, server_default="pending",
                    comment="状态: pending/paid/cancelled/refunded/failed")
    channel = Column(String(32), nullable=False, server_default="mock",
                     comment="支付渠道: mock/creem/manual")
    provider_order_id = Column(String(128), nullable=True, comment="支付渠道订单号")
    provider_raw = Column(Text, nullable=True, comment="支付回调原始数据(JSON)")
    remark = Column(String(255), nullable=True, comment="备注")
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp(), comment="创建时间")
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(),
                        onupdate=func.current_timestamp(), comment="更新时间")

    def __repr__(self):
        return f"<OrderInfo(order_no='{self.order_no}', user_id='{self.user_id}', status='{self.status}')>"
