/*!
 * LLM Gateway UI i18n
 *
 * The HTML/JS sources are written in Chinese. When the UI language is English
 * (the default), text nodes and translatable attributes are replaced at runtime
 * using the dictionary below. Switching back to Chinese simply reloads the page
 * without translation, because the source text is already Chinese.
 */
(function () {
  'use strict';

  const LANG_KEY = 'ui_lang';
  const DEFAULT_LANG = 'en';
  const SUPPORTED = ['en', 'zh'];
  const ATTRS = ['placeholder', 'title', 'aria-label', 'alt'];

  const DICT = {
    // ==================== 管理台：导航与通用 ====================
    '控制台': 'Console',
    '环境': 'Environment',
    '用量信息': 'Usage',
    '调用记录': 'Call records',
    '大模型提供商管理': 'Providers',
    '大模型管理': 'Models',
    '项目与密钥': 'Projects & keys',
    '渠道健康': 'Channel health',
    '对话': 'Chat',
    '接入说明': 'Integration guide',
    '大模型管理平台': 'LLM Gateway',
    '大模型管理平台 - LLM Gateway': 'LLM Gateway',
    '大模型管理平台 - 管理后台': 'LLM Gateway - Admin',
    '刷新': 'Refresh',
    '退出': 'Sign out',
    '取消': 'Cancel',
    '确认': 'Confirm',
    '确认操作': 'Confirm',
    '确认新增': 'Create',
    '创建': 'Create',
    '删除': 'Delete',
    '复制': 'Copy',
    '编辑': 'Edit',
    '重置': 'Reset',
    '查看': 'View',
    '查询': 'Search',
    '保存': 'Save',
    '保存修改': 'Save changes',
    '登录': 'Sign in',
    '登 录': 'Sign in',
    '管理员登录': 'Admin sign-in',
    '管理员账号': 'Admin username',
    '密码': 'Password',
    '使用管理员账号登录': 'Sign in with the admin account',
    '退出管理登录': 'Sign out of the admin console',
    '刷新当前页面': 'Refresh this page',
    '上一页': 'Previous',
    '下一页': 'Next',
    '加载中...': 'Loading...',
    '暂无数据': 'No data',
    '处理建议': 'Suggested action',
    '操作': 'Actions',
    '状态': 'Status',
    '状态码': 'Status code',
    '类型': 'Type',
    '时间': 'Time',
    '名称': 'Name',
    '说明': 'Description',
    '含义': 'Meaning',
    '取值': 'Value',
    '备注': 'Notes',
    '可选备注': 'Optional notes',
    '可选备注信息': 'Optional notes',
    '操作失败': 'Operation failed',

    // ==================== 管理台：统计与用量 ====================
    '查看平台 LLM 调用量与 Token 消耗': 'Platform LLM calls and token usage',
    '按用户、模型与日期检索每一次 LLM 调用明细': 'Search every LLM call by user, model, and date',
    '按项目签发 API Key，设置调用 / Token / 成本配额': 'Issue API keys per project and set call/token/cost quotas',
    '查看渠道成功率、延迟、熔断与成本路由策略': 'Channel success rates, latency, circuit breaking, and cost routing',
    '统一维护提供商名称、API 地址与 API Key': 'Manage provider names, API URLs, and API keys in one place',
    '管理转发到各提供商的模型配置': 'Manage how models are forwarded to providers',
    '接口地址、请求头、集群路由与调用示例': 'Endpoint, headers, cluster routing, and examples',
    '累计 LLM 请求': 'Total LLM requests',
    '活跃用户': 'Active users',
    '产生调用记录的用户数': 'Users with call records',
    '今日调用': 'Today\'s calls',
    '今日成本': 'Today\'s cost',
    '今日成功率': 'Today\'s success rate',
    '今日成功率、平均延迟与熔断状态': 'Today\'s success rate, average latency, and circuit state',
    '本月调用': 'This month\'s calls',
    '本月成本': 'This month\'s cost',
    '总 Token': 'Total tokens',
    '总 Token 消耗': 'Total token usage',
    '输入 Token': 'Input tokens',
    '输出 Token': 'Output tokens',
    '输入 / 输出 Token 构成': 'Input / output token mix',
    '输入 + 输出': 'Input + output',
    '输入': 'Input',
    '输出': 'Output',
    '成本': 'Cost',
    '缓存命中': 'Cache hits',
    '缓存命中 -': 'Cache hits -',
    '平均延迟': 'Average latency',
    '连续失败': 'Consecutive failures',
    '最后错误': 'Last error',
    '最后使用': 'Last used',
    '重试次数': 'Retry count',
    '模型用量分布': 'Model usage breakdown',
    '近 7 天': 'Last 7 days',
    '近 30 天': 'Last 30 days',
    '近 90 天': 'Last 90 days',
    '近 30 天模型用量': 'Model usage in the last 30 days',
    '按 Token 总量排序': 'Sort by total tokens',
    '按选中维度分组统计；不选时默认按模型': 'Group by the selected dimensions; defaults to model',
    '输入 / 输出（USD / 1M tokens）': 'Input / output (USD / 1M tokens)',
    '输入单价': 'Input price',
    '输出单价': 'Output price',
    '输出占比': 'Output share',
    '单价': 'Price',
    '计费单价（可选）': 'Pricing (optional)',
    '成本币种': 'Cost currency',
    '用量明细': 'Usage details',
    '产生调用记录的用户数': 'Users with call records',
    '调用次数': 'Calls',
    '调用': 'Calls',
    '用户': 'User',
    '用户 ID': 'User ID',
    '功能码': 'Feature code',
    '用途': 'Purpose',
    '模型': 'Model',
    '项目': 'Project',
    '集群': 'Cluster',
    '全部提供商': 'All providers',
    '全部状态': 'All statuses',
    '全部类型': 'All types',
    '全部集群': 'All clusters',
    '全部模型': 'All models',
    '导出 CSV': 'Export CSV',
    '按项目隔离调用量、Token 与成本': 'Isolate calls, tokens, and cost per project',
    '共 0 条': '0 records',
    '导出当前会话': 'Export this conversation',
    '导出当前会话': 'Export this conversation',

    // ==================== 管理台：提供商与模型 ====================
    '大模型提供商': 'LLM providers',
    '大模型参数': 'Model parameters',
    '提供商': 'Provider',
    '提供商名称': 'Provider name',
    '提供商参数': 'Provider parameters',
    '密钥': 'Key',
    '复制密钥': 'Copy key',
    'API 地址': 'API URL',
    'Base URL 与端点': 'Base URL and endpoints',
    '接入地址': 'Endpoint',
    '关联模型': 'Linked models',
    '典型用途': 'Typical use',
    '模型名称': 'Model name',
    '模型类型': 'Model type',
    '模型列表：': 'Model list:',
    '模型扩展配置 (JSON)': 'Model extra config (JSON)',
    '文本模型': 'Text model',
    '语音模型': 'Audio model',
    '是否使用中': 'Active',
    '使用中': 'Active',
    '启用': 'Enabled',
    '停用': 'Disabled',
    '未使用': 'Inactive',
    '已启用': 'Enabled',
    '已停用': 'Disabled',
    '新增提供商': 'Add provider',
    '新增模型': 'Add model',
    '新增项目': 'Add project',
    '新建 Token': 'New token',
    '删除提供商': 'Delete provider',
    '删除模型': 'Delete model',
    '编辑提供商': 'Edit provider',
    '编辑模型': 'Edit model',
    '编辑项目': 'Edit project',
    'Token 名称': 'Token name',
    'Token 已生成': 'Token generated',
    '有效 Token': 'Valid tokens',
    '过期时间': 'Expiry',
    '允许模型': 'Allowed models',
    '允许的模型': 'Allowed models',
    '项目 / 团队名称': 'Project / team name',
    '项目 ID': 'Project ID',
    '项目 Token 与配额': 'Projects, tokens, and quotas',
    '项目 Token 或上游 Key': 'Project token or upstream key',
    '项目 Token + 流式请求': 'Project token + streaming request',
    '请求头': 'Request headers',
    '路由头、思考与 JSON 输出控制': 'Routing headers, thinking, and JSON output',
    '路由策略已保存': 'Routing strategy saved',
    '集群路由策略': 'Cluster routing strategy',
    '集群类型': 'Cluster',
    '集群与模型选择': 'Clusters and model selection',
    '集群1': 'Cluster 1',
    '集群2': 'Cluster 2',
    '集群3': 'Cluster 3',
    '集群4': 'Cluster 4',
    '集群5': 'Cluster 5',
    '集群6': 'Cluster 6',
    '集群7': 'Cluster 7',
    '集群8': 'Cluster 8',
    '集群9': 'Cluster 9',
    '主 LLM 默认池': 'Default main LLM pool',
    '异步 / 后台任务常用池': 'Pool for async/background tasks',
    '特殊分流或独立容量池': 'Special routing or dedicated capacity pool',
    '策略': 'Strategy',
    '轮询': 'Round-robin',
    '成本优先': 'Cost first',
    '延迟优先': 'Latency first',
    '熔断阈值': 'Circuit-breaker threshold',
    '冷却（秒）': 'Cooldown (seconds)',
    '重试、熔断与成本优先；修改后点击保存': 'Retry, circuit breaking, and cost-first routing; click Save after changes',
    '检查 Token 的允许模型与项目状态': 'Check the token\'s allowed models and project status',
    '重新在「项目与密钥」创建或轮换 Token': 'Create or rotate a token in Projects & keys',
    '网关已尝试同集群其他渠道；检查提供商地址与 Key': 'The gateway already tried other channels in the cluster; check the provider URL and key',
    '所选集群没有可用模型': 'No models available in the selected cluster',

    // ==================== 管理台：参数与提示 ====================
    '思考': 'Thinking',
    '思考模式': 'Thinking mode',
    '强制开启思考': 'Force thinking on',
    '强制关闭思考': 'Force thinking off',
    '跟随请求（不干预）': 'Follow request (no override)',
    '流式': 'Streaming',
    '流式输出': 'Streaming output',
    '流式读取': 'Streaming read',
    '单次响应的最大输出 token 数。': 'Maximum output tokens per response.',
    '仅保留概率最高的 K 个 token；部分厂商不支持。': 'Keep only the K most probable tokens; not supported by all providers.',
    '仅部分厂商支持。o 系列跳过采样参数，Claude 开启思考时固定 temperature=1。': 'Only some providers support this. o-series models skip sampling parameters; Claude fixes temperature=1 when thinking is enabled.',
    '核采样，仅保留累计概率前 P 的 token；与 temperature 互斥。': 'Nucleus sampling; keeps tokens within cumulative probability P; mutually exclusive with temperature.',
    '越高内容越随机；与 top_p 互斥，填写一个会禁用另一个。': 'Higher values are more random; mutually exclusive with top_p; setting one disables the other.',
    '互斥，只能配置一个；': 'are mutually exclusive; set only one;',
    '时，服务端会覆盖请求体同名参数；留空则沿用客户端值。': ', the server overrides the same request-body parameter; if empty, the client value is used.',
    '留空表示沿用客户端请求参数；temperature 与 top_p 只能填写一个。': 'Empty keeps the client\'s request parameters; set only one of temperature and top_p.',
    '留空表示不过期。': 'Empty means no expiry.',
    '要求 JSON 输出（服务端按实际模型决定是否注入）': 'Request JSON output (the server decides whether to inject it for the actual model)',
    '仅 OpenRouter 提供商会启用该参数。': 'Only OpenRouter providers use this parameter.',
    '关闭时不注入 provider 字段；开启后使用默认路由参数。': 'No provider field is injected when off; the default routing parameters are used when on.',
    '已开启：默认使用上述路由参数，可按需修改。': 'On: the default routing parameters above are used; edit as needed.',
    'OpenRouter 路由参数': 'OpenRouter routing parameters',
    '模型自身扩展字段，如语音音色；与下方 OpenRouter 路由参数分开填写。': 'Model-specific fields such as voice; separate from the OpenRouter routing parameters below.',
    '实时匹配 providers.txt；选中后 API 地址为空时会自动填入。': 'Matches providers.txt as you type; selecting one fills the API URL if empty.',
    '同一提供商下的模型共用此密钥。': 'Models under the same provider share this key.',
    '完整密钥只显示一次，请立即复制保存。关闭后无法再次查看。': 'The full key is shown only once. Copy it now; you cannot view it again after closing.',
    '新密钥只会展示一次。': 'The new key is shown only once.',
    '同一集群内的启用模型按轮询调度。': 'Active models in the same cluster are scheduled round-robin.',
    '填写基础地址即可，调用时会自动补 /chat/completions；模型列表从 /models 拉取。': 'Enter the base URL; /chat/completions is appended automatically. The model list comes from /models.',
    '用于用量页估算成本；留空表示不统计。成本为估算值，实际账单以厂商为准。': 'Used to estimate cost in Usage; empty disables it. Estimates only; the provider\'s bill is authoritative.',
    '地址与 API Key 由提供商统一配置。': 'The URL and API key are configured on the provider.',
    '集群在「大模型管理」中按模型配置': 'Clusters are configured per model in Models',
    '选择提供商后自动拉取可用模型': 'Select a provider to load available models',
    '选择项目后查看用量': 'Select a project to view usage',
    '选择项目后查看 Token': 'Select a project to view tokens',
    '降级': 'Fallback',
    '缺省': 'Default',
    '匿名': 'Anonymous',
    '未传': 'Not provided',
    '不限': 'Unlimited',
    '留空 = 不限': 'Empty = unlimited',
    'gpt-*, deepseek-*；留空 = 不限': 'gpt-*, deepseek-*; empty = unlimited',
    '不覆盖': 'No override',
    '不计算成本': 'Do not calculate cost',
    '例如：https://api.deepseek.com': 'e.g. https://api.deepseek.com',
    '例如：web-prod / 客服生产环境': 'e.g. web-prod / support production',
    '例如：客服机器人 / 工作室 A': 'e.g. support bot / Studio A',
    '开始日期': 'Start date',
    '结束日期': 'End date',
    '搜索项目名称': 'Search project name',
    '用途（main / async / 自定义）': 'Purpose (main / async / custom)',
    '输入或选择提供商名称...': 'Type or select a provider name...',
    '选择提供商后自动加载，也可手动输入': 'Loads after selecting a provider; you can also type manually',
    '开启后按默认值注入 provider 字段': 'Inject the default provider field when enabled',
    '例如：你是一名严谨的软件工程师，回答尽量给出可执行步骤。': 'e.g. You are a rigorous software engineer; prefer actionable steps.',

    // ==================== 管理台：项目 / 配额 ====================
    '每日调用上限': 'Daily call limit',
    '每日 Token 上限': 'Daily token limit',
    '每日成本上限': 'Daily cost limit',
    '每月调用上限': 'Monthly call limit',
    '每月 Token 上限': 'Monthly token limit',
    '每月成本上限': 'Monthly cost limit',
    '每日 Token 消耗': 'Daily token usage',
    '项目可设置每日 / 每月 调用次数、Token 数和成本上限。留空 = 不限，': 'Projects can limit daily/monthly calls, tokens, and cost. Empty = unlimited,',
    '限额留空 = 不限，0 = 禁止调用；调用次数在请求前检查，Token/成本在响应后累计（软限额）。': 'Empty = unlimited; 0 = blocked. Call counts are checked before the request; tokens/cost accumulate after the response (soft limits).',
    '只累计与该项目币种一致的调用成本，不做汇率换算。': 'Only costs in the project\'s currency are accumulated; no FX conversion.',
    '项目配额超限': 'Project quota exceeded',
    '禁用': 'Disabled',
    '禁止': 'Blocked',
    '登出': 'Sign out',

    // ==================== 接入说明 ====================
    '快速开始': 'Quick start',
    'OpenAI SDK 示例': 'OpenAI SDK example',
    'cURL 示例': 'cURL example',
    'OpenAI 兼容接口，按集群路由': 'OpenAI-compatible API, routed by cluster',
    '流式返回标准 SSE；非流式返回上游 JSON 信封': 'Streaming returns standard SSE; non-streaming returns the upstream JSON envelope',
    '项目 Token；网关校验项目、配额与模型范围。不带': 'Project token; the gateway validates the project, quota, and model scope. Without',
    '前缀时按旧版上游 Key 语义处理': 'prefix is handled with legacy upstream-key semantics',
    '覆盖服务端 Key；异步链强制使用服务端 Key。': 'overrides the server-side key; async chains always use the server-side key.',
    '调用方标识，用于用量统计；不传视为匿名': 'Caller identifier for usage attribution; omitted means anonymous',
    '调用方链路追踪 ID；不传由网关生成，并写入调用记录': 'Caller trace ID; generated by the gateway when omitted and stored in call records',
    '异步判定、日志与 token 用量记账，不影响集群选择；建议 ≤16 字符': 'Async detection, logging, and token accounting; does not affect cluster selection; ≤16 characters recommended',
    '思考模式开关；仅在模型「思考模式」为跟随请求时生效': 'Thinking switch; only applies when the model\'s thinking mode follows the request',
    '功能码，仅用于用量明细分组统计；不传或非法记为': 'Feature code for usage grouping; omitted or invalid values are recorded as',
    '可选，≤64 字符': 'Optional, ≤64 characters',
    '模型列表：': 'Model list:',
    '推荐使用': 'Recommended:',
    '兼容：': 'Compatible:',
    '接入自有用户体系': 'Bring your own user system',
    '配置': 'Configuration',
    '手动启动（本地开发）': 'Run manually (local development)',
    '快速开始（Docker）': 'Quick start (Docker)',
    '最简单：一键启动': 'Quickest start: one-click launch',
    '测试': 'Tests',
    '目录结构': 'Project layout',
    '许可证': 'License',
    '响应与错误': 'Responses and errors',
    '上游厂商返回错误': 'Upstream provider returned an error',
    '错误格式为': 'error format is',
    '便于排查': 'for troubleshooting',

    // ==================== 聊天页 ====================
    '对话 · LLM Gateway': 'Chat · LLM Gateway',
    '本地对话 · 网关直连': 'Local chat · direct to gateway',
    '新对话': 'New chat',
    '设置': 'Settings',
    '导入': 'Import',
    '管理台': 'Admin console',
    '模型': 'Model',
    '模型与参数': 'Model and parameters',
    '选择模型': 'Select model',
    '选择模型与参数': 'Select model and parameters',
    '系统提示词': 'System prompt',
    '消息仅保存在本机': 'Messages stay on this device',
    '发送': 'Send',
    '关闭': 'Close',
    '会话列表': 'Conversations',
    '历史会话': 'History',
    '打开会话列表': 'Open conversations',
    '模型列表': 'Model list',
    '运营商列表': 'Provider list',
    '选择或输入模型': 'Select or type a model',
    '选择运营商': 'Select a provider',
    '选择运营商后自动加载模型': 'Loads models after selecting a provider',
    '点击重命名': 'Click to rename',
    '输入消息，Enter 发送，Shift + Enter 换行': 'Type a message. Enter to send, Shift+Enter for a new line',
    '导出当前会话': 'Export this conversation',
    '开启或关闭思考模式': 'Toggle thinking mode',
    '思考模式：仅对配置为「跟随请求」的模型生效': 'Thinking mode: only applies to models configured to follow the request',
    'sk-gw-...（本地开源模式可留空）': 'sk-gw-... (optional in local open-source mode)',
    '对话设置': 'Chat settings',
    '保存设置': 'Save settings',
    '应用': 'Apply',
    '取消': 'Cancel',
    '网关地址': 'Gateway URL',
    '项目 API Key': 'Project API key',
    '模型': 'Model',
    '运营商': 'Provider',
    '采样参数': 'Sampling parameters',
    '留空沿用网关默认': 'Empty uses the gateway default',
    '本地保存': 'Saved locally',
    '本地对话 · 网关直连': 'Local chat · direct to gateway',
    '消息仅保存在本机': 'Messages stay on this device',
    '配置网关访问凭证和当前会话的系统提示词。': 'Configure gateway credentials and this conversation\'s system prompt.',
    '选择运营商与模型，并按会话覆盖采样参数。': 'Choose a provider and model, and override sampling parameters per conversation.',
    '这里只切换模型；运营商、采样参数与思考开关请使用顶部「模型」按钮。': 'This only switches the model; use the top Model button for the provider, sampling parameters, and thinking switch.',
    '仅用于筛选可选模型，实际路由由网关集群策略决定。': 'Only filters selectable models; actual routing is decided by the gateway\'s cluster strategy.',
    '写入当前会话；新会话默认沿用最近一次设置。': 'Applies to this conversation; new conversations reuse the latest settings.',
    'temperature 与 top_p 互斥，填写一个会自动清空另一个；管理台已为模型配置的同名参数优先。': 'temperature and top_p are mutually exclusive; setting one clears the other. Parameters configured for the model in the admin console take precedence.',
    '或使用项目配额时填写。密钥只保存在本机浏览器。': 'or when project quotas are used. The key is stored only in this browser.',
    '消息只保存在当前浏览器。选择一个模型，直接输入即可。切换会话不会上传聊天记录。': 'Messages stay in this browser. Pick a model and start typing; switching conversations never uploads chat history.',
    '还没有会话，点击上方「新对话」开始。': 'No conversations yet. Click New chat above to start.',
    '还没有消息': 'No messages yet',
    '开始一段对话': 'Start a conversation',
    '在下方输入消息，Enter 发送': 'Type a message below and press Enter to send',
    '你': 'You',
    '助手': 'Assistant',
    '你好': 'Hello',
    '复制': 'Copy',
    '复制失败': 'Copy failed',
    '复制失败，请手动选择文本': 'Copy failed; select the text manually',
    '已复制': 'Copied',
    '重新生成': 'Regenerate',
    '停止生成': 'Stop generating',
    '正在生成': 'Generating',
    '正在生成…': 'Generating...',
    '正在生成… 点击方块停止': 'Generating... click the square to stop',
    '已停止': 'Stopped',
    '（已停止）': '(stopped)',
    '思考过程': 'Thinking process',
    '思考': 'Thinking',
    '删除会话': 'Delete conversation',
    '删除会话「': 'Delete conversation "',
    '」？此操作只影响本机。': '"? This only affects this device.',
    '重命名会话': 'Rename conversation',
    '此操作不可撤销。': 'This cannot be undone.',
    '请输入 Token 名称': 'Enter a token name',
    '请输入项目名称': 'Enter a project name',
    '请输入管理员账号': 'Enter the admin username',
    '请输入密码': 'Enter your password',
    '请选择大模型提供商': 'Select a provider',
    '请填写提供商名称、API 地址与 API Key': 'Enter the provider name, API URL, and API key',
    '请填写模型名称': 'Enter a model name',
    '请先选择模型': 'Select a model first',
    '请先选择项目': 'Select a project first',
    '请先停止当前回复': 'Stop the current response first',
    '请先在大模型提供商管理中新增提供商': 'Add a provider in Providers first',
    '请求失败': 'Request failed',
    '网络错误，请检查连接': 'Network error; check your connection',
    '登录失败': 'Sign-in failed',
    '登录中...': 'Signing in...',
    '登录成功，欢迎': 'Signed in. Welcome,',
    '当前账号无管理员权限': 'This account has no admin permission',
    '保存失败': 'Save failed',
    '创建失败': 'Create failed',
    '更新失败': 'Update failed',
    '更新成功': 'Updated',
    '更新成功，关联模型配置已同步': 'Updated; linked model configs synced',
    '新增成功': 'Created',
    '删除成功': 'Deleted',
    '删除失败': 'Delete failed',
    '吊销': 'Revoke',
    '吊销密钥': 'Revoke key',
    '吊销失败': 'Revoke failed',
    '已吊销': 'Revoked',
    '轮换': 'Rotate',
    '轮换密钥': 'Rotate key',
    '轮换失败': 'Rotate failed',
    '轮换后将生成新密钥，旧密钥立即失效，请及时替换调用方配置。': 'Rotation creates a new key and immediately invalidates the old one; update your callers.',
    '吊销后该密钥立即失效，正在使用它的调用会开始失败。': 'The key stops working immediately after revocation and in-flight callers will start failing.',
    '删除后该提供商将无法继续提供模型服务。若仍有模型关联此提供商，需要先删除或迁移这些模型。': 'The provider can no longer serve models after deletion. If models are still linked, delete or migrate them first.',
    '删除后该模型将不再参与集群转发，历史调用记录会保留。': 'The model stops participating in cluster routing after deletion; historical call records are kept.',
    '重置熔断状态': 'Reset circuit state',
    '重置失败': 'Reset failed',
    '已重置': 'Reset',
    '重置后该渠道将恢复参与流量调度，若上游仍异常可能很快再次熔断。': 'The channel rejoins traffic after reset; if the upstream is still failing it may trip again quickly.',
    '历史数据未关联提供商': 'Legacy model without a linked provider',
    '历史模型未关联提供商，保存时保留原有地址与密钥': 'Legacy model without a linked provider; its URL and key are kept on save',
    '已关联提供商，点击模型名称可加载模型列表': 'Provider linked; click the model name to load the model list',
    '未关联': 'Not linked',
    '已加载': 'Loaded',
    '正在拉取': 'Loading',
    '拉取模型列表失败': 'Failed to load models',
    '模型列表拉取失败，可手动输入模型名称': 'Failed to load models; you can type a model name',
    '该运营商下没有匹配的模型': 'No matching models for this provider',
    '暂无可用模型': 'No models available',
    '暂无可用模型，请先在管理台启用文本模型': 'No models available; enable a text model in the admin console first',
    '未选择模型': 'No model selected',
    '未加载到模型：当前网关要求项目 Token，请在「设置」中填写 sk-gw- 密钥。': 'Could not load models: this gateway requires a project token. Enter an sk-gw- key in Settings.',
    '未加载到模型：请先在管理台添加并启用模型；如果网关开启了项目 Token 校验，请在「设置」中填写密钥。': 'Could not load models: add and enable a model in the admin console. If project-token validation is enabled, enter a key in Settings.',
    '模型配置已应用': 'Model configuration applied',
    '设置已保存': 'Settings saved',
    '模型：': 'Model: ',
    '聊天': 'Chat',
    '当前没有可导出的会话': 'No conversation to export',
    '导出失败': 'Export failed',
    '已导出当前会话': 'Conversation exported',
    '已开始下载': 'Download started',
    '导入失败：文件不是有效的 JSON': 'Import failed: the file is not valid JSON',
    '导入失败：没有识别到会话': 'Import failed: no conversations found',
    '导入的对话': 'Imported chat',
    '已导入': 'Imported',
    '已复制模型': 'Model copied',
    '本地会话保存失败：浏览器存储空间可能已满': 'Failed to save locally: browser storage may be full',
    '无法写入本地设置：浏览器存储空间可能已满': 'Could not save local settings: browser storage may be full',
    '当前环境': 'Current environment',
    '本地环境': 'Local environment',
    '生产环境': 'Production',
    '日': 'day',
    '月': 'month',
    '天': 'days',
    '日均': 'Daily average',
    '是': 'Yes',
    '否': 'No',

    // ==================== 后端常见消息（显示在界面中） ====================
    '查询成功': 'Success',
    '新增成功': 'Created',
    '更新成功': 'Updated',
    '删除成功': 'Deleted',
    '创建成功，密钥只显示一次': 'Created. The key is shown only once.',
    '已吊销': 'Revoked',
    '已重置': 'Reset',
    '提供商不存在': 'Provider not found',
    '模型不存在': 'Model not found',
    'Token 不存在': 'Token not found',
    '项目不存在': 'Project not found',
    '项目已停用': 'Project disabled',
    'API 地址不合法（仅支持 HTTPS 公网地址）': 'Invalid API URL (HTTPS public URLs only)',
    '服务器内部错误': 'Internal server error',
    '发生异常': 'An error occurred',
    '缺少 Authorization header 或 API Key': 'Missing Authorization header or API key',
    '请求参数验证失败': 'Invalid request parameters',
    '无管理员权限': 'No admin permission',
    '未授权': 'Unauthorized',
    '操作成功': 'Success',

    // ==================== 句子片段（被行内标签拆分） ====================
    '= 禁止调用。 调用次数在请求前检查；Token 和成本在响应后累计，属于软限额，最多超出一个请求。': '= blocked. Call counts are checked before the request; tokens and cost accumulate after the response (soft limits, at most one request over).',
    'Authorization: Bearer &lt;上游 key&gt;': 'Authorization: Bearer <upstream key>',
    '。 成功响应会带': '. Successful responses include',
    '。 每个集群按「渠道健康」中的路由策略选择模型：轮询、成本优先或延迟优先。': '. Each cluster picks models according to the routing strategy in Channel health: round-robin, cost-first, or latency-first.',
    '。兼容入口：': '. Compatible aliases:',
    '。网关只会用服务端配置的上游 Key 转发，Token 本身不会发给厂商。': '. The gateway always forwards with the server-side upstream key; the token itself is never sent to the provider.',
    '。请求体保持标准 OpenAI chat/completions 格式，': '. The request body uses the standard OpenAI chat/completions format,',
    '与': 'and',
    '事件，直到': 'events until',
    '兼容旧用法：不带': 'Legacy behavior: without a',
    '前缀时，主链（': 'prefix, the main chain (',
    '前缀的 Token 一定会被校验；无效、吊销、过期直接 401。 设置': 'prefixed tokens are always validated; invalid, revoked, or expired tokens get a 401. Set',
    '后，不带 Token 的请求也会被拒绝。': 'requests without a token are rejected as well.',
    '回落： 不以': 'Fallback: without a',
    '在「大模型提供商管理」新增提供商，填写名称、API 地址与 API Key。': 'Add a provider under Providers with its name, API URL, and API key.',
    '在「大模型管理」中启用该集群模型': 'Enable the cluster\'s models under Models',
    '在「大模型管理」新增模型，选择提供商并设置集群；temperature、单价与 max_tokens 可选。': 'Add a model under Models, select a provider, and set its cluster; temperature, price, and max_tokens are optional.',
    '在「项目与密钥」创建项目，签发': 'Create a project under Projects & keys and issue a',
    '在「项目与密钥」新建项目，按需设置配额，再创建 Token 并复制': 'Create a project under Projects & keys, set quotas as needed, then create a token and copy it',
    '如': 'e.g.',
    '带': 'with a',
    '建议留空，由服务端按': 'Leave empty to let the server use',
    '开头 →': 'prefix →',
    '开头的标识': 'prefix',
    '成功': 'Success',
    '成本只累计与项目币种一致的调用记录，不做汇率换算。Token 允许按模型名限制， 支持': 'Cost only accumulates records in the project\'s currency; no FX conversion. Tokens can be restricted by model name; supports',
    '指定的集群选择模型。': 'the selected cluster to choose a model.',
    '推荐：': 'Recommended:',
    '支持': 'Supports',
    '时按': 'uses',
    '时按实际扣费记录，其余厂商为估算值。': 'the actual charge is recorded; other providers are estimated.',
    '更新时间': 'Updated',
    '模型配置了': 'When a model configures',
    '模型配置输入/输出单价后，「用量明细」会显示估算成本（USD / 1M tokens）。 OpenRouter 返回': 'Set input/output prices to show estimated cost under Usage (USD / 1M tokens). When OpenRouter returns',
    '模型集群。主链建议': 'model cluster. The main chain usually uses',
    '渠道失败时会在同集群内自动换渠道重试（连接失败、超时、429、5xx、401/403）。 连续失败达到阈值会熔断并冷却，冷却后自动半开探测；可在「渠道健康」手动重置。 400/404/422 属于请求或模型本身问题，不会换渠道重试。': 'When a channel fails, the gateway retries other channels in the same cluster (connection errors, timeouts, 429, 5xx, 401/403). Consecutive failures trip the circuit breaker and start a cool-down; after cool-down it probes half-open. Reset it manually under Channel health. 400/404/422 are request/model problems and do not trigger failover.',
    '留空，通过': 'Leave empty and use',
    '请选择提供商': 'Select a provider',
    '选择集群。': 'choose a cluster.',
    '逗号分隔，支持 * 通配；留空表示允许集群内所有模型。': 'Comma-separated; * wildcards supported; empty allows all models in the cluster.',
    '通配，例如': 'wildcard, e.g.',
    '配额超限返回': 'Quota violations return',
    '鉴权': 'Authentication',
    '集群用': 'Cluster uses',
    '项目 Token 无效、吊销或过期': 'Project token invalid, revoked, or expired',
    '（OpenAI SDK 直接可用）': '(works directly with the OpenAI SDK)',
    '（SSE 原样透传）与普通 JSON 响应。模型名称、API 地址与 API Key 均在管理页配置，调用方无需接触上游地址。': '(SSE passed through as-is) and regular JSON responses. Model names, API URLs, and API keys are configured in the admin console; callers never need the upstream URL.',
    '（返回可用模型与集群）；内置聊天页：': '(returns available models and clusters); built-in chat:',
    '（默认）或任意以': '(default) or any value starting with',
    '）仍可用': ') still works',
    '，model 留空或使用合法名称': ', leave model empty or use a valid name',
    '，以': ', in',
    '，便于排查。': ' for troubleshooting.',
    '，可直接作为 OpenAI SDK 的': ', and can be used directly as the OpenAI SDK\'s',
    '，异步链建议': '; async chains usually use',
    '，调整项目限额或等待次日 / 次月': '. Adjust the project limits or wait for the next day/month',
    '，错误格式为': '. The error format is',
    '；同集群内轮询': '; round-robin within the cluster',
    '；留空表示不限。': '; empty means unlimited.',
    'Token 不允许使用该模型 / 项目已停用': 'Token is not allowed to use this model / project disabled',
    'Token， 请求头使用': 'Token. Use it in the request header',
    'X-Async-Type、model 或 JSON 非法': 'Invalid X-Async-Type, model, or JSON',
    'base_url 指向 /v1': 'point base_url to /v1',
    'base_url=http://你的地址:9010/v1': 'base_url=http://your-host:9010/v1',
    'Authorization: Bearer &lt;上游 key&gt;': 'Authorization: Bearer <upstream key>',
    '兼容旧用法：不带 sk-gw- 前缀的 Token': 'Legacy behavior: tokens without the sk-gw- prefix',
    '上游厂商返回错误': 'Upstream provider returned an error',
    '建议留空，由服务端按集群选择': 'Leave empty to let the server pick by cluster',

    // ==================== 聊天页 / 校验消息补充 ====================
    'API Key 无效或已过期': 'API key invalid or expired',
    'Authorization: Bearer sk-gw-你的项目Token': 'Authorization: Bearer sk-gw-your-project-token',
    'sk-gw-你的项目Token': 'sk-gw-your-project-token',
    'max_tokens 需为正整数': 'max_tokens must be a positive integer',
    'temperature 与 top_p 只能填写一个': 'Set only one of temperature and top_p',
    'temperature 需在 0 ~ 2 之间': 'temperature must be between 0 and 2',
    'temperature 需在 0~2 之间': 'temperature must be between 0 and 2',
    'top_k 需为正整数': 'top_k must be a positive integer',
    'top_p 需在 0 ~ 1 之间': 'top_p must be between 0 and 1',
    'top_p 需在 0~1 之间': 'top_p must be between 0 and 1',
    '输入单价需为不小于 0 的数字': 'Input price must be a number ≥ 0',
    '输出单价需为不小于 0 的数字': 'Output price must be a number ≥ 0',
    '上游返回了空响应': 'Upstream returned an empty response',
    '上游返回错误': 'Upstream returned an error',
    '获取模型详情失败': 'Failed to load model details',
    '请选择或输入模型': 'Select or type a model',
    '选择或输入模型': 'Select or type a model',
    '提供商参数必须是有效的 JSON': 'Provider parameters must be valid JSON',
    '额外配置必须是有效的 JSON': 'Extra config must be valid JSON',
    '更新于': 'Updated',
    '失败': 'Failed',
    '打开会话': 'Open conversation',
    '共': 'Total',
    '条记录': 'records',
    '条消息 ·': 'messages ·',
    '次 ·': '·',
    '次 · 近': '· last',
    '个会话': 'conversations',
    '个可用模型': 'models available',
    '运营商「': 'Provider "',
    '· 估算': '· estimated',
    '· 成本币种': '· cost currency',
    '· 输出': '· output',
    '解释一段代码': 'Explain code',
    '写一封邮件': 'Write an email',
    '拆解一个需求': 'Break down a requirement',
    '总结一段文字': 'Summarize text',
    '请逐行解释下面这段代码，并指出潜在问题：\n\n': 'Explain the following code line by line and point out potential issues:\n\n',
    '帮我写一封简洁、专业的邮件，主题是：\n\n': 'Write a concise, professional email with the subject:\n\n',
    '请把下面这个需求拆解成可执行的开发任务，并标注优先级：\n\n': 'Break the following requirement into actionable development tasks and mark their priority:\n\n',
    '请用要点总结下面这段内容，并给出三条关键结论：\n\n': 'Summarize the following content as bullet points and give three key conclusions:\n\n',
    '思考过程': 'Thinking process',
    '在下方输入消息，Enter 发送': 'Type a message below and press Enter to send',
    '聊天': 'Chat',

    // ==================== 登录后空状态 / 状态标签 ====================
    '暂无 Token 消耗数据': 'No token usage data yet',
    '暂无调用记录': 'No call records yet',
    '暂无提供商，请先新增一个': 'No providers yet. Add one to get started.',
    '暂无模型，请点击「新增模型」添加': 'No models yet. Click "Add model" to create one.',
    '暂无项目，点击右上角新增': 'No projects yet. Click Add in the top-right corner.',
    '暂无启用中的模型': 'No active models',
    '估算成本': 'Estimated cost',
    '占比': 'Share',
    '正常': 'Healthy',
    '半开': 'Half-open',
    '熔断': 'Open',
    '默认': 'Default',
    '未配置': 'Not configured',
    '非流式': 'Non-streaming',
    '已用': 'Used',
    '可用': 'Available',
    '未用': 'Unused',
    '文本': 'Text',
    '语音': 'Audio',
    '跟随': 'Follow',
    '开启': 'On',
    '暂无配置': 'No configuration yet',
    '自定义': 'Custom',
    '主模型': 'Main model',
    '异步通用': 'Async (general)',
    '暂无渠道': 'No channels yet',
    '近 30 天暂无调用': 'No calls in the last 30 days',
    '还没有 Token，点击右上角新建': 'No tokens yet. Click New in the top-right corner.',
    '加载失败': 'Load failed',
    '没有匹配的提供商': 'No matching providers',
    '没有匹配的模型': 'No matching models',
  };

  // Dynamic strings: number + unit, or text assembled at runtime.
  const PATTERNS = [
    [/^(.+?) 调用 (.+?) 次 输入 (.+?) · 输出 (.+?) 总 Token (.+)$/, '$1\nCalls $2\nInput $3 · Output $4\nTotal tokens $5'],
    [/^输入\s*(.+?)\s*·\s*输出\s*(.+?)\s*·\s*估算\s*(.+)$/, 'Input $1 · Output $2 · Est. $3'],
    [/^输入\s*(.+?)\s*·\s*输出\s*(.+)$/, 'Input $1 · Output $2'],
    [/^缓存命中\s*(.+)$/, 'Cache hits $1'],
    [/^共\s*(\d+)\s*条记录$/, 'Total $1 records'],
    [/^共\s*(\d+)\s*条$/, 'Total $1'],
    [/^共\s*(.+)$/, 'Total $1'],
    [/^打开会话\s+(.+)$/, function (m, name) { return 'Open conversation ' + t(name); }],
    [/^删除会话\s+(.+)$/, function (m, name) { return 'Delete conversation ' + t(name); }],
    [/^(\d+)\s*条记录$/, '$1 records'],
    [/^(\d+)\s*个会话$/, '$1 conversations'],
    [/^(\d+)\s*个可用模型$/, '$1 models available'],
    [/^(\d+)\s*个模型$/, '$1 models'],
    [/^(\d+)\s*个$/, '$1 models'],
    [/^已导入\s*(\d+)\s*个会话$/, 'Imported $1 conversations'],
    [/^已加载\s*(\d+)\s*个可用模型，点击模型名称选择$/, 'Loaded $1 models; click a model name to select'],
    [/^日均\s*(.+)\s*次\s*·\s*近\s*(\d+)\s*天$/, 'Daily average $1 calls · last $2 days'],
    [/^调用\s*(.+)\s*次\s*·\s*(.+)$/, '$1 calls · $2'],
    [/^(.+?)\s*·\s*(\d+)\s*条消息\s*·\s*(.*)$/, function (m, a, count, tail) {
      return translateSegments(a) + ' · ' + count + ' messages · ' + translateSegments(tail);
    }],
    [/^(\d+)\s*条消息\s*·\s*(.*)$/, '$1 messages · $2'],
    [/^运营商「(.+)」下可用\s*(\d+)\s*个模型，也可直接输入模型名$/, 'Provider "$1" has $2 models; you can also type a model name'],
    [/^运营商「(.+)」$/, 'Provider "$1"'],
    [/^运营商「(.+)$/, 'Provider "$1'],
    [/^未限定运营商，共\s*(\d+)\s*个可用模型$/, 'No provider filter; $1 models available'],
    [/^正在拉取\s*(.+)\s*的模型列表\.\.\.$/, 'Loading models for $1...'],
    [/^项目 ID\s*(.+)\s*·\s*成本币种\s*(.+)$/, 'Project ID $1 · cost currency $2'],
    [/^模型：\s*(.+)$/, 'Model: $1'],
    [/^集群(\d+)$/, 'Cluster $1'],
    [/^环境(\d+)$/, 'Environment $1'],
    [/^更新于\s*(.+)$/, 'Updated $1'],
    [/^已选择\s*(\d+)\s*个文件$/, '$1 files selected'],
    [/^获取模型列表失败:\s*(.+)$/, 'Failed to load models: $1'],
    [/^上游返回错误\s*\(HTTP\s*(\d+)\):\s*(.*)$/s, 'Upstream error (HTTP $1): $2'],
    [/^流式转发失败:\s*(.+)$/, 'Streaming forward failed: $1'],
    [/^转发请求失败:\s*(.+)$/, 'Forwarding failed: $1'],
  ];

  // Substring fixes applied inside <pre>/<code> without damaging formatting.
  const CODE_REPLACEMENTS = [
    [/sk-gw-你的项目Token/g, 'sk-gw-your-project-token'],
    [/你的项目Token/g, 'your-project-token'],
    [/你的地址/g, 'your-host'],
    [/上游 key/g, 'upstream key'],
    [/留空由网关按集群选择/g, 'leave empty to let the gateway pick by cluster'],
    [/你好/g, 'Hello'],
  ];

  function normalize(s) {
    return s.replace(/\s+/g, ' ').trim();
  }

  // Decode HTML entities in keys so they match rendered DOM text.
  const decodedDict = {};
  Object.keys(DICT).forEach(function (key) {
    const k = key
      .replace(/&lt;/g, '<')
      .replace(/&gt;/g, '>')
      .replace(/&amp;/g, '&');
    decodedDict[k] = DICT[key];
  });

  function detectLang() {
    try {
      const stored = localStorage.getItem(LANG_KEY);
      if (SUPPORTED.indexOf(stored) !== -1) return stored;
    } catch (e) { /* storage may be unavailable */ }
    return DEFAULT_LANG;
  }

  let lang = detectLang();

  function translate(text) {
    if (text === null || text === undefined) return null;
    if (decodedDict[text] !== undefined) return decodedDict[text];
    const key = normalize(text);
    if (!key) return null;
    if (decodedDict[key] !== undefined) return decodedDict[key];
    for (let i = 0; i < PATTERNS.length; i++) {
      if (PATTERNS[i][0].test(key)) return key.replace(PATTERNS[i][0], PATTERNS[i][1]);
    }
    return null;
  }

  function t(text) {
    if (lang === 'zh') return text;
    const out = translate(text);
    return out !== null ? out : text;
  }

  // Translate each " · "-separated segment, keeping separators intact.
  function translateSegments(text) {
    return String(text).split(/\s*·\s*/).map(function (part) { return t(part); }).join(' · ');
  }

  function isSkipped(el) {
    return !!(el && el.closest && el.closest('[data-no-i18n]'));
  }

  function translateCodeNode(node) {
    let value = node.nodeValue;
    if (!value) return;
    let changed = false;
    for (let i = 0; i < CODE_REPLACEMENTS.length; i++) {
      const next = value.replace(CODE_REPLACEMENTS[i][0], CODE_REPLACEMENTS[i][1]);
      if (next !== value) { value = next; changed = true; }
    }
    if (changed) node.nodeValue = value;
  }

  function translateTextNode(node) {
    const value = node.nodeValue;
    if (!value || !value.trim()) return;
    const parent = node.parentElement;
    if (!parent || isSkipped(parent)) return;
    if (parent.closest('script, style, textarea')) return;
    if (parent.closest('pre, code')) {
      translateCodeNode(node);
      return;
    }
    const core = value.trim();
    const out = translate(core);
    if (out === null || out === core) return;
    // Preserve surrounding whitespace so inline elements keep their spacing.
    const start = value.indexOf(core);
    const lead = value.slice(0, start);
    const trail = value.slice(start + core.length);
    node.nodeValue = lead + out + trail;
  }

  function translateElementAttrs(el) {
    if (!el || el.nodeType !== 1 || isSkipped(el)) return;
    for (let i = 0; i < ATTRS.length; i++) {
      const name = ATTRS[i];
      const value = el.getAttribute(name);
      if (!value) continue;
      const out = translate(value);
      if (out !== null && out !== value) el.setAttribute(name, out);
    }
  }

  function translateSubtree(root) {
    if (!root) return;
    if (root.nodeType === 3) {
      translateTextNode(root);
      return;
    }
    if (root.nodeType !== 1) return;
    if (isSkipped(root)) return;
    translateElementAttrs(root);
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null);
    let node;
    while ((node = walker.nextNode())) translateTextNode(node);
    const elements = root.querySelectorAll('*');
    for (let i = 0; i < elements.length; i++) translateElementAttrs(elements[i]);
  }

  function mountSwitcher() {
    if (document.querySelector('.i18n-switch')) return;
    const wrap = document.createElement('div');
    wrap.className = 'i18n-switch';
    wrap.setAttribute('data-no-i18n', '');
    wrap.setAttribute('role', 'group');
    wrap.setAttribute('aria-label', 'Language');
    const en = document.createElement('button');
    en.type = 'button';
    en.textContent = 'EN';
    en.dataset.lang = 'en';
    const zh = document.createElement('button');
    zh.type = 'button';
    zh.textContent = '中文';
    zh.dataset.lang = 'zh';
    const buttons = [en, zh];
    buttons.forEach(function (btn) {
      if (btn.dataset.lang === lang) btn.classList.add('active');
      btn.addEventListener('click', function () {
        if (btn.dataset.lang === lang) return;
        try { localStorage.setItem(LANG_KEY, btn.dataset.lang); } catch (e) { /* ignore */ }
        location.reload();
      });
      wrap.appendChild(btn);
    });
    // The chat page has a composer in the bottom-right corner, so mount the
    // switch inside its sidebar. Other pages get a floating pill.
    const isChat = !!document.getElementById('messageInput');
    const foot = document.querySelector('.sidebar-foot');
    if (isChat && foot) {
      wrap.classList.add('i18n-switch-inline');
      foot.insertBefore(wrap, foot.firstChild);
    } else {
      wrap.classList.add('i18n-switch-floating');
      document.body.appendChild(wrap);
    }
  }

  function injectStyles() {
    if (document.getElementById('i18n-style')) return;
    const style = document.createElement('style');
    style.id = 'i18n-style';
    style.textContent =
      '.i18n-switch{display:inline-flex;align-items:center;gap:2px;padding:3px;border-radius:999px;font-family:inherit}' +
      '.i18n-switch-floating{position:fixed;right:16px;bottom:16px;z-index:99999;background:rgba(15,23,42,.72);' +
      'backdrop-filter:blur(6px);box-shadow:0 4px 14px rgba(0,0,0,.18)}' +
      '.i18n-switch-inline{align-self:flex-start;margin:0 0 10px;background:rgba(148,163,184,.14)}' +
      '.i18n-switch button{border:0;background:transparent;color:#94a3b8;font-size:11.5px;line-height:1;' +
      'padding:5px 10px;border-radius:999px;cursor:pointer;font-family:inherit;transition:background .15s,color .15s}' +
      '.i18n-switch button:hover{color:#fff}' +
      '.i18n-switch button.active{background:#fff;color:#0f172a;font-weight:600}' +
      '@media (max-width:600px){.i18n-switch-floating{right:10px;bottom:74px}}';
    document.head.appendChild(style);
  }

  function applyDocumentTitle() {
    if (lang === 'zh') return;
    const title = document.title;
    const out = translate(title);
    if (out !== null) document.title = out;
  }

  function setHtmlLang() {
    document.documentElement.lang = lang === 'zh' ? 'zh-CN' : 'en';
  }

  function start() {
    setHtmlLang();
    mountSwitcher();
    injectStyles();
    if (lang === 'zh') return;
    applyDocumentTitle();
    translateSubtree(document.body);

    const observer = new MutationObserver(function (mutations) {
      for (let i = 0; i < mutations.length; i++) {
        const m = mutations[i];
        if (m.type === 'childList') {
          for (let j = 0; j < m.addedNodes.length; j++) translateSubtree(m.addedNodes[j]);
        } else if (m.type === 'characterData') {
          translateTextNode(m.target);
        } else if (m.type === 'attributes') {
          translateElementAttrs(m.target);
        }
      }
    });
    observer.observe(document.body, {
      childList: true,
      subtree: true,
      characterData: true,
      attributes: true,
      attributeFilter: ATTRS,
    });
  }

  window.I18N = {
    get lang() { return lang; },
    setLang: function (next) {
      if (SUPPORTED.indexOf(next) === -1 || next === lang) return;
      try { localStorage.setItem(LANG_KEY, next); } catch (e) { /* ignore */ }
      location.reload();
    },
    t: t,
    apply: function (root) { translateSubtree(root || document.body); },
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();
