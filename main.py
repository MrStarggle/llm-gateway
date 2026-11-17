"""StarggleAPI - 多厂商大模型统一接入网关"""
import asyncio
import logging
import os
import re
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

# 先加载 .env，再导入会在模块级读取环境变量的模块
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

from app.api.v1.api import api_router  # noqa: E402
from app.api.v1.controller import call_manage_controller  # noqa: E402

logger = logging.getLogger()  # root logger — 让所有模块的日志都能输出
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s %(message)s", "%Y-%m-%d %H:%M:%S"))
    logger.addHandler(handler)

# 关闭第三方库的 INFO 日志（httpx, urllib3 等）
for lib in ("httpx", "httpcore", "urllib3"):
    logging.getLogger(lib).setLevel(logging.WARNING)

DEBUG = os.environ.get("GATEWAY_DEBUG", "").lower() in ("1", "true", "yes")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # 启动时：初始化数据库
    from app.config.database import init_database
    db_ok = await init_database()
    if not db_ok:
        logger.warning("数据库初始化未完全成功，部分功能可能不可用")

    # 原始调用明细保留期清理（项目日聚合表不删）
    try:
        retention_days = int(os.getenv("USAGE_RETENTION_DAYS", "90") or 0)
    except ValueError:
        retention_days = 90
    if retention_days > 0:
        try:
            from app.config.database import AsyncSessionLocal
            from app.services.usage_manage_service import cleanup_old_records
            async with AsyncSessionLocal() as db:
                deleted = await cleanup_old_records(db, retention_days)
            if deleted:
                logger.info("已清理 %d 条超过 %d 天的调用明细", deleted, retention_days)
        except Exception as e:
            logger.warning("调用明细清理失败（不影响启动）: %s", e)

    # LLM 报文日志开关（默认开启，可在管理台「渠道健康」切换）
    log_refresh_task = None
    if db_ok:
        try:
            from app.config.database import AsyncSessionLocal
            from app.services import log_settings_service
            async with AsyncSessionLocal() as db:
                enabled = await log_settings_service.load(db)
            log_refresh_task = asyncio.create_task(log_settings_service.refresh_loop())
            logger.info("LLM 报文日志：%s", "开启" if enabled else "关闭")
        except Exception as e:
            logger.warning("加载 LLM 报文日志开关失败，使用默认值: %s", e)

    if DEBUG:
        logger.info("DEBUG 模式已开启 — 错误响应将包含调试信息")
    yield

    if log_refresh_task:
        log_refresh_task.cancel()
        try:
            await log_refresh_task
        except asyncio.CancelledError:
            pass

    # 关闭时：清理资源
    from app.config.database import engine
    await engine.dispose()
    logger.info("数据库连接池已释放")


app = FastAPI(title="StarggleAPI", lifespan=lifespan)
app.state.DEBUG = DEBUG

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class RequestIdMiddleware:
    """为每个请求生成/透传 X-Request-Id，纯 ASGI 实现，不影响流式响应."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        raw = ""
        for key, value in scope.get("headers", []):
            if key.lower() == b"x-request-id":
                raw = value.decode("latin-1").strip()
                break
        request_id = raw if _REQUEST_ID_RE.match(raw) else uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id

        async def send_with_request_id(message):
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                headers[:] = [
                    (k, v) for k, v in headers if k.lower() != b"x-request-id"
                ]
                headers.append((b"x-request-id", request_id.encode("latin-1")))
            await send(message)

        await self.app(scope, receive, send_with_request_id)


# 管理台默认同源访问；跨域部署时通过 CORS_ORIGINS 配置允许来源（逗号分隔）
_cors_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# 最后添加的中间件最先执行，确保所有响应都带请求 ID
app.add_middleware(RequestIdMiddleware)

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

# 挂载 v1 API 路由
app.include_router(api_router, prefix="/api/v1")

# 同时挂载到 /router 中间路径（兼容既有调用）
app.include_router(api_router, prefix="/router")

# OpenAI 客户端友好入口：base_url=http://host:9010/v1
app.include_router(call_manage_controller.router, prefix="/v1", tags=["OpenAI 兼容入口"])


# ---------- 前端管理台 ----------
@app.get("/", response_class=HTMLResponse)
@app.get("/model-manage", response_class=HTMLResponse)
async def manage_page():
    html_path = BASE_DIR / "templates" / "model_manage.html"
    return HTMLResponse(
        html_path.read_text(encoding="utf-8"),
        headers={"Cache-Control": "no-store"},
    )


@app.get("/chat", response_class=HTMLResponse)
@app.get("/chat/", response_class=HTMLResponse)
async def chat_page():
    """内置聊天页：会话保存在浏览器本地，网关只负责转发和记账."""
    html_path = BASE_DIR / "templates" / "chat.html"
    return HTMLResponse(
        html_path.read_text(encoding="utf-8"),
        headers={"Cache-Control": "no-store"},
    )


if __name__ == "__main__":
    import asyncio

    import uvicorn

    port = int(os.getenv("PORT", "9010"))
    config = uvicorn.Config(app, host="0.0.0.0", port=port)
    server = uvicorn.Server(config)
    asyncio.run(server.serve())
