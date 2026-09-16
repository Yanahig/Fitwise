"""提示词集中管理：一次改动只动这里，版本号跟着一起走。

见 docs/agent-core-design.md 第 5 节。要点：

1. 四个 agent 步骤（抽取 / 判断 / 建议 / 路由）的指令、schema 与输入模板都放在这个文件里，
   agents.py 与 agent_router.py 只负责准备数据、调用并落库；
2. 每一步有独立的版本号，连同模型名一起写进 AI 调用账本（ai_calls）与判断轨迹 ——
   「这条结论是哪版提示词算出来的」必须能回答；
3. PROMPT_SET_VERSION 是整体版本：改了任何一步就一起递增，方便按批次做回归对比。

改提示词的正确姿势：改文本 → 递增对应版本号 → 跑 scripts/regression_check.py 对比前后差异。
"""

from __future__ import annotations

#: 整体版本。任何一步提示词有改动就递增（格式：日期.序号）。
PROMPT_SET_VERSION = "2026-09-16.1"

EXTRACT_PROMPT_VERSION = f"extract@{PROMPT_SET_VERSION}"
JUDGE_PROMPT_VERSION = f"judge@{PROMPT_SET_VERSION}"
SOLUTION_PROMPT_VERSION = f"solution@{PROMPT_SET_VERSION}"
ROUTE_PROMPT_VERSION = f"route@{PROMPT_SET_VERSION}"

PROMPT_VERSIONS = {
    "extract": EXTRACT_PROMPT_VERSION,
    "judge": JUDGE_PROMPT_VERSION,
    "solution": SOLUTION_PROMPT_VERSION,
    "route": ROUTE_PROMPT_VERSION,
}


# --------------------------------------------------------------------------- #
# 结构化输出 schema（作为提示词的一部分发给模型）
# --------------------------------------------------------------------------- #

REQUIREMENT_SCHEMA = """{
  "customer_name": "从材料里识别出的客户单位名称；材料里没写就留空字符串",
  "project_name": "从材料里识别出的项目名称；材料里没写就留空字符串",
  "requirements": [{
    "title": "需求短标题（不超过 18 字）",
    "detail": "需求描述，保留客户口径",
    "category": "部署|产品能力|技术|合规|规模|服务",
    "priority": "high|medium|low",
    "tags": ["能力标签，从需求中推断"],
    "constraints": ["客户提出的硬性约束"],
    "source_material_name": "来源文件名（必须与输入材料名一致）",
    "source_page": 1,
    "source_heading": "来源章节",
    "source_excerpt": "来源原文片段（不超过 80 字）"
  }],
  "open_questions": [{
    "question": "待澄清问题",
    "why": "为什么要问",
    "owner": "客户|内部"
  }],
  "project_facts": [{
    "label": "客户与项目|建设范围|工期口径|预算|交付环境|关键时间点|决策链",
    "value": "从材料里摘出的客观事实，不加判断、不写建议",
    "source_material_name": "来源文件名（必须与输入材料名一致）",
    "source_page": 1,
    "source_excerpt": "来源原文片段（不超过 60 字）"
  }],
  "material_summaries": [{
    "material_name": "来源文件名（必须与输入材料名一致）",
    "summary": "这份材料整体写了什么，一句话、不超过 60 字，只讲事实"
  }]
}"""

JUDGE_SCHEMA = """{
  "status": "full|partial|none|unknown",
  "headline": "一句话结论（不超过 40 字）",
  "condition": "非完全支持时的一句话前置条件或缺口",
  "rationale": "为什么这样判断，必须引用客户来源与企业证据（含页码）",
  "gaps": ["能力缺口或前置条件"],
  "confirmations": ["需要继续确认的问题"],
  "confidence": 0.0
}"""

SOLUTION_SCHEMA = """{
  "summary": "整体判断（2-3 句）",
  "steps": [{ "title": "", "detail": "", "based_on": ["依据的产品或案例"], "status": "full|partial|none|unknown" }],
  "capability_plan": [{ "product": "", "role": "", "readiness": "full|partial|none|unknown" }],
  "ask_customer": ["需要向客户确认的问题"],
  "ask_internal": [{ "question": "需要内部确认的问题", "owner": "平台研发|产品团队|交付团队|售前负责人" }],
  "risks": [{ "level": "high|medium|low", "title": "", "detail": "", "mitigation": "", "based_on": [1, 3] }],
  "next_actions": [{ "action": "", "owner": "", "due": "", "priority": "high|medium|low", "based_on": [1] }]
}"""

ROUTE_SCHEMA = """{
  "kind": "answer 或 action",
  "text": "给用户看的话，不超过 80 字；kind=action 时说明你要做什么",
  "citation_pages": [引用了材料第几页，没有就空数组],
  "tool": "run_full_analysis / run_extraction / run_matching / compose_solution / confirm_requirements；kind=answer 时为 null",
  "scope": "tool=confirm_requirements 时填 all（全部待确认）或 high（只确认高优先级），其余为 null"
}"""


# --------------------------------------------------------------------------- #
# system 提示词
# --------------------------------------------------------------------------- #

EXTRACT_SYSTEM = (
    "你是企业售前的需求分析助手。请从客户材料中抽取核心需求、需求分类、优先级、硬性约束与待确认问题。"
    "每条需求必须给出真实来源（文件名 + 页码）；材料中没有明确的信息要放入 open_questions，不要编造。"
    "表达用售前听得懂的口语化中文，不要使用技术或工程术语（例如「基线」「落库」「模型」「检索」）。"
)

JUDGE_SYSTEM = (
    "你是企业售前决策助手，负责判断客户需求能否被企业现有能力满足。"
    "必须做判断而不是总结；结论只能引用下面给出的证据；证据中没有的能力不得推断为支持；"
    "不输出最终承诺，只输出售前初步判断。"
    "表达用售前听得懂的口语化中文，不要使用技术或工程术语（例如「基线」「落库」「模型」「检索」「置信度」）。"
)

SOLUTION_SYSTEM = (
    "你是企业售前的方案助手。请基于已完成的「需求 × 企业能力匹配结果」给出解决路径与下一步行动。"
    "不得承诺知识库中没有的能力；风险与待确认项必须明确列出；输出面向售前的可执行建议。"
    "表达用售前听得懂的口语化中文，不要使用技术或工程术语（例如「基线」「落库」「模型」「检索」）。"
)

ROUTE_SYSTEM = (
    "你是企业售前助手 Fitwise，负责回答关于这个项目的问题，并在合适的时候提议下一步动作。"
    "只能使用下面给出的材料片段与项目状态作答；材料里没有写的信息必须说「材料里没有提到」，不要推测。"
    "只有当用户明确要求推进（重新整理需求 / 做能力判断 / 生成售前建议）时才返回 action，其余一律 answer。"
    "判断能不能做、给方案是另外的步骤，你只是提议，不要自己下结论。"
    "用户在打招呼或闲聊时正常回应，不要回一句「材料里没有提到」。"
    "表达用售前听得懂的口语化中文，不要出现「模型」「检索」「落库」「置信度」这类词。"
)


# --------------------------------------------------------------------------- #
# user 提示词：只做模板拼装，数据由调用方准备好再传进来
# --------------------------------------------------------------------------- #


def extract_user_prompt(*, project_name: str, digest: str) -> str:
    """材料 digest → 需求抽取的 user 提示词。"""
    return "\n".join(
        [
            f"【项目】{project_name}",
            "【客户材料如下，格式为 (P页码·章节) 原文】",
            digest,
            "【抽取要求】",
            "1. 只抽取客户明确提出的需求，同一件事只输出一条：即使材料里分处不同段落/不同页码去描述"
            "同一个要求（例如接口与并发写在两处），也要合并成一条，不要拆成两条近义需求；",
            "2. category 只能是 部署/产品能力/技术/合规/规模/服务 之一；",
            "3. source_material_name 必须与上面的材料名完全一致，source_page 必须是该材料中出现的页码；",
            "4. 材料中未明确、但会影响判断的信息，写入 open_questions。",
            "4.1 另外识别两样东西：customer_name（客户单位名称，例如「XX市档案馆」）与 project_name"
            "（项目名称，20 字以内，去掉客户单位名与「招标需求书 / RFP / 建设项目」这类字样，"
            "例如「档案数字化与智能处理平台」）。只从材料的标题、抬头、落款里认，"
            "认不出就留空字符串，不要自己编一个名字。",
            "5. 另外摘出 3-8 条 project_facts，label 只能从这七个里选：客户与项目 / 建设范围 / 工期口径 / "
            "预算 / 交付环境 / 关键时间点 / 决策链；不要自创分类。",
            "6. project_facts 只写材料里明确写着的客观事实，不写判断、不写建议；「关键时间点」只写日期与里程碑"
            "（答疑截止、投标截止、上线时间），接口与性能要求不要放进来；每条必须给出 source_material_name、"
            "source_page 与 source_excerpt；同一件事在不同材料里口径不一致时按原文各记一条"
            "（例如「工期口径：RFP 要求 4 个月」与「工期口径：07-22 邮件改为 3 个月」）。",
            "7. material_summaries 要为每一份材料写一句：这份材料整体写了什么（不超过 60 字），"
            "只讲事实、不写判断，material_name 必须与材料名完全一致 —— 它会显示在材料清单里，供人一眼知道这堆材料是什么。",
        ]
    )


def judge_user_prompt(
    *,
    title: str,
    detail: str,
    source_material_name: str,
    source_page: int | None,
    source_excerpt: str,
    evidence_block: str,
    case_block: str,
) -> str:
    """一条需求 + 检索到的证据 → 能力判断的 user 提示词。"""
    return "\n".join(
        [
            f"【客户需求】{title}",
            f"需求描述：{detail}",
            f"客户来源：{source_material_name} P{source_page or '-'} —— {source_excerpt}",
            "",
            "【企业能力证据】",
            evidence_block,
            "",
            "【历史成功案例】",
            case_block,
            "",
            "【判断要求】",
            "1. status 只能是 full（完全支持）/ partial（部分支持）/ none（暂不支持）/ unknown（信息不足需要确认）；",
            "2. 结论必须能回溯到上面的文档名与页码；",
            "3. 缺少证据时输出 unknown，并说明需要确认什么；",
            "4. headline 用一句话说明企业能力现状，condition 写明前置条件或缺口。",
        ]
    )


def solution_user_prompt(*, project_name: str, problem: str, match_lines: str) -> str:
    """匹配结果清单 → 售前建议的 user 提示词。"""
    return "\n".join(
        [
            f"【项目】{project_name}",
            f"【客户问题】{problem}",
            "【匹配结果】",
            match_lines or "（尚未完成能力匹配）",
            "",
            "【要求】",
            "1. 解决路径按“可直接使用的能力 → 需确认的前置条件 → 需要补信息或定制的部分”排序；",
            "2. ask_customer 是问客户的问题，ask_internal 是要内部拉通的问题（含责任方）；",
            "3. 风险分为 high / medium / low，每条都要有应对建议；",
            "4. next_actions 要具体、可指派、带时限；",
            "5. risks 与 next_actions 每条都必须写 based_on：填上面匹配结果里的**需求编号**（整数数组，"
            "例如 [1, 3]），编号必须来自上面的列表，至少一个 —— 售前会顺着它去核对依据。",
        ]
    )


def route_user_prompt(*, project_name: str, state_lines: str, evidence: str, message: str) -> str:
    """项目状态 + 材料片段 + 用户提问 → 对话路由的 user 提示词。"""
    return "\n".join(
        [
            f"【项目】{project_name}",
            "【项目状态】",
            state_lines,
            "",
            "【可用证据】",
            evidence,
            "",
            f"【用户的问题】{message}",
            "",
            "【要求】",
            "1. 回答里只要用到了上面的内容，就必须把对应页码放进 citation_pages；",
            "2. 上面没有的，直接说没有提到，citation_pages 留空；",
            "3. 用户只是问信息时不要返回 action；",
            "4. 动作与研究口径：说「重新分析 / 跑一遍分析」用 run_full_analysis；"
            "说「整理需求」用 run_extraction；说「能不能做 / 做判断」用 run_matching；"
            "说「出方案 / 写建议」用 compose_solution；"
            "说「确认需求 / 都确认了 / 确认高优先级」用 confirm_requirements，"
            "并在 scope 里填 all 或 high（确认需求需要用户批准，你只负责准备清单）。",
        ]
    )
