"""材料检索的调参小工具：看看分片里有什么、一个问句能命中哪几片。

    .venv\\Scripts\\python.exe scripts\\check_material_search.py 工期 上线 接口

只读：直接读 server/data/fitwise.db，不写任何东西。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
SERVER_DIR = ROOT / "server"
sys.path.insert(0, str(SERVER_DIR))

from sqlalchemy import select  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.models import Material, MaterialChunk, Project  # noqa: E402
from app.services import material_search  # noqa: E402


def main() -> int:
    keywords = sys.argv[1:] or ["工期", "周期", "上线", "接口", "语言"]
    db = SessionLocal()
    try:
        project = db.execute(select(Project).order_by(Project.id)).scalars().first()
        if project is None:
            print("no projects")
            return 0

        rows = db.execute(
            select(MaterialChunk, Material)
            .join(Material, Material.id == MaterialChunk.material_id)
            .where(Material.project_id == project.id)
            .order_by(MaterialChunk.material_id, MaterialChunk.page)
        ).all()

        print(f"project #{project.id} {project.name} · 分片 {len(rows)} 片\n")
        for chunk, material in rows:
            text = chunk.text or ""
            found = [word for word in keywords if word in text]
            print(f"— {material.filename} 第 {chunk.page} 页 · {len(text)} 字 · 命中关键词 {found}")
            print(f"  {text[:220].replace(chr(10), ' / ')}")

        print("\n=== 问句命中测试 ===")
        for query in ("工期是多久", "多久能上线", "接口要求是什么", "要支持哪些语言"):
            terms = material_search.query_terms(query)
            hits = material_search.search_chunks(db, project_id=project.id, query=query, top_k=3)
            print(f"\nQ: {query}")
            print(f"   候选词: {' / '.join(terms[:14])}")
            for hit in hits:
                print(f"   命中 {hit.score:.0f} 分 · 第 {hit.page} 页 · {hit.text[:60]}")
            if not hits:
                print("   没有命中")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
