"""用户级配额与访问策略（网关自有表，不修改共享的 user_info）

- 每个 user_id 一行，包含每日/每月 Token 上限与访问封禁开关；
- 限额语义与项目配额一致：NULL=不限，0=禁止；
- user_id 也包含项目 Token 回落产生的 gw:<token_id> 合成ID。
"""
from sqlalchemy import BigInteger, Column, Index, String, TIMESTAMP, func

from app.config.database import Base


class UserQuotaPolicy(Base):
    __tablename__ = "user_quota_policy"

    user_id = Column(String(64), primary_key=True, nullable=False,
                     comment="用户ID（含 gw:<token_id> 合成ID）")
    daily_token_limit = Column(BigInteger, nullable=True, comment="每日Token上限；NULL=不限，0=禁止")
    monthly_token_limit = Column(BigInteger, nullable=True, comment="每月Token上限；NULL=不限，0=禁止")
    status = Column(String(8), nullable=False, server_default="active",
                    comment="访问状态：active/blocked")
    remark = Column(String(255), nullable=True, comment="备注")
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp(), comment="创建时间")
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(),
                        onupdate=func.current_timestamp(), comment="更新时间")

    __table_args__ = (
        Index("idx_user_quota_status", "status"),
    )
