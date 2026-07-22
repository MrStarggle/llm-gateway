"""用户信息表（与 StarggleCom 共享数据库，只读映射）"""
from sqlalchemy import Column, String, Text, TIMESTAMP, text
from sqlalchemy.sql import func
from app.config.database import Base


class UserInfo(Base):
    """用户个人信息表（与 StarggleCom 共用同一张表）"""
    __tablename__ = "user_info"

    user_id = Column(String(64), primary_key=True, nullable=False, comment="用户ID")
    user_name = Column(String(128), nullable=False, comment="用户名")
    user_head_img = Column(String(512), nullable=False, comment="用户头像")
    user_basic_info = Column(Text, nullable=True, comment="用户基本信息")

    system_settings = Column(Text, nullable=True, comment="系统设置")
    compulsory_settings = Column(Text, nullable=True, comment="强制命令设定")
    reply_length_start = Column(String(8), nullable=True, server_default="1")
    reply_length_end = Column(String(8), nullable=True, server_default="1500")

    login_id = Column(String(256), nullable=False, unique=True, comment="登录ID")
    password = Column(String(256), nullable=False, comment="密码")

    phone = Column(String(64), nullable=True, comment="手机号")
    email = Column(String(256), nullable=False, unique=True, comment="邮箱")

    ip_addr = Column(String(64), nullable=False, server_default="127.0.0.1")
    routing_model_id = Column(String(64), nullable=True)
    membership_level = Column(String(32), nullable=False, server_default="1")

    created_at = Column(TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = Column(TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP"), onupdate=func.current_timestamp())

    def __repr__(self):
        return f"<UserInfo(user_id='{self.user_id}', user_name='{self.user_name}')>"
