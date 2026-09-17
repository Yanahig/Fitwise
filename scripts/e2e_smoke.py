"""Fitwise 端到端冒烟测试：登录 → 上传 → 解析 → 需求抽取 → 能力匹配 → 解决路径 → 行动项。

用法（需先启动后端）：
    .venv\\Scripts\\python.exe scripts/e2e_smoke.py

默认打 http://127.0.0.1:8000；用 FITWISE_BASE 指向别的实例（回归沙箱就是靠这个复用本脚本）：
    $env:FITWISE_BASE="http://127.0.0.1:8010"

脚本会自动生成一份合成的中文 RFP 作为测试材料，不会上传任何真实客户资料。
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import difflib
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))

from scorecard import check, norm, print_scorecard  # noqa: E402

BASE = os.environ.get("FITWISE_BASE", "http://127.0.0.1:8000")
SCRIPT_DIR = Path(__file__).resolve().parent
RFP = SCRIPT_DIR / "test-rfp.pdf"


def ensure_rfp() -> None:
    """没有测试文件时现场生成一份合成 RFP。"""
    if RFP.exists():
        return
    subprocess.run([sys.executable, str(SCRIPT_DIR / "make_test_rfp.py")], check=True)


def wait_job(client: httpx.Client, job_id: str, label: str, timeout: int = 300) -> dict:
    started = time.time()
    last = ""
    while time.time() - started < timeout:
        job = client.get(f"/api/jobs/{job_id}").json()
        message = f"{job['status']} {job['done']}/{job['total']} {job.get('message') or ''}"
        if message != last:
            print(f"  [{label}] {message}")
            last = message
        if job["status"] in ("done", "failed"):
            return job
        time.sleep(2)
    raise TimeoutError(f"{label} 超时")


def _run() -> int:
    ensure_rfp()
    print(f"0. 目标实例：{BASE}")
    client = httpx.Client(base_url=BASE, timeout=180)

    login = client.post(
        "/api/auth/login", json={"email": "presales@fitwise.local", "password": "fitwise123"}
    )
    login.raise_for_status()
    user = login.json()["user"]
    client.headers["Authorization"] = f"Bearer {login.json()['token']}"
    print(f"1. 登录成功：{user['name']}（{user['role']}）")

    meta = client.get("/api/meta").json()
    print(
        f"2. 元信息：{len(meta['stages'])} 个阶段 | 解析器 {meta['integrations']['parser']['provider']}"
        f"（{len(meta['integrations']['parser']['formats'])} 种格式）| 模型 {meta['integrations']['llm']['model']}"
    )

    projects = client.get("/api/projects").json()
    project = projects[0]
    pid = project["id"]
    print(f"3. 项目：{project['name']}（{project['customer_name']}，阶段 {project['stage']}）")

    with RFP.open("rb") as handle:
        upload = client.post(
            f"/api/projects/{pid}/materials",
            files={"file": ("XX银行智能票据与档案处理平台RFP.pdf", handle, "application/pdf")},
        )
    upload.raise_for_status()
    material_id = upload.json()["id"]
    print(f"4. 上传材料：{upload.json()['filename']}（{upload.json()['size_bytes']} bytes）")

    material = None
    for _ in range(60):
        time.sleep(2)
        materials = client.get(f"/api/projects/{pid}/materials").json()
        material = next(item for item in materials if item["id"] == material_id)
        if material["status"] in ("parsed", "failed"):
            break
    assert material, "未获取到材料状态"
    print(
        f"5. 解析结果：{material['status']} | 引擎 {material['parse_engine']} | {material['page_count']} 页"
        + (f" | 错误 {material['parse_error'][:80]}" if material["parse_error"] else "")
    )
    if material["status"] != "parsed":
        return 1

    preview = client.get(f"/api/materials/{material_id}/preview").json()
    pages = sorted({chunk["page"] for chunk in preview["chunks"]})
    print(f"   页码索引：{pages}，首个片段 {preview['chunks'][0]['text'][:40]!r}")

    job = client.post(f"/api/projects/{pid}/requirements/extract").json()
    result = wait_job(client, job["job_id"], "需求抽取")
    if result["status"] != "done":
        print(f"抽取失败：{result['error']}")
        return 1

    payload = client.get(f"/api/projects/{pid}/requirements").json()
    requirements = payload["requirements"]
    print(f"6. 抽取需求 {len(requirements)} 条（待确认），示例：")
    for item in requirements[:5]:
        print(
            f"   - {item['title']}｜{item['category']}｜{item['priority']}｜"
            f"{item['source']['document_name']} P{item['source']['page']}"
        )

    # ① 抽取层：有产出、来源完整、没有把同一件事抽两遍
    check("抽取有产出", len(requirements) > 0, f"{len(requirements)} 条需求")
    missing_source = [
        item["title"]
        for item in requirements
        if not (item["source"].get("document_name") and item["source"].get("page"))
    ]
    check("每条需求都有来源页码", not missing_source, f"缺来源 {len(missing_source)} 条" if missing_source else "")
    seen: list[tuple[str, str]] = []
    duplicates = []
    for item in requirements:
        title, detail = norm(item["title"]), norm(item["detail"])
        if any(
            title == old_title
            or (len(title) >= 6 and len(old_title) >= 6 and (title in old_title or old_title in title))
            or len(detail) >= 12
            and len(old_detail) >= 12
            and difflib.SequenceMatcher(None, detail, old_detail).ratio() >= 0.72
            for old_title, old_detail in seen
        ):
            duplicates.append(item["title"])
        seen.append((title, detail))
    check("没有重复需求", not duplicates, f"重复：{'、'.join(duplicates[:3])}" if duplicates else "")

    confirm = client.post(f"/api/projects/{pid}/requirements/confirm", json={"ids": None})
    print(f"7. 人工确认基线：{confirm.json()['confirmed']} 条")

    job = client.post(f"/api/projects/{pid}/matches/run").json()
    result = wait_job(client, job["job_id"], "能力匹配")
    if result["status"] != "done":
        print(f"匹配失败：{result['error']}")
        return 1
    print(f"8. 匹配结果：{result['result']}")

    matches = client.get(f"/api/projects/{pid}/matches").json()
    details = []
    for item in matches[:5]:
        detail = client.get(f"/api/matches/{item['id']}").json()
        evidences = detail.get("evidences", [])
        print(
            f"   - {item['requirement']['title']} → {item['status']}｜{item['headline'][:40]}"
            f"｜证据 {len(evidences)} 条"
        )
        if evidences:
            first = evidences[-1]
            print(f"     依据：{first['document_name']} P{first['page']}｜{first['excerpt'][:50]}")

    # ② 判断层：结论不能比证据乐观 —— 这是这个产品最要紧的一条，必须每次回归都验
    for item in matches:
        details.append(client.get(f"/api/matches/{item['id']}").json())

    over_optimistic, no_evidence, no_page = [], [], []
    for detail in details:
        evidences = detail.get("evidences") or []
        capability = [row for row in evidences if row.get("source_type") == "capability"]
        status = detail["status"]
        if status == "full" and not capability:
            over_optimistic.append(detail["requirement"]["title"])
        if status != "unknown" and not evidences:
            no_evidence.append(detail["requirement"]["title"])
        if any(not row.get("page") for row in evidences):
            no_page.append(detail["requirement"]["title"])

    check(
        "越界检查：完全支持必须有支持证据",
        not over_optimistic,
        f"越界 {len(over_optimistic)} 条：{'、'.join(over_optimistic[:3])}" if over_optimistic else "0 条越界",
    )
    check(
        "非待补依据的结论都有证据",
        not no_evidence,
        f"无证据 {len(no_evidence)} 条：{'、'.join(no_evidence[:3])}" if no_evidence else "",
    )
    check("证据都能落到页码", not no_page, f"{len(no_page)} 条缺页码" if no_page else "")

    statuses: dict[str, int] = {}
    for detail in details:
        statuses[detail["status"]] = statuses.get(detail["status"], 0) + 1
    print(f"   结论分布：{statuses}")

    job = client.post(
        f"/api/projects/{pid}/solutions/generate",
        json={"problem": "客户要求私有化部署、多语言 OCR，同时要求处理特殊票据。"},
    ).json()
    result = wait_job(client, job["job_id"], "解决路径")
    if result["status"] != "done":
        print(f"生成失败：{result['error']}")
        return 1

    solution = client.get(f"/api/projects/{pid}/solutions").json()[0]
    print(f"9. 解决路径 v{solution['version']}：{solution['summary'][:80]}")
    print(f"   路径 {len(solution['steps'])} 步｜风险 {len(solution['risks'])} 条｜待确认 {len(solution['ask_customer']) + len(solution['ask_internal'])} 项")

    # 风险与行动要能回指依据：每条带 requirement_ids，读取时补上 judgment + evidence
    with_basis = [item for item in solution["risks"] if item.get("basis")]
    if with_basis:
        sample = with_basis[0]
        evidences = [
            f"{evidence['document_name']} P{evidence['page']}"
            for basis in sample["basis"]
            for evidence in basis["evidences"][:2]
        ]
        print(
            f"   风险依据链：{len(with_basis)}/{len(solution['risks'])} 条能回指｜"
            f"示例「{sample['title'][:24]}」→ {' / '.join(evidences[:3])}"
        )
    else:
        print("   风险依据链：✗ 没有任何风险挂上依据（_attach_requirement_ids 没生效）")
        return 1

    check(
        "风险都能回指判断与证据",
        len(with_basis) == len(solution["risks"]),
        f"{len(with_basis)}/{len(solution['risks'])} 条",
    )
    levels = {item["level"] for item in solution["risks"]}
    check("风险有轻重之分", "high" in levels, f"等级：{'、'.join(sorted(levels))}")

    print(
        f"10. 行动建议（只在方案里，不再落成待办）："
        f"要问客户 {len(solution['ask_customer'])} 条、要问内部 {len(solution['ask_internal'])} 条、"
        f"要同步销售 {len(solution['sync_sales'])} 条、动作 {len(solution['next_actions'])} 条"
    )
    for item in solution["ask_customer"][:2]:
        text = item["question"] if isinstance(item, dict) else str(item)
        print(f"   - 要问客户：{text[:50]}")

    # ③ 建议层：三组都要有东西，而且对客组不能混进内部问题
    check(
        "三组行动都非空",
        all([solution["ask_customer"], solution["ask_internal"], solution["sync_sales"]]),
        f"客户 {len(solution['ask_customer'])} / 内部 {len(solution['ask_internal'])} / "
        f"销售 {len(solution['sync_sales'])}",
    )
    merged = [item for item in solution["ask_customer"] if isinstance(item, dict)]
    check(
        "对客清单是合并过的（每条带 covers）",
        bool(merged) and len(merged) == len(solution["ask_customer"]) and all("covers" in item for item in merged),
        f"{len(merged)}/{len(solution['ask_customer'])} 条",
    )
    ask_customer_norm = {
        norm(item["question"] if isinstance(item, dict) else str(item)) for item in solution["ask_customer"]
    }
    ask_internal_norm = {norm(item.get("question", "")) for item in solution["ask_internal"]}
    overlap = ask_customer_norm & ask_internal_norm
    check("对客与内部问题不重复", not overlap, f"重复 {len(overlap)} 条" if overlap else "")
    with_to = [item for item in solution["sync_sales"] if item.get("to")]
    check(
        "要同步销售的每条都写了同步给谁",
        len(with_to) == len(solution["sync_sales"]),
        f"{len(with_to)}/{len(solution['sync_sales'])} 条",
    )

    customers = client.get("/api/customers").json()
    board = client.get("/api/dashboard").json()
    print(
        f"11. 工作台：客户 {board['stats']['customers']} 个（接口返回 {len(customers)} 条）｜"
        f"进行中项目 {len(board['projects'])} 个｜最近动态 {len(board['activities'])} 条"
    )

    return 0


def main() -> int:
    """跑链路 + 打分数表：链路中途失败也把已经跑出来的检查项列出来。"""
    try:
        code = _run()
    except Exception as error:  # noqa: BLE001
        check("脚本执行到结束", False, f"{type(error).__name__}: {str(error)[:80]}")
        code = 1
    failed = print_scorecard()
    return 1 if (code or failed) else 0


if __name__ == "__main__":
    sys.exit(main())
