"""UI 沙箱：用一份库副本 + 一套独立的 UI/后端，验证只有"中途状态"才会出现的交互。

    .venv\\Scripts\\python.exe scripts\\uitest_sandbox.py

做的事：
  1. 复制 server/data/fitwise.db 到临时目录，并把这个项目的「能力判断 + 售前建议」清掉，
     让它停在「基线已定、还没判断」的状态 —— 这样状态机才会有两步可跑；
  2. 起后端（8010，CORS 放开 5199）和前端（5199，VITE_API_BASE 指向 8010）；
  3. 一直跑到被 Ctrl+C / 杀掉为止，之后临时目录自己删掉。

真实数据、真实服务都不受影响。
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
BACKEND_PORT = 8010
UI_PORT = 5199
UI_ORIGIN = f"http://127.0.0.1:{UI_PORT}"


def reset_project_state(db_url: str) -> None:
    """把项目重置到「基线已定、还没判断」：清掉判断与建议，需求保持已确认。"""
    from sqlalchemy import create_engine, delete, text

    engine = create_engine(db_url)
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM match_results"))
        connection.execute(text("DELETE FROM match_evidences"))
        connection.execute(text("DELETE FROM solutions"))
        connection.execute(text("DELETE FROM agent_messages"))


def wait_ready(url: str, timeout: int = 60) -> bool:
    started = time.time()
    while time.time() - started < timeout:
        try:
            if httpx.get(url, timeout=3).status_code == 200:
                return True
        except Exception:  # noqa: BLE001
            pass
        time.sleep(1)
    return False


def main() -> int:
    workdir = Path(tempfile.mkdtemp(prefix="fitwise-uitest-"))
    db_path = workdir / "fitwise.db"
    shutil.copy2(SERVER_DIR / "data" / "fitwise.db", db_path)
    db_url = f"sqlite:///{db_path.as_posix()}"
    reset_project_state(db_url)

    backend_env = dict(os.environ)
    backend_env["DATABASE_URL"] = db_url
    backend_env["STORAGE_DIR"] = str(workdir / "uploads")
    backend_env["CORS_ORIGINS"] = f"{UI_ORIGIN},http://localhost:{UI_PORT}"

    ui_env = dict(os.environ)
    ui_env["VITE_API_BASE"] = f"http://127.0.0.1:{BACKEND_PORT}"

    print(f"sandbox db: {db_path}")
    backend = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(BACKEND_PORT)],
        cwd=str(SERVER_DIR),
        env=backend_env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # 直接用 node 起 vite：不经过 npm 的中间进程，出问题日志也落在文件里好查
    node = shutil.which("node") or "node"
    vite = ROOT / "node_modules" / "vite" / "bin" / "vite.js"
    ui_log = Path(tempfile.gettempdir()) / "fitwise-uitest-ui.log"
    ui_handle = ui_log.open("w", encoding="utf-8", errors="replace")
    ui = subprocess.Popen(
        [node, str(vite), "--port", str(UI_PORT), "--strictPort", "--host", "127.0.0.1"],
        cwd=str(ROOT),
        env=ui_env,
        stdout=ui_handle,
        stderr=subprocess.STDOUT,
    )
    try:
        if not wait_ready(f"http://127.0.0.1:{BACKEND_PORT}/api/health-check"):
            print("后端没起来")
            return 1
        if not wait_ready(UI_ORIGIN, timeout=90):
            print("前端没起来")
            return 1
        print(f"READY  UI={UI_ORIGIN}  API=http://127.0.0.1:{BACKEND_PORT}  ui log={ui_log}")
        while True:
            time.sleep(5)
            if backend.poll() is not None or ui.poll() is not None:
                print("有一个进程退出了，收工")
                return 1
    except KeyboardInterrupt:
        print("\n收工")
        return 0
    finally:
        for process in (ui, backend):
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
        ui_handle.close()
        # Windows 上刚杀掉的进程偶尔还攥着句柄，留几次重试，别把临时目录留在那儿
        for _ in range(3):
            shutil.rmtree(workdir, ignore_errors=True)
            if not workdir.exists():
                break
            time.sleep(2)
        if workdir.exists():
            print(f"注意：临时目录没删掉（句柄占用）→ {workdir}")


if __name__ == "__main__":
    raise SystemExit(main())
