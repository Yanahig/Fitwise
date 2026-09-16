"""DeepSeek（OpenAI 兼容协议）客户端。

统一入口：chat_json() —— 强制模型输出 JSON，并在解析失败时回退到调用方提供的
确定性实现，保证系统在模型异常时依然可用。

每次调用都会结算一份 meta（模型、耗时、尝试次数、token、是否回退、失败码），
并交给 on_call 回调写进 AI 调用账本 —— 成本、可观测与版本追溯共用这一份数据。
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Callable
from urllib.parse import urlparse

import httpx

from ..config import settings
from . import ai_ledger

logger = logging.getLogger(__name__)

FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


class LLMError(RuntimeError):
    """模型调用失败。code 是失败成因码，可重试性由 ai_ledger.is_retryable 判定。"""

    def __init__(self, message: str, *, code: str = ai_ledger.ERROR_UNKNOWN) -> None:
        super().__init__(message)
        self.code = code


def endpoint_host(url: str) -> str:
    """端点主机名：写进账本，用来回答「这次用的是哪家/哪个端点」。"""
    try:
        return urlparse(url).hostname or url[:80]
    except ValueError:  # pragma: no cover - 兜底，正常配置不会触发
        return url[:80]


def classify_error(error: Exception, *, status: int | None = None) -> str:
    """把异常归类成失败成因码：网络抖动可重试，凭据错、输出不合规重试也没用。"""
    if status is not None:
        if status in (401, 403):
            return ai_ledger.ERROR_AUTH
        if status == 429:
            return ai_ledger.ERROR_RATE_LIMIT
        if status >= 500:
            return ai_ledger.ERROR_SERVER
        return ai_ledger.ERROR_BAD_REQUEST
    if isinstance(error, httpx.TimeoutException):
        return ai_ledger.ERROR_TIMEOUT
    if isinstance(error, httpx.TransportError):
        return ai_ledger.ERROR_NETWORK
    code = getattr(error, "code", "")
    if code and code != ai_ledger.ERROR_UNKNOWN:
        return str(code)
    message = str(error)
    if "缺少必需字段" in message:
        return ai_ledger.ERROR_MISSING_KEYS
    if "JSON" in message or isinstance(error, json.JSONDecodeError):
        return ai_ledger.ERROR_BAD_JSON
    return ai_ledger.ERROR_UNKNOWN


def _extract_json(content: str) -> dict[str, Any]:
    cleaned = FENCE_RE.sub("", content).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            return json.loads(cleaned[start : end + 1])
        raise


async def chat_json(
    *,
    system: str,
    user: str,
    schema_hint: str,
    fallback: Callable[[], dict[str, Any]] | None = None,
    temperature: float = 0.2,
    required_keys: list[str] | None = None,
    meta: dict[str, Any] | None = None,
    trace_id: str = "",
    step: str = "",
    prompt_version: str = "",
    on_call: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """调用模型并返回 JSON。失败时使用 fallback（如提供）。

    - required_keys：模型输出缺少这些顶层字段就按失败处理（重试 → 回退），
      避免用默认值把"模型没按要求输出"这件事悄悄吃掉。
    - meta：调用结束后回填实际使用的模型、耗时、尝试次数与是否走了回退，
      调用方据此在界面上标注"本次为规则结果"，而不是只写进日志。
    - trace_id / step / prompt_version / on_call：把这次调用记进 AI 调用账本，
      用来算成本、复盘链路、回答"这条结论是哪版提示词算出来的"。
    """
    started = time.perf_counter()
    attempts = 0
    prompt_tokens = 0
    completion_tokens = 0
    error_code = ""
    llm_enabled = settings.llm_enabled

    def emit(*, fallback_used: bool, error: str = "") -> None:
        """把这次调用记进账本（meta 摘要 + on_call 回调）。成功与失败都要记。"""
        latency_ms = int((time.perf_counter() - started) * 1000)
        model_name = settings.llm_model if llm_enabled else "规则回退"
        provider = endpoint_host(settings.llm_base_url) if llm_enabled else "rules"
        if meta is not None:
            meta.update(
                {
                    "model": model_name,
                    "attempts": attempts,
                    "fallback_used": fallback_used,
                    "latency_ms": latency_ms,
                    "error": error[:300],
                    "error_code": error_code,
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "prompt_version": prompt_version,
                    "trace_id": trace_id,
                    "step": step,
                }
            )
        if on_call is not None:
            on_call(
                {
                    "trace_id": trace_id,
                    "step": step,
                    "provider": provider,
                    "model": model_name,
                    "prompt_version": prompt_version,
                    "attempts": attempts,
                    "latency_ms": latency_ms,
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "fallback_used": fallback_used,
                    "ok": not fallback_used and not error,
                    "error_code": error_code,
                    "error": error,
                }
            )

    def finish(payload: dict[str, Any], *, fallback_used: bool, error: str = "") -> dict[str, Any]:
        emit(fallback_used=fallback_used, error=error)
        return payload

    if not llm_enabled:
        error_code = ai_ledger.ERROR_NO_API_KEY
        message = "未配置 LLM_API_KEY"
        if not fallback:
            emit(fallback_used=True, error=message)
            raise LLMError(message, code=error_code)
        logger.warning("未配置 LLM_API_KEY，使用本地规则回退")
        return finish(fallback(), fallback_used=True, error=message)

    url = f"{settings.llm_base_url.rstrip('/')}/chat/completions"
    body = {
        "model": settings.llm_model,
        "messages": [
            {"role": "system", "content": f"{system}\n\n必须只输出 JSON，结构如下：\n{schema_hint}"},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "response_format": {"type": "json_object"},
        "stream": False,
    }
    headers = {"Authorization": f"Bearer {settings.llm_api_key}", "Content-Type": "application/json"}

    last_error: Exception | None = None
    for attempt in range(2):
        attempts = attempt + 1
        try:
            async with httpx.AsyncClient(timeout=settings.llm_timeout_seconds) as client:
                response = await client.post(url, headers=headers, json=body)
            if response.status_code >= 400:
                raise LLMError(
                    f"LLM HTTP {response.status_code}: {response.text[:300]}",
                    code=classify_error(LLMError("http"), status=response.status_code),
                )
            payload = response.json()
            usage = payload.get("usage") or {}
            prompt_tokens += int(usage.get("prompt_tokens") or 0)
            completion_tokens += int(usage.get("completion_tokens") or 0)
            content = payload["choices"][0]["message"]["content"]
            try:
                parsed = _extract_json(content)
            except json.JSONDecodeError as error:
                raise LLMError("模型输出不是合法 JSON", code=ai_ledger.ERROR_BAD_JSON) from error
            if not isinstance(parsed, dict):
                raise LLMError("模型输出不是 JSON 对象", code=ai_ledger.ERROR_BAD_JSON)
            missing = [key for key in (required_keys or []) if key not in parsed]
            if missing:
                raise LLMError(
                    f"模型输出缺少必需字段：{'、'.join(missing)}",
                    code=ai_ledger.ERROR_MISSING_KEYS,
                )
            return finish(parsed, fallback_used=False)
        except Exception as error:  # noqa: BLE001 - 需要兜底所有异常，保证系统可用
            last_error = error
            error_code = classify_error(error)
            logger.warning("LLM 调用失败（第 %s 次，%s）：%s", attempt + 1, error_code, error)
            # 凭据错、请求不合法、输出不合规：再试一次也是同一个结果，直接走回退
            if not ai_ledger.is_retryable(error_code):
                logger.warning("失败成因「%s」不可重试，直接走回退", error_code)
                break

    if fallback:
        logger.warning("LLM 连续失败，使用本地规则回退：%s", last_error)
        return finish(fallback(), fallback_used=True, error=str(last_error))
    emit(fallback_used=True, error=str(last_error))
    raise LLMError(str(last_error), code=error_code or ai_ledger.ERROR_UNKNOWN)


async def health() -> dict[str, Any]:
    """轻量健康检查：只读模型列表，不产生计费。"""
    if not settings.llm_enabled:
        return {"ok": False, "reason": "未配置 LLM_API_KEY"}
    url = f"{settings.llm_base_url.rstrip('/')}/models"
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(url, headers={"Authorization": f"Bearer {settings.llm_api_key}"})
        models = [item.get("id") for item in (response.json().get("data") or [])]
        return {"ok": response.status_code == 200, "models": models, "configured": settings.llm_model}
    except Exception as error:  # noqa: BLE001
        return {"ok": False, "reason": str(error)}
