# 重构设计：Schedule 控制反转（Code-Owned Orchestration）

- 分支：`refactor/schedule-orchestrator`
- 范围：日程的生成、确认、调整、重排，涉及 coordinator、`schedule_tools`、`realtime_tools`、`api/routes/chat.py`、`api/routes/schedule.py` 和 ChatPage 的确认流程
- 状态：设计已定，待实施

---

## 1. 背景：反复出现的 bug

6/7 – 6/11 期间，schedule 相关的修复集中在下面几类：

| 症状 | 相关 commit | 当时的修法 |
|---|---|---|
| Gemini 输出格式不稳定：时间戳用下划线、混进自然语言、出现 12 小时制，dict 参数被序列化成字符串，事件 title 被改成 "Event" | `cae728c` `8c30008` `22ee779` | `_normalize_timestamp`、`json.loads` 兜底、prompt 规则 |
| Coordinator 不调工具，凭上下文"背"出一份日程（fake response） | `a285f0a` `a9f752e` | prompt 中加 `CRITICAL: NEVER write out a timed schedule…` |
| 用户确认的方案没写进后端；重新生成时把已确认的日程覆盖 | `8c30008` `a9f752e` `bb00e22` | 新增 `confirm_schedule`、`get_today_schedule`、`confirmed` 标记、`/schedule/confirm`，以及 `pending_proposal` 交接 |
| 重排错过的任务时用错工具（adjust 和 plan 混用） | `3dfd337` | 在 prompt 里写清楚两个工具各自的用法 |
| 任务时间重叠 | `80fd225` | prompt 规则加上 `_resolve_overlaps` |

到现在，`agents/coordinator.py` 的 INSTRUCTION 里仍有 13 处 `CRITICAL`、`MUST`、`ALWAYS`、`NEVER`；`api/routes/chat.py` 里还有一个"查 45 秒内生成的 DB 记录"的 fallback，专门用来兜住 LLM 没调工具的情况。

## 2. 根因

**本该由代码确定执行的控制流，交给了一个概率性的组件。**

现在的 coordinator（ADK `Agent`）同时承担四个角色：

1. **路由**：决定调哪个工具；
2. **状态机**：决定什么时候确认、什么时候先读当前状态；
3. **执行者**：工具本身带副作用，比如 `plan_schedule` 内部调用 `_persist_schedule` 写库；
4. **渲染器**：用自然语言把日程复述给用户。

状态也散落在三个地方：MongoDB 的 `daily_schedules`、ADK session 的对话上下文、LLM 的"记忆"。

`daily_schedules` 目前有 **4 个写入方**，规则各不相同：

| 写入方 | 位置 | 触发方式 |
|---|---|---|
| `_persist_schedule` | `agents/tools/schedule_tools.py:537` | LLM 调用 `plan_schedule` 时，作为副作用写入 |
| `confirm_schedule` tool | `agents/tools/schedule_tools.py:584` | LLM 判断用户确认了，并且记得调用 |
| `POST /schedule/confirm`（plan 分支） | `api/routes/schedule.py:113` | 前端按钮，或 `AFFIRM_RE` 正则匹配到"yes"这类短回复 |
| `POST /schedule/confirm`（adjust 分支） | 同上 | 前端按钮；直接信任客户端传上来的 `updated_schedule` |

所以本质上这是一个**选型错误**：日程这件事的路径可以穷举（生成、确认、调整、重排），属于 workflow 形态，却用了自主决策的 agent 来实现。prompt 规则等于用自然语言给一个概率性的状态机写规格说明，因此修完一个还会冒出下一个。

## 3. 目标与非目标

**目标**
- G1：日程状态只有一份数据源，所有写入都经过**同一个**服务。
- G2：状态转换全部由代码执行。LLM 只能**提议**，不能**提交**。
- G3：LLM 只出现在两个**无副作用**的边界：一是意图解析，二是日程生成。两者的输出都受 schema 约束，并且经过校验。
- G4：前端展示的日程永远来自状态，不来自 LLM 写的文字。
- G5：删掉 coordinator 里和日程相关的 prompt 约束、`get_today_schedule` 和 `confirm_schedule` 工具，以及 chat.py 里的 45 秒 fallback。

**非目标**
- 不改 Goal Agent 内部（`agents/goal/`）、health pipeline、geo 计算逻辑。
- 不改前端视觉，只改数据流。
- 不做多日规划、鉴权或多用户并发之外的扩展。

## 4. 目标架构

```
POST /chat/
   │
   ▼
[code] load_turn_context(user_id, date)
       = DayPlan（当前状态） + preload 上下文（goals / health / relationship / calendar / pending_reschedule）
   │
   ▼
[LLM①] parse_intent(message, turn_context) → Intent
       Pydantic + Gemini response_schema；无工具、无副作用
   │
   ├── intent = chat ──────────► [LLM] 只读对话 agent（原 coordinator 去掉日程写工具）
   │                                   → reply（文字），不改变状态
   │
   └── intent ∈ 日程类 ────────► [code] DayPlanService.handle(command)
                                   │  1. 校验当前状态是否允许这个转换
                                   │  2. 需要生成时调用 [LLM②] generator（纯函数）
                                   │     → 校验 schema 和不变量 → 失败重试一次 → 仍失败则返回显式错误
                                   │  3. 唯一写入口：repository.save(day_plan, expected_version)
                                   ▼
                                 TurnResult { day_plan, reply }
   │
   ▼
ChatResponse { reply, day_plan }   ← 前端只根据 day_plan 渲染方案和日程
```

核心原则：**LLM 只能提议，只有代码能提交。**

## 5. 领域模型与状态机

### 5.1 DayPlan（每个 `user_id + date` 一份）

```python
# schemas/day_plan.py
class ActivePlan(BaseModel):
    strategy_name: str            # "Most Productive" | "Most Relaxed" | "Fastest" | "Adjusted"
    tasks: list[ScheduleTask]
    confirmed_at: str             # ISO

class Proposal(BaseModel):
    proposal_id: str              # uuid
    kind: Literal["plan", "adjust"]
    strategies: list[ScheduleStrategy]   # adjust 时只有一个 strategy，名为 "Adjusted"
    top_recommendation: str
    explanation: str = ""         # adjust 的 what_changed 和 message
    based_on_version: int | None  # adjust 时记录基于哪个版本的 active
    created_at: str

class DayPlan(BaseModel):
    user_id: str
    date: str                     # YYYY-MM-DD
    active: ActivePlan | None = None
    proposal: Proposal | None = None
    version: int = 0              # 乐观锁，每次写入加 1
```

`status` 由两个字段推导，不单独存储：

| active | proposal | status |
|---|---|---|
| None | None | `EMPTY` |
| None | 有 | `PROPOSED` |
| 有 | None | `CONFIRMED` |
| 有 | 有 | `CONFIRMED_WITH_PROPOSAL` |

### 5.2 Commands 与转换规则

| Command | 前置条件 | 效果 | 用到 LLM② 吗 |
|---|---|---|---|
| `GeneratePlan(date, new_events, focus_tasks)` | 任意状态 | `proposal = 新的 plan 方案`；**`active` 不动** | 是 |
| `AdjustPlan(trigger, detail, new_events)` | `active` 存在 | `proposal = 新的 adjust 方案（based_on_version = version）` | 是 |
| `ConfirmProposal(proposal_id?, strategy_name)` | `proposal` 存在；`strategy_name` 在 `proposal.strategies` 中 | `active = 这个 strategy 的 tasks`；`proposal = None` | 否 |
| `DiscardProposal()` | `proposal` 存在 | `proposal = None` | 否 |
| `RescheduleMissed(target_date?)` | `pending_reschedule` 存在 | 在 target_date 上执行 `GeneratePlan`，把 missed tasks 作为 `focus_tasks` 传入 | 是 |

前置条件不满足时，抛出 `InvalidTransition(reason)`，由 orchestrator 转成一句友好的回复（例如"还没有生成方案，要我先帮你排一下吗？"）。**不要**把这种情况交给 LLM 去自行判断。

补充两条规则：
- `pending_reschedule` 在**目标日期的方案被确认**时，由 `ConfirmProposal` 在同一次写入中清除，不在生成时清除。为此 Proposal 需要额外带一个 `consumes_pending_reschedule: bool`。
- adjust 方案确认时，如果 `based_on_version` 不等于当前 version，说明 active 已经被改过，拒绝确认，并提示用户重新调整。

### 5.3 不变量（由代码保证，`DayPlanService` 每次写入前都要校验）

1. 任意两个 task 的时间不重叠。复用 `_resolve_overlaps` 和 `_validate_and_fix`。
2. `calendar_event` 和 locked block 的 title、时间、location **原样保留**。
3. 所有时间都是 `YYYY-MM-DDTHH:MM:SS`，且落在目标日期上（跨午夜的情况单独处理）。
4. `ConfirmProposal` 只能从 **DB 里已有的 proposal** 中选 strategy，不接受客户端传上来的 tasks。
5. 写入使用 `find_one_and_update({..., version: expected})`；version 不匹配时抛出 `ConcurrentModification`。

### 5.4 存储与兼容

- 集合仍然是 `daily_schedules`，key 仍然是 `(user_id, date)`。
- 新字段：`active`、`proposal`、`version`。
- **读取兼容旧文档**，由 repository 负责映射：
  - `confirmed == True` 时，`active = {strategy_name, tasks}`；
  - `all_strategies` 存在且 `confirmed != True` 时，`proposal = {kind: "plan", strategies: all_strategies, top_recommendation: strategy_name}`。
- 写入时只写新字段，同时清掉旧字段（`$unset`）。
- `GET /schedule/today` 改为读 `active.tasks`，返回结构 `{tasks}` 保持不变，geo enrichment 逻辑也不动。
- "今天"的计算统一用一个 helper `today_for(user_id)`。现在代码里 `date.today()` 和 `datetime.utcnow().date()` 混用，见 chat.py 的 fallback。

## 6. LLM 边界

### 6.1 LLM①：意图解析 `agents/intent.py`

```python
class EventSpec(BaseModel):
    title: str                    # 必须是用户原话或上下文里的原标题
    start_time: str | None = None # 能确定时用 ISO
    end_time: str | None = None
    time_hint: Literal["morning", "afternoon", "evening", "now", "unspecified"] | None = None
    duration_minutes: int | None = None
    location: str | None = None

class PlanDay(BaseModel):     type: Literal["plan_day"];   target_date: str | None; new_events: list[EventSpec] = []; focus_tasks: list[str] = []
class Adjust(BaseModel):      type: Literal["adjust"];     trigger: Literal["new_event","task_overrun","energy_update","location_change"]; detail: str; new_events: list[EventSpec] = []
class Confirm(BaseModel):     type: Literal["confirm"];    strategy_name: str | None   # None 表示选推荐方案
class Discard(BaseModel):     type: Literal["discard"]
class Reschedule(BaseModel):  type: Literal["reschedule_missed"]; target_date: str | None
class Chat(BaseModel):        type: Literal["chat"]

Intent = Annotated[PlanDay | Adjust | Confirm | Discard | Reschedule | Chat, Field(discriminator="type")]
```

- 调用方式：`generate_content(..., response_mime_type="application/json", response_schema=IntentEnvelope)`，再用 Pydantic 校验。如果 Gemini 对 discriminated union 的支持有限，就改成扁平的 envelope（`type` 加上所有可选字段），由代码拆分。**实施时先验证这一点。**
- 解析器的输入要包括当前 `DayPlan.status`、proposal 里的 strategy 名称、今天的日历事件和 `pending_reschedule`，让模型知道哪些意图在当前状态下合理。但**合不合法由代码判断**，模型不负责。
- 时间换算移到代码里：`time_hint` 到具体时间段的映射（morning 对应 08–12，以此类推）、默认时长 2h，都在 `resolve_event(EventSpec, date, now)` 里完成。这样 prompt 里对应的规则就可以删掉。
- 解析失败或校验失败时，降级为 `Chat`。宁可多聊一句，也不能误改状态。

### 6.2 LLM②：日程生成（纯函数）

- `agents/tools/schedule_tools.plan_schedule` 拆成两个函数：
  - `generate_schedule(inp: ScheduleInput) -> ScheduleOutput`：只调 LLM，接着做 `_enforce_constraints`、`_validate_and_fix`，**不写库**；
  - 原来的 `_persist_schedule` 删除，写库交给 `DayPlanService`。
- `realtime_tools.adjust_schedule` 同样拆出 `generate_adjustment(active_tasks, trigger, detail) -> RealtimeOutput`，**并补上和 plan 相同的不变量校验**（现在完全没有校验）。
- 都加上 `response_schema`。如果 Pydantic 模型直接作为 schema 不兼容（比如带默认值、`dict` 字段），就单独定义一个 `*LLMSchema` 给模型用，再映射成领域模型。
- 失败策略：校验不通过时重试 1 次，仍失败则抛出 `GenerationFailed`。Orchestrator 返回明确的错误文案，**不要**像现在这样悄悄返回一个兜底日程（对应 handover 文档 3.1 里的 9pm–11pm 问题）。
- `calendar_events` 不再由 LLM 搬运：今天的 Google Calendar 事件和 upcoming events 由代码直接放进 `ScheduleInput.calendar_events`，LLM① 只负责提取用户**本轮新提到的**事件。

### 6.3 只读对话 agent

- `build_coordinator` 保留，用来处理 `Chat` 意图，比如"我今天该专注什么""最近为什么累"。
- 从工具列表中**移除**：`plan_schedule`、`adjust_schedule`、`confirm_schedule`、`get_today_schedule`、`clear_pending_reschedule`。
- 保留：`read_user_context`、memory 相关工具、`analyze_health`、`track_goals`、`get_relationship_context`、`get_geo_info`、`check_performance`。
- 在 `_preload_user_context` 里加上当前 DayPlan 的摘要（active 的 strategy 和 tasks 数量、proposal 是否存在），让它回答"我今天安排了什么"这类问题时有真实依据。
- INSTRUCTION 删掉 MODE B 和所有日程相关规则，加一句"如果用户想改日程，引导他直接说出需求"。
- Goal Tracking sub-agent（`goal_tracking_root`）挂载方式不变。

## 7. 模块与文件改动

| 文件 | 改动 |
|---|---|
| `schemas/day_plan.py` | **新增**：DayPlan、ActivePlan、Proposal、Commands、领域错误 |
| `services/day_plan_repository.py` | **新增**：读取（含旧文档映射）、带版本号的写入；是 `daily_schedules` 唯一的写入方 |
| `services/day_plan_service.py` | **新增**：`handle(command) -> DayPlan`，负责转换规则和不变量校验 |
| `services/turn_orchestrator.py` | **新增**：`run_turn(user_id, message, session_id) -> TurnResult`，串起意图解析、分发、生成回复 |
| `agents/intent.py` | **新增**：LLM① 意图解析，以及 `resolve_event` |
| `agents/tools/schedule_tools.py` | `plan_schedule` 改为 `generate_schedule`（纯函数）；删除 `_persist_schedule` 和 `confirm_schedule` |
| `agents/tools/realtime_tools.py` | `adjust_schedule` 改为 `generate_adjustment`（纯函数，加校验）；删除 `get_today_schedule` |
| `agents/tools/__init__.py` | 同步导出 |
| `agents/coordinator.py` | 变成只读对话 agent（见 6.3） |
| `api/routes/chat.py` | 改为调用 `turn_orchestrator.run_turn`；删除 function_response 截获和 45 秒 DB fallback |
| `api/routes/schedule.py` | `/confirm` 改为接收 `{user_id, date, proposal_id, strategy_name}` 并走 service；`/today` 改读 `active`；新增 `GET /schedule/day?user_id&date` 返回完整 DayPlan |
| `frontend/src/utils/api.js`、`pages/ChatPage.jsx`、`components/AgentDrawer.jsx`、`store/useStore.js` | 根据 `day_plan.proposal` 渲染方案；确认时只发 `proposal_id + strategy_name`；`AFFIRM_RE` 快捷路径可以保留，但必须调用同一个 confirm 接口 |
| `docs/api.md` | 更新 `/chat` 和 `/schedule/*` 的接口约定 |

### API 约定变化

```jsonc
// POST /chat/ 响应
{
  "reply": "string",
  "session_id": "string",
  "day_plan": { /* DayPlan，前端渲染的唯一依据 */ },
  "error": null | { "code": "generation_failed" | "invalid_transition", "message": "..." },
  // 过渡期保留，Phase 5 删除：
  "pending_proposal": { ... },   // 从 day_plan.proposal 映射出来，兼容旧前端
  "schedule_updated": true
}

// POST /schedule/confirm 请求
{ "user_id": "...", "date": "YYYY-MM-DD", "proposal_id": "...", "strategy_name": "Most Relaxed" }
```

## 8. 实施阶段

每个阶段单独 commit，结束时测试必须全绿，并且应用可以运行。

**Phase 1：领域模型与唯一写入口（不改变外部行为）**
- 新增 `schemas/day_plan.py` 和 `services/day_plan_repository.py`、`day_plan_service.py`。
- 让现有三个写入方（`_persist_schedule`、`confirm_schedule` tool、`/schedule/confirm`）内部改为调用 service，外部接口不变。
- 测试：转换规则（每条前置条件的正反例）、不变量、旧文档映射、version 冲突。

**Phase 2：生成器纯函数化**
- 拆出 `generate_schedule` 和 `generate_adjustment`，加 `response_schema`、校验和重试，失败时返回显式错误。
- 工具层暂时保留一层薄包装，内部调用"生成器加 service"，保证 coordinator 还能用。
- 测试：用 stub 替换 genai client，覆盖格式错误、重叠、事件被改名、重试后成功、重试后仍失败。

**Phase 3：意图解析与 orchestrator**
- 新增 `agents/intent.py` 和 `services/turn_orchestrator.py`，chat.py 切换过去。
- 加配置开关 `settings.use_schedule_orchestrator`，默认为 True，旧路径保留以便回退。
- coordinator 去掉写工具，改成只读 agent。
- 测试：用 stub 替换 LLM①、LLM② 和只读 agent，逐条覆盖第 1 节的历史 bug 场景（见第 9 节）。

**Phase 4：前端切换**
- 根据 `day_plan` 渲染；确认改为发送 `proposal_id + strategy_name`；处理 `error` 字段。
- 手动验收：见第 9.3 节。

**Phase 5：清理**
- 删除旧工具、`_persist_schedule`、45 秒 fallback、`pending_proposal` 兼容字段、开关和旧路径、INSTRUCTION 里的日程规则。
- 更新 `docs/api.md` 和 `readme.md` 的架构段落。

## 9. 测试与验收

### 9.1 测试环境
- 沿用 `tests/conftest.py`，用 testcontainers 起 `mongo:7`，**需要本机能运行 Docker**。
- 新测试放在 `tests/unit/test_day_plan_*.py` 和 `tests/integration/test_schedule_orchestrator.py`。
- 所有 LLM 调用都通过依赖注入换成 stub，测试不访问网络。

### 9.2 必须有的回归场景（对应历史 bug）

| # | 场景 | 期望 |
|---|---|---|
| R1 | 已确认 Most Relaxed，用户再说"plan my day" | 生成新的 proposal，`active` 不变 |
| R2 | 用户说"let's go with most relaxed"（`AFFIRM_RE` 匹配不上的确认说法） | 意图为 `confirm`，`active` 是 Most Relaxed，proposal 清空 |
| R3 | 没有 proposal 时用户说"confirm" | 返回 `invalid_transition`，状态不变 |
| R4 | 有 active 时用户说"3 点加个会" | 产生 `adjust` proposal，active 不变；确认后 active 更新 |
| R5 | adjust proposal 生成后 active 被改过，再确认这个 adjust | 返回 `ConcurrentModification`，拒绝 |
| R6 | 有 `pending_reschedule`，用户同意挪到明天 | 生成明天的 plan proposal，并带上 missed tasks；确认后 `pending_reschedule` 被清除 |
| R7 | 生成器返回带下划线的时间戳、重叠的任务、被改名的日历事件 | 校验修正或重试，最终写入的方案满足全部不变量 |
| R8 | 生成器两次都失败 | 返回 `generation_failed`，**不写入**任何兜底日程 |
| R9 | 用户问"我今天该专注什么" | 走只读 agent，状态不变，DB 无写入 |
| R10 | 客户端伪造 tasks 调用 `/schedule/confirm` | 被忽略，只按 `proposal_id + strategy_name` 从 DB 里取 |

### 9.3 验收清单
- [ ] `grep -rn "DAILY_SCHEDULES" --include=*.py` 中，写操作（`update_one`、`insert`、`find_one_and_update`）**只**出现在 `day_plan_repository.py`
- [ ] coordinator 的工具列表里没有任何会写 `daily_schedules` 的工具
- [ ] INSTRUCTION 中不再有日程相关的 `CRITICAL`、`MUST`、`ALWAYS`、`NEVER`
- [ ] `chat.py` 中没有基于时间窗口的 DB fallback
- [ ] R1–R10 全部通过，原有测试不回归
- [ ] 手动走一遍 `docs/demo_script_v2.md` 的核心流程：plan、确认、加事件调整、确认、第二天重排

## 10. 取舍与风险

| 风险 | 应对 |
|---|---|
| 意图种类没覆盖到的说法被误判 | 判不准时降级为 `chat`，由只读 agent 回答并引导用户说清楚；把误判的日志收集起来，再扩充意图种类 |
| 多了一次意图解析的 LLM 调用 | 意图解析用 flash 模型、`thinking_budget=0`，而且省掉了 coordinator 多轮工具调用的开销，预计总延迟持平或下降。Phase 3 前后各测一次 `chat.llm_duration` |
| Gemini `response_schema` 对复杂 Pydantic 类型支持有限 | 单独定义扁平的 LLM schema，再映射成领域模型（见 6.1 和 6.2） |
| Demo 脚本依赖旧行为（主动推送、MODE A 话术） | Phase 4 手动验收时逐条核对 `docs/demo.md` 和 `demo_script_v2.md` |
| 和队友正在进行的改动冲突 | 本分支只动表 7 中的文件；合并前先 rebase `main` |
