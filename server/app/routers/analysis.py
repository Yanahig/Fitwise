from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..db import SessionLocal, get_db
from ..deps import get_current_user
from ..domain import PROJECT_STAGES, infer_tags
from ..models import (
    CapabilityDoc,
    CaseStudy,
    Material,
    MatchResult,
    Project,
    Requirement,
    Solution,
    User,
)
from ..serializers import (
    capability_doc_out,
    case_out,
    match_out,
    requirement_out,
    solution_out,
)
from ..services import agents, jobs
from ..services.activity import log_activity

router = APIRouter(tags=["analysis"])

STAGE_ORDER = {stage["id"]: int(stage["order"]) for stage in PROJECT_STAGES}

# 活动日志给售前看的状态说法
STATUS_LABELS = {
    "full": "完全支持",
    "partial": "部分支持",
    "none": "暂不支持",
    "unknown": "待确认",
}


def _advance_stage(db: Session, project: Project, target: str) -> None:
    if STAGE_ORDER.get(target, 0) > STAGE_ORDER.get(project.stage, 0):
        project.stage = target
        db.flush()


class RequirementPatch(BaseModel):
    title: str | None = None
    detail: str | None = None
    category: str | None = None
    priority: str | None = None
    status: str | None = None
    tags: list[str] | None = None
    constraints: list[str] | None = None


class ManualRequirement(BaseModel):
    title: str
    detail: str = ""
    category: str = "产品能力"
    priority: str = "medium"
    tags: list[str] = []


class ConfirmRequest(BaseModel):
    ids: list[int] | None = None  # 为空表示确认全部草稿


class GenerateSolutionRequest(BaseModel):
    problem: str = ""


class MatchReview(BaseModel):
    status: str
    note: str = ""
    headline: str | None = None


# --------------------------------------------------------------------------- #
# 后台任务实现
# --------------------------------------------------------------------------- #


async def _run_extract(job_id: str, project_id: int, actor: str) -> None:
    db = SessionLocal()
    try:
        project = db.get(Project, project_id)
        if not project:
            jobs.fail_job(job_id, "项目不存在")
            return
        materials = (
            db.execute(select(Material).where(Material.project_id == project_id)).scalars().all()
        )
        parsed = [item for item in materials if item.status == "parsed"]
        jobs.update_job(job_id, total=max(len(parsed), 1), current="正在抽取需求…", message="")
        if not parsed:
            jobs.fail_job(job_id, "没有解析成功的材料")
            return
        created, blocked = await agents.analyze_requirements(
            db, project=project, materials=materials, actor=actor
        )
        _advance_stage(db, project, "requirements")
        log_activity(
            db,
            actor=actor,
            type="requirements_extracted",
            summary=f"从材料里整理出 {len(created)} 条需求，等待确认",
            customer_id=project.customer_id,
            project_id=project.id,
        )
        db.commit()
        jobs.finish_job(
            job_id,
            result={"requirements": len(created), **blocked},
            message=f"已抽取 {len(created)} 条需求",
        )
    except Exception as error:  # noqa: BLE001
        db.rollback()
        jobs.fail_job(job_id, str(error))
    finally:
        db.close()


async def _run_matching(job_id: str, project_id: int, actor: str, requirement_ids: list[int] | None) -> None:
    db = SessionLocal()
    try:
        project = db.get(Project, project_id)
        if not project:
            jobs.fail_job(job_id, "项目不存在")
            return
        # 人工闸门在这里生效：只有已确认的需求才做能力判断。
        # 闸门不能只装在界面上 —— 直接调接口也必须拿不到"基于草稿的结论"。
        query = select(Requirement).where(
            Requirement.project_id == project_id,
            Requirement.status == "confirmed",
        )
        if requirement_ids:
            query = query.where(Requirement.id.in_(requirement_ids))
        requirements = db.execute(query.order_by(Requirement.id)).scalars().all()
        if not requirements:
            jobs.fail_job(job_id, "还没有已确认的需求：先确认需求，我才能做能力判断")
            return

        jobs.update_job(job_id, total=len(requirements))
        # 清理旧的 AI 结论（人工覆写的保留）
        existing = (
            db.execute(
                select(MatchResult).where(MatchResult.requirement_id.in_([item.id for item in requirements]))
            )
            .scalars()
            .all()
        )
        for match in existing:
            if match.judgment_source != "human":
                db.execute(delete(MatchResult).where(MatchResult.id == match.id))
        db.commit()

        results: list[MatchResult] = []
        for index, requirement in enumerate(requirements):
            jobs.update_job(
                job_id,
                done=index,
                current=requirement.title,
                message=f"正在判断（{index + 1}/{len(requirements)}）：{requirement.title}",
            )
            results.append(await agents.judge_requirement(db, requirement=requirement))
            db.commit()
        jobs.update_job(job_id, done=len(requirements), current="", message="匹配完成")

        # 安全网：并发重跑可能给同一条需求留下两份结论，只保留最新那份（人工覆写的除外）
        judged_ids = {match.requirement_id for match in results}
        newest: dict[int, int] = {}
        for match in results:
            newest[match.requirement_id] = max(newest.get(match.requirement_id, 0), match.id or 0)
        stale_removed = 0
        if judged_ids:
            rows = (
                db.execute(select(MatchResult).where(MatchResult.requirement_id.in_(judged_ids)))
                .scalars()
                .all()
            )
            for match in rows:
                if match.judgment_source == "human" or match.id == newest.get(match.requirement_id):
                    continue
                db.execute(delete(MatchEvidence).where(MatchEvidence.match_id == match.id))
                db.delete(match)
                stale_removed += 1
            db.flush()

        counts: dict[str, int] = {}
        flagged = 0
        fallback = 0
        for match in results:
            counts[match.status] = counts.get(match.status, 0) + 1
            verdict = match.self_check or {}
            codes = {
                str(item.get("code"))
                for item in verdict.get("reasons", [])
                if isinstance(item, dict)
            }
            if verdict.get("flagged"):
                flagged += 1
            if "llm_fallback" in codes:
                fallback += 1

        # 自检发现的证据不足，转成待确认问题；只增不丢，重跑不会冲掉已处理过的条目
        guardrail_questions = [
            {
                "question": str(item).strip(),
                "why": f"判断「{match.requirement.title}」时发现证据不足，需要先确认这一条。",
                "owner": "客户",
                "source": "guardrail",
            }
            for match in results
            if match.requirement is not None
            for item in (match.confirmations or [])
            if str(item).strip()
        ]
        if guardrail_questions:
            project.open_questions = agents.merge_open_questions(
                project.open_questions, guardrail_questions
            )[:20]

        _advance_stage(db, project, "matching")
        log_activity(
            db,
            actor=actor,
            type="matches_completed",
            summary=(
                f"完成能力匹配：完全支持 {counts.get('full', 0)}、部分支持 {counts.get('partial', 0)}、"
                f"暂不支持 {counts.get('none', 0)}、待确认 {counts.get('unknown', 0)}"
                + (f"；{flagged} 条被自检标记并按上限降级" if flagged else "")
            ),
            customer_id=project.customer_id,
            project_id=project.id,
        )
        db.commit()
        jobs.finish_job(
            job_id,
            result={
                "matches": len(results),
                "counts": counts,
                "guardrail_flagged": flagged,
                "llm_fallback": fallback,
                "open_questions": len(project.open_questions or []),
                "stale_matches_removed": stale_removed,
            },
            message="匹配完成",
        )
    except Exception as error:  # noqa: BLE001
        db.rollback()
        jobs.fail_job(job_id, str(error))
    finally:
        db.close()


async def _run_solution(job_id: str, project_id: int, actor: str, problem: str) -> None:
    db = SessionLocal()
    try:
        project = db.get(Project, project_id)
        if not project:
            jobs.fail_job(job_id, "项目不存在")
            return
        matches = (
            db.execute(select(MatchResult).where(MatchResult.project_id == project_id)).scalars().all()
        )
        if not matches:
            jobs.fail_job(job_id, "请先完成能力匹配")
            return
        jobs.update_job(job_id, total=1, current="正在生成解决路径…")
        solution = await agents.compose_solution(
            db, project=project, matches=matches, problem=problem, actor=actor
        )
        _advance_stage(db, project, "solution")
        log_activity(
            db,
            actor=actor,
            type="solution_generated",
            summary=f"生成了解决路径：{solution.summary[:80]}",
            customer_id=project.customer_id,
            project_id=project.id,
        )
        db.commit()
        jobs.finish_job(job_id, result={"solution_id": solution.id, "version": solution.version}, message="解决路径已生成")
    except Exception as error:  # noqa: BLE001
        db.rollback()
        jobs.fail_job(job_id, str(error))
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# 任务查询
# --------------------------------------------------------------------------- #


@router.get("/api/jobs/{job_id}")
def get_job(job_id: str, _: User = Depends(get_current_user)) -> dict:
    job = jobs.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在或已过期")
    return job


# --------------------------------------------------------------------------- #
# 需求
# --------------------------------------------------------------------------- #


@router.get("/api/projects/{project_id}/requirements")
def list_requirements(
    project_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    requirements = (
        db.execute(select(Requirement).where(Requirement.project_id == project_id).order_by(Requirement.id))
        .scalars()
        .all()
    )
    matches = db.execute(select(MatchResult).where(MatchResult.project_id == project_id)).scalars().all()
    by_requirement = {match.requirement_id: match for match in matches}
    project = db.get(Project, project_id)
    return {
        "requirements": [requirement_out(item, by_requirement.get(item.id)) for item in requirements],
        "open_questions": (project.open_questions if project else []) or [],
    }


@router.post("/api/projects/{project_id}/requirements/extract", status_code=202)
def extract_requirements(
    project_id: int,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    running = jobs.find_running("requirements.extract", project_id)
    if running:
        return {"job_id": running["id"], "reused": True}
    job_id = jobs.create_job("requirements.extract", project_id=project_id)
    background.add_task(_run_extract, job_id, project_id, user.name)
    return {"job_id": job_id}


@router.post("/api/projects/{project_id}/requirements", status_code=201)
def create_requirement(
    project_id: int,
    payload: ManualRequirement,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    requirement = Requirement(
        project_id=project_id,
        title=payload.title,
        detail=payload.detail,
        category=payload.category,
        priority=payload.priority,
        status="confirmed",
        source_material_name="人工录入",
        tags=payload.tags or infer_tags(f"{payload.title} {payload.detail}"),
        created_by_ai=False,
        confirmed_by=user.name,
        confirmed_at=datetime.now(timezone.utc),
    )
    db.add(requirement)
    log_activity(
        db,
        actor=user.name,
        type="requirement_created",
        summary=f"手动添加了一条需求：{payload.title}",
        customer_id=project.customer_id,
        project_id=project.id,
    )
    db.commit()
    return requirement_out(requirement)


@router.patch("/api/requirements/{requirement_id}")
def update_requirement(
    requirement_id: int,
    payload: RequirementPatch,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    requirement = db.get(Requirement, requirement_id)
    if not requirement:
        raise HTTPException(status_code=404, detail="需求不存在")
    changes = payload.model_dump(exclude_none=True)
    for key, value in changes.items():
        setattr(requirement, key, value)
    # 只改状态不算"改内容"：人工改过内容的需求，重跑抽取时不再被 AI 结果覆盖
    if {"title", "detail", "category", "priority", "tags", "constraints"} & set(changes):
        requirement.edited = True
    if changes.get("status") == "confirmed":
        requirement.confirmed_by = user.name
        requirement.confirmed_at = datetime.now(timezone.utc)
    project = db.get(Project, requirement.project_id)
    if project:
        log_activity(
            db,
            actor=user.name,
            type="requirement_updated",
            summary=(
                f"确认需求：{requirement.title}"
                if changes.get("status") == "confirmed"
                else f"修改需求：{requirement.title}"
            ),
            customer_id=project.customer_id,
            project_id=project.id,
        )
    db.commit()
    return requirement_out(requirement)


@router.post("/api/projects/{project_id}/requirements/confirm")
def confirm_requirements(
    project_id: int,
    payload: ConfirmRequest,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    query = select(Requirement).where(Requirement.project_id == project_id, Requirement.status == "draft")
    if payload.ids:
        # 带 ids 时必须继续带 project_id：否则可以拿别的项目的需求 id 把它标成"已确认"
        query = query.where(Requirement.id.in_(payload.ids))
    requirements = db.execute(query).scalars().all()
    for requirement in requirements:
        requirement.status = "confirmed"
        requirement.confirmed_by = user.name
        requirement.confirmed_at = datetime.now(timezone.utc)
    project = db.get(Project, project_id)
    if project and requirements:
        log_activity(
            db,
            actor=user.name,
            type="requirements_confirmed",
            summary=f"确认了 {len(requirements)} 条需求",
            customer_id=project.customer_id,
            project_id=project.id,
        )
    db.commit()

    # 需求确认是人的决策点；确认后 Fitwise 自动开始能力匹配，不需要再点一次
    running = jobs.find_running("matches.run", project_id)
    if running:
        return {"confirmed": len(requirements), "job_id": running["id"], "reused": True}
    job_id = jobs.create_job("matches.run", project_id=project_id)
    ids = [item.id for item in requirements]
    background.add_task(_run_matching, job_id, project_id, user.name, ids or None)
    return {"confirmed": len(requirements), "job_id": job_id}


@router.delete("/api/requirements/{requirement_id}", status_code=204)
def delete_requirement(
    requirement_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> None:
    requirement = db.get(Requirement, requirement_id)
    if not requirement:
        raise HTTPException(status_code=404, detail="需求不存在")
    db.delete(requirement)
    db.commit()


# --------------------------------------------------------------------------- #
# 能力匹配
# --------------------------------------------------------------------------- #


@router.post("/api/projects/{project_id}/matches/run", status_code=202)
def run_matching(
    project_id: int,
    background: BackgroundTasks,
    requirement_ids: list[int] | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    running = jobs.find_running("matches.run", project_id)
    if running:
        return {"job_id": running["id"], "reused": True}
    job_id = jobs.create_job("matches.run", project_id=project_id)
    background.add_task(_run_matching, job_id, project_id, user.name, requirement_ids)
    return {"job_id": job_id}


@router.get("/api/projects/{project_id}/matches")
def list_matches(
    project_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[dict]:
    matches = (
        db.execute(select(MatchResult).where(MatchResult.project_id == project_id).order_by(MatchResult.id))
        .scalars()
        .all()
    )
    return [match_out(item) for item in matches]


@router.get("/api/matches/{match_id}")
def get_match(
    match_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    match = db.get(MatchResult, match_id)
    if not match:
        raise HTTPException(status_code=404, detail="匹配结果不存在")
    payload = match_out(match, include_detail=True)
    docs = [db.get(CapabilityDoc, doc_id) for doc_id in (match.capability_doc_ids or [])]
    cases = [db.get(CaseStudy, case_id) for case_id in (match.case_ids or [])]
    payload["capability_docs"] = [capability_doc_out(doc, include_signals=True) for doc in docs if doc]
    payload["cases"] = [case_out(case) for case in cases if case]
    return payload


@router.patch("/api/matches/{match_id}/review")
def review_match(
    match_id: int,
    payload: MatchReview,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    match = db.get(MatchResult, match_id)
    if not match:
        raise HTTPException(status_code=404, detail="匹配结果不存在")
    if payload.status not in {"full", "partial", "none", "unknown"}:
        raise HTTPException(status_code=400, detail="状态不合法")
    match.status = payload.status
    if payload.headline:
        match.headline = payload.headline
    match.judgment_source = "human"
    match.reviewed_by = user.name
    match.reviewed_at = datetime.now(timezone.utc)
    match.review_note = payload.note
    project = db.get(Project, match.project_id)
    if project:
        log_activity(
            db,
            actor=user.name,
            type="match_reviewed",
            summary=f"人工修正判断：{match.requirement.title} → {STATUS_LABELS.get(payload.status, payload.status)}"
            + (f"（原因：{payload.note[:60]}）" if payload.note else ""),
            customer_id=project.customer_id,
            project_id=project.id,
        )
    db.commit()
    return match_out(match)


# --------------------------------------------------------------------------- #
# 解决路径
# --------------------------------------------------------------------------- #


@router.post("/api/projects/{project_id}/solutions/generate", status_code=202)
def generate_solution(
    project_id: int,
    payload: GenerateSolutionRequest,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    running = jobs.find_running("solutions.generate", project_id)
    if running:
        return {"job_id": running["id"], "reused": True}
    problem = payload.problem or project.summary or f"{project.name} 的售前推进方案"
    job_id = jobs.create_job("solutions.generate", project_id=project_id)
    background.add_task(_run_solution, job_id, project_id, user.name, problem)
    return {"job_id": job_id}


@router.get("/api/projects/{project_id}/solutions")
def list_solutions(
    project_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[dict]:
    solutions = (
        db.execute(
            select(Solution).where(Solution.project_id == project_id).order_by(Solution.version.desc())
        )
        .scalars()
        .all()
    )
    return [solution_out(item, db) for item in solutions]


@router.patch("/api/solutions/{solution_id}")
def update_solution(
    solution_id: int,
    status_value: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    solution = db.get(Solution, solution_id)
    if not solution:
        raise HTTPException(status_code=404, detail="方案不存在")
    solution.status = status_value
    db.commit()
    return solution_out(solution, db)
