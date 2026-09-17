"""三个 Agent：需求抽取 → 能力匹配 → 解决路径。

设计原则（与产品定位一致）：
1. **证据只能来自知识库**：模型负责判断与表达，证据（文档名 + 页码 + 原文）由检索层提供，
   模型不能凭空创造引用。
2. **模型不能比证据更乐观**：规则层根据命中的能力信号 / 限制 / 缺口给出结论上限，
   模型只能更保守，不能更激进；知识库里没有证据一律输出「待补依据」（信息不足时先不给结论）。
3. **失败可降级**：模型不可用时走确定性规则，系统不会因为 API 故障而不可用。
"""

from __future__ import annotations

import difflib
import logging
import re
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .. import prompts
from ..domain import infer_tags, is_pending_name
from ..models import (
    CapabilityDoc,
    CaseStudy,
    MatchEvidence,
    MatchResult,
    Material,
    MaterialChunk,
    Project,
    Requirement,
    Solution,
)
from . import ai_ledger, retrieval
from .llm import chat_json

logger = logging.getLogger(__name__)

REQUIREMENT_KEYWORDS = (
    "需求",
    "要求",
    "须",
    "需",
    "应",
    "不得",
    "不低于",
    "不支持",
    "必须",
    "支持",
    "提供",
    "接口",
    "部署",
    "准确率",
    "安全",
    "合规",
)

# --------------------------------------------------------------------------- #
# 工具函数
# --------------------------------------------------------------------------- #


def _ledger_recorder(db: Session, *, project_id: int):
    """把模型调用记进 AI 调用账本。写账本失败不影响业务（见 services/ai_ledger.py）。"""

    def record(entry: dict[str, Any]) -> None:
        ai_ledger.record(db, project_id=project_id, **entry)

    return record


def _clip(text: str, limit: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[:limit] + "…"


def _humanize(text: str) -> str:
    """把模型输出里的技术写法换成售前听得懂的说法。"""
    text = re.sub(r"(?<![A-Za-z0-9])P(\d{1,4})(?![A-Za-z0-9])", r"第 \1 页", text or "")
    for source, target in (
        ("需求基线", "已确认的需求"),
        ("基线需求", "已确认的需求"),
        ("落库", "已保存"),
        ("置信度", "把握度"),
    ):
        text = text.replace(source, target)
    return text


def _material_digest(db: Session, materials: list[Material], budget: int = 45_000) -> tuple[str, bool]:
    """把材料的带页码片段拼成提示词输入；超预算时按需求关键词优先筛选。"""
    blocks: list[str] = []
    used = 0
    truncated = False

    for material in materials:
        chunks = (
            db.execute(
                select(MaterialChunk)
                .where(MaterialChunk.material_id == material.id)
                .order_by(MaterialChunk.order_index)
            )
            .scalars()
            .all()
        )
        if not chunks and material.markdown:
            blocks.append(
                f"【材料：{material.filename}｜共 {material.page_count or 1} 页】\n"
                f"{_clip(material.markdown, 6000)}"
            )
            continue

        header = f"【材料：{material.filename}｜共 {material.page_count or 1} 页】"
        body: list[str] = []
        for chunk in chunks:
            line = f"(P{chunk.page}{('·' + chunk.heading) if chunk.heading else ''}) {chunk.text}"
            if used + len(line) > budget:
                truncated = True
                break
            used += len(line)
            body.append(line)
        blocks.append(header + "\n" + "\n".join(body))
        if truncated:
            break

    if truncated:
        blocks.append(
            "（材料内容较长，以上为按需求关键词优先级筛选后的片段；如需完整内容请分段上传或拆分文件。）"
        )
    return "\n\n".join(blocks), truncated


ALLOWED_FACT_LABELS = (
    "客户与项目",
    "建设范围",
    "工期口径",
    "预算",
    "交付环境",
    "关键时间点",
    "决策链",
)


def _norm_text(text: str) -> str:
    """去空白后的文本：中英混排的标点与空格不影响相似度判断。"""
    return re.sub(r"\s+", "", text or "")


def _is_duplicate_requirement(
    candidate_title: str,
    candidate_detail: str,
    existing: list[tuple[str, str]],
    *,
    title_threshold: float = 0.78,
    detail_threshold: float = 0.72,
) -> bool:
    """需求级去重：标题像、**或者描述几乎是同一句话**，都算重复。

    只看标题会漏。实测教训：同一件事被抽成两条时，标题可以完全不同 ——
    「REST接口与SDK对接，峰值≥200QPS」vs「标准接口对接现有影像平台」标题相似度只有 0.24，
    但两条描述相似度 0.85（同一句话的两种说法），结果需求清单里出现两条一样的东西。
    所以标题之外必须再看描述：长描述（≥12 字）相似度超阈值就算重复。
    """
    normalized = _norm_text(candidate_title)
    if not normalized:
        return True
    normalized_detail = _norm_text(candidate_detail)
    for item_title, item_detail in existing:
        if normalized == item_title:
            return True
        if len(normalized) >= 6 and len(item_title) >= 6:
            if normalized in item_title or item_title in normalized:
                return True
            if difflib.SequenceMatcher(None, normalized, item_title).ratio() >= title_threshold:
                return True
        if len(normalized_detail) >= 12 and len(item_detail) >= 12:
            ratio = difflib.SequenceMatcher(None, normalized_detail, item_detail).ratio()
            if ratio >= detail_threshold:
                return True
    return False


def _pick_source_material(materials: list[Material], name: str) -> Material | None:
    if not name:
        return None
    normalized = name.strip().lower()
    for material in materials:
        if material.filename.lower() == normalized:
            return material
    for material in materials:
        stem = re.sub(r"\.[a-z0-9]+$", "", material.filename.lower())
        if stem and (stem in normalized or normalized in stem):
            return material
    # 模型有时会把材料**正文里的标题**当成文件名（例如把文件名写成 RFP 的抬头）。
    # 这种情况用相似度兜一下，避免整条需求因为"名字对不上"被丢掉。
    best: Material | None = None
    best_ratio = 0.0
    candidate = re.sub(r"\.[a-z0-9]+$", "", normalized)
    for material in materials:
        stem = re.sub(r"\.[a-z0-9]+$", "", material.filename.lower())
        if not stem:
            continue
        ratio = difflib.SequenceMatcher(None, stem, candidate).ratio()
        if ratio > best_ratio:
            best, best_ratio = material, ratio
    if best is not None and best_ratio >= 0.55:
        return best
    return materials[0] if len(materials) == 1 else None


def _material_containing(
    db: Session,
    materials: list[Material],
    page: int | None,
    excerpt: str,
) -> Material | None:
    """按引用原文反查是哪份材料。

    文件名对不上时的第二种定位方式：模型给的 source_excerpt 是从材料里抄的，
    哪份材料里有这句话，来源就是它。比继续猜文件名可靠。
    """
    needles = [needle for needle in _evidence_needles(excerpt) if len(needle) >= 8]
    if not needles:
        return None
    for strict in (True, False):
        for material in materials:
            query = select(MaterialChunk).where(MaterialChunk.material_id == material.id)
            if strict and page:
                query = query.where(MaterialChunk.page == page)
            chunks = db.execute(query.order_by(MaterialChunk.order_index)).scalars().all()
            for needle in needles:
                for chunk in chunks:
                    if needle in _norm_for_match(chunk.text):
                        return material
    return None


QUOTE_EQUIV = str.maketrans(
    {
        "「": "“",
        "」": "”",
        "『": "“",
        "』": "”",
        '"': "“",
        "＂": "“",
        "‘": "“",
        "’": "”",
    }
)


def _norm_for_match(text: str) -> str:
    """比对引用原文时统一空白与引号写法。

    模型抄原文时常把 “ ” 写成 「 」，把全角括号写成半角 —— 这不是引用不实，
    不该因此判成"定位不到"。这里只做标点与空白的归一，词句本身仍要逐字命中。
    """
    return re.sub(r"\s+", "", (text or "").translate(QUOTE_EQUIV))


def _evidence_needles(excerpt: str) -> list[str]:
    """由长到短的候选片段：长摘录更具体，短摘录兜住模型省略或改写标点的情况。"""
    base = _norm_for_match(excerpt)
    return [needle for needle in dict.fromkeys([base[:24], base[:16], base[:12]]) if len(needle) >= 8]


def locate_evidence(
    db: Session,
    material_id: int | None,
    page: int | None,
    excerpt: str,
) -> tuple[MaterialChunk | None, bool]:
    """在指定材料里定位引用原文，返回 (命中的片段, 是否定位成功)。

    和旧实现的区别：**定位失败就明确失败**。旧写法在找不到原文时退回该材料的第一块，
    调用方随即把来源页码改写成第 1 页 —— 引用看起来有据可查，实际是伪造的定位。
    宁可让界面显示"来源未定位"，也不要一个假的页码。
    """
    if not material_id:
        return None, False

    needles = _evidence_needles(excerpt)
    same_page = (
        db.execute(
            select(MaterialChunk)
            .where(MaterialChunk.material_id == material_id)
            .where(MaterialChunk.page == page)
            .order_by(MaterialChunk.order_index)
        )
        .scalars()
        .all()
        if page
        else []
    )
    if needles:
        for needle in needles:
            for chunk in same_page:
                if needle in _norm_for_match(chunk.text):
                    return chunk, True
        # 页码可能被模型写偏：同材料其它页里找得到，也算定位成功，并据此纠正页码
        for needle in needles:
            for chunk in (
                db.execute(
                    select(MaterialChunk)
                    .where(MaterialChunk.material_id == material_id)
                    .order_by(MaterialChunk.order_index)
                )
                .scalars()
                .all()
            ):
                if needle in _norm_for_match(chunk.text):
                    return chunk, True
        return None, False

    if same_page:
        # 只给了页码、没给摘录：该页本身可用
        return same_page[0], True
    return None, False


# --------------------------------------------------------------------------- #
# Agent 1：需求抽取
# --------------------------------------------------------------------------- #


def _fallback_requirements(materials: list[Material], digest: str) -> dict:
    """无模型时的确定性抽取：按含需求关键词的句子切分。"""
    requirements = []
    for material in materials:
        for raw_line in re.split(r"[\n。；;]", material.markdown or ""):
            line = raw_line.strip()
            if len(line) < 8 or not any(keyword in line for keyword in REQUIREMENT_KEYWORDS):
                continue
            requirements.append(
                {
                    "title": line[:18],
                    "detail": line,
                    "category": "部署" if "部署" in line else "产品能力",
                    "priority": "high" if any(k in line for k in ("必须", "不得", "不低于")) else "medium",
                    "tags": infer_tags(line),
                    "constraints": [],
                    "source_material_name": material.filename,
                    "source_page": 1,
                    "source_heading": "",
                    "source_excerpt": line[:80],
                }
            )
    return {"requirements": requirements[:20], "open_questions": [], "project_facts": []}


#: 「硬性口径」：标 high（P0）必须在原文里找得到这些写法之一
HARD_PRIORITY_PATTERNS = (
    "必须",
    "须",
    "不得",
    "不允许",
    "不接受",
    "禁止",
    "不低于",
    "不少于",
    "不得低于",
    "应满足",
    "应在",
)

#: 模型可能给出各种写法：先收敛到三档，认不出来的归 medium 并计数
PRIORITY_ALIASES = {
    "high": "high",
    "p0": "high",
    "高": "high",
    "medium": "medium",
    "p1": "medium",
    "中": "medium",
    "low": "low",
    "p2": "low",
    "低": "low",
}


def normalize_priority(value: Any) -> tuple[str, bool]:
    """把模型给的优先级收敛到 high/medium/low。返回（档位, 是否认不出来）。"""
    text = str(value or "").strip().lower()
    if not text:
        return "medium", False
    mapped = PRIORITY_ALIASES.get(text)
    if mapped:
        return mapped, False
    return "medium", True


def guard_priority(priority: str, *texts: str) -> tuple[str, bool]:
    """越界检查：标 high 必须有硬性表述兜底，找不到就降一档。

    和判断层同一条原则 —— 结论不许比证据乐观。优先级没有证据支撑时，
    宁可少标一个 P0，也不要让"人人 P0"把排序变成摆设。
    """
    if priority != "high":
        return priority, False
    blob = " ".join(text for text in texts if text)
    if any(pattern in blob for pattern in HARD_PRIORITY_PATTERNS):
        return priority, False
    return "medium", True


async def analyze_requirements(
    db: Session,
    *,
    project: Project,
    materials: list[Material],
    actor: str,
    trace_id: str = "",
) -> tuple[list[Requirement], dict[str, Any]]:
    """抽出草稿需求，并回传"被拦掉多少"：去重几条、因为没有来源丢掉几条。

    返回计数而不是只返回列表，是为了让调用方（job result、日志）看得到拦截情况 ——
    这块出过"一条都没抽出来但没人发现"的事故。
    """
    parsed = [material for material in materials if material.status == "parsed"]
    if not parsed:
        raise ValueError("没有已解析完成的材料，无法抽取需求")

    digest, truncated = _material_digest(db, parsed)
    system = prompts.EXTRACT_SYSTEM
    user = prompts.extract_user_prompt(project_name=project.name, digest=digest)

    meta: dict[str, Any] = {}
    payload = await chat_json(
        system=system,
        user=user,
        schema_hint=prompts.REQUIREMENT_SCHEMA,
        fallback=lambda: _fallback_requirements(parsed, digest),
        required_keys=["requirements"],
        meta=meta,
        trace_id=trace_id,
        step="extract",
        prompt_version=prompts.EXTRACT_PROMPT_VERSION,
        on_call=_ledger_recorder(db, project_id=project.id),
    )

    fallback_used = bool(meta.get("fallback_used"))
    unlocated_sources = 0

    # 客户名 / 项目名：留空（或还是占位名）时用这次识别的结果补上，人工填过的不覆盖
    identified_customer = _clip(str(payload.get("customer_name") or "").strip(), 80)
    identified_project = _clip(str(payload.get("project_name") or "").strip(), 120)
    if identified_customer and project.customer is not None and is_pending_name(project.customer.name):
        project.customer.name = identified_customer
    if identified_project and is_pending_name(project.name):
        project.name = identified_project

    raw_facts = [item for item in payload.get("project_facts", []) if isinstance(item, dict)]
    raw_requirements = [item for item in payload.get("requirements", []) if isinstance(item, dict)]
    # 截断与超限都要计数：静默截断会让"看起来分析完了"变成一句谎话
    over_limit = max(0, len(raw_facts) - 10) + max(0, len(raw_requirements) - 40)

    # 重新抽取时清理旧的草稿需求：已确认的保留，人工改过内容的也保留
    db.execute(
        delete(Requirement).where(
            Requirement.project_id == project.id,
            Requirement.status == "draft",
            Requirement.created_by_ai.is_(True),
            Requirement.edited.is_(False),
        )
    )
    db.flush()

    # 材料的一句话概括：显示在材料清单里，让人一眼知道这堆材料是什么
    summaries = {
        str(item.get("material_name") or "").strip(): _clip(str(item.get("summary") or "").strip(), 120)
        for item in payload.get("material_summaries", [])
        if isinstance(item, dict)
    }
    for material in parsed:
        text = summaries.get(material.filename)
        if text:
            material.summary = text

    # 待确认问题写回项目：只增不丢（重跑不能冲掉已经跟客户确认过的条目）
    fresh_questions = [
        {
            "question": str(item.get("question") or "").strip(),
            "why": str(item.get("why") or "").strip(),
            "owner": str(item.get("owner") or "客户"),
            "source": "ai",
        }
        for item in payload.get("open_questions", [])
        if isinstance(item, dict) and str(item.get("question") or "").strip()
    ]
    project.open_questions = merge_open_questions(project.open_questions, fresh_questions)[:20]

    # 项目要点：只记材料里写着的事实，带来源页码；人工编辑过或已忽略的条目在重跑时保留
    kept_facts = [
        item
        for item in (project.highlights or [])
        if isinstance(item, dict) and (item.get("edited") or item.get("ignored"))
    ]
    extracted_facts: list[dict] = []
    for item in raw_facts[:10]:
        value = _clip(str(item.get("value") or "").strip(), 120)
        if not value:
            continue
        material = _pick_source_material(parsed, str(item.get("source_material_name") or ""))
        if material is None:
            # 找不到来源材料的事实不展示：项目要点同样遵守「没有证据就不说」
            continue
        try:
            page = int(item.get("source_page")) if item.get("source_page") is not None else None
        except (TypeError, ValueError):
            page = None
        if page:
            page = max(1, min(page, material.page_count or 1))
        chunk, located = locate_evidence(
            db, material.id, page, str(item.get("source_excerpt") or "")
        )
        if chunk is not None:
            page = chunk.page
        elif not located:
            unlocated_sources += 1
        label = str(item.get("label") or "").strip()
        if label not in ALLOWED_FACT_LABELS:
            label = "其他要点"
        extracted_facts.append(
            {
                "label": label,
                "value": value,
                "source_material_name": material.filename,
                "source_page": page,
                # 定位不到原文时如实标记，界面会显示"来源未定位"
                "source_located": located,
            }
        )
    project.highlights = kept_facts + extracted_facts

    # 已存在的需求（人工确认的基线）不再重复创建草稿，避免重复抽取后需求列表翻倍
    existing: list[tuple[str, str]] = [
        (_norm_text(item.title), _norm_text(item.detail))
        for item in db.execute(select(Requirement).where(Requirement.project_id == project.id)).scalars().all()
    ]

    created: list[Requirement] = []
    skipped = 0
    unsourced = 0
    priority_downgraded = 0
    priority_unrecognized = 0
    for item in raw_requirements[:40]:
        material = _pick_source_material(parsed, str(item.get("source_material_name") or ""))
        if material is None:
            # 文件名对不上时，用引用的原文反查是哪份材料（模型常把正文标题当文件名）
            material = _material_containing(db, parsed, item.get("source_page"), str(item.get("source_excerpt") or ""))
        if material is None:
            # 两条路都定位不到来源的需求不进清单：和项目要点同一条原则 —— 没有证据就不说
            unsourced += 1
            continue
        page = item.get("source_page")
        try:
            page = int(page) if page is not None else None
        except (TypeError, ValueError):
            page = None
        if material and page:
            page = max(1, min(page, material.page_count or 1))

        chunk, located = locate_evidence(
            db, material.id if material else None, page, str(item.get("source_excerpt") or "")
        )
        excerpt = str(item.get("source_excerpt") or "").strip()
        heading = str(item.get("source_heading") or "").strip()
        if chunk is not None:
            page = chunk.page
            heading = heading or chunk.heading
            if not excerpt or re.sub(r"\s+", "", excerpt)[:12] not in re.sub(r"\s+", "", chunk.text):
                excerpt = _clip(chunk.text, 120)
        elif not located:
            # 定位失败：保留模型给的页码但如实计数，判断阶段的自检会再次核对并封顶结论
            unlocated_sources += 1

        title = str(item.get("title") or "").strip()[:200] or _clip(str(item.get("detail") or ""), 20)
        detail = str(item.get("detail") or "").strip()
        if _is_duplicate_requirement(title, detail, existing):
            skipped += 1
            continue
        existing.append((_norm_text(title), _norm_text(detail)))
        # 优先级两道闸：先把模型给的值收敛到三档（认不出来的归中并计数），
        # 再对 high 做越界检查 —— 原文里找不到硬性表述就降一档，别让"人人 P0"把排序变成摆设。
        raw_priority, priority_unknown = normalize_priority(item.get("priority"))
        # 只看这条需求自己的原文与描述，不看整页：整页里只要有一句「必须」，
        # 同一页的需求就都能挂 P0 —— 那样闸门等于没有。
        priority, priority_downgraded_here = guard_priority(raw_priority, title, detail, excerpt)
        if priority_unknown:
            priority_unrecognized += 1
        if priority_downgraded_here:
            priority_downgraded += 1
        requirement = Requirement(
            project_id=project.id,
            title=title,
            detail=detail,
            category=str(item.get("category") or "产品能力"),
            priority=priority,
            status="draft",
            source_material_id=material.id if material else None,
            source_material_name=material.filename if material else "",
            source_page=page,
            source_heading=heading,
            source_excerpt=excerpt,
            tags=item.get("tags") or infer_tags(f"{title} {item.get('detail') or ''}"),
            constraints=item.get("constraints") or [],
            created_by_ai=True,
        )
        db.add(requirement)
        created.append(requirement)

    db.flush()

    # 并发重跑（上传后自动抽取 + 手动再抽一次）可能各插一份同名草稿：同名只留一条，
    # 人工改过的那条优先；并把清理如实计数，而不是让需求清单悄悄翻倍。
    drafts = (
        db.execute(
            select(Requirement)
            .where(Requirement.project_id == project.id, Requirement.status == "draft")
            .order_by(Requirement.id)
        )
        .scalars()
        .all()
    )
    _, duplicates = dedupe_draft_titles(list(drafts))
    for item in duplicates:
        db.delete(item)
    concurrent_duplicates = len(duplicates)
    if duplicates:
        db.flush()
        removed_ids = {item.id for item in duplicates}
        created = [item for item in created if item.id not in removed_ids]

    logger.info(
        "需求抽取完成：项目 %s，%s 条（去重跳过 %s 条，无来源丢弃 %s 条，来源未定位 %s 条，"
        "超限丢弃 %s 条，并发重复清理 %s 条，优先级降级 %s 条，优先级认不出 %s 条，"
        "截断=%s，回退=%s，操作人=%s）",
        project.id,
        len(created),
        skipped,
        unsourced,
        unlocated_sources,
        over_limit,
        concurrent_duplicates,
        priority_downgraded,
        priority_unrecognized,
        truncated,
        fallback_used,
        actor,
    )
    return created, {
        "skipped_duplicates": skipped,
        "dropped_without_source": unsourced,
        "unlocated_sources": unlocated_sources,
        "dropped_over_limit": over_limit,
        "concurrent_duplicates_removed": concurrent_duplicates,
        "priority_downgraded": priority_downgraded,
        "priority_unrecognized": priority_unrecognized,
        "digest_truncated": int(bool(truncated)),
        "llm_fallback": int(fallback_used),
        "prompt_version": prompts.EXTRACT_PROMPT_VERSION,
        "identified_customer": identified_customer,
        "identified_project": identified_project,
    }


# --------------------------------------------------------------------------- #
# Agent 2：能力匹配（证据化判断）
# --------------------------------------------------------------------------- #


def _rule_status(hits: list[retrieval.DocHit]) -> str:
    """根据知识库证据给出结论上限。"""
    if not hits:
        return "unknown"
    constraints = [signal for hit in hits for signal in hit.constraints]
    if any(signal.signal.kind == "gap" for signal in constraints):
        return "none"
    if constraints:
        return "partial"
    return "full"


# --------------------------------------------------------------------------- #
# 自检 guardrail：只出裁决，由调用方决定怎么处理
# --------------------------------------------------------------------------- #

GUARDRAIL_BLOCK = "block"
GUARDRAIL_WARN = "warn"

STATUS_RANK = {"unknown": 0, "none": 1, "partial": 2, "full": 3}


def merge_open_questions(existing: list | None, fresh: list[dict]) -> list[dict]:
    """待确认问题只增不丢：已存在的条目保留，新条目去重后追加。

    重跑抽取或判断不再整批覆盖 —— 覆盖式更新会把已经跟客户确认过的问题冲掉。
    """
    merged: list[dict] = []
    seen: set[str] = set()
    for item in [*(existing or []), *fresh]:
        if not isinstance(item, dict):
            continue
        key = _norm_text(str(item.get("question") or ""))
        if not key or key in seen:
            continue
        seen.add(key)
        merged.append(item)
    return merged


def dedupe_draft_titles(drafts: list[Requirement]) -> tuple[list[Requirement], list[Requirement]]:
    """同名草稿只留一条，优先保留人工改过的那条。

    返回 (保留, 待删)。两条都被人工改过时都保留 —— 宁可留重复，也不替人决定删哪条。
    """
    groups: dict[str, list[Requirement]] = {}
    for item in drafts:
        key = _norm_text(item.title)
        if not key:
            continue
        groups.setdefault(key, []).append(item)

    keep: list[Requirement] = []
    drop: list[Requirement] = []
    for items in groups.values():
        if len(items) == 1:
            keep.append(items[0])
            continue
        edited = [item for item in items if item.edited]
        if len(edited) >= 2:
            keep.extend(items)
            continue
        winner = edited[0] if edited else items[0]
        keep.append(winner)
        drop.extend(item for item in items if item is not winner)
    return keep, drop


def evidence_guardrail(
    db: Session | None,
    *,
    requirement: Requirement,
    hits: list[retrieval.DocHit],
    case_hits: list[retrieval.CaseHit],
    status: str,
    rationale: str,
    fallback_used: bool = False,
) -> dict:
    """对一条判断做确定性自检，返回裁决而不是自己改结论。

    agent 负责判断，guardrail 只负责 flagged / reasons / metrics；
    是降级、追问还是补材料，由 _run_matching 决定（见 docs/agent-core-design.md）。
    db 传 None 时跳过"来源能否定位"一项，供离线自测使用。
    """
    reasons: list[dict] = []
    support = [(hit, signal) for hit in hits for signal in hit.signals]
    constraints = [(hit, signal) for hit in hits for signal in hit.constraints]
    unique_support = {(hit.doc.id, signal.signal.page) for hit, signal in support}
    evidence_pages = {signal.signal.page for _, signal in [*support, *constraints]}
    evidence_pages |= {hit.case.evidence_page for hit in case_hits}
    if requirement.source_page:
        evidence_pages.add(requirement.source_page)

    # 1. 客户来源能不能定位（修掉"找不到就退回第一页"的伪定位）
    if db is not None and requirement.source_material_id:
        _, located = locate_evidence(
            db,
            requirement.source_material_id,
            requirement.source_page,
            requirement.source_excerpt or requirement.detail,
        )
        if not located:
            reasons.append(
                {
                    "code": "source_not_located",
                    "severity": GUARDRAIL_BLOCK,
                    "detail": "这条需求在客户材料里定位不到原文，来源页码不可信。",
                }
            )
    elif not requirement.source_material_id or not requirement.source_page:
        reasons.append(
            {
                "code": "source_missing",
                "severity": GUARDRAIL_BLOCK,
                "detail": "这条需求没有可回指的来源材料或页码。",
            }
        )

    # 2. 完全支持必须有支持信号
    if status == "full" and not support:
        reasons.append(
            {
                "code": "no_support_signal",
                "severity": GUARDRAIL_BLOCK,
                "detail": "结论是完全支持，但没有任何支持信号。",
            }
        )

    # 3. 支持与缺口冲突（跨文档冲突的最小版本）
    if support and any(signal.signal.kind == "gap" for _, signal in constraints):
        reasons.append(
            {
                "code": "support_conflict_with_gap",
                "severity": GUARDRAIL_BLOCK,
                "detail": "同一条需求同时命中支持与缺口信号，不能判为完全支持。",
            }
        )

    # 4. 同一处证据被重复计数
    if len(support) > len(unique_support):
        reasons.append(
            {
                "code": "evidence_reused",
                "severity": GUARDRAIL_WARN,
                "detail": f"{len(support)} 条支持证据去重后只有 {len(unique_support)} 条。",
            }
        )

    # 5. 模型理由里的页码要能在本次证据或客户来源里找到
    cited = {int(item) for item in re.findall(r"[Pp](\d{1,4})", rationale or "")}
    cited |= {int(item) for item in re.findall(r"第\s*(\d{1,4})\s*页", rationale or "")}
    unverified = sorted(cited - evidence_pages)
    if unverified:
        reasons.append(
            {
                "code": "unverified_citation",
                "severity": GUARDRAIL_WARN,
                "detail": "理由里的页码不在本次证据中："
                + "、".join(f"第 {page} 页" for page in unverified[:5]),
            }
        )

    # 6. 结论来自规则回退也要留痕（静默回退会让人以为一直是模型在判断）
    if fallback_used:
        reasons.append(
            {
                "code": "llm_fallback",
                "severity": GUARDRAIL_WARN,
                "detail": "本次结论由本地规则生成（模型不可用或输出不合规）。",
            }
        )

    blocking = [item for item in reasons if item["severity"] == GUARDRAIL_BLOCK]
    return {
        "flagged": bool(blocking),
        "reasons": reasons,
        "metrics": {
            "support": len(support),
            "unique_support": len(unique_support),
            "constraints": len(constraints),
            "cases": len(case_hits),
            "status": status,
        },
    }


def _cap_status_by_guardrail(status: str, verdict: dict) -> tuple[str, list[str]]:
    """把自检裁决落到结论上：只降不升。返回 (最终状态, 降级说明)。"""
    codes = {str(item.get("code")) for item in verdict.get("reasons", [])}
    capped = status
    notes: list[str] = []

    def lower_to(target: str) -> None:
        nonlocal capped
        if STATUS_RANK.get(target, 3) < STATUS_RANK.get(capped, 3):
            capped = target

    if codes & {"source_not_located", "source_missing"}:
        lower_to("partial")
        notes.append("客户来源未定位，结论最多部分支持")
    if "no_support_signal" in codes:
        lower_to("partial")
        notes.append("没有支持信号，不能判为完全支持")
    if "support_conflict_with_gap" in codes:
        lower_to("partial")
        notes.append("同时命中支持与缺口，降为部分支持")
    return capped, notes


def _evidence_confidence(*, status: str, verdict: dict, fallback_used: bool) -> float:
    """把握度由证据派生，不用模型自报的数字（自报置信度没有校准意义）。"""
    metrics = verdict.get("metrics") or {}
    base = {"full": 0.9, "partial": 0.72, "none": 0.82, "unknown": 0.3}.get(status, 0.4)
    sources = int(metrics.get("unique_support") or 0) + int(metrics.get("constraints") or 0)
    score = base + min(0.06, 0.02 * max(0, sources - 1))
    if verdict.get("flagged"):
        score -= 0.1
    if fallback_used:
        score -= 0.05
    return round(max(0.05, min(0.98, score)), 2)


def _build_rationale(
    requirement: Requirement,
    hits: list[retrieval.DocHit],
    case_hits: list[retrieval.CaseHit],
    status: str,
) -> str:
    parts: list[str] = []
    source = f"《{requirement.source_material_name}》"
    if requirement.source_page:
        source += f" P{requirement.source_page}"
    parts.append(f"客户在{source}提出：{requirement.source_excerpt or requirement.detail}")

    support = [(hit, signal) for hit in hits for signal in hit.signals]
    constraints = [(hit, signal) for hit in hits for signal in hit.constraints]
    if support:
        hit, signal = support[0]
        parts.append(
            f"企业知识库中《{hit.doc.title} {hit.doc.version}》P{signal.signal.page}显示：{signal.signal.excerpt}"
        )
    elif status == "unknown":
        parts.append("在企业知识库中未检索到可支撑该需求的能力文档或案例证据。")
    if constraints:
        hit, signal = constraints[0]
        parts.append(
            f"但《{hit.doc.title} {hit.doc.version}》P{signal.signal.page}指出：{signal.signal.excerpt}"
        )
    if case_hits:
        case = case_hits[0].case
        parts.append(f"历史案例《{case.name}》可作参考：{case.evidence_excerpt}")

    closing = {
        "full": "因此判断为「完全支持」，该能力可直接纳入方案。",
        "partial": "因此判断为「部分支持」，需先确认上述前置条件再对客户承诺。",
        "none": "因此判断为「暂不支持」，需评估定制开发或替代方案。",
        "unknown": "因此判断为「待补依据」，补齐依据前不做确定承诺。",
    }[status]
    parts.append(closing)
    return "".join(parts)


def _fallback_judgement(
    requirement: Requirement,
    hits: list[retrieval.DocHit],
    case_hits: list[retrieval.CaseHit],
) -> dict:
    status = _rule_status(hits)
    support = [(hit, signal) for hit in hits for signal in hit.signals]
    constraints = [(hit, signal) for hit in hits for signal in hit.constraints]

    if status == "full" and support:
        headline = f"{support[0][0].doc.product}：{support[0][1].signal.text}"
    elif status == "partial" and constraints:
        headline = f"{constraints[0][0].doc.product}：{_clip(constraints[0][1].signal.text, 40)}（需确认）"
    elif status == "none" and constraints:
        headline = f"当前没有标准能力：{_clip(constraints[0][1].signal.text, 40)}"
    elif requirement.source_excerpt:
        headline = "客户材料信息不足，需要向客户确认"
    else:
        headline = "知识库未检索到足够证据，需要确认"

    return {
        "status": status,
        "headline": headline,
        "condition": constraints[0][1].signal.text if constraints else "",
        "rationale": _build_rationale(requirement, hits, case_hits, status),
        "gaps": [signal.signal.text for _, signal in constraints if signal.signal.kind in {"gap", "limit"}],
        "confirmations": [signal.signal.text for _, signal in constraints if signal.signal.kind == "uncertain"],
        "confidence": {"full": 0.9, "partial": 0.75, "none": 0.85, "unknown": 0.35}[status],
    }


async def judge_requirement(
    db: Session,
    *,
    requirement: Requirement,
    trace_id: str = "",
) -> MatchResult:
    text = f"{requirement.title} {requirement.detail}"
    tags = list(dict.fromkeys((requirement.tags or []) + infer_tags(text)))
    hits = retrieval.search_capabilities(db, text=text, tags=tags)
    case_hits = retrieval.search_cases(db, tags=tags)

    evidence_block = (
        "\n".join(
            "\n".join(
                [
                    f"《{hit.doc.title} {hit.doc.version}》（{hit.doc.doc_type}）",
                    "支持范围："
                    + "；".join(hit.doc.supported_scope or [])
                    + (
                        "；证据：" + " | ".join(f"P{s.signal.page} {s.signal.excerpt}" for s in hit.signals)
                        if hit.signals
                        else ""
                    ),
                    "限制与缺口："
                    + (" | ".join(f"P{s.signal.page} [{s.signal.kind}] {s.signal.excerpt}" for s in hit.constraints) or "无"),
                ]
            )
            for hit in hits
        )
        or "（未检索到相关企业能力文档）"
    )
    case_block = (
        "\n".join(f"《{hit.case.name}》P{hit.case.evidence_page}：{hit.case.evidence_excerpt}" for hit in case_hits)
        or "（未检索到相似历史案例）"
    )

    system = prompts.JUDGE_SYSTEM
    user = prompts.judge_user_prompt(
        title=requirement.title,
        detail=requirement.detail,
        source_material_name=requirement.source_material_name,
        source_page=requirement.source_page,
        source_excerpt=requirement.source_excerpt,
        evidence_block=evidence_block,
        case_block=case_block,
    )

    fallback = lambda: _fallback_judgement(requirement, hits, case_hits)  # noqa: E731
    meta: dict[str, Any] = {}
    payload = await chat_json(
        system=system,
        user=user,
        schema_hint=prompts.JUDGE_SCHEMA,
        fallback=fallback,
        required_keys=["status", "rationale"],
        meta=meta,
        trace_id=trace_id,
        step="judge",
        prompt_version=prompts.JUDGE_PROMPT_VERSION,
        on_call=_ledger_recorder(db, project_id=requirement.project_id),
    )

    rule_status = _rule_status(hits)
    llm_status = str(payload.get("status") or "").strip()
    if rule_status == "unknown":
        status = "unknown"  # 无证据一律待补依据，模型不可覆盖
    elif rule_status == "none":
        status = "none"
    elif rule_status == "partial":
        status = "partial"
    else:
        status = llm_status if llm_status in {"full", "partial", "unknown"} else "full"

    base = _fallback_judgement(requirement, hits, case_hits)
    rationale = _humanize(str(payload.get("rationale") or base["rationale"]))
    fallback_used = bool(meta.get("fallback_used"))

    # 自检：agent 只负责判断；裁决在 guardrail，降级由这里执行（见 docs/agent-core-design.md）
    verdict = evidence_guardrail(
        db,
        requirement=requirement,
        hits=hits,
        case_hits=case_hits,
        status=status,
        rationale=rationale,
        fallback_used=fallback_used,
    )
    capped_status, caps = _cap_status_by_guardrail(status, verdict)
    codes = [str(item.get("code")) for item in verdict.get("reasons", [])]
    # 展示给用户的说法：状态与原因都用中文，模型名/提示词版本/token 这类工程信息留在数据里备查
    status_text = {"full": "完全支持", "partial": "部分支持", "none": "暂不支持", "unknown": "待补依据"}
    reason_text = {
        "source_not_located": "来源没定位到原文",
        "source_missing": "缺少可回指的来源",
        "no_support_signal": "没有支持依据",
        "support_conflict_with_gap": "支持与缺口同时出现",
        "evidence_reused": "同一处依据被重复引用",
        "unverified_citation": "理由里的页码不在依据里",
        "llm_fallback": "这次由系统规则给出",
    }
    trace = [
        {
            "step": "recall",
            "detail": f"查了企业能力资料 {len(hits)} 份、历史案例 {len(case_hits)} 个",
            "rule_cap": rule_status,
        },
        {
            "step": "judge",
            "detail": "用这些资料核对了一遍",
            "fallback_used": fallback_used,
            "error_code": meta.get("error_code") or "",
            "trace_id": trace_id,
            "model": meta.get("model"),
            "prompt_version": meta.get("prompt_version") or prompts.JUDGE_PROMPT_VERSION,
            "latency_ms": meta.get("latency_ms"),
            "tokens": int(meta.get("prompt_tokens") or 0) + int(meta.get("completion_tokens") or 0),
        },
        {
            "step": "guardrail",
            "detail": "核查通过"
            if not verdict["flagged"]
            else "核查提示：" + "、".join(reason_text.get(code, code) for code in codes),
            "flagged": verdict["flagged"],
            "codes": codes,
        },
        {
            "step": "decide",
            "detail": f"结论：{status_text.get(status, status)} → {status_text.get(capped_status, capped_status)}"
            + ("（" + "；".join(caps) + "）" if caps else ""),
            "caps": caps,
        },
    ]

    result = MatchResult(
        project_id=requirement.project_id,
        requirement_id=requirement.id,
        status=capped_status,
        headline=_clip(_humanize(str(payload.get("headline") or base["headline"])), 300),
        condition=_clip(_humanize(str(payload.get("condition") or base["condition"])), 500),
        rationale=rationale,
        # 把握度由证据派生：模型自报的数字不作数
        confidence=_evidence_confidence(status=capped_status, verdict=verdict, fallback_used=fallback_used),
        judgment_source="ai",
        gaps=list(dict.fromkeys([_humanize(item) for item in [*(payload.get("gaps") or []), *base["gaps"]]]))[:6],
        confirmations=list(
            dict.fromkeys([_humanize(item) for item in [*(payload.get("confirmations") or []), *base["confirmations"]]])
        )[:6],
        capability_doc_ids=[hit.doc.id for hit in hits],
        case_ids=[hit.case.id for hit in case_hits],
        trace=trace,
        self_check=verdict,
    )
    db.add(result)
    db.flush()

    # 证据永远来自检索层，而不是模型输出
    for hit in hits:
        for signal in [*hit.signals, *hit.constraints]:
            db.add(
                MatchEvidence(
                    match_id=result.id,
                    source_type="capability",
                    document_name=f"{hit.doc.title} {hit.doc.version}",
                    page=signal.signal.page,
                    heading=signal.signal.heading,
                    excerpt=signal.signal.excerpt,
                )
            )
    db.add(
        MatchEvidence(
            match_id=result.id,
            source_type="customer",
            document_name=requirement.source_material_name or "客户材料",
            page=requirement.source_page,
            heading=requirement.source_heading,
            excerpt=requirement.source_excerpt or requirement.detail,
        )
    )
    for hit in case_hits:
        db.add(
            MatchEvidence(
                match_id=result.id,
                source_type="case",
                document_name=hit.case.name,
                page=hit.case.evidence_page,
                heading="案例证据",
                excerpt=hit.case.evidence_excerpt,
            )
        )
    db.flush()
    return result


async def match_requirements(
    db: Session,
    *,
    project: Project,
    requirements: list[Requirement],
    actor: str,
) -> list[MatchResult]:
    requirement_ids = [item.id for item in requirements]
    if requirement_ids:
        existing = (
            db.execute(select(MatchResult).where(MatchResult.requirement_id.in_(requirement_ids)))
            .scalars()
            .all()
        )
        for match in existing:
            if match.judgment_source != "human":  # 人工覆写过的结论不覆盖
                db.execute(delete(MatchEvidence).where(MatchEvidence.match_id == match.id))
                db.delete(match)
        db.flush()

    results: list[MatchResult] = []
    for requirement in requirements:
        # 与 _run_matching 同一条闸门：只判断已确认的需求
        if requirement.status != "confirmed":
            continue
        results.append(await judge_requirement(db, requirement=requirement))
    logger.info("能力匹配完成：项目 %s，%s 条（操作人=%s）", project.id, len(results), actor)
    return results


# --------------------------------------------------------------------------- #
# Agent 3：解决路径
# --------------------------------------------------------------------------- #


def _attach_requirement_ids(items: list, matches: list[MatchResult]) -> list[dict]:
    """把模型写的需求编号映射回需求 id。

    风险和行动是模型自由写的，但"依据哪几条需求"必须能落到库里的判断上 ——
    对不上就丢掉，和校验引用页码同一套原则：模型提议、后端校验。

    编号是首选（提示词里带了编号列表，模型回报得很准）；万一它写了标题，
    只认完全同名 —— 之前用"包含"匹配，把相邻需求的判断也挂上去了，反倒是误导。
    """
    by_index = {index + 1: match for index, match in enumerate(matches)}
    by_title = {
        re.sub(r"\s+", "", match.requirement.title): match
        for match in matches
        if match.requirement is not None
    }
    rows: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        row = dict(item)
        ids: list[int] = []
        for ref in item.get("based_on") or []:
            match = None
            text = str(ref).strip()
            if text.isdigit():
                match = by_index.get(int(text))
            elif text:
                match = by_title.get(re.sub(r"\s+", "", text))
            if match is not None and match.requirement_id not in ids:
                ids.append(match.requirement_id)
        row["requirement_ids"] = ids
        rows.append(row)
    return rows


def _ensure_risks_for_judgements(risks: list[dict], matches: list[MatchResult]) -> list[dict]:
    """兜底：判断为「暂不支持 / 部分支持」的需求，必须有对应的风险行。

    风险原本全靠模型自由写，实测出现过「某条需求判断为暂不支持、却没有挂任何风险」的遗漏。
    规则很简单：结论是暂不支持 → 高风险；部分支持 → 中风险；模型没写就用判断里的缺口 / 前置条件补一条。
    """
    covered = {rid for risk in risks for rid in (risk.get("requirement_ids") or [])}
    filled = list(risks)
    for match in matches:
        if match.status not in {"none", "partial"} or match.requirement is None:
            continue
        if match.requirement_id in covered:
            continue
        title = match.requirement.title
        if match.status == "none":
            level, label = "high", "能力缺口"
            detail = (match.gaps or [match.headline or "当前没有标准能力"])[0]
            mitigation = "在正式方案中列为定制或可选部分，避免直接承诺。"
        else:
            level, label = "medium", "范围与验收口径待确认"
            detail = (match.confirmations or [match.condition or match.headline or "存在前置条件"])[0]
            mitigation = "写入方案风险项，并在启动阶段与客户冻结验收口径。"
        filled.append(
            {
                "level": level,
                "title": f"{label}：{title}",
                "detail": detail,
                "mitigation": mitigation,
                "based_on": [title],
                "requirement_ids": [match.requirement_id],
            }
        )
    return filled


def _validate_solution_steps(steps: list, matches: list[MatchResult]) -> list[dict]:
    """步骤状态必须与它依据的判断一致：步骤不能比判断更乐观。

    模型写的 status 只当建议 —— 能对上判断就按判断结果校正（多条依据取最保守的一条），
    对不上的保留原文但标 status_verified=False，界面可以据此提示"未校验依据"。
    """
    rows = _attach_requirement_ids(steps, matches)
    by_requirement = {match.requirement_id: match for match in matches}
    verified: list[dict] = []
    for row in rows:
        statuses = [
            by_requirement[rid].status
            for rid in (row.get("requirement_ids") or [])
            if rid in by_requirement
        ]
        if statuses:
            worst = min(statuses, key=lambda item: STATUS_RANK.get(item, 0))
            row["status_verified"] = True
            if STATUS_RANK.get(str(row.get("status") or ""), 3) > STATUS_RANK.get(worst, 0):
                row["status"] = worst
                row["status_capped"] = True
            else:
                row["status"] = row.get("status") or worst
        else:
            row["status_verified"] = False
        verified.append(row)
    return verified


def _question_pool_lines(project: Project, matches: list[MatchResult]) -> str:
    """把「已有的待确认问题」拼成给方案步骤看的一段文本。

    来源是需求阶段抽出来的问题（自带 owner）与每条判断给出的前提。
    必须给全量：模型看不到池子，就只能照着匹配结果再问一遍，同一件事会被问三遍
    （需求阶段一次、判断一次、方案再一次），前端只按完全相同的文本去重是合并不掉的。
    """
    lines: list[str] = []
    for item in project.open_questions or []:
        if not isinstance(item, dict):
            continue
        text = str(item.get("question") or "").strip()
        if not text:
            continue
        lines.append(f"- [{str(item.get('owner') or '客户')}] {text}")
    for match in matches:
        title = match.requirement.title if match.requirement else ""
        for item in match.confirmations or []:
            text = str(item or "").strip()
            if text:
                lines.append(f"- [判断前提·{title}] {text}")
    return "\n".join(lines)


def _normalize_ask_customer(items: list) -> list[dict]:
    """对客问题统一成 {question, affects, covers}。

    老数据是纯字符串数组，新数据是对象：读取时都要能用，所以在这里归一。
    affects 只认 judge / promise 两档（不确认会不会改变能力结论）；covers 这里还是模型写的
    「匹配结果编号」，由 _attach_ask_customer_covers 校验成需求 id 后才落库。
    """
    rows: list[dict] = []
    seen: set[str] = set()
    for item in items:
        if isinstance(item, dict):
            question = str(item.get("question") or "").strip()
            affects = str(item.get("affects") or "").strip().lower()
            covers = [int(value) for value in item.get("covers") or [] if str(value).strip().isdigit()]
        else:
            question, affects, covers = str(item or "").strip(), "", []
        if not question or question in seen:
            continue
        seen.add(question)
        rows.append(
            {
                "question": question,
                "affects": affects if affects in {"judge", "promise"} else "",
                "covers": covers,
            }
        )
    return rows


def _normalize_ask_internal(items: list) -> list[dict]:
    """内部问题统一成 {question, owner}，顺手按问题文本去重。"""
    rows: list[dict] = []
    seen: set[str] = set()
    for item in items:
        if isinstance(item, dict):
            question = str(item.get("question") or "").strip()
            owner = str(item.get("owner") or "").strip()
        else:
            question, owner = str(item or "").strip(), ""
        if not question or question in seen:
            continue
        seen.add(question)
        rows.append({"question": question, "owner": owner})
    return rows


def _attach_ask_customer_covers(items: list, matches: list[MatchResult]) -> list[dict]:
    """把对客问题的 covers 从「匹配结果编号」映射成需求 id，再交给前端去重。

    模型写的 covers 是上面匹配结果列表里的编号（1..N）；前端手上只有库里的需求 id，
    两边量纲不一致就直接比对不上 —— 于是"模型已经合并过、前端又补一遍"的重复全都回来了。
    与 risks / next_actions 一样：模型提议编号，后端校验成 id。
    """
    by_index = {index: match.requirement_id for index, match in enumerate(matches, start=1)}
    rows = _normalize_ask_customer(items)
    for row in rows:
        ids: list[int] = []
        for ref in row.get("covers") or []:
            requirement_id = by_index.get(int(ref))
            if requirement_id and requirement_id not in ids:
                ids.append(requirement_id)
        row["covers"] = ids
    return rows


def _derive_sync_sales(matches: list[MatchResult]) -> list[dict]:
    """规则兜底：模型没给「要同步销售」的信息时，从判断结果直接推。

    只做站得住的推导 —— 暂不支持 → 别正面承诺；待补依据 → 先别表态；
    部分支持且带前置条件 → 对外说结论时要带上这个前提。
    同步的是"信息"不是待办，所以每条都写清不同步会出什么事（why）。
    """
    rows: list[dict] = []
    seen: set[str] = set()

    def push(info: str, to: str, why: str, urgency: str) -> None:
        key = info.strip()
        if not key or key in seen:
            return
        seen.add(key)
        rows.append({"info": key, "to": to, "why": why, "urgency": urgency})

    for match in matches:
        title = match.requirement.title if match.requirement else "这条需求"
        if match.status == "none":
            push(
                f"「{title}」目前没有能力依据，对客户先按暂不支持讲，不要正面承诺。",
                "销售",
                "销售先许了口，方案与交付兜不住时只能由公司背。",
                "high",
            )
        elif match.status == "unknown":
            push(
                f"「{title}」的证据还没补齐，对客户先按待补依据讲，等内部确认口径后再表态。",
                "销售",
                "结论没定就表态，后面要么改口、要么硬做。",
                "medium",
            )
        elif match.status == "partial" and match.condition:
            push(
                f"「{title}」的结论带前置条件：{match.condition}",
                "售前负责人",
                "不带上这个前提对外说，会被当成无条件承诺。",
                "medium",
            )
    return rows


def _normalize_sync_sales(items: list, matches: list[MatchResult]) -> list[dict]:
    """要同步销售的信息统一成 {info, to, why, urgency}；模型没给就按规则推。"""
    rows: list[dict] = []
    seen: set[str] = set()
    for item in items:
        if isinstance(item, dict):
            info = str(item.get("info") or item.get("text") or "").strip()
            to = str(item.get("to") or item.get("owner") or "销售").strip()
            why = str(item.get("why") or "").strip()
            urgency = str(item.get("urgency") or item.get("priority") or "").strip().lower()
        else:
            info, to, why, urgency = str(item or "").strip(), "销售", "", ""
        if not info or info in seen:
            continue
        seen.add(info)
        rows.append(
            {
                "info": info,
                "to": to or "销售",
                "why": why,
                "urgency": urgency if urgency in {"high", "medium", "low"} else "medium",
            }
        )
    return rows or _derive_sync_sales(matches)


def _fallback_solution(project: Project, matches: list[MatchResult], problem: str) -> dict:
    full = [m for m in matches if m.status == "full"]
    partial = [m for m in matches if m.status == "partial"]
    gaps = [m for m in matches if m.status == "none"]
    unknown = [m for m in matches if m.status == "unknown"]

    steps = []
    for match in full[:3]:
        steps.append(
            {
                "title": f"采用现有能力：{match.requirement.title}",
                "detail": match.headline,
                "based_on": [match.headline],
                "status": "full",
            }
        )
    for match in partial[:3]:
        steps.append(
            {
                "title": f"确认前置条件后纳入方案：{match.requirement.title}",
                "detail": f"{match.headline}。需先确认：{(match.confirmations or [match.condition])[0]}",
                "based_on": [match.headline],
                "status": "partial",
            }
        )
    for match in gaps[:2]:
        steps.append(
            {
                "title": f"评估定制或替代路径：{match.requirement.title}",
                "detail": (match.gaps or ["当前没有标准能力"])[0],
                "based_on": [match.headline],
                "status": "none",
            }
        )
    for match in unknown[:2]:
        steps.append(
            {
                "title": f"补齐信息后再判断：{match.requirement.title}",
                "detail": (match.confirmations or ["客户材料缺少关键信息"])[0],
                "based_on": [match.headline],
                "status": "unknown",
            }
        )

    risks = []
    for match in gaps:
        risks.append(
            {
                "level": "high",
                "title": f"能力缺口：{match.requirement.title}",
                "detail": (match.gaps or ["当前没有标准能力"])[0],
                "mitigation": "在正式方案中列为定制或可选部分，避免直接承诺。",
                "based_on": [match.requirement.title],
            }
        )
    for match in partial + unknown:
        risks.append(
            {
                "level": "medium",
                "title": f"范围与验收口径待确认：{match.requirement.title}",
                "detail": (match.confirmations or [match.condition or "存在前置条件"])[0],
                "mitigation": "写入方案风险项，并在启动阶段与客户冻结验收口径。",
                "based_on": [match.requirement.title],
            }
        )
    risks.append(
        {
            "level": "low",
            "title": "结论基于当前知识库版本",
            "detail": "若能力文档更新或补充新案例，需要重新匹配以确认结论。",
            "mitigation": "内部评审时补充最新项目经验，并对关键结论做人工复核。",
        }
    )

    summary = (
        f"共 {len(matches)} 条需求：完全支持 {len(full)} 条、部分支持 {len(partial)} 条、"
        f"暂不支持 {len(gaps)} 条、待补依据 {len(unknown)} 条。"
    )
    blocking = [m.requirement.title for m in gaps + unknown]
    summary += (
        f"整体方案在补齐 {len(blocking)} 项确认后可行，需重点处理：{'、'.join(blocking)}。"
        if blocking
        else "整体方案可行，可进入方案编制与报价阶段。"
    )

    ask_customer: list[dict] = []
    for index, match in enumerate(matches, start=1):
        for item in match.confirmations or []:
            if not item:
                continue
            ask_customer.append(
                {
                    "question": item,
                    "affects": "judge" if match.status in {"none", "unknown"} else "promise",
                    "covers": [index],
                }
            )

    return {
        "summary": summary,
        "steps": steps,
        "capability_plan": [],
        "ask_customer": ask_customer[:6],
        "ask_internal": [],
        "sync_sales": _derive_sync_sales(matches),
        "risks": risks,
        "next_actions": [
            {
                "action": f"向客户发送《需求确认清单》（{len(blocking)} 项待确认）",
                "owner": "售前负责人",
                "due": "1 个工作日内",
                "priority": "high",
            },
            {
                "action": "输出方案初稿与风险清单，完成内部技术评审",
                "owner": "售前 + 方案团队",
                "due": "10 个工作日内",
                "priority": "medium",
            },
            {
                "action": "内部评审通过后再向客户做正式技术承诺",
                "owner": "项目负责人",
                "due": "对客承诺前",
                "priority": "high",
            },
        ],
    }


async def compose_solution(
    db: Session,
    *,
    project: Project,
    matches: list[MatchResult],
    problem: str,
    actor: str,
    trace_id: str = "",
) -> Solution:
    # 带编号：模型在 based_on 里回编号，后端按编号校验成需求 id（比标题可靠）
    match_lines = "\n".join(
        f"{index}. {match.requirement.title}：{match.headline}"
        f"｜缺口：{(match.gaps or ['无'])[0]}｜待确认：{(match.confirmations or ['无'])[0]}"
        for index, match in enumerate(matches, start=1)
    )
    system = prompts.SOLUTION_SYSTEM
    user = prompts.solution_user_prompt(
        project_name=project.name,
        problem=problem,
        match_lines=match_lines,
        question_pool=_question_pool_lines(project, matches),
    )
    meta: dict[str, Any] = {}
    payload = await chat_json(
        system=system,
        user=user,
        schema_hint=prompts.SOLUTION_SCHEMA,
        fallback=lambda: _fallback_solution(project, matches, problem),
        required_keys=["summary"],
        meta=meta,
        trace_id=trace_id,
        step="solution",
        prompt_version=prompts.SOLUTION_PROMPT_VERSION,
        on_call=_ledger_recorder(db, project_id=project.id),
    )

    previous = (
        db.execute(select(Solution).where(Solution.project_id == project.id).order_by(Solution.version.desc()))
        .scalars()
        .first()
    )
    solution = Solution(
        project_id=project.id,
        problem=problem,
        summary=str(payload.get("summary") or ""),
        version=(previous.version + 1) if previous else 1,
        status="draft",
        # 步骤状态按判断结果校正：方案不能比判断更乐观
        steps=_validate_solution_steps(payload.get("steps") or [], matches),
        # 能力组合一律由检索结果聚合；只有在聚合为空时才用模型那份，且必须能对上知识库里的产品
        capability_plan=_capability_plan_from_matches(db, matches)
        or _known_products_only(db, payload.get("capability_plan") or []),
        reference_cases=_reference_cases_from_matches(db, matches),
        # covers 从"匹配结果编号"换成需求 id，前端才能按编号跟判断前提去重
        ask_customer=_attach_ask_customer_covers(payload.get("ask_customer") or [], matches),
        ask_internal=_normalize_ask_internal(payload.get("ask_internal") or []),
        # 要同步销售的是"信息"，模型没给就按判断结果推：暂不支持 → 别正面承诺；待补依据 → 先别表态
        sync_sales=_normalize_sync_sales(payload.get("sync_sales") or [], matches),
        # 风险与行动也要能回指依据：模型给需求标题，这里校验成库里的需求 id
        risks=_ensure_risks_for_judgements(
            _attach_requirement_ids(payload.get("risks") or [], matches), matches
        ),
        next_actions=_attach_requirement_ids(payload.get("next_actions") or [], matches),
    )
    db.add(solution)
    db.flush()
    logger.info("解决路径生成：项目 %s 版本 %s（操作人=%s）", project.id, solution.version, actor)
    return solution


def _reference_cases_from_matches(db: Session, matches: list[MatchResult]) -> list[dict]:
    """从匹配结果里聚合可参考的历史案例（按命中次数排序）。"""
    counter: dict[int, int] = {}
    for match in matches:
        for case_id in match.case_ids or []:
            counter[case_id] = counter.get(case_id, 0) + 1
    ordered = sorted(counter.items(), key=lambda item: item[1], reverse=True)[:3]

    references: list[dict] = []
    for case_id, hits in ordered:
        case = db.get(CaseStudy, case_id)
        if not case:
            continue
        titles = [
            match.requirement.title
            for match in matches
            if case_id in (match.case_ids or [])
        ][:2]
        references.append(
            {
                "case_id": case_id,
                "name": case.name,
                "reason": f"与「{'、'.join(titles)}」需求相似：{case.evidence_excerpt}",
                "hit_count": hits,
            }
        )
    return references


def _capability_plan_from_matches(db: Session, matches: list[MatchResult]) -> list[dict]:
    """按产品聚合匹配结果，形成推荐能力组合。"""
    plan: dict[str, dict] = {}
    rank = {"full": 3, "partial": 2, "unknown": 1, "none": 0}
    for match in matches:
        for doc_id in match.capability_doc_ids or []:
            doc = db.get(CapabilityDoc, doc_id)
            if not doc:
                continue
            entry = plan.setdefault(
                doc.product,
                {"product": doc.product, "role": "", "readiness": match.status, "status_counts": {}},
            )
            if match.requirement.title not in entry["role"]:
                entry["role"] = f"{entry['role']} / {match.requirement.title}".strip(" /")
            counts = entry["status_counts"]
            counts[match.status] = counts.get(match.status, 0) + 1
            if rank.get(match.status, 0) > rank.get(entry["readiness"], 0):
                entry["readiness"] = match.status
    return sorted(
        plan.values(),
        key=lambda item: item["status_counts"].get("full", 0) * 2 + item["status_counts"].get("partial", 0),
        reverse=True,
    )


def _known_products_only(db: Session, plan: list) -> list[dict]:
    """兜底：模型给的能力组合只保留知识库里有据可查的产品。

    正常情况下能力组合由 _capability_plan_from_matches 聚合；只有在聚合为空时才用模型那份，
    此时产品名必须能在能力库里对上 —— 模型不能凭空造一个产品放进推荐方案。
    """
    known = {
        row[0]
        for row in db.execute(select(CapabilityDoc.product).where(CapabilityDoc.status == "active")).all()
    }
    return [
        item
        for item in plan
        if isinstance(item, dict) and str(item.get("product") or "") in known
    ]
