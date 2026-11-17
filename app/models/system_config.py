"""系统运行配置（键值对）"""
from sqlalchemy import Column, String, Text, TIMESTAMP, func

from app.config.database import Base


class SystemConfig(Base):
    __tablename__ = "system_config"

    config_key = Column(String(64), primary_key=True, nullable=False, comment="配置键")
    config_value = Column(Text, nullable=False, comment="配置值")
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(),
                        onupdate=func.current_timestamp(), comment="更新时间")
