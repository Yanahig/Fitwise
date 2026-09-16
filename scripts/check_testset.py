"""效果评测：拿固定题库跑一遍，输出抽全率、越界率、证据覆盖、结论分布与成本。

链路回归（regression_check）回答的是「有没有坏」；这个脚本回答的是「好不好」。
题库材料与答题卡在 scripts/testset/（用 scripts/make_testset_materials.py 生成）。

跑法：
    # 推荐：在回归沙箱里跑，不碰演示数据
    $env:FITWISE_SANDBOX_PORT="8023"
    .venv\\Scripts\\python.exe scripts\\regression_check.py --testset

    # 也可以对着已经在跑的沙箱单独跑，只跑其中几份
    $env:FITWISE_BASE="http://127.0.0.1:8023"
    .venv\\Scripts\\python.exe scripts\\check_testset.py --only 01,05

它会给每份材料建一个独立项目、走完整链路（上传 → 解析 → 抽需求 → 确认 → 能力判断），
然后对着答题卡算四个数：

    抽全率   材料里该被读出来的关键信息，读出来了几成（阈值 80%）
    越界率   「我们做不了」的条目被误判成完全支持的条数（阈值 0）
    证据覆盖 有来源页码的需求占比（阈值 100%）
    噪音     需求条数落在答题卡给的区间内（防止抽出一堆无关内容）
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

import demo_reset as dr  # noqa: E402  复用它的等待逻辑（等材料读完、等自动整理稳定）
from scorecard import check, norm, print_scorecard  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TEST_DIR = ROOT / "scripts" / "testset"
EXPECTED = TEST_DIR / "expected.json"
BASE = os.environ.get("FITWISE_BASE", "http://127.0.0.1:8010")

EXTRACT_TIMEOUT = 420
MATCH_TIMEOUT = 900
PARSE_TIMEOUT = 300


def wait_job(client: httpx.Client, job_id: str, label: str, timeout: int) -> dict:
    started = time.time()
    last = ""
    while time.time() - started < timeout:
        job = client.get(f"/api/jobs/{job_id}").json()
        note = f"{job['status']} {job.get('done')}/{job.get('total')}"
        if note != last:
            print(f"      [{label}] {note}")
            last = note
        if job["status"] in ("done", "failed"):
            return job
        time.sleep(2)
    return {"status": "timeout", "error": f"{label} 超时"}


def ensure_customer(client: httpx.Client) -> int:
    """题库用的客户单独建一个：不混进演示客户，也不受演示数据清理影响。"""
    for item in client.get("/api/customers").json():
        if item["name"] == "效果评测客户":
            return item["id"]
    created = client.post(
        "/api/customers",
        json={"name": "效果评测客户", "industry": "效果评测", "owner_name": "Fitwise"},
    ).json()
    return created["id"]


def upload(client: httpx.Client, project_id: int, path: Path) -> dict:
    mime = "text/plain" if path.suffix.lower() == ".txt" else "application/pdf"
    with path.open("rb") as handle:
        response = client.post(
            f"/api/projects/{project_id}/materials",
            files={"file": (path.name, handle, mime)},
        )
    response.raise_for_status()
    return response.json()


def run_material(client: httpx.Client, spec: dict, customer_id: int) -> dict:
    """一份材料 = 一个独立项目，走完整链路，把评分需要的原始数据都取回来。"""
    path = TEST_DIR / spec["file"]
    if not path.exists():
        raise FileNotFoundError(f"题库缺文件：{path}（先跑 scripts/make_testset_materials.py）")

    project = client.post(
        "/api/projects",
        json={"customer_id": customer_id, "name": spec["project_name"]},
    ).json()
    project_id = project["id"]
    print(f"   项目 #{project_id}｜{spec['project_name']}")

    material = upload(client, project_id, path)
    material = dr.wait_material(client, project_id, material["id"], timeout=PARSE_TIMEOUT) or {}
    status = material.get("status", "timeout")
    print(f"   解析：{status}｜{material.get('page_count', 0)} 页｜{material.get('parse_error', '')[:80]}")

    result: dict = {
        "spec": spec,
        "project_id": project_id,
        "material": material,
        "parse_status": status,
        "requirements": [],
        "highlights": [],
        "matches": [],
        "chunks": [],
        "ledger": {},
        "elapsed": 0,
    }
    if status != "parsed":
        return result

    started = time.time()
    requirements, highlights = dr.wait_settled(client, project_id, expected_extractions=1, timeout=EXTRACT_TIMEOUT)
    result["requirements"] = requirements
    result["highlights"] = highlights
    result["chunks"] = client.get(f"/api/materials/{material['id']}/preview").json().get("chunks", [])

    drafts = [item["id"] for item in requirements if item["status"] == "draft"]
    if drafts:
        confirmed = client.post(
            f"/api/projects/{project_id}/requirements/confirm", json={"ids": drafts}
        ).json()
        job = wait_job(client, confirmed["job_id"], "能力判断", MATCH_TIMEOUT)
        if job["status"] != "done":
            print(f"   ⚠ 能力判断没跑完：{job.get('error')}")
    result["matches"] = client.get(f"/api/projects/{project_id}/matches").json()
    result["ledger"] = client.get(f"/api/projects/{project_id}/ai-calls").json()
    result["elapsed"] = int(time.time() - started)
    return result


def score_material(result: dict) -> None:
    spec = result["spec"]
    tag = spec["file"].split("-")[0]
    expect = spec["expect_parse"]
    status = result["parse_status"]
    requirements = result["requirements"]
    matches = result["matches"]

    # ① 解析结果符合预期（允许 parsed|failed 的是"读得出来算过、读不出来要明说"）
    parse_ok = status in expect.split("|")
    detail = status if not result["material"].get("parse_error") else f"{status}｜{result['material']['parse_error'][:60]}"
    check(f"{tag} 解析结果符合预期（{expect}）", parse_ok, detail)

    # ② 不许静默产出空内容：要么有带页码的片段，要么明确失败并给成因
    if status == "parsed":
        chunks = result["chunks"]
        has_text = any((item.get("text") or "").strip() for item in chunks)
        has_page = any(item.get("page") for item in chunks)
        check(f"{tag} 读出来就有内容、有页码", has_text and has_page, f"片段 {len(chunks)} 条")
    else:
        error = result["material"].get("parse_error", "")
        check(
            f"{tag} 失败时给出成因码",
            error.startswith("[") and "]" in error,
            error[:40] or "（没有写明原因）",
        )

    if status != "parsed":
        return

    # ③ 抽全率：关键信息落成「需求」或「项目要点」都算读出来了
    texts = [norm(f"{item['title']}{item['detail']}") for item in requirements]
    texts += [norm(f"{item.get('label', '')}{item.get('value', '')}") for item in result["highlights"]]
    must = spec.get("must_extract") or []
    hits = [word for word in must if any(norm(word) in text for text in texts)]
    if must:
        rate = len(hits) / len(must)
        missing = [word for word in must if word not in hits]
        check(
            f"{tag} 抽全率 ≥ 80%",
            rate >= 0.8,
            f"{len(hits)}/{len(must)}（漏：{'、'.join(missing) or '无'}）",
        )

    # ④ 越界率：能力库没有证据的条目不许判「完全支持」
    forbidden = spec.get("must_not_full_support") or []
    violations = []
    for match in matches:
        requirement = match.get("requirement") or {}
        text = norm(f"{requirement.get('title', '')}{requirement.get('detail', '')}")
        if match.get("status") == "full" and any(norm(word) in text for word in forbidden):
            violations.append(requirement.get("title", "?"))
    check(f"{tag} 越界率 = 0（不比证据乐观）", not violations, f"越界：{'、'.join(violations) or '无'}")

    # ⑤ 证据覆盖：每条需求都要能点回原文页码
    missing_page = [item["title"] for item in requirements if not (item.get("source") or {}).get("page")]
    check(
        f"{tag} 证据覆盖 100%（每条需求都有来源页码）",
        not missing_page,
        f"缺页码：{len(missing_page)} 条",
    )

    # ⑥ 噪音：需求条数要落在答题卡给的区间内
    low, high = spec.get("min_requirements", 0), spec.get("max_requirements", 99)
    count = len(requirements)
    check(f"{tag} 需求条数在 {low}–{high} 之间", low <= count <= high, f"实际 {count} 条")

    counts: dict[str, int] = {}
    for match in matches:
        counts[match["status"]] = counts.get(match["status"], 0) + 1
    totals = (result["ledger"].get("totals") or {})
    print(
        f"   结论分布：{counts or '（无判断）'}｜需求 {count} 条｜用时 {result['elapsed']}s｜"
        f"调用 {totals.get('calls', 0)} 次｜token {totals.get('total_tokens', 0)}"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", default="", help="只跑指定编号，例如 01,05")
    parser.add_argument("--allow-prod", action="store_true", help="允许对着 8000 的实例跑（会往库里建项目）")
    parser.add_argument(
        "--verify-red",
        action="store_true",
        help="自检：故意把答题卡改坏（加一条必漏的关键词、把「完全支持」的条目列进越界名单），确认分数表会变红",
    )
    args = parser.parse_args()

    if ":8000" in BASE and not args.allow_prod:
        print(
            "这个脚本会在库里新建项目并上传材料，默认不允许对着 8000 的演示实例跑。\n"
            "请用回归沙箱：$env:FITWISE_SANDBOX_PORT=\"8023\"; "
            ".venv\\Scripts\\python.exe scripts\\regression_check.py --testset"
        )
        return 1
    if not EXPECTED.exists():
        print(f"缺答题卡 {EXPECTED}，先跑 scripts/make_testset_materials.py")
        return 1

    import json

    expected = json.loads(EXPECTED.read_text(encoding="utf-8"))
    wanted = {item.strip() for item in args.only.split(",") if item.strip()}
    specs = [
        spec for spec in expected["materials"] if not wanted or spec["file"].split("-")[0] in wanted
    ]
    if args.verify_red:
        print("【自检模式】故意把答题卡改坏，预期分数表出现红叉（用来证明这套评测能判红）\n")
        for spec in specs:
            spec["must_extract"] = list(spec.get("must_extract") or []) + ["一定读不出来的关键词XYZ"]
            spec["must_not_full_support"] = list(spec.get("must_not_full_support") or []) + ["部署"]

    client = httpx.Client(base_url=BASE, timeout=300)
    login = client.post(
        "/api/auth/login", json={"email": "presales@fitwise.local", "password": "fitwise123"}
    )
    login.raise_for_status()
    client.headers["Authorization"] = f"Bearer {login.json()['token']}"
    print(f"instance: {BASE}｜题库版本 {expected['version']}｜材料 {len(specs)} 份\n")

    customer_id = ensure_customer(client)
    for spec in specs:
        print(f"--- {spec['file']}｜{spec['notes']}")
        try:
            result = run_material(client, spec, customer_id)
        except Exception as error:  # noqa: BLE001 - 单份材料出错不该打断整轮评测
            check(f"{spec['file'].split('-')[0]} 跑完链路", False, str(error)[:80])
            continue
        score_material(result)
        print("")

    code = print_scorecard("效果评测分数表（题库）")
    if args.verify_red:
        if code == 1:
            print("\n[自检通过] 故意改坏后分数表确实变红 —— 这套评测能判红，不是摆设。")
            return 0
        print("\n[自检失败] 故意改坏后仍然全绿：说明断言没生效，得先修评测本身。")
        return 1
    return code


if __name__ == "__main__":
    raise SystemExit(main())
