"""上传文件 → TextIn 解析 → 带页码的文本片段入库。"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import delete
from sqlalchemy.orm import Session

from ..models import Material, MaterialChunk
from . import ai_ledger, textin

logger = logging.getLogger(__name__)

PLAIN_TEXT_SUFFIXES = {".txt", ".md", ".csv", ".json"}
MAX_CHUNK_CHARS = 1400


def guess_material_type(filename: str) -> str:
    name = filename.lower()
    # 先判更具体的类型：「XX招标答疑与补充通知」是答疑，不是招标文件本身
    if any(keyword in name for keyword in ("答疑", "澄清", "qa", "question")):
        return "qa"
    if any(keyword in name for keyword in ("纪要", "会议", "minutes", "meeting")):
        return "minutes"
    if any(keyword in name for keyword in ("邮件", "mail", "往来")):
        return "email"
    if any(keyword in name for keyword in ("聊天", "微信", "im聊天", "chat", "会话")):
        return "chat"
    if any(keyword in name for keyword in ("rfp", "招标", "需求书", "采购", "tender")):
        return "rfp"
    return "other"


def elements_to_chunks(elements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把 TextIn elements 按页聚合成片段，保留页码与标题层级 —— 证据链的基础。"""
    chunks: list[dict[str, Any]] = []
    current_page: int | None = None
    current_heading = ""
    buffer: list[str] = []

    def flush() -> None:
        nonlocal buffer, current_heading
        text = "\n".join(part for part in buffer if part).strip()
        if text:
            chunks.append(
                {
                    "page": current_page or 1,
                    "heading": current_heading[:200],
                    "text": text,
                }
            )
        buffer = []

    for element in elements:
        text = (element.get("text") or "").strip()
        if not text:
            continue
        page = int(element.get("page_number") or current_page or 1)
        kind = element.get("type") or ""
        if current_page is None:
            current_page = page
        if page != current_page or sum(len(part) for part in buffer) >= MAX_CHUNK_CHARS:
            flush()
            current_page = page
            current_heading = ""
        if kind in {"Title", "SectionHeader"} and not current_heading:
            current_heading = text
        buffer.append(text)
    flush()
    return chunks


def markdown_to_chunks(markdown: str, page_count: int) -> list[dict[str, Any]]:
    """没有 elements 时的兜底：按标题切分，页码平均分配。"""
    if not markdown.strip():
        return []
    blocks = re.split(r"\n(?=#{1,3}\s)", markdown)
    chunks: list[dict[str, Any]] = []
    per_page = max(1, len(blocks) // max(page_count, 1))
    for index, block in enumerate(blocks):
        text = block.strip()
        if not text:
            continue
        heading_match = re.match(r"#{1,3}\s*(.+)", text)
        chunks.append(
            {
                "page": min(page_count or 1, index // per_page + 1),
                "heading": (heading_match.group(1).strip() if heading_match else "")[:200],
                "text": text,
            }
        )
    return chunks


def _local_text_chunks(path: Path) -> list[dict[str, Any]]:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = path.read_text(encoding="gbk", errors="ignore")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    chunks: list[dict[str, Any]] = []
    for index in range(0, len(lines), 25):
        block = lines[index : index + 25]
        chunks.append({"page": index // 25 + 1, "heading": "", "text": "\n".join(block)})
    return chunks


async def parse_material(db: Session, material: Material, *, trace_id: str = "") -> Material:
    """解析一份材料，写入 markdown 与带页码的片段。

    trace_id 把这一步和后面的抽取/判断/建议串成一次运行（见 services/ai_ledger.py）。
    失败成因码写进 material.parse_error 前缀与账本：前端可以据此给不同的下一步提示，
    而不是统一一句"没读出来"。
    """
    path = Path(material.storage_path)
    material.status = "parsing"
    material.parse_error = ""
    db.flush()

    started = time.perf_counter()
    chunks: list[dict[str, Any]] = []
    attempts = 0
    engine = "textin-xparse"
    error_code = ""
    try:
        if path.suffix.lower() in PLAIN_TEXT_SUFFIXES:
            engine = "local-text"
            attempts = 1
            chunks = _local_text_chunks(path)
            material.markdown = path.read_text(encoding="utf-8", errors="ignore")
            material.page_count = max(1, len(chunks))
            material.parse_engine = engine
        else:
            document = await textin.parse_file(path, material.filename)
            attempts = document.attempts
            material.markdown = document.markdown
            material.page_count = document.page_count or 1
            material.textin_file_id = document.file_id
            material.parse_engine = engine
            chunks = elements_to_chunks(document.elements) or markdown_to_chunks(
                document.markdown, material.page_count
            )

        db.execute(delete(MaterialChunk).where(MaterialChunk.material_id == material.id))
        for index, chunk in enumerate(chunks):
            db.add(
                MaterialChunk(
                    material_id=material.id,
                    page=chunk["page"],
                    heading=chunk.get("heading", ""),
                    text=chunk["text"],
                    order_index=index,
                )
            )
        material.status = "parsed"
        material.parsed_at = datetime.now(timezone.utc)
    except Exception as error:  # noqa: BLE001 - 解析失败要落库，前端要能看到原因
        error_code = textin.classify(error)
        attempts = max(attempts, int(getattr(error, "attempts", 0) or 0))
        logger.warning("解析失败 %s（成因 %s）：%s", material.filename, error_code, error)
        material.status = "failed"
        material.parse_error = f"[{error_code}] {error}"[:500]
    finally:
        ai_ledger.record(
            db,
            trace_id=trace_id,
            project_id=material.project_id,
            step="parse",
            provider=textin.endpoint_host() if engine == "textin-xparse" else "local",
            model=engine,
            attempts=attempts,
            latency_ms=int((time.perf_counter() - started) * 1000),
            ok=material.status == "parsed",
            error_code=error_code,
            error=material.parse_error,
        )

    db.flush()
    return material
