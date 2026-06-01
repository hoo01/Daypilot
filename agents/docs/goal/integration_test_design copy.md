# Goal Tracking Agent — Integration Test Design

**Project:** DayPilot  
**Service:** `goal-tracking-agent`  
**Version:** 0.1  
**Date:** 2026-05-30  
**Status:** Design complete, pending implementation

---

## Table of Contents

- [1. Overview](#1-overview)
- [2. Test Scenarios (22 total)](#2-test-scenarios-22-total)
- [3. Project Configuration](#3-project-configuration)
- [4. Fake Data Layer](#4-fake-data-layer)
- [5. Test Design and Reporting](#5-test-design-and-reporting)
- [6. Cross-Agent Reusability](#6-cross-agent-reusability)
- [7. Implementation Roadmap](#7-implementation-roadmap)
- [8. Out of Scope](#8-out-of-scope)

---

## 1. Overview

### Why this simulator is needed

The Goal Tracking Agent is fully implemented. However, the other DayPilot agents (Coordinator, Schedule Planning, Memory, Health & Energy) do not exist yet, making true multi-agent end-to-end testing impossible.

This integration test simulator verifies all core Goal Agent logic in complete isolation — without any other agent present.

### Core design principles

1. **Every external dependency has an explicit fake.** Coordinator-assembled input, Schedule Agent events, Memory Agent write endpoint, and Calendar API are all injected via fixtures. No real external services are called.
2. **The LLM layer is replaced by a deterministic stub.** A `StubRunner` replaces the real ADK Runner and drives tool calls and responses from fixed per-scenario scripts. LLM behavior is validated separately by `tests/evals/*.evalset.json` and is not repeated here.
3. **The database layer uses real MongoDB.** A `mongo:7` Docker container is started via `testcontainers`, ensuring that atomic operations, index behavior, and aggregation pipelines all behave exactly as they do in production.
4. **The fake data layer is designed for reuse across other agents.** `tests/fixtures/domain/` strictly avoids importing Goal Agent runtime code, so it can be moved into a shared package when a second agent needs it.

### Scope

**In scope:**
- All internal module interactions: intake → validation → decomposition → feasibility → state transitions → overdue → memory write → daily output
- All API endpoint request/response formats and HTTP status codes
- MongoDB data consistency, including concurrent write scenarios
- Degraded paths: Calendar unavailable, empty memory context, malformed LLM output

**Not in scope:** See [Section 8](#8-out-of-scope).

---

## 2. Test Scenarios (22 total)

### Scenario design principle

The Goal Agent **never reads raw user input directly**. Every test scenario enters via a pre-assembled `GoalAgentInput` (or event payload), simulating the state after the Coordinator Agent has already handled routing and data assembly.

### 2.1 Normal flows (N1–N4)

| ID | Description | Key assertions |
|---|---|---|
| **N1** | Clear, quantifiable, time-bound goal → single intake turn → reaches `confirming` stage | `stage == "confirming"`; goal `status == "CREATED"` in DB; correct number of sub-tasks |
| **N2** | Vague goal (e.g. "study more") → triggers validation loop → user clarifies over 1–2 turns → goal becomes valid | First response contains none of `"invalid"`, `"rejected"`, `"fail"`; after second turn `validation.passed == True` |
| **N3** | Infeasible goal (time + habit feasibility both fail) → agent presents exactly 3 options → user picks option A (extend deadline) | Response contains `"A."`, `"B."`, `"C."`; after picking A, goal deadline is updated and feasibility_score recomputed |
| **N4** | User has 3 active goals → `POST /v1/scheduled/daily-output` → returns 3 `GoalsOutput` objects | `processed_users == 1`; `goals_output` length == 3; no `planned_date` field in any `GoalSubTask` |

### 2.2 State transitions (S1–S4)

| ID | Description | Key assertions |
|---|---|---|
| **S1** | Schedule Agent sends `subtask-scheduled` event → goal transitions from `CREATED` to `IN_PROGRESS` | DB goal `status == "IN_PROGRESS"`; `planned_date` written to the corresponding sub-task |
| **S2** | Send `subtask-completed` events one by one (3 sub-tasks total) → progress increments → on last completion goal auto-transitions to `COMPLETED` | `progress_percent` increments accurately on each event; final `status == "COMPLETED"` |
| **S3** | Schedule Agent sends overdue notification → progress recalculated → reminder string appears in `EventAck.warnings` | HTTP 200; `ack.status == "acknowledged"`; `warnings` contains a `"reminder:"` prefixed message |
| **S4** | Overdue notification received → user chooses replan with new deadline → goal returns to `IN_PROGRESS` | `POST /v1/goals/{id}/replan` returns updated goal; `deadline` changed; `status == "IN_PROGRESS"` |

### 2.3 Edge / degraded paths (E1–E4)

| ID | Description | Key assertions |
|---|---|---|
| **E1** | New user, `memory_context == ""` → habit feasibility falls back to LLM-derived estimates (coding goals: overrun_ratio = 0.30) | `feasibility.habit.degraded == False`; `feasibility_note` contains `"no_memory_baseline"` |
| **E2** | `calendar_free_slots == []` (Coordinator could not fetch calendar data) → time feasibility degrades | `feasibility.time.degraded == True`; `feasibility_score <= 0.7`; HTTP 200 |
| **E3** | Overdue notification contains a `sub_task_id` that does not exist in DB → no crash, returns `partial` | `ack.status == "partial"`; `warnings` contains `"unknown_sub_task_id: <id>"`; event_log entry `status == "partial"` |
| **E4** | Same `event_id` overdue notification sent twice → second call returns `already_processed` and does not re-execute | Second response `ack.status == "already_processed"`; DB state unchanged from first processing |

### 2.4 Lifecycle (L1, L3)

| ID | Description | Key assertions |
|---|---|---|
| **L1** | Goal deadline has passed without completion → user sends abandon request → `status == "ABANDONED"` | `POST /v1/goals/{id}/abandon` returns 200; DB `status == "ABANDONED"`; event_log has a corresponding entry |
| **L3** | Intake session `expires_at` has passed → resume attempt with that `session_id` → 410 Gone | HTTP status 410; response body contains `"intake_session_expired"` |

### 2.5 Concurrency (C1)

| ID | Description | Key assertions |
|---|---|---|
| **C1** | Goal has 2 incomplete sub-tasks; send both `subtask-completed` events simultaneously via `asyncio.gather` → final `progress_percent == 100.0`, `status == "COMPLETED"` | No lost update; `progress_percent` is exactly 100.0; `status == "COMPLETED"` |

> **Background:** The original `recompute_progress_percent` used a read-compute-write pattern that was vulnerable to a lost-update race condition. It has been rewritten as a single atomic `find_one_and_update` with an aggregation pipeline before this document was finalized. C1 validates that this fix holds under real MongoDB concurrency.

### 2.6 State guards (X — 8 parameterized assertions)

Send illegal events to goals in terminal states (`COMPLETED` / `ABANDONED`) and verify the state machine rejects them correctly.

| Terminal state | Illegal event | Expected behavior |
|---|---|---|
| `COMPLETED` | overdue notification | Ignored (or logged); progress and status unchanged |
| `COMPLETED` | subtask-completed | Ignored; no progress change |
| `COMPLETED` | abandon request | Rejected with a specific error message |
| `COMPLETED` | replan request | Rejected with a specific error message |
| `ABANDONED` | overdue notification | Ignored; status stays `ABANDONED` |
| `ABANDONED` | subtask-completed | Ignored (log as zombie completion) |
| `ABANDONED` | abandon request | Idempotent no-op; does not error |
| `ABANDONED` | replan request | Rejected with a specific error message |

Implemented with `@pytest.mark.parametrize` — 8 cases share one test skeleton. The full 8-case matrix (rather than 4) is chosen because rejection semantics and error messages may legitimately differ between the two terminal states, and implementation cost is the same either way.

### 2.7 LLM stub robustness (G1, G2)

These scenarios exploit the `StubRunner`'s ability to return deliberately malformed output, testing the parsing and error-handling layer in ways that are difficult to reproduce with a real LLM.

| ID | Description | Key assertions |
|---|---|---|
| **G1** | Stub returns `GoalsOutput` JSON with extra/missing required fields | Parsing layer does not crash; either repairs (drops extra fields) or retries; final HTTP status != 500 |
| **G2** | Stub returns truncated JSON (simulates token limit exceeded) | No `JSONDecodeError` propagates; degraded fallback path is hit; HTTP status != 500 |

### 2.8 Boundary values (B1, B2)

| ID | Description | Key assertions |
|---|---|---|
| **B1** | Final `subtask-completed` pushes progress to exactly 100.0 (floating-point boundary) | `progress_percent == 100.0` (exact equality, not `>= 99.99`); `status == "COMPLETED"` is triggered |
| **B2** | `deadline = date.today()` → daily output `urgency` must be `"high"` | `urgency == "high"`, not `"medium"` or `"low"` |

### 2.9 Timeout (T1)

| ID | Description | Key assertions |
|---|---|---|
| **T1** | `fetch_free_windows` raises `asyncio.TimeoutError` (not an empty list) → time feasibility degrades; request does not hang and does not return 5xx | `feasibility.time.degraded == True`; HTTP 200; `feasibility_note` mentions timeout |

> **Difference from E2:** E2 tests an empty `calendar_free_slots` list (a valid empty response from the Coordinator). T1 tests the `daily_output_builder` code path where the Calendar API is called directly and times out — a different branch that raises `CalendarUnavailable`.

### 2.10 Partial failure (P2)

| ID | Description | Key assertions |
|---|---|---|
| **P2** | `write_weekly_summary` raises `httpx.HTTPStatusError` → goal data is not rolled back; failure is recorded in `weekly_memory_writes` | `weekly_memory_writes` entry `status == "failed"`; goals collection data intact; response `errors` field non-empty but HTTP 200 |

---

## 3. Project Configuration

### 3.1 MongoDB strategy — `testcontainers-python`

A real `mongo:7` Docker container is started once per pytest session via `testcontainers[mongodb]`. `ensure_indexes(db)` runs against it at session start and it tears down at session end.

**Why real MongoDB instead of mongomock:**
- The atomic `recompute_progress_percent` uses an aggregation pipeline update (`$filter`, `$round`, `$cond`) that mongomock does not reliably support.
- C1 (concurrent lost-update test) requires real MongoDB document-level locking semantics; mongomock is single-threaded in-process and cannot expose the race.

Trade-off: approximately 3 seconds of session startup overhead; requires Docker on developer machines and in CI.

`mongomock-motor` is **removed** from dev dependencies and from `tests/conftest.py` — single backend, no surprises.

### 3.2 LLM stub strategy — StubRunner

`app.state.runner` is replaced with a `StubRunner` instance before HTTP calls are made. No code in `app/agents/` is modified.

```python
# tests/fixtures/goal_agent/runner.py
from dataclasses import dataclass, field
from typing import Callable, Any
from motor.motor_asyncio import AsyncIOMotorDatabase


@dataclass
class ToolCall:
    fn: Callable
    kwargs: dict = field(default_factory=dict)


@dataclass
class ScenarioScript:
    intent: str
    tool_sequence: list[ToolCall]
    final_response: dict   # e.g. {"assistant_message": "...", "stage": "confirming"}


class StubRunner:
    """
    Drop-in replacement for google.adk.runners.Runner.
    Dispatches by state["input"]["intent"] to a fixed ScenarioScript.
    Tools execute for real against the test MongoDB; only the LLM step is faked.
    """
    def __init__(self, db: AsyncIOMotorDatabase, scripts: dict[str, ScenarioScript]):
        self.db = db
        self.scripts = scripts

    async def run_async(self, user_id: str, session_id: str, new_message: Any, state: dict) -> dict:
        intent = state.get("input", {}).get("intent", "")
        script = self.scripts.get(intent)
        if script is None:
            raise ValueError(f"StubRunner: no script registered for intent '{intent}'")
        for tool_call in script.tool_sequence:
            await tool_call.fn(self.db, **tool_call.kwargs)
        return script.final_response
```

Why StubRunner instead of monkey-patching `LlmAgent`:
- Single swap point (`app.state.runner`) with no global side effects.
- No risk of cross-test contamination.
- Resilient to ADK API changes — only `run_async`'s signature needs to stay aligned.

### 3.3 HTTP client

```python
from httpx import AsyncClient, ASGITransport

async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
    response = await client.post("/v1/intake/turn", json=payload)
```

Async throughout; no event-loop switching required.

### 3.4 Settings override

```python
# tests/conftest.py
@pytest.fixture(autouse=True)
def settings_override(mongo_uri: str, monkeypatch):
    from app.config import Settings
    test_settings = Settings(
        mongo_uri=mongo_uri,
        mongo_db_name="test_goal_tracking",
        gemini_api_key="test-dummy-key",
        memory_agent_url="http://mock-memory-agent",
        api_bearer_token="",          # auth disabled in tests
        overload_threshold_minutes=600,
    )
    monkeypatch.setattr("app.config.get_settings", lambda: test_settings)
```

Tests never read `.env` files.

### 3.5 Fixture summary

| Fixture | Scope | Provides |
|---|---|---|
| `mongo_container` | session | A running `mongo:7` testcontainer + connection URI |
| `test_db` | function | Fresh database per test; `ensure_indexes` applied; dropped at teardown |
| `settings_override` | function | `Settings` instance pointing at `test_db` + dummy credentials |
| `mock_memory_client` | function | `respx`-backed httpx mock for `write_weekly_summary` calls |
| `mock_calendar_service` | function | Existing `MagicMock` from current conftest — kept as-is |
| `app_with_stub_runner` | function | FastAPI app with `app.state.runner` replaced by `StubRunner(script)` |
| `async_client` | function | `httpx.AsyncClient` wrapping `app_with_stub_runner` |

### 3.6 New dev dependencies

Add to `pyproject.toml`:

```toml
[project.optional-dependencies]
dev = [
    # ... existing deps ...
    "testcontainers[mongodb]>=4.0",
    "pytest-asyncio>=0.23",
    "respx>=0.21",        # httpx mocking for Memory Agent write endpoint
    "freezegun>=1.4",     # time control for B1 (exact 100% progress) and B2 (deadline=today)
]
```

### 3.7 Directory layout

```
tests/
├── conftest.py                      # extends existing; adds mongo_container, app_with_stub_runner, settings_override
├── fixtures/
│   ├── __init__.py
│   ├── domain/                      # cross-agent reusable layer (see Section 4)
│   │   ├── __init__.py
│   │   ├── factories.py
│   │   └── personas.py
│   └── goal_agent/                  # Goal Agent-specific test infrastructure
│       ├── __init__.py
│       ├── llm_stubs.py             # ScenarioScript definitions for all 22 scenarios
│       ├── reporting.py             # step() context manager + terminal summary plugin
│       └── runner.py                # StubRunner
├── integration/
│   ├── test_intake_flows.py         # N1, N2, N3
│   ├── test_state_transitions.py    # S1, S2, S3, S4
│   ├── test_edge_cases.py           # E1, E2, E3, E4
│   ├── test_lifecycle.py            # L1, L3
│   ├── test_concurrency.py          # C1
│   ├── test_state_guards.py         # X (8 parameterized assertions)
│   ├── test_llm_robustness.py       # G1, G2
│   ├── test_boundaries.py           # B1, B2
│   ├── test_timeouts.py             # T1
│   ├── test_partial_failures.py     # P2
│   └── test_daily_output.py         # N4
├── unit/                            # existing — untouched
└── evals/                           # existing — untouched
```

---

## 4. Fake Data Layer

### 4.1 The layering principle

`tests/fixtures/` is split into two layers with a strict import boundary:

| Layer | Path | Rule | Who can use it |
|---|---|---|---|
| **Domain** (reusable) | `tests/fixtures/domain/` | Only imports `app.schemas.*` and stdlib | Any DayPilot agent's test suite |
| **Goal Agent** (specific) | `tests/fixtures/goal_agent/` | May import anything | Goal Agent tests only |

The domain layer's import restriction makes it `git mv`-able into a shared package with zero code changes when a second agent needs it.

### 4.2 `domain/factories.py` — function signatures

All functions provide sensible defaults and accept per-field overrides:

```python
from datetime import date, datetime, timezone, timedelta
from app.schemas.domain import Goal, SubTask
from app.schemas.input import GoalAgentInput, HealthOutput
from app.schemas.output import GoalsOutput, GoalSubTask
from app.schemas.events import OverdueNotification, SubtaskScheduledEvent, SubtaskCompletedEvent


def make_health_output(
    energy_score: float = 0.75,
    focus_windows: list[dict] | None = None,
    cognitive_load: float = 0.3,
) -> HealthOutput: ...


def make_goal_input(
    user_id: str = "u_test",
    intent: str = "add_goal",
    raw_user_message: str = "I want to solve 5 Leetcode problems by next Friday.",
    health: HealthOutput | None = None,
    memory_context: str = "",
    calendar_free_slots: list[dict] | None = None,
    session_id: str | None = None,
) -> dict: ...    # returns JSON-serializable dict for httpx


def make_subtask(
    sub_task_id: str = "t1",
    goal_id: str = "g_test",
    title: str = "Task 1",
    estimated_minutes: int = 30,
    priority: str = "medium",
    deadline: date | None = None,         # defaults to today + 7
    preferred_time_of_day: str = "flexible",
    can_split: bool = True,
    is_completed: bool = False,
    completed_at: datetime | None = None,
    planned_date: date | None = None,
) -> SubTask: ...


def make_goal(
    goal_id: str = "g_test",
    user_id: str = "u_test",
    title: str = "Solve 5 Leetcode problems",
    goal_type: str = "weekly",
    status: str = "CREATED",
    deadline: date | None = None,         # defaults to today + 7
    sub_tasks: list[SubTask] | None = None,
    feasibility_score: float = 0.85,
    feasibility_note: str = "",
    total_effort_minutes: int = 150,
    suggested_blocks_count: int = 2,
    suggested_split_ratio: list[float] | None = None,
) -> Goal: ...


def make_goals_output(
    goal_id: str = "g_test",
    urgency: str = "medium",
    feasibility_score: float = 0.85,
    feasibility_note: str = "",
    total_effort_minutes: int = 150,
    suggested_blocks_count: int = 2,
    suggested_split_ratio: list[float] | None = None,
    daily_sub_tasks: list[GoalSubTask] | None = None,
) -> GoalsOutput: ...


def make_overdue_event(
    event_id: str = "evt_test",
    goal_id: str = "g_test",
    sub_task_ids: list[str] | None = None,
    start_time: datetime | None = None,
) -> dict: ...


def make_subtask_scheduled_event(
    event_id: str = "evt_test",
    sub_task_id: str = "t1",
    goal_id: str = "g_test",
    start_time: datetime | None = None,
) -> dict: ...


def make_subtask_completed_event(
    event_id: str = "evt_test",
    sub_task_id: str = "t1",
    goal_id: str = "g_test",
    completed_at: datetime | None = None,
) -> dict: ...
```

### 4.3 `domain/personas.py` — three pre-canned user states

```python
from tests.fixtures.domain.factories import make_goal_input, make_health_output


def new_user(intent: str = "add_goal", raw_message: str = "") -> dict:
    """First-time user. Empty memory_context — falls back to LLM-derived estimates."""
    return make_goal_input(
        intent=intent,
        raw_user_message=raw_message,
        memory_context="",
        health=make_health_output(energy_score=0.7),
        calendar_free_slots=[
            {"start": "2026-05-30T09:00:00Z", "end": "2026-05-30T12:00:00Z", "duration_minutes": 180}
        ],
    )


def experienced_user(intent: str = "add_goal", raw_message: str = "") -> dict:
    """User with history. Coding goals average 25% overrun."""
    return make_goal_input(
        intent=intent,
        raw_user_message=raw_message,
        memory_context=(
            "User typically completes weekly coding goals 25% slower than estimated. "
            "Completion rate for weekly goals: 0.78."
        ),
        health=make_health_output(energy_score=0.75),
        calendar_free_slots=[
            {"start": "2026-05-30T09:00:00Z", "end": "2026-05-30T12:00:00Z", "duration_minutes": 180},
            {"start": "2026-05-31T09:00:00Z", "end": "2026-05-31T11:00:00Z", "duration_minutes": 120},
        ],
    )


def infeasible_user(intent: str = "add_goal", raw_message: str = "") -> dict:
    """High-risk user. Short-deadline goals have a 70% abandonment rate."""
    return make_goal_input(
        intent=intent,
        raw_user_message=raw_message,
        memory_context=(
            "User typically completes Leetcode goals 40% slower than estimated. "
            "Short-deadline goals (<3 days) have 70% abandonment rate."
        ),
        health=make_health_output(energy_score=0.4, cognitive_load=0.7),
        calendar_free_slots=[
            {"start": "2026-05-30T09:00:00Z", "end": "2026-05-30T11:00:00Z", "duration_minutes": 120},
        ],
    )
```

### 4.4 Hard import rule for `domain/`

Code inside `tests/fixtures/domain/` may **only** import from:
- `app.schemas.*` (Pydantic models — the cross-agent contract layer)
- Python standard library

It must **never** import from:
- `app.tools.*`
- `app.agents.*`
- `app.runtime.*`
- `app.db.*`
- `google.adk`, `motor`, `httpx`, or any other runtime library

This constraint makes `domain/` portable: extracting it to a shared package is a `git mv` plus a `pyproject.toml`, not a refactor.

---

## 5. Test Design and Reporting

### 5.1 Naming and marker convention

Test function name: `test_<scenario_id>_<short_description>`

```python
@pytest.mark.scenario("N1")
@pytest.mark.category("normal")
async def test_N1_clear_quantifiable_goal_single_turn(async_client, test_db):
    ...

@pytest.mark.scenario("C1")
@pytest.mark.category("concurrency")
async def test_C1_concurrent_subtask_completed_no_lost_update(async_client, test_db):
    ...
```

Register all markers in `pyproject.toml` to suppress pytest warnings:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
markers = [
    "scenario(id): marks test with a scenario ID (e.g. N1, C1, X)",
    "category(name): marks test category (normal, state, edge, lifecycle, concurrency, state_guard, llm_robustness, boundary, timeout, partial_fail)",
]
```

### 5.2 Structured step output — `step()` helper

```python
# tests/fixtures/goal_agent/reporting.py
from contextlib import contextmanager


@contextmanager
def step(label: str):
    print(f"\n  ▶  {label}")
    yield
    print(f"  ✓  {label}")
```

Usage in a test:

```python
async def test_S2_subtask_completed_progresses_to_complete(async_client, test_db):
    with step("Seed goal: 3 sub-tasks, 1 already complete (progress=33.33%)"):
        goal = await seed_goal(test_db, sub_tasks=3, completed=1)
        assert goal.progress_percent == pytest.approx(33.33, abs=0.01)

    with step("Complete sub-task t2 → expect progress=66.67%, status IN_PROGRESS"):
        ack = await async_client.post("/v1/events/subtask-completed",
                                      json=make_subtask_completed_event(sub_task_id="t2"))
        assert ack.status_code == 200
        assert ack.json()["status"] == "acknowledged"

    with step("Complete sub-task t3 (last) → expect progress=100.0, status COMPLETED"):
        ack = await async_client.post("/v1/events/subtask-completed",
                                      json=make_subtask_completed_event(sub_task_id="t3"))
        goal_final = await get_goal_from_db(test_db, "g_test")
        assert goal_final.progress_percent == 100.0, (
            f"Expected 100.0, got {goal_final.progress_percent}. "
            f"Sub-tasks: {[(t.sub_task_id, t.is_completed) for t in goal_final.sub_tasks]}"
        )
        assert goal_final.status == "COMPLETED"
```

Terminal output on pass (run with `-s`):

```
tests/integration/test_state_transitions.py::test_S2_...
  ▶  Seed goal: 3 sub-tasks, 1 already complete (progress=33.33%)
  ✓  Seed goal: 3 sub-tasks, 1 already complete (progress=33.33%)
  ▶  Complete sub-task t2 → expect progress=66.67%, status IN_PROGRESS
  ✓  Complete sub-task t2 → expect progress=66.67%, status IN_PROGRESS
  ▶  Complete sub-task t3 (last) → expect progress=100.0, status COMPLETED
  ✓  Complete sub-task t3 (last) → expect progress=100.0, status COMPLETED
PASSED
```

On failure: the step that printed `▶` but not `✓` localises the failure immediately — no need to read a stack trace first.

### 5.3 Assertion style

Every `assert` carries a self-explanatory error message naming expected vs. actual values plus enough context to diagnose without re-reading the test:

```python
# Do not write:
assert goal.status == "COMPLETED"

# Write instead:
assert goal.status == "COMPLETED", (
    f"Goal {goal.goal_id} should be COMPLETED after all sub-tasks done, "
    f"but status is {goal.status!r}. Progress: {goal.progress_percent}%"
)
```

Use pytest's built-in `==` diff for complex object comparison. No snapshot testing library.

### 5.4 End-of-run summary

A custom pytest plugin registered via `pytest_terminal_summary` in `tests/conftest.py` prints a scenario coverage table at the end of every run:

```
========== Scenario Coverage Summary ==========
Category         | Scenarios       | Pass | Fail | Skip
-----------------|-----------------|------|------|-----
Normal           | N1, N2, N3, N4  |    4 |    0 |    0
State trans.     | S1, S2, S3, S4  |    4 |    0 |    0
Edge/degraded    | E1, E2, E3, E4  |    3 |    1 |    0
Lifecycle        | L1, L3          |    2 |    0 |    0
Concurrency      | C1              |    1 |    0 |    0
State guards     | X               |    8 |    0 |    0
LLM robustness   | G1, G2          |    2 |    0 |    0
Boundary         | B1, B2          |    2 |    0 |    0
Timeout          | T1              |    1 |    0 |    0
Partial fail     | P2              |    1 |    0 |    0
-----------------|-----------------|------|------|-----
TOTAL            | 22 + 8 (X)      |   28 |    1 |    0
```

The plugin tracks results via `pytest_runtest_logreport` and reads the `scenario` marker on each test item.

### 5.5 Run commands

```bash
# All integration tests + summary
pytest tests/integration/ -v -s

# Filter by category
pytest tests/integration/ -m "category('concurrency')" -v -s

# Filter by single scenario
pytest tests/integration/ -m "scenario('C1')" -v -s

# Fast smoke (skip concurrency tests)
pytest tests/integration/ -m "not category('concurrency')"

# Unit tests only (existing, unaffected)
pytest tests/unit/ -v
```

---

## 6. Cross-Agent Reusability

### 6.1 Per-agent reuse map

| Agent | What is shared | Reuse level |
|---|---|---|
| **Schedule Planning Agent** | Consumes `GoalsOutput`; pushes `subtask-scheduled` / `overdue` / `subtask-completed` events; also consumes `HealthOutput` | **High** — all domain factories and event factories apply directly |
| **Coordinator Agent** | Assembles `GoalAgentInput`; routes between agents | **Medium** — `make_goal_input()` + personas usable to assert its assembled payload shape |
| **Memory Agent** | Receives weekly `summary_text`; produces `memory_context` strings | **Medium** — persona `memory_context` strings are pre-canned Memory Agent output samples |
| **Health & Energy Agent** | Produces `HealthOutput` | **Low** — `make_health_output()` serves as a schema anchor only |
| **Real-time Adjustment Agent** | Schedule disruption (indirect) | **Low** |

### 6.2 Reuse example — Schedule Agent perspective

Schedule Agent tests can import from `domain/` without touching Goal Agent runtime code:

```python
# Schedule_Planning_Agent/tests/integration/test_daily_planning.py
from dayPilot_test_fixtures.domain.factories import make_goals_output, make_subtask
from dayPilot_test_fixtures.domain.personas import experienced_user

async def test_assigns_morning_blocks_for_focus_tasks(...):
    daily_output = make_goals_output(
        goal_id="g_test",
        suggested_blocks_count=2,
        daily_sub_tasks=[
            make_subtask(preferred_time_of_day="morning", estimated_minutes=60),
            make_subtask(preferred_time_of_day="morning", estimated_minutes=45),
        ],
    )
    # GoalSubTask schema validation happens automatically via Pydantic
```

Schedule Agent can also use `make_subtask_scheduled_event()` to assert the shape of events it emits, ensuring Goal Agent will accept them — bidirectional contract testing from a single set of factories.

### 6.3 Packaging strategy — in-repo now, extract on second use

**Current decision:** Keep `domain/` inside `Goal_Tracking_Agent/tests/fixtures/domain/`. Do not create a separate package yet.

**Rationale:** Schemas are still evolving (v1/v2 field differences). Premature extraction adds sync cost across moving schemas. Rule of Three — do not extract on first occurrence.

**Extraction trigger:** The moment any other agent's test suite needs to `import make_goal()` or `make_subtask()`, extract `domain/` to a standalone package `dayPilot-test-fixtures/`. The action is `git mv` + a new `pyproject.toml`. No factory code changes required because the import rule was enforced from the start.

### 6.4 What NOT to reuse

| Asset | Why it is Goal Agent-specific |
|---|---|
| `StubRunner` | Each agent has a different ADK agent hierarchy |
| `ScenarioScript` content | Scenarios are agent-specific |
| MongoDB collection schemas + indexes | Each agent has its own database |
| FastAPI route tests | Routes are agent-specific |
| `mongo_container` / `app_with_stub_runner` fixtures | Per-agent test infrastructure |

The reusable surface is: **domain object factories + user personas + naming conventions**.

### 6.5 Naming conventions — locked now to avoid rename-on-extract

| Category | Convention | Examples |
|---|---|---|
| Domain factories | `make_<domain_object>` snake_case | `make_goal`, `make_subtask`, `make_health_output` |
| User personas | `<state>_user` | `new_user`, `experienced_user`, `infeasible_user` |
| Event factories | `make_<event_name>_event` | `make_overdue_event` (not `make_overdue` or `make_overdue_notification`) |

After extraction the import path changes from `tests.fixtures.domain.factories` to `dayPilot_test_fixtures.domain.factories`. Function names do not change.

---

## 7. Implementation Roadmap

Implement in this order — each step is independently verifiable:

1. **Infrastructure layer** — `testcontainers` fixture, `StubRunner`, `settings_override`, `async_client` fixture. Smoke-verify with `/healthz` endpoint.
2. **Domain factories** — implement `factories.py` and `personas.py`. Verify Pydantic schema conformance with `pytest tests/unit/` (no DB needed).
3. **Normal flows** — implement N1, N2, N3, N4. These cover the full intake pipeline and daily output baseline.
4. **State transitions** — implement S1, S2, S3, S4. Validates the event-driven pipeline.
5. **Lifecycle** — implement L1, L3. Validates the abandon and expired-session terminal paths.
6. **Edge / degraded** — implement E1, E2, E3, E4. Each targets a distinct degraded code branch.
7. **Concurrency** — implement C1. Validates the `recompute_progress_percent` atomic fix under real load.
8. **State guards** — implement X (8 parameterized assertions). Verifies terminal-state guard completeness.
9. **LLM stub robustness** — implement G1, G2. Inject deliberately malformed stub output.
10. **Remaining** — implement B1, B2, T1, P2. These require `freezegun` and `respx` to be configured; implement after the rest of the suite is stable.

---

## 8. Out of Scope

| Excluded item | Where it is covered instead |
|---|---|
| Real LLM behavior (e.g. agent tone, question phrasing) | `tests/evals/*.evalset.json` (ADK evalset format) |
| Multi-agent end-to-end tests (Coordinator → Goal Agent → Schedule Agent full chain) | Separate document, after other agents are implemented |
| Performance / load testing | Separate test suite |
| Real Calendar or Gemini API calls | All external APIs are mocked via fixtures |
| Live user notification push (WebSocket / SSE) | Planned during Coordinator + frontend integration phase. The Goal Agent already surfaces reminder text via `EventAck.warnings["reminder:..."]`; the push mechanism belongs to the Coordinator and frontend. |
| `mongomock-motor` based tests | Removed from the project entirely — single backend only |

---

*Note: `app/tools/goal_db.py::recompute_progress_percent` was rewritten to use an atomic aggregation pipeline update before this document was finalized. Scenario C1 is the regression test for that fix.*
