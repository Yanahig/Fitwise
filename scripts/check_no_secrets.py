"""提交前自检：真实密钥不许进仓库。

跑法：
    .venv\\Scripts\\python.exe scripts\\check_no_secrets.py

它查三件事，全部离线、不联网：

1. **有没有 .env 类文件会被提交**：任何位置的 `.env` / `.env.local` 等（`.env.example` 除外）
   只要出现在 git 的待提交列表里就报错 —— 这比"靠 .gitignore 记得写对"更可靠。
2. **真实密钥有没有出现在代码里**：从 `server/.env` 读出四项敏感值
   （TEXTIN_APP_ID / TEXTIN_SECRET_CODE / LLM_API_KEY / JWT_SECRET），
   拿它们的真值去扫暂存区与工作区的文件。**只打印命中的文件名，不打印密钥内容。**
3. **常见密钥格式**：`sk-…` / `ghp_…` / `AKIA…` / 私钥文件头，兜住"硬编码在代码里"的情况。

为什么第 1 条和第 2 条都要有：.gitignore 只防"文件名"，防不住"密钥被复制到别的文件里"；
真值扫描能防后者，但前提是 server/.env 存在。两条一起才闭合。

注意：这里把端点地址（api.textin.com）、模型名、本地路径当作**非敏感** ——
它们本来就该出现在 .env.example 里。只有上面那四项算密钥。
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / "server" / ".env"

#: 只把这四项当密钥比对（端点地址 / 模型名 / 路径不是秘密）
SENSITIVE_KEYS = ("TEXTIN_APP_ID", "TEXTIN_SECRET_CODE", "LLM_API_KEY", "JWT_SECRET")

#: 常见密钥格式，兜住硬编码
PATTERNS: list[tuple[str, str]] = [
    ("模型服务密钥（sk- 开头）", r"sk-[A-Za-z0-9_\-]{20,}"),
    ("GitHub token", r"gh[pousr]_[A-Za-z0-9]{20,}"),
    ("AWS Access Key", r"AKIA[0-9A-Z]{16}"),
    ("私钥文件内容", r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
]

#: 允许出现在仓库里的模板文件
ENV_ALLOWLIST = {".env.example"}

RESULTS: list[tuple[bool, str, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    """注意参数顺序是（结论文字, 是否通过）：和 scripts/scorecard.py 保持一致。"""
    RESULTS.append((ok, name, detail))


def git(*args: str) -> str:
    result = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    return result.stdout or ""


def read_sensitive_values() -> dict[str, str]:
    """从 server/.env 读真实密钥值：只在内存里用，绝不打印。"""
    values: dict[str, str] = {}
    if not ENV_FILE.exists():
        return values
    for line in ENV_FILE.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key in SENSITIVE_KEYS and len(value) >= 9:
            values[key] = value
    return values


def check_env_files() -> None:
    """第一条：待提交列表里不许有 .env 类文件。"""
    staged = [item for item in git("diff", "--cached", "--name-only").splitlines() if item.strip()]
    pending = [item for item in git("status", "--porcelain", "--untracked-files=all").splitlines() if item.strip()]

    offenders: list[str] = []
    for line in pending:
        path = line[3:].strip().strip('"')
        name = Path(path).name
        if name in ENV_ALLOWLIST:
            continue
        if name == ".env" or name.startswith(".env."):
            offenders.append(path)

    check(
        "待提交列表里没有 .env 类文件",
        not offenders,
        "、" .join(offenders) if offenders else f"已检查 {len(pending)} 条待提交项，模板文件除外",
    )

    template = [item for item in staged if Path(item).name in ENV_ALLOWLIST]
    if template:
        print(f"   （本次提交包含模板文件：{'、'.join(template)} —— 必须只有占位符）")


def check_sensitive_values(values: dict[str, str]) -> None:
    """第二条：真实密钥的真值不许出现在暂存区或工作区文件里。"""
    if not values:
        check("真实密钥未出现在代码里", True, "server/.env 不存在或没有可比的密钥，跳过真值比对")
        return

    hits: list[str] = []
    for key, value in values.items():
        staged = [item for item in git("grep", "--cached", "-l", "-F", "-e", value).splitlines() if item.strip()]
        working = [item for item in git("grep", "-l", "-F", "-e", value).splitlines() if item.strip()]
        for path in sorted(set(staged) | set(working)):
            hits.append(f"{key} → {path}")

    check(
        "真实密钥未出现在代码里",
        not hits,
        "；".join(hits) if hits else f"已比对 {len(values)} 项密钥（{('、'.join(values))}）",
    )


def check_patterns() -> None:
    """第三条：常见密钥格式不该出现在仓库里（兜硬编码）。"""
    hits: list[str] = []
    for label, pattern in PATTERNS:
        for scope in (["--cached"], []):
            found = [
                item
                for item in git("grep", *scope, "-l", "-I", "-E", "-e", pattern).splitlines()
                if item.strip()
            ]
            hits.extend(f"{label} → {path}" for path in found)
    check("没有硬编码的密钥格式", not hits, "；".join(sorted(set(hits))) if hits else "已扫 sk- / ghp_ / AKIA / 私钥头")


def main() -> int:
    print("== 提交前自检：密钥 ==\n")
    values = read_sensitive_values()
    print(f"（从 server/.env 读到 {len(values)} 项用于比对：{'、'.join(values) or '无'}）\n")
    check_env_files()
    check_sensitive_values(values)
    check_patterns()

    passed = sum(1 for ok, _, _ in RESULTS if ok)
    for ok, name, detail in RESULTS:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  （{detail}）" if detail else ""))
    print(f"\n{passed}/{len(RESULTS)} 通过")
    if passed != len(RESULTS):
        print("有未通过项：先处理再提交；如果密钥已经提交过，先去服务商后台作废重发，再清理历史。")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
