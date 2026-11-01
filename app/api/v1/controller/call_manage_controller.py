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
from propmt import (core_propmt_one, core_propmt_two, core_list, core_propmt_deepseek,
                    user_top_propmt, user_default_propmt, user_core_propmt, super_core_propmt, user_active_propmt,
                    user_sec_propmt, ai_sec_propmt)

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

# ── Anthropic 原生 /v1/messages 协议（ofox 等兼容网关，样例见 test.txt）──
_ANTHROPIC_VERSION = "2023-06-01"       # 请求头 anthropic-version 固定值（协议要求）
_ANTHROPIC_DEFAULT_MAX_TOKENS = 8192    # 原生协议 max_tokens 必填：总控/客户端均未配置时的兜底

# 原生 SSE 事件族：命中即走 _ingest_anthropic_sse_data。分流必须先于通用 usage 提取——
# message_delta 的顶层 usage 只带 output_tokens，落进通用提取会把 prompt_tokens 覆写为 0，
# 冲掉 message_start 已记下的 input_tokens。未列出的（ping/content_block_start 等）
# 落回 OpenAI 通用路径亦为无害 no-op
_ANTHROPIC_SSE_EVENT_TYPES = frozenset({"message_start", "content_block_delta", "message_delta", "error"})

# ── 智谱 GLM 版本门槛（模型名形如 glm-<major>.<minor>[-变体]，如 glm-5.3-flash / z-ai/glm-4.6）──
# 官方文档（docs.bigmodel.cn「深度思考」）：
#   · reasoning_effort 仅 GLM-5.2 及以上支持，低版本传了报错（GLM-4.6 及以下无强度档）；
#   · GLM-5.3 / 5.3-FLASH / 5.3-FLASHX 起**不再支持 thinking.type=disabled**
#     （传了返回 HTTP 400，错误码 1210「该模型始终思考，不支持关闭思考；请使用 low、high 或 max」）。
_GLM_NAME_RE = re.compile(r"glm[-_ ]?(\d+)(?:\.(\d+))?", re.IGNORECASE)
_GLM_EFFORT_MIN_VER = (5, 2)
_GLM_FORCED_THINKING_MIN_VER = (5, 3)
_GLM_THINKING_EFFORT = "low"      # GLM-5.2+ 的思考强度档；厂商默认 max 最贵最慢

# ── MiniMax 强制思考门槛（模型名形如 minimax-m3.1 / MiniMax-M3.1）──
# M3.1 起与 GLM-5.3 族同款「强制思考、不可关闭」，且支持 reasoning_effort 强度档，
# 参数格式与智谱 GLM 完全一致（thinking.type + reasoning_effort），整体复用下方 GLM 判定链路。
# 注意：M 系版本号数字小（3.1 < 5.2），门槛不能拿 GLM 的常量来比，须按家族取（见 _thinking_gates）。
_MINIMAX_NAME_RE = re.compile(r"minimax[-_ ]?m?(\d+)(?:\.(\d+))?", re.IGNORECASE)
_MINIMAX_EFFORT_MIN_VER = (3, 1)
_MINIMAX_FORCED_THINKING_MIN_VER = (3, 1)


def _glm_version(model_name: str) -> Optional[tuple]:
    """从模型名解析 GLM/MiniMax 版本号 → (major, minor)；解析不出返回 None（按最低能力处理）。

    旧世代命名（chatglm-130b / glm-130b 之类）会解析出三位数版本号，越界即按「解析不出」
    处理——避免把 reasoning_effort 一类新参数发给不认识它的老模型。
    """
    text = model_name or ""
    m = _GLM_NAME_RE.search(text) or _MINIMAX_NAME_RE.search(text)
    if not m:
        return None
    major, minor = int(m.group(1)), int(m.group(2) or 0)
    if major > 9 or minor > 9:
        return None
    return major, minor


def _is_minimax(model_name: str) -> bool:
    """模型名是否属于 MiniMax 家族（与 GLM 共用思考判定链路，见 _glm_thinking_plan）。"""
    return "minimax" in (model_name or "").lower()


def _thinking_gates(model_name: str) -> tuple:
    """当前模型的（effort 支持门槛 / 强制思考门槛），按家族取常量。

    MiniMax 的 M3.1 版本数字上小于 GLM 的 5.2/5.3，但能力对齐——不能拿 GLM 的门槛去比。
    """
    if _is_minimax(model_name):
        return _MINIMAX_EFFORT_MIN_VER, _MINIMAX_FORCED_THINKING_MIN_VER
    return _GLM_EFFORT_MIN_VER, _GLM_FORCED_THINKING_MIN_VER


def _glm_forced_thinking(model_name: str) -> bool:
    """所选模型是否为「强制思考、不可关闭」型号（GLM-5.3 族 / MiniMax-M3.1+）。

    这类型号关不掉：官方对 disabled 返 400，聚合网关则静默忽略并让模型按默认 max 跑。
    与运营商地址无关（智谱直连与 OpenRouter 都一样关不掉），故只按模型名判定。
    """
    ver = _glm_version(model_name)
    if ver is None:
        return False
    forced_min = _thinking_gates(model_name)[1]
    return ver >= forced_min


def _glm_thinking_plan(model_name: str, enabled: bool) -> Optional[tuple]:
    """GLM/MiniMax 的思考决策 → (是否思考, 强度|None)；其他模型返回 None。

    两种出站格式共用同一套档位判断，各分支只负责把结果拼成自己的字段形态：
      · 智谱直连/聚合（非 OpenRouter url）：``thinking={type}`` + 顶层 ``reasoning_effort``
      · OpenRouter：嵌套 ``reasoning={enabled, effort}``
    与客户端 CallModelStreamService._glm_thinking_plan 同口径（两仓共用契约，改动须同步，客户端仓需同步加 MiniMax-M3.1 判定）。
    """
    text = (model_name or "").lower()
    if "glm" not in text and "minimax" not in text:
        return None                    # 非 GLM/MiniMax：不属于本规则的适用范围
    ver = _glm_version(model_name)
    effort_min, forced_min = _thinking_gates(model_name)
    effort = _GLM_THINKING_EFFORT if (ver is not None and ver >= effort_min) else None
    if ver is not None and ver >= forced_min:
        return True, effort            # 强制思考型号：关不掉，只能压强度
    return enabled, (effort if enabled else None)


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


def _is_anthropic_native_url(url: str) -> bool:
    """转发目标是否为 Anthropic 原生 ``/v1/messages`` 端点（ofox 等兼容网关）.

    原生协议（doc/test.txt）与 OpenAI ``/chat/completions`` 的差异，由调用方分别处理：
      · 认证头用 ``x-api-key``（非 Bearer），且必须带 ``anthropic-version``
      · ``max_tokens`` 必填，缺了上游直接 400
      · SSE 事件为 message_start / content_block_delta / message_delta 一族（见 _ingest_anthropic_sse_data）

    仅按 URL 路径判定：DB 须存完整端点 ``…/v1/messages`` 或基址 ``…/anthropic``
    （构造转发 URL 时补 ``/v1/messages``）；裸域名（如 https://api.anthropic.com）不会命中。
    """
    path = urlparse(url).path.rstrip("/").lower()
    return path.endswith("/messages")


def _apply_anthropic_native_body(body: dict) -> None:
    """Anthropic 原生协议的请求体适配（ofox /v1/messages 等原生端点）.

    OpenAI 格式允许 ``role: "system"`` 混在 messages 里（本平台客户端即按此发送），
    原生协议没有这个角色——system 必须提为顶层 ``system`` 字段，留在 messages 里
    上游直接 400。其余字段（model/max_tokens/stream/thinking/temperature）两协议
    同名同义，原样透传。
    """
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        return
    system_parts: list[str] = []
    kept: list[Any] = []
    for msg in messages:
        if isinstance(msg, dict) and msg.get("role") == "system":
            content = msg.get("content")
            if isinstance(content, str):
                system_parts.append(content)
            elif isinstance(content, list):
                # content blocks 形态：只拼其中的 text 块
                system_parts.append("".join(
                    blk.get("text", "") for blk in content if isinstance(blk, dict)
                ))
            continue
        kept.append(msg)
    if not system_parts:
        return
    body["messages"] = kept
    hoisted = "\n".join(p for p in system_parts if p)
    prev = body.get("system")
    if isinstance(prev, str) and prev:
        hoisted = f"{prev}\n{hoisted}"
    body["system"] = hoisted
    logger.info(
        "POST /call-manage/chat/completions -> Anthropic 原生适配: %d 条 system 消息提为顶层 system 字段",
        len(system_parts),
    )


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
        obj = obj.replace("<user_active_propmt>", user_active_propmt())#主动消息触发
        obj = obj.replace("<super_core_propmt>", super_core_propmt())#超凡侧会话指令
        obj = obj.replace("<user_sec_propmt>", user_sec_propmt())  # 用户会话层顶部第二条指令
        obj = obj.replace("<ai_sec_propmt>", ai_sec_propmt())  # AI会话层顶部第二条指令
        obj = obj.replace("<core_propmt_deepseek>", core_propmt_deepseek())#todo 如果是deepseek系列模型
        #obj = obj.replace("<core_propmt_deepseek>", "")#todo 如果不是deepseek系列模型；暂时不动这个
        #obj = obj.replace("<role_core_propmt>", role_core_propmt())#暂时注释，角色发言不需要了
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
      经 OpenRouter 的推理模型共用这一格式，不按模型名逐个特判（GLM/MiniMax 除外，见下）；
      非推理模型传该参数会被网关忽略，同时清理旧格式 ``extra_body.thinking`` 避免冲突
    - DeepSeek 直连 / MiMo 官方 API（api.xiaomimimo.com）: ``thinking = {"type": "enabled"|"disabled"}``；
      其中 DeepSeek 开启时额外注入 ``reasoning_effort = "low"``（参考 doc/temp.txt）
    - Claude: 开启用 ``thinking = {"type": "enabled", "budget_tokens": N}``；
      关闭即移除字段（无 ``type=disabled`` 语义）
    - Qwen: ``enable_thinking`` + ``chat_template_kwargs.enable_thinking``
    - GLM（智谱直连）: ``thinking = {"type": "enabled"|"disabled"}``（与 DeepSeek 同格式）；
      思考开启时默认注入 ``reasoning_effort = "low"``（智谱官方思考强度档位 low/high/max，
      模型默认 max 最费 token，客户端已显式传入则保留客户端档位），关闭时移除该参数。
      **但 GLM-5.3/flash/flashx 是强制思考型号**：模型层面不允许关闭，传 ``disabled`` 官方返 400、
      聚合网关则静默忽略（模型仍按默认 max 思考）。故这类型号恒发 ``enabled`` + 压到 low，
      把「关」降级为「开着但最低档」；``reasoning_effort`` 仅 GLM-5.2+ 支持，低版本不发
      **MiniMax-M3.1+ 同属强制思考型号**，参数格式与 GLM 一致，走同一分支
      （判定复用 _glm_thinking_plan / _glm_forced_thinking，仅版本门槛数值不同）
    - 其余模型族（GPT/o系列、Grok 等）无可控思考参数 → 不处理，保持原样
    """
    name = (model_name or "").lower()
    url = (com_url or "").lower()

    if "openrouter" in url:
        # OpenRouter 是统一网关：推理模型都用官方 reasoning.enabled 布尔值控制，
        # 不按模型名逐个特判；非推理模型传该参数会被网关忽略，无副作用。
        # **但 GLM/MiniMax 例外**：它有强制思考型号（关不掉，发 enabled=false 会被静默忽略并让模型
        # 按默认 max 跑）与独立强度档，故先过一遍 _glm_thinking_plan——否则同一个静默 max
        # 故障只是从智谱直连搬到了 OpenRouter 路由上（2026-10-02 两仓同修的教训）。
        prev_reasoning = body.get("reasoning") if isinstance(body.get("reasoning"), dict) else {}
        prev_effort = prev_reasoning.get("effort")
        glm_plan = _glm_thinking_plan(name, enabled)
        if glm_plan is None:
            body["reasoning"] = {"enabled": enabled}
            # 思考模式开启时控制思考深度（OpenRouter 官方 reasoning.effort 格式）
            if enabled:
                body["reasoning"]["effort"] = _GLM_THINKING_EFFORT
        else:
            think_on, effort = glm_plan
            if effort:
                # GLM 5.2+ 有强度档：**只发 effort 不带 enabled**——OpenRouter 官方推荐用
                # effort/max_tokens 控制思考，enabled 仅少数 provider 支持；2026-10-13 线上
                # enabled+low 仍被按默认 max 思考烧穿 max_tokens（docs/2.txt），优先怀疑
                # enabled 走了不支持路径。强制思考型号默认即思考，无 enabled 兜底需求。
                # 强制降级（客户端要关、型号关不掉）时不用客户端带来的档位——那多半是残留，
                # 顺着用会出现「客户端以为关了、实际按 high/max 烧」的最坏组合；其余保留其档位
                clamped = think_on and not enabled
                body["reasoning"] = {"effort": _GLM_THINKING_EFFORT if clamped else (prev_effort or effort)}
            else:
                # 无强度档的老 GLM（5.2-）：关得掉，enabled 布尔是唯一开关，保持
                body["reasoning"] = {"enabled": think_on}
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
            # Anthropic 硬约束：思考开启时 temperature 必须为 1，top_p/top_k 不可携带，
            # 违反即上游 400（ofox 等原生网关同约束）。客户端带来的值一律压掉。
            body["temperature"] = 1
            body.pop("top_p", None)
            body.pop("top_k", None)
        else:
            body.pop("thinking", None)
    elif "qwen" in name:
        body["enable_thinking"] = enabled
        body["chat_template_kwargs"] = {"enable_thinking": enabled}
    elif "glm" in name or "bigmodel" in url or "zhipu" in url or _is_minimax(name):
        # GLM（智谱）/ MiniMax：thinking.type 与 DeepSeek 同格式。但 GLM-5.3 / 5.3-flash / 5.3-flashx
        # 是**强制思考**型号（含 MiniMax-M3.1）——模型层面不允许关闭（官方：传 disabled 返回 400，错误码 1210
        # 「该模型始终思考，请使用 low、high 或 max」）。实测经聚合网关（ofox 等）时 disabled
        # 会被静默**忽略**：请求通（200），但模型按**默认 max** 强度一路思考——客户端以为自己
        # 关掉了，实际拿到最贵最慢那一档，且报文里没有任何强度参数可查。
        # 故对强制思考型号恒发 enabled，把「关」降级为「开着但压到最低档」，而不是发一个无效的 disabled。
        glm_ver = _glm_version(name)
        forced_thinking = _glm_forced_thinking(name)
        effort_min = _thinking_gates(name)[0]
        if enabled or forced_thinking:
            body["thinking"] = {"type": "enabled"}
            # 思考强度：官方独立参数（GLM/MiniMax） reasoning_effort（low/high/max，模型默认 max），
            # 与 thinking.type 开关分离。默认压到 low 省 token；客户端已显式传入则保留其档位。
            # 仅 GLM-5.2+ / MiniMax-3.1+ 认该参数（低版本传了报错），故按版本门禁。
            if glm_ver is not None and glm_ver >= effort_min:
                if forced_thinking and not enabled:
                    # 强制降级（客户端要关、型号关不掉）：不用客户端带来的档位，最低档处理
                    body["reasoning_effort"] = _GLM_THINKING_EFFORT
                else:
                    body.setdefault("reasoning_effort", _GLM_THINKING_EFFORT)
        else:
            body["thinking"] = {"type": "disabled"}
            body.pop("reasoning_effort", None)


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


# ── Gemini 安全阈值（_apply_gemini_safety 注入 extra_body.safety_settings）──
_GEMINI_SAFETY_SETTINGS = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
]


# ── Gemini 安全阈值注入 ──
def _apply_gemini_safety(body: dict, model_name: str) -> None:
    """Gemini 系模型关闭安全拦截：extra_body.safety_settings 四类全部 BLOCK_NONE.

    与客户端 CallModelStreamService 的 Gemini 分支保持一致（extra_body 字面键，
    经 OpenRouter 透传）。合并不覆盖：客户端已显式传 extra_body.safety_settings
    时保留客户端值；extra_body 已存在（如其他参数）时只补 safety_settings 键。
    """
    if "gemini" not in (model_name or "").lower():
        return
    extra_body = body.get("extra_body")
    if not isinstance(extra_body, dict):
        if extra_body is not None:
            logger.warning(
                "Gemini safety_settings：客户端 extra_body 非对象(%r)，丢弃后注入", extra_body,
            )
        extra_body = {}
        body["extra_body"] = extra_body
    if "safety_settings" in extra_body:
        logger.info(
            "Gemini safety_settings：客户端已显式传入，跳过注入 model=%s", model_name,
        )
        return
    # 深拷贝注入：常量是模块级共享对象，本文件惯例是原地改 body，
    # 引用共享会让未来任何原地修改跨请求串状态
    extra_body["safety_settings"] = [dict(s) for s in _GEMINI_SAFETY_SETTINGS]
    logger.info("注入 Gemini safety_settings(BLOCK_NONE): model=%s", model_name)


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


def _ingest_sse_chunk(
    buf: bytes,
    accumulated_content: list[str],
    accumulated_reasoning: list[str],
    accumulated_usage: dict[str, int],
    flush: bool = False,
) -> bytes:
    """消费 ``buf`` 里的**完整** SSE 行并累加，返回残余的半行（留给下次拼接）。

    **必须按行缓冲，不能逐 chunk 独立切行**：``aiter_bytes`` 吐的是任意网络分片，
    边界与 SSE 行边界无关——一条 ``data: {...}`` 经常被切成两块，逐 chunk
    ``decode().split("\\n")`` 会让两个半行都不以 ``data: `` 开头，**整条 delta 被静默
    丢弃**；流尾没有换行收尾的末行同样永远等不到处理。

    2026-09-20 实测（StarggleChat `docs/1.txt`）：2485 字正文随机缺字 20+ 处
    （「陈让」→「陈」、「三个月不敢试」→「三个月敢试」语义反转），且正文在句中断掉；
    同一次请求的思维链同样缺字——两条流共用一个坏的解析，非模型问题。

    ``flush=True`` 时把残余当完整行处理（流结束时调用，末帧常无尾随 ``\\n``）。
    """
    if b"\n" in buf:
        *lines, buf = buf.split(b"\n")
    elif not flush:
        return buf
    else:
        lines, buf = [buf], b""
    for raw in lines:
        line = raw.decode("utf-8", errors="replace")
        if not (line.startswith("data: ") and line[6:] != "[DONE]"):
            continue
        try:
            data = json.loads(line[6:])
            # Anthropic 原生事件（ofox /v1/messages 一族）先按 type 分流——必须先于下方
            # 通用 usage 提取：message_delta 的顶层 usage 只有 output_tokens，落进通用
            # 提取会把 prompt_tokens 覆写为 0，冲掉 message_start 已记下的 input_tokens
            if data.get("type") in _ANTHROPIC_SSE_EVENT_TYPES:
                _ingest_anthropic_sse_data(
                    data, accumulated_content, accumulated_reasoning, accumulated_usage,
                )
                continue
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
    return buf


def _ingest_anthropic_sse_data(
    data: dict,
    accumulated_content: list[str],
    accumulated_reasoning: list[str],
    accumulated_usage: dict[str, int],
) -> None:
    """消费 Anthropic 原生 SSE 事件（ofox /v1/messages 等），累加正文/思维链/usage.

    与 OpenAI chunk 的字段差异：
      · 正文在 content_block_delta.delta.text，思维链在 thinking_delta.delta.thinking
      · usage 拆两帧：message_start.message.usage.input_tokens（入参）、
        message_delta.usage.output_tokens（出参终值），total 两帧各自求和
      · 流内 error 事件以 HTTP 200 到达，只记日志（原始事件已透传给客户端自行处理）
    缓存字段沿用 DeepSeek 口径换算：cache_read → hit、cache_creation → miss。
    """
    etype = data.get("type")
    if etype == "content_block_delta":
        delta = data.get("delta") or {}
        dtype = delta.get("type")
        if dtype == "text_delta" and delta.get("text"):
            accumulated_content.append(delta["text"])
        elif dtype == "thinking_delta" and delta.get("thinking"):
            accumulated_reasoning.append(delta["thinking"])
    elif etype == "message_start":
        usage = ((data.get("message") or {}).get("usage") or {})
        if usage.get("input_tokens") is not None:
            cache_read = usage.get("cache_read_input_tokens") or 0
            cache_creation = usage.get("cache_creation_input_tokens") or 0
            # Anthropic 的 input_tokens 不含缓存部分；对齐 DeepSeek 口径——
            # prompt_tokens = 未命中 + 命中 + 新建，hit/miss 作为其子集保留
            accumulated_usage["prompt_tokens"] = usage.get("input_tokens", 0) + cache_read + cache_creation
            accumulated_usage["completion_tokens"] = accumulated_usage.get("completion_tokens", 0)
            accumulated_usage["prompt_cache_hit_tokens"] = cache_read
            accumulated_usage["prompt_cache_miss_tokens"] = cache_creation
            accumulated_usage["total_tokens"] = (
                accumulated_usage["prompt_tokens"] + accumulated_usage["completion_tokens"]
            )
    elif etype == "message_delta":
        usage = data.get("usage") or {}
        if usage.get("output_tokens") is not None:
            accumulated_usage["completion_tokens"] = usage.get("output_tokens", 0)
            accumulated_usage["prompt_tokens"] = accumulated_usage.get("prompt_tokens", 0)
            accumulated_usage["total_tokens"] = (
                accumulated_usage["prompt_tokens"] + accumulated_usage["completion_tokens"]
            )
    elif etype == "error":
        err = data.get("error") or {}
        logger.error(
            "Anthropic 原生流内 error 事件: type=%s message=%s", err.get("type"), err.get("message"),
        )


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
        X-Starggle-Purpose: "main"（默认，使用 is_base="0" 的模型轮询）、
                            "async" 或 "async1".."async13"（异步LLM总控分路：命中 async_manage_info
                            且启用且已绑定模型时按配置路由并接管 model/思考/temperature/max_tokens，
                            否则回落 is_base="1" 轮询；裸 "async" 复用 async13「通用后台对话」的配置）.
        X-Starggle-Thinking: 主 LLM 思考模式开关（"1"/"true" 开启，"0"/"false" 关闭）.
                             服务端按选中模型/运营商的参数规范注入思考参数；
                             异步模式不受此头影响（思考模式由总控 is_think 决定：'1'强制开/'0'强制关/NULL跟随客户端不注入，未命中总控强制关闭）.

    请求体: 标准 OpenAI chat completions 格式.
    """
    t0 = time.perf_counter()
    llm_purpose = x_starggle_purpose or "main"
    # 任何 async* 都按异步计（含 async1..13 与未知 async99 等），
    # 防止未知 purpose 串到主模型路由使用客户端 Authorization key
    is_async = llm_purpose.startswith("async")

    # ── 异步LLM总控：async* 命中总控表且启用且已绑定模型时走配置路由，否则回落轮询 ──
    # async1..13 各查各的行；裸 "async" 及其他未知 async* 统一复用 async13「通用后台对话」的配置
    purpose_cfg = None
    lookup_purpose = llm_purpose
    if is_async:
        if not _ASYNC_PURPOSE_RE.match(llm_purpose):
            lookup_purpose = "async13"
        purpose_cfg = await async_manage_service.get_config_by_purpose(db, lookup_purpose)
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
                "POST /call-manage/chat/completions -> purpose=%s 总控(config=%s)绑定模型 %s 不存在或停用，回落 is_base=1 轮询",
                llm_purpose, lookup_purpose, purpose_cfg.ai_model_id,
            )
            use_config = False
        else:
            selected = bound
            logger.info(
                "POST /call-manage/chat/completions -> purpose=%s 命中异步LLM总控(config=%s): "
                "model=%r com=%s is_think=%s",
                llm_purpose, lookup_purpose, selected.ai_model_name, selected.com_name, purpose_cfg.is_think,
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
    # 兼容 DB 里存 https://openrouter.ai 或 https://openrouter.ai/api/v1 的情况
    # Anthropic 原生协议（ofox 等：POST /anthropic/v1/messages）不走 /chat/completions：
    #   · DB 存完整端点 …/v1/messages → 原样使用
    #   · DB 存 …/anthropic 基址 → 补 /v1/messages
    if raw_url.endswith("/chat/completions"):
        forward_url = raw_url
    elif raw_url.endswith("/messages"):
        forward_url = raw_url
    elif raw_url.endswith("/anthropic"):
        forward_url = f"{raw_url}/v1/messages"
    else:
        forward_url = f"{raw_url}/chat/completions"
    _validate_url(forward_url)
    # 原生端点判定只算一次，本方法内三处（response_format / max_tokens 兜底 / 认证头）共用
    is_anthropic_native = _is_anthropic_native_url(forward_url)

    # ── 解析请求体（须先于下方协议适配，body 在此之前尚未赋值）──
    body = await request.json()
    body = _replace_core_prompts(body)

    # ── Anthropic 原生端点：请求体协议适配 ──
    # messages 里的 role:"system" 提为顶层 system 字段（原生协议无 system 角色，不转换上游 400）
    if is_anthropic_native:
        _apply_anthropic_native_body(body)

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

    # （思考模式注入统一移至下方 model 名解析之后：异步按总控 is_think，主模式按 X-Starggle-Thinking 头）

    # ── response_format 注入 ──
    # 客户端通过 X-Starggle-Response-Format header 声明需要 JSON 输出，
    # 服务端根据实际模型决定是否/如何注入 response_format。
    if x_starggle_response_format == "json_object":
        model_name_lower = selected.ai_model_name.lower()
        is_o_series = bool(_O_SERIES_RE.match(model_name_lower))
        if is_anthropic_native:
            # Anthropic 原生协议无 response_format 字段，注入会被上游 400 拒绝
            logger.info(
                "POST /call-manage/chat/completions -> Anthropic 原生端点不支持 response_format，跳过注入 model=%s",
                selected.ai_model_name,
            )
        elif not is_o_series:
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
    #           未命中总控的回落（含裸 async 未配 async13）一律强制关闭（兼容推理模型）
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

    # ── Anthropic 原生端点：max_tokens 必填，缺省兜底 ──
    # 总控与客户端都没给时上游直接 400；兜底值须能装下思考预算收敛的最低余量
    # （budget ≥1024 + 正文 ≥1024），且小于默认思考预算以触发下方收敛逻辑。
    # bool 是 int 子类：JSON max_tokens=true 会漏过 isinstance int 判断，须显式排除
    body_max_tokens = body.get("max_tokens")
    if is_anthropic_native and (not isinstance(body_max_tokens, int) or isinstance(body_max_tokens, bool)):
        body["max_tokens"] = _ANTHROPIC_DEFAULT_MAX_TOKENS
        logger.info(
            "POST /call-manage/chat/completions -> Anthropic 原生端点缺 max_tokens，注入默认 %d model=%s",
            _ANTHROPIC_DEFAULT_MAX_TOKENS, model_name,
        )

    # ── 思考参数注入：按选中模型/运营商的参数规范构造 ──
    # 例外：强制思考型号（GLM-5.3 族 / MiniMax-M3.1+）即使「未表达偏好」也要注入。它们关不掉，不注入就是
    # 厂商默认 max（最贵最慢那一档）——异步链 is_think=NULL（跟随客户端）而客户端又不发
    # X-Starggle-Thinking 头时正是这条路。按「关闭请求」交给 _apply_thinking_params 降级为
    # enabled + 最低档；其余模型维持「缺头不注入、请求体原样透传」的既有契约。
    if think_enabled is not None:
        _apply_thinking_params(body, model_name, selected.com_url, think_enabled)
    elif _glm_forced_thinking(model_name):
        _apply_thinking_params(body, model_name, selected.com_url, False)

    # ── Claude 思考模式预算收敛 ──
    # budget_tokens 必须小于 max_tokens（Anthropic 硬约束，OpenRouter 透传同约束）。
    # 预算不足时把 budget 收敛到实际 max_tokens 内（最低 1024）；连最低预算都放不下则关闭思考，
    # 避免整路请求上游 400。仅直连 Claude 的 thinking 字段可收敛；OpenRouter reasoning 无 budget 键不动。
    # guard 不能只看 think_enabled：总控 is_think=NULL（跟随客户端）而客户端自带
    # thinking.enabled 时，上方刚兜底注入的 max_tokens 可能小于其 budget，同样须收敛。
    # 注意：本块必须与上面的 if/elif **同级**，不能被塞进某个分支体——它自身已有按需 guard。
    if "claude" in model_name.lower():
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

    # Gemini 安全阈值注入：extra_body.safety_settings 全 BLOCK_NONE（仅 gemini 系模型）
    _apply_gemini_safety(body, model_name)

    is_stream = body.get("stream", False)

    logger.info(
        "POST /call-manage/chat/completions -> model=%s stream=%s purpose=%s "
        "selected=%s(%s) url=%s body_model=%r",
        model_name, is_stream, llm_purpose, selected.ai_model_name, selected.com_name,
        forward_url, body.get("model"),
    )

    # Anthropic 原生端点（ofox /v1/messages）：x-api-key + anthropic-version（协议样例只认 x-api-key）
    if is_anthropic_native:
        fwd_headers = {
            "x-api-key": api_key,
            "anthropic-version": _ANTHROPIC_VERSION,
            "Content-Type": "application/json",
        }
    else:
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
                # 逐 chunk 累加日志用正文/usage——按行缓冲，细节见 _ingest_sse_chunk
                sse_buf = b""
                async for chunk in _stream_aiter_bytes(resp):
                    total_bytes += len(chunk)
                    accumulated_chunks.append(chunk)
                    sse_buf = _ingest_sse_chunk(
                        sse_buf + chunk,
                        accumulated_content,
                        accumulated_reasoning,
                        accumulated_usage,
                    )
                    yield chunk
                # 流结束：flush 无换行收尾的末行（末帧常无尾随 \n）
                if sse_buf:
                    _ingest_sse_chunk(
                        sse_buf,
                        accumulated_content,
                        accumulated_reasoning,
                        accumulated_usage,
                        flush=True,
                    )
            except Exception as e:
                elapsed = (time.perf_counter() - t0) * 1000
                # 异常类型名必须带上：部分上游断流异常（RemoteProtocolError 等）str() 为空串，
                # 只打 {e} 会得到 "error="（2026-09-15 error.log 实测），客户端拿到的
                # [ERROR] 事件也成了一句没有原因的空话。
                # 压平空白：异常消息内嵌换行会把单行 SSE 帧撕成多行杂散行
                err_desc = " ".join(f"{type(e).__name__}: {e}".split())
                logger.error(
                    "POST /call-manage/chat/completions <- STREAM ERROR model=%s elapsed=%.0fms error=%s",
                    model_name, elapsed, err_desc,
                )
                yield f"data: [ERROR] 流式转发失败: {err_desc}\n\n".encode("utf-8")
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
                if usage and "prompt_tokens" not in usage and "input_tokens" in usage:
                    # Anthropic 原生 usage 字段名 → OpenAI 口径（ofox /v1/messages 非流式）。
                    # input_tokens 不含缓存部分，同流式口径（见 _ingest_anthropic_sse_data）并入 prompt
                    cache_read = usage.get("cache_read_input_tokens") or 0
                    cache_creation = usage.get("cache_creation_input_tokens") or 0
                    prompt = usage.get("input_tokens", 0) + cache_read + cache_creation
                    usage = {
                        "prompt_tokens": prompt,
                        "completion_tokens": usage.get("output_tokens", 0),
                        "total_tokens": prompt + usage.get("output_tokens", 0),
                        "prompt_cache_hit_tokens": cache_read,
                        "prompt_cache_miss_tokens": cache_creation,
                    }
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
