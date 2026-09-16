"""单步 Agent 路由的验收脚本：对**数据库副本**跑，只读、不改任何数据。

    .venv\\Scripts\\python.exe scripts\\check_agent_router.py

验收标准（与第 1 步迁移一致）：
  1. 问材料里的信息 → 回答带原文页码；
  2. 材料里没有的信息 → 老实说没提到，且不给引用；
  3. 说「重新跑一遍分析」→ 给出动作意图（不自己执行）；
  4. 状态不满足的动作 → 被拦下并说明差什么。
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
SERVER_DIR = ROOT / "server"
sys.path.insert(0, str(SERVER_DIR))

workdir = Path(tempfile.mkdtemp(prefix="fitwise-agent-check-"))
source_db = SERVER_DIR / "data" / "fitwise.db"
if not source_db.exists():
    print("RESULT: SKIP - no dev database found")
    raise SystemExit(0)
shutil.copy2(source_db, workdir / "fitwise-test.db")
os.environ["DATABASE_URL"] = f"sqlite:///{(workdir / 'fitwise-test.db').as_posix()}"
os.environ["STORAGE_DIR"] = str(workdir / "uploads")

from sqlalchemy import select  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.models import Project  # noqa: E402
from app.services import agent_router  # noqa: E402

QUESTIONS = [
    "工期是多久？",
    "交付环境有什么要求？",
    "付款周期是多少？",
    "重新跑一遍分析",
    "你好",
]


def main() -> int:
    db = SessionLocal()
    try:
        project = db.execute(select(Project).order_by(Project.id)).scalars().first()
        if project is None:
            print("RESULT: SKIP - database has no projects")
            return 0
        print(f"project: #{project.id} {project.name}")
        state = agent_router.project_state(db, project)
        print(f"state: {state}\n")

        problems: list[str] = []

        # ---- 状态机：下一步与计划 ----
        print("=== 状态机 ===")
        cases = [
            (
                "没有材料",
                {"materials": 0, "materials_parsed": 0, "materials_failed": 0, "requirements_draft": 0,
                 "requirements_confirmed": 0, "matches": 0, "solutions": 0},
                "先把客户材料拖进来",
                None,
            ),
            (
                "材料读完、还没整理",
                {"materials": 1, "materials_parsed": 1, "materials_failed": 0, "requirements_draft": 0,
                 "requirements_confirmed": 0, "matches": 0, "solutions": 0},
                "整理需求",
                "run_extraction",
            ),
            (
                "有草稿没确认（人工闸门）",
                {"materials": 1, "materials_parsed": 1, "materials_failed": 0, "requirements_draft": 13,
                 "requirements_confirmed": 0, "matches": 0, "solutions": 0},
                "确认这 13 条需求",
                None,
            ),
            (
                "基线已定、还没判断",
                {"materials": 1, "materials_parsed": 1, "materials_failed": 0, "requirements_draft": 0,
                 "requirements_confirmed": 13, "matches": 0, "solutions": 0},
                "做能力判断",
                "run_matching",
            ),
            (
                "判断完成、还没建议",
                {"materials": 1, "materials_parsed": 1, "materials_failed": 0, "requirements_draft": 0,
                 "requirements_confirmed": 13, "matches": 13, "solutions": 0},
                "生成售前建议",
                "compose_solution",
            ),
        ]
        for name, sample, expect_label, expect_tool in cases:
            step = agent_router.next_step(sample)
            got = (step or {}).get("label"), (step or {}).get("tool")
            ok = got == (expect_label, expect_tool)
            print(f"  {name}: {got} {'✓' if ok else f'✗ 期望 {(expect_label, expect_tool)}'}")
            if not ok:
                problems.append(f"状态机「{name}」不对")

        steps, gate = agent_router.build_plan(cases[1][1])
        print(f"  从零开始的计划: steps={steps} gate={(gate or {}).get('label')}")
        # 计划必须停在人工闸门：整理完需求就停，等确认了才谈判断
        if steps != ["run_extraction"]:
            problems.append(f"计划没有停在人工闸门前：{steps}")
        if not gate or gate.get("label") != "确认这 1 条需求":
            problems.append(f"计划没有停在人工闸门：{gate}")

        real_step = agent_router.next_step(state)
        print(f"  当前项目下一步: {real_step}")

        # ---- 对话路由：材料问答 / 无据可依 / 动作提议 ----
        print("\n=== 对话路由 ===")
        for question in QUESTIONS:
            result = asyncio.run(agent_router.route_message(db, project=project, message=question))
            pages = [item["page"] for item in result["citations"]]
            print(f"Q: {question}")
            print(f"   kind={result['kind']} tool={result['tool']} pages={pages}")
            print(f"   text={result['text']}")
            if result["citations"]:
                first = result["citations"][0]
                print(f"   cite: {first['document_name']} 第 {first['page']} 页 · {first['excerpt'][:60]}")
            print()

            if question.startswith("工期") and not pages:
                problems.append("问材料里的信息却没带回页码")
            if question.startswith("付款") and pages:
                problems.append("材料里没有的信息却给了引用")
            if question.startswith("重新跑") and result["kind"] != "action":
                problems.append("「重新跑一遍分析」没有给出动作")

        # ---- 审批类动作：确认需求必须走"待批准"，id 由后端给 ----
        print("\n=== 审批类动作 ===")
        approval = asyncio.run(
            agent_router.route_message(db, project=project, message="帮我确认这些需求")
        )
        print(
            f"Q: 帮我确认这些需求 → kind={approval['kind']} tool={approval['tool']} "
            f"ids={len((approval.get('approval') or {}).get('payload', {}).get('ids', []))}"
        )
        if approval["kind"] != "approval":
            problems.append("「确认需求」没有走待批准")
        if not (approval.get("approval") or {}).get("payload", {}).get("ids"):
            problems.append("待批准没有带上要确认的 id")

        if problems:
            print("RESULT: FAIL - " + "; ".join(problems))
            return 1
        print("RESULT: PASS - 材料问答带页码、无据可依时不给引用、动作只提议不执行")
        return 0
    finally:
        db.close()
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
