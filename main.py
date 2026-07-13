import json
import logging
import os
import re
import time
from enum import Enum
from typing import AsyncGenerator, Optional
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import httpx

from propmt import core_propmt_one, core_propmt_two, role_core_propmt

logger = logging.getLogger("starggle")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S"))
    logger.addHandler(handler)
logger.propagate = False

DEBUG = os.environ.get("STARGGLE_DEBUG", "").lower() in ("1", "true", "yes")

app = FastAPI(title="LLM API 转发服务 v2")


@app.on_event("startup")
async def _startup_log():
    if DEBUG:
        logger.info("DEBUG 模式已开启 — 请求体将完整打印到日志")

BASE_DIR = Path(__file__).resolve().parent
COMPANLIST_FILE = BASE_DIR / "companlist.txt"

class Vendor(str, Enum):
    openrouter = "openrouter"
    claude = "claude"
    gemini = "gemini"
    grok = "grok"
    gpt = "gpt"
    deepseek = "deepseek"
    mimo = "mimo"
    minimax = "minimax"

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
    Vendor.deepseek: {
        "url": "https://api.deepseek.com/v1/chat/completions",
        "auth_header": "Authorization",
        "auth_prefix": "Bearer ",
    },
    Vendor.mimo: {
        "url": "https://api.xiaomimimo.com/v1/chat/completions",
        "auth_header": "Authorization",
        "auth_prefix": "Bearer ",
    },
    Vendor.minimax: {
        "url": "https://api.minimaxi.com/v1/chat/completions",
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


# ---------- 模型名称校验 ----------
_MODEL_NAME_RE = re.compile(r"^[a-zA-Z0-9_\-./@:]+$")


def _validate_model_name(name: str) -> str:
    """校验 model 名称，防止路径注入 / SSRF.

    允许 ``/``（如 ``deepseek/deepseek-v4-flash``），
    拒绝 ``..``（目录穿越）、``?``、``#`` 及空白/换行符。
    """
    if not name or not _MODEL_NAME_RE.match(name):
        raise HTTPException(status_code=400, detail="非法 model 名称")
    if ".." in name:
        raise HTTPException(status_code=400, detail="非法 model 名称")
    return name


# ---------- systemPropmt 占位符替换 ----------
def _replace_core_prompts(obj):
    """递归遍历请求体，替换 system prompt 中的 <core_propmt> / </core_propmt> 占位符."""
    if isinstance(obj, str):
        obj = obj.replace("<core_propmt>", core_propmt_one())
        obj = obj.replace("</core_propmt>", core_propmt_two())
        obj = obj.replace("<role_core_propmt>", "")
        obj = obj.replace("</role_core_propmt>", role_core_propmt())
        return obj
    if isinstance(obj, dict):
        return {k: _replace_core_prompts(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_replace_core_prompts(item) for item in obj]
    return obj


# ---------- 模型调用转发 ----------
async def _close_safely(obj: Optional[object]) -> None:
    """安全关闭 httpx 客户端或响应，避免 finally 中异常覆盖原始错误."""
    if obj is not None and hasattr(obj, "aclose"):
        try:
            await obj.aclose()
        except Exception:
            pass


async def _stream_aiter_bytes(resp: httpx.Response) -> AsyncGenerator[bytes, None]:
    """将 httpx 流式响应逐块 yield 为 bytes（SSE 透传）."""
    async for chunk in resp.aiter_bytes():
        yield chunk


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

    if DEBUG:
        logger.info("DEBUG request body (原始):\n%s", json.dumps(body, ensure_ascii=False, indent=2))

    body = _replace_core_prompts(body)

    if DEBUG:
        logger.info("DEBUG request body (替换后):\n%s", json.dumps(body, ensure_ascii=False, indent=2))

    model_name = _validate_model_name(body.get("model", ""))
    url = cfg.get("url", "").format(model=model_name)
    is_stream = body.get("stream", False)

    logger.info(
        "POST /%s/chat/completions -> model=%s stream=%s",
        vendor.value, model_name, is_stream,
    )
    logger.info(
        "POST /%s/chat/completions -> forwarding to %s auth_header=%s api_key_len=%d",
        vendor.value, url, cfg["auth_header"], len(api_key),
    )

    fwd_headers = {
        cfg["auth_header"]: cfg["auth_prefix"] + api_key,
        "Content-Type": "application/json",
    }
    if "extra_headers" in cfg:
        fwd_headers.update(cfg["extra_headers"])

    # ---------- 流式转发 ----------
    if is_stream:
        client: Optional[httpx.AsyncClient] = None
        resp: Optional[httpx.Response] = None
        stream_timeout = httpx.Timeout(300.0, read=60.0)

        async def event_generator() -> AsyncGenerator[bytes, None]:
            nonlocal client, resp
            try:
                client = httpx.AsyncClient(timeout=stream_timeout)
                resp = await client.send(
                    client.build_request("POST", url, json=body, headers=fwd_headers),
                    stream=True,
                )
                logger.info(
                    "POST /%s/chat/completions <- %d model=%s stream",
                    vendor.value, resp.status_code, model_name,
                )
                if resp.status_code >= 400:
                    error_body = await resp.aread()
                    logger.error(
                        "POST /%s/chat/completions <- %d model=%s stream_error body=%s",
                        vendor.value, resp.status_code, model_name,
                        error_body.decode("utf-8", errors="replace"),
                    )
                    yield (
                        f"data: [ERROR] 上游返回 {resp.status_code}: "
                        f"{error_body.decode('utf-8', errors='replace')}\n\n"
                    ).encode("utf-8")
                    return
                async for chunk in _stream_aiter_bytes(resp):
                    yield chunk
            except Exception as e:
                elapsed = (time.perf_counter() - t0) * 1000
                logger.error(
                    "POST /%s/chat/completions <- STREAM ERROR model=%s elapsed=%.0fms error=%s",
                    vendor.value, model_name, elapsed, str(e),
                )
                yield f"data: [ERROR] 流式转发失败: {str(e)}\n\n".encode("utf-8")
            finally:
                await _close_safely(resp)
                await _close_safely(client)
                elapsed = (time.perf_counter() - t0) * 1000
                logger.info(
                    "POST /%s/chat/completions <- STREAM DONE model=%s elapsed=%.0fms",
                    vendor.value, model_name, elapsed,
                )

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    # ---------- 非流式转发 ----------
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, json=body, headers=fwd_headers)
            elapsed = (time.perf_counter() - t0) * 1000
            resp_text = resp.text
            logger.info(
                "POST /%s/chat/completions <- %d model=%s elapsed=%.0fms len=%d",
                vendor.value, resp.status_code, model_name, elapsed, len(resp_text),
            )
            logger.debug(
                "POST /%s/chat/completions <- body=%s",
                vendor.value, resp_text[:500],
            )
            try:
                return resp.json()
            except Exception:
                return JSONResponse(
                    {"_raw": resp_text, "status_code": resp.status_code},
                    status_code=resp.status_code,
                )
    except Exception as e:
        elapsed = (time.perf_counter() - t0) * 1000
        logger.error(
            "POST /%s/chat/completions <- ERROR model=%s elapsed=%.0fms error=%s",
            vendor.value, model_name, elapsed, str(e),
        )
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
            if resp.status_code >= 400:
                logger.warning(f"POST /{vendor}/models upstream error {resp.status_code}: {resp.text[:500]}")
                raise HTTPException(
                    status_code=502,
                    detail=f"上游获取模型列表失败 (HTTP {resp.status_code})",
                )
            try:
                return resp.json()
            except Exception:
                logger.warning(f"POST /{vendor}/models upstream non-JSON response")
                return JSONResponse(
                    {"object": "list", "data": []},
                    status_code=200,
                )
    except HTTPException:
        raise  # 直接透传，避免异常消息被外层重复包装
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

    logger.debug("DEBUG 模式已开启 — 请求体将完整打印到日志")

    config = uvicorn.Config(app, host="0.0.0.0", port=9010)
    server = uvicorn.Server(config)
    asyncio.run(server.serve())
