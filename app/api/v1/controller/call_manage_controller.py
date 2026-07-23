"""LLM 调用管理 控制器

提供基于数据库模型配置的 LLM 转发端点：
- POST /chat/completions — 转发聊天补全请求（支持流式/非流式）
- POST /models — 从上游 API 获取可用模型列表
"""
import json
import logging
import re
import time
from typing import Any, AsyncGenerator, Optional
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.database import get_db
from app.services import call_manage_service
from app.utils.response import ResponseFactory
from propmt import core_propmt_one, core_propmt_two, role_core_propmt

logger = logging.getLogger(__name__)

router = APIRouter()

# ── 模型名称校验 ──
_MODEL_NAME_RE = re.compile(r"^[a-zA-Z0-9_\-./@:]+$")

# ── SSRF 防护：禁止的目标地址 ──
_BLOCKED_HOSTS = frozenset({
    "127.0.0.1", "localhost", "0.0.0.0",
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
    "169.254.0.0/16", "::1", "fc00::/7", "fe80::/10",
})

# ── DEBUG 开关（与 main.py 共享环境变量） ──
DEBUG = __import__("os").environ.get("STARGGLE_DEBUG", "").lower() in ("1", "true", "yes")


def _validate_model_name(name: str) -> str:
    """校验 model 名称，防止路径注入 / SSRF.

    允许 ``/``（如 ``deepseek/deepseek-v4-flash``），
    拒绝 ``..``（目录穿越）、``?``、``#`` 及空白/换行符.
    """
    if not name or not _MODEL_NAME_RE.match(name):
        raise HTTPException(status_code=400, detail="非法 model 名称")
    if ".." in name:
        raise HTTPException(status_code=400, detail="非法 model 名称")
    return name


def _validate_url(url: str) -> str:
    """校验转发目标 URL，防止 SSRF.

    要求 https 协议，拒绝私有/回环地址.
    """
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise HTTPException(status_code=400, detail="仅支持 HTTPS 转发目标")
    hostname = (parsed.hostname or "").lower()
    if not hostname:
        raise HTTPException(status_code=400, detail="无效的转发目标 URL")
    # 拒绝回环地址
    if hostname in ("127.0.0.1", "localhost", "0.0.0.0", "::1"):
        raise HTTPException(status_code=400, detail="不允许的转发目标")
    # 拒绝私有网络地址
    if hostname.startswith(("10.", "172.16.", "192.168.")):
        raise HTTPException(status_code=400, detail="不允许的转发目标")
    return url


# ── systemPropmt 占位符替换 ──
def _replace_core_prompts(obj: Any) -> Any:
    """递归遍历请求体，替换 system prompt 中的 <core_propmt> / </core_propmt> 占位符."""
    if isinstance(obj, str):
        obj = obj.replace("<core_propmt>", core_propmt_one())
        obj = obj.replace("</core_propmt>", core_propmt_two())
        obj = obj.replace("<role_core_propmt>", role_core_propmt())
        obj = obj.replace("</role_core_propmt>", "")
        return obj
    if isinstance(obj, dict):
        return {k: _replace_core_prompts(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_replace_core_prompts(item) for item in obj]
    return obj


# ── httpx 安全关闭 ──
async def _close_safely(obj: Optional[object]) -> None:
    """安全关闭 httpx 客户端或响应，避免 finally 中异常覆盖原始错误."""
    if obj is not None and hasattr(obj, "aclose"):
        try:
            await obj.aclose()
        except Exception as exc:
            logger.debug("关闭 httpx 资源时出现异常: %s", exc)


async def _stream_aiter_bytes(resp: httpx.Response) -> AsyncGenerator[bytes, None]:
    """将 httpx 流式响应逐块 yield 为 bytes（SSE 透传）."""
    async for chunk in resp.aiter_bytes():
        yield chunk


# ── 共享的模型拉取逻辑（call-manage 和 model-manage 共用） ──

async def _fetch_models_from_upstream(com_url: str, api_key: str) -> tuple[list[str], str]:
    """从上游 API 拉取可用模型列表.

    Args:
        com_url: 运营商 API 基础地址.
        api_key: API Key.

    Returns:
        (模型 ID 列表, 错误消息). 成功时错误消息为空字符串.
    """
    base_url = com_url.rstrip("/")
    models: list[str] = []
    candidates = [
        f"{base_url}/v1/models",
        f"{base_url}/models",
        f"{base_url}/api/v1/models",
    ]
    headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
    last_error = ""

    for url in candidates:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(url, headers=headers)
                if resp.status_code >= 400:
                    last_error = f"HTTP {resp.status_code}"
                    continue
                data = resp.json()
                raw_list = data.get("data", [])
                if isinstance(raw_list, list):
                    for item in raw_list:
                        if isinstance(item, dict) and "id" in item:
                            models.append(item["id"])
                        elif isinstance(item, str):
                            models.append(item)
                    break
                last_error = "响应格式不匹配"
        except httpx.TimeoutException:
            last_error = "请求超时"
            continue
        except Exception as e:
            last_error = str(e)
            continue

    return models, "" if models else last_error


# ── 共享的 Pydantic 模型 ──
class FetchModelsBody(BaseModel):
    com_url: str = Field(..., min_length=1, description="运营商 API 地址")
    api_key: str = Field(..., min_length=1, description="API Key")


# ── LLM 转发端点 ──

@router.post("/chat/completions")
async def chat_completions(
    request: Request,
    db: AsyncSession = Depends(get_db),
    authorization: Optional[str] = Header(None),
    x_starggle_purpose: Optional[str] = Header(None, alias="X-Starggle-Purpose"),
    x_starggle_response_format: Optional[str] = Header(None, alias="X-Starggle-Response-Format"),
):
    """转发聊天补全请求到配置的 LLM 模型（从数据库 model_manage_info 表选取）.

    Headers:
        Authorization: 可选的 Bearer token（主 LLM 模式下可覆盖 DB 中的 api_key）.
        X-Starggle-Purpose: "main"（默认，使用 is_base="0" 的模型）或
                            "async"（使用 is_base="1" 的基础模型）.

    请求体: 标准 OpenAI chat completions 格式.
    """
    t0 = time.perf_counter()
    llm_purpose = x_starggle_purpose or "main"
    is_async = llm_purpose == "async"

    # ── 从数据库获取可用模型 ──
    target_is_base = "1" if is_async else "0"
    counter_type = "async" if is_async else "primary"
    models = await call_manage_service.get_active_models(db, is_base=target_is_base)

    if not models:
        logger.error("没有可用的 %s 模型（is_using=1, is_base=%s）", llm_purpose, target_is_base)
        raise HTTPException(
            status_code=503,
            detail=f"没有可用的{'异步' if is_async else '主'} LLM 模型，请检查 model_manage_info 表配置",
        )

    selected = await call_manage_service.next_model(models, counter_type)

    # ── 校验并构造转发 URL ──
    raw_url = selected.com_url.rstrip("/")
    # 仅对无路径的基础 URL 追加 /chat/completions
    parsed = urlparse(raw_url)
    if not parsed.path or parsed.path == "/":
        forward_url = f"{raw_url}/chat/completions"
    else:
        forward_url = raw_url
    _validate_url(forward_url)

    # ── 确定 API Key ──
    # 主 LLM：优先使用客户端提供的 key；异步 LLM：强制使用 DB 配置的 key
    if is_async:
        api_key = selected.api_key
    else:
        client_key = ""
        if authorization:
            client_key = authorization.removeprefix("Bearer ").strip()
        api_key = client_key if client_key else selected.api_key
        if not api_key:
            raise HTTPException(status_code=401, detail="缺少 Authorization header 或 API Key")

    # ── 解析请求体 ──
    body = await request.json()
    body = _replace_core_prompts(body)

    # DEBUG：打印完整请求报文
    if DEBUG:
        logger.info(
            "POST /call-manage/chat/completions -> 请求报文:\n%s",
            json.dumps(body, ensure_ascii=False, indent=2),
        )

    # 异步模式：关闭思考模式（兼容 deepseek 等推理模型）
    if is_async:
        body["thinking"] = {"type": "disabled"}
        body.pop("reasoning", None)

    # ── response_format 注入 ──
    # 客户端通过 X-Starggle-Response-Format header 声明需要 JSON 输出，
    # 服务端根据实际模型决定是否/如何注入 response_format。
    _O_SERIES_RE = re.compile(r"o[13](-|mini|pro|\b).*", re.IGNORECASE)
    if x_starggle_response_format == "json_object":
        model_name_lower = selected.ai_model_name.lower()
        is_o_series = bool(_O_SERIES_RE.match(model_name_lower))
        if not is_o_series:
            body["response_format"] = {"type": "json_object"}
        else:
            logger.info(
                "POST /call-manage/chat/completions -> model=%s 不支持 response_format，跳过注入",
                selected.ai_model_name,
            )

    model_name = body.get("model", "").strip()
    # 客户端可不传 model_name（空串），由服务端根据 model_manage_info 选取
    if not model_name:
        model_name = selected.ai_model_name
        body["model"] = model_name
    else:
        model_name = _validate_model_name(model_name)
    is_stream = body.get("stream", False)

    logger.info(
        "POST /call-manage/chat/completions -> model=%s stream=%s purpose=%s "
        "selected=%s(%s) url=%s",
        model_name, is_stream, llm_purpose, selected.ai_model_name, selected.com_name, forward_url,
    )

    fwd_headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    # ── 流式转发 ──
    if is_stream:
        client: Optional[httpx.AsyncClient] = None
        resp: Optional[httpx.Response] = None
        stream_timeout = httpx.Timeout(300.0, read=60.0)

        async def event_generator() -> AsyncGenerator[bytes, None]:
            nonlocal client, resp
            total_bytes = 0
            accumulated_chunks: list[bytes] = []
            try:
                client = httpx.AsyncClient(timeout=stream_timeout)
                resp = await client.send(
                    client.build_request("POST", forward_url, json=body, headers=fwd_headers),
                    stream=True,
                )
                logger.info(
                    "POST /call-manage/chat/completions <- %d model=%s stream",
                    resp.status_code, model_name,
                )
                if resp.status_code >= 400:
                    error_body = await resp.aread()
                    logger.error(
                        "POST /call-manage/chat/completions <- %d model=%s stream_error body=%s",
                        resp.status_code, model_name,
                        error_body.decode("utf-8", errors="replace"),
                    )
                    yield (
                        f"data: [ERROR] 上游返回 {resp.status_code}: "
                        f"{error_body.decode('utf-8', errors='replace')}\n\n"
                    ).encode("utf-8")
                    return
                async for chunk in _stream_aiter_bytes(resp):
                    total_bytes += len(chunk)
                    accumulated_chunks.append(chunk)
                    yield chunk
            except Exception as e:
                elapsed = (time.perf_counter() - t0) * 1000
                logger.error(
                    "POST /call-manage/chat/completions <- STREAM ERROR model=%s elapsed=%.0fms error=%s",
                    model_name, elapsed, str(e),
                )
                yield f"data: [ERROR] 流式转发失败: {str(e)}\n\n".encode("utf-8")
            finally:
                await _close_safely(resp)
                await _close_safely(client)
                elapsed = (time.perf_counter() - t0) * 1000
                if DEBUG:
                    accumulated_text = b"".join(accumulated_chunks).decode("utf-8", errors="replace")
                    logger.info(
                        "POST /call-manage/chat/completions <- STREAM DONE model=%s "
                        "elapsed=%.0fms total_bytes=%d\n完整返回报文:\n%s",
                        model_name, elapsed, total_bytes, accumulated_text,
                    )
                else:
                    logger.info(
                        "POST /call-manage/chat/completions <- STREAM DONE model=%s "
                        "elapsed=%.0fms total_bytes=%d",
                        model_name, elapsed, total_bytes,
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

    # ── 非流式转发 ──
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(forward_url, json=body, headers=fwd_headers)
            elapsed = (time.perf_counter() - t0) * 1000
            resp_text = resp.text
            logger.info(
                "POST /call-manage/chat/completions <- %d model=%s elapsed=%.0fms len=%d",
                resp.status_code, model_name, elapsed, len(resp_text),
            )
            if DEBUG:
                logger.info(
                    "POST /call-manage/chat/completions <- 完整返回报文:\n%s",
                    resp_text,
                )

            if resp.status_code >= 400:
                logger.warning(
                    "POST /call-manage/chat/completions <- upstream error %d model=%s body=%s",
                    resp.status_code, model_name, resp_text[:500],
                )
                raise HTTPException(
                    status_code=502,
                    detail=f"上游返回错误 (HTTP {resp.status_code}): {resp_text[:500]}",
                )

            try:
                return resp.json()
            except Exception:
                return JSONResponse(
                    {"_raw": resp_text, "status_code": resp.status_code},
                    status_code=resp.status_code,
                )
    except HTTPException:
        raise
    except Exception as e:
        elapsed = (time.perf_counter() - t0) * 1000
        logger.error(
            "POST /call-manage/chat/completions <- ERROR model=%s elapsed=%.0fms error=%s",
            model_name, elapsed, str(e),
        )
        raise HTTPException(status_code=502, detail=f"转发请求失败: {str(e)}")


# ── 模型列表获取 ──

@router.post("/models")
async def fetch_models(body: FetchModelsBody):
    """从运营商 API 拉取可用模型列表.

    请求体: { com_url, api_key }
    """
    t0 = time.perf_counter()
    models, error = await _fetch_models_from_upstream(body.com_url, body.api_key)

    if not models and error:
        return ResponseFactory.bad_request(message=f"获取模型列表失败: {error}")

    elapsed = (time.perf_counter() - t0) * 1000
    logger.info("POST /call-manage/models -> %d models elapsed=%.0fms", len(models), elapsed)
    models = sorted(set(models))
    return ResponseFactory.ok(data={"models": models}, message="查询成功")
