# Fitwise · AI 售前决策助手

企业售前每天收到一堆客户材料（RFP、Word、Excel、邮件、聊天记录）。Fitwise 要解决的是这一个场景：
**材料到齐后，产出一份能直接对内/对客使用的《客户要什么 · 我们能不能做 · 下一步做什么》初稿，每条结论都能点回原文页码。**

MVP 只有三个核心功能，按顺序串成一条链：

**材料解析（含确认）→ 能力匹配 → 售前建议**

AI 的角色：**AI 负责读、找、对、写初稿；人负责确认、定界、承诺**。没有证据时 AI 只能输出「待补依据」（信息不足，先不给结论），命中能力缺口时结论上限就是「暂不支持」，不允许比证据更乐观。

---

## 1. 三个核心功能

| # | 功能 | 回答什么 | 靠什么 | 产出 |
| --- | --- | --- | --- | --- |
| 1 | 材料解析 | 客户给了什么、我认不认 | TextIn 解析出带页码的原文；DeepSeek 抽出项目要点与需求，**每条需求带着客户原文那一句**；人在这里确认（点「确认」= 进基线 + 立刻能力匹配） | 材料清单（可折叠）· 项目要点 · 项目需求（草稿 / 已确认，带原文引文与页码） |
| 2 | 能力匹配 | 这些需求我们能不能做 | 检索企业能力库与历史案例，规则层先给结论上限，DeepSeek 再组织表达 | 每条已确认需求的能力结论（完全支持 / 部分支持 / 暂不支持 / 待补依据）· 风险 · 依据；可按结论档或风险等级筛 |
| 3 | 售前建议 | 还剩什么没定、下一步怎么办 | 汇总判断的后果与所有待澄清问题 | 整体结论与匹配度 · 风险提示 · 要问客户/要问内部/要同步销售 · 不可承诺清单 |

三个功能的边界：材料解析讲事实与确认（材料里写着什么、这条算不算数）；能力匹配讲结论（能不能做、多危险）；售前建议讲下一步（还剩什么问题、谁去问）。项目要点只做核对、编辑、忽略，不进入确认流程。

确认在「材料解析 · 项目需求」里做：每条需求下面直接摆着**客户原文那一句**（不用翻 PDF），点「确认」= 进基线 + 立刻跑能力匹配；AI 措辞不对先「改写」再确认。
「能力匹配」页只列已进基线的需求：一条需求一张卡，结论（支持情况）、风险、依据都在卡上，依据可就地展开（含人工覆写与留痕）；页首两排筛选胶囊 —— 按结论档（待补依据 / 暂不支持 / 部分支持 / 完全支持）或按风险等级（高 / 中 / 低）看。
**人工判定优先**：在展开区底部可以改档并写明原因（记谁、什么时候、为什么）；改过之后这条需求不再被 AI 重跑覆盖，重跑任务会跳过它并如实报"已由人工判定 N 条跳过"。
售前建议页只回答「还剩什么没定」：一句结论 + 三句概括（风险 / 待澄清 / 下一步）常驻，三句都能点；
下面是两块：风险提示按高 → 中 → 低分区（每条都能点回它依据的那条需求），以及「要问谁」（要问客户 / 要问内部 / 要同步销售，标出哪条影响判断、哪条只影响承诺）。

需求优先级（P0 / P1 / P2）有明确口径，不是模型随口标：P0 = 客户写了硬性口径（必须 / 不得 / 不低于 / 不接受）或不做就交付不了；P1 = 影响方案、报价或工期的关键条件；P2 = 加分项与可选范围。抽完之后按同一套规则核对原文，找不到硬性表述就自动降一档（`agents.guard_priority`，降级条数进 job result 与日志），落库前还会把非法值收敛到三档；需求清单按优先级从高到低排，点卡片左侧的 P0/P1/P2 可以人工改档。

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
    prompts.py          四个步骤的提示词 + schema + 版本号（改提示词先改这里）
    db.py               SQLAlchemy engine / session / init_db
    models.py           核心对象（客户、项目、材料、需求、判断、证据、方案、活动…）
    domain.py           状态字典、中文标签词表、标签推断
    seed.py             账号 / 知识库 / 演示客户项目初始化
    routers/            auth · customers · projects · materials · analysis · agent · dashboard · knowledge · traces
    services/
      textin.py         TextIn xParse 客户端（同步 + 异步 + 轮询）
      llm.py            DeepSeek 客户端（JSON 输出、失败重试、规则回退）
      ai_ledger.py      AI 调用账本（trace_id · token · 耗时 · 失败成因 · 提示词版本）
      parse_pipeline.py 解析结果 → 带页码片段
      retrieval.py      标签 + 关键词混合检索（可替换为向量检索）
      agents.py         需求抽取 / 能力判断 / 售前建议三个 Agent + 证据校验
src/
  pages/                工作台、项目列表、项目工作台、登录
  components/project/   MaterialsModule（材料解析 + 需求确认）· RequirementsModule（能力匹配）
                        · MatchDetail（判断依据与人工覆写，挂在需求卡上）· JudgementPage（售前建议）
                        · ProjectContextBar（项目栏与证据抽屉）· AgentPanel
scripts/                测试用 RFP 生成、端到端冒烟测试与沙箱回归（regression_check / uitest_sandbox）
                        check_ai_ledger（账本与重试自测）· check_trace_api（账本接口验收）
                        make_testset_materials / check_testset（回归题库与效果评测，见 scripts/testset/README.md）
docs/information-hierarchy.md  界面信息层级原则、逐页精简清单与后续待办
docs/acceptance-checklist.md   验收清单：十项可当场验证的验收（怎么验 · 合格标准 · 不合格说明什么）
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
| 上传 / 粘贴材料 | 两处入口：「工作台 · 新建分析」和「材料解析 · 客户材料」都支持 —— 点「选择文件 / 上传材料」选文件，或点「材料输入」粘邮件 / 聊天记录（存成 txt 走同一条链路）；文件也可以直接拖到页面里 | L1 自动执行 |
| 整理需求 / 能力判断 / 生成售前建议 | 说「重新跑一遍分析」「做能力判断」「生成售前建议」 | L1 自动执行 |
| 一条龙跑完整流程 | 说「从头跑一遍完整流程」 | L1，但遇到人工闸门会停下等你 |
| **确认需求** | 说「帮我确认这些需求」→ 点「批准并执行」 | **L2 必须人批准**（服务端留痕：谁、什么时候） |
| 会话与回执卡 | 自动落库，刷新页面后对话与卡片都还在 | — |

两条原则：**动作进 Agent，产物留中间页**；**AI 只准备，人做承诺**。
右侧是核心交互面，内容不随中间页变；中间页是产物面，三个页签只切换看哪份产物。

想算账与复盘，看两个只读接口（都不改数据）：

- `GET /api/projects/{id}/ai-calls` —— 调用次数、token、失败、回退、按步骤分组，
  用来回答"贵在哪一步"；
- `GET /api/traces/{trace_id}` —— 一次运行（一次上传 / 一次"从头跑一遍" / 一次提问）的完整调用链，
  用来回答"这次到底调了什么、哪一步失败、为什么"。

出问题时还有一个**诊断现场**（前端埋点，只记元数据、不记任何正文）：

- `GET /api/events?limit=50` —— 全局最近事件；`?name=api_failed` 只看接口失败；
- `GET /api/projects/{id}/events` —— 某个项目的事件。

五个事件：`client_boot`（构建版本 / 后端地址 / 浏览器，回答"你看到的是哪一版"）、
`page_view`（去了哪页、从哪来、上一页停了几秒）、`api_failed`（路径 / 状态码 / 耗时 / 错误文案，
**不含请求体**）、`action_finished`（提取 / 匹配 / 生成建议 / 新建分析的结果与耗时，带 job id）、
`client_error`（前端报错与未捕获的 Promise）。上报失败静默、不阻塞交互，只发到自己的后端（不接第三方 SDK）。

### 7.2 开发须知（这几条是踩过坑总结的）

- **后端不要开 `--reload`**：这台机器上 WatchFiles 会卡在 `Reloading...` 不真正重启，新路由一直 404。
  改完后端手动重启：停掉 8000 端口的进程，再
  `Start-Process .venv\Scripts\python.exe -ArgumentList "-m","uvicorn","app.main:app","--host","127.0.0.1","--port","8000" -WorkingDirectory server`。
- **原能力回归**：`python scripts\regression_check.py --with-agent` —— 复制一份库、在 8010 起独立后端、跑完整链路
  （上传 → 解析 → 抽取 → 确认 → 判断 → 建议 + 对话与审批 + 调用账本），跑完自动删临时目录，不碰真实数据。
  它会先做**端口预检**：8010 上已经有别的实例（比如上一次没退干净、或另一个会话的沙箱）就直接失败 ——
  否则会连上别人的实例然后报假 PASS。遇到这种情况换个端口：
  `$env:FITWISE_SANDBOX_PORT="8021"; python scripts\regression_check.py --with-agent`。
- **账本与重试自测**：`python scripts\check_ai_ledger.py`（不调模型、不碰真实库，覆盖账本汇总、
  失败成因码、回退留痕、解析重试）；`python scripts\check_trace_api.py`（对着实例跑，验账本数字与业务对得上）。
- **提交前自检密钥**：`python scripts\check_no_secrets.py` —— 查三件事：待提交列表里有没有 .env 类文件、
  `server/.env` 里的真实密钥有没有被复制到代码里、有没有 sk- / ghp_ / AKIA / 私钥头这类硬编码。
  `.gitignore` 只防"文件名"，防不住"密钥被复制到别的文件"，两条一起才闭合。它只打印命中的文件名，不打印密钥内容。
- **效果评测（题库）**：`python scripts\regression_check.py --testset` —— 在沙箱里拿 6 份固定材料各建一个项目，
  走完整链路后算抽全率（阈值 80%）、越界率（必须 0）、证据覆盖（必须 100%）与需求条数区间。
  材料与答题卡在 `scripts/testset/`（说明见该目录 README）。
  想确认这套评测能判红：`python scripts\check_testset.py --only 01 --verify-red`。
  末尾会打两张**评测分数表**（链路 10 项 / 对话 5 项），其中最关键的是「越界检查：完全支持必须有支持证据」——
  它守的是这个产品的命门：结论不许比证据乐观。规则见 `scripts/scorecard.py`。
- **UI 沙箱**：`python scripts\uitest_sandbox.py` —— 复制库并把项目重置到「基线已定、还没判断」，
  再起 8010 后端 + 5199 前端，用来验证只有中途状态才会出现的交互。
- **演示数据**：`python scripts\demo_reset.py` —— 新建演示客户/项目、传一份合成 RFP、停在「需求待确认」。剧本见 `docs/demo-script.md`。
- **前端构建与起沙箱要提权**：esbuild 在沙箱里读不到项目文件（`vite build` 同理）。
- **清理进程要按端口或明确 PID**，不要按「最近启动的 python」批量杀 —— 会把后端一起杀掉。
