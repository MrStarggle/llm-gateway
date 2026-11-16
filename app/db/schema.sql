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
    input_price_per_1m  DECIMAL(18,6) NULL COMMENT '输入单价（每 1M token）',
    output_price_per_1m DECIMAL(18,6) NULL COMMENT '输出单价（每 1M token）',
    price_currency      VARCHAR(8)    NOT NULL DEFAULT 'USD' COMMENT '价格币种',
    price_source        VARCHAR(16)   NULL COMMENT '价格来源：manual/provider',
    price_updated_at    DATETIME      NULL COMMENT '价格更新时间',
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
    project_id               VARCHAR(64)  NULL COMMENT '项目ID',
    token_id                 VARCHAR(64)  NULL COMMENT '项目Token ID',
    channel_id               VARCHAR(64)  NULL COMMENT '实际服务的模型ID',
    request_id               VARCHAR(64)  NULL COMMENT '请求ID',
    retry_count              INT          NOT NULL DEFAULT 0 COMMENT '网关内部重试次数',
    model                    VARCHAR(128) NOT NULL DEFAULT '' COMMENT '模型名称',
    purpose                  VARCHAR(16)  NOT NULL DEFAULT 'main' COMMENT '用途：main/async',
    feature_code             VARCHAR(64)  NOT NULL DEFAULT 'uncategorized' COMMENT '功能码',
    is_stream                INT          NOT NULL DEFAULT 0 COMMENT '是否流式：1是0否',
    prompt_tokens            INT          NOT NULL DEFAULT 0 COMMENT '输入token',
    completion_tokens        INT          NOT NULL DEFAULT 0 COMMENT '输出token',
    total_tokens             INT          NOT NULL DEFAULT 0 COMMENT '总token',
    prompt_cache_hit_tokens  INT          NOT NULL DEFAULT 0 COMMENT '缓存命中token',
    prompt_cache_miss_tokens INT          NOT NULL DEFAULT 0 COMMENT '缓存未命中token',
    estimated_cost           DECIMAL(18,8) NULL COMMENT '本次调用成本',
    cost_currency            VARCHAR(8)   NULL COMMENT '成本币种',
    cost_source              VARCHAR(16)  NULL COMMENT '成本来源：estimate/provider',
    record_date              DATE         NOT NULL COMMENT '记录日期（按天聚合用）',
    created_at               TIMESTAMP    DEFAULT CURRENT_TIMESTAMP NOT NULL COMMENT '创建时间',
    KEY idx_user_id (user_id),
    KEY idx_record_date (record_date),
    KEY idx_user_token_feature_code (feature_code),
    KEY idx_user_token_project_id (project_id),
    KEY idx_user_token_token_id (token_id),
    KEY idx_user_token_channel_id (channel_id),
    KEY idx_user_token_request_id (request_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Token 用量明细表';

CREATE TABLE IF NOT EXISTS user_daily_quota
(
    id         INT AUTO_INCREMENT PRIMARY KEY COMMENT '自增主键',
    user_id    VARCHAR(64) NOT NULL COMMENT '调用方用户/客户端ID',
    quota_date DATE        NOT NULL COMMENT '计数日期',
    call_count INT         NOT NULL DEFAULT 0 COMMENT '当日调用次数',
    total_tokens BIGINT    NOT NULL DEFAULT 0 COMMENT '当日token总数（配额口径）',
    updated_at TIMESTAMP   DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP NOT NULL COMMENT '更新时间',
    UNIQUE KEY uq_user_daily_quota_user_date (user_id, quota_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='每日调用与Token计数表（配额口径）';

CREATE TABLE IF NOT EXISTS user_quota_policy
(
    user_id             VARCHAR(64)  NOT NULL PRIMARY KEY COMMENT '用户ID（含 gw:<token_id> 合成ID）',
    daily_token_limit   BIGINT       NULL COMMENT '每日Token上限；NULL=不限，0=禁止',
    monthly_token_limit BIGINT       NULL COMMENT '每月Token上限；NULL=不限，0=禁止',
    status              VARCHAR(8)   NOT NULL DEFAULT 'active' COMMENT '访问状态：active/blocked',
    remark              VARCHAR(255) NULL COMMENT '备注',
    created_at          TIMESTAMP    DEFAULT CURRENT_TIMESTAMP NOT NULL COMMENT '创建时间',
    updated_at          TIMESTAMP    DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP NOT NULL COMMENT '更新时间',
    KEY idx_user_quota_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='用户配额与访问策略表';

CREATE TABLE IF NOT EXISTS project_info
(
    project_id          VARCHAR(64)  NOT NULL PRIMARY KEY COMMENT '项目ID（雪花ID）',
    project_name        VARCHAR(128) NOT NULL UNIQUE COMMENT '项目/团队名称',
    status              VARCHAR(8)   NOT NULL DEFAULT 'active' COMMENT '状态：active/disabled',
    daily_call_limit    INT          NULL COMMENT '每日调用次数上限；NULL=不限，0=禁止',
    monthly_call_limit  INT          NULL COMMENT '每月调用次数上限；NULL=不限，0=禁止',
    daily_token_limit   BIGINT       NULL COMMENT '每日Token上限；NULL=不限，0=禁止',
    monthly_token_limit BIGINT       NULL COMMENT '每月Token上限；NULL=不限，0=禁止',
    daily_cost_limit    DECIMAL(18,8) NULL COMMENT '每日成本上限（项目币种）；NULL=不限',
    monthly_cost_limit  DECIMAL(18,8) NULL COMMENT '每月成本上限（项目币种）；NULL=不限',
    cost_currency       VARCHAR(8)   NOT NULL DEFAULT 'USD' COMMENT '成本币种',
    remarks             TEXT         NULL COMMENT '备注',
    created_at          TIMESTAMP    DEFAULT CURRENT_TIMESTAMP NOT NULL COMMENT '创建时间',
    updated_at          TIMESTAMP    DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP NOT NULL COMMENT '更新时间',
    KEY idx_project_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='项目（团队）表';

CREATE TABLE IF NOT EXISTS project_token_info
(
    token_id       VARCHAR(64)  NOT NULL PRIMARY KEY COMMENT 'Token ID（雪花ID）',
    project_id     VARCHAR(64)  NOT NULL COMMENT '所属项目ID',
    name           VARCHAR(128) NOT NULL COMMENT 'Token 名称',
    token_hash     VARCHAR(64)  NOT NULL UNIQUE COMMENT 'Token SHA-256 哈希',
    token_prefix   VARCHAR(20)  NOT NULL COMMENT '展示用前缀',
    token_suffix   VARCHAR(8)   NOT NULL COMMENT '展示用后4位',
    allowed_models TEXT         NULL COMMENT '允许的模型 JSON 数组；NULL=不限',
    expires_at     DATETIME     NULL COMMENT '过期时间；NULL=不过期',
    status         VARCHAR(8)   NOT NULL DEFAULT 'active' COMMENT '状态：active/revoked',
    last_used_at   DATETIME     NULL COMMENT '最后使用时间',
    remarks        TEXT         NULL COMMENT '备注',
    created_at     TIMESTAMP    DEFAULT CURRENT_TIMESTAMP NOT NULL COMMENT '创建时间',
    UNIQUE KEY uq_project_token_name (project_id, name),
    KEY idx_project_token_project_id (project_id),
    KEY idx_project_token_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='项目 API Token 表';

CREATE TABLE IF NOT EXISTS project_usage_daily
(
    id          INT AUTO_INCREMENT PRIMARY KEY COMMENT '自增主键',
    project_id  VARCHAR(64)   NOT NULL COMMENT '项目ID',
    usage_date  DATE          NOT NULL COMMENT '统计日期',
    call_count  INT           NOT NULL DEFAULT 0 COMMENT '成功调用次数',
    total_tokens BIGINT       NOT NULL DEFAULT 0 COMMENT 'Token 总数',
    cost_amount DECIMAL(18,8) NOT NULL DEFAULT 0 COMMENT '成本合计（项目币种）',
    updated_at  TIMESTAMP     DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP NOT NULL COMMENT '更新时间',
    UNIQUE KEY uq_project_usage_daily (project_id, usage_date),
    KEY idx_project_usage_date (usage_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='项目每日用量聚合表';

CREATE TABLE IF NOT EXISTS channel_health_info
(
    model_id              VARCHAR(64) NOT NULL PRIMARY KEY COMMENT '模型ID（ai_model_id）',
    stat_date             DATE        NULL COMMENT '统计日期',
    success_count         INT         NOT NULL DEFAULT 0 COMMENT '今日成功次数',
    failure_count         INT         NOT NULL DEFAULT 0 COMMENT '今日失败次数',
    latency_sum_ms        BIGINT      NOT NULL DEFAULT 0 COMMENT '今日延迟总和（流式为TTFB）',
    consecutive_failures  INT         NOT NULL DEFAULT 0 COMMENT '连续失败次数',
    consecutive_successes INT         NOT NULL DEFAULT 0 COMMENT '连续成功次数',
    state                 VARCHAR(16) NOT NULL DEFAULT 'closed' COMMENT '状态：closed/open/half_open',
    cooldown_until        DATETIME    NULL COMMENT '冷却结束时间',
    last_error            VARCHAR(200) NULL COMMENT '最后错误标识（不含上游报文）',
    last_success_at       DATETIME    NULL COMMENT '最后成功时间',
    last_failure_at       DATETIME    NULL COMMENT '最后失败时间',
    updated_at            TIMESTAMP   DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP NOT NULL COMMENT '更新时间',
    KEY idx_channel_health_state (state)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='渠道健康状态表';

CREATE TABLE IF NOT EXISTS cluster_routing_config
(
    async_type          VARCHAR(8)  NOT NULL PRIMARY KEY COMMENT '集群：async1..async9',
    strategy            VARCHAR(16) NOT NULL DEFAULT 'round_robin' COMMENT '路由策略',
    retry_max           INT         NOT NULL DEFAULT 1 COMMENT '重试次数（总尝试 <= 3）',
    failure_threshold   INT         NOT NULL DEFAULT 5 COMMENT '连续失败熔断阈值',
    cooldown_seconds    INT         NOT NULL DEFAULT 60 COMMENT '熔断冷却秒数',
    output_ratio        FLOAT       NOT NULL DEFAULT 0.3 COMMENT '成本估算输出占比',
    enabled             INT         NOT NULL DEFAULT 1 COMMENT '是否启用健康路由',
    updated_at          TIMESTAMP   DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP NOT NULL COMMENT '更新时间'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='集群路由配置表';
