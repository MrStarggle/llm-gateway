"""项目（团队）ORM 模型"""
from sqlalchemy import BigInteger, Column, Integer, Numeric, String, Text, TIMESTAMP, func

from app.config.database import Base


class ProjectInfo(Base):
    __tablename__ = "project_info"

    project_id = Column(String(64), primary_key=True, nullable=False, comment="项目ID（雪花ID）")
    project_name = Column(String(128), nullable=False, unique=True, comment="项目/团队名称")
    status = Column(String(8), nullable=False, server_default="active", index=True,
                    comment="状态：active/disabled")
    # 配额：NULL=不限，0=禁止
    daily_call_limit = Column(Integer, nullable=True, comment="每日调用次数上限；NULL=不限，0=禁止")
    monthly_call_limit = Column(Integer, nullable=True, comment="每月调用次数上限；NULL=不限，0=禁止")
    daily_token_limit = Column(BigInteger, nullable=True, comment="每日Token上限；NULL=不限，0=禁止")
    monthly_token_limit = Column(BigInteger, nullable=True, comment="每月Token上限；NULL=不限，0=禁止")
    daily_cost_limit = Column(Numeric(18, 8), nullable=True, comment="每日成本上限（项目币种）；NULL=不限")
    monthly_cost_limit = Column(Numeric(18, 8), nullable=True, comment="每月成本上限（项目币种）；NULL=不限")
    cost_currency = Column(String(8), nullable=False, server_default="USD", comment="成本币种")
    remarks = Column(Text, nullable=True, comment="备注")
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp(), comment="创建时间")
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(),
                        onupdate=func.current_timestamp(), comment="更新时间")
