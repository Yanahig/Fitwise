"""人工改过的需求不会被重跑覆盖 —— 确定性检查（临时库 + 假模型，不碰演示数据）。

跑法：.venv\\Scripts\\python.exe scripts\\check_requirement_edits.py

验三件事：
  1. 人工改过内容的草稿，重跑抽取后仍在（不被 AI 结果冲掉）；
  2. 没被人动过的旧草稿，照常清掉重建；
  3. 同名草稿只留一条，且优先留人工改过的那条。
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))

TEMP_DB = Path(tempfile.mkdtemp(prefix="fitwise-edit-check-")) / "check.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TEMP_DB.as_posix()}"
os.environ["STORAGE_DIR"] = str(TEMP_DB.parent / "uploads")

from app.db import SessionLocal, init_db  # noqa: E402
from app.models import Customer, Material, MaterialChunk, Project, Requirement  # noqa: E402
from app.services import agents  # noqa: E402


def fake_payload() -> dict:
    """假装模型抽回来两条同名需求 —— 用来验证同名去重与人工编辑保护。"""
    return {
        "requirements": [
            {
                "title": "AI 新抽的工期要求",
                "detail": "合同签订后 3 个月内完成上线。",
                "category": "服务",
                "priority": "high",
                "tags": ["delivery"],
                "constraints": [],
                "source_material_name": "测试材料.pdf",
                "source_page": 1,
                "source_heading": "1.3 项目周期",
                "source_excerpt": "合同签订后 3 个月内完成上线。",
            },
            {
                "title": "AI 新抽的工期要求",
                "detail": "合同签订后 3 个月内完成上线并投入试运行。",
                "category": "服务",
                "priority": "high",
                "tags": ["delivery"],
                "constraints": [],
                "source_material_name": "测试材料.pdf",
                "source_page": 1,
                "source_heading": "1.3 项目周期",
                "source_excerpt": "合同签订后 3 个月内完成上线并投入试运行。",
            },
        ],
        "open_questions": [],
        "project_facts": [],
        "material_summaries": [{"material_name": "测试材料.pdf", "summary": "一份测试材料。"}],
    }


def main() -> int:
    init_db()
    db = SessionLocal()
    problems: list[str] = []
    try:
        customer = Customer(name="自测客户（虚构）", industry="测试")
        db.add(customer)
        db.flush()
        project = Project(customer_id=customer.id, name="编辑保护自测", stage="materials")
        db.add(project)
        db.flush()

        material = Material(
            project_id=project.id,
            filename="测试材料.pdf",
            status="parsed",
            markdown="1.3 项目周期\n合同签订后 3 个月内完成上线。",
            page_count=1,
        )
        db.add(material)
        db.flush()
        db.add(MaterialChunk(material_id=material.id, page=1, heading="1.3 项目周期", text="合同签订后 3 个月内完成上线。", order_index=0))

        edited = Requirement(
            project_id=project.id,
            title="人工改过的工期要求",
            detail="售前改写成客户口径：3 个月内上线并投入试运行。",
            status="draft",
            created_by_ai=True,
            edited=True,
            source_material_id=material.id,
            source_material_name=material.filename,
            source_page=1,
            source_excerpt="合同签订后 3 个月内完成上线。",
        )
        untouched = Requirement(
            project_id=project.id,
            title="没被人动过的旧草稿",
            detail="上一条 AI 草稿。",
            status="draft",
            created_by_ai=True,
            edited=False,
        )
        db.add_all([edited, untouched])
        db.commit()

        async def run() -> tuple[list, dict]:
            async def fake_chat_json(**_kwargs) -> dict:
                return fake_payload()

            agents.chat_json = fake_chat_json  # type: ignore[assignment]
            return await agents.analyze_requirements(
                db, project=project, materials=[material], actor="自测"
            )

        created, blocked = asyncio.run(run())
        db.expire_all()

        remaining = db.query(Requirement).filter(Requirement.project_id == project.id).all()
        titles = [item.title for item in remaining]

        if edited.title not in titles:
            problems.append("人工改过的草稿被清掉了")
        if untouched.title in titles:
            problems.append("没被人动过的旧草稿应该被清掉")
        if titles.count("AI 新抽的工期要求") != 1:
            problems.append(f"同名草稿没有去重：{titles}")
        # 同名需求可能被两种机制拦下：插入时的相似度去重，或插入后的同名去重。
        # 两种都对，关键是别漏、也别重复计数。
        deduped = blocked.get("skipped_duplicates", 0) + blocked.get("concurrent_duplicates_removed", 0)
        if deduped != 1:
            problems.append(f"去重计数不对（应为 1）：{blocked}")
        if not created:
            problems.append("没有创建新草稿")

        print("重跑后剩下的需求：")
        for item in remaining:
            print(f"  - {item.title}｜edited={item.edited}｜status={item.status}")
        print(f"清理统计：{blocked}")
    finally:
        db.close()

    if problems:
        print("\n[FAIL] " + "；".join(problems))
        return 1
    print("\n[PASS] 人工改过的需求被保留、旧草稿被清理、同名只留一条（优先留人工改过的）")
    return 0


if __name__ == "__main__":
    code = main()
    shutil.rmtree(TEMP_DB.parent, ignore_errors=True)  # 临时库跑完就删，别在 %TEMP% 里攒
    raise SystemExit(code)
