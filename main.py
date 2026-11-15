"""LLM Gateway - 多厂商大模型统一接入网关"""
import logging
import os
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
    if DEBUG:
        logger.info("DEBUG 模式已开启 — 请求体将完整打印到日志")
    yield
    # 关闭时：清理资源
    from app.config.database import engine
    await engine.dispose()
    logger.info("数据库连接池已释放")


app = FastAPI(title="LLM Gateway", lifespan=lifespan)

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

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

# 挂载 v1 API 路由
app.include_router(api_router, prefix="/api/v1")

# 同时挂载到 /router 中间路径（兼容既有调用）
app.include_router(api_router, prefix="/router")


# ---------- 前端管理台 ----------
@app.get("/", response_class=HTMLResponse)
@app.get("/model-manage", response_class=HTMLResponse)
async def manage_page():
    html_path = BASE_DIR / "templates" / "model_manage.html"
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    import asyncio

    import uvicorn

    port = int(os.getenv("PORT", "9010"))
    config = uvicorn.Config(app, host="0.0.0.0", port=port)
    server = uvicorn.Server(config)
    asyncio.run(server.serve())
