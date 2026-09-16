"""原能力回归：在**临时沙箱**里跑一遍端到端链路，不碰你正在用的服务与数据。

    .venv\\Scripts\\python.exe scripts\\regression_check.py
    .venv\\Scripts\\python.exe scripts\\regression_check.py --with-agent   # 顺带跑对话检查

做的事：
  1. 把 server/data/fitwise.db 复制到临时目录（上传目录也换成临时的）；
  2. 在 8010 端口起一个 uvicorn（复用同一份代码），DATABASE_URL / STORAGE_DIR 指向副本；
  3. 用 FITWISE_BASE 让 scripts/e2e_smoke.py 打这个沙箱实例；
  4. 收工：停掉沙箱、删掉临时目录。

所以它既能验证「改完之后原链路还能跑」，又不会往演示项目里写任何数据。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
SERVER_DIR = ROOT / "server"
PORT = int(os.environ.get("FITWISE_SANDBOX_PORT", "8010"))
BASE = f"http://127.0.0.1:{PORT}"


def wait_ready(timeout: int = 60) -> bool:
    started = time.time()
    while time.time() - started < timeout:
        try:
            response = httpx.get(f"{BASE}/api/health-check", timeout=3)
            if response.status_code == 200:
                return True
        except Exception:  # noqa: BLE001 - 启动过程里连不上是正常的
            pass
        time.sleep(1)
    return False


def port_in_use() -> bool:
    """端口上已经有别的实例在跑吗？

    之前踩过的坑：别人（或上一次没退干净的沙箱）已经占着这个端口时，
    `wait_ready` 会连上**那个**实例、然后一路返回 True —— 于是这次回归其实跑在
    另一份代码、另一个库上，"PASS"是假阳性。所以先做一次端口预检，冲突就直接退出。
    """
    try:
        httpx.get(f"{BASE}/api/health-check", timeout=2)
        return True
    except Exception:  # noqa: BLE001 - 连不上说明端口是空的
        return False


def main() -> int:
    if port_in_use():
        print(
            f"RESULT: FAIL - 端口 {PORT} 上已经有实例在跑。\n"
            f"  回归必须跑在自己的沙箱里，否则会误判别人的实例。\n"
            f"  换个端口：$env:FITWISE_SANDBOX_PORT=\"8021\"; "
            f".venv\\Scripts\\python.exe scripts\\regression_check.py --with-agent"
        )
        return 1

    workdir = Path(tempfile.mkdtemp(prefix="fitwise-regression-"))
    source_db = SERVER_DIR / "data" / "fitwise.db"
    if source_db.exists():
        shutil.copy2(source_db, workdir / "fitwise.db")

    env = dict(os.environ)
    env["DATABASE_URL"] = f"sqlite:///{(workdir / 'fitwise.db').as_posix()}"
    env["STORAGE_DIR"] = str(workdir / "uploads")

    print(f"sandbox: {workdir}  →  {BASE}")
    # 沙箱后端的日志留一份：起不来时能直接看到原因（以前丢进 DEVNULL，出问题只能猜）
    server_log = (workdir / "sandbox-server.log").open("w", encoding="utf-8")
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(PORT)],
        cwd=str(SERVER_DIR),
        env=env,
        stdout=server_log,
        stderr=subprocess.STDOUT,
    )
    try:
        if not wait_ready():
            print("RESULT: FAIL - 沙箱后端没起来")
            print(f"  端口 {PORT} 上没等到 /api/health-check，sanity 日志（最后 15 行）：")
            server_log.flush()
            tail = (workdir / "sandbox-server.log").read_text(encoding="utf-8", errors="replace").splitlines()
            for line in tail[-15:]:
                print("   " + line)
            if server.poll() is not None:
                print(f"  进程已退出，退出码 {server.returncode}")
            else:
                print("  进程还在跑 —— 大概率是端口被占（上一次沙箱没退干净），重跑一次即可")
            return 1
        print("sandbox: ready\n")

        smoke_env = dict(os.environ)
        smoke_env["FITWISE_BASE"] = BASE
        smoke_env["PYTHONIOENCODING"] = "utf-8"
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "e2e_smoke.py")],
            env=smoke_env,
            cwd=str(ROOT),
        )
        if result.returncode != 0:
            print("\nRESULT: FAIL - 端到端链路")
            return result.returncode
        print("\nRESULT: PASS - 端到端链路")

        if "--with-agent" in sys.argv:
            print("\n--- 对话与工具回执卡 ---")
            agent_check = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "check_agent_conversation.py")],
                env=smoke_env,
                cwd=str(ROOT),
            )
            if agent_check.returncode != 0:
                print("\nRESULT: FAIL - 对话检查")
                return agent_check.returncode

            print("\n--- AI 调用账本（成本与可观测） ---")
            trace_check = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "check_trace_api.py")],
                env=smoke_env,
                cwd=str(ROOT),
            )
            if trace_check.returncode != 0:
                print("\nRESULT: FAIL - 调用账本")
                return trace_check.returncode
        return 0
    finally:
        server.terminate()
        try:
            server.wait(timeout=15)
        except subprocess.TimeoutExpired:
            server.kill()
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
