"""TextIn xParse 文档解析客户端。

支持 19 种文件格式（PDF / Word / Excel / PPT / 图片 / OFD / HTML / TXT …），
返回带页码的 elements 与 markdown —— 页码是整套证据链的基础。

文档：https://docs.textin.com/xparse/v1/quickstart
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from ..config import settings

logger = logging.getLogger(__name__)

SYNC_ENDPOINT = "/api/v1/xparse/parse/sync"
ASYNC_ENDPOINT = "/api/v1/xparse/parse/async"

DEFAULT_CONFIG = {
    "capabilities": {
        "include_table_structure": True,
        "title_tree": True,
    }
}


class TextInError(RuntimeError):
    """TextIn 解析失败。"""


@dataclass
class ParsedDocument:
    markdown: str = ""
    elements: list[dict[str, Any]] = field(default_factory=list)
    page_count: int = 0
    success_count: int = 0
    file_id: str = ""
    job_id: str = ""
    schema_version: str = ""


def _headers() -> dict[str, str]:
    return {
        "x-ti-app-id": settings.textin_app_id,
        "x-ti-secret-code": settings.textin_secret_code,
    }


def _payload_to_document(payload: dict[str, Any]) -> ParsedDocument:
    if payload.get("code") not in (200, 0, None):
        raise TextInError(f"TextIn 返回错误：{payload.get('message') or payload.get('code')}")

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
        raise TextInError("未配置 TEXTIN_APP_ID / TEXTIN_SECRET_CODE")

    url = f"{settings.textin_base_url}{SYNC_ENDPOINT}"
    files = {"file": (filename or path.name, path.read_bytes())}
    data = {"config": json.dumps(DEFAULT_CONFIG)}

    async with httpx.AsyncClient(timeout=300) as client:
        response = await client.post(url, headers=_headers(), files=files, data=data)
        if response.status_code >= 400:
            raise TextInError(f"TextIn HTTP {response.status_code}: {response.text[:300]}")
        return _payload_to_document(response.json())


async def parse_file_async(
    path: Path,
    filename: str | None = None,
    poll_interval: float = 3.0,
    max_wait_seconds: float = 900,
) -> ParsedDocument:
    """异步解析：适合大文件，创建任务后轮询结果。"""
    if not settings.textin_enabled:
        raise TextInError("未配置 TEXTIN_APP_ID / TEXTIN_SECRET_CODE")

    url = f"{settings.textin_base_url}{ASYNC_ENDPOINT}"
    files = {"file": (filename or path.name, path.read_bytes())}
    headers = _headers()

    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(url, headers=headers, files=files)
        if response.status_code >= 400:
            raise TextInError(f"TextIn HTTP {response.status_code}: {response.text[:300]}")
        payload = response.json()
        data = payload.get("data") or {}
        job_id = str(data.get("job_id") or "")
        if not job_id:
            raise TextInError(f"TextIn 未返回 job_id：{payload}")

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
                    raise TextInError("TextIn 异步任务完成但缺少 result_url")
                result_response = await client.get(result_url, headers=headers)
                result_payload = result_response.json()
                document = _payload_to_document({"code": 200, "data": result_payload})
                document.job_id = job_id
                return document
            if status == "failed":
                raise TextInError(f"TextIn 解析失败：{status_data.get('message')}")

    raise TextInError("TextIn 异步解析超时")


async def parse_file(path: Path, filename: str | None = None, page_hint: int | None = None) -> ParsedDocument:
    """统一入口：按页数选择同步或异步。"""
    if page_hint and page_hint > settings.textin_async_page_threshold:
        logger.info("文件页数 %s 超过阈值，使用异步解析：%s", page_hint, filename or path.name)
        return await parse_file_async(path, filename)
    return await parse_file_sync(path, filename)
