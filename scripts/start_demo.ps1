# 启动演示环境：后端 8000 + 前端 5183，各开一个 PowerShell 窗口。
# 关掉窗口就停止对应服务 —— 这样进程归你自己的桌面会话管，不会被别的东西回收。
#
# 用法（在仓库根目录）：
#   powershell -ExecutionPolicy Bypass -File scripts\start_demo.ps1

$root = Split-Path -Parent $PSScriptRoot

Write-Host "启动后端（8000）…"
Start-Process powershell -ArgumentList @(
  '-NoExit', '-Command',
  "cd '$root\server'; Write-Host 'Fitwise 后端 · http://127.0.0.1:8000'; ..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000"
)

Start-Sleep -Seconds 2

Write-Host "启动前端（5183）…"
Start-Process powershell -ArgumentList @(
  '-NoExit', '-Command',
  "cd '$root'; Write-Host 'Fitwise 前端 · http://127.0.0.1:5183'; npm run dev -- --port 5183 --strictPort"
)

Start-Sleep -Seconds 4

Write-Host ""
Write-Host "打开： http://127.0.0.1:5183/#/projects/1/materials"
Write-Host "登录： 点「一键进入演示（售前 张岚）」，或 presales@fitwise.local / fitwise123"
Write-Host ""
Write-Host "自检： .venv\Scripts\python.exe scripts\demo_check.py"
Write-Host "停止： powershell -ExecutionPolicy Bypass -File scripts\stop_demo.ps1（或直接关掉那两个窗口）"
