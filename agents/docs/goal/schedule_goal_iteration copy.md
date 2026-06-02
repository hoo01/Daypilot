# Schedule & Goal Agent — Iteration Notes

This document tracks all identified issues and planned modifications arising from the
Schedule Planning Agent ↔ Goal Tracking Agent integration review (session: 2026-05-31).

---

## 1. `OverdueTaskRef.start_time` type change ✅ RESOLVED — Change reverted, keeping `start_time: datetime`

**File:** `schemas/goal_events.py`

**Original proposal:** Change `start_time: datetime` to `scheduled_date: date` to enforce
day-level granularity for overdue tracking.

**Decision (PRD §11 Q3):** The change was **not applied**. `planned_date` is redundant because
the date can always be derived from `start_time` via `.date()`. Keeping a separate `date`-typed
field would duplicate information and create two sources of truth.

**Current state (correct):**
```python
class OverdueTaskRef(BaseModel):
    sub_task_id: str
    goal_id: str
    start_time: datetime   # originally-scheduled start from Schedule Agent output
```

`tests/unit/test_schemas.py` (`TestOverdueTaskRefContract`) explicitly enforces this:
- `test_start_time_field_present` — asserts `start_time` is present
- `test_planned_date_field_absent` — asserts `planned_date` is absent

**No further action needed on this item.**

---

## 2. End-of-day checklist — DESIGN COMPLETE, IMPLEMENTATION NOT STARTED

### Trigger model

The trigger is **frontend-initiated at midnight (00:00 local time)**.

Throughout the day, the user marks tasks complete in the UI. Each completion is sent
immediately to the backend via `POST /v1/events/subtask-completed`. At midnight, the
frontend sends a single "close the day" request. The backend already has the full
completion state; no checklist data needs to be re-sent — the midnight call is a
processing trigger, not a data upload.

```
During the day:
  User taps task as done → POST /v1/events/subtask-completed  (real-time, per task)

At midnight (frontend cron / background service):
  POST /v1/scheduled/end-of-day  {"user_id": "...", "date": "2026-06-02"}
    → Backend computes what's incomplete, classifies goal health, acts accordingly
    → Returns summary to frontend (e.g. "3 tasks carried to tomorrow, 1 goal needs your input")
```

---

### Full data propagation chain

```
POST /v1/scheduled/end-of-day
  │
  ├─ 1. Query: subtasks where planned_date == today AND is_completed == False
  │         grouped by goal_id
  │
  ├─ 2. For each affected goal:
  │       a. Fetch goal document
  │       b. Compute remaining_effort_minutes, remaining_days, daily_rate_needed
  │       c. Compute historical_daily_rate  (via compute_daily_rate())
  │       d. Classify: on_track  OR  needs_replan (Level 2)
  │
  ├─ 3a. ON-TRACK goals (silent carryover):
  │       → update_sub_task(planned_date = today + 1 day)  for each incomplete subtask
  │       → No user interaction. Tomorrow's daily-output naturally picks them up.
  │
  └─ 3b. NEEDS-REPLAN goals:
          → update_goal(replan_requested_at = now())
          → set_goal_status(goal_id, "OVERDUE")
          → No immediate action. Coordinator picks this up next time user opens the app.


Next day (user opens app):
  Coordinator calls track_goals(user_id)
    → track_goals calls POST /v1/scheduled/daily-output
    → daily-output checks goal.replan_requested_at  →  sets GoalsOutput.replan_pending = True
    → track_goals returns replan_pending = True to Coordinator

  Coordinator sees replan_pending = True
    → Routes to goal_tracking_root (Goal Agent) with intent = "replan"

  Goal Agent (overdue handler):
    → Presents user with: Extend deadline / Reduce scope / Snooze 24h / Keep as-is
    → Applies user choice (updates deadline, marks subtasks ABANDONED, etc.)
    → Clears goal.replan_requested_at = null

  Coordinator receives updated goal state
    → Calls plan_schedule() with the updated goal context
    → Schedule Agent generates tomorrow's schedule with correct subtask list
```

---

### Level 2 trigger conditions (same as §5, applied here)

Both conditions use data already on the Goal document — no extra queries needed.

```python
remaining_effort    = sum(t.estimated_minutes for t in goal.sub_tasks if not t.is_completed)
remaining_days      = max((goal.deadline - date.today()).days, 1)
daily_rate_needed   = remaining_effort / remaining_days

# historical_daily_rate: see compute_daily_rate() in §5C
```

**Level 2 fires if either condition is true:**
- `daily_rate_needed > historical_daily_rate * 1.5`
- `remaining_days <= 3 AND goal.progress_percent < 70`

If neither fires → on_track (silent carryover).

Level 1 (soft reminder / streak tracking from §5B) is a future enhancement; for the
initial implementation only on_track vs. Level 2 is needed.

---

### Schema changes required

**`schemas/goal_domain.py` — add to `Goal`:**
```python
replan_requested_at: Optional[datetime] = None   # set by end-of-day; cleared after user responds
```

**`schemas/goals.py` — add to `GoalsOutput`:**
```python
replan_pending: bool = False   # True when goal.replan_requested_at is set
```

**`api/routes/scheduled.py` — `_goal_to_goals_output()`:**
```python
replan_pending = goal.replan_requested_at is not None,
```

---

### New endpoint: `POST /v1/scheduled/end-of-day`

**Location:** `api/routes/scheduled.py`

```python
class EndOfDayRequest(BaseModel):
    user_id: str
    date: Optional[date] = None          # defaults to today

class GoalEndOfDayResult(BaseModel):
    goal_id: str
    goal_title: str
    action: str                          # "carried_over" | "replan_requested"
    incomplete_count: int

class EndOfDayResponse(BaseModel):
    processed_date: date
    goals_processed: int
    results: list[GoalEndOfDayResult]
    errors: list[str]

@router.post("/scheduled/end-of-day", response_model=EndOfDayResponse)
async def end_of_day(body: EndOfDayRequest) -> EndOfDayResponse:
    target_date = body.date or date.today()
    tomorrow = target_date + timedelta(days=1)
    db = get_db()
    results = []

    goals = await list_active_goals(db, body.user_id)
    for goal in goals:
        incomplete = [t for t in goal.sub_tasks
                      if not t.is_completed and t.planned_date == target_date]
        if not incomplete:
            continue

        daily_rate = await compute_daily_rate(db, goal.goal_id)
        remaining_effort = sum(t.estimated_minutes for t in goal.sub_tasks if not t.is_completed)
        remaining_days = max((goal.deadline - target_date).days, 1)
        daily_rate_needed = remaining_effort / remaining_days

        needs_replan = (
            (daily_rate > 0 and daily_rate_needed > daily_rate * 1.5)
            or (remaining_days <= 3 and goal.progress_percent < 70)
        )

        if needs_replan:
            await update_goal(db, goal.goal_id, {"replan_requested_at": _now_utc().isoformat()})
            await set_goal_status(db, goal.goal_id, "OVERDUE")
            action = "replan_requested"
        else:
            for t in incomplete:
                await update_sub_task(db, goal.goal_id, t.sub_task_id,
                                      {"planned_date": tomorrow.isoformat()})
            action = "carried_over"

        results.append(GoalEndOfDayResult(
            goal_id=goal.goal_id,
            goal_title=goal.title,
            action=action,
            incomplete_count=len(incomplete),
        ))

    return EndOfDayResponse(
        processed_date=target_date,
        goals_processed=len(results),
        results=results,
        errors=[],
    )
```

---

### Coordinator instruction change

After the fix to `track_goals()` (§4), add this routing rule:

```
| `replan_goal` | track_goals() returns any goal with replan_pending=True |
|               | Transfer to goal_tracking_root with intent="replan"      |
|               | Pass the goal_id(s) with replan_pending=True as context  |
```

---

### What needs to be built (ordered by dependency)

| Step | Component | Location | Depends on |
|---|---|---|---|
| 1 | `replan_requested_at` field on `Goal` | `schemas/goal_domain.py` | — |
| 2 | `compute_daily_rate()` | `agents/tools/progress_calc.py` | — |
| 3 | `POST /v1/scheduled/end-of-day` endpoint | `api/routes/scheduled.py` | steps 1, 2 |
| 4 | `replan_pending` on `GoalsOutput` + `_goal_to_goals_output()` update | `schemas/goals.py`, `api/routes/scheduled.py` | step 1 |
| 5 | `track_goals()` HTTP fix (§4B) + parse `replan_pending` | `agents/tools/goal_tools.py` | step 4 |
| 6 | Coordinator instruction: route on `replan_pending` | `agents/coordinator.py` | step 5 |
| 7 | Frontend midnight cron → `POST /v1/scheduled/end-of-day` | Frontend | step 3 |

---

## 3. `handle_overdue` does not perform rescheduling — PENDING BROADER DESIGN

**File:** `api/routes/events.py`, `handle_overdue()`

**Context:** §1 was resolved — `OverdueTaskRef` keeps `start_time: datetime` (not `scheduled_date`).
The handler receives `start_time` but currently ignores it. It only reads `ref.goal_id` and
`ref.sub_task_id`, then recomputes `progress_percent` and writes a behind-schedule reminder to
the event log. No rescheduling happens.

**Why `start_time` would be useful:**
- Deferral tracking: `start_time.date()` gives the originally-planned date. Logging how many
  times a subtask slipped is useful for feasibility scoring and `compute_daily_rate()` (§5C).
- Rescheduling input: the Schedule Agent needs to know which tasks were missed and on what day
  in order to carry them forward.

**Current state:** `handle_overdue` is a log-and-acknowledge handler only. Rescheduling is
entirely absent from the system (confirmed — no component currently carries incomplete tasks
into the next day's `plan_schedule` call).

**Decision deferred to §2 design:** Rescheduling is a Coordinator-level responsibility triggered
by the end-of-day checklist flow. `handle_overdue` should remain a pure event receiver.
Once the §2 data chain is designed, the rescheduling path will be specified there.

---

## 4. `track_goals()` reads from an orphaned collection — FIX CONFIRMED

**Files:**
- `agents/tools/goal_tools.py` — `track_goals()`
- `agents/memory.py` — `MemoryAgent.get_goal_state()` / `upsert_goal_state()`

### Root cause

`track_goals()` calls `MemoryAgent.get_goal_state(user_id)`, which reads from the `goal_state`
MongoDB collection. That collection is **never written to** — `upsert_goal_state()` is defined
on `MemoryAgent` but has zero callers in the codebase. As a result:

- `get_goal_state()` always returns `{}`
- `track_goals()` hits the `"no_goals"` early-return branch and returns
  `{"goal_status": "no_goals", "progress_percent": 0.0, ...}`
- The Coordinator feeds this empty context into `plan_schedule()`, so generated schedules
  have no awareness of actual goal progress

The real goal data lives in the `goals` collection, managed by `api/routes/goals.py`,
`api/routes/events.py`, and `api/routes/scheduled.py`.

### Fix plan

**Step 1 — Remove dead code from `MemoryAgent`**

Delete `upsert_goal_state()` and `get_goal_state()` from `agents/memory.py`.
These methods have no callers and refer to a collection that is no longer the source of truth.

**Step 2 — Replace `track_goals()` with a real HTTP call**

`agents/tools/goal_tools.py`, `track_goals(user_id)`:

```python
async def track_goals(user_id: str) -> dict:
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            f"{settings.goal_agent_url}/v1/scheduled/daily-output",
            json={"user_id": user_id},
        )
        response.raise_for_status()
        data = response.json()   # DailyOutputResponse: {processed_users, goals_output, errors}

    goals_output = data.get("goals_output", [])
    if not goals_output:
        return {"goal_status": "no_goals", "progress_percent": 0.0, "urgency": "low",
                "goals": [], "replan_pending": False}

    # Derive aggregate status for the Coordinator
    urgencies = [g["urgency"] for g in goals_output]
    top_urgency = "high" if "high" in urgencies else ("medium" if "medium" in urgencies else "low")
    avg_feasibility = sum(g["feasibility_score"] for g in goals_output) / len(goals_output)
    replan_pending = any(g.get("replan_pending", False) for g in goals_output)

    return {
        "goal_status": "on_track" if avg_feasibility >= 0.6 else "at_risk",
        "progress_percent": round(avg_feasibility * 100, 1),
        "urgency": top_urgency,
        "goals": goals_output,
        "replan_pending": replan_pending,   # True if any goal needs user decision
    }
```

**Step 3 — Add `goal_agent_url` to config**

`config.py`: add `goal_agent_url: str = "http://localhost:8001"` (or the Cloud Run URL in prod).

### What this fixes

After this change, `plan_schedule()` receives real goal urgency, feasibility, and today's
subtask list from the Goal Tracking Agent, so generated schedules are actually informed by
goal progress.

---

## 4B. Supporting changes for the end-of-day + replan flow — NOT YET IMPLEMENTED

These are smaller changes that don't fit neatly under a single section but are required
for the §2 chain to work end-to-end.

---

### `compute_daily_rate()` — new function

**File:** `agents/tools/progress_calc.py`

Computes how many minutes of goal work the user has been completing per day, on average,
over the past N days. Used by the end-of-day endpoint to evaluate Level 2 conditions.

```python
from datetime import date, datetime, timedelta, timezone
from motor.motor_asyncio import AsyncIOMotorDatabase
from agents.tools.goal_db import get_goal

async def compute_daily_rate(
    db: AsyncIOMotorDatabase,
    goal_id: str,
    window_days: int = 7,
) -> float:
    """
    Returns average completed effort (minutes/day) over the last window_days days.
    Uses completed_at timestamps on sub_tasks — no event_log query needed.
    Returns 0.0 if no completions exist yet.
    """
    goal = await get_goal(db, goal_id)
    if not goal:
        return 0.0

    days_since_created = (date.today() - goal.created_at.date()).days
    N = max(min(days_since_created, window_days), 1)
    cutoff = datetime.now(timezone.utc) - timedelta(days=N)

    completed_minutes = sum(
        t.estimated_minutes
        for t in goal.sub_tasks
        if t.is_completed
        and t.completed_at is not None
        and t.completed_at >= cutoff
    )
    return completed_minutes / N
```

---

### `POST /v1/goals/{goal_id}/replan` — must clear `replan_requested_at`

**File:** `api/routes/goals.py`, `replan_goal()`

The endpoint already exists and updates `deadline` + sets `status = "IN_PROGRESS"`.
It needs one additional write to clear the replan flag so the Coordinator stops routing
to the Goal Agent:

```python
# Add to replan_goal(), after set_goal_status():
from agents.tools.goal_db import update_goal
await update_goal(db, goal_id, {"replan_requested_at": None})
```

---

### "Reduce scope" — new endpoint for subtask abandonment

**File:** `api/routes/goals.py`

The "Reduce scope" replan option requires marking specific subtasks as abandoned
(not the whole goal). This endpoint does not currently exist.

```python
class ReduceScopeRequest(BaseModel):
    user_id: str
    sub_task_ids: list[str]   # subtasks the user agrees to drop

@router.post("/{goal_id}/reduce-scope", response_model=Goal)
async def reduce_scope(goal_id: str, body: ReduceScopeRequest) -> Goal:
    db = get_db()
    goal = await get_goal(db, goal_id)
    if goal is None:
        raise HTTPException(status_code=404, detail={"error": "goal_not_found"})
    if goal.status in TERMINAL_STATES:
        raise HTTPException(status_code=422, detail={"error": "illegal_transition"})

    for sub_task_id in body.sub_task_ids:
        await update_sub_task(db, goal_id, sub_task_id, {"is_completed": True,
                                                          "abandoned": True})
    await update_goal(db, goal_id, {"replan_requested_at": None})
    new_pct = await recompute_progress_percent(db, goal_id)
    if new_pct == 100.0:
        await set_goal_status(db, goal_id, "COMPLETED")

    updated = await get_goal(db, goal_id)
    # log event ...
    return updated
```

Note: `SubTask` schema needs `abandoned: bool = False` added to distinguish dropped
subtasks from genuinely completed ones. This affects `compute_progress_percent()`.

**Decision (confirmed):** Abandoned subtasks are excluded from **both** numerator and
denominator. They do not count as completed and do not inflate the total.

```python
# agents/tools/progress_calc.py — update compute_progress_percent():
def compute_progress_percent(sub_tasks: list[SubTask]) -> float:
    active = [t for t in sub_tasks if not getattr(t, "abandoned", False)]
    if not active:
        return 0.0
    completed = sum(1 for t in active if t.is_completed)
    return round(completed / len(active) * 100, 2)
```

`recompute_progress_percent()` in `agents/tools/goal_db.py` uses a MongoDB aggregation
pipeline and must also be updated to filter out `abandoned == true` subtasks from both
the size count and the completed filter.

---

### Goal Agent overdue handler — tool list update

**File:** `agents/goal/overdue.py`

The current tool list is `[get_goal, set_goal_status, format_overdue_prompt]`.
For the replan flow (triggered when `replan_requested_at` is set), the agent needs
to be able to call the three replan paths:

```python
# Add these tools to build_overdue_handler_agent():

async def _call_replan(goal_id: str, new_deadline: str, user_id: str):
    """Extend deadline: POST /v1/goals/{goal_id}/replan"""
    async with httpx.AsyncClient() as client:
        await client.post(
            f"{settings.goal_agent_url}/v1/goals/{goal_id}/replan",
            json={"new_deadline": new_deadline, "user_id": user_id},
        )

async def _call_reduce_scope(goal_id: str, sub_task_ids: list[str], user_id: str):
    """Drop subtasks: POST /v1/goals/{goal_id}/reduce-scope"""
    async with httpx.AsyncClient() as client:
        await client.post(
            f"{settings.goal_agent_url}/v1/goals/{goal_id}/reduce-scope",
            json={"sub_task_ids": sub_task_ids, "user_id": user_id},
        )

async def _clear_replan_flag(goal_id: str):
    """Used for 'Keep as-is' — clears flag without changing goal."""
    return await update_goal(db, goal_id, {"replan_requested_at": None})
```

The overdue handler prompt (`agents/goal/prompts/overdue.md`) also needs updating
to cover the four user choices: Extend deadline / Reduce scope / Snooze 24h / Keep as-is.

---

## 5. Replan decision tree after end-of-day checklist — NOT YET IMPLEMENTED

### Overview

After the end-of-day checklist is processed, incomplete tasks feed into a two-branch
decision tree. The split happens in the Coordinator based on goal health metrics.

```
End-of-day checklist result
 ├─ Incomplete tasks exist, but goal is still on track
 │     → Coordinator silently carries them into tomorrow's schedule
 │       → POST /schedule/generate  (no user interaction)
 │
 └─ Goal is behind / near deadline / chronically incomplete
       → Coordinator triggers Goal Agent replan flow
         → Goal Agent asks user: extend deadline / reduce scope / keep as-is
           → if sub_tasks are re-split
               → Coordinator → POST /schedule/generate with new sub_tasks
```

### Level 1 — Soft reminder (no forced replan)

Trigger conditions (both use rolling 3-day streak):
- `progress_gap > 20%` for 3 consecutive days, OR
- `goal_status == "behind_schedule"` for 3 consecutive days

Behavior: Coordinator does **not** interrupt the user with a replan prompt.
It only increases the weight of goal-related focus blocks in the next daily schedule.
The user can continue ignoring without being forced into a decision.

**Implementation note — streak tracking (decided: event_log query approach):**
"3 consecutive days" does not require a counter field on the Goal schema.
The `event_log` collection already stores one `daily_output` entry per goal per day.
To evaluate the streak, query the last 3 `event_log` documents where
`event_type == "daily_output"` and `goal_id == <id>`, ordered by `received_at` descending,
and check that all 3 have `payload.progress_gap > 0.2`.
No schema change required; the historical data is already there.

### Level 2 — Forced replan interaction

Trigger conditions (either one is sufficient):
- `daily_rate_needed > historical_daily_rate * 1.5`
- `remaining_days <= 3 AND progress_percent < 70%`

Where:
```
daily_rate_needed     = remaining_effort_minutes / remaining_days
historical_daily_rate = total completed effort (minutes) over past N days / N
                        (N = min(days since goal created, 7))
```

These conditions mean the user objectively cannot catch up at their current pace.
The Coordinator must surface a decision prompt — the user cannot ignore it.

User choices and outcomes:

| Choice | What happens |
|---|---|
| Extend deadline | Goal Agent updates `deadline`, recomputes urgency, Coordinator replans |
| Reduce scope | Goal Agent marks low-priority sub_tasks as `ABANDONED`, Coordinator replans |
| Snooze 24 h | Coordinator sets a `replan_snoozed_until` timestamp; Level 2 suppressed until then |
| Keep as-is (no snooze) | No change; Level 2 re-triggers the next day |

**Snooze implementation note (decided: field on Goal document):**
Add `replan_snoozed_until: datetime | null` directly to the Goal schema (`domain.py`).
Before firing a Level 2 prompt, check `replan_snoozed_until > now()`. If snoozed, skip.
When user picks "Snooze 24 h", set `replan_snoozed_until = now() + 24h`.
When user picks any other option, clear the field to `null`.

**Implementation note — `historical_daily_rate`:**
This metric does not exist yet in the Goal schema or any tool. It needs to be computed
from `event_log` entries of type `subtask_completed` and their `completed_at` timestamps.
A new tool function `compute_daily_rate(db, goal_id, window_days=7) -> float` is needed
in `Goal_Tracking_Agent/app/tools/`.

### What needs to be built

| Component | Location | Notes |
|---|---|---|
| Level 1/2 classifier | `Coordinator` or `Goal_Tracking_Agent/app/tools/` | Reads event_log + goal fields |
| `compute_daily_rate()` | `Goal_Tracking_Agent/app/tools/progress_calc.py` | New function |
| Soft-reminder signal to Schedule Agent | `scheduled_routes.py` daily-output response | Add `soft_reminder: bool` flag to `GoalsOutput` |
| Forced replan prompt (Level 2) | Coordinator conversation flow | Asks user; collects choice |
| Deadline/scope update endpoints | `goal_routes.py` | May already exist — check |

---

## Status summary

| # | Item | Status |
|---|---|---|
| 1 | `OverdueTaskRef` type change | ✅ Resolved — change reverted, `start_time: datetime` kept per PRD §11 Q3 |
| 2 | End-of-day checklist — full chain design | ✅ Design complete |
| 2-1 | `replan_requested_at` field on `Goal` schema | ⬜ Not started |
| 2-2 | `compute_daily_rate()` in `progress_calc.py` | ⬜ Not started |
| 2-3 | `POST /v1/scheduled/end-of-day` endpoint | ⬜ Not started |
| 2-4 | `replan_pending` on `GoalsOutput` + `_goal_to_goals_output()` | ⬜ Not started |
| 2-5 | `track_goals()` HTTP fix + parse `replan_pending` | ⬜ Not started (same as 4B) |
| 2-6 | Coordinator instruction: route on `replan_pending` | ⬜ Not started |
| 2-7 | Frontend midnight cron → `POST /v1/scheduled/end-of-day` | ⬜ Not started (frontend) |
| 3 | `handle_overdue` rescheduling | 🔶 Deferred — rescheduling now handled by §2-3 endpoint; `handle_overdue` remains a log-only receiver |
| 4A | Remove `upsert_goal_state` / `get_goal_state` from `MemoryAgent` | ⬜ Not started |
| 4B | `track_goals()` → real HTTP call + return `replan_pending` | ⬜ Not started (same as 2-5) |
| 4C | Add `goal_agent_url` to `config.py` | ⬜ Not started |
| 4B-1 | `compute_daily_rate()` in `progress_calc.py` | ⬜ Not started — implementation spec in §4B |
| 4B-2 | `replan_goal` endpoint: clear `replan_requested_at` after replan | ⬜ Not started — spec in §4B |
| 4B-3 | `POST /v1/goals/{id}/reduce-scope` new endpoint | ⬜ Not started — spec in §4B; decision needed on `abandoned` flag |
| 4B-4 | `SubTask` schema: add `abandoned: bool = False`; update both progress_percent functions | ⬜ Not started — decision confirmed: excluded from numerator AND denominator |
| 4B-5 | Goal Agent overdue handler: add replan/reduce-scope/clear tools | ⬜ Not started — spec in §4B |
| 4B-6 | `agents/goal/prompts/overdue.md`: update for 4-choice replan flow | ⬜ Not started |
| 5A | Level 2 forced replan prompt + user choice (Goal Agent) | ⬜ Not started — design complete in §2 + §4B |
| 5B | Level 1 streak tracking (3-day rolling window via event_log) | ⬜ Not started — future enhancement after Level 2 works |
| 5C | `compute_daily_rate()` | ⬜ Not started (same as 4B-1) |
| 5D | `replan_snoozed_until` field + snooze logic | ⬜ Not started — needed for Goal Agent "Snooze 24h" option |
