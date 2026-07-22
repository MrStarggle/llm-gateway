import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.api.v1.api import api_router

logger = logging.getLogger("starggle")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S"))
    logger.addHandler(handler)
logger.propagate = False

DEBUG = os.environ.get("STARGGLE_DEBUG", "").lower() in ("1", "true", "yes")

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


app = FastAPI(title="LLM API 转发服务 v2", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://www.starggle.com"],
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent
COMPANLIST_FILE = BASE_DIR / "companlist.txt"

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

# 挂载 v1 API 路由
app.include_router(api_router, prefix="/api/v1")

# 同时挂载到 /router 中间路径
app.include_router(api_router, prefix="/router")


# ---------- 厂家列表文件读写 ----------
def read_companlist():
    companies = []
    if COMPANLIST_FILE.exists():
        with open(COMPANLIST_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    parts = line.split(",", 2)
                    if len(parts) >= 2:
                        companies.append({
                            "domain": parts[0].strip(),
                            "name": parts[1].strip(),
                            "notes": parts[2].strip() if len(parts) > 2 else ""
                        })
    return companies


def write_companlist(companies):
    with open(COMPANLIST_FILE, "w", encoding="utf-8") as f:
        f.write("# 域名, 厂家名称, 备注\n")
        for c in companies:
            f.write(f"{c['domain']}, {c['name']}, {c.get('notes', '')}\n")


# ---------- Pydantic 模型 ----------
class CompanyCreate(BaseModel):
    domain: str
    name: str
    notes: str = ""


class CompanyUpdate(BaseModel):
    domain: str
    name: str
    notes: str = ""


# ---------- 厂家管理 API ----------
@app.get("/api/companlist")
async def get_companlist():
    companies = read_companlist()
    logger.info(f"GET /api/companlist -> {len(companies)} companies")
    return companies


@app.post("/api/companlist", status_code=201)
async def add_company(company: CompanyCreate):
    companies = read_companlist()
    companies.append({"domain": company.domain, "name": company.name, "notes": company.notes})
    write_companlist(companies)
    logger.info(f"POST /api/companlist -> add domain={company.domain} name={company.name}")
    return {"message": "ok"}


@app.put("/api/companlist/{index}")
async def update_company(index: int, company: CompanyUpdate):
    companies = read_companlist()
    if index < 0 or index >= len(companies):
        logger.warning(f"PUT /api/companlist/{index} -> 404 index not found")
        raise HTTPException(status_code=404, detail="索引不存在")
    companies[index] = {"domain": company.domain, "name": company.name, "notes": company.notes}
    write_companlist(companies)
    logger.info(f"PUT /api/companlist/{index} -> update domain={company.domain} name={company.name}")
    return {"message": "ok"}


@app.delete("/api/companlist/{index}")
async def delete_company(index: int):
    companies = read_companlist()
    if index < 0 or index >= len(companies):
        logger.warning(f"DELETE /api/companlist/{index} -> 404 index not found")
        raise HTTPException(status_code=404, detail="索引不存在")
    removed = companies.pop(index)
    write_companlist(companies)
    logger.info(f"DELETE /api/companlist/{index} -> removed domain={removed['domain']} name={removed['name']}")
    return {"message": "ok"}


# ---------- 前端页面 ----------
@app.get("/", response_class=HTMLResponse)
async def index():
    html_path = BASE_DIR / "templates" / "index.html"
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


@app.get("/model-manage", response_class=HTMLResponse)
async def model_manage_page():
    html_path = BASE_DIR / "templates" / "model_manage.html"
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    import uvicorn
    import asyncio

    logger.debug("DEBUG 模式已开启 — 请求体将完整打印到日志")

    config = uvicorn.Config(app, host="0.0.0.0", port=9010)
    server = uvicorn.Server(config)
    asyncio.run(server.serve())
