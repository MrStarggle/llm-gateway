# LLM Gateway

一个轻量的多厂商大模型统一接入网关：用 OpenAI 兼容协议对接多家模型服务，
在管理台统一维护提供商、模型、集群与请求参数，并记录调用用量。

## 特性

- **多厂商统一接入**：OpenAI 兼容 `POST /chat/completions`，支持流式（SSE）与非流式
- **提供商集中配置**：API 地址与 Key 在提供商层统一维护，模型引用提供商配置
- **模型集群与轮询**：模型按 `async1..async9` 划分为 9 个集群，同集群内自动轮询
- **厂商参数适配**：内置 DeepSeek/GLM/MiniMax/Claude/Gemini/Qwen 等思考参数与协议差异处理
- **模型级参数覆盖**：`temperature` / `top_p` / `top_k` / `max_tokens` 可按模型覆盖
- **用量统计**：Token 用量、调用记录、按模型/功能码/用户分组
- **成本估算**：模型配置输入/输出单价后，按调用记录估算成本（OpenRouter 可直接用上游返回的实际扣费）
- **管理台**：提供商、模型、集群、用量与接入说明一体化
- **单管理员模式**：环境变量配置账号，JWT 登录，无需额外用户系统
- **零配置存储**：默认 SQLite，开箱即用；需要多实例时可切换 MySQL

## 最简单：一键启动

需要 Python 3.10+（安装时勾选 “Add Python to PATH”）。

- **Windows**：双击 `start.bat`
- **macOS / Linux**：`./start.sh`

脚本会自动创建虚拟环境、安装依赖、生成 `.env`、启动服务并打开管理台。
默认地址 <http://127.0.0.1:9010/>，默认账号 `admin / admin`。

> 默认账号只适合本机使用；如果要对局域网或公网开放，先修改 `.env` 中的
> `ADMIN_USERNAME` / `ADMIN_PASSWORD` / `JWT_SECRET_KEY`。

## 快速开始（Docker）

```bash
cp .env.example .env
# 修改 .env 中的管理员账号与 JWT_SECRET_KEY
docker compose up -d --build
```

打开 <http://localhost:9010/>，使用 `.env` 中的管理员账号登录。

默认使用 SQLite，数据库文件持久化在 `gateway_data` 卷中，无需额外数据库服务。

## 手动启动（本地开发）

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env

uvicorn main:app --host 0.0.0.0 --port 9010
```

应用启动时会自动建表，数据库默认写入 `data/gateway.db`。

> SQLite 适合单机单进程部署。不要同时启动多个 uvicorn worker 或多个实例共享同一个
> SQLite 文件；需要多实例/高并发写入时，请切换到 MySQL。

## 配置

| 环境变量 | 说明 | 默认 |
|---|---|---|
| `DB_BACKEND` | `sqlite` 或 `mysql` | `sqlite` |
| `SQLITE_PATH` | SQLite 数据文件路径 | `data/gateway.db` |
| `DATABASE_URL` | 显式 SQLAlchemy 异步连接串，优先级最高 | 空 |
| `MYSQL_HOST` / `MYSQL_PORT` / `MYSQL_USER` / `MYSQL_PASSWORD` / `MYSQL_DATABASE` | MySQL 连接（`DB_BACKEND=mysql` 时使用） | localhost / 3306 / root / 空 / `llm_gateway` |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | 管理台登录账号（明文保存在 env，单管理员） | `admin` / `admin` |
| `JWT_SECRET_KEY` | JWT 签名密钥，生产必须修改 | 代码默认 `dev-only-change-me`；示例文件里是占位符 |
| `PORT` | 服务端口 | `9010` |
| `GATEWAY_DEBUG` | `1` 时输出请求体调试日志 | `0` |
| `CORS_ORIGINS` | 跨域管理台来源，逗号分隔 | 空（同源即可） |

### 管理员账号

开源版没有用户表，只有一组环境变量管理员账号：

```bash
ADMIN_USERNAME=admin
ADMIN_PASSWORD=admin
JWT_SECRET_KEY=change-me-to-a-long-random-string
```

- 改账号/密码：修改 `.env` 后**重启服务**，已签发的 JWT 在过期前仍然有效（默认 7 天）
- 改 `JWT_SECRET_KEY`：所有已签发 token 立即失效
- 没有注册、找回密码、多用户；需要这些能力就按「接入自有用户体系」替换鉴权层
- 默认 `admin / admin` 仅适合本机；对局域网或公网开放前必须修改

### SQLite 数据与备份

默认数据库是单文件 `data/gateway.db`，首次启动自动创建。

```bash
# 停止服务后直接复制即可
cp data/gateway.db data/gateway.db.bak
```

WAL 模式下会同时存在 `gateway.db-wal` / `gateway.db-shm`；运行中需要备份时用：

```bash
sqlite3 data/gateway.db ".backup 'data/gateway.db.bak'"
```

Docker 部署时数据在 `gateway_data` 卷里，不要删除该卷。

### 切换到 MySQL

先在 MySQL 中建库（表由程序启动时自动创建）：

```sql
CREATE DATABASE IF NOT EXISTS llm_gateway
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

然后在 `.env` 中配置：

```bash
DB_BACKEND=mysql
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=your-password
MYSQL_DATABASE=llm_gateway
```

MySQL 模式会在启动时执行 `app/db/schema.sql` 与幂等迁移。
SQLite 和 MySQL 之间没有自动数据迁移；切换前需要自己导出/导入。

### 安全与部署提示

- 公网部署前必须修改 `ADMIN_USERNAME` / `ADMIN_PASSWORD` / `JWT_SECRET_KEY`
- 建议放在 HTTPS 反向代理（Nginx/Caddy）之后，并在代理层加登录限流
- SQLite 模式只运行一个进程，不要使用多个 worker 或多个实例共享同一文件
- 完整请求体和模型响应默认**不写日志**；`GATEWAY_DEBUG=1` 才会打印，其中可能包含用户提示词

### 接入自有用户体系

开源版默认是单管理员模式：`app/api/v1/controller/auth_controller.py` 用 env 中的
`ADMIN_USERNAME` / `ADMIN_PASSWORD` 校验并签发 JWT，全程不查用户表。

如果要接入你自己的用户表/OAuth/SSO，只需要替换两处：

- `auth_controller.py`：登录接口改为校验你自己的用户
- `admin_auth.verify_admin_token`：改为校验你的 token（或复用同一套 JWT）

管理接口统一通过 `Depends(verify_admin_token)` 鉴权，替换这一层即可。

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
| `X-Purpose` | `main` / 任意以 `async` 开头的标识 | 异步判定、日志与用量统计；不影响集群选择 |
| `X-Thinking` | `1` / `0` | 思考开关；仅在模型思考模式为「跟随请求」时生效 |
| `X-Response-Format` | `json_object` | 要求 JSON 输出 |
| `X-User-Id` | 调用方标识 | 用于调用记录与用量统计 |
| `X-Feature-Code` | 如 `role_reply` | 功能码，用于用量明细分组统计；不传记为 `uncategorized` |
| `Authorization` | `Bearer <key>` | 可选；主链可覆盖服务端配置的上游 Key |

## 项目结构

```
app/
  api/v1/controller/   管理端、模型、调用转发接口
  config/              数据库与运行配置
  db/schema.sql        MySQL 建表脚本（SQLite 由 ORM 自动建表）
  models/              提供商、模型、用量 ORM
  services/            模型选择/轮询、用量统计、提供商管理
  utils/               JWT、雪花 ID、统一响应
templates/model_manage.html   管理台
main.py                        FastAPI 入口
```

## License

Apache-2.0
