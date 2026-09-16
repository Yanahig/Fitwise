"""把演示项目从「需求待确认」推进到底：确认需求 → 能力判断 → 售前建议。

用法（后端在线即可，本机或服务器都行）：

    FITWISE_BASE=http://127.0.0.1:8100 python scripts/demo_finish.py

配合 `scripts/demo_reset.py --purge --preload` 使用：那个脚本负责铺材料、
抽需求（停在「需求待确认」等人工确认），这个脚本负责把剩下三步跑完，
让 HR / 客户自己点开就能看到完整的判断与建议。

环境变量：
    FITWISE_BASE      后端地址，默认 http://127.0.0.1:8000
    FITWISE_PROJECT    指定项目 id，默认取项目列表里的第一个
    FITWISE_EMAIL / FITWISE_PASSWORD  登录账号，默认演示售前账号
"""

from __future__ import annotations

import os
import time

import httpx

BASE = os.environ.get("FITWISE_BASE", "http://127.0.0.1:8000")
EMAIL = os.environ.get("FITWISE_EMAIL", "presales@fitwise.local")
PASSWORD = os.environ.get("FITWISE_PASSWORD", "fitwise123")
PROBLEM = "客户要求私有化部署、多语言 OCR，同时要求处理特殊票据。"


def wait_job(client: httpx.Client, job_id: str, label: str, timeout: int = 900) -> dict:
    started = time.time()
    while time.time() - started < timeout:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job.get("status") in ("done", "failed"):
            print(f"[{label}] {job['status']} {job.get('error') or ''}".rstrip())
            return job
        time.sleep(3)
    raise SystemExit(f"[{label}] 超时（{timeout}s）")


def main() -> int:
    client = httpx.Client(base_url=BASE, timeout=300)
    login = client.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})
    login.raise_for_status()
    client.headers["Authorization"] = f"Bearer {login.json()['token']}"

    project_id = os.environ.get("FITWISE_PROJECT")
    pid = int(project_id) if project_id else client.get("/api/projects").json()[0]["id"]
    print(f"项目 id：{pid}")

    requirements = client.get(f"/api/projects/{pid}/requirements").json()["requirements"]
    print(f"待确认需求：{len(requirements)} 条")

    confirmed = client.post(f"/api/projects/{pid}/requirements/confirm", json={"ids": None}).json()
    print(f"已确认为基线：{confirmed.get('confirmed')} 条")

    job = client.post(f"/api/projects/{pid}/matches/run").json()
    wait_job(client, job["job_id"], "能力判断")
    matches = client.get(f"/api/projects/{pid}/matches").json()
    distribution: dict[str, int] = {}
    for item in matches:
        distribution[item["status"]] = distribution.get(item["status"], 0) + 1
    print(f"判断结论：{len(matches)} 条 {distribution}")

    job = client.post(f"/api/projects/{pid}/solutions/generate", json={"problem": PROBLEM}).json()
    wait_job(client, job["job_id"], "售前建议")
    solution = client.get(f"/api/projects/{pid}/solutions").json()[0]
    print(
        f"售前建议 v{solution['version']}：{len(solution['steps'])} 步 / "
        f"{len(solution['risks'])} 条风险 / 问客户 {len(solution['ask_customer'])} 项 / "
        f"问内部 {len(solution['ask_internal'])} 项"
    )
    print("完成：项目已推进到「售前建议」状态")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
