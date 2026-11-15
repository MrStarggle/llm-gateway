-- LLM Gateway database schema (MySQL 8+)
-- 应用启动时会先按 ORM 模型 create_all，再执行本脚本补全索引/约束；重复执行安全。

CREATE TABLE IF NOT EXISTS llm_provider_info
(
    provider_id   VARCHAR(64)  NOT NULL PRIMARY KEY COMMENT '提供商ID（雪花ID）',
    provider_name VARCHAR(128) NOT NULL UNIQUE COMMENT '提供商名称（唯一）',
    api_url       VARCHAR(512) NOT NULL COMMENT 'API 地址',
    api_key       VARCHAR(512) NOT NULL COMMENT 'API Key',
    remarks       TEXT         NULL COMMENT '备注',
    created_at    TIMESTAMP    DEFAULT CURRENT_TIMESTAMP NOT NULL COMMENT '创建时间',
    updated_at    TIMESTAMP    DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP NOT NULL COMMENT '更新时间'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='大模型提供商配置表';

CREATE TABLE IF NOT EXISTS model_manage_info
(
    ai_model_id   VARCHAR(64)  NOT NULL PRIMARY KEY COMMENT '模型ID（雪花ID）',
    ai_model_name VARCHAR(128) NOT NULL COMMENT '模型名称',
    com_name      VARCHAR(128) NOT NULL COMMENT '提供商名称（冗余副本）',
    com_url       VARCHAR(512) NOT NULL COMMENT 'API 地址（冗余副本）',
    api_key       VARCHAR(512) NOT NULL COMMENT 'API Key（冗余副本）',
    provider_id   VARCHAR(64)  NULL COMMENT '提供商ID（指向 llm_provider_info）',
    ai_model_type VARCHAR(8)   DEFAULT '0' COMMENT '0文本模型，1语音模型',
    is_using      VARCHAR(1)   NOT NULL DEFAULT '1' COMMENT '是否使用中：1是0否',
    is_think      VARCHAR(1)   NULL DEFAULT '0' COMMENT '思考模式：0跟随请求，1强制开启，2强制关闭',
    is_stream     VARCHAR(1)   DEFAULT '1' COMMENT '流式：1是0否',
    async_type    VARCHAR(8)   NOT NULL DEFAULT 'async1' COMMENT '集群类型：async1..async9',
    temperature   FLOAT        NULL COMMENT '覆盖请求体temperature；NULL=不覆盖',
    top_p         FLOAT        NULL COMMENT '覆盖请求体top_p；NULL=不覆盖（与temperature互斥）',
    top_k         INT          NULL COMMENT '覆盖请求体top_k；NULL=不覆盖（部分厂商不支持）',
    max_tokens    INT          NULL COMMENT '覆盖请求体max_tokens；NULL=不覆盖',
    extra_config  TEXT         NULL COMMENT '额外 JSON 配置',
    remarks       TEXT         NULL COMMENT '备注',
    created_at    TIMESTAMP    DEFAULT CURRENT_TIMESTAMP NOT NULL COMMENT '创建时间',
    updated_at    TIMESTAMP    DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP NOT NULL COMMENT '更新时间',
    KEY idx_model_provider_id (provider_id),
    KEY idx_model_async_type (async_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='大模型配置表';

CREATE TABLE IF NOT EXISTS user_token_info
(
    id                       INT AUTO_INCREMENT PRIMARY KEY COMMENT '自增主键',
    user_id                  VARCHAR(64)  NOT NULL COMMENT '调用方用户/客户端ID',
    model                    VARCHAR(128) NOT NULL DEFAULT '' COMMENT '模型名称',
    purpose                  VARCHAR(16)  NOT NULL DEFAULT 'main' COMMENT '用途：main/async',
    is_stream                INT          NOT NULL DEFAULT 0 COMMENT '是否流式：1是0否',
    prompt_tokens            INT          NOT NULL DEFAULT 0 COMMENT '输入token',
    completion_tokens        INT          NOT NULL DEFAULT 0 COMMENT '输出token',
    total_tokens             INT          NOT NULL DEFAULT 0 COMMENT '总token',
    prompt_cache_hit_tokens  INT          NOT NULL DEFAULT 0 COMMENT '缓存命中token',
    prompt_cache_miss_tokens INT          NOT NULL DEFAULT 0 COMMENT '缓存未命中token',
    record_date              DATE         NOT NULL COMMENT '记录日期（按天聚合用）',
    created_at               TIMESTAMP    DEFAULT CURRENT_TIMESTAMP NOT NULL COMMENT '创建时间',
    KEY idx_user_id (user_id),
    KEY idx_record_date (record_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Token 用量明细表';

CREATE TABLE IF NOT EXISTS user_daily_quota
(
    id         INT AUTO_INCREMENT PRIMARY KEY COMMENT '自增主键',
    user_id    VARCHAR(64) NOT NULL COMMENT '调用方用户/客户端ID',
    quota_date DATE        NOT NULL COMMENT '计数日期',
    call_count INT         NOT NULL DEFAULT 0 COMMENT '当日调用次数',
    updated_at TIMESTAMP   DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP NOT NULL COMMENT '更新时间',
    UNIQUE KEY uq_user_daily_quota_user_date (user_id, quota_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='每日调用计数表（统计用）';
