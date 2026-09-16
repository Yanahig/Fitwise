"""DeepSeek（OpenAI 兼容协议）客户端。

统一入口：chat_json() —— 强制模型输出 JSON，并在解析失败时回退到调用方提供的
确定性实现，保证系统在模型异常时依然可用。
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Callable

import httpx

from ..config import settings

logger = logging.getLogger(__name__)

FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


class LLMError(RuntimeError):
    """模型调用失败。"""


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
) -> dict[str, Any]:
    """调用模型并返回 JSON。失败时使用 fallback（如提供）。

    - required_keys：模型输出缺少这些顶层字段就按失败处理（重试 → 回退），
      避免用默认值把"模型没按要求输出"这件事悄悄吃掉。
    - meta：调用结束后回填实际使用的模型、耗时、尝试次数与是否走了回退，
      调用方据此在界面上标注"本次为规则结果"，而不是只写进日志。
    """
    started = time.perf_counter()
    attempts = 0

    def finish(payload: dict[str, Any], *, fallback_used: bool, error: str = "") -> dict[str, Any]:
        if meta is not None:
            meta.update(
                {
                    "model": settings.llm_model,
                    "attempts": attempts,
                    "fallback_used": fallback_used,
                    "latency_ms": int((time.perf_counter() - started) * 1000),
                    "error": error[:300],
                }
            )
        return payload

    if not settings.llm_enabled:
        if fallback:
            logger.warning("未配置 LLM_API_KEY，使用本地规则回退")
            return finish(fallback(), fallback_used=True, error="未配置 LLM_API_KEY")
        raise LLMError("未配置 LLM_API_KEY")

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
                raise LLMError(f"LLM HTTP {response.status_code}: {response.text[:300]}")
            payload = response.json()
            content = payload["choices"][0]["message"]["content"]
            parsed = _extract_json(content)
            if not isinstance(parsed, dict):
                raise LLMError("模型输出不是 JSON 对象")
            missing = [key for key in (required_keys or []) if key not in parsed]
            if missing:
                raise LLMError(f"模型输出缺少必需字段：{'、'.join(missing)}")
            return finish(parsed, fallback_used=False)
        except Exception as error:  # noqa: BLE001 - 需要兜底所有异常，保证系统可用
            last_error = error
            logger.warning("LLM 调用失败（第 %s 次）：%s", attempt + 1, error)

    if fallback:
        logger.warning("LLM 连续失败，使用本地规则回退：%s", last_error)
        return finish(fallback(), fallback_used=True, error=str(last_error))
    raise LLMError(str(last_error))


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
