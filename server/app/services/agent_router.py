"""单步 Agent 路由：一次调用决定「用材料回答」还是「提议哪个动作」。

P0 刻意不做多步循环：

1. 先用 material_search 拿材料片段（命中结果决定回答能引用什么）；
2. 一次 chat_json，让它要么给出带页码的回答，要么给出一个动作意图；
3. 动作只返回意图，由前端调用既有的 /requirements/extract、/matches/run、
   /solutions/generate 执行 —— 所以这一层是只读的，自己不改任何数据；
4. 引用（citations）一律由检索命中生成，模型只负责挑页码，挑不出就不给引用。

判断权仍然在规则层与人工手里：这里既不给结论上限，也不替人确认需求。
"""

from __future__ import annotations

import logging

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from .. import prompts
from ..models import MatchResult, Material, Project, Requirement, Solution
from . import ai_ledger, conversation, material_search
from .agents import _clip, _humanize
from .llm import chat_json

logger = logging.getLogger(__name__)

#: 允许 Agent 提议的动作。动作的资格还要过 _guard_tool，模型说了不算。
ALLOWED_TOOLS: dict[str, str] = {
    "run_full_analysis": "重新跑一遍分析",
    "run_extraction": "重新整理需求",
    "run_matching": "做能力判断",
    "compose_solution": "生成售前建议",
}

#: 需要人点头的动作（L2）：Agent 只准备，批准后才执行
APPROVAL_TOOLS: dict[str, str] = {
    "confirm_requirements": "确认需求",
}


def project_state(db: Session, project: Project) -> dict[str, int]:
    """项目状态就是 Agent 的世界模型：它决定「现在能不能做下一步」。"""
    materials = db.execute(
        select(
            func.count(Material.id),
            func.sum(case((Material.status == "parsed", 1), else_=0)),
            func.sum(case((Material.status == "failed", 1), else_=0)),
        ).where(Material.project_id == project.id)
    ).one()
    requirements = db.execute(
        select(
            func.sum(case((Requirement.status == "draft", 1), else_=0)),
            func.sum(case((Requirement.status == "confirmed", 1), else_=0)),
        ).where(Requirement.project_id == project.id)
    ).one()
    matches = db.execute(
        select(func.count(MatchResult.id)).where(MatchResult.project_id == project.id)
    ).scalar_one()
    solutions = db.execute(
        select(func.count(Solution.id)).where(Solution.project_id == project.id)
    ).scalar_one()
    return {
        "materials": materials[0] or 0,
        "materials_parsed": materials[1] or 0,
        "materials_failed": materials[2] or 0,
        "requirements_draft": requirements[0] or 0,
        "requirements_confirmed": requirements[1] or 0,
        "matches": matches,
        "solutions": solutions,
    }


def next_step(state: dict[str, int]) -> dict | None:
    """状态机：下一步做什么，由项目状态决定，不由模型决定。

    这是「Agent 读状态决定下一步」的唯一实现 —— 计划、界面上的下一步提示、
    计划（build_plan）都从它派生，避免各写一套顺序；能不能调某个工具则另由 _guard_tool 把关。
    """
    if state["materials"] == 0:
        return {"label": "先把客户材料拖进来", "tool": None, "blocked": True, "target": "materials"}
    if state["materials_failed"]:
        return {
            "label": f"重试 {state['materials_failed']} 份读取失败的材料",
            "tool": None,
            "blocked": True,
            "target": "materials",
        }
    if not (state["requirements_draft"] or state["requirements_confirmed"]):
        return {"label": "整理需求", "tool": "run_extraction", "blocked": False, "target": "requirements"}
    if not state["requirements_confirmed"]:
        return {
            "label": f"确认这 {state['requirements_draft']} 条需求",
            "tool": None,
            "blocked": True,
            "target": "requirements",
        }
    if not state["matches"]:
        return {"label": "做能力判断", "tool": "run_matching", "blocked": False, "target": "judgement"}
    if not state["solutions"]:
        return {"label": "生成售前建议", "tool": "compose_solution", "blocked": False, "target": "judgement"}
    return None


def build_plan(state: dict[str, int], limit: int = 4) -> tuple[list[str], dict | None]:
    """一条任务里能串多步：按状态机往下模拟，遇到人工闸门就停。

    返回（可自动执行的步骤, 停在哪一步）。停在一步说明那一步需要人来做 ——
    例如确认需求，Agent 不能替人确认。
    """
    simulated = dict(state)
    steps: list[str] = []
    for _ in range(limit):
        step = next_step(simulated)
        if not step or step["blocked"] or not step["tool"]:
            break
        steps.append(step["tool"])
        if step["tool"] == "run_extraction":
            simulated["requirements_draft"] = max(simulated["requirements_draft"], 1)
        elif step["tool"] == "run_matching":
            simulated["matches"] = max(simulated["matches"], 1)
        elif step["tool"] == "compose_solution":
            simulated["solutions"] = max(simulated["solutions"], 1)
    return steps, next_step(simulated)


def _state_lines(state: dict[str, int]) -> str:
    return "\n".join(
        [
            f"客户材料：{state['materials']} 份（已读完 {state['materials_parsed']}，读取失败 {state['materials_failed']}）",
            f"需求：待确认 {state['requirements_draft']} 条，已确认 {state['requirements_confirmed']} 条",
            f"能力判断：已完成 {state['matches']} 条",
        ]
    )


def _guard_tool(tool: str | None, state: dict[str, int]) -> tuple[str | None, str]:
    """动作的资格由项目状态决定，不由模型决定。返回 (允许的工具, 不允许时的说明)。"""
    if tool == "confirm_requirements":
        if not state["requirements_draft"]:
            return None, "现在没有待确认的需求。"
        return tool, ""
    if tool == "run_full_analysis":
        if not state["materials_parsed"]:
            return None, "还没有读成功的客户材料，先上传材料我才能分析。"
        return tool, ""
    if tool == "run_extraction":
        if not state["materials_parsed"]:
            return None, "还没有读成功的客户材料，先上传材料我才能整理需求。"
        return tool, ""
    if tool == "run_matching":
        if not state["requirements_confirmed"]:
            waiting = state["requirements_draft"]
            if waiting:
                return None, f"还有 {waiting} 条需求等着你确认 —— 确认之后我再做能力判断。"
            return None, "还没有确认过的需求，先整理并确认需求，我才能做能力判断。"
        return tool, ""
    if tool == "compose_solution":
        if not state["matches"]:
            return None, "还没有能力判断的结果，先做一轮判断，我再写售前建议。"
        return tool, ""
    return None, ""


def _looks_like_action(message: str) -> bool:
    text = message or ""
    return any(
        keyword in text
        for keyword in (
            "重新分析",
            "再分析",
            "跑一遍",
            "跑一次",
            "开始分析",
            "重新判断",
            "重新整理",
            "整理需求",
            "生成建议",
            "写个方案",
            "出个方案",
            "确认需求",
            "都确认",
            "确认高优先",
        )
    )


def _looks_like_full_run(message: str) -> bool:
    """「一条龙跑完」类请求：这时候才给它一份多步计划。"""
    text = message or ""
    return any(
        keyword in text
        for keyword in ("完整流程", "一条龙", "一路", "从材料到", "全都跑", "全部跑", "都跑一遍", "自动跑", "跑完流程", "从头跑")
    )


def _fallback_route(message: str, hits: list[material_search.Evidence], state: dict[str, int]) -> dict:
    """模型不可用时的确定性路由：动作规则 + 材料命中摘录。"""
    if _looks_like_action(message):
        no_requirement_yet = not state["requirements_draft"] and not state["requirements_confirmed"]
        if "确认" in message:
            return {
                "kind": "action",
                "tool": "confirm_requirements",
                "scope": "high" if "高优先" in message else "all",
                "text": "我把待确认的需求整理成清单，等你确认。",
                "citation_pages": [],
            }
        if "整理" in message and "分析" not in message:
            return {"kind": "action", "tool": "run_extraction", "text": "开始重新整理需求。", "citation_pages": []}
        if "判断" in message or "能不能做" in message:
            return {"kind": "action", "tool": "run_matching", "text": "开始做能力判断。", "citation_pages": []}
        if "建议" in message or "方案" in message:
            return {"kind": "action", "tool": "compose_solution", "text": "开始生成售前建议。", "citation_pages": []}
        if no_requirement_yet:
            return {"kind": "action", "tool": "run_extraction", "text": "先把材料里的需求整理出来。", "citation_pages": []}
        return {"kind": "action", "tool": "run_full_analysis", "text": "开始重新跑一遍分析。", "citation_pages": []}
    if hits:
        best = hits[0]
        where = f"第 {best.page} 页" if best.page else best.heading or ""
        return {
            "kind": "answer",
            "text": f"材料{where}写着：{_clip(best.text, 120)}",
            "citation_pages": [best.page] if best.page else [],
        }
    return {"kind": "answer", "text": "材料里没有找到相关的内容。", "citation_pages": []}


def _citations(payload: dict, hits: list[material_search.Evidence]) -> list[dict]:
    """引用只从检索命中里取：页码对不上就不给引用。"""
    wanted: set[int] = set()
    for item in payload.get("citation_pages") or []:
        try:
            wanted.add(int(item))
        except (TypeError, ValueError):
            continue
    if not wanted:
        return []
    picked: list[dict] = []
    for hit in hits:
        key = (hit.material_id, hit.page)
        if hit.page not in wanted or any(item["material_id"] == key[0] and item["page"] == key[1] for item in picked):
            continue
        picked.append(
            {
                "material_id": hit.material_id,
                "document_name": hit.document_name,
                "page": hit.page,
                "excerpt": _clip(hit.text, 160),
            }
        )
    return picked[:3]


def draft_targets(db: Session, project_id: int) -> tuple[list[int], list[int]]:
    """待确认需求的 id：全部，以及其中的高优先级。批准卡里的 id 由这里来，不由模型给。"""
    rows = db.execute(
        select(Requirement.id, Requirement.priority).where(
            Requirement.project_id == project_id,
            Requirement.status == "draft",
        )
    ).all()
    return [row[0] for row in rows], [row[0] for row in rows if row[1] == "high"]


def _normalize(
    payload: dict,
    *,
    message: str,
    hits: list[material_search.Evidence],
    state: dict[str, int],
    drafts: list[int],
    highs: list[int],
) -> dict:
    text = _humanize(str(payload.get("text") or "").strip())[:300]
    if str(payload.get("kind") or "") == "action":
        tool, blocked = _guard_tool(payload.get("tool"), state)
        if not tool:
            return {
                "kind": "answer",
                "text": blocked or "这一步现在做不了。",
                "citations": [],
                "tool": None,
                "tool_label": None,
                "problem": None,
            }
        if tool in APPROVAL_TOOLS:
            # L2：只准备，不执行。id 由后端按状态算，模型只能选"全部还是高优先级"。
            scope = str(payload.get("scope") or "all")
            chosen = highs if scope == "high" and highs else drafts
            chosen_high = len([item for item in chosen if item in set(highs)])
            detail = (
                f"把 {len(chosen)} 条 AI 推断的需求设为基线"
                + (f"（其中高优先级 {chosen_high} 条）" if chosen_high else "")
                + "；确认之后我会自动开始能力判断，你只需要批准这一下。"
            )
            return {
                "kind": "approval",
                "text": text or f"我准备好了 {len(chosen)} 条需求，等你确认。",
                "citations": [],
                "tool": tool,
                "tool_label": APPROVAL_TOOLS[tool],
                "problem": None,
                "approval": {
                    "tool": tool,
                    "label": APPROVAL_TOOLS[tool],
                    "detail": detail,
                    "payload": {"ids": chosen},
                },
            }
        return {
            "kind": "action",
            "text": text or f"开始{ALLOWED_TOOLS[tool]}。",
            "citations": [],
            "tool": tool,
            "tool_label": ALLOWED_TOOLS[tool],
            # 让用户的问法直接成为建议里的「客户问题」
            "problem": message if tool == "compose_solution" else None,
        }
    citations = _citations(payload, hits)
    return {
        "kind": "answer",
        "text": text or "材料里没有找到相关的内容。",
        "citations": citations,
        "tool": None,
        "tool_label": None,
        "problem": None,
    }


async def route_message(db: Session, *, project: Project, message: str, trace_id: str = "") -> dict:
    state = project_state(db, project)

    # 一条龙请求：给一份按状态机算出来的多步计划（遇人工闸门就停在闸门前）
    if _looks_like_full_run(message):
        steps, gate = build_plan(state)
        if steps:
            result = {
                "kind": "plan",
                "text": f"好，我按顺序跑这 {len(steps)} 步：{' → '.join(ALLOWED_TOOLS[item] for item in steps)}。",
                "citations": [],
                "tool": None,
                "tool_label": None,
                "problem": message,
                "steps": steps,
                "gate": gate,
                "next_step": next_step(state),
            }
            conversation.append(db, project_id=project.id, role="user", kind="text", text=message)
            saved = conversation.append(
                db,
                project_id=project.id,
                role="agent",
                kind="text",
                text=result["text"],
                data={"steps": steps, "gate": gate, "next_step": result["next_step"]},
            )
            result["message_id"] = saved.id
            return result
        # 没有可跑的步骤：如实说明现在卡在哪
        hold = gate["label"] if gate else "现在没有需要重跑的步骤"
        result = {
            "kind": "answer",
            "text": f"{hold}。" if gate else "该做的都做完了，直接看售前建议就行。",
            "citations": [],
            "tool": None,
            "tool_label": None,
            "problem": None,
            "steps": [],
            "gate": gate,
            "next_step": gate,
        }
        conversation.append(db, project_id=project.id, role="user", kind="text", text=message)
        saved = conversation.append(
            db,
            project_id=project.id,
            role="agent",
            kind="text",
            text=result["text"],
            data={"next_step": gate},
        )
        result["message_id"] = saved.id
        return result

    hits = material_search.search_evidence(
        db,
        project_id=project.id,
        highlights=project.highlights or [],
        query=message,
        top_k=6,
    )
    drafts, highs = draft_targets(db, project.id)

    facts = [hit for hit in hits if hit.kind == "fact"]
    chunks = [hit for hit in hits if hit.kind == "chunk"]
    blocks: list[str] = []
    if facts:
        blocks.append(
            "【项目要点（已经从材料里核对过的事实）】\n"
            + "\n".join(
                f"- 第 {hit.page or '-'} 页 · {hit.heading}：{_clip(hit.text, 200)}" for hit in facts
            )
        )
    if chunks:
        blocks.append(
            "【材料原文片段】\n"
            + "\n\n".join(
                f"[第 {hit.page} 页 · {hit.document_name}]\n{_clip(hit.text, 400)}" for hit in chunks
            )
        )
    evidence = "\n\n".join(blocks) or "（材料里没有找到相关片段）"
    system = prompts.ROUTE_SYSTEM
    user = prompts.route_user_prompt(
        project_name=project.name,
        state_lines=_state_lines(state),
        evidence=evidence,
        message=message,
    )
    payload = await chat_json(
        system=system,
        user=user,
        schema_hint=prompts.ROUTE_SCHEMA,
        fallback=lambda: _fallback_route(message, hits, state),
        trace_id=trace_id,
        step="route",
        prompt_version=prompts.ROUTE_PROMPT_VERSION,
        on_call=lambda entry: ai_ledger.record(db, project_id=project.id, **entry),
    )
    result = _normalize(
        payload,
        message=message,
        hits=hits,
        state=state,
        drafts=drafts,
        highs=highs,
    )
    result["steps"] = []
    result["next_step"] = next_step(state)

    # 会话落库：刷新页面、第二天回来，Agent 还知道聊过什么
    conversation.append(db, project_id=project.id, role="user", kind="text", text=message)
    saved = conversation.append(
        db,
        project_id=project.id,
        role="agent",
        kind="text",
        text=result["text"],
        data={
            "citations": result["citations"],
            "tool": result["tool"],
            "tool_label": result["tool_label"],
            "problem": result["problem"],
            "next_step": result["next_step"],
            "approval": result.get("approval"),
        },
    )
    result["message_id"] = saved.id
    logger.info(
        "Agent 路由：项目 %s kind=%s tool=%s 命中片段=%s",
        project.id,
        result["kind"],
        result["tool"],
        len(hits),
    )
    return result
