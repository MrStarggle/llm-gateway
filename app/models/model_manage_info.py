"""模型管理信息 ORM 模型"""
from sqlalchemy import Column, String, Text, TIMESTAMP, func
from app.config.database import Base


class ModelManageInfo(Base):
    __tablename__ = "model_manage_info"

    # 主键：雪花算法生成的唯一 ID（存储为字符串）
    ai_model_id = Column(String(64), primary_key=True, nullable=False, comment="模型ID（雪花ID）")
    ai_model_name = Column(String(128), nullable=False, comment="模型名称")
    com_name = Column(String(128), nullable=False, comment="运营商名称")
    com_url = Column(String(512), nullable=False, comment="运营商URL")
    api_key = Column(String(512), nullable=False, comment="运营商API-Key")
    ai_model_type = Column(String(8), default="0", comment="0文本模型，1语音模型")
    is_using = Column(String(1), nullable=False, comment="是否使用中：1是0否")
    is_think = Column(String(1), default="0", comment="0默认，1思考模型，2混合模型")
    is_stream = Column(String(1), default="1", comment="流式：1是0否")
    is_base = Column(String(1), default="0", comment="基础默认模型：1是0否")
    extra_config = Column(Text, comment="存储语音模型的音色、语速、音调等JSON配置")
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp(), comment="创建时间")
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(),
                        onupdate=func.current_timestamp(), comment="更新时间")
    remarks = Column(Text, comment="备注")
