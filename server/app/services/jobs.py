"""轻量后台任务登记表（单进程内存实现）。

P0 用一个进程内的任务表把「解析 / 抽取 / 匹配 / 生成」变成可轮询的后台任务，
前端据此显示真实进度。P1 替换为真正的任务队列（Redis + worker）时，
只需保持 create/update/get 这三个接口不变。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

JOBS: dict[str, dict[str, Any]] = {}


def create_job(kind: str, *, total: int = 1, project_id: int | None = None) -> str:
    job_id = uuid.uuid4().hex[:12]
    JOBS[job_id] = {
        "id": job_id,
        "kind": kind,
        "project_id": project_id,
        "status": "running",
        "total": total,
        "done": 0,
        "current": "",
        "message": "",
        "error": "",
        "result": {},
        "created_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
    }
    return job_id


def update_job(job_id: str, **fields: Any) -> None:
    job = JOBS.get(job_id)
    if job:
        job.update(fields)


def finish_job(job_id: str, *, result: dict | None = None, message: str = "") -> None:
    update_job(
        job_id,
        status="done",
        message=message,
        result=result or {},
        finished_at=datetime.now(timezone.utc).isoformat(),
    )


def fail_job(job_id: str, error: str) -> None:
    update_job(
        job_id,
        status="failed",
        error=error[:500],
        finished_at=datetime.now(timezone.utc).isoformat(),
    )


def get_job(job_id: str) -> dict[str, Any] | None:
    return JOBS.get(job_id)


def find_running(kind: str, project_id: int | None) -> dict[str, Any] | None:
    """同项目同类型的任务已经在跑就复用，不再起第二个。

    之前踩过的坑：确认需求后后端自动跑能力判断，用户（或脚本）又点了一次"再跑一遍"，
    两个任务并发写同一批需求 → 同一需求出现两条结论、话术还不一样。
    """
    for job in JOBS.values():
        if job["kind"] == kind and job["project_id"] == project_id and job["status"] == "running":
            return job
    return None
