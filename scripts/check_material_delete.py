"""删除材料的连带规则：草稿需求跟着材料走，人工痕迹（已确认需求、人工改过的要点）留下。

对着**数据库副本**跑，不碰 server/data/fitwise.db：

    .venv\\Scripts\\python.exe scripts\\check_material_delete.py

脚本自己把库复制到临时目录，并把这份材料的 storage_path 改成临时路径，
所以既不会改动真实数据，也不会删掉真实的上传文件。
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
SERVER_DIR = ROOT / "server"
sys.path.insert(0, str(SERVER_DIR))

workdir = Path(tempfile.mkdtemp(prefix="fitwise-delete-check-"))
db_copy = workdir / "fitwise-test.db"
source_db = SERVER_DIR / "data" / "fitwise.db"
if not source_db.exists():
    print("RESULT: SKIP - no dev database found")
    raise SystemExit(0)
shutil.copy2(source_db, db_copy)

os.environ["DATABASE_URL"] = f"sqlite:///{db_copy.as_posix()}"
os.environ["STORAGE_DIR"] = str(workdir / "uploads")

from sqlalchemy import func, select  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.models import Material, MaterialChunk, Project, Requirement  # noqa: E402
from app.routers.materials import delete_material  # noqa: E402


def main() -> int:
    db = SessionLocal()
    try:
        material = db.execute(select(Material).order_by(Material.id)).scalars().first()
        if material is None:
            print("RESULT: SKIP - database has no materials")
            return 0

        material_id = material.id
        filename = material.filename
        project_id = material.project_id
        # Safety: never unlink the real upload
        material.storage_path = str(workdir / "uploads" / "not-here.pdf")
        db.commit()

        def snapshot() -> dict:
            requirements = (
                db.execute(select(Requirement).where(Requirement.project_id == project_id))
                .scalars()
                .all()
            )
            mine = [item for item in requirements if item.source_material_id == material_id]
            # 材料删掉后 source_material_id 会被 FK 置成 NULL，所以「谁留下的」
            # 只能用 source_material_name 来数：它才是删除后仍成立的证据。
            by_name = [
                item
                for item in requirements
                if item.source_material_name == filename and item.status == "confirmed"
            ]
            project = db.get(Project, project_id)
            facts = [
                item
                for item in (project.highlights or [])
                if isinstance(item, dict) and item.get("source_material_name") == filename
            ]
            chunks = db.execute(
                select(func.count())
                .select_from(MaterialChunk)
                .where(MaterialChunk.material_id == material_id)
            ).scalar_one()
            return {
                "material_exists": db.get(Material, material_id) is not None,
                "chunks": chunks,
                "project_requirements": len(requirements),
                "this_material_drafts": len([i for i in mine if i.status == "draft"]),
                "this_material_confirmed": len([i for i in mine if i.status == "confirmed"]),
                "confirmed_requirements_by_name": len(by_name),
                "this_material_facts": len(facts),
                "this_material_facts_touched_by_human": len(
                    [i for i in facts if i.get("edited") or i.get("ignored")]
                ),
            }

        before = snapshot()
        delete_material(material_id, db=db, _=None)
        after = snapshot()

        print(f"material: #{material_id} {filename}")
        print(f"before: {before}")
        print(f"after:  {after}")

        problems: list[str] = []
        if after["material_exists"]:
            problems.append("material row survived")
        if after["chunks"]:
            problems.append("material chunks survived")
        if after["this_material_drafts"]:
            problems.append("draft requirements survived")
        expected_total = before["project_requirements"] - before["this_material_drafts"]
        if after["project_requirements"] != expected_total:
            problems.append(
                f"requirement count wrong: expected {expected_total}, got {after['project_requirements']}"
            )
        if after["confirmed_requirements_by_name"] != before["confirmed_requirements_by_name"]:
            problems.append("confirmed requirements were deleted")
        if after["this_material_facts"] != before["this_material_facts_touched_by_human"]:
            problems.append("untouched facts survived (or touched facts were lost)")

        if problems:
            print("RESULT: FAIL - " + "; ".join(problems))
            return 1
        print("RESULT: PASS - drafts removed with the material, confirmed + human-touched facts kept")
        return 0
    finally:
        db.close()
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
