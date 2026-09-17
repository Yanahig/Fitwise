"""前端诊断事件的收与看：排查"用户说他点了没反应"这类问题的最小闭环。

- `POST /api/events`：前端批量上报（失败静默、不阻塞交互，前端侧全部 catch 掉）；
- `GET /api/projects/{id}/events`：按项目看最近的事件，倒序，用 curl 就能看，不用做界面。

两条硬规矩写在 models.Event 上：**只收元数据、失败不影响业务**。
这里额外做一层清洗：字段数、字段名、字符串长度都截断 —— 前端失手把正文传上来也进不了库。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import Event, Project, User
from ..serializers import iso

router = APIRouter(tags=["events"])

#: 单次上报的事件条数上限：前端攒一批发一次，超出的丢掉（诊断数据不值得为它排队）
MAX_BATCH = 40
#: 单个事件的字段数与字段长度上限：超了截断，避免把正文塞进来
MAX_FIELDS = 12
MAX_VALUE_LEN = 160
#: 保留最近多少条：诊断现场是短周期数据，演示机上别把库撑起来（超出就删最旧的）
KEEP_ROWS = 5000


class EventIn(BaseModel):
    name: str
    payload: dict[str, Any] = {}
    project_id: int | None = None


class EventBatch(BaseModel):
    events: list[EventIn] = []


def _clean_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """只留标量字段，键名与字符串值都截断 —— 正文进不来。"""
    clean: dict[str, Any] = {}
    for key, value in list(payload.items())[:MAX_FIELDS]:
        if isinstance(value, str):
            clean[str(key)[:24]] = value[:MAX_VALUE_LEN]
        elif isinstance(value, (int, float, bool)) or value is None:
            clean[str(key)[:24]] = value
    return clean


@router.post("/api/events", status_code=202)
def record_events(
    batch: EventBatch,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """前端上报一批事件。名字不做白名单 —— 加新事件不该需要动后端。"""
    rows: list[Event] = []
    known_projects: dict[int, bool] = {}
    for item in batch.events[:MAX_BATCH]:
        name = str(item.name or "").strip()[:48]
        if not name:
            continue
        project_id = item.project_id
        if project_id is not None and project_id not in known_projects:
            # 项目可能已经被删（或前端给错 id）：查一次，存在才挂上去
            known_projects[project_id] = db.get(Project, project_id) is not None
        rows.append(
            Event(
                user_name=user.name,
                project_id=project_id if known_projects.get(project_id or 0) else None,
                name=name,
                payload=_clean_payload(item.payload),
            )
        )
    if rows:
        db.add_all(rows)
        db.commit()
        _prune(db)
    return {"recorded": len(rows)}


def _prune(db: Session) -> None:
    """只留最近 KEEP_ROWS 条：诊断数据不用长期保留，也不值得为它做归档。"""
    oldest = db.execute(
        select(Event.id).order_by(Event.id.desc()).offset(KEEP_ROWS).limit(1)
    ).scalar()
    if oldest is not None:
        db.execute(delete(Event).where(Event.id <= oldest))
        db.commit()


@router.get("/api/projects/{project_id}/events")
def list_events(
    project_id: int,
    limit: int = 100,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[dict]:
    size = min(max(limit, 1), 500)
    rows = (
        db.execute(
            select(Event)
            .where(Event.project_id == project_id)
            .order_by(Event.id.desc())
            .limit(size)
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": row.id,
            "project_id": row.project_id,
            "name": row.name,
            "payload": row.payload or {},
            "user": row.user_name,
            "created_at": iso(row.created_at),
        }
        for row in rows
    ]


@router.get("/api/events")
def list_recent_events(
    limit: int = 100,
    name: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[dict]:
    """全局视图：不指定项目也能看最近发生了什么 —— 登录页出错、访问到不存在的项目都会落在这里。

    排查姿势：先 `GET /api/events?limit=50` 看全貌，再用 `?name=api_failed` 或按项目筛。
    """
    size = min(max(limit, 1), 500)
    query = select(Event).order_by(Event.id.desc()).limit(size)
    if name:
        query = select(Event).where(Event.name == name[:48]).order_by(Event.id.desc()).limit(size)
    rows = db.execute(query).scalars().all()
    return [
        {
            "id": row.id,
            "project_id": row.project_id,
            "name": row.name,
            "payload": row.payload or {},
            "user": row.user_name,
            "created_at": iso(row.created_at),
        }
        for row in rows
    ]
