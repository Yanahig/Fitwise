from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(80))
    role: Mapped[str] = mapped_column(String(32), default="presales")  # admin / presales / engineer / viewer
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), index=True)
    industry: Mapped[str] = mapped_column(String(80), default="")
    scale: Mapped[str] = mapped_column(String(80), default="")
    region: Mapped[str] = mapped_column(String(80), default="")
    tier: Mapped[str] = mapped_column(String(16), default="B")  # S/A/B/C
    owner_name: Mapped[str] = mapped_column(String(80), default="")
    source: Mapped[str] = mapped_column(String(80), default="")
    health: Mapped[str] = mapped_column(String(16), default="normal")  # hot / normal / risk
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    projects: Mapped[list["Project"]] = relationship(back_populates="customer", cascade="all, delete-orphan")


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    code: Mapped[str] = mapped_column(String(40), default="")
    stage: Mapped[str] = mapped_column(String(32), default="materials")  # 见 domain/stages.py
    status: Mapped[str] = mapped_column(String(24), default="active")  # active / won / lost / paused
    owner_name: Mapped[str] = mapped_column(String(80), default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    open_questions: Mapped[list] = mapped_column(JSON, default=list)
    # 项目要点：只存材料里明确写着的事实（背景/范围/工期/环境/时间点/决策链），每条带来源页码
    highlights: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    customer: Mapped[Customer] = relationship(back_populates="projects")
    materials: Mapped[list["Material"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    requirements: Mapped[list["Requirement"]] = relationship(back_populates="project", cascade="all, delete-orphan")


class Material(Base):
    __tablename__ = "materials"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    file_type: Mapped[str] = mapped_column(String(40), default="")
    material_type: Mapped[str] = mapped_column(String(32), default="other")  # rfp / minutes / qa / email / other
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    storage_path: Mapped[str] = mapped_column(String(500), default="")
    status: Mapped[str] = mapped_column(String(24), default="uploaded")  # uploaded / parsing / parsed / failed
    parse_engine: Mapped[str] = mapped_column(String(32), default="textin-xparse")
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    textin_file_id: Mapped[str] = mapped_column(String(80), default="")
    parse_error: Mapped[str] = mapped_column(Text, default="")
    markdown: Mapped[str] = mapped_column(Text, default="")
    # 这份材料整体写了什么：Agent 抽取时顺带产出一句，显示在材料清单里
    summary: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[int] = mapped_column(Integer, default=1)
    uploaded_by: Mapped[str] = mapped_column(String(80), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    parsed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    project: Mapped[Project] = relationship(back_populates="materials")
    chunks: Mapped[list["MaterialChunk"]] = relationship(back_populates="material", cascade="all, delete-orphan")


class MaterialChunk(Base):
    __tablename__ = "material_chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    material_id: Mapped[int] = mapped_column(ForeignKey("materials.id", ondelete="CASCADE"), index=True)
    page: Mapped[int] = mapped_column(Integer, default=1)
    heading: Mapped[str] = mapped_column(String(255), default="")
    text: Mapped[str] = mapped_column(Text, default="")
    order_index: Mapped[int] = mapped_column(Integer, default=0)

    material: Mapped[Material] = relationship(back_populates="chunks")


class Requirement(Base):
    __tablename__ = "requirements"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    detail: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(32), default="产品能力")
    priority: Mapped[str] = mapped_column(String(16), default="medium")
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft / confirmed / dropped
    source_material_id: Mapped[int | None] = mapped_column(ForeignKey("materials.id", ondelete="SET NULL"), nullable=True)
    source_material_name: Mapped[str] = mapped_column(String(255), default="")
    source_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_heading: Mapped[str] = mapped_column(String(255), default="")
    source_excerpt: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[list] = mapped_column(JSON, default=list)
    constraints: Mapped[list] = mapped_column(JSON, default=list)
    created_by_ai: Mapped[bool] = mapped_column(Boolean, default=True)
    # 人工改过内容的需求：重跑抽取时保留，不被 AI 新结果覆盖（草稿也一样）
    edited: Mapped[bool] = mapped_column(Boolean, default=False)
    confirmed_by: Mapped[str] = mapped_column(String(80), default="")
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    project: Mapped[Project] = relationship(back_populates="requirements")
    matches: Mapped[list["MatchResult"]] = relationship(back_populates="requirement", cascade="all, delete-orphan")


class CapabilityDoc(Base):
    __tablename__ = "capability_docs"

    id: Mapped[int] = mapped_column(primary_key=True)
    product: Mapped[str] = mapped_column(String(80), index=True)
    title: Mapped[str] = mapped_column(String(200))
    doc_type: Mapped[str] = mapped_column(String(40), default="产品文档")
    version: Mapped[str] = mapped_column(String(24), default="")
    owner: Mapped[str] = mapped_column(String(80), default="")
    status: Mapped[str] = mapped_column(String(16), default="active")
    effective_at: Mapped[str] = mapped_column(String(32), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[list] = mapped_column(JSON, default=list)
    supported_scope: Mapped[list] = mapped_column(JSON, default=list)
    limitations: Mapped[list] = mapped_column(JSON, default=list)
    deployment: Mapped[list] = mapped_column(JSON, default=list)
    api_capabilities: Mapped[list] = mapped_column(JSON, default=list)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    signals: Mapped[list["CapabilitySignal"]] = relationship(back_populates="doc", cascade="all, delete-orphan")


class CapabilitySignal(Base):
    __tablename__ = "capability_signals"

    id: Mapped[int] = mapped_column(primary_key=True)
    doc_id: Mapped[int] = mapped_column(ForeignKey("capability_docs.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(24), default="support")  # support / limit / gap / uncertain
    text: Mapped[str] = mapped_column(Text, default="")
    page: Mapped[int] = mapped_column(Integer, default=1)
    heading: Mapped[str] = mapped_column(String(255), default="")
    excerpt: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[list] = mapped_column(JSON, default=list)

    doc: Mapped[CapabilityDoc] = relationship(back_populates="signals")


class CaseStudy(Base):
    __tablename__ = "case_studies"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    industry: Mapped[str] = mapped_column(String(80), default="")
    scale: Mapped[str] = mapped_column(String(80), default="")
    duration: Mapped[str] = mapped_column(String(80), default="")
    background: Mapped[str] = mapped_column(Text, default="")
    needs: Mapped[list] = mapped_column(JSON, default=list)
    products: Mapped[list] = mapped_column(JSON, default=list)
    solution: Mapped[str] = mapped_column(Text, default="")
    results: Mapped[list] = mapped_column(JSON, default=list)
    lessons: Mapped[list] = mapped_column(JSON, default=list)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    evidence_doc: Mapped[str] = mapped_column(String(200), default="")
    evidence_page: Mapped[int] = mapped_column(Integer, default=1)
    evidence_excerpt: Mapped[str] = mapped_column(Text, default="")


class MatchResult(Base):
    __tablename__ = "match_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    requirement_id: Mapped[int] = mapped_column(ForeignKey("requirements.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="unknown")  # full / partial / none / unknown
    headline: Mapped[str] = mapped_column(String(300), default="")
    condition: Mapped[str] = mapped_column(Text, default="")
    rationale: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    judgment_source: Mapped[str] = mapped_column(String(16), default="ai")  # ai / human
    reviewed_by: Mapped[str] = mapped_column(String(80), default="")
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_note: Mapped[str] = mapped_column(Text, default="")
    gaps: Mapped[list] = mapped_column(JSON, default=list)
    confirmations: Mapped[list] = mapped_column(JSON, default=list)
    capability_doc_ids: Mapped[list] = mapped_column(JSON, default=list)
    case_ids: Mapped[list] = mapped_column(JSON, default=list)
    # 取证轨迹（检索 → 判断 → 自检 → 决策）与自检裁决：Agent 化的可见证据
    # 见 docs/agent-core-design.md：agent 负责判断，guardrail 只出裁决
    trace: Mapped[list] = mapped_column(JSON, default=list)
    self_check: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    requirement: Mapped[Requirement] = relationship(back_populates="matches")
    evidences: Mapped[list["MatchEvidence"]] = relationship(back_populates="match", cascade="all, delete-orphan")


class MatchEvidence(Base):
    __tablename__ = "match_evidences"

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("match_results.id", ondelete="CASCADE"), index=True)
    source_type: Mapped[str] = mapped_column(String(16), default="capability")  # customer / capability / case
    document_name: Mapped[str] = mapped_column(String(255), default="")
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    heading: Mapped[str] = mapped_column(String(255), default="")
    excerpt: Mapped[str] = mapped_column(Text, default="")

    match: Mapped[MatchResult] = relationship(back_populates="evidences")


class Solution(Base):
    __tablename__ = "solutions"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    problem: Mapped[str] = mapped_column(Text, default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft / reviewed
    steps: Mapped[list] = mapped_column(JSON, default=list)
    capability_plan: Mapped[list] = mapped_column(JSON, default=list)
    reference_cases: Mapped[list] = mapped_column(JSON, default=list)
    ask_customer: Mapped[list] = mapped_column(JSON, default=list)
    ask_internal: Mapped[list] = mapped_column(JSON, default=list)
    risks: Mapped[list] = mapped_column(JSON, default=list)
    next_actions: Mapped[list] = mapped_column(JSON, default=list)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Activity(Base):
    __tablename__ = "activities"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"), nullable=True, index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True)
    actor: Mapped[str] = mapped_column(String(80), default="")
    type: Mapped[str] = mapped_column(String(40), default="note")
    summary: Mapped[str] = mapped_column(String(400), default="")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AgentMessage(Base):
    """对话消息（项目级）。

    会话必须落库：刷新页面、换设备、第二天回来，Agent 都得记得聊过什么、做过什么。
    role=user / agent 是聊天，role=tool 是工具回执卡（材料卡与动作卡都是它）——
    回执只存 material_id 或 job_id，状态仍然从项目与材料表实时读，避免两套进度。
    """

    __tablename__ = "agent_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16), default="user")  # user / agent / tool
    kind: Mapped[str] = mapped_column(String(16), default="text")  # text / material / job
    text: Mapped[str] = mapped_column(Text, default="")
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
