"""AI 调用账本的查询面：成本、可观测、版本追溯都从这里看。

只读接口，不参与业务链路：

- `GET /api/projects/{id}/ai-calls`：按项目看调用次数、token、失败与回退（成本口径）；
- `GET /api/traces/{trace_id}`：按一次运行看完整调用链（复盘口径）——
  一次上传或一次「从头跑一遍」就是一个 trace，解析 / 抽取 / 每条判断 / 建议都在里面。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import Project, User
from ..prompts import PROMPT_SET_VERSION, PROMPT_VERSIONS
from ..services import ai_ledger

router = APIRouter(tags=["traces"])


@router.get("/api/projects/{project_id}/ai-calls")
def project_ai_calls(
    project_id: int,
    limit: int = 50,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    if not db.get(Project, project_id):
        raise HTTPException(status_code=404, detail="项目不存在")
    summary = ai_ledger.project_summary(db, project_id=project_id, limit=limit)
    # 当前生效的提示词版本：和历史记录里的 prompt_version 对照，就能知道哪次改动影响了哪批结论
    summary["prompt_set_version"] = PROMPT_SET_VERSION
    summary["prompt_versions"] = PROMPT_VERSIONS
    return summary


@router.get("/api/traces/{trace_id}")
def trace_detail(
    trace_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    calls = ai_ledger.trace_calls(db, trace_id=trace_id)
    if not calls:
        raise HTTPException(status_code=404, detail="没有这次运行的调用记录")
    return {
        "trace_id": trace_id,
        "calls": [ai_ledger.call_out(item) for item in calls],
        "totals": {
            "calls": len(calls),
            "failed": sum(1 for item in calls if not item.ok),
            "fallback": sum(1 for item in calls if item.fallback_used),
            "total_tokens": sum(item.prompt_tokens + item.completion_tokens for item in calls),
            "latency_ms": max((item.latency_ms for item in calls), default=0),
        },
    }
