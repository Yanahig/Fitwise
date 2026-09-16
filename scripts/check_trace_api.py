"""AI 调用账本的验收脚本（对着某个实例跑）：

    $env:FITWISE_BASE="http://127.0.0.1:8021"
    .venv\\Scripts\\python.exe scripts\\check_trace_api.py

验收三件事（对应「成本」与「可观测」两条工程要求）：

1. 按项目能看到调用汇总：次数、token、失败、回退、按步骤分组；
2. 按 trace 能复盘一次运行：解析 / 抽取 / 判断 / 建议都在同一条链上；
3. 账本与业务对得上：判断次数不少于已确认需求条数（逐条判断，一条一次调用）。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))

from scorecard import print_scorecard, check  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = os.environ.get("FITWISE_BASE", "http://127.0.0.1:8000")


def main() -> int:
    client = httpx.Client(base_url=BASE, timeout=60)
    login = client.post(
        "/api/auth/login", json={"email": "presales@fitwise.local", "password": "fitwise123"}
    )
    login.raise_for_status()
    client.headers["Authorization"] = f"Bearer {login.json()['token']}"
    project_id = client.get("/api/projects").json()[0]["id"]
    print(f"instance: {BASE} · project #{project_id}")

    summary = client.get(f"/api/projects/{project_id}/ai-calls").json()
    totals = summary["totals"]
    steps = {row["step"]: row for row in summary["by_step"]}
    print(
        "1. 项目汇总：调用 {calls} 次｜失败 {failed}｜回退 {fallback}｜"
        "token {total_tokens}｜平均 {avg_latency_ms} ms".format(**totals)
    )
    step_line = "、".join(f"{name}×{row['calls']}" for name, row in steps.items())
    print(f"   按步骤：{step_line}")
    print(f"   当前提示词版本：{summary.get('prompt_set_version')}｜{summary.get('prompt_versions')}")

    check("账本有记录", totals["calls"] > 0, f"calls={totals['calls']}")
    check("知道贵在哪一步（按步骤分组）", len(steps) >= 2, f"steps={list(steps)}")
    check("覆盖到解析与判断两步", "parse" in steps and "judge" in steps)
    check("token 有数（不是只记次数）", totals["total_tokens"] > 0, f"tokens={totals['total_tokens']}")
    check("提示词版本可查", bool(summary.get("prompt_versions")))

    # 逐条判断：判断步的调用次数应该 ≥ 已确认需求条数
    requirements = client.get(f"/api/projects/{project_id}/requirements").json()["requirements"]
    confirmed = [item for item in requirements if item["status"] == "confirmed"]
    judge_calls = steps.get("judge", {}).get("calls", 0)
    check(
        "判断次数与业务对得上（每条需求一次调用）",
        judge_calls >= len(confirmed),
        f"judge 调用 {judge_calls} 次｜已确认需求 {len(confirmed)} 条",
    )

    # 一次提问的 trace 只有 1 次调用，这很正常；要找的是「一条链路」那种运行：
    # 解析 + 抽取，或者一次能力判断（逐条判断都在同一个 trace 下）。
    pipeline = None
    for item in summary["items"][:20]:
        trace = client.get(f"/api/traces/{item['trace_id']}").json()
        if len(trace["calls"]) >= 2:
            pipeline = trace
            break

    if pipeline:
        chain = [f"{item['step']}({item['model']})" for item in pipeline["calls"]]
        print(f"2. 一次运行 trace={pipeline['trace_id']}：{len(pipeline['calls'])} 次调用")
        print(f"   链路：{' → '.join(chain[:8])}{' …' if len(chain) > 8 else ''}")
        print(
            "   合计：token {total_tokens}｜失败 {failed}｜回退 {fallback}｜最长 {latency_ms} ms".format(
                **pipeline["totals"]
            )
        )
    check(
        "按 trace 能复盘整条链路",
        pipeline is not None,
        f"calls={len(pipeline['calls']) if pipeline else 0}",
    )
    if pipeline:
        check(
            "每条调用都带模型与端点",
            all(item["model"] and item["provider"] for item in pipeline["calls"]),
        )
        check(
            "判断/抽取类调用都带提示词版本",
            all(
                item["prompt_version"]
                for item in pipeline["calls"]
                if item["step"] in {"extract", "judge", "solution", "route"}
            ),
        )

    return print_scorecard("AI 调用账本分数表")


if __name__ == "__main__":
    raise SystemExit(main())
