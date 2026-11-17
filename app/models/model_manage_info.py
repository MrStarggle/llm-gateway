"""模型管理信息 ORM 模型"""
from sqlalchemy import BigInteger, Column, DateTime, Float, Integer, Numeric, String, Text, TIMESTAMP, func
from app.config.database import Base


class ModelManageInfo(Base):
    __tablename__ = "model_manage_info"

    # 主键：雪花算法生成的唯一 ID（存储为字符串）
    ai_model_id = Column(String(64), primary_key=True, nullable=False, comment="模型ID（雪花ID）")
    ai_model_name = Column(String(128), nullable=False, comment="模型名称")
    com_name = Column(String(128), nullable=False, comment="运营商名称")
    com_url = Column(String(512), nullable=False, comment="运营商URL")
    api_key = Column(String(512), nullable=False, comment="运营商API-Key")
    # 提供商关联：地址/密钥的配置源为 llm_provider_info，本表三个字段为调用链路直读的冗余副本
    provider_id = Column(String(64), nullable=True, index=True, comment="提供商ID（指向 llm_provider_info）")
    ai_model_type = Column(String(8), default="0", comment="0文本模型，1语音模型")
    is_using = Column(String(1), nullable=False, comment="是否使用中：1是0否")
    is_think = Column(String(1), default="0", comment="思考模式：0跟随请求，1强制开启，2强制关闭")
    is_stream = Column(String(1), default="1", comment="流式：1是0否")
    # 集群类型：async1..async9（对应管理页「集群1..集群9」）。
    # 同一集群内的启用模型按轮询调度；原 is_base 字段已废弃并在迁移中删除。
    async_type = Column(String(8), nullable=False, server_default="async1", index=True,
                        comment="集群类型：async1..async9")
    # 模型级请求参数覆盖：非 NULL 时覆盖客户端请求体同名参数，NULL 表示沿用客户端值。
    # temperature 与 top_p 为互斥采样参数（同时配置时仅 temperature 生效）。
    temperature = Column(Float, nullable=True, comment="覆盖请求体temperature；NULL=不覆盖")
    top_p = Column(Float, nullable=True, comment="覆盖请求体top_p；NULL=不覆盖（与temperature互斥）")
    top_k = Column(Integer, nullable=True, comment="覆盖请求体top_k；NULL=不覆盖")
    max_tokens = Column(Integer, nullable=True, comment="覆盖请求体max_tokens；NULL=不覆盖")
    # 计费单价（每 1M token），用于估算用量成本；NULL 表示不计算
    input_price_per_1m = Column(Numeric(18, 6), nullable=True, comment="输入单价（每 1M token）")
    output_price_per_1m = Column(Numeric(18, 6), nullable=True, comment="输出单价（每 1M token）")
    price_currency = Column(String(8), nullable=False, server_default="USD", comment="价格币种")
    price_source = Column(String(16), nullable=True, comment="价格来源：manual/provider")
    price_updated_at = Column(DateTime, nullable=True, comment="价格更新时间")
    extra_config = Column(Text, comment="存储语音模型的音色、语速、音调等JSON配置")
    # 排序批次号：普通新增生成新批次，复制模型沿用源模型批次，
    # 列表按 batch_no DESC, created_at ASC 排序，使副本始终紧跟源模型。
    batch_no = Column(BigInteger, nullable=True, index=True, comment="排序批次号：同批次模型相邻展示")
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp(), comment="创建时间")
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(),
                        onupdate=func.current_timestamp(), comment="更新时间")
    remarks = Column(Text, comment="备注")
