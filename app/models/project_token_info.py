"""项目 API Token ORM 模型

只保存 Token 的 SHA-256 哈希，明文仅在创建/轮换时返回一次。
"""
from sqlalchemy import Column, DateTime, String, Text, TIMESTAMP, UniqueConstraint, func

from app.config.database import Base


class ProjectTokenInfo(Base):
    __tablename__ = "project_token_info"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_project_token_name"),
    )

    token_id = Column(String(64), primary_key=True, nullable=False, comment="Token ID（雪花ID）")
    project_id = Column(String(64), nullable=False, index=True, comment="所属项目ID")
    name = Column(String(128), nullable=False, comment="Token 名称，如 web-prod")
    token_hash = Column(String(64), nullable=False, unique=True, comment="Token SHA-256 哈希")
    token_prefix = Column(String(20), nullable=False, comment="展示用前缀")
    token_suffix = Column(String(8), nullable=False, comment="展示用后4位")
    allowed_models = Column(Text, nullable=True, comment="允许的模型 JSON 数组，支持通配；NULL=不限")
    expires_at = Column(DateTime, nullable=True, comment="过期时间；NULL=不过期")
    status = Column(String(8), nullable=False, server_default="active", index=True,
                    comment="状态：active/revoked")
    last_used_at = Column(DateTime, nullable=True, comment="最后使用时间")
    remarks = Column(Text, nullable=True, comment="备注")
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp(), comment="创建时间")
