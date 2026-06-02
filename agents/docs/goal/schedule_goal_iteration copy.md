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

## 2. End-of-day checklist trigger — DESIGN IN PROGRESS

### Trigger source decision

**The end-of-day checklist is frontend-triggered, not Cloud Scheduler-triggered.**

The original plan (Cloud Scheduler → backend endpoint) is dropped. Rationale:
- The checklist is a user-facing interaction; the frontend already owns the session.
- Timing is user-dependent (not everyone wraps up at exactly 11 PM).
- Letting the frontend initiate avoids push-notification infrastructure complexity.

The Cloud Scheduler approach remains valid for silent background jobs (e.g. `daily-output`,
`weekly-memory`) but is **not** the right model for an interactive checklist.

### What the checklist flow looks like (high level)

```
Frontend detects end-of-day (user closes app / taps "end my day" / time threshold)
  → Frontend calls backend: "give me today's incomplete tasks"
  → Backend queries subtasks where planned_date == today AND is_completed == False
  → Frontend renders checklist to user: "Did you complete these?"
  → User taps done/not done per item
  → Frontend sends results back to backend:
      completed items  → POST /v1/events/subtask-completed
      skipped items    → POST /v1/events/overdue  (OverdueNotification)
```

### What still needs to be designed

The full data propagation chain — from frontend trigger through backend, Goal Agent, and
back to Schedule Agent for next-day planning — has not yet been fully specified. The
following questions must be answered before any backend API can be finalised:

1. **Frontend trigger**: What event causes the frontend to start the checklist?
   (explicit button, time-based prompt, app close hook?)
2. **Backend query endpoint**: The frontend needs an endpoint to fetch today's incomplete
   subtasks per user. Does this live at `GET /v1/goals/incomplete-today` or is it an
   extension of `/v1/scheduled/daily-output`?
3. **Agent routing after results**: After the user responds, which agent decides whether
   to silently carry tasks forward vs. trigger a Goal Agent replan? (See §5 for the
   decision tree — that logic still applies, it just now has a frontend trigger instead
   of a Cloud Scheduler trigger.)
4. **Schedule Agent input**: How do confirmed-incomplete subtasks get fed into the next
   `plan_schedule` call? Does Coordinator pass them as additional `goal_context`, or
   does the Goal Agent update the subtask list first?

**Implementation is blocked pending answers to the above. §5 (replan decision tree) is
not blocked — it can be designed independently once the trigger source is settled.**

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
        return {"goal_status": "no_goals", "progress_percent": 0.0, "urgency": "low", "goals": []}

    # Derive aggregate status for the Coordinator
    urgencies = [g["urgency"] for g in goals_output]
    top_urgency = "high" if "high" in urgencies else ("medium" if "medium" in urgencies else "low")
    avg_feasibility = sum(g["feasibility_score"] for g in goals_output) / len(goals_output)

    return {
        "goal_status": "on_track" if avg_feasibility >= 0.6 else "at_risk",
        "progress_percent": round(avg_feasibility * 100, 1),
        "urgency": top_urgency,
        "goals": goals_output,
    }
```

**Step 3 — Add `goal_agent_url` to config**

`config.py`: add `goal_agent_url: str = "http://localhost:8001"` (or the Cloud Run URL in prod).

### What this fixes

After this change, `plan_schedule()` receives real goal urgency, feasibility, and today's
subtask list from the Goal Tracking Agent, so generated schedules are actually informed by
goal progress.

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
| 2 | End-of-day checklist trigger | 🔶 Design in progress — frontend-triggered; full data chain TBD |
| 3 | `handle_overdue` rescheduling | 🔶 Deferred — blocked on §2 data chain design |
| 4A | Remove `upsert_goal_state` / `get_goal_state` from `MemoryAgent` | ⬜ Not started |
| 4B | `track_goals()` → real HTTP call to `/v1/scheduled/daily-output` | ⬜ Not started |
| 4C | Add `goal_agent_url` to `config.py` | ⬜ Not started |
| 5A | End-of-day replan decision tree (Coordinator logic) | ⬜ Not started — can be designed once §2 trigger is settled |
| 5B | Level 1 streak tracking via event_log query | ⬜ Not started |
| 5C | `compute_daily_rate()` tool function | ⬜ Not started |
| 5D | Level 2 forced replan prompt + user choice handling | ⬜ Not started |
| 5E | `replan_snoozed_until` field on Goal schema + snooze logic | ⬜ Not started |
