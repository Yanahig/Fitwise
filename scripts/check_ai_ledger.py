"""AI 调用账本、失败成因与解析重试的确定性自测：不调模型、不碰真实库。

跑法：.venv\\Scripts\\python.exe scripts\\check_ai_ledger.py

覆盖四件事：

1. 账本写入与汇总（按项目看调用/token/失败/回退，按 trace 复盘一次运行）；
2. 模型不可用时的回退也要留痕（fallback_used + no_api_key），而不是只有日志知道；
3. 失败成因归类与可重试判定（超时/网络/限流/5xx 可重试，凭据错与输出不合规不重试）；
4. 解析重试：可重试的失败会重试一次并记下尝试次数，不可重试的立即失败。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parent.parent
SERVER_DIR = ROOT / "server"
sys.path.insert(0, str(SERVER_DIR))

import httpx  # noqa: E402

from app.db import Base  # noqa: E402
from app.models import Customer, Project  # noqa: E402
from app.services import ai_ledger, llm, textin  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RESULTS: list[tuple[bool, str, str]] = []


def check(ok: bool, name: str, detail: str = "") -> None:
    RESULTS.append((ok, name, detail))


def build_db():
    """临时内存库：和真实演示库完全隔离。"""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    customer = Customer(name="自测客户", industry="政务")
    session.add(customer)
    session.flush()
    project = Project(customer_id=customer.id, name="自测项目")
    session.add(project)
    session.commit()
    return session, project


def test_ledger(db, project) -> None:
    ai_ledger.record(
        db,
        trace_id="trace-selfcheck",
        project_id=project.id,
        step="parse",
        provider="api.textin.com",
        model="textin-xparse",
        attempts=2,
        latency_ms=1200,
        ok=True,
    )
    ai_ledger.record(
        db,
        trace_id="trace-selfcheck",
        project_id=project.id,
        step="judge",
        provider="api.deepseek.com",
        model="deepseek-flash",
        prompt_version="judge@self-check",
        attempts=1,
        latency_ms=800,
        prompt_tokens=1200,
        completion_tokens=180,
        fallback_used=True,
        ok=False,
        error_code=ai_ledger.ERROR_TIMEOUT,
        error="read timeout",
    )
    db.commit()

    calls = ai_ledger.trace_calls(db, trace_id="trace-selfcheck")
    check(len(calls) == 2, "按 trace 复盘：两次调用都被串起来", f"calls={len(calls)}")

    summary = ai_ledger.project_summary(db, project_id=project.id, limit=10)
    totals = summary["totals"]
    check(totals["calls"] == 2, "按项目汇总：调用次数", f"calls={totals['calls']}")
    check(totals["total_tokens"] == 1380, "按项目汇总：token 合计", f"tokens={totals['total_tokens']}")
    check(totals["fallback"] == 1 and totals["failed"] == 1, "按项目汇总：回退与失败分开计数")
    check(
        [row["step"] for row in summary["by_step"]] and summary["by_step"][0]["calls"] >= 1,
        "按步骤分组：能说出每一步各调了几次",
        f"by_step={[row['step'] for row in summary['by_step']]}",
    )
    check(summary["items"][0]["step"] == "judge", "明细按时间倒序（最近一次在最前）")


def test_error_codes() -> None:
    check(
        llm.classify_error(httpx.TimeoutException("slow")) == ai_ledger.ERROR_TIMEOUT
        and ai_ledger.is_retryable(ai_ledger.ERROR_TIMEOUT),
        "超时：归类为 timeout，可重试",
    )
    check(
        llm.classify_error(httpx.ConnectError("boom")) == ai_ledger.ERROR_NETWORK
        and ai_ledger.is_retryable(ai_ledger.ERROR_NETWORK),
        "网络错误：归类为 network，可重试",
    )
    check(
        llm.classify_error(llm.LLMError("x"), status=401) == ai_ledger.ERROR_AUTH
        and not ai_ledger.is_retryable(ai_ledger.ERROR_AUTH),
        "凭据错：归类为 auth，不重试",
    )
    check(
        llm.classify_error(llm.LLMError("x"), status=429) == ai_ledger.ERROR_RATE_LIMIT
        and llm.classify_error(llm.LLMError("x"), status=503) == ai_ledger.ERROR_SERVER,
        "限流与 5xx：归类为 rate_limit / server_error，可重试",
    )
    check(
        llm.classify_error(llm.LLMError("模型输出缺少必需字段：summary")) == ai_ledger.ERROR_MISSING_KEYS
        and ai_ledger.is_retryable(ai_ledger.ERROR_MISSING_KEYS),
        "输出不合规：归类为 missing_keys，重试一次（输出有随机性，再试经常就好了）",
    )
    check(
        llm.classify_error(llm.LLMError("模型输出不是合法 JSON")) == ai_ledger.ERROR_BAD_JSON
        and ai_ledger.is_retryable(ai_ledger.ERROR_BAD_JSON),
        "JSON 不合规：归类为 bad_json，同样重试一次",
    )
    check(
        not ai_ledger.is_retryable(ai_ledger.ERROR_CONTENT)
        and not ai_ledger.is_retryable(ai_ledger.ERROR_BAD_REQUEST),
        "内容问题与请求不合法：不重试",
    )


def test_fallback_is_recorded(db, project) -> None:
    """模型不可用时走规则回退，也要在账本里留下「这次是规则结果」。"""
    original_key = llm.settings.llm_api_key
    try:
        llm.settings.llm_api_key = ""
        payload = asyncio.run(
            llm.chat_json(
                system="system",
                user="user",
                schema_hint="{}",
                fallback=lambda: {"status": "partial"},
                meta={},
                trace_id="trace-fallback",
                step="judge",
                prompt_version="judge@self-check",
                on_call=lambda item: ai_ledger.record(db, project_id=project.id, **item),
            )
        )
        db.commit()
        calls = ai_ledger.trace_calls(db, trace_id="trace-fallback")
        check(payload == {"status": "partial"}, "没有 API Key 时返回规则回退结果")
        check(
            len(calls) == 1 and calls[0].fallback_used and calls[0].error_code == ai_ledger.ERROR_NO_API_KEY,
            "回退也留痕：fallback_used + no_api_key 都进了账本",
            f"calls={len(calls)}",
        )
    finally:
        llm.settings.llm_api_key = original_key


def test_parse_retry() -> None:
    """可重试的解析失败重试一次；不可重试的立即失败。"""
    original_delay = textin.RETRY_DELAY_SECONDS
    original_sync = textin.parse_file_sync
    original_enabled = textin.settings.textin_app_id
    try:
        textin.RETRY_DELAY_SECONDS = 0.0
        textin.settings.textin_app_id = "self-check"
        textin.settings.textin_secret_code = "self-check"
        attempts: list[int] = []

        async def flaky(path, filename=None):
            attempts.append(1)
            if len(attempts) == 1:
                raise textin.TextInError("connection reset", code=ai_ledger.ERROR_NETWORK)
            return textin.ParsedDocument(markdown="ok", page_count=1)

        textin.parse_file_sync = flaky
        document = asyncio.run(textin.parse_file(Path("self-check.pdf"), "self-check.pdf"))
        check(
            document.attempts == 2 and len(attempts) == 2,
            "网络抖动：自动重试一次并记下尝试次数",
            f"attempts={document.attempts}",
        )

        hard_attempts: list[int] = []

        async def unauthorized(path, filename=None):
            hard_attempts.append(1)
            raise textin.TextInError("bad credentials", code=ai_ledger.ERROR_AUTH)

        textin.parse_file_sync = unauthorized
        try:
            asyncio.run(textin.parse_file(Path("self-check.pdf"), "self-check.pdf"))
            check(False, "凭据错：不重试，直接失败")
        except textin.TextInError as error:
            check(
                len(hard_attempts) == 1 and error.code == ai_ledger.ERROR_AUTH,
                "凭据错：不重试，直接失败（不浪费一轮等待）",
                f"attempts={len(hard_attempts)}",
            )
    finally:
        textin.RETRY_DELAY_SECONDS = original_delay
        textin.parse_file_sync = original_sync
        textin.settings.textin_app_id = original_enabled


def main() -> int:
    db, project = build_db()
    try:
        test_ledger(db, project)
        test_error_codes()
        test_fallback_is_recorded(db, project)
        test_parse_retry()
    finally:
        db.close()

    passed = sum(1 for ok, _, _ in RESULTS if ok)
    for ok, name, detail in RESULTS:
        mark = "PASS" if ok else "FAIL"
        suffix = f"  ({detail})" if detail else ""
        print(f"[{mark}] {name}{suffix}")
    print(f"\n{passed}/{len(RESULTS)} 通过")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
