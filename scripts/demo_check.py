"""演示前自检：一条命令确认"知识库满、客户侧空、模型与解析都在线"。

跑法：
    .venv\\Scripts\\python.exe scripts\\demo_check.py
    .venv\\Scripts\\python.exe scripts\\demo_check.py --allow-materials   # 预演过的项目（已有材料）也算通过

环境变量：FITWISE_BASE（默认 http://127.0.0.1:8000）、FITWISE_UI（默认 http://127.0.0.1:5183）
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import httpx

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
BASE = os.environ.get("FITWISE_BASE", "http://127.0.0.1:8000")
UI_BASE = os.environ.get("FITWISE_UI", "http://127.0.0.1:5183")

OK = "  [OK]"
WARN = "  [! ]"
BAD = "  [XX]"


def main() -> int:
    parser = argparse.ArgumentParser(description="Fitwise 演示前自检")
    parser.add_argument("--allow-materials", action="store_true", help="项目里已有材料也算通过（预演模式）")
    args = parser.parse_args()

    blockers: list[str] = []
    print(f"演示环境自检 · 后端 {BASE} · 前端 {UI_BASE}\n")

    # 1. 后端在不在
    try:
        health = httpx.get(f"{BASE}/api/health-check", timeout=5)
        print(f"{OK if health.status_code == 200 else BAD} 后端：{health.status_code}")
        if health.status_code != 200:
            blockers.append("后端不可用")
    except Exception as error:  # noqa: BLE001
        print(f"{BAD} 后端：连不上（{type(error).__name__}）")
        blockers.append("后端不可用：先起 uvicorn（见 README）")
        print("\n后端没起来，后面的检查跳过。")
        return 1

    # 2. 前端在不在（不阻塞）
    try:
        ui = httpx.get(UI_BASE, timeout=5)
        print(f"{OK if ui.status_code == 200 else WARN} 前端：{ui.status_code}（{UI_BASE}）")
        if ui.status_code != 200:
            blockers.append("前端不可用：npm run dev -- --port 5183")
    except Exception:  # noqa: BLE001
        print(f"{WARN} 前端：连不上（{UI_BASE}）")
        blockers.append("前端不可用：npm run dev -- --port 5183")

    # 3. 登录 + 配置 + 知识库
    client = httpx.Client(base_url=BASE, timeout=20)
    login = client.post("/api/auth/login", json={"email": "presales@fitwise.local", "password": "fitwise123"})
    if login.status_code != 200:
        print(f"{BAD} 演示账号登录失败：{login.status_code}")
        blockers.append("演示账号登录失败（presales@fitwise.local / fitwise123）")
        return 1
    client.headers["Authorization"] = f"Bearer {login.json()['token']}"

    meta = client.get("/api/meta").json()
    llm = meta["integrations"]["llm"]
    parser_info = meta["integrations"]["parser"]
    docs = meta["knowledge"]["docs"]
    cases = meta["knowledge"]["cases"]
    print(f"{OK if docs >= 9 and cases >= 5 else WARN} 企业知识库：{docs} 份能力文档 / {cases} 个历史案例")
    if docs < 9 or cases < 5:
        blockers.append("知识库不完整：跑 scripts/demo_reset.py --purge 会重新灌 seed")

    # 3.1 结论档位的护栏：gap 信号决定"暂不支持"能不能出现，而它的标签必须够窄 ——
    #     gap 挂上 archive / pdf 这种泛标签，等于"整个领域都做不了"，会把所有需求一起拉低。
    BROAD_TAGS = {
        "archive", "pdf", "office", "scanned", "document-parse", "table",
        "deployment", "api", "integration", "ocr", "structured-fields",
    }
    kb_docs = client.get("/api/knowledge/docs").json()
    gaps, broad = [], []
    for doc in kb_docs:
        for signal in doc.get("signals") or []:
            if signal.get("kind") != "gap":
                continue
            gaps.append(signal)
            hits = set(signal.get("tags") or []) & BROAD_TAGS
            if hits:
                broad.append((doc.get("title", ""), sorted(hits)))
    if gaps:
        print(f"{OK} 「暂不支持」可触发：知识库有 {len(gaps)} 条 gap 信号")
    else:
        print(f"{WARN} 「暂不支持」出不来：知识库一条 gap 信号都没有")
        blockers.append("知识库里没有 gap 信号，演示时不会出现「暂不支持」")
    for title, tags in broad:
        print(f"{BAD} gap 信号标签过宽：{title} → {tags}（会让所有相关需求都被判暂不支持）")
        blockers.append(f"gap 信号标签过宽：{title} → {tags}")
    print(f"{OK if parser_info['enabled'] else BAD} 文档解析（{parser_info['provider']}）：{'已配置' if parser_info['enabled'] else '未配置凭据'}")
    if not parser_info["enabled"]:
        blockers.append("TextIn 凭据未配置：材料读不出来")
    mode = "公网模型（材料会出内网）" if llm.get("external") else "内网模型"
    print(f"{OK if llm['enabled'] else BAD} 大模型（{llm['provider']} / {llm['model']} · {mode}）：{'已配置' if llm['enabled'] else '未配置 key'}")
    if not llm["enabled"]:
        blockers.append("LLM key 未配置：会走规则回退（结果明显变糙）")

    # 4. 演示项目状态
    projects = client.get("/api/projects").json()
    if not projects:
        print(f"{BAD} 没有项目：先跑 scripts/demo_reset.py --purge")
        blockers.append("没有演示项目")
        project = None
    else:
        project = projects[0]
        pid = project["id"]
        materials = client.get(f"/api/projects/{pid}/materials").json()
        requirements = client.get(f"/api/projects/{pid}/requirements").json()["requirements"]
        matches = client.get(f"/api/projects/{pid}/matches").json()
        state_ok = not materials and not requirements
        label = f"项目 #{pid} {project['name']}"
        print(
            f"{OK if state_ok else (WARN if args.allow_materials else BAD)} {label}："
            f"材料 {len(materials)} 份 · 需求 {len(requirements)} 条 · 判断 {len(matches)} 条"
        )
        if not state_ok and not args.allow_materials:
            blockers.append("项目不是空白起点：跑 scripts/demo_reset.py --purge，或用 --allow-materials")
        print(f"     演示入口：{UI_BASE}/#/projects/{pid}/materials")

    # 5. 演示材料在不在
    files = sorted(path.name for path in (ROOT / "demo").glob("*.pdf"))
    print(f"{OK if files else BAD} 演示材料：{len(files)} 份" + (f"（{'、'.join(files)}）" if files else ""))
    if not files:
        blockers.append("demo/ 下没有 PDF：跑 scripts/make_demo_materials.py")

    print()
    if blockers:
        print("阻塞项：")
        for item in blockers:
            print(f"  - {item}")
        return 1
    print("一切就绪：知识库满、客户侧空、解析与模型在线。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
