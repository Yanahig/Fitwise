"""自检 guardrail 的确定性自测：不调模型、不连数据库。

跑法：.venv\\Scripts\\python.exe scripts\\check_agent_guardrail.py

覆盖 docs/agent-core-design.md 第 3 节里的判定规则：支持信号缺失、支持与缺口冲突、
未验证页码、来源缺失、规则回退留痕，以及"只降不升"的封顶逻辑与待确认问题的合并去重。
"""

from __future__ import annotations

import sys
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent / "server"
sys.path.insert(0, str(SERVER_DIR))

from app.models import CapabilityDoc, CapabilitySignal, MatchResult, Requirement  # noqa: E402
from app.services import agents, retrieval  # noqa: E402


def make_doc(doc_id: int = 1, product: str = "星云 OCR") -> CapabilityDoc:
    return CapabilityDoc(
        id=doc_id,
        product=product,
        title=f"{product} 产品能力说明",
        version="v3.2",
        status="active",
    )


def make_signal(kind: str, page: int, excerpt: str) -> CapabilitySignal:
    return CapabilitySignal(kind=kind, page=page, heading="2.1 识别对象", text=excerpt, excerpt=excerpt)


def make_hit(doc: CapabilityDoc, *, support=(), constraints=()) -> retrieval.DocHit:
    return retrieval.DocHit(
        doc=doc,
        score=6.0,
        matched_tags=["ocr"],
        signals=[retrieval.SignalHit(signal=item, relevance=1.0) for item in support],
        constraints=[retrieval.SignalHit(signal=item, relevance=1.0) for item in constraints],
    )


def make_requirement(**overrides) -> Requirement:
    base = {
        "id": 1,
        "project_id": 1,
        "title": "票据识别准确率不低于 99%",
        "detail": "客户要求字段级准确率不低于 99%。",
        # source_material_id 给非空值：db=None 时跳过"来源能否定位"这一项（离线自测用）
        "source_material_id": 1,
        "source_material_name": "RFP.pdf",
        "source_page": 12,
        "source_excerpt": "字段级准确率不低于 99%。",
        "tags": ["ocr"],
    }
    base.update(overrides)
    return Requirement(**base)


def verdict_of(requirement: Requirement, *, hits, status, rationale) -> dict:
    return agents.evidence_guardrail(
        None,
        requirement=requirement,
        hits=list(hits),
        case_hits=[],
        status=status,
        rationale=rationale,
    )


def codes_of(verdict: dict) -> set[str]:
    return {str(item.get("code")) for item in verdict.get("reasons", [])}


def case_clean_full() -> str:
    """有支持信号、理由只引用证据页码：自检不应标记。"""
    doc = make_doc()
    hits = [make_hit(doc, support=[make_signal("support", 12, "标准印刷体字段级准确率 98.6%")])]
    verdict = verdict_of(
        make_requirement(), hits=hits, status="full", rationale="企业能力说明第 12 页给出准确率指标。"
    )
    assert not verdict["flagged"], f"不应被标记，实际 reasons={verdict['reasons']}"
    capped, notes = agents._cap_status_by_guardrail("full", verdict)
    assert capped == "full" and not notes, f"不应降级，实际 {capped} {notes}"
    return "有支持信号且页码可核 → 保持完全支持"


def case_full_without_support() -> str:
    """结论完全支持但没有支持信号：必须降级。"""
    doc = make_doc()
    hits = [make_hit(doc, constraints=[make_signal("limit", 14, "低质量影像准确率下降")])]
    verdict = verdict_of(make_requirement(), hits=hits, status="full", rationale="企业能力说明第 14 页。")
    assert "no_support_signal" in codes_of(verdict), verdict
    capped, notes = agents._cap_status_by_guardrail("full", verdict)
    assert capped == "partial" and notes, f"应降为部分支持，实际 {capped}"
    return "完全支持但无支持信号 → 降为部分支持"


def case_support_conflict_with_gap() -> str:
    """同时命中支持与缺口：不能判完全支持。"""
    doc = make_doc()
    hits = [
        make_hit(
            doc,
            support=[make_signal("support", 6, "支持标准票据识别")],
            constraints=[make_signal("gap", 20, "财政电子票据不在标准范围内")],
        )
    ]
    verdict = verdict_of(make_requirement(), hits=hits, status="full", rationale="见第 6 页与第 20 页。")
    assert "support_conflict_with_gap" in codes_of(verdict), verdict
    capped, _ = agents._cap_status_by_guardrail("full", verdict)
    assert capped == "partial", capped
    return "支持与缺口冲突 → 降为部分支持"


def case_unverified_citation() -> str:
    """理由里出现证据之外的页码：标记但不拦结论。"""
    doc = make_doc()
    hits = [make_hit(doc, support=[make_signal("support", 12, "标准印刷体字段级准确率 98.6%")])]
    verdict = verdict_of(make_requirement(), hits=hits, status="partial", rationale="详见第 99 页。")
    assert "unverified_citation" in codes_of(verdict), verdict
    assert not verdict["flagged"], "未验证页码只应告警，不应拦结论"
    return "理由页码对不上 → 告警但不拦"


def case_source_missing() -> str:
    """需求没有可回指的来源：必须标记并封顶。"""
    hits = [make_hit(make_doc(), support=[make_signal("support", 12, "…")])]
    verdict = verdict_of(
        make_requirement(source_material_id=None, source_page=None, source_excerpt=""),
        hits=hits,
        status="full",
        rationale="见第 12 页。",
    )
    assert "source_missing" in codes_of(verdict), verdict
    capped, _ = agents._cap_status_by_guardrail("full", verdict)
    assert capped == "partial", capped
    return "需求没有来源 → 标记并降为部分支持"


def case_fallback_visible() -> str:
    """规则回退要留痕，便于界面标注「本次为规则结果」。"""
    doc = make_doc()
    hits = [make_hit(doc, support=[make_signal("support", 12, "…")])]
    verdict = agents.evidence_guardrail(
        None,
        requirement=make_requirement(),
        hits=hits,
        case_hits=[],
        status="full",
        rationale="见第 12 页。",
        fallback_used=True,
    )
    assert "llm_fallback" in codes_of(verdict), verdict
    assert not verdict["flagged"], "回退只应告警"
    return "规则回退 → 留痕但不拦"


def case_merge_open_questions() -> str:
    """待确认问题只增不丢：重跑不能冲掉已处理过的条目。"""
    existing = [{"question": "工期以哪一版为准？", "why": "两份材料口径不同", "owner": "客户"}]
    fresh = [
        {"question": "工期以哪一版为准？", "why": "重复", "owner": "客户"},
        {"question": "韩语是否纳入本期？", "why": "标准版不支持", "owner": "内部", "source": "guardrail"},
    ]
    merged = agents.merge_open_questions(existing, fresh)
    assert len(merged) == 2, merged
    assert merged[0].get("why") == "两份材料口径不同", "已存在的条目不能被新结果覆盖"
    return "待确认问题合并去重、老条目不被覆盖"


def case_step_status_capped() -> str:
    """方案步骤的状态不能比它依据的判断更乐观。"""
    matches = [MatchResult(id=1, project_id=1, requirement_id=7, status="partial", headline="部分支持")]
    steps = [
        {"title": "直接采用现有能力", "detail": "…", "status": "full", "based_on": [1]},
        {"title": "继续调研", "detail": "…", "status": "unknown"},
    ]
    rows = agents._validate_solution_steps(steps, matches)
    assert rows[0]["status"] == "partial" and rows[0].get("status_capped"), rows[0]
    assert rows[0]["status_verified"] is True, rows[0]
    assert rows[1]["status_verified"] is False, rows[1]
    return "方案步骤状态被判断结果校正，无依据的步骤标未校验"


CASES = [
    case_clean_full,
    case_full_without_support,
    case_support_conflict_with_gap,
    case_unverified_citation,
    case_source_missing,
    case_fallback_visible,
    case_merge_open_questions,
    case_step_status_capped,
]


def main() -> int:
    failures = 0
    for item in CASES:
        try:
            detail = item()
            print(f"[PASS] {item.__name__} —— {detail}")
        except AssertionError as error:
            failures += 1
            print(f"[FAIL] {item.__name__} —— {error}")
        except Exception as error:  # noqa: BLE001
            failures += 1
            print(f"[ERROR] {item.__name__} —— {type(error).__name__}: {error}")
    print(f"\n{len(CASES) - failures}/{len(CASES)} 通过")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
