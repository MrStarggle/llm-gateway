# LLM Gateway

一个轻量的多厂商大模型统一接入网关：用 OpenAI 兼容协议对接多家模型服务，
在管理台统一维护提供商、模型、集群与请求参数，并记录调用用量。

## 特性

- **多厂商统一接入**：OpenAI 兼容 `POST /chat/completions`，支持流式（SSE）与非流式
- **提供商集中配置**：API 地址与 Key 在提供商层统一维护，模型引用提供商配置
- **模型集群与轮询**：模型按 `async1..async9` 划分为 9 个集群，同集群内自动轮询
- **厂商参数适配**：内置 DeepSeek/GLM/MiniMax/Claude/Gemini/Qwen 等思考参数与协议差异处理
- **模型级参数覆盖**：`temperature` / `top_p` / `top_k` / `max_tokens` 可按模型覆盖
- **用量统计**：Token 用量、调用记录、按模型分布
- **管理台**：提供商、模型、集群、用量与接入说明一体化
- **单管理员模式**：环境变量配置账号，JWT 登录，无需额外用户系统

## 快速开始（Docker）

```bash
cp .env.example .env
# 修改 .env 中的 MySQL 密码、管理员账号、JWT_SECRET_KEY
docker compose up -d --build
```

打开 <http://localhost:9010/>，使用 `.env` 中的管理员账号登录。

## 本地运行

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# 准备 MySQL 数据库（默认库名 llm_gateway），并填写 .env

uvicorn main:app --host 0.0.0.0 --port 9010
```

应用启动时会自动建表并执行幂等迁移。

## 配置

| 环境变量 | 说明 | 默认 |
|---|---|---|
| `MYSQL_HOST` / `MYSQL_PORT` / `MYSQL_USER` / `MYSQL_PASSWORD` / `MYSQL_DATABASE` | MySQL 连接 | localhost / 3306 / root / 空 / `llm_gateway` |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | 管理台登录账号 | `admin` / `admin` |
| `JWT_SECRET_KEY` | JWT 签名密钥，生产必须修改 | `dev-only-change-me` |
| `PORT` | 服务端口 | `9010` |
| `GATEWAY_DEBUG` | `1` 时输出请求体调试日志 | `0` |
| `CORS_ORIGINS` | 跨域管理台来源，逗号分隔 | 空（同源即可） |

## 调用

统一入口：

```bash
curl -X POST "http://localhost:9010/router/call-manage/chat/completions" \
  -H "Content-Type: application/json" \
  -H "X-Async-Type: async1" \
  -d '{
    "model": "",
    "messages": [{"role": "user", "content": "你好"}],
    "stream": false
  }'
```

请求头：

| 请求头 | 取值 | 说明 |
|---|---|---|
| `X-Async-Type` | `async1`..`async9` | 模型集群；不传时主链默认 `async1`、异步链默认 `async2` |
| `X-Purpose` | `main` / `async1`..`async13` | 用途标识，用于日志与用量统计 |
| `X-Thinking` | `1` / `0` | 思考开关；仅在模型思考模式为「跟随请求」时生效 |
| `X-Response-Format` | `json_object` | 要求 JSON 输出 |
| `X-User-Id` | 调用方标识 | 用于调用记录与用量统计 |
| `Authorization` | `Bearer <key>` | 可选；主链可覆盖服务端配置的上游 Key |

## 项目结构

```
app/
  api/v1/controller/   管理端、模型、调用转发接口
  config/              数据库与运行配置
  db/schema.sql        MySQL 建表脚本
  models/              提供商、模型、用量 ORM
  services/            模型选择/轮询、用量统计、提供商管理
  utils/               JWT、雪花 ID、统一响应
templates/model_manage.html   管理台
main.py                        FastAPI 入口
```

## License

Apache-2.0
