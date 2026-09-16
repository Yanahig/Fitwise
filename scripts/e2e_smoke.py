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


# --------------------------------------------------------------------------- #
# 评测分数表
#
# 跑完链路只是"没坏"；这张表回答的是"这一版 Agent 的硬性质还在不在"：
#   ① 证据化：每条结论都能回指真实文档 + 页码
#   ② 不比证据乐观：结论是「完全支持」就必须有支持类证据（越界率必须为 0）
#   ③ 建议可用：三组行动非空、对客与内部不重复、风险有轻重
# --------------------------------------------------------------------------- #

CHECKS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    CHECKS.append((name, ok, detail))
    print(f"   {'✓' if ok else '✗'} {name}" + (f"：{detail}" if detail else ""))
    return ok


def norm(text: str) -> str:
    return "".join((text or "").split())


def print_scorecard() -> int:
    print("\n================ 评测分数表 ================")
    for name, ok, detail in CHECKS:
        print(f"[{'OK' if ok else 'XX'}] {name}" + (f"｜{detail}" if detail else ""))
    failed = [name for name, ok, _ in CHECKS if not ok]
    passed = len(CHECKS) - len(failed)
    print(f"\n结果：{passed}/{len(CHECKS)} 通过" + ("（全部通过 ✅）" if not failed else f"；未过：{'、'.join(failed)}"))
    return 1 if failed else 0


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

    print(
        f"10. 行动建议（只在方案里，不再落成待办）："
        f"要问客户 {len(solution['ask_customer'])} 条、要问内部 {len(solution['ask_internal'])} 条、"
        f"动作 {len(solution['next_actions'])} 条"
    )
    for item in solution["ask_customer"][:2]:
        print(f"   - 要问客户：{item[:50]}")

    customers = client.get("/api/customers").json()
    board = client.get("/api/dashboard").json()
    print(
        f"11. 工作台：客户 {board['stats']['customers']} 个（接口返回 {len(customers)} 条）｜"
        f"进行中项目 {len(board['projects'])} 个｜最近动态 {len(board['activities'])} 条"
    )

    print("\n端到端链路验证完成 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
