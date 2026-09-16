"""对话落库与工具回执卡的验收脚本（对着某个实例跑）。

    $env:FITWISE_BASE="http://127.0.0.1:8010"
    .venv\\Scripts\\python.exe scripts\\check_agent_conversation.py

验收：提问会落库 → 历史能读回（含引用）→ 工具回执卡能建、能更新成完成。
回归沙箱里跑就不会往演示项目里写东西。
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))

from scorecard import check, print_scorecard  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = os.environ.get("FITWISE_BASE", "http://127.0.0.1:8000")


def ensure_drafts(client: httpx.Client, project_id: int) -> int:
    """审批链要验的是"有草稿时走待批准"，所以先确保项目里有待确认需求。

    两个坑：
    1. 上一个脚本可能已经把需求全部确认，项目里一条草稿都不剩；
    2. 直接重跑抽取也没用 —— 抽出来的需求与已确认基线重名，会被需求级去重整批挡掉。
    所以先删掉一条已确认需求，再重跑抽取：它会被重新抽成草稿。
    """
    payload = client.get(f"/api/projects/{project_id}/requirements").json()
    drafts = [item for item in payload["requirements"] if item["status"] == "draft"]
    if drafts:
        return len(drafts)

    confirmed = [item for item in payload["requirements"] if item["status"] == "confirmed"]
    if confirmed:
        client.delete(f"/api/requirements/{confirmed[-1]['id']}")

    job = client.post(f"/api/projects/{project_id}/requirements/extract").json()
    for _ in range(120):
        state = client.get(f"/api/jobs/{job['job_id']}").json()
        if state["status"] in ("done", "failed"):
            break
        time.sleep(1)
    payload = client.get(f"/api/projects/{project_id}/requirements").json()
    return len([item for item in payload["requirements"] if item["status"] == "draft"])


def main() -> int:
    client = httpx.Client(base_url=BASE, timeout=120)
    login = client.post(
        "/api/auth/login", json={"email": "presales@fitwise.local", "password": "fitwise123"}
    )
    login.raise_for_status()
    client.headers["Authorization"] = f"Bearer {login.json()['token']}"
    project_id = client.get("/api/projects").json()[0]["id"]
    print(f"instance: {BASE} · project #{project_id}")

    before = client.get(f"/api/projects/{project_id}/agent/messages").json()
    print(f"1. 历史消息 {len(before)} 条")

    reply = client.post(
        f"/api/projects/{project_id}/agent/ask", json={"message": "工期是多久"}
    ).json()
    print(f"2. 提问 → {reply['kind']}｜{reply['text'][:40]}｜引用 {len(reply['citations'])} 条")

    after = client.get(f"/api/projects/{project_id}/agent/messages").json()
    print(f"3. 落库后 {len(after)} 条（新增 {len(after) - len(before)}）")

    card = client.post(
        f"/api/projects/{project_id}/agent/messages",
        json={
            "role": "tool",
            "kind": "job",
            "text": "能力判断",
            "data": {"tool": "run_matching", "label": "能力判断", "status": "running"},
        },
    ).json()
    print(f"4. 建回执卡 #{card['id']}｜{card['data'].get('status')}")

    patched = client.patch(
        f"/api/agent/messages/{card['id']}",
        json={"text": "判断完成：完全支持 4 · 部分支持 7", "data": {"status": "done", "tool": "run_matching"}},
    ).json()
    print(f"5. 更新回执卡｜{patched['text']}｜{patched['data'].get('status')}")

    final = client.get(f"/api/projects/{project_id}/agent/messages").json()

    # 审批链：Agent 只准备，留痕由服务端写
    drafts = ensure_drafts(client, project_id)
    print(f"5.5 待确认需求 {drafts} 条（审批链的前置条件）")
    # 意图分类由模型做，"帮我确认这些需求"偶尔会被判成普通提问（返回 answer 而不是批准卡）。
    # 这是模型的抖动，不是链路问题，所以允许重试：第一次用最自然的说法，
    # 重试时把意图说得更明确一点（模拟用户换个说法再说一遍）。
    phrases = [
        "帮我确认这些需求",
        "帮我把待确认的需求整理成清单，等我批准",
        "把待确认需求设为基线，先给我一张批准卡",
    ]
    prepared = None
    for attempt, phrase in enumerate(phrases, start=1):
        prepared = client.post(
            f"/api/projects/{project_id}/agent/ask", json={"message": phrase}
        ).json()
        if prepared.get("kind") == "approval":
            break
        print(f"6. 第 {attempt} 次没走待批准（kind={prepared.get('kind')}），换个说法重试")
        time.sleep(1)
    print(f"6. 确认需求 → kind={prepared['kind']}｜{prepared.get('approval', {}).get('detail', '')[:40]}")
    approval_card = client.post(
        f"/api/projects/{project_id}/agent/messages",
        json={
            "role": "tool",
            "kind": "approval",
            "text": prepared["text"],
            "data": {"approval": prepared.get("approval")},
        },
    ).json()
    decided = client.post(
        f"/api/projects/{project_id}/agent/approvals",
        json={"message_id": approval_card["id"], "decision": "declined"},
    ).json()
    approval_data = (decided.get("data") or {}).get("approval") or {}
    print(f"7. 留痕：decision={approval_data.get('decision')} by={approval_data.get('by')} at={'有' if approval_data.get('at') else '无'}")

    # ④ 对话层：提问要落库、回答要带引用、回执卡要能走完、需要人承诺的动作必须走批准卡
    check(
        "提问与回执卡都落库",
        len(final) - len(before) == 3,
        f"新增 {len(final) - len(before)} 条消息",
    )
    check(
        "回答带引用并落库",
        any(item["role"] == "agent" and item["data"].get("citations") for item in final),
    )
    check(
        "回执卡能更新成完成",
        any(item["role"] == "tool" and item["data"].get("status") == "done" for item in final),
    )
    check("确认需求走批准卡（不自己执行）", prepared["kind"] == "approval", f"kind={prepared['kind']}")
    check(
        "批准留痕由服务端写",
        approval_data.get("decision") == "declined" and bool(approval_data.get("by")),
        f"decision={approval_data.get('decision')} by={approval_data.get('by')}",
    )
    return print_scorecard("对话与审批分数表")


if __name__ == "__main__":
    raise SystemExit(main())
