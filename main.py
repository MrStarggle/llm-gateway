import logging
import time
from enum import Enum
from typing import Optional
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import httpx

logger = logging.getLogger("starggle")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S"))
    logger.addHandler(handler)
logger.propagate = False

app = FastAPI(title="LLM API 转发服务 v2")

BASE_DIR = Path(__file__).resolve().parent
COMPANLIST_FILE = BASE_DIR / "companlist.txt"

class Vendor(str, Enum):
    openrouter = "openrouter"
    claude = "claude"
    gemini = "gemini"
    grok = "grok"
    gpt = "gpt"

VENDOR_CONFIG = {
    Vendor.openrouter: {
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "auth_header": "Authorization",
        "auth_prefix": "Bearer ",
    },
    Vendor.claude: {
        "url": "https://api.anthropic.com/v1/messages",
        "auth_header": "x-api-key",
        "auth_prefix": "",
        "extra_headers": {"anthropic-version": "2023-06-01"},
    },
    Vendor.gemini: {
        "url": "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        "auth_header": "x-goog-api-key",
        "auth_prefix": "",
    },
    Vendor.grok: {
        "url": "https://api.x.ai/v1/chat/completions",
        "auth_header": "Authorization",
        "auth_prefix": "Bearer ",
    },
    Vendor.gpt: {
        "url": "https://api.openai.com/v1/chat/completions",
        "auth_header": "Authorization",
        "auth_prefix": "Bearer ",
    },
}

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


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


# ---------- 模型调用转发 ----------
@app.post("/{vendor}/chat/completions")
async def call_model(vendor: Vendor, request: Request, authorization: Optional[str] = Header(None)):
    t0 = time.perf_counter()
    cfg = VENDOR_CONFIG[vendor]

    api_key = ""
    if authorization:
        api_key = authorization.removeprefix("Bearer ").strip()
    if not api_key:
        raise HTTPException(status_code=401, detail="缺少 Authorization header 或 API Key")

    body = await request.json()
    body["stream"] = False
    model_name = body.get("model", "unknown")
    url = cfg.get("url", "").format(model=model_name)

    logger.info(f"POST /{vendor.value}/chat/completions -> model={model_name} body={body}")
    logger.info(f"POST /{vendor.value}/chat/completions -> forwarding to {url} with auth_header={cfg['auth_header']} api_key_len={len(api_key)}")

    fwd_headers = {
        cfg["auth_header"]: cfg["auth_prefix"] + api_key,
        "Content-Type": "application/json",
    }
    if "extra_headers" in cfg:
        fwd_headers.update(cfg["extra_headers"])

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, json=body, headers=fwd_headers)
            elapsed = (time.perf_counter() - t0) * 1000
            resp_text = resp.text
            logger.info(f"POST /{vendor.value}/chat/completions <- {resp.status_code} model={model_name} elapsed={elapsed:.0f}ms body={resp_text}")
            try:
                return resp.json()
            except Exception:
                return JSONResponse(
                    {"_raw": resp_text, "status_code": resp.status_code},
                    status_code=resp.status_code,
                )
    except Exception as e:
        elapsed = (time.perf_counter() - t0) * 1000
        logger.error(f"POST /{vendor.value}/chat/completions <- ERROR model={model_name} elapsed={elapsed:.0f}ms error={str(e)}")
        raise HTTPException(status_code=502, detail=f"转发请求失败: {str(e)}")


# ---------- 模型列表获取 ----------
@app.post("/{vendor}/models")
async def get_models(vendor: str, authorization: Optional[str] = Header(None)):
    t0 = time.perf_counter()
    companies = read_companlist()
    matched = next((c for c in companies if c["name"].lower() == vendor.lower()), None)
    if not matched:
        raise HTTPException(status_code=404, detail=f"未知厂家: {vendor}")

    domain = matched["domain"]
    if "openrouter" in domain:
        models_url = f"https://{domain}/api/v1/models"
    else:
        models_url = f"https://{domain}/v1/models"

    api_key = ""
    if authorization:
        api_key = authorization.removeprefix("Bearer ").strip()

    logger.info(f"POST /{vendor}/models -> {models_url}")

    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(models_url, headers=headers)
            elapsed = (time.perf_counter() - t0) * 1000
            logger.info(f"POST /{vendor}/models <- {resp.status_code} elapsed={elapsed:.0f}ms")
            try:
                return resp.json()
            except Exception:
                return JSONResponse(
                    {"_raw": resp.text, "status_code": resp.status_code},
                    status_code=resp.status_code,
                )
    except Exception as e:
        elapsed = (time.perf_counter() - t0) * 1000
        logger.error(f"POST /{vendor}/models <- ERROR elapsed={elapsed:.0f}ms error={str(e)}")
        raise HTTPException(status_code=502, detail=f"获取模型列表失败: {str(e)}")


# ---------- 前端页面 ----------
@app.get("/", response_class=HTMLResponse)
async def index():
    html_path = BASE_DIR / "templates" / "index.html"
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    import uvicorn
    import asyncio

    config = uvicorn.Config(app, host="0.0.0.0", port=9010)
    server = uvicorn.Server(config)
    asyncio.run(server.serve())
