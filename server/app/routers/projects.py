from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import (
    Activity,
    Customer,
    Material,
    MatchResult,
    Project,
    Requirement,
    Solution,
    User,
)
from ..serializers import (
    activity_out,
    customer_out,
    material_out,
    project_out,
    requirement_out,
    solution_out,
)
from ..services.activity import log_activity

router = APIRouter(prefix="/api/projects", tags=["projects"])


class ProjectRequest(BaseModel):
    customer_id: int
    name: str
    code: str = ""
    stage: str = "materials"
    status: str = "active"
    owner_name: str = ""
    summary: str = ""


class HighlightsPatch(BaseModel):
    highlights: list[dict]


def project_counts(db: Session, project_id: int) -> dict:
    materials = db.execute(select(func.count(Material.id)).where(Material.project_id == project_id)).scalar() or 0
    parsed = (
        db.execute(
            select(func.count(Material.id)).where(Material.project_id == project_id, Material.status == "parsed")
        ).scalar()
        or 0
    )
    requirements = (
        db.execute(select(func.count(Requirement.id)).where(Requirement.project_id == project_id)).scalar() or 0
    )
    confirmed = (
        db.execute(
            select(func.count(Requirement.id)).where(
                Requirement.project_id == project_id, Requirement.status == "confirmed"
            )
        ).scalar()
        or 0
    )
    status_rows = db.execute(
        select(MatchResult.status, func.count(MatchResult.id))
        .where(MatchResult.project_id == project_id)
        .group_by(MatchResult.status)
    ).all()
    match_counts = {status: count for status, count in status_rows}
    has_solution = (
        db.execute(select(func.count(Solution.id)).where(Solution.project_id == project_id)).scalar() or 0
    ) > 0
    return {
        "materials": materials,
        "materials_parsed": parsed,
        "requirements": requirements,
        "requirements_confirmed": confirmed,
        "matches": sum(match_counts.values()),
        "matches_full": match_counts.get("full", 0),
        "matches_partial": match_counts.get("partial", 0),
        "matches_none": match_counts.get("none", 0),
        "matches_unknown": match_counts.get("unknown", 0),
        "has_solution": has_solution,
    }


@router.get("")
def list_projects(
    customer_id: int | None = Query(default=None),
    status: str | None = Query(default=None),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[dict]:
    query = select(Project).order_by(Project.updated_at.desc())
    if customer_id:
        query = query.where(Project.customer_id == customer_id)
    if status:
        query = query.where(Project.status == status)
    projects = db.execute(query).scalars().all()
    return [project_out(item, counts=project_counts(db, item.id)) for item in projects]


@router.post("", status_code=201)
def create_project(
    payload: ProjectRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    customer = db.get(Customer, payload.customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail="客户不存在")
    project = Project(**payload.model_dump())
    db.add(project)
    db.flush()
    log_activity(
        db,
        actor=user.name,
        type="project_created",
        summary=f"创建了项目：{project.name}",
        customer_id=customer.id,
        project_id=project.id,
    )
    db.commit()
    return project_out(project, counts=project_counts(db, project.id))


class ProjectPatch(BaseModel):
    name: str | None = None
    owner_name: str | None = None
    summary: str | None = None


@router.patch("/{project_id}")
def update_project(
    project_id: int,
    payload: ProjectPatch,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """改项目名/负责人/摘要：AI 从材料里识别出项目名后回填，人也可以手动改。"""
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    for key, value in payload.model_dump(exclude_none=True).items():
        setattr(project, key, str(value).strip())
    log_activity(
        db,
        actor=user.name,
        type="project_updated",
        summary=f"更新项目：{project.name}",
        customer_id=project.customer_id,
        project_id=project.id,
    )
    db.commit()
    return project_out(project, counts=project_counts(db, project.id))


@router.get("/{project_id}")
def get_project(
    project_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    materials = (
        db.execute(
            select(Material).where(Material.project_id == project_id).order_by(Material.created_at.desc())
        )
        .scalars()
        .all()
    )
    matches = (
        db.execute(select(MatchResult).where(MatchResult.project_id == project_id)).scalars().all()
    )
    match_by_requirement = {match.requirement_id: match for match in matches}
    requirements = (
        db.execute(
            select(Requirement)
            .where(Requirement.project_id == project_id)
            .order_by(Requirement.id)
        )
        .scalars()
        .all()
    )
    solution = (
        db.execute(
            select(Solution).where(Solution.project_id == project_id).order_by(Solution.version.desc())
        )
        .scalars()
        .first()
    )
    activities = (
        db.execute(
            select(Activity)
            .where(Activity.project_id == project_id)
            .order_by(Activity.created_at.desc())
            .limit(30)
        )
        .scalars()
        .all()
    )

    payload = project_out(project, counts=project_counts(db, project_id))
    payload["customer"] = customer_out(project.customer)
    payload["materials"] = [material_out(item) for item in materials]
    payload["requirements"] = [
        requirement_out(item, match_by_requirement.get(item.id)) for item in requirements
    ]
    payload["open_questions"] = project.open_questions or []
    payload["solution"] = solution_out(solution, db) if solution else None
    payload["activities"] = [activity_out(item) for item in activities]
    return payload


@router.patch("/{project_id}/highlights")
def update_highlights(
    project_id: int,
    payload: HighlightsPatch,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """项目要点的人工维护：只允许改事实文案或标记忽略，不允许写入判断结论。"""
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    cleaned: list[dict] = []
    for item in payload.highlights[:20]:
        value = str(item.get("value") or "").strip()
        if not value:
            continue
        cleaned.append(
            {
                "label": str(item.get("label") or "项目要点").strip()[:20],
                "value": value[:200],
                "source_material_name": str(item.get("source_material_name") or "")[:200],
                "source_page": item.get("source_page") or None,
                "edited": bool(item.get("edited")),
                "ignored": bool(item.get("ignored")),
            }
        )
    project.highlights = cleaned
    log_activity(
        db,
        actor=user.name,
        type="highlights_updated",
        summary=f"更新了项目要点：{project.name}",
        customer_id=project.customer_id,
        project_id=project.id,
    )
    db.commit()
    return {"highlights": project.highlights}


@router.get("/{project_id}/activities")
def list_activities(
    project_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[dict]:
    activities = (
        db.execute(
            select(Activity)
            .where(Activity.project_id == project_id)
            .order_by(Activity.created_at.desc())
            .limit(100)
        )
        .scalars()
        .all()
    )
    return [activity_out(item) for item in activities]
