# Goal Tracking Agent — Implementation Architecture

**Project:** DayPilot  
**Service:** `goal-tracking-agent`  
**Owner:** Astrid  
**Version:** 0.2  
**Date:** 2026-05-27  
**Stack:** Google Cloud Agent Builder · FastAPI · Python 3.12 · MongoDB Atlas · Google Cloud Run  
**LLM:** gemini-2.5-pro-preview (complex reasoning) · gemini-2.5-flash (fast agents) · gemini-2.5-flash-lite (lightweight tools)

---

## 1. ADK Agent Type Mapping

### 1.1 Agent Hierarchy

```text
goal_tracking_root          (LlmAgent)
├── goal_intake_agent       (LlmAgent)
│   ├── validation_loop     (LoopAgent)
│   │   └── goal_validator  (LlmAgent)
│   ├── decomposition_agent (LlmAgent)
│   └── feasibility_workflow          (SequentialAgent)
│       ├── feasibility_parallel      (ParallelAgent)
│       │   ├── time_feasibility_agent   (LlmAgent)
│       │   ├── habit_feasibility_agent  (LlmAgent)
│       │   └── load_feasibility_agent   (LlmAgent)
│       └── feasibility_synthesis_agent (LlmAgent)
├── progress_tracking_agent (LlmAgent)
├── overdue_handler_agent   (LlmAgent)
├── weekly_memory_writer    (SequentialAgent)
│   ├── memory_analyzer     (LlmAgent)
│   └── memory_writer       (LlmAgent)
└── daily_output_builder    (LlmAgent)
```

### 1.2 Per-Module Justification

| PRD § | Module | ADK Agent Type | Justification |
|---|---|---|---|
| 4.1 | **Goal Intake Mode** | `LlmAgent` (`goal_intake_agent`) | Owns the multi-turn conversation window. Each HTTP call is one ADK turn; state persists across calls via the custom `MongoSessionService`. Routes internally by reading `state["intake.stage"]`. Holds tools for goal CRUD and session persistence. |
| 4.2 | **Goal Validation** | `LoopAgent` (`validation_loop`) wrapping `LlmAgent` (`goal_validator`) | Validation is an intra-turn refinement loop: the `goal_validator` checks all three dimensions (quantifiable, time-bound, appropriate granularity) against `state["intake.draft"]`. If any fail it writes the missing dimensions to `state["validation.failures"]` and immediately loops. Loop exits when `state["validation.passed"] == True` or when `max_iterations=5` is reached and the agent returns the next clarifying question to the user. No user I/O occurs mid-loop; the loop operates on accumulated draft state. |
| 4.3 | **Sub-task Decomposition** | `LlmAgent` (`decomposition_agent`) | One-shot structured-output call. Gemini is instructed to return `list[SubTask]` as a JSON array. A single pass is sufficient because the goal is fully validated before this agent activates. |
| 4.4 | **Feasibility Check** | `SequentialAgent` (`feasibility_workflow`) of [ `ParallelAgent` (`feasibility_parallel`), `LlmAgent` (`feasibility_synthesis_agent`) ] | Layers 1 (Calendar), 2 (Memory), and 3 (internal DB) read from three independent sources with no data dependency between them, making `ParallelAgent` the correct choice. Each layer agent writes its result to a namespaced state key (`feasibility.time`, `feasibility.habit`, `feasibility.load`). The `feasibility_synthesis_agent` runs after all three complete (enforced by `SequentialAgent`) and reads all three keys to compose the final score and proposal options. |
| 4.5 | **Progress Tracking & Behind-Schedule** | `LlmAgent` (`progress_tracking_agent`) | Purely event-driven; no polling. Invoked by `POST /v1/events/overdue`. Uses tools to update `progress_percent`, recalculate feasibility, and compose the reminder message. |
| 4.6 | **Overdue & Abandonment** | `LlmAgent` (`overdue_handler_agent`) | Conversational decision tree (replan vs. abandon). Executes the user's choice via tools (`set_goal_status`, `update_goal_deadline`), then signals the root to return to normal conversation. |
| 4.7a | **Memory Read** | Pre-loaded state key `state["input"].memory_context` consumed by `habit_feasibility_agent` | Memory context is assembled by the Coordinator from the Memory Agent and arrives as a compressed string in `GoalAgentInput.memory_context`. No HTTP call to the Memory Agent during live agent operation. `memory_analyzer` reads from MongoDB directly for the weekly write job, which runs outside of a Coordinator-initiated session. |
| 4.7b | **Memory Weekly Write** | `SequentialAgent` (`weekly_memory_writer`) of [ `LlmAgent` (`memory_analyzer`), `LlmAgent` (`memory_writer`) ] | Analysis must complete before the compressed summary is written; sequential ordering is semantically required. `memory_analyzer` reads the past 7 days from MongoDB and writes a structured analysis object to `state["weekly.analysis"]`. `memory_writer` reads that state and calls `write_weekly_summary`. Triggered by Cloud Scheduler via `POST /v1/scheduled/weekly-memory`. |
| §5 | **Daily GoalsOutput Push** | `LlmAgent` (`daily_output_builder`) | Assembles one `GoalsOutput` per active goal for all users (or a specific `user_id` if provided). Triggered by Cloud Scheduler via `POST /v1/scheduled/daily-output`. The output is persisted to the `event_log` collection for the Schedule Planning Agent to consume. |

**Resolved Design Decisions (PRD §11):**

| # | Question | Resolution |
|---|---|---|
| Q1 | Intent routing ownership | Coordinator Agent (ReAct pattern) — the only agent with raw user input access. Goal Agent receives structured `GoalAgentInput`; never sees raw chat. |
| Q2 | Health data pull mechanism | Via Coordinator — `HealthOutput` arrives in `GoalAgentInput.health`, consistent with how Schedule Agent receives health data. No direct Health Agent calls anywhere in this service. |
| Q3 | Overdue notification format | `sub_task_id` + `goal_id` must be embedded in Schedule Agent's `task_id` or `notes` field at scheduling time. `planned_date` dropped from overdue notification; `start_time: datetime` used instead (derivable from Schedule Agent's output). |
| Q4 | Shared polling utility | Not needed — both Goal Agent and Real-time Agent are purely event-driven (request-response). No continuous polling anywhere in the system. |
| Q5 | Weighted sub-task scoring | Deferred to v2. V1 uses equal weighting: `progress = checked / total × 100`. No impact on Schedule Agent interface; it consumes `priority` string only. |

---

## 2. Project Directory Structure

```text
Goal_Tracking_Agent/
├── pyproject.toml                  # uv/Poetry project; deps: google-adk, fastapi, uvicorn, motor, pydantic>=2, google-auth, httpx
├── Dockerfile                      # Cloud Run image: python:3.12-slim, uvicorn on $PORT, non-root user
├── .dockerignore                   # Excludes .venv, __pycache__, tests/, .env
├── cloudbuild.yaml                 # Cloud Build pipeline: test → docker build → push → gcloud run deploy
├── .env.example                    # Documents required env vars without secrets
├── README.md
├── docs/
│   ├── prd.md
│   └── architecture.md             # This document
├── app/
│   ├── __init__.py
│   ├── main.py                     # FastAPI app factory; lifespan opens Motor client + calls ensure_indexes(); mounts all routers
│   ├── config.py                   # Pydantic BaseSettings; reads MONGO_URI, GEMINI_API_KEY, GCP_PROJECT, MEMORY_AGENT_URL, CALENDAR_SERVICE_ACCOUNT_JSON, OVERLOAD_THRESHOLD_MINUTES
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── root.py                 # goal_tracking_root LlmAgent; sub_agents list; transfers to child by intent
│   │   ├── intake.py               # goal_intake_agent LlmAgent; stage-routing logic; owns intake.* state keys
│   │   ├── validation.py           # validation_loop LoopAgent + goal_validator LlmAgent; exit condition on validation.passed
│   │   ├── decomposition.py        # decomposition_agent LlmAgent; output_schema=list[SubTask]
│   │   ├── feasibility.py          # feasibility_workflow SequentialAgent + feasibility_parallel ParallelAgent + three layer agents + synthesis agent
│   │   ├── progress.py             # progress_tracking_agent LlmAgent; processes overdue notification events
│   │   ├── overdue.py              # overdue_handler_agent LlmAgent; handles replan and abandon user decisions
│   │   ├── weekly_memory.py        # weekly_memory_writer SequentialAgent + memory_analyzer + memory_writer LlmAgents
│   │   └── daily_output.py         # daily_output_builder LlmAgent; assembles GoalsOutput list for Schedule Agent
│   ├── prompts/
│   │   ├── root.md                 # Root agent system prompt (full text in §3 of this document)
│   │   ├── intake.md               # Intake agent: stage-aware Q&A instructions and tone guidelines
│   │   ├── validation.md           # Validator: dimension extraction rules and loop-exit conditions
│   │   ├── decomposition.md        # Decomposer: sub-task generation rules per goal type
│   │   ├── feasibility_time.md     # Time layer: calendar math instructions
│   │   ├── feasibility_habit.md    # Habit layer: memory pattern reading + fallback LLM estimation
│   │   ├── feasibility_load.md     # Load layer: active goals aggregation + overload threshold
│   │   ├── feasibility_synthesis.md # Synthesis: composing score + 3-option proposal
│   │   ├── progress.md             # Progress: behind-schedule reminder format
│   │   ├── overdue.md              # Overdue: replan vs. abandon conversational flow
│   │   ├── weekly_memory.md        # Memory writer: distillation and compression format
│   │   └── daily_output.md         # Output builder: GoalsOutput assembly per active goal
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── goal_db.py              # Async CRUD on goals collection (create, read, update, list, set_status)
│   │   ├── subtask_db.py           # Async CRUD on sub_tasks embedded array (add, get, complete, bulk_set)
│   │   ├── intake_session_db.py    # Async read/write for intake_sessions collection; used by MongoSessionService
│   │   ├── calendar_api.py         # Google Calendar free/busy API reader; used by scheduled jobs only — intake-time feasibility reads from GoalAgentInput.calendar_free_slots
│   │   ├── memory_agent.py         # HTTP client for Memory Agent write-only; reads arrive pre-assembled in GoalAgentInput.memory_context from Coordinator
│   │   ├── feasibility_calc.py     # Pure sync functions: time_feasibility, load_feasibility, synthesize_feasibility
│   │   ├── progress_calc.py        # Pure sync function: compute_progress_percent
│   │   └── messaging.py            # Pure sync helpers: format reminder, overdue prompt, feasibility proposal strings
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── domain.py               # Goal, SubTask — field names exactly match PRD §8
│   │   ├── output.py               # GoalSubTask (no planned_date), GoalsOutput — field names exactly match PRD §5
│   │   ├── input.py                # GoalAgentInput, HealthOutput — field names exactly match PRD §6; carries health, memory_context, calendar_free_slots from Coordinator
│   │   ├── events.py               # OverdueNotification (start_time), SubtaskScheduledEvent (start_time), SubtaskCompletedEvent — field names match PRD §4.5/§7 formats
│   │   └── intake.py               # IntakeSession, IntakeTurn, IntakeTurnRequest, IntakeTurnResponse, IntakeConfirmRequest
│   ├── db/
│   │   ├── __init__.py
│   │   ├── client.py               # Motor AsyncIOMotorClient singleton; exposed via FastAPI Depends
│   │   ├── collections.py          # String constants: GOALS, INTAKE_SESSIONS, WEEKLY_MEMORY_WRITES, EVENT_LOG
│   │   └── indexes.py              # ensure_indexes(db): creates all IndexModel entries listed in §6
│   ├── api/
│   │   ├── __init__.py
│   │   ├── deps.py                 # FastAPI Depends factories: get_db, get_runner, get_session_service
│   │   ├── intake_routes.py        # POST /v1/intake/turn, POST /v1/intake/confirm
│   │   ├── event_routes.py         # POST /v1/events/overdue, /subtask-scheduled, /subtask-completed
│   │   ├── goal_routes.py          # GET /v1/goals, GET /v1/goals/{goal_id}, POST /v1/goals/{goal_id}/abandon, POST /v1/goals/{goal_id}/replan
│   │   ├── scheduled_routes.py     # POST /v1/scheduled/daily-output, POST /v1/scheduled/weekly-memory
│   │   └── health_routes.py        # GET /healthz, GET /readyz
│   └── runtime/
│       ├── __init__.py
│       ├── adk_runner.py           # Builds google.adk.runners.Runner with MongoSessionService; one Runner per FastAPI lifespan
│       ├── session_service.py      # Custom ADK SessionService backed by intake_sessions collection; supports resume by session_id
│       └── errors.py               # Domain exceptions (CalendarUnavailable, GoalNotFound, IntakeSessionExpired) + FastAPI exception handlers
└── tests/
    ├── __init__.py
    ├── conftest.py                 # pytest fixtures: Motor test client, mock Memory Agent, mock Calendar API
    ├── unit/
    │   ├── test_feasibility_calc.py
    │   ├── test_progress_calc.py
    │   └── test_schemas.py         # Asserts GoalSubTask has no planned_date; field names match PRD §5 and §7 exactly
    ├── integration/
    │   ├── test_intake_flow.py     # Full multi-turn intake via httpx TestClient
    │   ├── test_overdue_flow.py    # POST /v1/events/overdue → DB state + response
    │   └── test_daily_output.py    # POST /v1/scheduled/daily-output → GoalsOutput list
    └── evals/
        ├── intake_quantifiable.evalset.json
        ├── intake_vague_to_valid.evalset.json
        ├── feasibility_infeasible.evalset.json
        ├── overdue_known_subtask.evalset.json
        ├── overdue_unknown_subtask.evalset.json
        ├── weekly_memory_write.evalset.json
        └── daily_output_no_planned_date.evalset.json
```

---

## 3. Root `LlmAgent` System Prompt

```markdown
# Identity

You are the Goal Tracking Agent, code-named Astrid, operating within the DayPilot multi-agent scheduling system. You manage the complete lifecycle of user goals: intake, validation, sub-task decomposition, feasibility assessment, progress tracking, and behavioral memory.

# Role Boundary

You are an **advisor, not a decision-maker**. You surface insights, warnings, and proposals. The user retains full control over every final decision. When the user makes an explicit choice — even one you assessed as infeasible — you execute it without further argument.

You do **not** schedule specific calendar slots or resolve time conflicts between tasks. That responsibility belongs to the Schedule Planning Agent. When a user asks "when can I do this?", respond with urgency and effort estimates only, and note that their daily schedule is managed by the Schedule Planning Agent.

# Activation

The Coordinator Agent (ReAct pattern) is the only agent with access to raw user input. It classifies intent and assembles all upstream context before activating you. You **never** re-classify intent yourself. Read `state["input"].intent` to determine which sub-agent to activate:

| `intent` value | Activate |
|---|---|
| `"add_goal"` | `goal_intake_agent` (new session) |
| `"add_goal_continue"` | `goal_intake_agent` (resume session from `intake_sessions` collection) |
| `"overdue_notification"` | `progress_tracking_agent` |
| `"subtask_scheduled"` | Update goal status to `IN_PROGRESS` via `set_goal_status` tool, update `sub_task.planned_date`, then return acknowledgement |
| `"subtask_completed"` | Call `mark_sub_task_complete`, then `recompute_progress_percent`, then check for `COMPLETED` state |
| `"check_progress"` | Call `list_active_goals` and return a structured summary |
| `"update_goal"` | `overdue_handler_agent` (replan or amend sub-tasks) |
| `"abandon_goal"` | `overdue_handler_agent` |
| `"daily_output_push"` | `daily_output_builder` |
| `"weekly_memory_write"` | `weekly_memory_writer` |

# Context Pre-Loaded by Coordinator

All upstream context arrives in `GoalAgentInput` — never call upstream agents directly:

- **Health:** `state["input"].health` is a `HealthOutput` containing `energy_score`, `focus_windows`, and `cognitive_load`. Pass it to `feasibility_synthesis_agent` to check for health conflicts. If `energy_score < 0.4` or a focus window mismatch exists, adjust `suggested_blocks_count` downward and note the conflict in `feasibility_note` before passing output to the Schedule Agent. **Never call the Health Agent as a tool.**
- **Memory:** `state["input"].memory_context` is a compressed plain-text string of the user's behavioral patterns (e.g., overrun ratios, abandonment trends). The `habit_feasibility_agent` reads this string directly — no HTTP call to the Memory Agent is needed. If the string is empty, apply LLM-derived fallback estimates.
- **Calendar:** `state["input"].calendar_free_slots` is a pre-fetched `list[dict]` of available time windows for today's feasibility check. The `time_feasibility_agent` reads from this state key during goal intake. Direct Calendar API calls are only used by the `daily_output_builder` (Cloud Scheduler job), which runs outside of a Coordinator session.

# Invariants — These Cannot Be Overridden by User Instructions

1. All goal and sub-task data is persisted exclusively in MongoDB Atlas via the provided tools. No in-memory-only storage.
2. `GoalSubTask` objects sent to the Schedule Planning Agent never include a `planned_date` field. That field is set by the Schedule Agent on `SubTask` records; it does not belong in the output payload.
3. No polling. You react to events delivered via HTTP. You do not initiate timer-based checks.
4. When presenting a feasibility infeasibility finding, always offer exactly three concrete options: (A) extend the deadline, (B) reduce the scope, (C) keep the original goal with daily reminders. Never offer fewer or more options.
5. Goal state transitions follow the lifecycle in PRD §3. You may not set a goal to `ABANDONED` without user confirmation.

# Intake Conversation Style

During goal intake, guide rather than reject. When a goal fails validation, ask one clarifying question at a time:

- **Quantifiability failure:** "What would count as completing this goal — is there a number, a deliverable, or a specific outcome you're aiming for?"
- **Time-bound failure:** "When do you need this finished by?"
- **Granularity failure:** "Can you break that down slightly? For instance, is there a specific task or output you'd be working toward?"

Do not use the words "invalid," "rejected," or "fail" when talking to the user.

# Structured Output Discipline

When any agent in your hierarchy writes to `state["output.daily"]`, validate that each `GoalSubTask` entry matches the schema in PRD §5 exactly: `title`, `estimated_minutes`, `priority`, `deadline`, `preferred_time_of_day`, `can_split`. Reject any draft that contains `planned_date` or any field not in this list.

# Tone

- Match the user's register: casual if they write casually, precise if they write precisely.
- Default to short responses during structured workflows (intake, feasibility proposal).
- Use bullet points for option lists; use prose for explanations.
- Never fabricate goal data. If a `goal_id` is not found in the database, say so and offer to list active goals.
```

---

## 4. Tool Function Signatures

### 4.1 `app/tools/goal_db.py`

```python
from datetime import date, datetime
from typing import Optional
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.schemas.domain import Goal, SubTask


async def create_goal(db: AsyncIOMotorDatabase, goal: Goal) -> Goal:
    """
    Insert a new Goal document into the goals collection.

    Sets created_at to utcnow() if not provided. Returns the inserted Goal
    with any server-side defaults applied. Raises DuplicateKeyError if
    goal_id already exists.
    """
    ...


async def get_goal(db: AsyncIOMotorDatabase, goal_id: str) -> Optional[Goal]:
    """
    Fetch a single Goal by goal_id.

    Returns None if the goal_id does not exist. Does not raise; callers
    check for None and raise GoalNotFound if appropriate.
    """
    ...


async def update_goal(
    db: AsyncIOMotorDatabase,
    goal_id: str,
    updates: dict,
) -> Optional[Goal]:
    """
    Apply a partial update to a Goal document using $set.

    `updates` must contain only valid Goal field names. Returns the updated
    Goal, or None if goal_id not found. Does not validate field names;
    callers are responsible for passing clean dicts derived from Pydantic
    model_dump(exclude_unset=True).
    """
    ...


async def list_active_goals(
    db: AsyncIOMotorDatabase,
    user_id: str,
    statuses: list[str] = ("CREATED", "IN_PROGRESS", "OVERDUE"),
) -> list[Goal]:
    """
    Return all goals for user_id whose status is in `statuses`.

    Results are sorted by deadline ascending. An empty list is valid and
    does not raise.
    """
    ...


async def set_goal_status(
    db: AsyncIOMotorDatabase,
    goal_id: str,
    new_status: str,
    updated_deadline: Optional[date] = None,
) -> Optional[Goal]:
    """
    Transition a goal to `new_status`.

    If `updated_deadline` is provided, updates the deadline field atomically
    in the same operation (used by replan flow). Validates that `new_status`
    is one of the legal lifecycle states before writing. Returns updated Goal.
    """
    ...


async def recompute_progress_percent(
    db: AsyncIOMotorDatabase,
    goal_id: str,
) -> float:
    """
    Recalculate and persist progress_percent for the given goal.

    Reads the goal's embedded sub_tasks, applies:
        progress_percent = (completed_count / total_count) * 100
    Writes the result back with $set, then returns the new value.
    Raises GoalNotFound if goal_id does not exist.
    """
    ...
```

### 4.2 `app/tools/subtask_db.py`

```python
from datetime import date, datetime
from typing import Optional
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.schemas.domain import SubTask


async def add_sub_task(
    db: AsyncIOMotorDatabase,
    goal_id: str,
    sub_task: SubTask,
) -> SubTask:
    """
    Push a new SubTask into the sub_tasks array of the given goal.

    Uses MongoDB $push operator for atomic append. sub_task.goal_id must
    match goal_id. Raises GoalNotFound if goal_id does not exist.
    """
    ...


async def get_sub_task(
    db: AsyncIOMotorDatabase,
    goal_id: str,
    sub_task_id: str,
) -> Optional[SubTask]:
    """
    Return the SubTask matching sub_task_id within the given goal's
    sub_tasks array.

    Returns None if either goal_id or sub_task_id is not found. Callers
    check for None when processing overdue notifications that may reference
    unknown sub_task_ids.
    """
    ...


async def update_sub_task(
    db: AsyncIOMotorDatabase,
    goal_id: str,
    sub_task_id: str,
    updates: dict,
) -> Optional[SubTask]:
    """
    Apply a partial update to a single embedded SubTask using the
    MongoDB positional $ operator.

    `updates` must contain only valid SubTask field names. Returns the
    updated SubTask document, or None if not found.
    """
    ...


async def mark_sub_task_complete(
    db: AsyncIOMotorDatabase,
    goal_id: str,
    sub_task_id: str,
    completed_at: datetime,
) -> Optional[SubTask]:
    """
    Set is_completed=True and completed_at on the given sub_task.

    Atomically updates the embedded document. Returns the updated SubTask,
    or None if sub_task_id is unknown (caller logs a warning but does not
    raise so batch processing continues).
    """
    ...


async def bulk_set_sub_tasks(
    db: AsyncIOMotorDatabase,
    goal_id: str,
    sub_tasks: list[SubTask],
) -> Goal:
    """
    Replace the entire sub_tasks array for a goal in one atomic $set.

    Used by decomposition_agent after the user confirms the generated
    sub-task list. Returns the updated Goal document.
    """
    ...
```

### 4.3 `app/tools/intake_session_db.py`

```python
from datetime import datetime, timedelta
from typing import Optional
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.schemas.intake import IntakeSession, IntakeTurn


async def start_intake_session(
    db: AsyncIOMotorDatabase,
    user_id: str,
) -> IntakeSession:
    """
    Create a new IntakeSession document with status="open", stage="initial",
    and expires_at = utcnow() + 24 hours.

    Returns the created session. The session_id is a UUID4 string generated
    by this function.
    """
    ...


async def resume_intake_session(
    db: AsyncIOMotorDatabase,
    session_id: str,
) -> Optional[IntakeSession]:
    """
    Fetch an open IntakeSession by session_id.

    Returns None if the session does not exist, has status != "open", or
    has passed its expires_at. Callers raise IntakeSessionExpired on None.
    """
    ...


async def append_intake_turn(
    db: AsyncIOMotorDatabase,
    session_id: str,
    turn: IntakeTurn,
) -> None:
    """
    Append one IntakeTurn to the session's history array and update
    last_active_at to utcnow().

    Does not update expires_at; TTL is fixed at creation time.
    """
    ...


async def save_intake_draft(
    db: AsyncIOMotorDatabase,
    session_id: str,
    draft: dict,
    stage: str,
) -> None:
    """
    Persist the current partial goal draft and intake stage to the session.

    `draft` is a dict of validated Goal fields collected so far.
    `stage` is one of: "initial", "validating", "decomposing",
    "feasibility", "confirming".
    """
    ...


async def complete_intake_session(
    db: AsyncIOMotorDatabase,
    session_id: str,
    goal_id: str,
) -> None:
    """
    Mark the session as status="completed" and record the resulting goal_id.

    Called after the goal has been written to the goals collection and the
    user has confirmed the sub-task list.
    """
    ...
```

### 4.4 `app/tools/calendar_api.py`

```python
from datetime import date, datetime
from dataclasses import dataclass
from google.oauth2 import service_account
from googleapiclient.discovery import Resource


@dataclass
class FreeWindow:
    start: datetime
    end: datetime
    duration_minutes: int


class CalendarUnavailable(Exception):
    """Raised when the Google Calendar API is unreachable or returns an error."""


async def fetch_free_windows(
    user_id: str,
    start: date,
    end: date,
    calendar_client: Resource,
) -> list[FreeWindow]:
    """
    Query Google Calendar free/busy API for the user's available time
    between `start` and `end` (inclusive).

    **When this is called:** Only by the `daily_output_builder` (Cloud
    Scheduler job) and the `time_feasibility_agent` when running in a
    scheduled context. During goal intake, the Coordinator pre-fetches
    available slots and delivers them in `GoalAgentInput.calendar_free_slots`;
    the `time_feasibility_agent` reads from that state key instead.

    Returns a list of FreeWindow objects representing contiguous blocks
    with no existing events. Raises CalendarUnavailable if the API call
    fails, times out, or returns an HTTP error; callers must handle
    degraded feasibility in that case.

    `calendar_client` is an authenticated Resource injected via FastAPI
    Depends; it uses a service account with domain-wide delegation.
    """
    ...


def sum_free_minutes(windows: list[FreeWindow]) -> int:
    """
    Sum total available minutes across all FreeWindow objects.

    Pure function; used by time_feasibility Layer 1 calculation.
    """
    return sum(w.duration_minutes for w in windows)
```

### 4.5 `app/tools/memory_agent.py`

Memory reads are no longer a direct tool call. The Coordinator assembles behavioral history from the Memory Agent and passes it to the Goal Agent as `GoalAgentInput.memory_context: str`. This module is **write-only** from the Goal Agent's perspective.

```python
import httpx


async def write_weekly_summary(
    user_id: str,
    week_start: str,         # ISO date string, e.g., "2026-05-20"
    summary_text: str,
    memory_agent_url: str,
    http_client: httpx.AsyncClient,
) -> None:
    """
    Write a compressed weekly behavioral summary to the Memory Agent via
    HTTP POST.

    `summary_text` is a plain-text paragraph (≤500 chars) distilled by the
    memory_analyzer agent. This is the only direct Memory Agent call in this
    service; all reads arrive via GoalAgentInput.memory_context assembled by
    the Coordinator. Raises httpx.HTTPStatusError on failure; the caller logs
    the error and writes a failed status to weekly_memory_writes collection
    for audit.
    """
    ...
```

### 4.6 `app/tools/feasibility_calc.py`

```python
from dataclasses import dataclass
from typing import Optional
from app.schemas.domain import Goal


@dataclass
class FeasibilityLayerResult:
    layer: str                    # "time" | "habit" | "load"
    feasible: bool
    available_minutes: Optional[int]
    adjusted_effort_minutes: Optional[int]
    overrun_ratio: Optional[float]
    overload_flag: Optional[bool]
    degraded: bool = False        # True if a dependency (Calendar, Memory) was unavailable
    note: str = ""


def time_feasibility(
    total_effort_minutes: int,
    remaining_days: int,
    free_minutes: Optional[int],
) -> FeasibilityLayerResult:
    """
    Layer 1: Determine if available calendar time covers total effort.

    If `free_minutes` is None (Calendar API degraded), returns a result with
    feasible=True and degraded=True so synthesis can lower the score ceiling.
    """
    ...


def habit_feasibility(
    total_effort_minutes: int,
    memory_context: str,          # GoalAgentInput.memory_context; empty string if no history
    goal_type: str,
    deadline_days: int,
) -> FeasibilityLayerResult:
    """
    Layer 2: Adjust effort estimate using historical behavioral context.

    `memory_context` is the compressed string assembled by the Coordinator
    from the Memory Agent. The LLM agent parses overrun ratios and completion
    rates from this text. If `memory_context` is empty (new user or no
    history), applies LLM-derived fallback estimates by goal_type:
    - coding/problem-solving goals: overrun_ratio = 0.30
    - writing/reading goals: overrun_ratio = 0.10
    - daily tasks: overrun_ratio = 0.05
    Sets degraded=False because the fallback is intentional per PRD §4.4.
    """
    ...


def load_feasibility(
    active_goals: list[Goal],
    new_effort_minutes: int,
    overload_threshold_minutes: int,
) -> FeasibilityLayerResult:
    """
    Layer 3: Check if total active workload exceeds the overload threshold.

    Sums remaining_effort across all IN_PROGRESS goals plus new_effort_minutes.
    `overload_threshold_minutes` is read from app Config (env var
    OVERLOAD_THRESHOLD_MINUTES, default 600 = 10 hours).
    """
    ...


def synthesize_feasibility(
    time_result: FeasibilityLayerResult,
    habit_result: FeasibilityLayerResult,
    load_result: FeasibilityLayerResult,
) -> tuple[float, str]:
    """
    Combine all three layer results into a single feasibility_score (0.0–1.0)
    and a human-readable feasibility_note.

    Scoring logic:
    - Start at 1.0
    - Subtract 0.3 if time_result.feasible is False
    - Subtract 0.2 if habit_result.feasible is False
    - Subtract 0.15 if load_result.overload_flag is True
    - Cap at 0.7 if any layer has degraded=True (incomplete data)

    Returns (score, note). Note is empty string when score >= 0.7 and no
    layer is degraded.
    """
    ...
```

### 4.7 `app/tools/progress_calc.py`

```python
from app.schemas.domain import SubTask


def compute_progress_percent(sub_tasks: list[SubTask]) -> float:
    """
    Calculate goal completion percentage based purely on sub-task completion.

    Formula: (completed_count / total_count) * 100
    Returns 0.0 if sub_tasks is empty to avoid ZeroDivisionError.
    All sub-tasks are weighted equally (v1; weighted scoring deferred to v2).
    """
    if not sub_tasks:
        return 0.0
    completed = sum(1 for t in sub_tasks if t.is_completed)
    return round((completed / len(sub_tasks)) * 100, 2)
```

### 4.8 `app/tools/messaging.py`

```python
from datetime import date


def format_behind_schedule_reminder(
    goal_title: str,
    completed_count: int,
    total_count: int,
    deadline: date,
) -> str:
    """
    Format the user-facing reminder message for a behind-schedule goal.

    Returns a plain-text string in the style:
    "You're behind on your goal '[goal_title]' — N of M sub-tasks remain
    and your deadline is [deadline]. Would you like to replan or adjust
    the goal?"
    """
    ...


def format_overdue_prompt(goal_title: str) -> str:
    """
    Format the user-facing prompt when a goal transitions to OVERDUE.

    Returns:
    "Your goal '[goal_title]' has passed its deadline. Would you like to
    replan it, or mark it as abandoned?"
    """
    ...


def format_feasibility_proposal(
    goal_title: str,
    original_effort_minutes: int,
    adjusted_effort_minutes: int,
    overrun_ratio: float,
    original_deadline: date,
    extended_deadline: date,
    reduced_scope: str,
) -> str:
    """
    Format the three-option feasibility proposal shown to the user when
    a goal is assessed as infeasible.

    Returns a multi-line string with options A (extend deadline),
    B (reduce scope), C (keep original with reminders). Includes the
    historical overrun context per PRD §4.4 example format.
    """
    ...
```

---

## 5. Session State Key Design

State is stored in the ADK `Session.state` dict, backed by `MongoSessionService`. All keys are namespaced by prefix.

| Key | Type | R/W | Lifetime | Owning Agent | Notes |
|---|---|---|---|---|---|
| `input` | `GoalAgentInput` | R | request | root | Set by FastAPI route before runner invocation; field names match PRD §6 |
| `input.user_id` | `str` | R | request | root | Used to scope all DB queries |
| `input.intent` | `str` | R | request | root | Routing key; values in §3 intent table |
| `input.raw_user_message` | `str` | R | request | root | Original user message forwarded by Coordinator for LLM context |
| `input.health` | `HealthOutput` | R | request | root | Pre-assembled by Coordinator from Health Agent; never fetched directly |
| `input.memory_context` | `str` | R | request | `habit_feasibility_agent` | Compressed behavioral history from Memory Agent via Coordinator; empty string if no history |
| `input.calendar_free_slots` | `list[dict]` | R | request | `time_feasibility_agent` | Pre-fetched available windows for today; used during intake-time feasibility only |
| `intake.session_id` | `str` | RW | intake session | `goal_intake_agent` | Persists across HTTP turns; written on session start |
| `intake.stage` | `Literal["initial","validating","decomposing","feasibility","confirming"]` | RW | intake session | `goal_intake_agent` | Controls which branch of intake runs each turn |
| `intake.draft` | `dict` | RW | intake session | `goal_intake_agent` | Partial Goal fields accumulated across turns; never written back to DB until confirmed |
| `intake.history` | `list[IntakeTurn]` | RW | intake session | `goal_intake_agent` | Full conversation history for context injection |
| `validation.passed` | `bool` | RW | request | `goal_validator` | LoopAgent exit condition; set True when all 3 dimensions satisfied |
| `validation.failures` | `list[str]` | RW | request | `goal_validator` | Which dimensions failed; used to select follow-up questions |
| `decomposition.sub_tasks` | `list[SubTask]` | W | request | `decomposition_agent` | Generated sub-tasks awaiting user confirmation; R by `goal_intake_agent` in confirming stage |
| `feasibility.time` | `FeasibilityLayerResult` | W | request | `time_feasibility_agent` | Written during ParallelAgent pass; R by synthesis |
| `feasibility.habit` | `FeasibilityLayerResult` | W | request | `habit_feasibility_agent` | Written during ParallelAgent pass; R by synthesis |
| `feasibility.load` | `FeasibilityLayerResult` | W | request | `load_feasibility_agent` | Written during ParallelAgent pass; R by synthesis |
| `feasibility.proposal` | `FeasibilityProposal` | W | request | `feasibility_synthesis_agent` | Three-option struct; R by `goal_intake_agent` to present to user |
| `overdue.batch` | `list[OverdueTaskRef]` | RW | request | `progress_tracking_agent` | Inbound from Schedule Agent; items removed as processed |
| `overdue.reminders` | `list[str]` | W | request | `progress_tracking_agent` | Formatted reminder messages to include in response |
| `weekly.window_start` | `date` | R | weekly job | `memory_analyzer` | Set by `/v1/scheduled/weekly-memory` route from request body |
| `weekly.window_end` | `date` | R | weekly job | `memory_analyzer` | Set by `/v1/scheduled/weekly-memory` route from request body |
| `weekly.analysis` | `dict` | W | weekly job | `memory_analyzer` | Structured analysis dict; R by `memory_writer` |
| `output.daily` | `list[GoalsOutput]` | W | request | `daily_output_builder` | Final payload for Schedule Agent; validated for GoalSubTask schema compliance |
| `last_error` | `str \| None` | RW | request | any | Set on caught exceptions; included in response for caller diagnostics |

---

## 6. MongoDB Collection Schemas & Indexes

### 6.1 `goals`

Sub-tasks are embedded to guarantee atomic progress updates and avoid cross-collection joins. The 16 MB document limit is not a constraint here since sub-tasks are small objects (≤50 per goal in practice).

```python
# app/schemas/domain.py — field names exactly match PRD §8
from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel


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
    planned_date: Optional[date]     # Set by Schedule Agent via /v1/events/subtask-scheduled


class Goal(BaseModel):
    goal_id: str
    user_id: str
    title: str
    goal_type: str                   # "weekly" | "daily" | "long_term"
    status: str                      # "CREATED" | "IN_PROGRESS" | "COMPLETED" | "PARTIALLY_COMPLETED" | "OVERDUE" | "ABANDONED"
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

```python
# app/db/indexes.py (goals collection)
from pymongo import ASCENDING, DESCENDING, IndexModel

GOALS_INDEXES = [
    IndexModel([("goal_id", ASCENDING)], unique=True, name="goal_id_unique"),
    IndexModel([("user_id", ASCENDING), ("status", ASCENDING)], name="user_status"),
    IndexModel([("user_id", ASCENDING), ("deadline", ASCENDING)], name="user_deadline"),
    IndexModel([("status", ASCENDING), ("deadline", ASCENDING)], name="status_deadline"),
    # Supports overdue notification lookup by sub_task_id within embedded array
    IndexModel([("sub_tasks.sub_task_id", ASCENDING)], name="subtask_id"),
]
```

### 6.2 `intake_sessions`

```python
# app/schemas/intake.py
from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class IntakeTurn(BaseModel):
    role: str          # "user" | "agent"
    content: str
    timestamp: datetime


class IntakeSession(BaseModel):
    session_id: str
    user_id: str
    status: str        # "open" | "completed" | "expired"
    stage: str         # "initial" | "validating" | "decomposing" | "feasibility" | "confirming"
    draft: dict        # Partial Goal fields; schema-free to accommodate incremental collection
    history: list[IntakeTurn]
    validation_failures: list[str]
    created_at: datetime
    last_active_at: datetime
    expires_at: datetime   # TTL index target; set to created_at + 24h
    goal_id: Optional[str] # Populated on completion
```

```python
# app/db/indexes.py (intake_sessions collection)
INTAKE_SESSIONS_INDEXES = [
    IndexModel([("session_id", ASCENDING)], unique=True, name="session_id_unique"),
    IndexModel([("user_id", ASCENDING), ("status", ASCENDING)], name="user_status"),
    IndexModel([("expires_at", ASCENDING)], expireAfterSeconds=0, name="ttl_expires"),
]
```

### 6.3 `weekly_memory_writes`

Idempotency guard: if the weekly job is re-triggered for the same `(user_id, week_start)`, the unique index causes a duplicate key error that the route handler converts to a 200 no-op with `{"status": "already_written"}`.

```python
# Embedded in app/runtime or a dedicated schema
from datetime import date, datetime
from pydantic import BaseModel


class WeeklyMemoryWrite(BaseModel):
    write_id: str
    user_id: str
    week_start: date
    week_end: date
    summary_text: str
    written_at: datetime
    status: str   # "success" | "failed"
    error: str    # Empty string on success; error detail on failure
```

```python
WEEKLY_MEMORY_INDEXES = [
    IndexModel(
        [("user_id", ASCENDING), ("week_start", ASCENDING)],
        unique=True,
        name="user_week_unique",
    ),
]
```

### 6.4 `event_log`

Stores all inbound events (overdue, subtask-scheduled, subtask-completed) for idempotency, audit, and replay. The unique `event_id` index prevents double-processing if the Schedule Agent retries delivery.

```python
from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class EventLogEntry(BaseModel):
    event_id: str          # Caller-generated UUID; unique constraint enforces idempotency
    event_type: str        # "overdue" | "subtask_scheduled" | "subtask_completed"
    goal_id: str
    sub_task_id: Optional[str]
    payload: dict          # Raw request body for replay
    received_at: datetime
    processed_at: Optional[datetime]
    status: str            # "processed" | "partial" | "failed"
    warnings: list[str]    # e.g., ["unknown_sub_task_id: t99"]
```

```python
EVENT_LOG_INDEXES = [
    IndexModel([("event_id", ASCENDING)], unique=True, name="event_id_unique"),
    IndexModel([("goal_id", ASCENDING), ("received_at", DESCENDING)], name="goal_events"),
    IndexModel([("event_type", ASCENDING), ("received_at", DESCENDING)], name="type_time"),
]
```

---

## 7. FastAPI Endpoint Definitions

All endpoints are under `/v1`. All request/response bodies are JSON. Coordinator provides a Bearer token verified by a dependency in `app/api/deps.py`.

### 7.1 Intake Routes (`app/api/intake_routes.py`)

```python
# Request / Response schemas for intake endpoints
# IntakeTurnRequest wraps GoalAgentInput (PRD §6) and adds session_id for the HTTP layer.

class IntakeTurnRequest(BaseModel):
    # GoalAgentInput fields (PRD §6) — field names match exactly
    user_id: str
    intent: str                          # "add_goal" | "add_goal_continue"
    raw_user_message: str                # Original user message forwarded by Coordinator
    health: HealthOutput                 # Pre-assembled by Coordinator from Health Agent
    memory_context: str                  # Compressed behavioral history; empty string if none
    calendar_free_slots: list[dict]      # Pre-fetched available windows for feasibility Layer 1
    # HTTP session layer (not part of GoalAgentInput)
    session_id: Optional[str]            # None to start a new session

class IntakeTurnResponse(BaseModel):
    session_id: str
    stage: str
    assistant_message: str
    goal_id: Optional[str]               # Populated only when stage transitions to "confirming"
    validation_failures: list[str]       # Non-empty when agent needs more info

class IntakeConfirmRequest(BaseModel):
    session_id: str
    user_id: str
    confirmed: bool                      # False triggers a restart of the confirming stage
```

| Method | Path | Request Body | Response | Tools / Agents Invoked |
|---|---|---|---|---|
| `POST` | `/v1/intake/turn` | `IntakeTurnRequest` | `IntakeTurnResponse` | `goal_intake_agent` → `validation_loop` → `decomposition_agent` → `feasibility_workflow` (stage-dependent) |
| `POST` | `/v1/intake/confirm` | `IntakeConfirmRequest` | `Goal` | `bulk_set_sub_tasks`, `create_goal`, `complete_intake_session`; returns the finalized `Goal` document |

### 7.2 Event Routes (`app/api/event_routes.py`)

```python
# Schemas derived from PRD §4.5 notification formats — field names match exactly.
# planned_date dropped per PRD §11 Q3; start_time used in both event types.

class OverdueTaskRef(BaseModel):
    sub_task_id: str
    goal_id: str
    start_time: datetime            # Originally scheduled start; replaces planned_date (PRD §11 Q3)

class OverdueNotification(BaseModel):
    event_id: str                   # Caller-generated UUID; idempotency key
    overdue_tasks: list[OverdueTaskRef]

class SubtaskScheduledEvent(BaseModel):
    event_id: str
    sub_task_id: str
    goal_id: str
    start_time: datetime            # Scheduled start time from Schedule Agent's output

class SubtaskCompletedEvent(BaseModel):
    event_id: str
    sub_task_id: str
    goal_id: str
    completed_at: datetime

class EventAck(BaseModel):
    status: str                     # "acknowledged" | "already_processed" | "partial"
    processed_count: int
    warnings: list[str]             # Non-empty when sub_task_ids were unknown
```

| Method | Path | Request Body | Response | Tools / Agents Invoked |
|---|---|---|---|---|
| `POST` | `/v1/events/overdue` | `OverdueNotification` | `EventAck` | `progress_tracking_agent` → `recompute_progress_percent`, `format_behind_schedule_reminder`; reminders returned in `EventAck.warnings` for Coordinator to surface to user |
| `POST` | `/v1/events/subtask-scheduled` | `SubtaskScheduledEvent` | `EventAck` | `update_sub_task` (sets `planned_date` from `start_time.date()`), `set_goal_status("IN_PROGRESS")` if goal was `CREATED` |
| `POST` | `/v1/events/subtask-completed` | `SubtaskCompletedEvent` | `EventAck` | `mark_sub_task_complete`, `recompute_progress_percent`, `set_goal_status("COMPLETED")` if progress == 100 |

### 7.3 Goal Routes (`app/api/goal_routes.py`)

```python
class ReplanRequest(BaseModel):
    new_deadline: date
    user_id: str

class AbandonRequest(BaseModel):
    user_id: str
    reason: Optional[str]
```

| Method | Path | Query / Body | Response | Tools / Agents Invoked |
|---|---|---|---|---|
| `GET` | `/v1/goals` | `?user_id&status` (query params) | `list[Goal]` | `list_active_goals` |
| `GET` | `/v1/goals/{goal_id}` | — | `Goal` | `get_goal`; 404 if not found |
| `POST` | `/v1/goals/{goal_id}/abandon` | `AbandonRequest` | `Goal` | `overdue_handler_agent` → `set_goal_status("ABANDONED")`; writes event to `event_log` |
| `POST` | `/v1/goals/{goal_id}/replan` | `ReplanRequest` | `Goal` | `overdue_handler_agent` → `set_goal_status("IN_PROGRESS", updated_deadline=new_deadline)`; writes event to `event_log` |

### 7.4 Scheduled Routes (`app/api/scheduled_routes.py`)

Both endpoints are called by Cloud Scheduler using OIDC authentication. They use `POST` so Cloud Scheduler's HTTP target works idiomatically.

```python
class DailyOutputRequest(BaseModel):
    user_id: Optional[str]          # None means process all active users

class DailyOutputResponse(BaseModel):
    processed_users: int
    goals_output: list[GoalsOutput]
    errors: list[str]

class WeeklyMemoryRequest(BaseModel):
    user_id: Optional[str]
    week_start: Optional[date]      # Defaults to most recent Monday

class WeeklyMemoryAck(BaseModel):
    processed_users: int
    skipped_users: int              # Already written this week (idempotency)
    errors: list[str]
```

| Method | Path | Request Body | Response | Tools / Agents Invoked |
|---|---|---|---|---|
| `POST` | `/v1/scheduled/daily-output` | `DailyOutputRequest` | `DailyOutputResponse` | `daily_output_builder` → `list_active_goals`, `synthesize_feasibility` per goal; output written to `event_log` with `event_type="daily_output"` |
| `POST` | `/v1/scheduled/weekly-memory` | `WeeklyMemoryRequest` | `WeeklyMemoryAck` | `weekly_memory_writer` → `memory_analyzer` → `memory_writer` → `write_weekly_summary`; idempotency via `weekly_memory_writes` unique index |

### 7.5 Health Routes (`app/api/health_routes.py`)

| Method | Path | Response | Notes |
|---|---|---|---|
| `GET` | `/healthz` | `{"ok": true}` | Liveness probe; Cloud Run restarts container if this fails |
| `GET` | `/readyz` | `{"ok": bool, "mongo": bool, "memory_agent": bool, "calendar": bool}` | Readiness probe; pings each dependency; returns 503 if any dependency is down |

---

## 8. Error Handling

### 8.1 Interrupted Intake Session

**Scenario:** The user starts a goal intake session, provides partial information, and the session becomes inactive (browser closed, app backgrounded) without reaching `stage="confirming"`.

**Handling:**
1. `IntakeSession` document persists in `intake_sessions` with `status="open"`.
2. The TTL index on `expires_at` (set to `created_at + 24h`) automatically removes the document after 24 hours of inactivity.
3. When the user returns and the Coordinator sends `intent="intake_continue"` with a `session_id`, `resume_intake_session` is called first.
4. If `resume_intake_session` returns `None` (TTL expired), the route raises `IntakeSessionExpired` which the exception handler converts to HTTP 410 Gone with body `{"error": "intake_session_expired", "message": "Your previous goal setup session has expired. Would you like to start a new one?"}`.
5. If the session is found and `status="open"`, the agent reads `stage` and `draft` from state and resumes at the correct point, injecting `history` as context.

### 8.2 Missing Memory Context (No History for User)

**Scenario:** The Coordinator provides an empty string for `GoalAgentInput.memory_context` because the Memory Agent has no behavioral history for this user (new user, or Memory Agent returned no data when the Coordinator fetched it).

**Handling:**
1. `habit_feasibility` receives `memory_context=""`.
2. The function detects the empty context and applies LLM-derived fallback overrun estimates by `goal_type`:
   - `"weekly"` (coding/problem-solving): `overrun_ratio = 0.30`
   - `"long_term"` (writing/reading): `overrun_ratio = 0.10`
   - `"daily"`: `overrun_ratio = 0.05`
3. Returns `FeasibilityLayerResult(degraded=False, note="no_memory_baseline; using LLM general estimates")`.
4. `degraded=False` because the fallback is intentional per PRD §4.4, not a system failure.
5. The `feasibility_note` on the saved `Goal` includes `"no_memory_baseline"` for future audit.

### 8.3 Calendar API Failure

**Scenario A — Intake-time feasibility (Coordinator-provided slots):** `GoalAgentInput.calendar_free_slots` is an empty list because the Coordinator could not fetch calendar data.

**Handling (Scenario A):**
1. `time_feasibility_agent` reads `state["input"].calendar_free_slots`, finds an empty list.
2. Calls `time_feasibility(total_effort_minutes, remaining_days, free_minutes=None)`.
3. Returns `FeasibilityLayerResult(degraded=True, note="calendar_slots_empty")`.
4. `synthesize_feasibility` caps `feasibility_score` at `0.7` and appends: `"Note: calendar availability could not be verified; score is capped at 0.7."`.

**Scenario B — Scheduled job:** `fetch_free_windows` raises `CalendarUnavailable` (network timeout, service account error, or Google API 5xx) during `daily_output_builder` or `time_feasibility_agent` in a Cloud Scheduler context.

**Handling (Scenario B):**
1. `time_feasibility_agent` catches `CalendarUnavailable`, calls `time_feasibility(total_effort_minutes, remaining_days, free_minutes=None)`.
2. Same degraded result as Scenario A.
3. Endpoint returns HTTP 200 with degraded feasibility. Never returns 5xx because of a Calendar failure.
4. Failure is logged at WARNING level with `user_id`, `goal_id`, and exception detail.

### 8.4 Unknown `sub_task_id` in Overdue Notification

**Scenario:** The `OverdueNotification` payload from the Schedule Agent contains a `sub_task_id` that does not exist in the embedded `sub_tasks` array of the referenced `goal_id`.

**Handling:**
1. `POST /v1/events/overdue` is received.
2. Event is written to `event_log` immediately (before processing) with `status="processing"` for idempotency.
3. For each `OverdueTaskRef`, `get_sub_task(db, goal_id, sub_task_id)` is called.
4. If it returns `None`: the `sub_task_id` is added to `warnings`; processing continues to the next item in the batch without raising an exception.
5. Known sub-tasks are still processed: `recompute_progress_percent` and reminders are generated for the recognized ones.
6. `event_log` entry is updated to `status="partial"` with `warnings=["unknown_sub_task_id: {sub_task_id}"]`.
7. Response: HTTP 200 `EventAck(status="partial", processed_count=N, warnings=["unknown_sub_task_id: {id}"])`.
8. The batch is never rejected; partial processing is always preferred over dropping the entire notification.

### 8.5 Cross-Cutting Error Handling

| Scenario | Behavior |
|---|---|
| MongoDB write failure (transient) | Raise 503 with `Retry-After: 5` header; Motor async client uses connection pooling with automatic reconnect |
| Duplicate `event_id` (idempotent retry) | `event_log` unique index raises `DuplicateKeyError`; handler returns 200 `EventAck(status="already_processed")` |
| LLM timeout in ADK runner | ADK Runner surfaces `google.adk.exceptions.AgentError`; handler returns 200 with fallback message `"I need a moment — could you try again?"` and preserves `IntakeSession` state |
| Pydantic validation failure on request body | FastAPI default 422 Unprocessable Entity with field-level error detail |
| `goal_id` not found in goal CRUD endpoints | `GoalNotFound` exception → 404 with `{"error": "goal_not_found", "goal_id": "..."}` |
| `GoalSubTask` in daily output contains `planned_date` | Schema-level validator on `GoalsOutput` raises `ValueError`; route returns 500 and alerts ops — this is a programming error, not a user error |

---

## 9. ADK Eval Test Cases

All evalsets follow the Google ADK `EvalSet` JSON schema. Each `turn` specifies `user_content`, `expected_tool_use` (for deterministic tool-call checks), and `reference` (for LLM-judge semantic checks).

### 9.1 `intake_quantifiable.evalset.json`

```json
[
  {
    "name": "intake_quantifiable_happy_path",
    "description": "Single-turn intake: clear, quantifiable, time-bound goal. Expects CREATED status and 10 sub-tasks.",
    "initial_session_state": {
      "input": {
        "user_id": "u001",
        "intent": "add_goal",
        "raw_user_message": "I want to solve 10 Leetcode medium problems by this Friday.",
        "health": {
          "energy_score": 0.75,
          "focus_windows": [
            {"start": "2026-05-28T09:00:00Z", "end": "2026-05-28T12:00:00Z"},
            {"start": "2026-05-29T09:00:00Z", "end": "2026-05-29T11:00:00Z"}
          ],
          "cognitive_load": 0.3
        },
        "memory_context": "User typically completes weekly coding goals 25% slower than estimated. Completion rate for weekly goals: 0.78.",
        "calendar_free_slots": [
          {"start": "2026-05-28T09:00:00Z", "end": "2026-05-28T12:00:00Z", "duration_minutes": 180},
          {"start": "2026-05-29T09:00:00Z", "end": "2026-05-29T11:00:00Z", "duration_minutes": 120}
        ]
      }
    },
    "turns": [
      {
        "user_content": {
          "role": "user",
          "parts": [{"text": "I want to solve 10 Leetcode medium problems by this Friday."}]
        },
        "expected_tool_use": [
          {
            "tool_name": "start_intake_session",
            "tool_input": {"user_id": "u001"}
          },
          {
            "tool_name": "create_goal",
            "tool_input": {
              "title": "Solve 10 Leetcode medium problems",
              "goal_type": "weekly",
              "status": "CREATED"
            }
          },
          {
            "tool_name": "bulk_set_sub_tasks",
            "tool_input": {}
          }
        ],
        "reference": "Great! I've set up your goal to solve 10 Leetcode medium problems by Friday. I've broken it down into 10 sub-tasks, one per problem."
      }
    ],
    "pass_criteria": {
      "final_state_checks": [
        {"key": "intake.stage", "expected": "confirming"},
        {"key": "validation.passed", "expected": true}
      ],
      "db_checks": [
        {"collection": "goals", "filter": {"user_id": "u001", "status": "CREATED"}, "expect_count": 1},
        {"collection": "goals", "filter": {"user_id": "u001"}, "field": "sub_tasks", "expect_length": 10}
      ],
      "schema_checks": [
        {"model": "GoalSubTask", "assert_field_absent": "planned_date"}
      ]
    }
  }
]
```

### 9.2 `intake_vague_to_valid.evalset.json`

```json
[
  {
    "name": "intake_vague_goal_requires_clarification",
    "description": "Multi-turn intake: vague goal triggers validation loop, agent asks clarifying questions over 2 turns until all 3 dimensions are satisfied.",
    "initial_session_state": {
      "input": {
        "user_id": "u002",
        "intent": "add_goal",
        "raw_user_message": "I want to study more.",
        "health": {"energy_score": 0.6, "focus_windows": [], "cognitive_load": 0.4},
        "memory_context": "",
        "calendar_free_slots": [
          {"start": "2026-05-28T14:00:00Z", "end": "2026-05-28T17:00:00Z", "duration_minutes": 180}
        ]
      }
    },
    "turns": [
      {
        "user_content": {
          "role": "user",
          "parts": [{"text": "I want to study more."}]
        },
        "expected_tool_use": [
          {"tool_name": "start_intake_session", "tool_input": {"user_id": "u002"}},
          {"tool_name": "save_intake_draft", "tool_input": {"stage": "validating"}}
        ],
        "reference": "What would count as completing this goal — is there a number, a deliverable, or a specific outcome you're aiming for?"
      },
      {
        "user_content": {
          "role": "user",
          "parts": [{"text": "Finish 3 chapters of my OS textbook by next Friday."}]
        },
        "expected_tool_use": [
          {"tool_name": "append_intake_turn", "tool_input": {}},
          {"tool_name": "save_intake_draft", "tool_input": {"stage": "decomposing"}}
        ],
        "reference": "Got it. I'll break that down into sub-tasks for each chapter."
      }
    ],
    "pass_criteria": {
      "final_state_checks": [
        {"key": "validation.passed", "expected": true},
        {"key": "intake.draft.title", "expected_contains": "3 chapters"},
        {"key": "intake.stage", "expected": "decomposing"}
      ],
      "response_checks": [
        {"turn": 0, "assert_response_does_not_contain": ["invalid", "rejected", "fail"]}
      ]
    }
  }
]
```

### 9.3 `feasibility_infeasible.evalset.json`

```json
[
  {
    "name": "feasibility_infeasible_three_options_proposal",
    "description": "Goal intake reaches feasibility stage; Calendar and Memory data make the goal infeasible. Agent must present exactly 3 concrete options.",
    "initial_session_state": {
      "input": {
        "user_id": "u003",
        "intent": "add_goal",
        "raw_user_message": "I want to solve 20 Leetcode hard problems in 2 days.",
        "health": {"energy_score": 0.4, "focus_windows": [], "cognitive_load": 0.7},
        "memory_context": "User typically completes Leetcode goals 40% slower than estimated. Short-deadline goals (<3 days) have 70% abandonment rate.",
        "calendar_free_slots": [
          {"start": "2026-05-28T09:00:00Z", "end": "2026-05-28T11:00:00Z", "duration_minutes": 120}
        ]
      }
    },
    "turns": [
      {
        "user_content": {
          "role": "user",
          "parts": [{"text": "I want to solve 20 Leetcode hard problems in 2 days."}]
        },
        "expected_tool_use": [
          {"tool_name": "list_active_goals", "tool_input": {"user_id": "u003"}}
        ],
        "reference": "Based on your history, similar goals typically take ~40% longer than planned. Suggested adjustments: A. Extend deadline to 4 days, B. Reduce target to 9 problems, C. Keep original goal — I will send daily reminders to help you stay on track."
      }
    ],
    "pass_criteria": {
      "final_state_checks": [
        {"key": "feasibility.proposal.option_count", "expected": 3},
        {"key": "feasibility.time.feasible", "expected": false}
      ],
      "response_checks": [
        {"turn": 0, "assert_response_contains": ["A.", "B.", "C."]},
        {"turn": 0, "assert_options_count": 3}
      ]
    }
  }
]
```

### 9.4 `overdue_known_subtask.evalset.json`

```json
[
  {
    "name": "overdue_notification_known_subtask_updates_progress",
    "description": "POST /v1/events/overdue with a valid sub_task_id. Expects progress recalculated, reminder generated, no DB inconsistency.",
    "initial_db_state": {
      "goals": [
        {
          "goal_id": "g001",
          "user_id": "u001",
          "title": "Finish assignment draft",
          "status": "IN_PROGRESS",
          "progress_percent": 60.0,
          "sub_tasks": [
            {"sub_task_id": "t1", "is_completed": true, "title": "Outline"},
            {"sub_task_id": "t2", "is_completed": false, "title": "Draft section 1"},
            {"sub_task_id": "t3", "is_completed": true, "title": "Draft section 2"},
            {"sub_task_id": "t4", "is_completed": false, "title": "Review"},
            {"sub_task_id": "t5", "is_completed": true, "title": "Submit"}
          ],
          "deadline": "2026-05-28"
        }
      ]
    },
    "turns": [
      {
        "user_content": {
          "role": "user",
          "parts": [{
            "text": "EVENT:overdue",
            "event_payload": {
              "event_id": "evt_001",
              "overdue_tasks": [
                {"sub_task_id": "t2", "goal_id": "g001", "start_time": "2026-05-27T09:00:00"}
              ]
            }
          }]
        },
        "expected_tool_use": [
          {"tool_name": "get_sub_task", "tool_input": {"goal_id": "g001", "sub_task_id": "t2"}},
          {"tool_name": "recompute_progress_percent", "tool_input": {"goal_id": "g001"}},
          {"tool_name": "format_behind_schedule_reminder", "tool_input": {}}
        ],
        "reference": "You're behind on your goal 'Finish assignment draft'"
      }
    ],
    "pass_criteria": {
      "db_checks": [
        {"collection": "goals", "filter": {"goal_id": "g001"}, "field": "progress_percent", "expected": 60.0},
        {"collection": "event_log", "filter": {"event_id": "evt_001"}, "field": "status", "expected": "processed"}
      ],
      "response_checks": [
        {"assert_status_code": 200},
        {"assert_field": "status", "expected": "acknowledged"},
        {"assert_field": "warnings", "expected_length": 0}
      ]
    }
  }
]
```

### 9.5 `overdue_unknown_subtask.evalset.json`

```json
[
  {
    "name": "overdue_notification_unknown_subtask_partial_ack",
    "description": "POST /v1/events/overdue contains a sub_task_id that does not exist. Expects 200 with warnings, no exception, event logged as partial.",
    "initial_db_state": {
      "goals": [
        {
          "goal_id": "g002",
          "user_id": "u002",
          "title": "Read research papers",
          "status": "IN_PROGRESS",
          "sub_tasks": [
            {"sub_task_id": "t10", "is_completed": false, "title": "Paper 1"}
          ]
        }
      ]
    },
    "turns": [
      {
        "user_content": {
          "role": "user",
          "parts": [{
            "text": "EVENT:overdue",
            "event_payload": {
              "event_id": "evt_002",
              "overdue_tasks": [
                {"sub_task_id": "t99", "goal_id": "g002", "start_time": "2026-05-27T09:00:00"}
              ]
            }
          }]
        },
        "expected_tool_use": [
          {"tool_name": "get_sub_task", "tool_input": {"goal_id": "g002", "sub_task_id": "t99"}}
        ],
        "reference": ""
      }
    ],
    "pass_criteria": {
      "db_checks": [
        {"collection": "event_log", "filter": {"event_id": "evt_002"}, "field": "status", "expected": "partial"},
        {"collection": "event_log", "filter": {"event_id": "evt_002"}, "field": "warnings", "expected_contains": "unknown_sub_task_id: t99"}
      ],
      "response_checks": [
        {"assert_status_code": 200},
        {"assert_field": "status", "expected": "partial"},
        {"assert_field": "processed_count", "expected": 0},
        {"assert_field": "warnings[0]", "expected_contains": "unknown_sub_task_id"}
      ]
    }
  }
]
```

### 9.6 `weekly_memory_write.evalset.json`

```json
[
  {
    "name": "weekly_memory_write_produces_compressed_summary",
    "description": "POST /v1/scheduled/weekly-memory with 7 days of goal completion data. Memory Agent must receive a single summary with completion rate and overrun stats.",
    "initial_db_state": {
      "goals": [
        {"goal_id": "g010", "user_id": "u005", "status": "COMPLETED", "goal_type": "weekly", "total_effort_minutes": 180, "created_at": "2026-05-20T10:00:00Z"},
        {"goal_id": "g011", "user_id": "u005", "status": "ABANDONED", "goal_type": "weekly", "total_effort_minutes": 120, "created_at": "2026-05-21T10:00:00Z"},
        {"goal_id": "g012", "user_id": "u005", "status": "COMPLETED", "goal_type": "daily", "total_effort_minutes": 60, "created_at": "2026-05-22T10:00:00Z"}
      ]
    },
    "turns": [
      {
        "user_content": {
          "role": "user",
          "parts": [{
            "text": "EVENT:weekly_memory_write",
            "event_payload": {"user_id": "u005", "week_start": "2026-05-20"}
          }]
        },
        "expected_tool_use": [
          {"tool_name": "list_active_goals", "tool_input": {}},
          {"tool_name": "write_weekly_summary", "tool_input": {"user_id": "u005"}}
        ],
        "reference": "Weekly behavioral summary written for user u005."
      }
    ],
    "pass_criteria": {
      "db_checks": [
        {"collection": "weekly_memory_writes", "filter": {"user_id": "u005", "week_start": "2026-05-20"}, "field": "status", "expected": "success"},
        {"collection": "weekly_memory_writes", "filter": {"user_id": "u005"}, "field": "summary_text", "assert_contains": ["completion", "abandonment"]}
      ],
      "response_checks": [
        {"assert_status_code": 200},
        {"assert_field": "processed_users", "expected": 1},
        {"assert_field": "skipped_users", "expected": 0}
      ],
      "memory_agent_mock_checks": [
        {"assert_called_once": "write_weekly_summary"},
        {"assert_summary_length_lte": 500}
      ]
    }
  }
]
```

### 9.7 `daily_output_no_planned_date.evalset.json`

```json
[
  {
    "name": "daily_output_goalsub_task_schema_compliance",
    "description": "Schema-level eval: GoalSubTask in daily output payload must not contain planned_date. Fails if planned_date appears anywhere in the output.",
    "initial_db_state": {
      "goals": [
        {
          "goal_id": "g020",
          "user_id": "u010",
          "title": "Complete project proposal",
          "status": "IN_PROGRESS",
          "deadline": "2026-05-30",
          "feasibility_score": 0.8,
          "feasibility_note": "",
          "total_effort_minutes": 240,
          "suggested_blocks_count": 3,
          "suggested_split_ratio": [0.4, 0.4, 0.2],
          "urgency": "high",
          "sub_tasks": [
            {
              "sub_task_id": "st1", "goal_id": "g020",
              "title": "Write executive summary", "estimated_minutes": 60,
              "priority": "high", "deadline": "2026-05-29",
              "preferred_time_of_day": "morning", "can_split": false,
              "is_completed": false, "completed_at": null,
              "planned_date": "2026-05-28"
            }
          ]
        }
      ]
    },
    "turns": [
      {
        "user_content": {
          "role": "user",
          "parts": [{
            "text": "EVENT:daily_output_push",
            "event_payload": {"user_id": "u010"}
          }]
        },
        "expected_tool_use": [
          {"tool_name": "list_active_goals", "tool_input": {"user_id": "u010"}}
        ],
        "reference": ""
      }
    ],
    "pass_criteria": {
      "response_checks": [
        {"assert_status_code": 200}
      ],
      "schema_checks": [
        {
          "model": "GoalSubTask",
          "assert_field_absent": "planned_date",
          "description": "GoalSubTask in daily output must not expose planned_date even though SubTask in DB has it"
        },
        {
          "assert_output_fields_exact": ["title", "estimated_minutes", "priority", "deadline", "preferred_time_of_day", "can_split"],
          "model": "GoalSubTask"
        }
      ]
    }
  }
]
```

---

## 10. Tech Stack

Derived from PRD §10.

### 10.1 Core

| Layer | Technology | Notes |
|---|---|---|
| LLM | `gemini-2.5-pro-preview` | Complex reasoning: feasibility synthesis, sub-task decomposition, weekly memory distillation |
| LLM | `gemini-2.5-flash` | Fast agents: validation loop, progress tracking, overdue handler |
| LLM | `gemini-2.5-flash-lite` | Lightweight tools: structured output calls, reminder formatting |
| Agent Framework | Google Cloud Agent Builder (ADK) | `google-adk` Python SDK; `LlmAgent`, `SequentialAgent`, `LoopAgent`, `ParallelAgent` |
| Backend | Python 3.12 + FastAPI | Async throughout; `uvicorn` on `$PORT` for Cloud Run |
| Database | MongoDB Atlas | Knowledge Graph tier; `motor` async driver; all persistence through this service only |
| Partner Track | MongoDB (Hackathon partner) | Atlas free tier for development; M10+ for production |

### 10.2 Google APIs & Integrations

| Service | Usage in Goal Tracking Agent |
|---|---|
| Google Calendar API | Direct read — `fetch_free_windows` for scheduled jobs and Cloud Scheduler-triggered output; service account with domain-wide delegation |
| Google OAuth 2.0 | Single auth flow for all Google services; token injected via Cloud Run service account |
| Gmail API | Not used by this service (used by Coordinator for cold-start context) |
| Wearable APIs | Not used directly; health data arrives pre-assembled in `GoalAgentInput.health` from Health Agent via Coordinator |

### 10.3 Infrastructure

| Component | Technology |
|---|---|
| Container runtime | Google Cloud Run (stateless; scales to zero) |
| Build pipeline | Cloud Build → Artifact Registry → Cloud Run deploy |
| Scheduled jobs | Cloud Scheduler → OIDC-authenticated `POST` to `/v1/scheduled/*` |
| Secrets | Secret Manager; mounted as env vars (`MONGO_URI`, `GEMINI_API_KEY`, `CALENDAR_SERVICE_ACCOUNT_JSON`) |
| Observability | Cloud Logging (structured JSON); Cloud Trace via OpenTelemetry |
