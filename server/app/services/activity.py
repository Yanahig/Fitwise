from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import Activity


def log_activity(
    db: Session,
    *,
    actor: str,
    type: str,
    summary: str,
    customer_id: int | None = None,
    project_id: int | None = None,
    payload: dict | None = None,
) -> Activity:
    """记录客户档案时间线上的一条活动。"""
    activity = Activity(
        customer_id=customer_id,
        project_id=project_id,
        actor=actor,
        type=type,
        summary=summary[:400],
        payload=payload or {},
    )
    db.add(activity)
    db.flush()
    return activity
