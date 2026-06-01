# Goal Tracking Agent — ADK Integration Refactor

**Branch:** `feature/goal-agent-adk`  
**Author:** Astrid  
**Last updated:** 2026-06-01  
**Status:** Phase 1 + Phase 2 (tool layer) complete; Phase 3–7 pending

---

## 1. Context & Architecture Decisions

### Background

The Goal Tracking Agent was originally a standalone FastAPI microservice with its own
ADK multi-agent hierarchy, MongoDB collections, REST event endpoints, Cloud Scheduler
jobs, and a 22-scenario integration test suite. A bad merge on the `frontend` branch
deleted all source files; only `.pyc` caches survived. This branch (`feature/goal-agent-adk`)
reconstructs from git history (commit `e04c449`) and the five design documents restored
by the author, then integrates the full agent hierarchy into the consolidated DayPilot
backend.

### Architecture decisions (confirmed, immutable for this branch)

**Decision A — Single ADK Runner.**
The `daypilot_coordinator` and `goal_tracking_root` share one `google.adk.runners.Runner`
instance inside the same FastAPI process. The coordinator transfers control to
`goal_tracking_root` via ADK's `transfer_to_agent` mechanism when the user's intent is
goal-related. No second process, no separate ADK App Runner.

**Decision B — Single MongoDB database.**
All new collections (`goals`, `intake_sessions`, `weekly_memory_writes`, `event_log`)
are created in the same `daypilot` MongoDB database as the existing collections
(`entities`, `user_preferences`, `goal_state`, `user_credentials`, `conversation_memory`).
No separate `goal_tracking` database.

### Integration model

```
User ──chat──▶  daypilot_coordinator (LlmAgent)
                     │
                     ├─ [check_progress intent] ──▶ track_goals() tool
                     │                               (deterministic, no LLM)
                     │
                     └─ [goal-mutating intent] ──▶ transfer_to_agent
                                                    │
                                              goal_tracking_root (LlmAgent)
                                                    │
                                     ┌──────────────┼────────────────┐
                                 goal_intake_agent  progress_tracking  overdue_handler
                                     │
                           ┌─────────┼──────────────┐
                      validation_loop  decomposition  feasibility_workflow
                                                           │
                                              ┌────────────┼────────────┐
                                          time_layer  habit_layer  load_layer
                                                           │
                                                     synthesis_agent

Schedule Agent events ──POST /v1/events/*──▶ FastAPI route handlers (no LLM)
Cloud Scheduler       ──POST /v1/scheduled/*─▶ daily_output_builder / weekly_memory_writer
```

**Read-only path** (`check_progress`, daily output assembly): the coordinator tool
`track_goals(user_id)` reads directly from MongoDB and returns `GoalsOutput`. No
sub-agent invocation needed — deterministic, no LLM in the hot path.

**Multi-turn / mutating path** (`add_goal`, `update_goal`, `abandon_goal`,
overdue handling): the coordinator transfers to `goal_tracking_root`, which owns
the conversation window until a complete, confirmed goal has been written to the DB.

**Event ingestion path**: `POST /v1/events/overdue|subtask-scheduled|subtask-completed`
are pure HTTP handlers. They write directly to MongoDB via DB tool functions. No ADK
Runner is invoked. Fast and idempotent.

---

## 2. Asset Inventory

### 2.1 Already on disk (Phase 1 + 2 complete)

| File | Status | Source |
|---|---|---|
| `schemas/goal_domain.py` | Created | Ported from `app/schemas/domain.py` (git `e04c449`) |
| `schemas/goal_events.py` | Created | Ported from `app/schemas/events.py` |
| `db/collections.py` | Updated | Added `GOALS`, `EVENT_LOG` constants |
| `agents/tools/goal_db.py` | Created | Ported, imports rewritten |
| `agents/tools/subtask_db.py` | Created | Ported, imports rewritten |
| `agents/tools/feasibility_calc.py` | Created | Pure functions; no change |
| `agents/tools/progress_calc.py` | Created | Pure function; no change |

### 2.2 Not in git history — must be rewritten from architecture doc

| Original file | New location | Notes |
|---|---|---|
| `app/agents/decomposition.py` | `agents/goal/decomposition.py` | One-shot structured output; `output_schema=list[SubTask]` |
| `app/agents/weekly_memory.py` | `agents/goal/weekly_memory.py` | `SequentialAgent(memory_analyzer, memory_writer)` |
| `app/tools/intake_session_db.py` | `agents/tools/intake_session_db.py` | 5 async functions; full signatures in §4.3 |
| `app/tools/memory_agent.py` | `agents/tools/memory_agent_client.py` | Write-only httpx call; reads arrive via `GoalAgentInput.memory_context` |
| `app/runtime/session_service.py` | Not ported | Replaced by `InMemorySessionService` + `intake_sessions` collection |
| `app/prompts/*.md` (12 files) | `agents/goal/prompts/*.md` | Full specs in §3 of architecture doc |

### 2.3 Port with import rewrites only

| Original | New location | Change |
|---|---|---|
| `app/agents/root.py` | `agents/goals.py` | `build_goal_tracking_root(db, cfg)` replaces stub |
| `app/agents/intake.py` | `agents/goal/intake.py` | `build_goal_intake_agent` |
| `app/agents/validation.py` | `agents/goal/validation.py` | `build_validation_loop` (LoopAgent) |
| `app/agents/feasibility.py` | `agents/goal/feasibility.py` | `build_feasibility_workflow` (Sequential + Parallel) |
| `app/agents/progress.py` | `agents/goal/progress.py` | `build_progress_tracking_agent` |
| `app/agents/overdue.py` | `agents/goal/overdue.py` | `build_overdue_handler_agent` |
| `app/agents/daily_output.py` | `agents/goal/daily_output.py` | `build_daily_output_builder` |
| `app/api/event_routes.py` | `api/routes/events.py` | Update DB/schema imports |
| `app/tools/calendar_api.py` | `agents/tools/calendar_api.py` | No logic change |
| `app/tools/messaging.py` | `agents/tools/goal_messaging.py` | Renamed to avoid collision |

---

## 3. Final Target Layout

```
schemas/
├── goal_domain.py          # Goal, SubTask, EventLogEntry, VALID_GOAL_STATUSES,
│                           # WeeklyMemoryWrite — field names match PRD §8 exactly
├── goal_events.py          # OverdueTaskRef (start_time: datetime, NOT planned_date),
│                           # OverdueNotification, SubtaskScheduledEvent,
│                           # SubtaskCompletedEvent, EventAck
├── goal_intake.py          # IntakeSession, IntakeTurn, IntakeTurnRequest,
│                           # IntakeTurnResponse, IntakeConfirmRequest, IntakeStage
└── goals.py                # GoalsOutput, GoalSubTask — ALREADY EXISTS, DO NOT MODIFY

db/
├── collections.py          # GOALS, INTAKE_SESSIONS, WEEKLY_MEMORY_WRITES, EVENT_LOG
│                           # added to existing class Collections
└── indexes.py              # NEW: ensure_indexes(db) — called from FastAPI lifespan

agents/
├── coordinator.py          # add goal_tracking_root to sub_agents list
├── goals.py                # REPLACE stub → build_goal_tracking_root(db, cfg)
└── goal/
    ├── __init__.py
    ├── intake.py           # build_goal_intake_agent + 7 tool closures
    ├── validation.py       # build_validation_loop (LoopAgent wrapping goal_validator)
    ├── decomposition.py    # build_decomposition_agent (REWRITE — not in git history)
    ├── feasibility.py      # build_feasibility_workflow
    │                       # SequentialAgent(ParallelAgent(time,habit,load), synthesis)
    ├── progress.py         # build_progress_tracking_agent
    ├── overdue.py          # build_overdue_handler_agent
    ├── weekly_memory.py    # build_weekly_memory_writer (REWRITE — not in git history)
    ├── daily_output.py     # build_daily_output_builder
    └── prompts/            # 12 .md files (REWRITE from architecture doc §3)
        ├── root.md
        ├── intake.md
        ├── validation.md
        ├── decomposition.md
        ├── feasibility_time.md
        ├── feasibility_habit.md
        ├── feasibility_load.md
        ├── feasibility_synthesis.md
        ├── progress.md
        ├── overdue.md
        ├── daily_output.md
        └── weekly_memory.md

agents/tools/
├── goal_db.py              # DONE ✓
├── subtask_db.py           # DONE ✓
├── feasibility_calc.py     # DONE ✓
├── progress_calc.py        # DONE ✓
├── calendar_api.py         # NEW: FreeWindow, CalendarUnavailable, fetch_free_windows,
│                           # sum_free_minutes
├── intake_session_db.py    # NEW: start/resume/append/save_draft/complete
├── goal_messaging.py       # NEW: format_behind_schedule_reminder, format_overdue_prompt,
│                           # format_feasibility_proposal
└── memory_agent_client.py  # NEW: write_weekly_summary (httpx POST to Memory Agent)

api/routes/
├── events.py               # NEW: POST /v1/events/overdue|subtask-scheduled|subtask-completed
├── intake.py               # NEW: POST /v1/intake/turn, POST /v1/intake/confirm
├── goals.py                # NEW: GET /v1/goals, GET /v1/goals/{id},
│                           # POST /v1/goals/{id}/abandon, POST /v1/goals/{id}/replan
└── scheduled.py            # NEW: POST /v1/scheduled/daily-output,
                            # POST /v1/scheduled/weekly-memory

tests/
├── conftest.py             # MERGE: mongo testcontainer + StubRunner + respx fixtures
│                           # into existing conftest
├── fixtures/
│   ├── domain/
│   │   ├── factories.py    # make_goal, make_subtask, make_goal_input, make_health_output,
│   │   │                   # make_goals_output, make_overdue_event, etc.
│   │   └── personas.py     # new_user, experienced_user, infeasible_user
│   └── goal_agent/
│       ├── runner.py       # StubRunner, ToolCall, ScenarioScript
│       ├── llm_stubs.py    # ScenarioScript definitions for all 22 scenarios
│       └── reporting.py    # step() context manager + pytest terminal summary plugin
├── unit/
│   ├── test_schemas.py     # GoalSubTask field contracts, planned_date rejection
│   ├── test_feasibility_calc.py
│   └── test_progress_calc.py
└── integration/
    ├── test_intake_flows.py       # N1, N2, N3
    ├── test_state_transitions.py  # S1, S2, S3, S4
    ├── test_edge_cases.py         # E1, E2, E3, E4
    ├── test_lifecycle.py          # L1, L3
    ├── test_concurrency.py        # C1
    ├── test_state_guards.py       # X (8 parameterized cases)
    ├── test_llm_robustness.py     # G1, G2
    ├── test_boundaries.py         # B1, B2
    ├── test_timeouts.py           # T1
    ├── test_partial_failures.py   # P2
    └── test_daily_output.py       # N4
```

---

## 4. Coordinator Integration

### 4.1 Intent routing matrix

The coordinator is the only agent that sees raw user input. It classifies intent and
assembles `GoalAgentInput` before transferring. The goal agent never re-classifies intent.

| Intent | Coordinator action | Agent invoked |
|---|---|---|
| `add_goal` | Assemble `GoalAgentInput`, transfer | `goal_tracking_root` → `goal_intake_agent` (new session) |
| `add_goal_continue` | Reuse `session_id`, transfer | `goal_tracking_root` → `goal_intake_agent` (resume) |
| `check_progress` | Call `track_goals(user_id)` tool directly | No transfer — deterministic read |
| `overdue_notification` | (event endpoint, not chat) | `progress_tracking_agent` via HTTP event |
| `subtask_scheduled` | (event endpoint, not chat) | Direct DB op via `/v1/events/subtask-scheduled` |
| `subtask_completed` | (event endpoint, not chat) | Direct DB op via `/v1/events/subtask-completed` |
| `update_goal` | Assemble input, transfer | `goal_tracking_root` → `overdue_handler_agent` |
| `abandon_goal` | Assemble input, transfer | `goal_tracking_root` → `overdue_handler_agent` |
| `daily_output_push` | (Cloud Scheduler, not chat) | `daily_output_builder` via `/v1/scheduled/daily-output` |
| `weekly_memory_write` | (Cloud Scheduler, not chat) | `weekly_memory_writer` via `/v1/scheduled/weekly-memory` |

### 4.2 GoalAgentInput assembly (coordinator's job before transfer)

```python
class GoalAgentInput(BaseModel):
    user_id: str
    intent: str                    # one of the intent values above
    raw_user_message: str          # original user text, for LLM context in goal agents
    health: HealthOutput           # pre-assembled from Health & Energy Agent
    memory_context: str            # compressed behavioral history; "" if no history
    calendar_free_slots: list[dict] # available windows; [] if Calendar API failed
```

Steps the coordinator performs before `transfer_to_agent`:
1. Classify `intent` from the raw message (coordinator's LLM does this naturally via ReAct)
2. Call `analyze_health(user_id)` → get `HealthOutput`
3. Call `retrieve_relevant_memories(user_id, query=raw_user_message)` → join into `memory_context`
4. If intent ∈ `{add_goal, update_goal}`: fetch calendar free slots for next N days via Calendar API (or pass `[]` on failure)
5. Write `state["input"] = GoalAgentInput(...)` into ADK session state
6. `transfer_to_agent("goal_tracking_root")`

The goal agent reads `state["input"]` on activation and **never calls upstream agents directly**.

### 4.3 Session strategy

The original microservice used `MongoSessionService` (ADK SessionService backed by the
`intake_sessions` collection). The consolidated backend uses `InMemorySessionService`.

**Decision**: Keep `InMemorySessionService` for short-lived ADK conversation turns.
Persist intake-specific state (`stage`, `draft`, `history`) in the `intake_sessions`
MongoDB collection via `intake_session_db.py` tool functions. The `goal_intake_agent`
tool closures (`start_intake_session`, `resume_intake_session`, `append_intake_turn`,
`save_intake_draft`, `complete_intake_session`) are the persistence layer for multi-turn
intake.

This decouples the ADK session ID from the intake session ID and allows TTL expiry of
intake sessions independently (24h TTL via MongoDB index on `expires_at`).

### 4.4 Root agent intent dispatch (from `agents/goal/prompts/root.md`)

```
| state["input"].intent  | Activate                                               |
|------------------------|--------------------------------------------------------|
| "add_goal"             | goal_intake_agent (new session)                        |
| "add_goal_continue"    | goal_intake_agent (resume from intake_sessions)        |
| "overdue_notification" | progress_tracking_agent                                |
| "subtask_scheduled"    | set_goal_status("IN_PROGRESS") + update sub_task       |
| "subtask_completed"    | mark_sub_task_complete + recompute + check COMPLETED   |
| "check_progress"       | list_active_goals + return summary (no sub-agent)      |
| "update_goal"          | overdue_handler_agent                                  |
| "abandon_goal"         | overdue_handler_agent                                  |
| "daily_output_push"    | daily_output_builder                                   |
| "weekly_memory_write"  | weekly_memory_writer                                   |
```

---

## 5. ADK Agent Hierarchy

```
goal_tracking_root        (LlmAgent)  gemini-2.5-pro-preview
├── goal_intake_agent     (LlmAgent)  gemini-2.5-flash
│   ├── validation_loop   (LoopAgent, max_iterations=5)
│   │   └── goal_validator (LlmAgent)  gemini-2.5-flash
│   ├── decomposition_agent (LlmAgent)  gemini-2.5-pro-preview
│   └── feasibility_workflow (SequentialAgent)
│       ├── feasibility_parallel (ParallelAgent)
│       │   ├── time_feasibility_agent  (LlmAgent)  gemini-2.5-flash-lite
│       │   ├── habit_feasibility_agent (LlmAgent)  gemini-2.5-flash
│       │   └── load_feasibility_agent  (LlmAgent)  gemini-2.5-flash-lite
│       └── feasibility_synthesis_agent (LlmAgent)  gemini-2.5-pro-preview
├── progress_tracking_agent (LlmAgent)  gemini-2.5-flash
├── overdue_handler_agent   (LlmAgent)  gemini-2.5-flash
├── weekly_memory_writer    (SequentialAgent)
│   ├── memory_analyzer     (LlmAgent)  gemini-2.5-pro-preview
│   └── memory_writer       (LlmAgent)  gemini-2.5-flash
└── daily_output_builder    (LlmAgent)  gemini-2.5-flash
```

### Per-agent model selection rationale

| Model | Agents | Reason |
|---|---|---|
| `gemini-2.5-pro-preview` | root, decomposition, feasibility_synthesis, memory_analyzer | Complex multi-step reasoning: sub-task decomposition, scoring synthesis, behavioral distillation |
| `gemini-2.5-flash` | intake, goal_validator, habit_feasibility, progress_tracking, overdue_handler, memory_writer, daily_output_builder | Standard reasoning; latency matters |
| `gemini-2.5-flash-lite` | time_feasibility, load_feasibility | Structured output calls with deterministic math; lightweight model sufficient |

### Intake stage state machine

```
initial → validating → decomposing → feasibility → confirming
```

State is persisted to `intake_sessions` MongoDB collection after each turn (not only
in ADK session memory). The `goal_intake_agent` reads `state["intake.stage"]` each turn
to decide which branch to execute.

### Feasibility parallel execution

The three feasibility layers have no data dependency on each other:
- Layer 1 (`time_feasibility_agent`): reads `state["input"].calendar_free_slots`
- Layer 2 (`habit_feasibility_agent`): reads `state["input"].memory_context`
- Layer 3 (`load_feasibility_agent`): queries `list_active_goals` from MongoDB

`ParallelAgent` runs all three concurrently. Each writes its result to a namespaced
state key (`feasibility.time`, `feasibility.habit`, `feasibility.load`). Then
`SequentialAgent` runs `feasibility_synthesis_agent` which reads all three keys and
produces the final score + 3-option proposal.

### ADK session state keys

| Key | Type | R/W | Owner | Notes |
|---|---|---|---|---|
| `input` | `GoalAgentInput` | R | root | Set by FastAPI route before `runner.run_async` |
| `intake.session_id` | `str` | RW | intake | UUID; persists across HTTP turns |
| `intake.stage` | `str` | RW | intake | `"initial" \| "validating" \| "decomposing" \| "feasibility" \| "confirming"` |
| `intake.draft` | `dict` | RW | intake | Partial Goal fields; never written to DB until confirmed |
| `intake.history` | `list[IntakeTurn]` | RW | intake | Full conversation; injected for context each turn |
| `validation.passed` | `bool` | RW | goal_validator | LoopAgent exit condition |
| `validation.failures` | `list[str]` | RW | goal_validator | Dimensions that failed |
| `decomposition.sub_tasks` | `list[SubTask]` | W | decomposition | Awaiting user confirmation |
| `feasibility.time` | `FeasibilityLayerResult` | W | time_feasibility | Written during ParallelAgent pass |
| `feasibility.habit` | `FeasibilityLayerResult` | W | habit_feasibility | Written during ParallelAgent pass |
| `feasibility.load` | `FeasibilityLayerResult` | W | load_feasibility | Written during ParallelAgent pass |
| `feasibility.proposal` | `dict` | W | synthesis | Three-option struct; R by intake agent |
| `overdue.batch` | `list[OverdueTaskRef]` | RW | progress_tracking | Items removed as processed |
| `overdue.reminders` | `list[str]` | W | progress_tracking | Formatted reminder strings |
| `weekly.window_start` | `date` | R | memory_analyzer | Set by scheduled route |
| `weekly.analysis` | `dict` | W | memory_analyzer | R by memory_writer |
| `output.daily` | `list[GoalsOutput]` | W | daily_output_builder | Validated; no `planned_date` in GoalSubTask |

---

## 6. Invariants (Must Not Break)

These are enforced by tests. A code change that violates any of these is a regression.

### I1 — GoalSubTask never carries `planned_date`

`GoalSubTask` (the schema sent to the Schedule Agent) must not have a `planned_date`
field. The `model_validator` in `GoalSubTask` raises `ValueError` if any dict passed
to it includes `planned_date`. `planned_date` lives only on `SubTask` (domain) and is
written back by the Schedule Agent via `/v1/events/subtask-scheduled`.

This is a programming error (500), not a user error. The output validator on
`GoalsOutput` enforces it.

### I2 — `OverdueTaskRef` uses `start_time`, not `planned_date`

The event schema field is `start_time: datetime`, not `planned_date`. This was a
deliberate PRD §11 Q3 decision (planned_date is derivable from start_time). Never revert.

### I3 — Feasibility scoring weights are fixed

```python
score = 1.0
if not time_result.feasible:   score -= 0.3
if not habit_result.feasible:  score -= 0.2
if load_result.overload_flag:  score -= 0.15
if any layer degraded:         score = min(score, 0.7)
score = round(max(0.0, min(1.0, score)), 2)
```

Do not modify the weights without also updating `tests/unit/test_feasibility_calc.py`.

### I4 — Infeasibility proposals present exactly 3 options

When the feasibility score < threshold, the agent must present **exactly** 3 options:
- **A.** Extend the deadline
- **B.** Reduce the scope
- **C.** Keep the original goal — I will send daily reminders

Never 2, never 4. The `agents/goal/prompts/feasibility_synthesis.md` prompt enforces this.
Test N3 asserts `response_contains(["A.", "B.", "C."])`.

### I5 — Event idempotency via `event_log`

Every `POST /v1/events/*` handler:
1. Attempts to insert an `EventLogEntry` into `event_log` with the caller-supplied `event_id`
2. If `DuplicateKeyError` is raised (unique index on `event_id`): return `EventAck(status="already_processed", processed_count=0, warnings=[])`
3. Only on successful insert: process the event and update the entry to `status="processed"`

This guarantees at-most-once processing. Test E4 verifies this.

### I6 — Goal lifecycle state machine

Valid states: `CREATED | IN_PROGRESS | COMPLETED | PARTIALLY_COMPLETED | OVERDUE | ABANDONED`

Enforced transitions:
- `CREATED → IN_PROGRESS`: first `subtask-scheduled` event
- `IN_PROGRESS → COMPLETED`: `progress_percent == 100.0` after `subtask-completed` event
- `IN_PROGRESS → PARTIALLY_COMPLETED`: deadline reached, `0 < progress < 100`
- `IN_PROGRESS → OVERDUE`: deadline reached, `progress == 0`
- `OVERDUE → IN_PROGRESS`: user chooses replan (`POST /v1/goals/{id}/replan`)
- `ANY → ABANDONED`: only on explicit user confirmation via `POST /v1/goals/{id}/abandon`

Terminal states (`COMPLETED`, `ABANDONED`) reject replan requests. Tests X1–X8 verify all
illegal transitions are rejected with a specific error message.

### I7 — Goal Agent never reads raw user input

The goal agent reads `state["input"].raw_user_message` (which the coordinator forwarded)
but never receives raw input from a WebSocket or direct HTTP call. All activation paths go
through `GoalAgentInput`. Test scenarios verify this at the fixture level (all test inputs
are pre-assembled `GoalAgentInput` dicts).

### I8 — No polling

The Goal Agent reacts to events delivered via HTTP. It never initiates timer-based checks
or maintains a long-running polling loop. PRD §4.5 is explicit on this.

### I9 — Atomic progress recompute

`recompute_progress_percent` must use MongoDB's `find_one_and_update` with an aggregation
pipeline update (not a read-compute-write pattern) to prevent the C1 lost-update race:

```python
# Correct: aggregation pipeline update
await db[GOALS].update_one(
    {"goal_id": goal_id},
    [{"$set": {"progress_percent": {
        "$multiply": [
            {"$divide": [
                {"$size": {"$filter": {"input": "$sub_tasks",
                                       "cond": "$$this.is_completed"}}},
                {"$size": "$sub_tasks"}
            ]},
            100
        ]
    }}}]
)
```

Test C1 fires two `subtask-completed` events simultaneously via `asyncio.gather` and
asserts `progress_percent == 100.0` with no lost update.

### I10 — Intake tone: never use rejection words

The intake validation loop must never use the words `"invalid"`, `"rejected"`, or `"fail"`
when talking to the user. Only guiding questions are permitted:
- Quantifiability failure: *"What would count as completing this goal?"*
- Time-bound failure: *"When do you need this finished by?"*
- Granularity failure: *"Can you break that down slightly?"*

Test N2 asserts `response_does_not_contain(["invalid", "rejected", "fail"])`.

---

## 7. Database Collections

All collections live in the same `daypilot` MongoDB database. `db/indexes.py` contains
`async def ensure_indexes(db)` called from the FastAPI `lifespan` context manager.

### 7.1 `goals`

Sub-tasks are embedded (not a separate collection) to guarantee atomic progress updates.

```python
class SubTask(BaseModel):
    sub_task_id: str
    goal_id: str
    title: str
    estimated_minutes: int
    priority: str                    # "high" | "medium" | "low"
    deadline: date
    preferred_time_of_day: str       # "morning" | "afternoon" | "night" | "flexible"
    can_split: bool
    is_completed: bool
    completed_at: Optional[datetime]
    planned_date: Optional[date]     # Written by /v1/events/subtask-scheduled only

class Goal(BaseModel):
    goal_id: str
    user_id: str
    title: str
    goal_type: str                   # "weekly" | "daily" | "long_term"
    status: str
    created_at: datetime
    deadline: date
    progress_percent: float          # 0.0 – 100.0
    sub_tasks: list[SubTask]
    feasibility_score: float
    feasibility_note: str
    total_effort_minutes: int
    suggested_blocks_count: int
    suggested_split_ratio: list[float]
```

Indexes:
```python
[
    IndexModel([("goal_id", ASCENDING)], unique=True),
    IndexModel([("user_id", ASCENDING), ("status", ASCENDING)]),
    IndexModel([("user_id", ASCENDING), ("deadline", ASCENDING)]),
    IndexModel([("status", ASCENDING), ("deadline", ASCENDING)]),
    IndexModel([("sub_tasks.sub_task_id", ASCENDING)]),  # for overdue lookup
]
```

### 7.2 `intake_sessions`

Multi-turn intake state; TTL 24 hours.

```python
class IntakeSession(BaseModel):
    session_id: str
    user_id: str
    status: str        # "open" | "completed" | "expired"
    stage: str         # "initial" | "validating" | "decomposing" | "feasibility" | "confirming"
    draft: dict        # partial Goal fields; schema-free
    history: list[IntakeTurn]
    validation_failures: list[str]
    created_at: datetime
    last_active_at: datetime
    expires_at: datetime   # TTL target = created_at + 24h
    goal_id: Optional[str] # populated on completion
```

Indexes:
```python
[
    IndexModel([("session_id", ASCENDING)], unique=True),
    IndexModel([("user_id", ASCENDING), ("status", ASCENDING)]),
    IndexModel([("expires_at", ASCENDING)], expireAfterSeconds=0),  # TTL
]
```

### 7.3 `weekly_memory_writes`

Idempotency guard for the weekly memory write job. Unique index on `(user_id, week_start)`
converts a duplicate write to a 200 no-op.

```python
class WeeklyMemoryWrite(BaseModel):
    write_id: str
    user_id: str
    week_start: date
    week_end: date
    summary_text: str
    written_at: datetime
    status: str        # "success" | "failed"
    error: str         # empty on success
```

Indexes:
```python
[
    IndexModel([("user_id", ASCENDING), ("week_start", ASCENDING)], unique=True),
]
```

### 7.4 `event_log`

Audit trail + idempotency key store for all inbound events.

```python
class EventLogEntry(BaseModel):
    event_id: str               # caller-generated UUID; unique index
    event_type: str             # "overdue" | "subtask_scheduled" | "subtask_completed"
    goal_id: str
    sub_task_id: Optional[str]
    payload: dict               # raw request body for replay
    received_at: datetime
    processed_at: Optional[datetime]
    status: str                 # "processed" | "partial" | "failed"
    warnings: list[str]         # e.g. ["unknown_sub_task_id: t99"]
```

Indexes:
```python
[
    IndexModel([("event_id", ASCENDING)], unique=True),
    IndexModel([("goal_id", ASCENDING), ("received_at", DESCENDING)]),
    IndexModel([("event_type", ASCENDING), ("received_at", DESCENDING)]),
]
```

---

## 8. REST API Endpoints

All endpoints under `/v1`. All request/response bodies are JSON.

### 8.1 Intake routes (`api/routes/intake.py`)

| Method | Path | Request | Response | Notes |
|---|---|---|---|---|
| `POST` | `/v1/intake/turn` | `IntakeTurnRequest` | `IntakeTurnResponse` | Drives `goal_intake_agent`; session-stateful |
| `POST` | `/v1/intake/confirm` | `IntakeConfirmRequest` | `Goal` | Finalizes and writes goal to DB |

```python
class IntakeTurnRequest(BaseModel):
    user_id: str
    intent: str                   # "add_goal" | "add_goal_continue"
    raw_user_message: str
    health: HealthOutput
    memory_context: str
    calendar_free_slots: list[dict]
    session_id: Optional[str]     # None → start new session

class IntakeTurnResponse(BaseModel):
    session_id: str
    stage: str
    assistant_message: str
    goal_id: Optional[str]        # set when stage == "confirming"
    validation_failures: list[str]

class IntakeConfirmRequest(BaseModel):
    session_id: str
    user_id: str
    confirmed: bool               # False restarts the confirming stage
```

### 8.2 Event routes (`api/routes/events.py`)

| Method | Path | Request | Response |
|---|---|---|---|
| `POST` | `/v1/events/overdue` | `OverdueNotification` | `EventAck` |
| `POST` | `/v1/events/subtask-scheduled` | `SubtaskScheduledEvent` | `EventAck` |
| `POST` | `/v1/events/subtask-completed` | `SubtaskCompletedEvent` | `EventAck` |

**`/v1/events/overdue`**: writes to `event_log`, calls `progress_tracking_agent` (or direct
tool calls), recomputes progress, generates reminder strings in `EventAck.warnings`.

**`/v1/events/subtask-scheduled`**: writes to `event_log`, calls `update_sub_task` to set
`planned_date = start_time.date()`, calls `set_goal_status("IN_PROGRESS")` if goal was `CREATED`.

**`/v1/events/subtask-completed`**: writes to `event_log`, calls `mark_sub_task_complete`,
`recompute_progress_percent` (atomic), then `set_goal_status("COMPLETED")` if `progress == 100.0`.

### 8.3 Goal routes (`api/routes/goals.py`)

| Method | Path | Request | Response |
|---|---|---|---|
| `GET` | `/v1/goals` | `?user_id&status` | `list[Goal]` |
| `GET` | `/v1/goals/{goal_id}` | — | `Goal` |
| `POST` | `/v1/goals/{goal_id}/abandon` | `AbandonRequest` | `Goal` |
| `POST` | `/v1/goals/{goal_id}/replan` | `ReplanRequest` | `Goal` |

### 8.4 Scheduled routes (`api/routes/scheduled.py`)

| Method | Path | Request | Response |
|---|---|---|---|
| `POST` | `/v1/scheduled/daily-output` | `DailyOutputRequest` | `DailyOutputResponse` |
| `POST` | `/v1/scheduled/weekly-memory` | `WeeklyMemoryRequest` | `WeeklyMemoryAck` |

`/v1/scheduled/daily-output` invokes `daily_output_builder`, which strips `planned_date`
from all `GoalSubTask` objects and writes output to `event_log` with
`event_type="daily_output"` for the Schedule Agent to consume.

`/v1/scheduled/weekly-memory` invokes `weekly_memory_writer` (Sequential: `memory_analyzer`
→ `memory_writer`). Idempotent via `weekly_memory_writes` unique index.

---

## 9. Error Handling

### Interrupted intake session

If `resume_intake_session` returns `None` (TTL expired or session not found):
raise `IntakeSessionExpired` → HTTP 410 Gone with `{"error": "intake_session_expired"}`.

### Empty memory context (new user)

`habit_feasibility(memory_context="")` applies fallback overrun ratios by goal type:
- `"weekly"` (coding/problem-solving): `overrun_ratio = 0.30`
- `"long_term"` (writing/reading): `overrun_ratio = 0.10`
- `"daily"`: `overrun_ratio = 0.05`

Returns `degraded=False` (intentional fallback, not a system failure).
Sets `feasibility_note` containing `"no_memory_baseline"` for audit.

### Calendar API failure

- During intake: `calendar_free_slots == []` → `time_feasibility(free_minutes=None)` →
  returns `degraded=True` → `synthesize_feasibility` caps score at `0.7`.
- During scheduled job: `fetch_free_windows` raises `CalendarUnavailable` → same
  degraded result. Never return 5xx because of a Calendar failure.

### Unknown sub_task_id in overdue notification

- Write `EventLogEntry(status="processing")` before processing for idempotency.
- For each `OverdueTaskRef`, call `get_sub_task`. If `None`: add to `warnings`, continue.
- Known sub-tasks are still processed normally.
- Update `event_log` to `status="partial"` with collected warnings.
- Return HTTP 200 `EventAck(status="partial", ...)`. Never reject the entire batch.

### Terminal state guard

`set_goal_status` rejects illegal transitions (e.g., `ABANDONED → IN_PROGRESS`) by
raising `ValueError`. The route handler converts this to HTTP 422 with a descriptive
error message. Tests X1–X8 verify all 8 illegal cases.

---

## 10. Configuration

Add to `config.py` (Pydantic `BaseSettings`):

```python
OVERLOAD_THRESHOLD_MINUTES: int = 600      # 10 hours; load_feasibility Layer 3 threshold
INTAKE_SESSION_TTL_HOURS: int = 24         # intake_sessions expires_at offset
goal_model: str = "gemini-2.5-flash"                    # default goal agent model
goal_reasoning_model: str = "gemini-2.5-pro-preview"   # decomposition, synthesis, memory_analyzer
goal_fast_model: str = "gemini-2.5-flash-lite"          # time_feasibility, load_feasibility
calendar_service_account_json: str | None = None        # optional; degrade if absent
```

---

## 11. Implementation Phases

### Phase 1 — DB + Schemas ✅ (complete)

- `db/collections.py`: `GOALS`, `EVENT_LOG` added
- `schemas/goal_domain.py`: `Goal`, `SubTask`, `VALID_GOAL_STATUSES`, `EventLogEntry`
- `schemas/goal_events.py`: `OverdueTaskRef`, `OverdueNotification`, `SubtaskScheduledEvent`,
  `SubtaskCompletedEvent`, `EventAck`

Still needed: `schemas/goal_intake.py`, `db/indexes.py`,
`db/collections.py` — add `INTAKE_SESSIONS`, `WEEKLY_MEMORY_WRITES`.

### Phase 2 — Tool layer ✅ (complete)

- `agents/tools/goal_db.py` ✓
- `agents/tools/subtask_db.py` ✓
- `agents/tools/feasibility_calc.py` ✓
- `agents/tools/progress_calc.py` ✓

Still needed: `agents/tools/calendar_api.py`, `agents/tools/intake_session_db.py`,
`agents/tools/goal_messaging.py`, `agents/tools/memory_agent_client.py`.

### Phase 3 — Event REST routes (no ADK)

1. `api/routes/events.py` — 3 idempotent event handlers
2. `api/routes/goals.py` — `GET /v1/goals`, `abandon`, `replan`
3. Mount in `api/app.py` under `/v1` prefix

**Verify**: `POST /v1/events/subtask-scheduled` returns 200 against a real MongoDB test
container; confirms `CREATED → IN_PROGRESS` transition.

### Phase 4 — Goal agent hierarchy (ADK)

1. Create `agents/goal/` with `__init__.py`
2. Write all 12 prompt `.md` files from architecture doc §3 specifications
3. Port sub-agent builders (update imports only):
   - `validation.py`, `feasibility.py`, `progress.py`, `overdue.py`, `daily_output.py`
4. Rewrite from spec:
   - `decomposition.py` (one-shot structured output, `output_schema=list[SubTask]`)
   - `weekly_memory.py` (`SequentialAgent(memory_analyzer, memory_writer)`)
5. Replace `agents/goals.py` stub with `build_goal_tracking_root(db, cfg)`

### Phase 5 — Coordinator integration

1. Update `agents/coordinator.py`:
   - Import and instantiate `build_goal_tracking_root`
   - Add to `sub_agents=[goal_tracking_root]`
2. Update coordinator `INSTRUCTION` with routing decision matrix (§4.1)
3. Implement `GoalAgentInput` assembly logic in coordinator (§4.2)
4. Add `/v1/intake/turn` and `/v1/intake/confirm` endpoints in `api/routes/intake.py`
5. Update `agents/tools/goal_tools.py` — replace stub `track_goals` with real
   `list_active_goals` + `GoalsOutput` assembly (deterministic, no LLM)

### Phase 6 — Scheduled job routes

1. `api/routes/scheduled.py` with both endpoints
2. Mount in `api/app.py`
3. `daily_output_builder` writes `GoalsOutput` to `event_log`
4. Test locally with direct `POST` (no Cloud Scheduler wiring needed for dev)

### Phase 7 — Tests

1. Add `testcontainers[mongodb]>=4.0`, `pytest-asyncio>=0.23`, `respx>=0.21`,
   `freezegun>=1.4` to dev dependencies
2. Replace `mongomock-motor` with real `mongo:7` testcontainer in `tests/conftest.py`
3. Implement `StubRunner`, `ScenarioScript`, `step()` in `tests/fixtures/goal_agent/`
4. Implement `tests/fixtures/domain/factories.py` and `personas.py`
5. Port 3 unit test files to `tests/unit/`
6. Implement 11 integration test files (`tests/integration/test_*.py`)

---

## 12. Testing Strategy

### Infrastructure

| Component | Technology | Notes |
|---|---|---|
| MongoDB | `testcontainers[mongodb]>=4.0` — real `mongo:7` | One container per pytest session; `ensure_indexes` at session start |
| LLM | `StubRunner` | Drop-in for `google.adk.runners.Runner`; dispatches by `intent` to `ScenarioScript`; tools execute for real against test MongoDB |
| Memory Agent HTTP | `respx>=0.21` | Mock at httpx transport level |
| Calendar API | `monkeypatch` on `fetch_free_windows` | Returns fixed `list[FreeWindow]` or raises `CalendarUnavailable` |
| Time | `freezegun>=1.4` | Required for B1 (exact 100% boundary) and B2 (deadline=today) |

**Why real MongoDB (not mongomock):** The atomic `recompute_progress_percent` uses a
MongoDB aggregation pipeline update. `mongomock-motor` does not reliably support `$filter`
+ `$round` + `$cond` in `update_one`. Scenario C1 requires real document-level locking
semantics to expose the race condition. `mongomock-motor` is removed entirely.

**StubRunner pattern:**
```python
class StubRunner:
    def __init__(self, db, scripts: dict[str, ScenarioScript]):
        ...
    async def run_async(self, user_id, session_id, new_message, state) -> dict:
        intent = state["input"]["intent"]
        script = self.scripts[intent]
        for tool_call in script.tool_sequence:
            await tool_call.fn(self.db, **tool_call.kwargs)  # real DB calls
        return script.final_response  # faked LLM response
```

### 22 Integration Scenarios

| Category | Scenarios | File |
|---|---|---|
| Normal flows | N1, N2, N3 | `test_intake_flows.py` |
| Daily output | N4 | `test_daily_output.py` |
| State transitions | S1, S2, S3, S4 | `test_state_transitions.py` |
| Edge / degraded | E1, E2, E3, E4 | `test_edge_cases.py` |
| Lifecycle | L1, L3 | `test_lifecycle.py` |
| Concurrency | C1 | `test_concurrency.py` |
| State guards | X (8 parametrize) | `test_state_guards.py` |
| LLM robustness | G1, G2 | `test_llm_robustness.py` |
| Boundary values | B1, B2 | `test_boundaries.py` |
| Timeout | T1 | `test_timeouts.py` |
| Partial failure | P2 | `test_partial_failures.py` |

### Scenario reference

**N1** — Clear goal, single intake turn → `stage == "confirming"`; goal `status == "CREATED"`;
correct sub-task count; `GoalSubTask` has no `planned_date`.

**N2** — Vague goal ("study more") → validation loop → first response contains none of
`"invalid"`, `"rejected"`, `"fail"`; after second turn `validation.passed == True`.

**N3** — Infeasible goal → agent presents exactly `["A.", "B.", "C."]`; user picks A →
deadline updated; `feasibility_score` recomputed.

**N4** — 3 active goals → `POST /v1/scheduled/daily-output` → `goals_output` length == 3;
no `planned_date` in any `GoalSubTask`.

**S1** — `subtask-scheduled` event → `status: CREATED → IN_PROGRESS`; `planned_date` written.

**S2** — 3 `subtask-completed` events one by one → `progress_percent` increments accurately;
final `status == "COMPLETED"`.

**S3** — Overdue notification → `ack.status == "acknowledged"`; `warnings` contains
`"reminder:"` prefixed message.

**S4** — `POST /v1/goals/{id}/replan` with new deadline → `status == "IN_PROGRESS"`;
`deadline` updated.

**E1** — New user, `memory_context == ""` → `feasibility.habit.degraded == False`;
`feasibility_note` contains `"no_memory_baseline"`.

**E2** — `calendar_free_slots == []` → `feasibility.time.degraded == True`;
`feasibility_score <= 0.7`; HTTP 200.

**E3** — Overdue notification with unknown `sub_task_id` → `ack.status == "partial"`;
`warnings` contains `"unknown_sub_task_id: <id>"`; `event_log.status == "partial"`.

**E4** — Same `event_id` sent twice → second response `ack.status == "already_processed"`;
DB state unchanged from first processing.

**L1** — `POST /v1/goals/{id}/abandon` → `status == "ABANDONED"`; `event_log` entry written.

**L3** — Expired `session_id` → `POST /v1/intake/turn` → HTTP 410 with `"intake_session_expired"`.

**C1** — Two `subtask-completed` events via `asyncio.gather` → `progress_percent == 100.0`
(exact, no lost update); `status == "COMPLETED"`.

**X (8 cases)** — `COMPLETED` + `ABANDONED` states each reject: overdue notification (ignored),
subtask-completed (ignored), abandon request, replan request. State guards verified.

**G1** — Stub returns `GoalsOutput` with extra/missing fields → no crash; HTTP status != 500.

**G2** — Stub returns truncated JSON → no `JSONDecodeError` propagates; HTTP status != 500.

**B1** — Last sub-task completion pushes progress to exactly `100.0`; `status == "COMPLETED"` triggered.

**B2** — `deadline = date.today()` → `urgency == "high"` in daily output.

**T1** — `fetch_free_windows` raises `asyncio.TimeoutError` → `feasibility.time.degraded == True`;
HTTP 200; `feasibility_note` mentions timeout.

**P2** — `write_weekly_summary` raises `httpx.HTTPStatusError` → `weekly_memory_writes.status == "failed"`;
goals data intact; HTTP 200 with non-empty `errors`.

### Test naming and markers

```python
@pytest.mark.scenario("N1")
@pytest.mark.category("normal")
async def test_N1_clear_quantifiable_goal_single_turn(async_client, test_db):
    ...
```

Register markers in `pyproject.toml`:
```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
markers = [
    "scenario(id): marks test with a scenario ID (e.g. N1, C1, X)",
    "category(name): marks test category",
]
```

---

## 13. Out of Scope for This Branch

- Cloud Run deployment, Cloud Scheduler wiring, GCP service account configuration
- LLM eval suite (`tests/evals/*.evalset.json`) — ADK evalset format; deferred to post-MVP
- Multi-agent E2E tests (Coordinator → Goal → Schedule full chain)
- Performance / load testing
- Real Google Calendar API integration — degraded mode (`calendar_free_slots == []`) is
  the intended handling until credentials are wired
- WebSocket / SSE push for user notifications — reminder text surfaces via
  `EventAck.warnings["reminder:..."]`; the push mechanism belongs to Coordinator + frontend

---

## 14. Verification

### Unit tests

```bash
pytest tests/unit/test_schemas.py -v
pytest tests/unit/test_feasibility_calc.py -v
pytest tests/unit/test_progress_calc.py -v
```

### Integration tests (38 cases: 22 scenarios + 8 parameterized X cases + 8 xfail boundary)

```bash
pytest tests/integration/ -v -s
# Expected: 38 passed, 0 failed

# Run by category
pytest tests/integration/ -m "category('concurrency')" -v -s
pytest tests/integration/ -m "scenario('C1')" -v -s
```

### Manual smoke (against `uvicorn main:app --reload`)

```bash
# Start new goal intake
curl -X POST localhost:8000/v1/intake/turn \
  -H "Content-Type: application/json" \
  -d '{"user_id":"u1","intent":"add_goal","raw_user_message":"study more","health":{"energy_score":0.7,"focus_windows":[],"cognitive_load":0.3},"memory_context":"","calendar_free_slots":[]}'
# → stage == "validating"

# Clarify goal
curl -X POST localhost:8000/v1/intake/turn \
  -H "Content-Type: application/json" \
  -d '{"user_id":"u1","intent":"add_goal_continue","raw_user_message":"finish 3 textbook chapters by Friday","session_id":"<id from above>",...}'
# → stage == "confirming"

# Confirm
curl -X POST localhost:8000/v1/intake/confirm \
  -d '{"session_id":"<id>","user_id":"u1","confirmed":true}'
# → Goal with status="CREATED"

# Schedule Agent sends event
curl -X POST localhost:8000/v1/events/subtask-scheduled \
  -d '{"event_id":"e1","sub_task_id":"t1","goal_id":"<id>","start_time":"2026-06-02T09:00:00"}'
# → EventAck(status="acknowledged"); goal status → "IN_PROGRESS"

# Duplicate event
curl -X POST localhost:8000/v1/events/subtask-scheduled \
  -d '{"event_id":"e1","sub_task_id":"t1","goal_id":"<id>","start_time":"2026-06-02T09:00:00"}'
# → EventAck(status="already_processed")

# Daily output
curl -X POST localhost:8000/v1/scheduled/daily-output \
  -d '{"user_id":"u1"}'
# → DailyOutputResponse; verify no "planned_date" in any GoalSubTask
```
