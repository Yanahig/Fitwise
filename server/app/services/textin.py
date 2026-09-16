"""TextIn xParse 文档解析客户端。

支持 19 种文件格式（PDF / Word / Excel / PPT / 图片 / OFD / HTML / TXT …），
返回带页码的 elements 与 markdown —— 页码是整套证据链的基础。

失败处理与模型侧对齐（此前只有超时、没有重试）：

- 可重试（网络 / 超时 / 限流 / 5xx）自动重试 1 次，再失败才把成因交给上层；
- 不可重试（凭据错、文件内容问题）立即失败 —— 重试只是白等一轮；
- 每个失败都带成因码，写进 material.parse_error 与 AI 调用账本，
  前端据此给不同的下一步提示，而不是统一一句"没读出来"。

文档：https://docs.textin.com/xparse/v1/quickstart
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from ..config import settings
from . import ai_ledger

logger = logging.getLogger(__name__)

SYNC_ENDPOINT = "/api/v1/xparse/parse/sync"
ASYNC_ENDPOINT = "/api/v1/xparse/parse/async"

#: 一次解析最多尝试几次（与模型侧一致：一次失败后重试一次）
MAX_ATTEMPTS = 2
#: 重试前的等待；第二次失败就放弃，不做更长的退避
RETRY_DELAY_SECONDS = 1.5

DEFAULT_CONFIG = {
    "capabilities": {
        "include_table_structure": True,
        "title_tree": True,
    }
}


class TextInError(RuntimeError):
    """TextIn 解析失败。code 是失败成因码，重试判断看 ai_ledger.is_retryable。"""

    def __init__(self, message: str, *, code: str = ai_ledger.ERROR_UNKNOWN) -> None:
        super().__init__(message)
        self.code = code
        #: 已经尝试了几次（默认 1 次）；parse_file 在重试后再失败时会覆盖它
        self.attempts = 1


def endpoint_host() -> str:
    """TextIn 端点主机名：写进账本，和模型侧保持同一种记录口径。"""
    try:
        from urllib.parse import urlparse

        return urlparse(settings.textin_base_url).hostname or settings.textin_base_url[:80]
    except ValueError:  # pragma: no cover - 兜底
        return settings.textin_base_url[:80]


def _status_code(status: int) -> str:
    if status in (401, 403):
        return ai_ledger.ERROR_AUTH
    if status == 429:
        return ai_ledger.ERROR_RATE_LIMIT
    if status >= 500:
        return ai_ledger.ERROR_SERVER
    return ai_ledger.ERROR_BAD_REQUEST


def _classify(error: Exception) -> str:
    if isinstance(error, TextInError):
        return error.code
    if isinstance(error, httpx.TimeoutException):
        return ai_ledger.ERROR_TIMEOUT
    if isinstance(error, httpx.TransportError):
        return ai_ledger.ERROR_NETWORK
    return ai_ledger.ERROR_UNKNOWN


def classify(error: Exception) -> str:
    """给上层用：把解析异常归类成失败成因码（写进 material.parse_error 前缀）。"""
    return _classify(error)


@dataclass
class ParsedDocument:
    markdown: str = ""
    elements: list[dict[str, Any]] = field(default_factory=list)
    page_count: int = 0
    success_count: int = 0
    file_id: str = ""
    job_id: str = ""
    schema_version: str = ""
    #: 实际尝试次数与耗时：写进 AI 调用账本，用来算成本与排查慢在哪
    attempts: int = 0
    latency_ms: int = 0


def _headers() -> dict[str, str]:
    return {
        "x-ti-app-id": settings.textin_app_id,
        "x-ti-secret-code": settings.textin_secret_code,
    }


def _payload_to_document(payload: dict[str, Any]) -> ParsedDocument:
    if payload.get("code") not in (200, 0, None):
        raise TextInError(
            f"TextIn 返回错误：{payload.get('message') or payload.get('code')}",
            code=ai_ledger.ERROR_CONTENT,
        )

    data = payload.get("data") or payload
    metadata = data.get("metadata") or {}
    return ParsedDocument(
        markdown=data.get("markdown") or "",
        elements=data.get("elements") or [],
        page_count=int(metadata.get("page_count") or 0),
        success_count=int(data.get("success_count") or 0),
        file_id=str(data.get("file_id") or ""),
        job_id=str(data.get("job_id") or ""),
        schema_version=str(data.get("schema_version") or ""),
    )


async def parse_file_sync(path: Path, filename: str | None = None) -> ParsedDocument:
    """同步解析：适合中小文件（文档建议 30 页以内走同步）。"""
    if not settings.textin_enabled:
        raise TextInError("未配置 TEXTIN_APP_ID / TEXTIN_SECRET_CODE", code=ai_ledger.ERROR_AUTH)

    url = f"{settings.textin_base_url}{SYNC_ENDPOINT}"
    files = {"file": (filename or path.name, path.read_bytes())}
    data = {"config": json.dumps(DEFAULT_CONFIG)}

    try:
        async with httpx.AsyncClient(timeout=300) as client:
            response = await client.post(url, headers=_headers(), files=files, data=data)
    except httpx.HTTPError as error:
        raise TextInError(f"TextIn 请求失败：{error}", code=_classify(error)) from error
    if response.status_code >= 400:
        raise TextInError(
            f"TextIn HTTP {response.status_code}: {response.text[:300]}",
            code=_status_code(response.status_code),
        )
    try:
        return _payload_to_document(response.json())
    except ValueError as error:
        raise TextInError(f"TextIn 返回内容无法解析：{error}", code=ai_ledger.ERROR_CONTENT) from error


async def parse_file_async(
    path: Path,
    filename: str | None = None,
    poll_interval: float = 3.0,
    max_wait_seconds: float = 900,
) -> ParsedDocument:
    """异步解析：适合大文件，创建任务后轮询结果。"""
    if not settings.textin_enabled:
        raise TextInError("未配置 TEXTIN_APP_ID / TEXTIN_SECRET_CODE", code=ai_ledger.ERROR_AUTH)

    url = f"{settings.textin_base_url}{ASYNC_ENDPOINT}"
    files = {"file": (filename or path.name, path.read_bytes())}
    headers = _headers()

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(url, headers=headers, files=files)
            if response.status_code >= 400:
                raise TextInError(
                    f"TextIn HTTP {response.status_code}: {response.text[:300]}",
                    code=_status_code(response.status_code),
                )
            payload = response.json()
            data = payload.get("data") or {}
            job_id = str(data.get("job_id") or "")
            if not job_id:
                raise TextInError(f"TextIn 未返回 job_id：{payload}", code=ai_ledger.ERROR_CONTENT)

            waited = 0.0
            while waited < max_wait_seconds:
                await asyncio.sleep(poll_interval)
                waited += poll_interval
                status_response = await client.get(f"{url}/{job_id}", headers=headers)
                status_payload = status_response.json()
                status_data = status_payload.get("data") or {}
                status = status_data.get("status")
                if status == "completed":
                    result_url = status_data.get("result_url")
                    if not result_url:
                        raise TextInError(
                            "TextIn 异步任务完成但缺少 result_url", code=ai_ledger.ERROR_CONTENT
                        )
                    result_response = await client.get(result_url, headers=headers)
                    result_payload = result_response.json()
                    document = _payload_to_document({"code": 200, "data": result_payload})
                    document.job_id = job_id
                    return document
                if status == "failed":
                    raise TextInError(
                        f"TextIn 解析失败：{status_data.get('message')}",
                        code=ai_ledger.ERROR_CONTENT,
                    )
    except httpx.HTTPError as error:
        raise TextInError(f"TextIn 请求失败：{error}", code=_classify(error)) from error

    raise TextInError("TextIn 异步解析超时", code=ai_ledger.ERROR_TIMEOUT)


async def parse_file(path: Path, filename: str | None = None, page_hint: int | None = None) -> ParsedDocument:
    """统一入口：按页数选择同步或异步，失败按可重试性自动重试 1 次。"""
    started = time.perf_counter()
    last_error: TextInError = TextInError("TextIn 解析失败", code=ai_ledger.ERROR_UNKNOWN)

    for attempt in range(MAX_ATTEMPTS):
        try:
            if page_hint and page_hint > settings.textin_async_page_threshold:
                logger.info("文件页数 %s 超过阈值，使用异步解析：%s", page_hint, filename or path.name)
                document = await parse_file_async(path, filename)
            else:
                document = await parse_file_sync(path, filename)
            document.attempts = attempt + 1
            document.latency_ms = int((time.perf_counter() - started) * 1000)
            return document
        except TextInError as error:
            last_error = error
            retryable = ai_ledger.is_retryable(error.code)
            if not retryable or attempt + 1 >= MAX_ATTEMPTS:
                error.attempts = attempt + 1
                raise
            logger.warning(
                "TextIn 解析失败（第 %s 次，成因 %s），%.1fs 后重试一次：%s",
                attempt + 1,
                error.code,
                RETRY_DELAY_SECONDS,
                filename or path.name,
            )
        except Exception as error:  # noqa: BLE001 - 意外异常也归类，重试一次再交给上层
            last_error = TextInError(str(error), code=_classify(error))
            last_error.attempts = attempt + 1
            if attempt + 1 >= MAX_ATTEMPTS:
                raise last_error from error
            logger.warning("TextIn 解析异常（第 %s 次）：%s", attempt + 1, error)
        await asyncio.sleep(RETRY_DELAY_SECONDS)

    raise last_error
