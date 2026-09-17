# Fitwise 部署说明（单机同源部署）

给 HR / 客户看的演示地址：**<http://8.159.155.16/fitwise/>**

这台服务器公网只开了 22 和 80 两个端口，80 由 nginx 占用并已经在服务 aifinance，
所以 Fitwise 挂在同一个 nginx 的 `/fitwise/` 路径下，**没有独立域名、没有 HTTPS**。

## 1. 部署形态

| 项 | 值 |
| --- | --- |
| 服务器 | `8.159.155.16`（阿里云 ECS，Ubuntu 22.04） |
| 系统账号 | `hannah`（普通账号，无 sudo、无密码，仅用于跑本服务） |
| 代码与前端产物 | `/home/hannah/app`（构建好的前端在 `/home/hannah/app/dist`） |
| Python venv | `/home/hannah/app/server/.venv` |
| 数据库 / 上传文件 | `/home/hannah/app/server/data/`（SQLite + uploads） |
| 后端服务 | systemd 单元 `fitwise.service`，`User=hannah`，监听 `127.0.0.1:8100` |
| 对外入口 | nginx `location /fitwise/` → `127.0.0.1:8100`（前缀被剥掉） |

与 aifinance 的关系：**同一个 nginx、同一台机器，其余全独立**——不同账号、
不同进程、不同数据库、不同端口。aifinance 的三条 location（`/`、`/admin`、
`/api/v1/chat/`）未做任何修改；nginx 站点配置改前的原件备份在
`/root/conf-backup-20260916/aifinance.bak`。

### 请求怎么走

```
浏览器  http://8.159.155.16/fitwise/#/projects/1/materials
   └─ nginx(80)  location /fitwise/  →  剥掉前缀  →  127.0.0.1:8100
        ├─ /api/*  → FastAPI 接口
        └─ 其余     → StaticFiles 返回 dist/ 里的前端（哈希路由，不需要 SPA 回退）
```

前端是**构建时**写死后端路径的：必须用 `VITE_API_BASE=/fitwise` 加
`--base=/fitwise/` 构建，否则资源 404 或接口打到 `127.0.0.1:8000`（那是 aifinance）。

## 2. 日常操作

以下命令都在本机（Windows）执行，`aifinance-prod` 是 `~/.ssh/config` 里的别名。

### 看状态与日志

```bash
ssh aifinance-prod "systemctl status fitwise --no-pager | head -15"
ssh aifinance-prod "journalctl -u fitwise -n 100 --no-pager"
ssh aifinance-prod "curl -s http://127.0.0.1:8100/api/health-check"
```

### 有人反馈"点了没反应"时怎么查（诊断事件）

前端埋点只记元数据（动作、状态、耗时、版本、路由），不记材料与需求正文。
先拿一个令牌，再看事件：

```bash
TOKEN=$(ssh aifinance-prod "curl -s -X POST http://127.0.0.1:8100/api/auth/login -H 'Content-Type: application/json' -d '{\"email\":\"presales@fitwise.local\",\"password\":\"fitwise123\"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)[\"token\"])'")
ssh aifinance-prod "curl -s -H 'Authorization: Bearer $TOKEN' 'http://127.0.0.1:8100/api/events?limit=50'"
ssh aifinance-prod "curl -s -H 'Authorization: Bearer $TOKEN' 'http://127.0.0.1:8100/api/projects/1/events?limit=100'"
```

五个事件：`client_boot`（哪一版、什么浏览器）、`page_view`（停在哪一页、停了多久）、
`api_failed`（哪个接口、状态码、耗时）、`action_finished`（提取 / 匹配 / 生成建议的结果与耗时）、
`client_error`（前端报错）。事件表只保留最近 5000 条，超了自动删最旧的，不用管运维。

### 只更新前端

```powershell
$env:VITE_API_BASE = "/fitwise"
npm run build -- --base=/fitwise/
tar -czf $env:TEMP\fitwise-dist.tar.gz -C . dist
scp $env:TEMP\fitwise-dist.tar.gz aifinance-prod:/tmp/
ssh aifinance-prod "sudo -u hannah tar -xzf /tmp/fitwise-dist.tar.gz -C /home/hannah/app && rm -f /tmp/fitwise-dist.tar.gz && systemctl restart fitwise"
```

### 更新后端代码

改完提交后，把当前提交打成包传上去（服务器上不需要 GitHub 密钥；
`.env`、`.venv`、`data/`、`dist/` 都不在包里，不会被覆盖）：

```powershell
git archive --format=tar.gz -o $env:TEMP\fitwise-src.tar.gz HEAD
scp $env:TEMP\fitwise-src.tar.gz aifinance-prod:/tmp/
ssh aifinance-prod "sudo -u hannah tar -xzf /tmp/fitwise-src.tar.gz -C /home/hannah/app && rm -f /tmp/fitwise-src.tar.gz && systemctl restart fitwise"
```

### 重新准备演示数据

```bash
# 1) 清场重建：备份数据库 → 清掉历史业务数据 → 建演示客户/项目 → 传 demo/ 两份材料
ssh aifinance-prod "cd /home/hannah/app && sudo -u hannah env FITWISE_BASE=http://127.0.0.1:8100 /home/hannah/app/server/.venv/bin/python scripts/demo_reset.py --purge --preload"

# 2) 把剩下三步跑完：确认需求 → 能力判断 → 售前建议
ssh aifinance-prod "cd /home/hannah/app && sudo -u hannah env FITWISE_BASE=http://127.0.0.1:8100 /home/hannah/app/server/.venv/bin/python scripts/demo_finish.py"
```

第 1 步会调 TextIn 解析、DeepSeek 抽需求，第 2 步会调 DeepSeek 做判断和建议，都会花少量额度。

## 3. 彻底撤掉

```bash
systemctl disable --now fitwise
rm -f /etc/systemd/system/fitwise.service /etc/nginx/snippets/fitwise.conf
# 再从 /etc/nginx/sites-available/aifinance 里删掉 "include /etc/nginx/snippets/fitwise.conf;" 那一行
nginx -t && systemctl reload nginx
rm -rf /home/hannah/app
userdel -r hannah
```

删完 aifinance 不受任何影响（它全程没被改过）。想恢复 nginx 原样，
也可以直接用 `/root/conf-backup-20260916/aifinance.bak` 覆盖回去。

## 4. 已知限制

- **没有 HTTPS**：HR 打开时浏览器会标"不安全"，这是纯 IP + 无证书的必然结果。
  以后拿到域名（或愿意用 `sslip.io` 这类免费通配 DNS），加一张 Let's Encrypt
  证书就能升级；前端要按新路径重新构建一次。
- **演示入口是公开的**：链接谁拿到谁能用，会消耗服务器上那对 TextIn / DeepSeek 密钥的额度。
  HR 看完建议撤掉，或者轮换一次密钥。
- **单进程、无并发设计**：uvicorn 单 worker，够演示用；内存占用约 75MB。
- **前端是构建快照**：`dist/` 不在 git 里，改完前端必须重新构建并上传（见 2.2）。
