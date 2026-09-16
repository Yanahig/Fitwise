"""ORM → API 字典的序列化。集中放置，避免每个路由重复拼装。"""

from __future__ import annotations

from .models import (
    Activity,
    AgentMessage,
    CapabilityDoc,
    CaseStudy,
    Customer,
    Material,
    MatchEvidence,
    MatchResult,
    Project,
    Requirement,
    Solution,
    User,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session


def iso(value) -> str | None:
    return value.isoformat() if value else None


def user_out(user: User) -> dict:
    return {"id": user.id, "email": user.email, "name": user.name, "role": user.role}


def customer_out(customer: Customer) -> dict:
    payload = {
        "id": customer.id,
        "name": customer.name,
        "industry": customer.industry,
        "scale": customer.scale,
        "region": customer.region,
        "tier": customer.tier,
        "owner_name": customer.owner_name,
        "source": customer.source,
        "health": customer.health,
        "notes": customer.notes,
        "created_at": iso(customer.created_at),
        "updated_at": iso(customer.updated_at),
    }
    return payload


def project_out(
    project: Project,
    *,
    customer_name: str | None = None,
    counts: dict | None = None,
) -> dict:
    payload = {
        "id": project.id,
        "customer_id": project.customer_id,
        "customer_name": customer_name or (project.customer.name if project.customer else ""),
        "name": project.name,
        "code": project.code,
        "stage": project.stage,
        "status": project.status,
        "owner_name": project.owner_name,
        "summary": project.summary,
        "highlights": project.highlights or [],
        "created_at": iso(project.created_at),
        "updated_at": iso(project.updated_at),
    }
    if counts is not None:
        payload["counts"] = counts
    return payload


def material_out(material: Material) -> dict:
    return {
        "id": material.id,
        "project_id": material.project_id,
        "filename": material.filename,
        "file_type": material.file_type,
        "material_type": material.material_type,
        "size_bytes": material.size_bytes,
        "status": material.status,
        "parse_engine": material.parse_engine,
        "page_count": material.page_count,
        "parse_error": material.parse_error,
        "summary": material.summary,
        "version": material.version,
        "uploaded_by": material.uploaded_by,
        "created_at": iso(material.created_at),
        "parsed_at": iso(material.parsed_at),
    }


def agent_message_out(message: AgentMessage) -> dict:
    return {
        "id": message.id,
        "project_id": message.project_id,
        "role": message.role,
        "kind": message.kind,
        "text": message.text,
        "data": message.data or {},
        "created_at": iso(message.created_at),
    }


def requirement_out(requirement: Requirement, match: MatchResult | None = None) -> dict:
    payload = {
        "id": requirement.id,
        "project_id": requirement.project_id,
        "title": requirement.title,
        "detail": requirement.detail,
        "category": requirement.category,
        "priority": requirement.priority,
        "status": requirement.status,
        "source": {
            "material_id": requirement.source_material_id,
            "document_name": requirement.source_material_name,
            "page": requirement.source_page,
            "heading": requirement.source_heading,
            "excerpt": requirement.source_excerpt,
        },
        "tags": requirement.tags or [],
        "constraints": requirement.constraints or [],
        "created_by_ai": requirement.created_by_ai,
        # 人工改过内容：重跑抽取时保留，界面上给出标记
        "edited": requirement.edited,
        "confirmed_by": requirement.confirmed_by,
        "confirmed_at": iso(requirement.confirmed_at),
        "created_at": iso(requirement.created_at),
    }
    if match is not None:
        payload["match"] = {"id": match.id, "status": match.status, "headline": match.headline}
    return payload


def evidence_out(evidence) -> dict:
    return {
        "id": evidence.id,
        "source_type": evidence.source_type,
        "document_name": evidence.document_name,
        "page": evidence.page,
        "heading": evidence.heading,
        "excerpt": evidence.excerpt,
    }


def match_out(match: MatchResult, *, include_detail: bool = False) -> dict:
    payload = {
        "id": match.id,
        "project_id": match.project_id,
        "requirement_id": match.requirement_id,
        "requirement": requirement_out(match.requirement) if match.requirement else None,
        "status": match.status,
        "headline": match.headline,
        "condition": match.condition,
        "rationale": match.rationale,
        "confidence": match.confidence,
        "judgment_source": match.judgment_source,
        "reviewed_by": match.reviewed_by,
        "reviewed_at": iso(match.reviewed_at),
        "review_note": match.review_note,
        "gaps": match.gaps or [],
        "confirmations": match.confirmations or [],
        "capability_doc_ids": match.capability_doc_ids or [],
        "case_ids": match.case_ids or [],
        # 取证轨迹与自检裁决：判断详情里的"取证过程"读这两项
        "trace": match.trace or [],
        "self_check": match.self_check or {},
        "created_at": iso(match.created_at),
    }
    if include_detail:
        payload["evidences"] = [evidence_out(item) for item in match.evidences]
    return payload


def capability_doc_out(doc: CapabilityDoc, *, include_signals: bool = False) -> dict:
    payload = {
        "id": doc.id,
        "product": doc.product,
        "title": doc.title,
        "doc_type": doc.doc_type,
        "version": doc.version,
        "owner": doc.owner,
        "status": doc.status,
        "effective_at": doc.effective_at,
        "description": doc.description,
        "tags": doc.tags or [],
        "supported_scope": doc.supported_scope or [],
        "limitations": doc.limitations or [],
        "deployment": doc.deployment or [],
        "api_capabilities": doc.api_capabilities or [],
        "updated_at": iso(doc.updated_at),
    }
    if include_signals:
        payload["signals"] = [
            {
                "id": signal.id,
                "kind": signal.kind,
                "text": signal.text,
                "page": signal.page,
                "heading": signal.heading,
                "excerpt": signal.excerpt,
                "tags": signal.tags or [],
            }
            for signal in doc.signals
        ]
    return payload


def case_out(case: CaseStudy) -> dict:
    return {
        "id": case.id,
        "name": case.name,
        "industry": case.industry,
        "scale": case.scale,
        "duration": case.duration,
        "background": case.background,
        "needs": case.needs or [],
        "products": case.products or [],
        "solution": case.solution,
        "results": case.results or [],
        "lessons": case.lessons or [],
        "tags": case.tags or [],
        "evidence": {
            "document_name": case.evidence_doc,
            "page": case.evidence_page,
            "excerpt": case.evidence_excerpt,
        },
    }


def _basis_out(db: Session | None, requirement_ids: list) -> list[dict]:
    """把 solution 里记的需求 id 还原成「判断 + 证据」。

    风险/行动只存 requirement_ids，证据在读的时候现查 —— 这样重新跑判断之后，
    售前建议里的依据不会变成过期数据。
    """
    ids = [int(item) for item in (requirement_ids or []) if str(item).isdigit()]
    if db is None or not ids:
        return []
    matches = (
        db.execute(select(MatchResult).where(MatchResult.requirement_id.in_(ids)))
        .scalars()
        .all()
    )
    basis: list[dict] = []
    for match in matches[:2]:
        evidences = (
            db.execute(select(MatchEvidence).where(MatchEvidence.match_id == match.id).limit(3))
            .scalars()
            .all()
        )
        basis.append(
            {
                "requirement_id": match.requirement_id,
                "title": match.requirement.title if match.requirement else "",
                "status": match.status,
                "headline": match.headline,
                "evidences": [
                    {
                        "source_type": item.source_type,
                        "document_name": item.document_name,
                        "page": item.page,
                        "excerpt": (item.excerpt or "")[:120],
                    }
                    for item in evidences
                ],
            }
        )
    return basis


def _with_basis(rows: list, db: Session | None) -> list[dict]:
    return [
        {**row, "basis": _basis_out(db, row.get("requirement_ids"))}
        for row in (rows or [])
        if isinstance(row, dict)
    ]


def solution_out(solution: Solution, db: Session | None = None) -> dict:
    return {
        "id": solution.id,
        "project_id": solution.project_id,
        "problem": solution.problem,
        "summary": solution.summary,
        "version": solution.version,
        "status": solution.status,
        "steps": solution.steps or [],
        "capability_plan": solution.capability_plan or [],
        "reference_cases": solution.reference_cases or [],
        "ask_customer": solution.ask_customer or [],
        "ask_internal": solution.ask_internal or [],
        # 风险与行动带上它们依据的判断与证据（存 id、读时解析）
        "risks": _with_basis(solution.risks or [], db),
        "next_actions": _with_basis(solution.next_actions or [], db),
        "generated_at": iso(solution.generated_at),
    }


def activity_out(activity: Activity) -> dict:
    return {
        "id": activity.id,
        "customer_id": activity.customer_id,
        "project_id": activity.project_id,
        "actor": activity.actor,
        "type": activity.type,
        "summary": activity.summary,
        "payload": activity.payload or {},
        "created_at": iso(activity.created_at),
    }
