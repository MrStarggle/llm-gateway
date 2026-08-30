"""LLM 调用管理 控制器

提供基于数据库模型配置的 LLM 转发端点：
- POST /chat/completions — 转发聊天补全请求（支持流式/非流式）
- POST /models — 从上游 API 获取可用模型列表
"""
import json
import logging
import os
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
from app.config.membership import get_tier
from app.services import call_manage_service, async_manage_service, model_manage_service
from app.utils.response import ResponseFactory
from propmt import (core_propmt_one, core_propmt_two, role_core_propmt, core_list, core_propmt_deepseek,
                    user_top_propmt, user_default_propmt, user_core_propmt, super_core_propmt)

logger = logging.getLogger(__name__)

router = APIRouter()

# ── 模型名称校验 ──
_MODEL_NAME_RE = re.compile(r"^[a-zA-Z0-9_\-./@:]+$")

# ── 异步LLM总控 purpose 识别（async1..async13，与 async_manage_info.purpose 对应）──
_ASYNC_PURPOSE_RE = re.compile(r"^async([1-9]|1[0-3])$")

# ── o 系列模型（上游不支持 response_format / 非默认 temperature）──
_O_SERIES_RE = re.compile(r"o[13](-|mini|pro|\b).*", re.IGNORECASE)

# ── Claude 思考模式默认预算（_apply_thinking_params 注入与预算收敛共用）──
_CLAUDE_THINKING_BUDGET = 10000

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
        obj = obj.replace("<core_list>", core_list())#指令目录
        obj = obj.replace("<core_propmt>", core_propmt_one())#核心指令1
        obj = obj.replace("</core_propmt>", core_propmt_two())#核心指令2
        obj = obj.replace("<user_top_propmt>", user_top_propmt())#会话层顶部指令
        obj = obj.replace("<user_default_propmt>", user_default_propmt())#旁白侧会话指令
        obj = obj.replace("<user_core_propmt>", user_core_propmt())#通用侧会话指令
        obj = obj.replace("<super_core_propmt>", super_core_propmt())#超凡侧会话指令
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
    - OpenRouter 网关: 用官方 ``reasoning.enabled`` 布尔值统一控制（``{"enabled": true|false}``），
      开启时额外注入 ``reasoning.effort = "low"``；
      所有经 OpenRouter 的推理模型共用这一格式，不按模型名逐个特判；
      非推理模型传该参数会被网关忽略，同时清理旧格式 ``extra_body.thinking`` 避免冲突
    - DeepSeek 直连 / MiMo 官方 API（api.xiaomimimo.com）: ``thinking = {"type": "enabled"|"disabled"}``；
      其中 DeepSeek 开启时额外注入 ``reasoning_effort = "low"``（参考 doc/temp.txt）
    - Claude: 开启用 ``thinking = {"type": "enabled", "budget_tokens": N}``；
      关闭即移除字段（无 ``type=disabled`` 语义）
    - Qwen: ``enable_thinking`` + ``chat_template_kwargs.enable_thinking``
    - 其余模型族（GPT/o系列、Grok 等）无可控思考参数 → 不处理，保持原样
    """
    name = (model_name or "").lower()
    url = (com_url or "").lower()

    if "openrouter" in url:
        # OpenRouter 是统一网关：所有经它的推理模型都用官方 reasoning.enabled 布尔值控制，
        # 不按模型名逐个特判；非推理模型传该参数会被网关忽略，无副作用。
        body["reasoning"] = {"enabled": enabled}
        # 思考模式开启时控制思考深度（OpenRouter 官方 reasoning.effort 格式）
        if enabled:
            body["reasoning"]["effort"] = "low"
        # 清理旧格式 extra_body.thinking，避免与官方 reasoning 参数冲突
        extra_body = body.get("extra_body")
        if isinstance(extra_body, dict):
            extra_body.pop("thinking", None)
            if not extra_body:
                body.pop("extra_body", None)
        return

    # DeepSeek 原生接口与 MiMo 官方 API 格式一致，均用 thinking.type 控制
    if "deepseek" in name or "mimo" in name or "xiaomimimo" in url:
        body["thinking"] = {"type": "enabled" if enabled else "disabled"}
        # DeepSeek 思考模式额外支持 reasoning_effort 控制思考深度（参考 doc/temp.txt）
        if "deepseek" in name:
            if enabled:
                body["reasoning_effort"] = "low"
            else:
                body.pop("reasoning_effort", None)
    elif "claude" in name:
        if enabled:
            body["thinking"] = {"type": "enabled", "budget_tokens": _CLAUDE_THINKING_BUDGET}
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
        X-Starggle-Purpose: "main"（默认，使用 is_base="0" 的模型）、
                            "async"（使用 is_base="1" 的基础模型）或
                            "async1".."async13"（异步LLM总控分路，命中 async_manage_info
                            且启用且已绑定模型时按配置路由并接管 model/思考/temperature/max_tokens，
                            否则回落 "async" 轮询逻辑）.
        X-Starggle-Thinking: 主 LLM 思考模式开关（"1"/"true" 开启，"0"/"false" 关闭）.
                             服务端按选中模型/运营商的参数规范注入思考参数；
                             异步模式不受此头影响（思考模式由总控 is_think 决定：'1'强制开/'0'强制关/NULL跟随客户端不注入，未命中总控强制关闭）.

    请求体: 标准 OpenAI chat completions 格式.
    """
    t0 = time.perf_counter()
    llm_purpose = x_starggle_purpose or "main"
    # 任何 async* 都按异步计（含 async1..13 与未知 async99 等），
    # 防止未知 purpose 串到主模型路由使用客户端 Authorization key
    is_async = llm_purpose == "async" or llm_purpose.startswith("async")

    # ── 异步LLM总控：async1..13 命中总控表且启用且已绑定模型时走配置路由，否则回落轮询 ──
    purpose_cfg = None
    if _ASYNC_PURPOSE_RE.match(llm_purpose):
        purpose_cfg = await async_manage_service.get_config_by_purpose(db, llm_purpose)
    use_config = bool(purpose_cfg and purpose_cfg.is_using == "1" and purpose_cfg.ai_model_id)

    # ── 会员日限额校验（携带 X-Starggle-User-Id 的用户才校验） ──
    # 匿名调用（无用户ID）不校验，保持转发原样。
    # 开关：STARGGLE_ENFORCE_QUOTA=0 关闭（本地调试/压测用）。
    enforce_quota = os.getenv("STARGGLE_ENFORCE_QUOTA", "1").strip().lower() in ("1", "true", "yes", "on")
    if enforce_quota and x_starggle_user_id:
        level = await call_manage_service.get_effective_membership(db, x_starggle_user_id)
        daily_limit = get_tier(level).get("dailyLimit", 0)
        if daily_limit > 0:
            used = await call_manage_service.get_today_call_count(db, x_starggle_user_id)
            if used >= daily_limit:
                logger.info(
                    "POST /call-manage/chat/completions -> QUOTA user=%s level=%s used=%d limit=%d",
                    x_starggle_user_id, level, used, daily_limit,
                )
                raise HTTPException(
                    status_code=402,
                    detail={
                        "code": "QUOTA_EXCEEDED",
                        "message": "今日调用次数已达上限，请升级会员",
                        "level": level,
                        "used": used,
                        "dailyLimit": daily_limit,
                    },
                )

    # ── 从数据库获取可用模型 ──
    # 总控优先：purpose 命中且启用且已绑定模型时直接点查绑定模型（不查 is_base、不走轮询，
    # 允许绑定主模型池的模型——如导演A/B对齐主LLM）；绑定失效则回落 is_base=1 轮询
    selected = None
    if use_config:
        bound = await model_manage_service.get_model_by_id(db, purpose_cfg.ai_model_id)
        if bound is None or bound.is_using != "1":
            logger.warning(
                "POST /call-manage/chat/completions -> purpose=%s 绑定模型 %s 不存在或停用，回落 is_base=1 轮询",
                llm_purpose, purpose_cfg.ai_model_id,
            )
            use_config = False
        else:
            selected = bound
            logger.info(
                "POST /call-manage/chat/completions -> purpose=%s 命中异步LLM总控: model=%r com=%s is_think=%s",
                llm_purpose, selected.ai_model_name, selected.com_name, purpose_cfg.is_think,
            )

    if selected is None:
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

    # （思考模式注入统一移至下方 model 名解析之后：异步按总控 is_think，主模式按 X-Starggle-Thinking 头）

    # ── response_format 注入 ──
    # 客户端通过 X-Starggle-Response-Format header 声明需要 JSON 输出，
    # 服务端根据实际模型决定是否/如何注入 response_format。
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

    # ── 思考模式开关判定 ──
    # 异步模式：总控配置 is_think 决定 —— "1"强制开 / "0"强制关 / None跟随客户端（think_enabled 保持 None → 不注入，请求体原样透传）；
    #           未命中总控的裸 async/回落一律强制关闭（兼容推理模型）
    # 主模式：由 X-Starggle-Thinking 头控制；缺头不注入，保持请求体原样
    think_enabled: Optional[bool] = None
    if is_async:
        think_enabled = {"1": True, "0": False}.get(purpose_cfg.is_think) if use_config else False
    elif x_starggle_thinking is not None:
        think_enabled = x_starggle_thinking.strip().lower() in ("1", "true", "yes", "on", "enabled")
        logger.info(
            "POST /call-manage/chat/completions -> X-Starggle-Thinking=%r enabled=%s model=%s",
            x_starggle_thinking, think_enabled, model_name,
        )

    # ── 异步LLM总控参数覆盖：模型/temperature/max_tokens 服务端接管 ──
    # 客户端 body 里的值仅作未配置回落时的默认。
    # 覆盖豁免：o 系列不支持非默认 temperature；Claude 思考模式要求 temperature 固定为 1。
    # （Claude 思考与 max_tokens 的预算冲突在下方思考注入后统一收敛，此处无需跳过覆盖）
    if use_config:
        body["model"] = selected.ai_model_name
        model_name = selected.ai_model_name
        model_name_lower = model_name.lower()
        is_o_series = bool(_O_SERIES_RE.match(model_name_lower))
        is_claude = "claude" in model_name_lower
        # 思考是否（将）开启：强制开=True；跟随客户端（think_enabled=None）时看请求体自带思考标记。
        # Claude 思考模式要求 temperature 固定为 1（Anthropic 硬约束），开启时跳过 temperature 覆盖避免上游 400。
        body_thinking = body.get("thinking")
        client_think_on = (
            (isinstance(body_thinking, dict) and body_thinking.get("type") == "enabled")
            or body.get("reasoning_effort") is not None
        )
        think_on = think_enabled is True or (think_enabled is None and client_think_on)
        if purpose_cfg.temperature is not None and not is_o_series and not (is_claude and think_on):
            body["temperature"] = purpose_cfg.temperature
        if purpose_cfg.max_tokens is not None:
            body["max_tokens"] = purpose_cfg.max_tokens
        logger.info(
            "POST /call-manage/chat/completions -> purpose=%s 总控覆盖: model=%r temperature=%r max_tokens=%r",
            llm_purpose, body.get("model"), body.get("temperature"), body.get("max_tokens"),
        )

    # ── 思考参数注入：按选中模型/运营商的参数规范构造 ──
    if think_enabled is not None:
        _apply_thinking_params(body, model_name, selected.com_url, think_enabled)
        # Claude 思考模式：budget_tokens 必须小于 max_tokens（Anthropic 硬约束，OpenRouter 透传同约束）。
        # 预算不足时把 budget 收敛到实际 max_tokens 内（最低 1024）；连最低预算都放不下则关闭思考，
        # 避免整路请求上游 400。仅直连 Claude 的 thinking 字段可收敛；OpenRouter reasoning 无 budget 键不动。
        if think_enabled and "claude" in model_name.lower():
            thinking = body.get("thinking")
            if isinstance(thinking, dict) and thinking.get("type") == "enabled":
                max_tokens = body.get("max_tokens")
                if isinstance(max_tokens, int) and max_tokens <= _CLAUDE_THINKING_BUDGET:
                    budget = max_tokens - 1024
                    if budget >= 1024:
                        thinking["budget_tokens"] = budget
                        logger.info(
                            "POST /call-manage/chat/completions -> Claude 思考 budget 收敛为 %d（max_tokens=%s）",
                            budget, max_tokens,
                        )
                    else:
                        thinking["type"] = "disabled"
                        logger.warning(
                            "POST /call-manage/chat/completions -> max_tokens=%s 不足以容纳 Claude 思考最低预算(1024)，已关闭思考",
                            max_tokens,
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
            accumulated_reasoning: list[str] = []  # 收集思维链 delta.reasoning_content / delta.reasoning
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
                                    # 思维链字段：DeepSeek 用 reasoning_content，OpenRouter 用 reasoning
                                    reasoning = delta.get("reasoning_content") or delta.get("reasoning") or ""
                                    if reasoning and isinstance(reasoning, str):
                                        accumulated_reasoning.append(reasoning)
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
                reasoning_text = "".join(accumulated_reasoning)
                usage_info = ""
                if accumulated_usage:
                    usage_info = (
                        f" usage[prompt={accumulated_usage.get('prompt_tokens', 0)} "
                        f"completion={accumulated_usage.get('completion_tokens', 0)} "
                        f"total={accumulated_usage.get('total_tokens', 0)}]"
                    )
                logger.info(
                    "POST /call-manage/chat/completions <- STREAM DONE model=%s "
                    "elapsed=%.0fms total_bytes=%d content_chars=%d reasoning_chars=%d%s\n完整返回内容:\n%s",
                    model_name, elapsed, total_bytes, len(content_text), len(reasoning_text), usage_info, content_text,
                )
                # 思维链内容单独打印（思考模式才产生，平时为空避免日志噪音）
                if reasoning_text:
                    logger.info(
                        "POST /call-manage/chat/completions <- STREAM 思维链 model=%s:\n%s",
                        model_name, reasoning_text,
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
