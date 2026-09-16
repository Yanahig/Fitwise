"""一次性演练脚本：在真机上把三大功能 + 右侧 Agent 完整走一遍，每一步把结果打出来。

跑法：
    .venv\\Scripts\\python.exe scripts\\tmp_rehearsal.py

它复用 demo_reset 里的等待逻辑（等材料读完、等自动整理稳定），
然后依次走：上传 → 抽取 → Agent 批准卡 → 确认需求 → 能力判断 → 售前建议。
跑完项目就"走完了"，要回到演示起点请再跑 scripts/demo_reset.py --purge --preload。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import demo_reset as dr  # noqa: E402  复用它的等待逻辑

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = "http://127.0.0.1:8000"


def wait_job(client: httpx.Client, job_id: str, label: str, timeout: int = 600) -> dict:
    started = time.time()
    last = ""
    while time.time() - started < timeout:
        job = client.get(f"/api/jobs/{job_id}").json()
        note = f"{job['status']} {job.get('done')}/{job.get('total')} {job.get('current') or ''}".strip()
        if note != last:
            print(f"    [{label}] {note}")
            last = note
        if job["status"] in ("done", "failed"):
            return job
        time.sleep(2)
    return {"status": "timeout"}


def main() -> int:
    client = httpx.Client(base_url=BASE, timeout=300)
    login = client.post(
        "/api/auth/login", json={"email": "presales@fitwise.local", "password": "fitwise123"}
    )
    login.raise_for_status()
    client.headers["Authorization"] = f"Bearer {login.json()['token']}"

    project = client.get("/api/projects").json()[0]
    pid = project["id"]
    print(f"[0] 项目 #{pid}｜{project['customer_name']} · {project['name']}")
    print(f"    起始状态：材料 {project['counts']['materials']} 份｜需求 {project['counts']['requirements']} 条")

    # ---------- 1. 材料解析（按演示剧本：先需求书，再答疑） ----------
    files = sorted((ROOT / "demo").glob("*.pdf"))
    for path in files:
        with path.open("rb") as handle:
            upload = client.post(
                f"/api/projects/{pid}/materials",
                files={"file": (path.name, handle, "application/pdf")},
            )
        upload.raise_for_status()
        material = dr.wait_material(client, pid, upload.json()["id"])
        if not material or material["status"] != "parsed":
            print(f"[1] ✗ {path.name} 没读出来：{(material or {}).get('parse_error', '未知')}")
            return 1
        print(
            f"[1] 上传 {path.name} → {material['status']}｜{material['page_count']} 页｜"
            f"{material.get('parse_engine') or '—'}"
        )

    requirements, highlights = dr.wait_settled(client, pid, expected_extractions=len(files))
    materials = client.get(f"/api/projects/{pid}/materials").json()
    print(f"[1] 材料清单：{len(materials)} 份")
    for item in materials:
        print(f"    - {item['filename']}｜{item['page_count']} 页｜{item.get('summary') or '（无摘要）'}")

    # ---------- 2. 需求确认 ----------
    payload = client.get(f"/api/projects/{pid}/requirements").json()
    drafts = [item for item in payload["requirements"] if item["status"] == "draft"]
    confirmed = [item for item in payload["requirements"] if item["status"] == "confirmed"]
    print(f"[2] 自动整理出 {len(drafts)} 条待确认需求（已确认 {len(confirmed)} 条）")
    for item in drafts:
        print(
            f"    - [{item['priority']}] {item['title']}｜{item['category']}｜"
            f"{item.get('source', {}).get('document_name', '')[:18]} P{item.get('source', {}).get('page')}"
        )

    questions = payload.get("open_questions") or []
    print(f"[2] 待澄清问题 {len(questions)} 条")
    for item in questions:
        print(f"    - [{item.get('owner') or '客户'}] {item['question'][:56]}")

    facts = [item for item in highlights if isinstance(item, dict)]
    print(f"[2] 项目要点 {len(facts)} 条")
    timeline = [item for item in facts if str(item.get("label")) == "工期口径"]
    for item in timeline:
        print(f"    - 工期口径｜{str(item.get('value'))[:52]}")
    if len(timeline) >= 2:
        print("    ✓ 两份材料的工期口径冲突被抓住了")

    # ---------- 3. Agent 批准卡 → 确认需求 → 能力判断 ----------
    reply = client.post(
        f"/api/projects/{pid}/agent/ask", json={"message": "帮我确认这些需求"}
    ).json()
    approval = reply.get("approval") or {}
    ids = (approval.get("payload") or {}).get("ids") or []
    print(f"[3] Agent：kind={reply['kind']}｜{approval.get('detail', '')[:60]}")
    if reply["kind"] != "approval":
        print("    ✗ 没有走批准卡，后面就没法继续验")
        return 1

    card = client.post(
        f"/api/projects/{pid}/agent/messages",
        json={"role": "tool", "kind": "approval", "text": reply["text"], "data": {"approval": approval}},
    ).json()
    decided = client.post(
        f"/api/projects/{pid}/agent/approvals",
        json={"message_id": card["id"], "decision": "approved"},
    ).json()
    trace = (decided.get("data") or {}).get("approval") or {}
    print(f"    留痕：decision={trace.get('decision')} by={trace.get('by')} at={'有' if trace.get('at') else '无'}")

    confirmed_result = client.post(f"/api/projects/{pid}/requirements/confirm", json={"ids": ids}).json()
    print(f"[3] 确认 {confirmed_result['confirmed']} 条需求，基线已更新")
    if confirmed_result.get("job_id"):
        job = wait_job(client, confirmed_result["job_id"], "能力判断")
        print(f"    判断任务：{job['status']}｜{job.get('message', '')}")

    matches = client.get(f"/api/projects/{pid}/matches").json()
    counts: dict[str, int] = {}
    for item in matches:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    print(f"[3] 判断结果 {len(matches)} 条：{counts}")
    for item in sorted(matches, key=lambda row: row["status"]):
        print(f"    - [{item['status']}] {item['requirement']['title'][:28]}｜{item['headline'][:44]}")

    # ---------- 4. 售前建议 ----------
    solution_job = client.post(f"/api/projects/{pid}/solutions/generate", json={"problem": ""}).json()
    finished = wait_job(client, solution_job["job_id"], "售前建议")
    print(f"[4] 建议任务：{finished['status']}")
    project = client.get(f"/api/projects/{pid}").json()
    solution = project.get("solution") or {}
    print(f"[4] 结论：{project['summary'] or solution.get('summary', '')[:80]}")
    risks = solution.get("risks") or []
    by_level: dict[str, int] = {}
    for item in risks:
        by_level[item["level"]] = by_level.get(item["level"], 0) + 1
    with_ids = len([item for item in risks if (item.get("requirement_ids") or [])])
    print(f"    风险 {len(risks)} 条：{by_level}｜能回指需求 {with_ids}/{len(risks)}")
    print(f"    要问客户 {len(solution.get('ask_customer') or [])} 条｜"
          f"要问内部 {len(solution.get('ask_internal') or [])} 条｜"
          f"动作 {len(solution.get('next_actions') or [])} 条")
    for item in (solution.get("ask_customer") or [])[:3]:
        print(f"    - 要问客户：{str(item)[:52]}")

    project = client.get(f"/api/projects/{pid}").json()
    print(f"[5] 终态：{project['counts']}")
    print("\n演练完成 ✅（要回到演示起点：scripts\\demo_reset.py --purge --preload）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
