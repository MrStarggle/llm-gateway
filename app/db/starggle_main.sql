CREATE TABLE IF NOT EXISTS model_manage_info
(
    ai_model_id   TEXT NOT NULL  primary key,       -- 模型ID (SQLite 使用 AUTOINCREMENT 而非 AUTO_INCREMENT)
    ai_model_name TEXT NOT NULL,                    -- 模型名称
    com_name      TEXT NOT NULL,                    -- 运营商名称
    com_url       TEXT NOT NULL,                    -- 运营商url
    api_key       TEXT NOT NULL,                    -- 运营商api-key
    ai_model_type TEXT DEFAULT '0',                 -- 0文本模型，1语音模型
    is_using      TEXT NOT NULL,                    -- 是否使用中：1是0否
    is_think      TEXT DEFAULT '0',                 -- 0默认，1思考模型,2混合模型
    is_stream     TEXT DEFAULT '1',                 -- 流式：1是0否
    is_base       TEXT DEFAULT '0',                 -- 基础默认模型：1是0否，对应之前的默认deepseek-flash
    is_main       TEXT DEFAULT '0',                 -- 主模型：1是0否
    extra_config  TEXT,                             --存储语音模型的音色、语速、音调等 JSON 配置
    created_at    TIMESTAMP default CURRENT_TIMESTAMP not null,
    updated_at    TIMESTAMP default CURRENT_TIMESTAMP not null,
    remarks        TEXT,                            -- 备注
    UNIQUE (ai_model_id)                              -- 模型 ID 唯一
    );
