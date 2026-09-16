"""企业知识库检索：标签匹配 + 关键词命中的混合检索。

P0 采用可解释的规则检索（9 份能力文档 / 5 个案例规模下效果最好、可复现、无额外成本）；
接口设计为可替换，P1 可平滑切换到向量检索（pgvector）而无需改 Agent。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import CapabilityDoc, CapabilitySignal, CaseStudy


@dataclass
class SignalHit:
    signal: CapabilitySignal
    relevance: float


@dataclass
class DocHit:
    doc: CapabilityDoc
    score: float
    matched_tags: list[str] = field(default_factory=list)
    signals: list[SignalHit] = field(default_factory=list)
    constraints: list[SignalHit] = field(default_factory=list)


@dataclass
class CaseHit:
    case: CaseStudy
    score: float
    matched_tags: list[str] = field(default_factory=list)


def _relevance(tags: list, requirement_tags: list[str]) -> float:
    """命中标签数为主，命中比例为辅（更具体的信号优先）。"""
    if not tags:
        return 0.0
    matched = len([tag for tag in tags if tag in requirement_tags])
    if matched == 0:
        return 0.0
    return matched + matched / len(tags)


def _text_score(text: str, doc: CapabilityDoc) -> float:
    """产品名等关键词在需求文本中直接出现时加权。"""
    if not text:
        return 0.0
    haystack = text.lower()
    alias = re.sub(r"^星云", "", doc.product or "").lower()
    score = 0.0
    if alias and alias in haystack:
        score += 3.0
    for keyword in (doc.title or "").replace("星云", " ").split():
        if len(keyword) >= 3 and keyword.lower() in haystack:
            score += 0.5
    return score


def search_capabilities(
    db: Session,
    *,
    text: str,
    tags: list[str],
    top_k: int = 4,
) -> list[DocHit]:
    docs = db.execute(select(CapabilityDoc).where(CapabilityDoc.status == "active")).scalars().all()
    requirement_tags = list(dict.fromkeys(tags))
    hits: list[DocHit] = []

    for doc in docs:
        signals = [s for s in doc.signals if any(tag in requirement_tags for tag in (s.tags or []))]
        matched_tags = list(
            dict.fromkeys(
                [tag for tag in (doc.tags or []) if tag in requirement_tags]
                + [tag for s in signals for tag in (s.tags or []) if tag in requirement_tags]
            )
        )
        if not matched_tags:
            continue

        signal_hits = [SignalHit(s, _relevance(s.tags or [], requirement_tags)) for s in signals]
        support = [s for s in signal_hits if s.signal.kind == "support"]
        constraints = [s for s in signal_hits if s.signal.kind != "support"]
        score = len(matched_tags) * 3 + len(support) * 2 + len(constraints) + _text_score(text, doc)
        hits.append(
            DocHit(
                doc=doc,
                score=score,
                matched_tags=matched_tags,
                signals=sorted(support, key=lambda item: item.relevance, reverse=True),
                constraints=sorted(constraints, key=lambda item: item.relevance, reverse=True),
            )
        )

    # 只保留真正命中能力信号或限制条件的文档，避免“标签沾边但没有证据”
    hits = [hit for hit in hits if hit.signals or hit.constraints]
    hits.sort(key=lambda hit: hit.score, reverse=True)
    return hits[:top_k]


def search_cases(db: Session, *, tags: list[str], top_k: int = 3) -> list[CaseHit]:
    cases = db.execute(select(CaseStudy)).scalars().all()
    requirement_tags = list(dict.fromkeys(tags))
    hits: list[CaseHit] = []
    for case in cases:
        matched = [tag for tag in (case.tags or []) if tag in requirement_tags]
        score = _relevance(case.tags or [], requirement_tags)
        if len(matched) == 0 or score < 2:
            continue
        hits.append(CaseHit(case=case, score=score, matched_tags=matched))
    hits.sort(key=lambda hit: hit.score, reverse=True)
    return hits[:top_k]


def hit_summary(hit: DocHit) -> str:
    """生成人类可读的命中说明，用于 prompt 与界面。"""
    parts = [f"《{hit.doc.title} {hit.doc.version}》"]
    if hit.signals:
        first = hit.signals[0].signal
        parts.append(f"P{first.page} {first.heading}：{first.excerpt}")
    if hit.constraints:
        first = hit.constraints[0].signal
        parts.append(f"限制 P{first.page}：{first.excerpt}")
    return "；".join(parts)
