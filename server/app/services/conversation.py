"""对话落库：会话能跨刷新、跨天活着，Agent 才有记忆。

只存"说过什么、做过什么"，不存对象状态：
工具回执卡里放的是 material_id / job_id，状态仍然从材料表与任务表实时读，
这样刷新之后卡片不会停在旧进度上。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AgentMessage

MAX_TEXT = 2000
MAX_LIMIT = 200


def append(
    db: Session,
    *,
    project_id: int,
    role: str,
    kind: str = "text",
    text: str = "",
    data: dict | None = None,
) -> AgentMessage:
    message = AgentMessage(
        project_id=project_id,
        role=role[:16],
        kind=kind[:16],
        text=(text or "")[:MAX_TEXT],
        data=data or {},
    )
    db.add(message)
    db.flush()
    return message


def recent(db: Session, *, project_id: int, limit: int = 40) -> list[AgentMessage]:
    rows = (
        db.execute(
            select(AgentMessage)
            .where(AgentMessage.project_id == project_id)
            .order_by(AgentMessage.id.desc())
            .limit(min(limit, MAX_LIMIT))
        )
        .scalars()
        .all()
    )
    return list(reversed(rows))


def update(db: Session, *, message_id: int, text: str | None = None, data: dict | None = None) -> AgentMessage | None:
    message = db.get(AgentMessage, message_id)
    if message is None:
        return None
    if text is not None:
        message.text = text[:MAX_TEXT]
    if data is not None:
        message.data = data
    db.flush()
    return message
