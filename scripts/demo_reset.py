"""演示环境准备：知识库预置好，客户侧留空，等演示时手动上传材料。

用法：
    # 空白起点：建一个干净的演示客户 + 项目，不传材料（推荐，演示时你手动上传）
    .venv\\Scripts\\python.exe scripts\\demo_reset.py

    # 清场后再建：先把数据库备份，再清掉历史客户/项目/材料/需求/判断/方案/对话，保留知识库与账号
    .venv\\Scripts\\python.exe scripts\\demo_reset.py --purge

    # 预演模式：顺带把 demo/ 下的两份材料传进项目并等它读完、整理完需求（需要后端在跑）
    .venv\\Scripts\\python.exe scripts\\demo_reset.py --purge --preload

    # 改了知识库种子文件后重建企业知识库（业务数据不动）
    .venv\\Scripts\\python.exe scripts\\demo_reset.py --reseed-kb

环境变量：FITWISE_BASE（默认 http://127.0.0.1:8000）—— 只有 --preload 需要后端在线。
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVER_DIR = ROOT / "server"
sys.path.insert(0, str(SERVER_DIR))

import httpx  # noqa: E402

from app.db import SessionLocal, init_db  # noqa: E402
from app.models import (  # noqa: E402
    Activity,
    AgentMessage,
    CapabilityDoc,
    CapabilitySignal,
    CaseStudy,
    Customer,
    Material,
    MaterialChunk,
    MatchEvidence,
    MatchResult,
    Project,
    Requirement,
    Solution,
)
from app.seed import DEFAULT_USERS, seed_knowledge, seed_users  # noqa: E402

UI_BASE = os.environ.get("FITWISE_UI", "http://127.0.0.1:5183")
BASE = os.environ.get("FITWISE_BASE", "http://127.0.0.1:8000")
DEMO_DIR = ROOT / "demo"

DEMO_CUSTOMER = "XX市档案馆（演示）"
DEMO_PROJECT = "档案数字化与智能处理平台（演示）"


def backup_database() -> Path | None:
    """清场前先备份库文件：演示库万一被清错，可以整体换回来。"""
    from app.config import settings

    url = settings.resolved_database_url
    if not url.startswith("sqlite:///"):
        print("· 非 SQLite 库，跳过文件备份（请自行确认是否有备份）")
        return None
    source = Path(url.replace("sqlite:///", "", 1))
    if not source.exists():
        print("· 还没有数据库文件，跳过备份")
        return None
    backup_dir = source.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / f"fitwise-{datetime.now().strftime('%Y%m%d-%H%M%S')}.db"
    shutil.copy2(source, target)
    try:
        shown = target.relative_to(ROOT)
    except ValueError:  # 沙箱/临时目录里的库不在仓库下，直接显示绝对路径
        shown = target
    print(f"· 已备份：{shown}")
    return target


def purge_business_data() -> None:
    """清掉业务数据，保留账号与企业知识库（能力文档 / 能力信号 / 历史案例）。"""
    db = SessionLocal()
    try:
        for model in (
            AgentMessage,
            MatchEvidence,
            MatchResult,
            Solution,
            Requirement,
            MaterialChunk,
            Material,
            Activity,
            Project,
            Customer,
        ):
            removed = db.query(model).delete()
            if removed:
                print(f"· 清理 {model.__tablename__}：{removed} 行")
        db.commit()
    finally:
        db.close()


def purge_knowledge() -> None:
    """清掉企业知识库，让 seed_knowledge 按最新种子文件重建。

    种子文件（server/seed/knowledge_base.json）改了之后必须走这一步 ——
    seed_knowledge 只在库为空时灌数据，不然演示里的"暂不支持 / 部分支持"还是旧口径。
    """
    db = SessionLocal()
    try:
        for model in (CapabilitySignal, CapabilityDoc, CaseStudy):
            removed = db.query(model).delete()
            if removed:
                print(f"· 清理 {model.__tablename__}：{removed} 行")
        db.commit()
    finally:
        db.close()


def create_demo_project() -> tuple[int, int]:
    """建演示客户 + 空白演示项目（材料 0、需求 0）。"""
    db = SessionLocal()
    try:
        owner = DEFAULT_USERS[1][1]
        customer = Customer(
            name=DEMO_CUSTOMER,
            industry="政务 / 公共事业",
            region="XX市",
            tier="A",
            owner_name=owner,
            source="演示数据",
            notes="演示客户，全部为虚构数据",
        )
        db.add(customer)
        db.flush()
        project = Project(
            customer_id=customer.id,
            name=DEMO_PROJECT,
            summary="XX市档案馆档案数字化与智能处理平台：等保三级、全离线信创环境、含 5 类特殊档案。",
            stage="materials",
            owner_name=owner,
            status="active",
        )
        db.add(project)
        db.commit()
        return customer.id, project.id
    finally:
        db.close()


def knowledge_stats() -> tuple[int, int]:
    db = SessionLocal()
    try:
        return db.query(CapabilityDoc).count(), db.query(CaseStudy).count()
    finally:
        db.close()


def wait_material(client: httpx.Client, project_id: int, material_id: int, timeout: int = 180) -> dict | None:
    started = time.time()
    while time.time() - started < timeout:
        rows = client.get(f"/api/projects/{project_id}/materials").json()
        material = next((item for item in rows if item["id"] == material_id), None)
        if material and material["status"] in ("parsed", "failed"):
            return material
        time.sleep(2)
    return None


def wait_settled(
    client: httpx.Client,
    project_id: int,
    *,
    expected_extractions: int = 1,
    timeout: int = 300,
    stable_rounds: int = 2,
    interval: int = 5,
) -> tuple[list[dict], list[dict]]:
    """等自动整理真正跑完：先等活动记录里"需求整理"的条数凑够，再等需求数稳定。

    每上传一份材料都会触发一次全项目整理，所以"有需求了"只是中间状态 ——
    只看需求数会读到半成品（例如第二份材料的工期口径还没进来）。
    整轮结束以活动记录为准，这是唯一能观察到"这次整理已经写库"的信号。
    """
    started = time.time()
    while time.time() - started < timeout:
        activities = client.get(f"/api/projects/{project_id}/activities").json()
        finished = len([item for item in activities if item.get("type") == "requirements_extracted"])
        if finished >= expected_extractions:
            break
        time.sleep(interval)

    last_count = -1
    stable = 0
    requirements: list[dict] = []
    highlights: list = []
    while time.time() - started < timeout:
        requirements = client.get(f"/api/projects/{project_id}/requirements").json()["requirements"]
        project = client.get(f"/api/projects/{project_id}").json()
        highlights = project.get("highlights") or []
        if requirements and len(requirements) == last_count:
            stable += 1
            if stable >= stable_rounds:
                break
        else:
            stable = 0
        last_count = len(requirements)
        time.sleep(interval)
    return requirements, highlights

def preload_materials(project_id: int) -> None:
    """把 demo/ 下的材料传进项目（只给预演用；正式演示请留空、手动上传）。"""
    files = sorted(DEMO_DIR.glob("*.pdf"))
    if not files:
        print(f"· {DEMO_DIR.relative_to(ROOT)} 下没有 PDF，先跑 scripts/make_demo_materials.py")
        return

    client = httpx.Client(base_url=BASE, timeout=300)
    login = client.post("/api/auth/login", json={"email": "presales@fitwise.local", "password": "fitwise123"})
    login.raise_for_status()
    client.headers["Authorization"] = f"Bearer {login.json()['token']}"

    for path in files:
        with path.open("rb") as handle:
            upload = client.post(
                f"/api/projects/{project_id}/materials",
                files={"file": (path.name, handle, "application/pdf")},
            )
        upload.raise_for_status()
        material_id = upload.json()["id"]
        print(f"· 已上传 {path.name}（#{material_id}），等它读完…")
        material = wait_material(client, project_id, material_id)
        if not material or material["status"] != "parsed":
            print(f"  读取失败：{(material or {}).get('parse_error', '未知原因')}")
            continue
        print(f"  读完：{material['page_count']} 页 · 引擎 {material['parse_engine']}")

    requirements, highlights = wait_settled(client, project_id, expected_extractions=len(files))
    print(f"· 自动整理出 {len(requirements)} 条需求（待确认）")

    timeline_facts = [
        item
        for item in highlights
        if isinstance(item, dict) and str(item.get("label") or "") == "工期口径"
    ]
    unlocated = [item for item in highlights if isinstance(item, dict) and item.get("source_located") is False]
    if unlocated:
        print(f"· 有 {len(unlocated)} 条要点的来源未定位（判断时会被自检标记）")
    if len(timeline_facts) >= 2:
        values = " ｜ ".join(str(item.get("value"))[:40] for item in timeline_facts)
        print(f"· 工期口径冲突已按原文各记一条：{values}")
    elif timeline_facts:
        print(f"· 工期口径要点：{timeline_facts[0].get('value')}")
    else:
        print("· 提示：这次没抓到「工期口径」要点，演示时可直接讲材料里的工期要求")


def main() -> int:
    parser = argparse.ArgumentParser(description="准备 Fitwise 演示环境")
    parser.add_argument("--purge", action="store_true", help="备份并清空历史业务数据（保留知识库与账号）")
    parser.add_argument("--preload", action="store_true", help="把 demo/ 下的材料传进项目（预演用，需要后端在跑）")
    parser.add_argument(
        "--reseed-kb",
        action="store_true",
        help="按最新的 server/seed/knowledge_base.json 重建企业知识库（改了种子文件后用）",
    )
    parser.add_argument("--keep-empty", action="store_true", help="只清场，不建新的演示项目")
    args = parser.parse_args()

    init_db()
    if args.purge:
        backup_database()
        purge_business_data()
    if args.reseed_kb:
        purge_knowledge()

    db = SessionLocal()
    try:
        seed_users(db)
        seed_knowledge(db)
    finally:
        db.close()

    docs, cases = knowledge_stats()
    print(f"· 企业知识库：{docs} 份能力文档 / {cases} 个历史案例（预置，演示中不变）")

    if args.keep_empty:
        print("\n清场完成，未创建新项目。")
        return 0

    customer_id, project_id = create_demo_project()
    print(f"· 演示客户 #{customer_id}：{DEMO_CUSTOMER}")
    print(f"· 演示项目 #{project_id}：{DEMO_PROJECT}（材料 0 份、需求 0 条）")

    if args.preload:
        preload_materials(project_id)
    else:
        files = sorted(path.name for path in DEMO_DIR.glob("*.pdf"))
        if files:
            print("\n演示动作：把这两份材料拖进右侧 Agent —— " + "、".join(files))

    print(f"\n演示入口：{UI_BASE}/#/projects/{project_id}/materials")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
