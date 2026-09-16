# 停止演示环境：按端口（8000 / 5183）找进程，只杀监听这两个端口的进程，
# 不按"最近启动的 python"批量杀，避免误伤别的服务。
#
# 用法：powershell -ExecutionPolicy Bypass -File scripts\stop_demo.ps1

foreach ($port in 8000, 5183) {
  $lines = netstat -ano | Select-String -Pattern ":$port\s+.*LISTENING"
  if (-not $lines) {
    Write-Host "端口 $port 上没有监听进程"
    continue
  }
  foreach ($line in $lines) {
    $procId = 0
    if (-not [int]::TryParse(($line -split '\s+')[-1], [ref]$procId)) { continue }
    $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
    if ($proc) {
      Stop-Process -Id $procId -Force
      Write-Host "已停止端口 $port 上的进程 $procId（$($proc.ProcessName)）"
    }
  }
}
