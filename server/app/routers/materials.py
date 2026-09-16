from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import SessionLocal, get_db
from ..deps import get_current_user
from ..models import Material, MaterialChunk, Project, Requirement, User
from ..serializers import material_out
from ..services.activity import log_activity
from ..services.parse_pipeline import guess_material_type, parse_material

router = APIRouter(tags=["materials"])

MAX_UPLOAD_BYTES = 500 * 1024 * 1024  # TextIn 单文件上限 500MB


def _parse_in_background(material_id: int) -> None:
    """后台解析：独立 session，避免请求结束后连接已关闭。"""
    db = SessionLocal()
    try:
        material = db.get(Material, material_id)
        if not material:
            return
        import asyncio

        asyncio.run(parse_material(db, material))
        project = db.get(Project, material.project_id)
        log_activity(
            db,
            actor="system",
            type="material_parsed" if material.status == "parsed" else "material_parse_failed",
            summary=(
                f"已读完客户材料：{material.filename}（共 {material.page_count} 页）"
                if material.status == "parsed"
                else f"这份材料没能读出来：{material.filename}"
            ),
            customer_id=project.customer_id if project else None,
            project_id=material.project_id,
        )
        db.commit()

        # Fitwise 自动推进：材料读完后立即提炼需求，用户不需要点任何按钮
        if material.status == "parsed" and project:
            from ..services import agents

            materials = (
                db.execute(select(Material).where(Material.project_id == material.project_id))
                .scalars()
                .all()
            )
            created, blocked = asyncio.run(
                agents.analyze_requirements(db, project=project, materials=materials, actor="Fitwise Agent")
            )
            log_activity(
                db,
                actor="Fitwise Agent",
                type="requirements_extracted",
                summary=f"自动读完全部材料，整理出 {len(created)} 条需求（去重 {blocked['skipped_duplicates']} 条），等待确认",
                customer_id=project.customer_id,
                project_id=project.id,
            )
            db.commit()
    finally:
        db.close()


@router.get("/api/projects/{project_id}/materials")
def list_materials(
    project_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[dict]:
    materials = (
        db.execute(
            select(Material).where(Material.project_id == project_id).order_by(Material.created_at.desc())
        )
        .scalars()
        .all()
    )
    return [material_out(item) for item in materials]


@router.post("/api/projects/{project_id}/materials", status_code=201)
async def upload_material(
    project_id: int,
    background: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail="文件超过 500MB，请拆分后再上传")

    suffix = Path(file.filename or "upload").suffix
    stored_name = f"{project_id}-{uuid.uuid4().hex[:8]}{suffix}"
    stored_path = settings.resolved_storage_dir / stored_name
    stored_path.write_bytes(content)

    material = Material(
        project_id=project_id,
        filename=file.filename or stored_name,
        file_type=file.content_type or suffix.lstrip("."),
        material_type=guess_material_type(file.filename or ""),
        size_bytes=len(content),
        storage_path=str(stored_path),
        status="uploaded",
        uploaded_by=user.name,
    )
    db.add(material)
    db.flush()
    log_activity(
        db,
        actor=user.name,
        type="material_uploaded",
        summary=f"上传了客户材料：{material.filename}",
        customer_id=project.customer_id,
        project_id=project.id,
    )
    db.commit()

    background.add_task(_parse_in_background, material.id)
    return material_out(material)


@router.post("/api/materials/{material_id}/parse")
def reparse_material(
    material_id: int,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    material = db.get(Material, material_id)
    if not material:
        raise HTTPException(status_code=404, detail="材料不存在")
    material.status = "uploaded"
    material.parse_error = ""
    db.commit()
    background.add_task(_parse_in_background, material.id)
    return material_out(material)


@router.delete("/api/materials/{material_id}", status_code=204)
def delete_material(
    material_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> None:
    """删材料时，连它抽出来的草稿需求一起删。

    保留两类人工痕迹：已确认的需求（人工基线）、人工改过或忽略的要点。
    Requirement.source_material_id 是 ondelete=SET NULL，材料没了以后这些记录
    靠 source_material_name 仍能说清出处，所以不需要跟着材料消失。
    """
    material = db.get(Material, material_id)
    if not material:
        raise HTTPException(status_code=404, detail="材料不存在")
    storage_path = Path(material.storage_path)
    project = db.get(Project, material.project_id)

    drafts = (
        db.execute(
            select(Requirement).where(
                Requirement.source_material_id == material.id,
                Requirement.status == "draft",
            )
        )
        .scalars()
        .all()
    )
    for item in drafts:
        db.delete(item)

    if project and project.highlights:
        project.highlights = [
            fact
            for fact in project.highlights
            if not (
                isinstance(fact, dict)
                and fact.get("source_material_name") == material.filename
                and not (fact.get("edited") or fact.get("ignored"))
            )
        ]

    db.delete(material)
    db.commit()
    if storage_path.exists():
        storage_path.unlink(missing_ok=True)


@router.get("/api/materials/{material_id}/preview")
def preview_material(
    material_id: int,
    page: int | None = Query(default=None),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    material = db.get(Material, material_id)
    if not material:
        raise HTTPException(status_code=404, detail="材料不存在")
    query = select(MaterialChunk).where(MaterialChunk.material_id == material_id)
    if page:
        query = query.where(MaterialChunk.page == page)
    chunks = db.execute(query.order_by(MaterialChunk.order_index)).scalars().all()
    return {
        "material": material_out(material),
        "markdown": material.markdown if page is None else "",
        "chunks": [
            {"id": item.id, "page": item.page, "heading": item.heading, "text": item.text}
            for item in chunks
        ],
    }
