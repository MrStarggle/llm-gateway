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
from propmt import (core_propmt_one, core_propmt_two, role_core_propmt, core_list, core_propmt_deepseek,
                    user_top_propmt, user_default_propmt, user_core_propmt)

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
        obj = obj.replace("<core_list>", core_list())
        obj = obj.replace("<core_propmt>", core_propmt_one())
        obj = obj.replace("</core_propmt>", core_propmt_two())
        obj = obj.replace("<user_top_propmt>", user_top_propmt())
        obj = obj.replace("<user_default_propmt>", user_default_propmt())
        obj = obj.replace("<user_core_propmt>", user_core_propmt())
        obj = obj.replace("<core_propmt_deepseek>", core_propmt_deepseek())#todo 如果是deepseek系列模型
        #obj = obj.replace("<core_propmt_deepseek>", "")#todo 如果不是deepseek系列模型；暂时不动这个
        obj = obj.replace("<role_core_propmt>", role_core_propmt())
        obj = obj.replace("</role_core_propmt>", "")
        return obj
    if isinstance(obj, dict):
        return {k: _replace_core_prompts(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_replace_core_prompts(item) for item in obj]
    return obj


# ── 思考模式参数注入 ──
def _apply_thinking_params(body: dict, model_name: str, com_url: str, enabled: bool) -> None:
    """按选中模型/运营商的参数规范，注入或移除请求体中的思考参数.

    与客户端 CallModelStreamService 的厂商分支保持一致的参数格式：
    - OpenRouter 网关: 用官方 ``reasoning.enabled`` 布尔值控制（``{"enabled": true|false}``），
      同时清理旧格式 ``extra_body.thinking`` 避免与新参数冲突
    - DeepSeek: ``thinking = {"type": "enabled"|"disabled"}``
    - Claude: 开启用 ``thinking = {"type": "enabled", "budget_tokens": N}``；
      关闭即移除字段（无 ``type=disabled`` 语义）
    - Qwen: ``enable_thinking`` + ``chat_template_kwargs.enable_thinking``
    - 其余模型族（GPT/o系列、Grok、MiMo 等）无可控思考参数 → 不处理，保持原样
    """
    name = (model_name or "").lower()
    url = (com_url or "").lower()

    if "openrouter" in url:
        if "deepseek" not in name:
            return
        body["reasoning"] = {"enabled": enabled}
        # 清理旧格式 extra_body.thinking，避免与官方 reasoning 参数冲突
        extra_body = body.get("extra_body")
        if isinstance(extra_body, dict):
            extra_body.pop("thinking", None)
            if not extra_body:
                body.pop("extra_body", None)
        return

    if "deepseek" in name:
        body["thinking"] = {"type": "enabled" if enabled else "disabled"}
    elif "claude" in name:
        if enabled:
            body["thinking"] = {"type": "enabled", "budget_tokens": 10000}
        else:
            body.pop("thinking", None)
    elif "qwen" in name:
        body["enable_thinking"] = enabled
        body["chat_template_kwargs"] = {"enable_thinking": enabled}


# ── 提供商路由参数注入 ──
def _apply_provider_params(body: dict, selected) -> None:
    """将 model_manage.html 维护的提供商参数（extra_config.provider）注入 OpenRouter 请求.

    仅缓存一个事实：OpenRouter 将路由参数放在请求体**顶层** ``provider`` 键
    （参考 temp/temp.txt），与 deepseek 的 ``extra_body.thinking`` 不是一回事。
    仅在运营商为 OpenRouter 且配置了 provider 时注入；
    客户端已显式传 ``body["provider"]`` 时保留客户端值，避免覆盖业务侧显式指定的路由。
    """
    url = (selected.com_url or "").lower()
    com_name = (selected.com_name or "").lower()
    if "openrouter" not in url and "openrouter" not in com_name:
        return
    if not selected.extra_config:
        return
    try:
        extra = json.loads(selected.extra_config)
    except (json.JSONDecodeError, TypeError):
        extra = None
    provider = (extra or {}).get("provider")
    if not isinstance(provider, dict) or not provider:
        return
    if "provider" in body:
        logger.info(
            "OpenRouter provider 参数：客户端已显式传入，跳过注入 body.provider=%s",
            json.dumps(body["provider"], ensure_ascii=False),
        )
        return
    body["provider"] = provider
    logger.info(
        "注入 OpenRouter provider 参数: %s",
        json.dumps(provider, ensure_ascii=False),
    )


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
    x_starggle_thinking: Optional[str] = Header(None, alias="X-Starggle-Thinking"),
    x_starggle_user_id: Optional[str] = Header(None, alias="X-Starggle-User-Id"),
):
    """转发聊天补全请求到配置的 LLM 模型（从数据库 model_manage_info 表选取）.

    Headers:
        Authorization: 可选的 Bearer token（主 LLM 模式下可覆盖 DB 中的 api_key）.
        X-Starggle-Purpose: "main"（默认，使用 is_base="0" 的模型）或
                            "async"（使用 is_base="1" 的基础模型）.
        X-Starggle-Thinking: 主 LLM 思考模式开关（"1"/"true" 开启，"0"/"false" 关闭）.
                             服务端按选中模型/运营商的参数规范注入思考参数；
                             异步模式固定关闭思考，不受此头影响.

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

    logger.info(
        "POST /call-manage/chat/completions -> 选中模型详情: ai_model_id=%s ai_model_name=%r com_name=%s com_url=%s is_base=%s",
        selected.ai_model_id, selected.ai_model_name, selected.com_name,
        selected.com_url, selected.is_base,
    )

    # ── 校验并构造转发 URL ──
    raw_url = selected.com_url.rstrip("/")
    # 如果 URL 不以 /chat/completions 结尾则自动追加
    # 兼容 DB 里存 https://openrouter.ai 或 https://openrouter.ai/api/v1 的情况
    if raw_url.endswith("/chat/completions"):
        forward_url = raw_url
    else:
        forward_url = f"{raw_url}/chat/completions"
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

    # 异步模式：关闭思考模式（兼容 deepseek 等推理模型）
    if is_async:
        _apply_thinking_params(body, selected.ai_model_name, selected.com_url, False)

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

    client_model = body.get("model", "")
    logger.info(
        "POST /call-manage/chat/completions -> 客户端传入 model=%r, selected.ai_model_name=%r",
        client_model, selected.ai_model_name,
    )
    model_name = client_model.strip()
    # 客户端可不传 model_name（空串），由服务端根据 model_manage_info 选取
    if not model_name:
        model_name = selected.ai_model_name
        body["model"] = model_name
        logger.info(
            "POST /call-manage/chat/completions -> 客户端未传 model，使用数据库配置: %r",
            model_name,
        )
    else:
        model_name = _validate_model_name(model_name)
        logger.info(
            "POST /call-manage/chat/completions -> 使用客户端传入 model: %r",
            model_name,
        )

    # 主 LLM 思考模式注入：由 X-Starggle-Thinking 头控制，按选中模型/运营商的参数规范构造。
    # 异步模式（is_async）固定关闭思考，不受此头影响。
    if not is_async and x_starggle_thinking is not None:
        thinking_enabled = x_starggle_thinking.strip().lower() in ("1", "true", "yes", "on", "enabled")
        _apply_thinking_params(body, model_name, selected.com_url, thinking_enabled)
        logger.info(
            "POST /call-manage/chat/completions -> X-Starggle-Thinking=%r enabled=%s model=%s",
            x_starggle_thinking, thinking_enabled, model_name,
        )

    # 提供商路由参数注入（OpenRouter）：把 model_manage_info.extra_config.provider 塞进请求体顶层 provider
    _apply_provider_params(body, selected)

    is_stream = body.get("stream", False)

    logger.info(
        "POST /call-manage/chat/completions -> model=%s stream=%s purpose=%s "
        "selected=%s(%s) url=%s body_model=%r",
        model_name, is_stream, llm_purpose, selected.ai_model_name, selected.com_name,
        forward_url, body.get("model"),
    )

    fwd_headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    # 打印最终发往上游 LLM 的请求报文
    logger.info(
        "POST /call-manage/chat/completions -> 发给上游的请求报文:\n%s",
        json.dumps(body, ensure_ascii=False, indent=2),
    )

    # ── 流式转发 ──
    if is_stream:
        client: Optional[httpx.AsyncClient] = None
        resp: Optional[httpx.Response] = None
        stream_timeout = httpx.Timeout(300.0, read=60.0)

        async def event_generator() -> AsyncGenerator[bytes, None]:
            nonlocal client, resp
            total_bytes = 0
            accumulated_chunks: list[bytes] = []
            accumulated_content: list[str] = []  # 收集 delta.content
            accumulated_usage: dict[str, int] = {}  # 收集 usage（prompt/completion/total_tokens）
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
                    # 解析 SSE chunk 提取 delta.content 和 usage（部分供应商在最后一个 chunk 中附带 usage）
                    text = chunk.decode("utf-8", errors="replace")
                    for line in text.split("\n"):
                        if line.startswith("data: ") and line[6:] != "[DONE]":
                            try:
                                data = json.loads(line[6:])
                                # 提取 usage（若有）：必须放在 choices 处理之前——
                                # DeepSeek 等供应商的末帧 usage 带空 choices []，若先取 choices[0] 会 IndexError，
                                # 导致 usage 提取被 except 吞掉，流式 token 记录丢失
                                usage = data.get("usage")
                                if usage and isinstance(usage, dict):
                                    accumulated_usage["prompt_tokens"] = usage.get("prompt_tokens", 0)
                                    accumulated_usage["completion_tokens"] = usage.get("completion_tokens", 0)
                                    accumulated_usage["total_tokens"] = usage.get("total_tokens", 0)
                                    accumulated_usage["prompt_cache_hit_tokens"] = usage.get("prompt_cache_hit_tokens", 0)
                                    accumulated_usage["prompt_cache_miss_tokens"] = usage.get("prompt_cache_miss_tokens", 0)
                                # 正文 delta：仅当 choices 非空时提取
                                choices = data.get("choices")
                                if choices:
                                    delta = choices[0].get("delta", {})
                                    content = delta.get("content", "")
                                    if content:
                                        accumulated_content.append(content)
                            except (json.JSONDecodeError, KeyError, IndexError):
                                pass
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
                content_text = "".join(accumulated_content)
                usage_info = ""
                if accumulated_usage:
                    usage_info = (
                        f" usage[prompt={accumulated_usage.get('prompt_tokens', 0)} "
                        f"completion={accumulated_usage.get('completion_tokens', 0)} "
                        f"total={accumulated_usage.get('total_tokens', 0)}]"
                    )
                logger.info(
                    "POST /call-manage/chat/completions <- STREAM DONE model=%s "
                    "elapsed=%.0fms total_bytes=%d content_chars=%d%s\n完整返回内容:\n%s",
                    model_name, elapsed, total_bytes, len(content_text), usage_info, content_text,
                )

                # 记录 token 用量（非关键路径，失败不影响响应）
                if x_starggle_user_id and accumulated_usage:
                    try:
                        await call_manage_service.record_token_usage(
                            db, x_starggle_user_id, model_name, llm_purpose,
                            is_stream=True, usage=accumulated_usage,
                        )
                    except Exception as e:
                        logger.warning("记录流式 token 用量失败: user_id=%s error=%s", x_starggle_user_id, e)

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
                "POST /call-manage/chat/completions <- %d model=%s elapsed=%.0fms len=%d\n完整返回报文:\n%s",
                resp.status_code, model_name, elapsed, len(resp_text), resp_text,
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
                data = resp.json()
            except Exception:
                return JSONResponse(
                    {"_raw": resp_text, "status_code": resp.status_code},
                    status_code=resp.status_code,
                )

            # 记录 token 用量（非关键路径，失败不影响响应）
            try:
                usage = (data or {}).get("usage") or {}
                await call_manage_service.record_token_usage(
                    db, x_starggle_user_id, model_name, llm_purpose,
                    is_stream=False, usage=usage,
                )
            except Exception as e:
                logger.warning("记录非流式 token 用量失败: user_id=%s error=%s", x_starggle_user_id, e)

            return data
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
