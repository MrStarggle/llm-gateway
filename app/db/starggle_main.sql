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

CREATE TABLE IF NOT EXISTS user_token_info
(
    id                INT AUTO_INCREMENT primary key, -- 自增主键
    user_id           VARCHAR(64)   NOT NULL,         -- 用户ID
    model             VARCHAR(128)  NOT NULL DEFAULT '',   -- 模型名称
    purpose           VARCHAR(16)   NOT NULL DEFAULT 'main', -- 用途: main/async
    is_stream         INT           NOT NULL DEFAULT 0, -- 是否流式: 1是0否
    prompt_tokens     INT           NOT NULL DEFAULT 0, -- 输入token
    completion_tokens INT           NOT NULL DEFAULT 0, -- 输出token
    total_tokens      INT           NOT NULL DEFAULT 0, -- 总token
    prompt_cache_hit_tokens  INT    NOT NULL DEFAULT 0, -- 缓存命中token
    prompt_cache_miss_tokens INT    NOT NULL DEFAULT 0, -- 缓存未命中token
    record_date       DATE          NOT NULL,         -- 记录日期（按天聚合用）
    created_at        TIMESTAMP default CURRENT_TIMESTAMP not null, -- 创建时间
    KEY idx_user_id (user_id),                        -- 用户ID索引
    KEY idx_record_date (record_date)                 -- 日期索引
    );
