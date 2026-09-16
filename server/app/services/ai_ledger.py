"""AI / 解析调用账本：一次用户动作一个 trace_id。

见 docs/agent-core-design.md 第 5 节。这张表同时解决三件事：

1. **成本**：按步骤、按项目算调用次数与 token，能回答「贵在哪一步」；
2. **可观测**：出错时能回答「这次运行调了什么、哪一步失败、失败码是什么」；
3. **版本追溯**：每条记录带 model 与 prompt_version，配合判断轨迹可回答
   「这条结论是哪版模型、哪版提示词算出来的」。

一条硬规矩：**写账本不能影响业务**。写入用 savepoint 隔离，写不进去只记日志，
不抛异常、不回滚业务事务 —— 观测能力再重要也不该把主线搞挂。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from ..models import AiCall

logger = logging.getLogger(__name__)

#: 失败成因码。前面几个是可重试的（网络与限流），后面几个重试也没用。
ERROR_TIMEOUT = "timeout"
ERROR_NETWORK = "network"
ERROR_RATE_LIMIT = "rate_limit"
ERROR_SERVER = "server_error"
ERROR_AUTH = "auth"
ERROR_BAD_REQUEST = "bad_request"
ERROR_BAD_JSON = "bad_json"
ERROR_MISSING_KEYS = "missing_keys"
ERROR_NO_API_KEY = "no_api_key"
ERROR_CONTENT = "content"
ERROR_UNKNOWN = "unknown"

#: 重试没有意义、只会白等一轮的成因。其余（超时、网络、限流、5xx、输出不合规、
#: 未归类异常）都重试一次 —— 模型输出有随机性，缺字段/JSON 不合规时再试一次经常就好了，
#: 这也是 agent 设计文档里「不合规就重试，再不合规走规则回退」的落实。
NON_RETRYABLE_CODES = frozenset(
    {ERROR_AUTH, ERROR_BAD_REQUEST, ERROR_NO_API_KEY, ERROR_CONTENT}
)


def is_retryable(error_code: str) -> bool:
    """这个失败值不值得重试：网络抖动值得，凭据错、内容不合规不值得。"""
    return error_code not in NON_RETRYABLE_CODES


def record(
    db: Session,
    *,
    trace_id: str = "",
    project_id: int | None = None,
    step: str = "",
    provider: str = "",
    model: str = "",
    prompt_version: str = "",
    attempts: int = 0,
    latency_ms: int = 0,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    fallback_used: bool = False,
    ok: bool = True,
    error_code: str = "",
    error: str = "",
) -> None:
    """记一条调用。任何异常都被吞掉并记日志 —— 账本坏了不能让主线跟着坏。"""
    try:
        with db.begin_nested():
            db.add(
                AiCall(
                    trace_id=trace_id or "",
                    project_id=project_id,
                    step=step,
                    provider=provider[:80],
                    model=model[:80],
                    prompt_version=prompt_version[:48],
                    attempts=attempts,
                    latency_ms=max(0, int(latency_ms)),
                    prompt_tokens=max(0, int(prompt_tokens)),
                    completion_tokens=max(0, int(completion_tokens)),
                    fallback_used=fallback_used,
                    ok=ok,
                    error_code=error_code[:40],
                    error=(error or "")[:300],
                )
            )
    except Exception as failure:  # noqa: BLE001 - 账本失败不影响业务
        logger.warning("AI 调用账本写入失败（不影响本次运行）：%s", failure)


def trace_calls(db: Session, *, trace_id: str, limit: int = 200) -> list[AiCall]:
    """一次运行的全部调用，按时间顺序 —— 复盘一条链路就看这个。"""
    if not trace_id:
        return []
    return list(
        db.execute(
            select(AiCall)
            .where(AiCall.trace_id == trace_id)
            .order_by(AiCall.created_at, AiCall.id)
            .limit(limit)
        )
        .scalars()
        .all()
    )


def project_calls(db: Session, *, project_id: int, limit: int = 50) -> list[AiCall]:
    return list(
        db.execute(
            select(AiCall)
            .where(AiCall.project_id == project_id)
            .order_by(AiCall.created_at.desc(), AiCall.id.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )


def project_summary(db: Session, *, project_id: int, limit: int = 50) -> dict[str, Any]:
    """按步骤汇总：调用次数、token、失败、回退、平均耗时 —— 成本与质量的同一份口径。"""
    rows = db.execute(
        select(
            AiCall.step,
            func.count(AiCall.id),
            func.sum(AiCall.prompt_tokens),
            func.sum(AiCall.completion_tokens),
            func.sum(case((AiCall.ok.is_(False), 1), else_=0)),
            func.sum(case((AiCall.fallback_used.is_(True), 1), else_=0)),
            func.avg(AiCall.latency_ms),
        )
        .where(AiCall.project_id == project_id)
        .group_by(AiCall.step)
    ).all()

    by_step: list[dict[str, Any]] = []
    calls = 0
    prompt_tokens = 0
    completion_tokens = 0
    failed = 0
    fallback = 0
    latency_weighted = 0.0
    for step, count, prompt, completion, failures, fallbacks, avg_latency in rows:
        count = int(count or 0)
        calls += count
        prompt_tokens += int(prompt or 0)
        completion_tokens += int(completion or 0)
        failed += int(failures or 0)
        fallback += int(fallbacks or 0)
        latency_weighted += float(avg_latency or 0.0) * count
        by_step.append(
            {
                "step": step or "(未标注)",
                "calls": count,
                "prompt_tokens": int(prompt or 0),
                "completion_tokens": int(completion or 0),
                "failed": int(failures or 0),
                "fallback": int(fallbacks or 0),
                "avg_latency_ms": int(avg_latency or 0),
            }
        )
    by_step.sort(key=lambda item: item["calls"], reverse=True)

    return {
        "totals": {
            "calls": calls,
            "failed": failed,
            "fallback": fallback,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "avg_latency_ms": int(latency_weighted / calls) if calls else 0,
        },
        "by_step": by_step,
        "items": [call_out(item) for item in project_calls(db, project_id=project_id, limit=limit)],
    }


def call_out(call: AiCall) -> dict[str, Any]:
    """给接口用的扁平结构：前端要算的字段这里都算好（token 合计、是否失败）。"""
    return {
        "id": call.id,
        "trace_id": call.trace_id,
        "project_id": call.project_id,
        "step": call.step,
        "provider": call.provider,
        "model": call.model,
        "prompt_version": call.prompt_version,
        "attempts": call.attempts,
        "latency_ms": call.latency_ms,
        "prompt_tokens": call.prompt_tokens,
        "completion_tokens": call.completion_tokens,
        "total_tokens": call.prompt_tokens + call.completion_tokens,
        "fallback_used": call.fallback_used,
        "ok": call.ok,
        "error_code": call.error_code,
        "error": call.error,
        "created_at": call.created_at.isoformat() if call.created_at else "",
    }
