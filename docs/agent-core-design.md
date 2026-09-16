# 最小 Agent 内核设计：契约化的 AI 步骤 + 一道独立 guardrail

> 目标：在「流程能跑通」「是 MVP 产品」「本质是 AI Agent」三个约束下，把 Fitwise 的
> AI 能力做实。本文取代早期"把自检塞进 Agent 内部"的写法。

## 1. 定位：本项目里的 AI Agent 指什么

一个 AI agent 就是**流程里一个 LLM 步骤**，它必须同时具备四个契约：

| 契约 | 在本项目里的实现 |
| --- | --- |
| 输入映射 | 显式声明喂给模型的内容（哪些材料的哪些片段），而不是默认整条记录 |
| 指令 | `system` + `user` 提示词，职责单一（抽取 / 判断 / 建议 / 路由各一份） |
| 结构化输出 | 强制 JSON，落库前校验必填字段；不合规就重试，再不合规走规则回退 |
| 响应映射 | 结论、证据、页码由后端映射回库，模型不直接写引用 |

据此，Fitwise 有 **4 个 agent 步骤**：

1. `analyze_requirements` —— 材料 → 草稿需求 / 项目要点 / 待确认问题 / 材料摘要
2. `judge_requirement` —— 单条需求 → 结论 + 理由 + 缺口（结论上限由规则层给）
3. `compose_solution` —— 匹配结果 → 解决路径 / 风险 / 待确认项
4. `route_message` —— 用户提问 → 回答或动作提议

以及 **1 道 guardrail**（见第 3 节）和 **1 条确定性主线**（材料 → 需求 → 确认 → 判断 → 建议）。

### Agent 自主到什么程度

- **自主**：这条需求的证据够不够、要不要标"待补依据"、要问客户什么。
- **不自主**：主线顺序（由 `next_step` 状态机给）、需求能否成为基线（人的闸门）、
  对客承诺（人的决定）。

### 无状态是默认

三条分析链路（抽取 / 判断 / 建议）**保持无状态**：同样输入应得到同样结果，方便回归与评测。
只有右侧对话引入会话标识（本项目就是 `project_id`），用来让问答有上下文。
把记忆做进分析链路会破坏可复现性，也让成本不可预测。

## 2. 为什么不把自检写在 Agent 内部

早期设计让 `judge_requirement` 自己检查自己。问题有三：

1. 指令要同时承担"判断"和"审自己"，职责不单一，提示词很快会互相打架；
2. 自检结论无法独立调阈值、独立复用、独立测试；
3. 裁决和结论混在一个对象里，出错时看不出是哪一层的问题。

正确分工是：**agent 干活 → guardrail 出裁决 → 父流程（`_run_matching`）决定怎么处理**。
guardrail 只标记不拦截，这与产品哲学同构：AI 只准备，人做承诺。

## 3. Guardrail：证据自检

`evidence_guardrail()` 是确定性函数（不调模型），输入是一条判断的全部上下文，
输出一份裁决：

```json
{
  "flagged": true,
  "reasons": [{ "code": "support_conflict_with_gap", "severity": "block", "detail": "…" }],
  "metrics": { "support": 2, "constraints": 1, "sources": 2, "unique_support_pages": 2 }
}
```

### 检查项

| code | 判定 | severity | 触发后的处置 |
| --- | --- | --- | --- |
| `source_not_located` | 需求来源在材料里定位不到原文 | block | 结论最多部分支持，标"来源未定位" |
| `source_missing` | 需求没有来源材料或来源页码 | block | 同上 |
| `no_support_signal` | 结论为完全支持但没有命中支持信号 | block | 降为部分支持 |
| `support_conflict_with_gap` | 同一条需求同时命中支持与缺口信号 | block | 降为部分支持，冲突两侧都写进结论 |
| `unverified_citation` | 模型写的理由里出现证据之外的页码 | warn | 保留结论，在自检里标注（界面提示"页码未验证"） |
| `evidence_reused` | 同一文档同一页被重复计为多条证据 | warn | 证据数按去重后计算 |
| `llm_fallback` | 本次结论来自规则回退（模型不可用/输出不合规） | warn | 界面标注"本次为规则结果" |

### 降级规则

`_cap_status_by_guardrail()`：**flagged 只降不升**——
`full → partial`，`partial` 保持，`none/unknown` 保持。
调用方拿到 `(最终状态, 降级原因)` 后写进轨迹。

### 阈值

`block` 类规则默认全开；如果发现"所有结论都被降级"（说明阈值过严、产品失去价值），
调的是**规则集**而不是模型。这条经验来自同类平台的告警配置：阈值过松会放过问题，
过严会淹没有效信号，唯一可靠的调法是拿真实项目做评测集回归。

## 4. 四处"静默"问题的处置

同类系统里最容易出事的不是模型答错，而是**系统悄悄降级了却没人知道**。本设计逐条处理：

| 静默问题 | 现在的行为 | 处置 |
| --- | --- | --- |
| 静默覆盖 | 重跑抽取整批删草稿、整批覆盖 `open_questions` | 草稿按 `edited` 保留；`open_questions` 改为**合并去重**（只增不丢） |
| 静默回退 | 模型失败走规则结果，只有日志知道 | `chat_json` 回传 `fallback_used`，写进轨迹与 `self_check`，界面标注 |
| 静默截断 | 材料 digest 45k 封顶、需求 40 条、要点 10 条 | 截断与超限计数进 job result 与日志，界面可查 |
| 静默改写 | 证据定位失败时回填成该材料第一块 | 改为明确失败：标 `source_not_located`，不再伪造页码 |
| 隐式输入 | 全部材料压成 digest 默认喂进去 | 输入在提示词里显式声明（材料清单 + 页码），后续再按需求相关度筛选 |

## 5. 契约升级

- **输出校验**：`chat_json(required_keys=[...])` —— 模型返回缺少必需字段时按失败处理
  （重试一次 → 规则回退），而不是用默认值把问题吃掉。
- **模型选择**：按任务复杂度分流——抽取/判断用强模型，对话路由与换词用便宜模型；
  换词策略优先走规则同义词表（零成本），模型只做兜底。
- **提示词集中且有版本号**：四个步骤的指令与 schema 都在 `app/prompts.py`，
  每步一个版本号（`extract@2026-09-16.1` 这种），改提示词就递增；`PROMPT_SET_VERSION`
  是整体版本，方便按批次回归对比。
- **版本可追溯**：轨迹里记录模型名、耗时、尝试次数、是否回退，并带上提示词版本与
  trace_id；结论可回答"用哪版模型、哪版提示词算出来的、属于哪一次运行"。
- **失败成因与重试策略**：每次失败都归类（`timeout` / `network` / `rate_limit` /
  `server_error` / `auth` / `bad_json` / `missing_keys` …）。网络与限流类重试一次，
  输出不合规也重试一次（模型输出有随机性），凭据错与请求不合法直接走回退 ——
  不把一轮等待浪费在注定失败的请求上。解析侧（TextIn）与模型侧同一套判定。
- **调用账本**：`ai_calls` 表记录每次调用的 trace_id / step / provider / model /
  prompt_version / attempts / latency / tokens / fallback / 失败码。一次用户动作
  （一次上传、一次"从头跑一遍"、一次提问）就是一个 trace_id，解析 → 抽取 → 每条判断 →
  建议都能按同一个 id 复盘。写账本走 savepoint 隔离，写不进去只记日志，不影响业务。

## 6. 能力核对（建之前先对一遍）

每个动作先问它落在哪一层，三层都不覆盖就是缺口：

| 动作 | 落在哪一层 |
| --- | --- |
| 读材料（PDF/图片/表格） | 下游步骤（TextIn xParse） |
| 抽需求 / 要点 / 问题 | 模型原生（结构化抽取） |
| 检索能力库与案例 | 工具（本地检索函数） |
| 结论能不能做 | 不外包：规则上限 + guardrail（刻意设计，不是缺口） |
| 回填页码、点回原文 | 下游（响应映射 + 原文预览） |
| 跨材料冲突检测 | **缺口**：需"下游对齐 + 模型解释"两段式，不能让模型自己发现矛盾 |

## 7. 变更清单与影响面

### 已实现（Agent 内核那一轮）

- `models.py` / `db.py`：`MatchResult` 新增 `trace`、`self_check` 两列（轻量迁移自动补列）。
- `services/llm.py`：`chat_json` 支持 `required_keys` 校验与 `meta` 回传（模型、耗时、尝试次数、是否回退）。
- `services/agents.py`：
  - `locate_evidence()` 取代 `_find_evidence_chunk()`：定位失败明确返回失败，不再兜底成第一页；
  - `evidence_guardrail()` + `_cap_status_by_guardrail()`：独立裁决与降级；
  - `judge_requirement()`：写 `trace`（检索 → 判断 → 自检 → 决策）与 `self_check`；
    `confidence` 改为由证据派生，不再用模型自报数字；
  - `analyze_requirements()`：`open_questions` 合并去重、截断/超限/未定位计数；
  - `compose_solution()`：`steps` 状态被判断结果校正、能力组合强制来自检索聚合。
- `routers/analysis.py`：判断只对**已确认**需求执行（人工闸门下沉到 service 层）；
  `confirm_requirements` 始终带 `project_id` 过滤；guardrail 结论并入 `open_questions`。
- 并发重复（回归时实测到的问题）：`jobs.find_running()` 让"确认后自动跑"与"再点一次"
  复用同一个任务；`agents.analyze_requirements()` 清理同名草稿、`_run_matching` 清理同一需求的
  旧结论 —— 之前同一条需求会出现两条话术不同的判断。
- `serializers.py` / `src/api/types.ts` / `MatchingTab.tsx`：判断详情展示"取证过程"与自检结果，
  "AI 把握度 XX%" 换成证据统计。
- `scripts/check_agent_guardrail.py`：guardrail 的确定性自测（不调模型）。
- `scripts/check_agent_conversation.py`：审批链检查先自铺前置条件（确保有待确认需求），
  不再依赖上一个脚本留下的状态。

### 已实现（工程化加固那一轮：版本、账本、重试）

这一轮不加产品能力，只补"能不能回滚、能不能算账、挂了知不知道为什么"：

- `app/prompts.py`（新）：四个步骤的 system 提示词、schema 与 user 模板集中一处，
  带 `PROMPT_SET_VERSION` 与每步版本号；`agents.py` / `agent_router.py` 不再内联提示词。
- `models.py`：新增 `AiCall`（`ai_calls` 表）。`init_db()` 的 `create_all` 会自动建表，
  已有演示库不需要重建。
- `services/ai_ledger.py`（新）：账本写入（savepoint 隔离，失败不影响业务）、
  按 trace 复盘、按项目汇总（次数 / token / 失败 / 回退 / 平均耗时 / 按步骤分组）、
  失败成因码与"可不可重试"的判定。
- `services/llm.py`：`chat_json` 结算 token（`usage`）、归类失败成因、
  把 trace_id / step / prompt_version / on_call 交给账本；不再对注定失败的请求做第二次尝试。
- `services/textin.py`：可重试失败（网络 / 超时 / 限流 / 5xx）自动重试一次，
  不可重试（凭据错、文件内容问题）立即失败；失败成因码回传上层。
- `services/parse_pipeline.py`：解析步骤也进账本，`material.parse_error` 带成因码前缀
  （`[timeout] …` / `[auth] …`），界面可以据此给不同的下一步提示。
- `routers/traces.py`（新）：`GET /api/projects/{id}/ai-calls`（成本口径）、
  `GET /api/traces/{trace_id}`（复盘口径）。
- `routers/analysis.py` / `routers/materials.py` / `routers/agent.py`：一次运行一个 trace_id
  （后台任务用 job_id，上传与提问各生成一个），判断的 job result 也带上提示词版本。
- 自测脚本：`scripts/check_ai_ledger.py`（账本、成因码、回退留痕、解析重试，不调模型）、
  `scripts/check_trace_api.py`（账本接口与业务的数字要对得上）。
- `scripts/regression_check.py`：加端口预检 —— 端口上已有别的实例时直接失败，
  不再"连上别人的服务然后报 PASS"（这个假阳性在实际回归里真实发生过一次）。

### 下一阶段（未做，按优先级）

1. **判断批量化**：5–8 条一批，把 10 条需求从约 1 分钟压到 20 秒内，并加 token 预算与终止条件；
   账本现在能给出这一改造前后的实测对比（调用次数、token、耗时）。
2. **换词再检索**：弱命中时用规则同义词换词重查一次（上限 2 轮），仍不足再降级为待确认。
3. **检索升级**：SQLite FTS5 / pgvector + BM25 混合，材料分片进索引（现在是全表扫描）。
4. **跨材料冲突检测**：把同 label 的事实（如工期口径）对齐后比对，输出差异卡片。
5. **判断结果缓存**：以（需求文本 + 知识库版本 + prompt 版本）为键复用判断，重跑时直接命中。

### 已实现（效果评测那一轮：把"跑得通"变成"有分数"）

链路回归只能回答"有没有坏"，回答不了"好不好"。这一轮补了效果评测的**题库**：

- `scripts/make_testset_materials.py` + `scripts/testset/expected.json`：6 份固定材料与人工答题卡
  （长材料 / 口径冲突的答疑 / 无页码的邮件 / 无文字层的扫描件 / 全超范围的清单 / 故意损坏的文件）。
  答题卡必须人工写 —— 让 AI 生成答题卡就变成 AI 给自己打分。
- `scripts/check_testset.py`：每份材料建一个独立项目走完整链路，算四个数：
  抽全率（阈值 80%）、越界率（必须 0，对应"不比证据乐观"）、证据覆盖（必须 100%）、
  需求条数区间（兜噪音）；同时打印结论分布、耗时、调用次数与 token。
  默认拒绝对着 8000 的演示实例跑。
- `--verify-red` 自检：故意把答题卡改坏，确认分数表会变红 —— 防止"全绿但没有牙齿"的假评测。
- 首轮实测（2026-09-16，6 份材料 31 项全过）：长材料 19 条需求 → 21 次调用 / 45,477 token / 188 秒；
  "大幅面工程图纸"被判**暂不支持**、"数据不得留存或用于训练"被判**待补依据** —— 规则上限按预期生效。

## 8. 验收标准

- 故意把一条需求改成知识库没有的能力：结论必须是"待补依据"，且不出现被改写过的页码。
- 把一条需求的 `source_excerpt` 改成材料里不存在的句子：must 出现 `source_not_located`，
  结论最多部分支持。
- 拔掉 `LLM_API_KEY` 重跑判断：结论仍然产出，且界面标注"本次为规则结果"。
- 重跑抽取两次：人工编辑过的草稿与已处理过的待确认问题都不丢。
- 直接调 `/matches/run` 而不确认需求：拿到明确的拒绝信息，而不是一份基于草稿的结论。
