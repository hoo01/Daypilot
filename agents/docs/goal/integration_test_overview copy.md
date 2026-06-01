# Goal Tracking Agent — Integration Test Overview

> **Audience:** teammates new to this service.  
> For the full technical design see [integration_test_design.md](integration_test_design.md).

---

## What this test suite does

The Goal Tracking Agent has no live neighbors yet — the Coordinator, Schedule Planning, Memory, and Health agents don't exist. These integration tests verify the entire agent in complete isolation by:

- Replacing the LLM with a **deterministic StubRunner** that executes real database operations but returns scripted responses.
- Running a **real `mongo:7` container** (via Docker + testcontainers) so atomic ops, indexes, and aggregation pipelines behave exactly as in production.
- Faking every external HTTP call (Memory Agent, Calendar API) via fixtures and `respx` mocks.

Nothing is mocked at the MongoDB layer, and nothing real is called outside the process.

---

## Simulated data and inputs

### Who sends what

| Simulated actor | How it's faked | Example |
|---|---|---|
| **Coordinator Agent** | `make_goal_input()` factory builds a `GoalAgentInput` payload | `intent="add_goal"`, `calendar_free_slots=[]`, `memory_context=""` |
| **Schedule Planning Agent** | HTTP POST to `/v1/events/subtask-scheduled` / `subtask-completed` / `overdue` | Event payloads from `make_subtask_completed_event()` etc. |
| **Memory Agent** | `respx` intercepts `POST /v1/memory/write-weekly` | Returns 200 OK (or 500 for failure scenarios) |
| **Calendar API** | `monkeypatch` on `fetch_free_windows` | Raises `asyncio.TimeoutError` for timeout tests |

### Domain objects seeded

Goals, sub-tasks, and intake sessions are inserted directly into the test database using real `create_goal()` / `start_intake_session()` calls — the same functions the production code uses. Each test runs against its own isolated database (fresh UUID-named DB per test, dropped on teardown).

### Personas

Three built-in user personas for concise test setup:

| Persona | `user_id` | Characteristics |
|---|---|---|
| `new_user()` | `u_new_...` | Empty `memory_context`, no calendar slots |
| `experienced_user()` | `u_exp_...` | Rich `memory_context`, full calendar |
| `infeasible_user()` | `u_inf_...` | Short deadline, heavy workload |

---

## Scenarios covered (38 tests, 41 collected)

### Normal intake flows

| ID | What it tests |
|---|---|
| **N1** | Clear goal → single turn → goal written to DB with 5 sub-tasks, `stage="confirming"` |
| **N2** | Vague goal ("study more") → agent asks for clarification → second turn resolves validation |
| **N3** | Infeasible goal → agent returns A/B/C options → user picks "extend deadline" → feasibility_score rises |
| **N4** | 3 active goals → `POST /scheduled/daily-output` → returns all 3 in response, no `planned_date` field leaked |

### State transitions

| ID | What it tests |
|---|---|
| **S1** | `subtask-scheduled` event → goal `CREATED → IN_PROGRESS`; `planned_date` written to sub-task |
| **S2** | Three `subtask-completed` events one by one → progress increments; final completion → `COMPLETED` |
| **S3** | Overdue notification → reminder warning appears in `EventAck.warnings` |
| **S4** | Replan after overdue → new deadline accepted → `status = IN_PROGRESS` |

### Edge / degraded paths

| ID | What it tests |
|---|---|
| **E1** | New user with no memory history → feasibility falls back to LLM estimates; note says `no_memory_baseline` |
| **E2** | Empty calendar slots (`[]`) → time feasibility degrades; `feasibility_score ≤ 0.7` |
| **E3** | Overdue event references a sub-task that doesn't exist → HTTP 200 with `status="partial"` and warning |
| **E4** | Same event sent twice → second call returns `already_processed`; DB unchanged |

### Lifecycle

| ID | What it tests |
|---|---|
| **L1** | Goal past deadline → user abandons → `status = ABANDONED`; event_log entry written |
| **L3** | Intake session TTL expired → second turn returns HTTP 410 `intake_session_expired` |

### Concurrency

| ID | What it tests |
|---|---|
| **C1** | Two `subtask-completed` events fired simultaneously via `asyncio.gather` → `progress_percent` is exactly 100.0 with no lost update (validates the atomic aggregation-pipeline rewrite) |

### State guards (8 parameterized cases)

Tests illegal operations on goals already in a terminal state (`COMPLETED` / `ABANDONED`).

| Action on terminal goal | Expected behavior | Status |
|---|---|---|
| COMPLETED + overdue | Ignored, status unchanged | ✅ Pass |
| COMPLETED + subtask-completed | Ignored, status unchanged | ✅ Pass |
| COMPLETED + abandon | Rejected with 4xx | ⚠️ `xfail` — guard not yet in production |
| COMPLETED + replan | Rejected with 4xx | ⚠️ `xfail` — guard not yet in production |
| ABANDONED + overdue | Ignored, status unchanged | ✅ Pass |
| ABANDONED + subtask-completed | Status unchanged (progress may update) | ✅ Pass |
| ABANDONED + abandon | Idempotent no-op | ✅ Pass |
| ABANDONED + replan | Rejected with 4xx | ⚠️ `xfail` — guard not yet in production |

> The three `xfail` cases are **expected failures** that document a known gap: `set_goal_status()` currently has no terminal-state guard. Once the guard is added, these three will automatically turn green.

### LLM robustness

| ID | What it tests |
|---|---|
| **G1** | StubRunner returns JSON with an extra unrecognised field → parsing layer doesn't crash (status ≠ 500) |
| **G2** | StubRunner returns truncated JSON (simulates token limit) → no `JSONDecodeError` propagates |

### Boundary values

| ID | What it tests |
|---|---|
| **B1** | Last sub-task completion pushes `progress_percent` to exactly `100.0` (not `99.999...`) → auto-completes goal |
| **B2** | `deadline == today` → daily output `urgency` is `"high"` (uses `freezegun` to fix the clock) |

### Timeout

| ID | What it tests |
|---|---|
| **T1** | Calendar API raises `asyncio.TimeoutError` mid-request → HTTP 200 returned; feasibility note contains `"time.degraded=True"` and mentions timeout |

### Partial failure

| ID | What it tests |
|---|---|
| **P2** | Memory Agent returns HTTP 500 → goals data untouched; `weekly_memory_writes` record written with `status="failed"` |

---

## How to run

Requires Docker Desktop running.

```bash
mkdir -p /tmp/docker-noauth && echo '{"auths":{}}' > /tmp/docker-noauth/config.json

conda run --no-capture-output -n daypilot \
  env DOCKER_CONFIG=/tmp/docker-noauth \
      DOCKER_HOST=unix:///Users/$USER/.docker/run/docker.sock \
      TESTCONTAINERS_RYUK_DISABLED=true \
  python -m pytest tests/integration/ -v
```

Expected output (first run pulls `mongo:7` image, ~600 MB one-time):

```
38 passed, 3 xfailed, 1 warning in ~8s
```

The terminal summary at the end of each run shows per-scenario pass/fail counts.

---

## Key infrastructure decisions

| Decision | Why |
|---|---|
| Real MongoDB via testcontainers | Atomic aggregation-pipeline updates and concurrent locking can't be tested with mongomock |
| StubRunner, not LLM mock | Replacing `app.state.runner` is the narrowest injection point; no production code is modified |
| `httpx.ASGITransport` (no lifespan) | State is set directly on the FastAPI app before wrapping in `AsyncClient`; ASGI lifespan is not triggered by httpx |
| `respx` for Memory Agent | Intercepts `httpx` calls at the transport layer; zero production code changes needed |
| `freezegun` for date-sensitive tests | Pins `date.today()` so B2's urgency calculation is deterministic regardless of when the suite runs |
