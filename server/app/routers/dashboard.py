"""工作台：今天有什么项目在推进、最近发生了什么。

只读聚合，不承担业务动作 —— 原来的行动项/承诺接口已经下线，这里只剩一个 GET。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import Activity, CapabilityDoc, CaseStudy, Customer, MatchResult, Project, User
from ..serializers import activity_out, project_out
from .projects import project_counts

router = APIRouter(tags=["dashboard"])


@router.get("/api/dashboard")
def dashboard(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    projects = (
        db.execute(select(Project).where(Project.status == "active").order_by(Project.updated_at.desc()))
        .scalars()
        .all()
    )
    pending_review = (
        db.execute(
            select(func.count(MatchResult.id)).where(
                MatchResult.status == "unknown", MatchResult.reviewed_at.is_(None)
            )
        ).scalar()
        or 0
    )
    activities = (
        db.execute(select(Activity).order_by(Activity.created_at.desc()).limit(20)).scalars().all()
    )

    return {
        "stats": {
            "customers": db.execute(select(func.count(Customer.id))).scalar() or 0,
            "projects_active": len(projects),
            "matches_pending_review": pending_review,
            "knowledge_docs": db.execute(select(func.count(CapabilityDoc.id))).scalar() or 0,
            "knowledge_cases": db.execute(select(func.count(CaseStudy.id))).scalar() or 0,
        },
        "projects": [project_out(item, counts=project_counts(db, item.id)) for item in projects],
        "activities": [activity_out(item) for item in activities],
        "viewer": {"name": user.name, "role": user.role},
    }
