# Fitwise · AI 售前决策助手

企业售前每天收到一堆客户材料（RFP、Word、Excel、邮件、聊天记录）。Fitwise 要解决的是这一个场景：
**材料到齐后 30 分钟内，产出一份能直接对内/对客使用的《客户要什么 · 我们能不能做 · 下一步做什么》初稿，每条结论都能点回原文页码。**

MVP 只有三个核心功能，按顺序串成一条链：

**材料解析 → 需求确认 → 售前建议**

AI 的角色：**AI 负责读、找、对、写初稿；人负责确认、定界、承诺**。没有证据时 AI 只能输出「待补依据」（信息不足，先不给结论），命中能力缺口时结论上限就是「暂不支持」，不允许比证据更乐观。

---

## 1. 三个核心功能

| # | 功能 | 回答什么 | 靠什么 | 产出 |
| --- | --- | --- | --- | --- |
| 1 | 材料解析 | 客户给了什么 | TextIn 解析出带页码的原文；系统按类型归档，并摘出项目要点（只记事实） | 项目要点（每条带来源页码）· 材料清单 · 解析状态 |
| 2 | 需求确认 | 客户到底要什么 | DeepSeek 抽取结构化需求并回填来源页码；人逐条确认后才成为基线 | 需求清单（草稿/基线）+ 待澄清问题（含「问谁」「影响判断还是影响承诺」） |
| 3 | 售前建议 | 我们能不能做、下一步怎么办 | 检索企业能力库与历史案例，规则层先给结论上限，DeepSeek 再组织表达 | 判断结论 · 风险 · 要问客户/要问内部/要同步销售 · 不可承诺清单 |

三个功能的边界：材料解析只讲事实（材料里写着什么），需求确认讲客户诉求（哪些算数），售前建议讲判断（能不能做、要不要承诺）。项目要点只做核对、编辑、忽略，不进入确认流程。

售前建议页「结论在上、依据在下」：一句结论 + 三句概括（需求判断 / 风险 / 下一步）常驻，三句都能点。
下面是两块：「能不能做」按 待补依据 → 暂不支持 → 部分支持 → 完全支持 排序，筛选栏既能按判断档筛、也能只看某一级风险；
风险正文就地展开在对应需求条目里（高/中/低标记），不另开板块。行动建议按"问谁"分成三组，可整段复制。
每条结论都能展开证据链，也可以人工覆写（留痕）。

---

## 2. 系统组成

| 层 | 实现 | 说明 |
| --- | --- | --- |
| 前端 | React 18 + TypeScript + Vite | 工作台 / 项目列表 / 项目工作台（三个功能页签） |
| 后端 | FastAPI + SQLAlchemy | 认证、客户与项目、材料解析、AI Agent 编排 |
| 数据库 | SQLite（默认）/ PostgreSQL | 通过 `DATABASE_URL` 切换，表结构由模型自动创建 |
| 文档解析 | **TextIn xParse** | 支持 PDF / Word / Excel / PPT / 图片 / OFD / HTML / TXT 等格式，返回**带页码**的元素与 Markdown |
| 大模型 | **DeepSeek**（OpenAI 兼容协议） | 需求抽取、能力判断、售前建议生成；模型不可用时自动降级为确定性规则 |
| 检索 | 标签 + 关键词混合检索 | 企业能力文档与历史案例；升级向量检索（pgvector）属于 P1 |
| 文件存储 | 本地目录（可换 S3/MinIO） | 上传原文与解析结果都落本地，满足「数据不出内网」诉求 |

关键设计：证据只能来自客户材料与知识库；规则层给结论上限，模型不能比证据更乐观；AI 与人工操作分别留痕。

---

## 3. 快速开始

### 3.1 后端

```bash
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r server/requirements.txt
copy server\.env.example server\.env     # 填入 TextIn 与 DeepSeek 凭据
cd server
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

首次启动会：创建数据库与表 → 写入演示账号 → 导入星云科技能力文档与案例 → 创建演示客户与项目。

接口文档：<http://127.0.0.1:8000/docs>

### 3.2 前端

```bash
npm install
npm run dev -- --port 5183     # http://127.0.0.1:5183
```

登录页提供「一键进入演示（售前 张岚）」，其余账号折叠在「用其他账号登录」里。密码均为 `fitwise123`：

| 账号 | 角色 |
| --- | --- |
| `presales@fitwise.local` | 售前（张岚） |
| `engineer@fitwise.local` | 技术专家（陈默） |
| `admin@fitwise.local` | 管理员 |

### 3.3 端到端冒烟测试

```bash
.venv\Scripts\python.exe scripts\e2e_smoke.py
```

脚本会：登录 → 上传合成 RFP（`scripts/test-rfp.pdf`）→ TextIn 解析 → DeepSeek 抽取需求 → 确认基线 → 能力判断 → 生成售前建议。

---

## 4. 目录结构

```
server/
  app/
    main.py             FastAPI 入口、CORS、启动时初始化种子数据
    config.py           配置（.env / 路径解析 / 开关）
    db.py               SQLAlchemy engine / session / init_db
    models.py           核心对象（客户、项目、材料、需求、判断、证据、方案、活动…）
    domain.py           状态字典、中文标签词表、标签推断
    seed.py             账号 / 知识库 / 演示客户项目初始化
    routers/            auth · customers · projects · materials · analysis · agent · dashboard · knowledge
    services/
      textin.py         TextIn xParse 客户端（同步 + 异步 + 轮询）
      llm.py            DeepSeek 客户端（JSON 输出、失败重试、规则回退）
      parse_pipeline.py 解析结果 → 带页码片段
      retrieval.py      标签 + 关键词混合检索（可替换为向量检索）
      agents.py         需求抽取 / 能力判断 / 售前建议三个 Agent + 证据校验
src/
  pages/                工作台、项目列表、项目工作台、登录
  components/project/   MaterialsModule（材料解析）· RequirementsModule（需求确认）
                        · MatchingModule + MatchingTab（逐条判断）· JudgementPage（售前建议）
                        · ProjectContextBar（项目栏与证据抽屉）· AgentPanel
scripts/                测试用 RFP 生成、端到端冒烟测试与沙箱回归（regression_check / uitest_sandbox）
docs/information-hierarchy.md  界面信息层级原则、逐页精简清单与后续待办
```

---

## 5. 配置项（server/.env）

| 变量 | 说明 |
| --- | --- |
| `TEXTIN_APP_ID` / `TEXTIN_SECRET_CODE` | TextIn xParse 凭据 |
| `TEXTIN_ASYNC_PAGE_THRESHOLD` | 超过多少页改用异步解析（默认 30） |
| `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` | DeepSeek 配置 |
| `DATABASE_URL` | 默认 `sqlite:///./data/fitwise.db`，可换成 PostgreSQL |
| `STORAGE_DIR` | 上传文件目录 |
| `JWT_SECRET` | 生产环境必须替换 |

`server/.env` 已在 `.gitignore` 中，不会被提交。

---

## 6. 已知限制与下一步

- 检索目前是标签 + 关键词混合检索；向量检索（PostgreSQL + pgvector）放 P1。
- 后台任务是单进程内存实现：重启后正在跑的任务会丢失，已落库的数据不受影响，重新点一次即可。
- SQLite 适合单机演示与小组使用，多人并发建议切 PostgreSQL。
- 「下一步」只到"行动建议"这一层（三组清单，可整段复制）：任务分派与跟踪、承诺审批、能力库/案例库后台维护、
  导出与提醒都不在本期 MVP 内 —— 行动项、承诺、联系人、知识库维护接口已按 MVP 定位删除，需要时再重做。

---

## 7. Agent 能力与开发须知

### 7.1 右侧 Agent 现在能做什么

| 能力 | 怎么触发 | 权限 |
| --- | --- | --- |
| 回答材料里的问题（带页码引用，可点回原文） | 直接问，例如「工期是多久」 | L0 只读 |
| 上传 / 粘贴材料 | 文件拖到页面任意位置，或在「客户材料」页点「选择文件上传」；邮件、聊天记录用「粘贴为材料」 | L1 自动执行 |
| 整理需求 / 能力判断 / 生成售前建议 | 说「重新跑一遍分析」「做能力判断」「生成售前建议」 | L1 自动执行 |
| 一条龙跑完整流程 | 说「从头跑一遍完整流程」 | L1，但遇到人工闸门会停下等你 |
| **确认需求** | 说「帮我确认这些需求」→ 点「批准并执行」 | **L2 必须人批准**（服务端留痕：谁、什么时候） |
| 会话与回执卡 | 自动落库，刷新页面后对话与卡片都还在 | — |

两条原则：**动作进 Agent，产物留中间页**；**AI 只准备，人做承诺**。
右侧是核心交互面，内容不随中间页变；中间页是产物面，三个页签只切换看哪份产物。

### 7.2 开发须知（这几条是踩过坑总结的）

- **后端不要开 `--reload`**：这台机器上 WatchFiles 会卡在 `Reloading...` 不真正重启，新路由一直 404。
  改完后端手动重启：停掉 8000 端口的进程，再
  `Start-Process .venv\Scripts\python.exe -ArgumentList "-m","uvicorn","app.main:app","--host","127.0.0.1","--port","8000" -WorkingDirectory server`。
- **原能力回归**：`python scripts\regression_check.py --with-agent` —— 复制一份库、在 8010 起独立后端、跑完整链路
  （上传 → 解析 → 抽取 → 确认 → 判断 → 建议 + 对话与审批），跑完自动删临时目录，不碰真实数据。
- **UI 沙箱**：`python scripts\uitest_sandbox.py` —— 复制库并把项目重置到「基线已定、还没判断」，
  再起 8010 后端 + 5199 前端，用来验证只有中途状态才会出现的交互。
- **演示数据**：`python scripts\demo_reset.py` —— 新建演示客户/项目、传一份合成 RFP、停在「需求待确认」。剧本见 `docs/demo-script.md`。
- **前端构建与起沙箱要提权**：esbuild 在沙箱里读不到项目文件（`vite build` 同理）。
- **清理进程要按端口或明确 PID**，不要按「最近启动的 python」批量杀 —— 会把后端一起杀掉。
