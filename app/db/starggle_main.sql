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
    extra_config  TEXT,                             -- 存储语音模型的音色、语速、音调等 JSON 配置
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
    purpose           VARCHAR(16)   NOT NULL DEFAULT 'main', -- 用途: main/async/async1..async13（异步分路）
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

CREATE TABLE IF NOT EXISTS orders
(
    id                 BIGINT       NOT NULL AUTO_INCREMENT PRIMARY KEY COMMENT '自增主键',
    order_no           VARCHAR(64)  NOT NULL UNIQUE COMMENT '业务订单号',
    user_id            VARCHAR(64)  NOT NULL COMMENT '用户ID',
    plan               VARCHAR(32)  NOT NULL COMMENT '套餐等级: free/plus/pro',
    amount_cents       INT          NOT NULL DEFAULT 0 COMMENT '金额（分）',
    currency           VARCHAR(8)   NOT NULL DEFAULT 'USD' COMMENT '币种',
    status             VARCHAR(24)  NOT NULL DEFAULT 'pending' COMMENT '状态: pending/paid/cancelled/refunded/failed',
    channel            VARCHAR(32)  NOT NULL DEFAULT 'mock' COMMENT '支付渠道: mock/creem/manual',
    provider_order_id  VARCHAR(128) NULL COMMENT '支付渠道订单号',
    provider_raw       TEXT         NULL COMMENT '支付回调原始数据(JSON)',
    remark             VARCHAR(255) NULL COMMENT '备注',
    created_at         TIMESTAMP    DEFAULT CURRENT_TIMESTAMP NOT NULL COMMENT '创建时间',
    updated_at         TIMESTAMP    DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP NOT NULL COMMENT '更新时间',
    KEY idx_orders_user_id (user_id),
    KEY idx_orders_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='订单表';

-- 异步LLM总控：13 路异步请求（X-Starggle-Purpose: async1..async13）的分路路由/参数配置
-- purpose 为业务主键，13 行固定种子数据由启动时 seed_async_manage_configs() 补齐（只插缺失行）
-- ai_model_id 为空或 is_using='0' 时该路回落 model_manage_info.is_base='1' 基础模型轮询
-- temperature/max_tokens 为 NULL 表示不覆盖（沿用客户端请求体值）
CREATE TABLE IF NOT EXISTS async_manage_info
(
    purpose      VARCHAR(16)  NOT NULL PRIMARY KEY COMMENT '用途标识: async1..async13（客户端 X-Starggle-Purpose 原值）',
    request_name VARCHAR(64)  NOT NULL COMMENT '用途中文名（管理页展示）',
    ai_model_id  VARCHAR(64)  NULL COMMENT '绑定模型ID（指向 model_manage_info.ai_model_id，逻辑引用不建外键）；空=回落轮询',
    is_think     VARCHAR(1)   NULL DEFAULT '0' COMMENT '请求级思考模式：1强制开/0强制关/NULL跟随客户端不注入（注意与 model_manage_info.is_think 模型属性不同义）',
    temperature  FLOAT        NULL COMMENT '覆盖请求体temperature；NULL=不覆盖',
    max_tokens   INT          NULL COMMENT '覆盖请求体max_tokens；NULL=不覆盖',
    is_using     VARCHAR(1)   NOT NULL DEFAULT '0' COMMENT '是否启用该路配置：1是0否（0=回落轮询）',
    remarks      TEXT         NULL COMMENT '备注',
    created_at   TIMESTAMP    DEFAULT CURRENT_TIMESTAMP NOT NULL COMMENT '创建时间',
    updated_at   TIMESTAMP    DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP NOT NULL COMMENT '更新时间'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='异步LLM总控表';
