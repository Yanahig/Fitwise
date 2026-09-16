"""初始化数据库：账号、企业知识库、演示客户与项目。

幂等：重复启动不会重复插入。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import SessionLocal, init_db
from .models import (
    Activity,
    CapabilityDoc,
    CapabilitySignal,
    CaseStudy,
    Customer,
    Project,
    User,
)
from .security import hash_password

logger = logging.getLogger(__name__)

SEED_FILE = Path(__file__).resolve().parent.parent / "seed" / "knowledge_base.json"

DEFAULT_USERS = [
    ("admin@fitwise.local", "管理员", "admin", "fitwise123"),
    ("presales@fitwise.local", "张岚（售前）", "presales", "fitwise123"),
    ("engineer@fitwise.local", "陈默（技术专家）", "engineer", "fitwise123"),
]


def seed_users(db: Session) -> None:
    for email, name, role, password in DEFAULT_USERS:
        exists = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
        if exists:
            continue
        db.add(User(email=email, name=name, role=role, password_hash=hash_password(password)))
        logger.info("创建默认账号：%s / %s", email, password)
    db.commit()


def seed_knowledge(db: Session) -> None:
    if db.execute(select(CapabilityDoc.id).limit(1)).first():
        return
    if not SEED_FILE.exists():
        logger.warning("未找到知识库种子文件：%s", SEED_FILE)
        return

    payload = json.loads(SEED_FILE.read_text(encoding="utf-8"))
    for item in payload.get("docs", []):
        doc = CapabilityDoc(
            product=item.get("productName", ""),
            title=item.get("docTitle", ""),
            doc_type=item.get("docType", "产品文档"),
            version=item.get("version", ""),
            owner=item.get("owner", "产品团队"),
            status="active",
            effective_at=item.get("updatedAt", ""),
            description=item.get("description", ""),
            tags=item.get("capabilityTags", []),
            supported_scope=item.get("supportedScope", []),
            limitations=item.get("limitations", []),
            deployment=item.get("deployment", []),
            api_capabilities=item.get("apiCapabilities", []),
        )
        db.add(doc)
        db.flush()
        for signal in item.get("signals", []):
            db.add(
                CapabilitySignal(
                    doc_id=doc.id,
                    kind="support",
                    text=signal.get("scope", ""),
                    page=int(signal.get("page") or 1),
                    heading=signal.get("heading", ""),
                    excerpt=signal.get("excerpt", ""),
                    tags=signal.get("tags", []),
                )
            )
        for constraint in item.get("constraintSignals", []):
            impact = constraint.get("impact", "limit")
            kind = {"gap": "gap", "limitation": "limit", "needs-confirmation": "uncertain"}.get(impact, "limit")
            db.add(
                CapabilitySignal(
                    doc_id=doc.id,
                    kind=kind,
                    text=constraint.get("detail", ""),
                    page=int(constraint.get("page") or 1),
                    heading=constraint.get("heading", ""),
                    excerpt=constraint.get("excerpt", ""),
                    tags=constraint.get("tags", []),
                )
            )

    for item in payload.get("cases", []):
        evidence = item.get("evidence") or {}
        db.add(
            CaseStudy(
                name=item.get("name", ""),
                industry=item.get("industry", ""),
                scale=item.get("scale", ""),
                duration=item.get("duration", ""),
                background=item.get("customerBackground", ""),
                needs=item.get("customerNeeds", []),
                products=item.get("products", []),
                solution=item.get("solution", ""),
                results=item.get("results", []),
                lessons=item.get("reusableLessons", []),
                tags=item.get("tags", []),
                evidence_doc=evidence.get("documentName", ""),
                evidence_page=int(evidence.get("page") or 1),
                evidence_excerpt=evidence.get("excerpt", ""),
            )
        )
    db.commit()
    logger.info("已导入知识库：%s 份能力文档、%s 个案例", len(payload.get("docs", [])), len(payload.get("cases", [])))


def seed_demo_project(db: Session) -> None:
    if db.execute(select(Customer.id).limit(1)).first():
        return
    customer = Customer(
        name="XX 城市商业银行",
        industry="银行 / 金融",
        scale="资产规模约 3,000 亿",
        region="华东",
        tier="A",
        owner_name="张岚",
        source="老客户转介绍",
        health="hot",
        notes="票据中心日均处理量约 50 万页，正在推进智能票据与档案处理平台一期。",
    )
    db.add(customer)
    db.flush()
    project = Project(
        customer_id=customer.id,
        name="智能票据与档案处理平台（一期）",
        code="BANK-2026-01",
        stage="materials",
        status="active",
        owner_name="张岚",
        summary="客户已完成 RFP 澄清，等待上传正式招标文件与答疑纪要后开始需求抽取。",
    )
    db.add(project)
    db.flush()
    db.add(
        Activity(
            customer_id=customer.id,
            project_id=project.id,
            actor="张岚",
            type="project_created",
            summary="新建项目：智能票据与档案处理平台（一期）",
        )
    )
    db.add(
        Activity(
            customer_id=customer.id,
            project_id=project.id,
            actor="张岚",
            type="note",
            summary="客户已完成 RFP 澄清，科技部关注信创与接口集成；下一步收集正式 RFP 与答疑纪要。",
        )
    )
    db.commit()
    logger.info("已创建演示客户与项目：%s / %s", customer.name, project.name)


def seed_all() -> None:
    init_db()
    db = SessionLocal()
    try:
        seed_users(db)
        seed_knowledge(db)
        seed_demo_project(db)
    finally:
        db.close()
