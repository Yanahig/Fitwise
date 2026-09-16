"""材料内检索：把「问材料里的信息」变成能点回页码的证据。

两路证据源，都带页码：

1. **项目要点**（project.highlights）：Agent 1 已经摘好的事实，带 label 与来源页。
   用户问「工期是多久」时，材料原文写的是「1.4 项目周期」，关键词对不上；
   但要点里的标签是「工期口径」——这一路能命中。提纯过的事实本来就比原文更容易答对。
2. **材料分片**（material_chunks）：按页聚合的原文，用来回答要点没覆盖的细节。

检索方式先用可解释的关键词命中（与 retrieval.py 同一套思路：可复现、零额外成本、能说清为什么命中）。
接口保持稳定（返回带页码的 Evidence），P1 换成向量检索时上层不用改。
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Material, MaterialChunk

# 问句里的疑问词与虚词：命中它们等于没命中，不如不参与打分
STOPWORDS = {
    "请问",
    "问一下",
    "有没有",
    "是否",
    "什么",
    "怎么",
    "如何",
    "多少",
    "多久",
    "哪一",
    "哪些",
    "哪个",
    "我们",
    "你们",
    "他们",
    "这个",
    "那个",
    "一下",
    "的话",
    "以及",
    "还有",
}

MAX_TERMS = 24


@dataclass
class ChunkHit:
    material_id: int
    document_name: str
    page: int
    heading: str
    text: str
    score: float


@dataclass
class Evidence:
    """给 Agent 看的统一证据：要点与原文同形，方便一起排序、一起给引用。"""

    material_id: int | None
    document_name: str
    page: int | None
    heading: str
    text: str
    score: float
    kind: str  # fact（项目要点）/ chunk（材料原文）


def query_terms(query: str) -> list[str]:
    """把问句切成 2–4 字的候选词。

    中文没有空格，P0 不做分词：直接取 n-gram，命中不了的候选自然得 0 分，
    所以宁可多切几个，也不用维护一份业务词表。
    """
    cleaned = "".join(char for char in (query or "") if char.isalnum())
    terms: list[str] = []
    for size in (4, 3, 2):
        for index in range(max(0, len(cleaned) - size + 1)):
            term = cleaned[index : index + size]
            if len(term) < 2 or term in STOPWORDS or term in terms:
                continue
            terms.append(term)
    return terms[:MAX_TERMS]


def search_chunks(
    db: Session,
    *,
    project_id: int,
    query: str,
    top_k: int = 6,
) -> list[ChunkHit]:
    """在项目的已解析材料里找片段。得分 = 命中词长度之和（词越长越具体）。"""
    terms = query_terms(query)
    if not terms:
        return []

    rows = db.execute(
        select(MaterialChunk, Material)
        .join(Material, Material.id == MaterialChunk.material_id)
        .where(Material.project_id == project_id, Material.status == "parsed")
    ).all()

    hits: list[ChunkHit] = []
    for chunk, material in rows:
        text = chunk.text or ""
        heading = chunk.heading or ""
        score = 0.0
        for term in terms:
            if term in text:
                score += len(term)
            if term and term in heading:
                score += len(term) * 0.6
        if score <= 0:
            continue
        hits.append(
            ChunkHit(
                material_id=material.id,
                document_name=material.filename,
                page=chunk.page,
                heading=heading,
                text=text,
                score=score,
            )
        )

    hits.sort(key=lambda item: item.score, reverse=True)
    return hits[:top_k]


def search_facts(
    db: Session,
    *,
    project_id: int,
    highlights: list,
    query: str,
    top_k: int = 4,
) -> list[Evidence]:
    """在项目要点里找。标签命中权重更高：用户问「工期」，命中的是「工期口径」这类标签。"""
    terms = query_terms(query)
    if not terms or not highlights:
        return []

    material_ids = {
        filename: material_id
        for material_id, filename in db.execute(
            select(Material.id, Material.filename).where(Material.project_id == project_id)
        ).all()
    }

    hits: list[Evidence] = []
    for fact in highlights:
        if not isinstance(fact, dict) or fact.get("ignored"):
            continue
        label = str(fact.get("label") or "")
        value = str(fact.get("value") or "")
        score = 0.0
        for term in terms:
            if term and term in label:
                score += len(term) * 1.4
            elif term and term in value:
                score += len(term)
        if score <= 0:
            continue
        name = str(fact.get("source_material_name") or "")
        page = fact.get("source_page")
        hits.append(
            Evidence(
                material_id=material_ids.get(name),
                document_name=name or "客户材料",
                page=int(page) if page else None,
                heading=label,
                text=value,
                # 提纯过的事实本来就更容易答对，给一点固有优势
                score=score + 2,
                kind="fact",
            )
        )
    hits.sort(key=lambda item: item.score, reverse=True)
    return hits[:top_k]


def search_evidence(
    db: Session,
    *,
    project_id: int,
    highlights: list,
    query: str,
    top_k: int = 6,
) -> list[Evidence]:
    """要点与原文合并检索：要点更能答对问题，原文用来补细节。"""
    facts = search_facts(db, project_id=project_id, highlights=highlights, query=query)
    chunks = [
        Evidence(
            material_id=hit.material_id,
            document_name=hit.document_name,
            page=hit.page,
            heading=hit.heading,
            text=hit.text,
            score=hit.score,
            kind="chunk",
        )
        for hit in search_chunks(db, project_id=project_id, query=query)
    ]
    merged = facts + chunks
    merged.sort(key=lambda item: item.score, reverse=True)
    return merged[:top_k]
