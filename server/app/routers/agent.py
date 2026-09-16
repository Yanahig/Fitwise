"""对话入口：Agent 的单步路由。

这个接口是只读的 —— 它只决定「用材料回答」还是「提议一个动作」，
动作的执行由前端调用既有的 /requirements/extract、/matches/run、/solutions/generate 完成。
这样只有一条写数据路径（既有端点），权限与留痕不用再做第二套。
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import AgentMessage, Project, User
from ..serializers import agent_message_out
from ..services import agent_router, conversation

router = APIRouter(tags=["agent"])

MAX_MESSAGE_CHARS = 500
ALLOWED_ROLES = {"tool", "agent"}
ALLOWED_KINDS = {"job", "material", "text", "approval"}


class AskPayload(BaseModel):
    message: str


class MessagePayload(BaseModel):
    role: str = "tool"
    kind: str = "job"
    text: str = ""
    data: dict = {}


class MessagePatch(BaseModel):
    text: str | None = None
    data: dict | None = None


class ApprovalPayload(BaseModel):
    message_id: int
    decision: str  # approved / declined


def _project_or_404(db: Session, project_id: int) -> Project:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return project


@router.post("/api/projects/{project_id}/agent/ask")
async def ask_agent(
    project_id: int,
    payload: AskPayload,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    project = _project_or_404(db, project_id)
    message = (payload.message or "").strip()[:MAX_MESSAGE_CHARS]
    if not message:
        raise HTTPException(status_code=400, detail="问题不能为空")
    result = await agent_router.route_message(db, project=project, message=message)
    db.commit()
    return result


@router.get("/api/projects/{project_id}/agent/messages")
def list_messages(
    project_id: int,
    limit: int = 40,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[dict]:
    """会话历史：刷新页面后 Agent 还认得这段对话。"""
    _project_or_404(db, project_id)
    return [agent_message_out(item) for item in conversation.recent(db, project_id=project_id, limit=limit)]


@router.get("/api/projects/{project_id}/agent/state")
def project_state(
    project_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    """项目状态与「下一步」：界面上的下一步提示就来自这里，不各算一套。"""
    project = _project_or_404(db, project_id)
    state = agent_router.project_state(db, project)
    return {"state": state, "next_step": agent_router.next_step(state)}


@router.post("/api/projects/{project_id}/agent/messages", status_code=201)
def append_message(
    project_id: int,
    payload: MessagePayload,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    """工具回执卡：动作开始时落一条，结束时更新它。"""
    _project_or_404(db, project_id)
    message = conversation.append(
        db,
        project_id=project_id,
        role=payload.role if payload.role in ALLOWED_ROLES else "tool",
        kind=payload.kind if payload.kind in ALLOWED_KINDS else "text",
        text=payload.text,
        data=payload.data,
    )
    db.commit()
    return agent_message_out(message)


@router.patch("/api/agent/messages/{message_id}")
def patch_message(
    message_id: int,
    payload: MessagePatch,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    message = conversation.update(db, message_id=message_id, text=payload.text, data=payload.data)
    if message is None:
        raise HTTPException(status_code=404, detail="消息不存在")
    db.commit()
    return agent_message_out(message)


@router.delete("/api/projects/{project_id}/agent/messages", status_code=204)
def clear_messages(
    project_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> None:
    """清空这个项目的对话：会话既然落了库，就得有清空的办法。"""
    _project_or_404(db, project_id)
    db.execute(delete(AgentMessage).where(AgentMessage.project_id == project_id))
    db.commit()


@router.post("/api/projects/{project_id}/agent/approvals")
def record_approval(
    project_id: int,
    payload: ApprovalPayload,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """批准留痕：谁、什么时候、批还是拒 —— 由服务端写，不由前端自报。

    这个接口不执行动作：批准之后由前端调用既有端点执行，
    这样"批准"和"执行"各自留痕，权限也只有一条路径。
    """
    _project_or_404(db, project_id)
    message = db.get(AgentMessage, payload.message_id)
    if message is None or message.project_id != project_id or message.kind != "approval":
        raise HTTPException(status_code=404, detail="待批准的动作不存在")
    data = dict(message.data or {})
    approval = dict(data.get("approval") or {})
    approval.update(
        {
            "decision": "approved" if payload.decision == "approved" else "declined",
            "by": user.name,
            "at": datetime.now(timezone.utc).isoformat(),
        }
    )
    data["approval"] = approval
    message.data = data
    db.commit()
    return agent_message_out(message)
