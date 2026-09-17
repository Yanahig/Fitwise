"""回归脚本共用的评测分数表。

跑通链路只是"没坏"；分数表回答的是"这一版 Agent 的硬性质还在不在"：
  ① 证据化：每条结论 / 风险 / 行动都能回指真实文档 + 页码
  ② 不比证据乐观：结论是「完全支持」就必须有支持类证据（越界率必须为 0）
  ③ 建议可用：三组清单非空（要问客户 / 要问内部 / 要同步销售）、对客与内部不重复、风险有轻重
  ④ 需要人确认的动作必须停下来等人批准，且留痕由服务端写

e2e_smoke.py 与 check_agent_conversation.py 各打一张表，regression_check.py 会把两张都带出来。
"""

from __future__ import annotations

CHECKS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    CHECKS.append((name, ok, detail))
    print(f"   {'✓' if ok else '✗'} {name}" + (f"：{detail}" if detail else ""))
    return ok


def print_scorecard(title: str = "评测分数表") -> int:
    """打印分数表；返回 1 表示有未过项（可以直接当进程退出码用）。"""
    print(f"\n================ {title} ================")
    for name, ok, detail in CHECKS:
        print(f"[{'OK' if ok else 'XX'}] {name}" + (f"｜{detail}" if detail else ""))
    failed = [name for name, ok, _ in CHECKS if not ok]
    passed = len(CHECKS) - len(failed)
    tail = "（全部通过 ✅）" if not failed else f"；未过：{'、'.join(failed)}"
    print(f"\n结果：{passed}/{len(CHECKS)} 通过{tail}")
    return 1 if failed else 0


def norm(text: str) -> str:
    """去空白的归一化文本：比较标题/问题时不受空格与换行影响。"""
    return "".join((text or "").split())
