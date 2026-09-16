from __future__ import annotations

"""知识库：MVP 里是**只读**的 —— 能力文档与案例由 `seed.py` 灌好，页面只用来回指依据。

维护接口（建文档 / 改文档 / 加信号 / 删信号）在 demo 里没有任何入口，也没人调用，一起下线；
真要做成产品时再当成一块独立的后台维护来做。
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import get_current_user
from ..domain import MATERIAL_TYPES, MATCH_STATUSES, PROJECT_STAGES, REQUIREMENT_STATUSES
from sqlalchemy import func

from ..models import CapabilityDoc, CaseStudy, User
from ..serializers import capability_doc_out, case_out
from ..services.llm import health as llm_health

router = APIRouter(tags=["knowledge"])


@router.get("/api/meta")
def meta(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict:
    return {
        "stages": PROJECT_STAGES,
        "match_statuses": MATCH_STATUSES,
        "requirement_statuses": REQUIREMENT_STATUSES,
        "material_types": MATERIAL_TYPES,
        "knowledge": {
            "docs": db.execute(select(func.count(CapabilityDoc.id))).scalar() or 0,
            "cases": db.execute(select(func.count(CaseStudy.id))).scalar() or 0,
        },
        "integrations": {
            "parser": {
                "provider": "TextIn xParse",
                "enabled": settings.textin_enabled,
                "formats": [
                    "pdf", "doc", "docx", "xls", "xlsx", "csv", "ppt", "pptx",
                    "png", "jpg", "jpeg", "bmp", "tiff", "webp", "html", "mhtml", "txt", "ofd", "rtf",
                ],
            },
            "llm": {
                "provider": "DeepSeek",
                "model": settings.llm_model,
                "enabled": settings.llm_enabled,
                # 数据流向要说清楚：材料内容会发到模型端点；换成本地模型只需改 LLM_BASE_URL
                "endpoint_host": _endpoint_host(settings.llm_base_url),
                "external": _is_external(settings.llm_base_url),
            },
        },
    }


def _endpoint_host(url: str) -> str:
    return (url or "").replace("https://", "").replace("http://", "").split("/")[0]


def _is_external(url: str) -> bool:
    host = _endpoint_host(url).lower()
    return not any(token in host for token in ("127.0.0.1", "localhost", "192.168.", "10.", "企业内网"))


@router.get("/api/health")
async def health(_: User = Depends(get_current_user)) -> dict:
    return {
        "parser": {"provider": "TextIn xParse", "enabled": settings.textin_enabled},
        "llm": await llm_health(),
    }


@router.get("/api/knowledge/docs")
def list_docs(
    q: str | None = Query(default=None),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[dict]:
    query = select(CapabilityDoc).order_by(CapabilityDoc.product, CapabilityDoc.id)
    if q:
        like = f"%{q}%"
        query = query.where(or_(CapabilityDoc.title.like(like), CapabilityDoc.product.like(like)))
    docs = db.execute(query).scalars().all()
    return [capability_doc_out(doc, include_signals=True) for doc in docs]


@router.get("/api/knowledge/cases")
def list_cases(
    q: str | None = Query(default=None),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[dict]:
    query = select(CaseStudy).order_by(CaseStudy.id)
    if q:
        like = f"%{q}%"
        query = query.where(or_(CaseStudy.name.like(like), CaseStudy.industry.like(like)))
    cases = db.execute(query).scalars().all()
    return [case_out(item) for item in cases]
