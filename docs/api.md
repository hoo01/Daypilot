# DayPilot API Reference

Base URL: `http://localhost:8000`

---

## Chat

### POST /chat/

Main chat endpoint. Each turn is classified (plan / adjust / confirm / discard / reschedule
missed tasks / chat). Schedule turns are executed by code (`DayPlanService`) and the reply is
rendered from the resulting state; everything else goes to the read-only conversational agent,
which never changes the schedule.

**Request**
```json
{
  "user_id": "demo_user",
  "message": "Good morning",
  "session_id": "optional-uuid-to-continue-session"
}
```

**Response**
```json
{
  "reply": "Here are 3 options for today: Most Productive, Most Relaxed, Fastest. I'd go with **Most Productive** ...",
  "session_id": "uuid",
  "day_plan": { /* DayPlan — see below; the only thing the UI renders schedules from */ },
  "error": null
}
```

`error` is `null` or `{"code", "message"}` with `code` one of:

| code | meaning | state |
|---|---|---|
| `invalid_transition` | the request doesn't fit the current state (e.g. "confirm" with no proposal, "adjust" with no confirmed plan, planning a past day) | unchanged |
| `concurrent_modification` | the plan changed while a proposal was pending (e.g. stale adjustment) | unchanged |
| `generation_failed` | the schedule generator produced no valid schedule after one retry | unchanged — no fallback schedule is written |

`day_plan` is the DayPlan the turn acted on (today's for chat turns; tomorrow's when planning
tomorrow or rescheduling missed tasks).

### DayPlan

One per `user_id + date`. `status` is derived: `EMPTY` (nothing), `PROPOSED` (proposal only),
`CONFIRMED` (active only), `CONFIRMED_WITH_PROPOSAL` (both). A proposal never changes
`active` until it is confirmed. Adjust proposals (`kind: "adjust"`) have a single strategy
named `"Adjusted"` and the explanation of what changed.

```json
{
  "user_id": "demo_user",
  "date": "2026-06-02",
  "active": {
    "strategy_name": "Most Relaxed",
    "tasks": [
      { "task_id": "most-relaxed-1", "title": "Reading", "start_time": "2026-06-02T10:00:00",
        "end_time": "2026-06-02T11:00:00", "type": "personal", "location": null, "notes": null }
    ],
    "confirmed_at": "2026-06-02T08:15:02"
  },
  "proposal": {
    "proposal_id": "3f0c…",
    "kind": "plan",
    "strategies": [ { "name": "Most Productive", "description": "...", "tasks": [...],
                      "total_focus_hours": 4.5, "reasoning": "..." } ],
    "top_recommendation": "Most Productive",
    "explanation": "",
    "based_on_version": null,
    "consumes_pending_reschedule": false,
    "created_at": "2026-06-02T09:40:11"
  },
  "version": 3,
  "status": "CONFIRMED_WITH_PROPOSAL"
}
```

---

## Schedule

### GET /schedule/day?user_id=xxx&date=YYYY-MM-DD

Returns the full DayPlan (`date` defaults to the server's today). Always 200; a day with
nothing stored returns `status: "EMPTY"`.

### GET /schedule/today?user_id=xxx

Returns today's **confirmed** tasks (`active.tasks`), each enriched with `geo_segment`
(origin → destination commute info, or `null`). 404 if nothing is confirmed for today —
an unconfirmed proposal is not a schedule.

```json
{ "tasks": [ { "task_id": "...", "title": "...", "start_time": "...", "end_time": "...",
                "type": "...", "location": "...", "geo_segment": null } ] }
```

### POST /schedule/confirm

Confirms one strategy of the **stored** proposal. The tasks are always taken from the server's
copy of the proposal; any tasks sent by the client are ignored.

**Request**
```json
{ "user_id": "demo_user", "date": "2026-06-02", "proposal_id": "3f0c…", "strategy_name": "Most Relaxed" }
```
`strategy_name` may be `null` to accept the recommended option.

**Response 200**
```json
{ "status": "confirmed", "day_plan": { /* DayPlan with the new active plan, proposal null */ } }
```

**Response 409** — `detail: {"code", "reason", "message"}`, e.g. `invalid_transition`
(no proposal / `proposal_outdated` / `unknown_strategy`) or `concurrent_modification`.
Nothing is written.

### POST /schedule/feedback

Submit end-of-day task completion feedback. Used by the checkbox UI to report uncompleted tasks.

**Request**
```json
{
  "user_id": "demo_user",
  "date": "2026-06-02",
  "uncompleted_tasks": [
    {
      "title": "Leetcode Practice",
      "scheduled_time": "2026-06-02T21:00:00"
    },
    {
      "title": "Study Session",
      "scheduled_time": "2026-06-02T14:00:00"
    }
  ]
}
```

**Response**
```json
{
  "message": "Got it! You didn't complete 2 tasks today. Want me to reschedule them?",
  "uncompleted": ["Leetcode Practice", "Study Session"],
  "suggested_reschedule_date": "2026-06-03"
}
```

### POST /schedule/adjust

Stateless adjustment preview: runs the adjustment generator on the schedule you send and returns the result. **Nothing is persisted** — to change the user's plan, say it in `/chat/` (e.g. "my 3pm meeting moved to 5"), which proposes an adjustment of the stored plan.

**Request**
```json
{
  "user_id": "demo_user",
  "current_schedule": [...],
  "trigger": "task_overrun",
  "trigger_detail": "Leetcode session ran 30 minutes over"
}
```

**Response**
```json
{
  "what_changed": ["Leetcode session ran over by 30 minutes"],
  "dropped_tasks": ["Optional reading"],
  "added_tasks": [],
  "updated_schedule": [...],
  "message": "Shifted your evening blocks by 30 minutes."
}
```

---

## Auth / Ingestion

### GET /auth/google?user_id=xxx

Returns Google OAuth URL. Redirect the user to this URL to authorize Calendar, Gmail, and Contacts access.

**Response**
```json
{
  "auth_url": "https://accounts.google.com/o/oauth2/auth?..."
}
```

### GET /auth/callback

OAuth callback — handled automatically by Google redirect. Triggers cold-start ingestion after login.

### POST /auth/ingest/{user_id}

Re-run data ingestion for a user using stored credentials.

---

## Health

### GET /health

```json
{ "status": "ok" }
```

---

## Notes for Frontend

- All `user_id` values must match across requests to maintain session context
- `session_id` in `/chat/` is optional on first message; pass it back on subsequent messages to continue the conversation
- `/schedule/feedback` should be called once at end of day when user submits the checkbox form
- Dates and times are ISO 8601 format (`2026-06-02T21:00:00`)
- Render proposals and schedules from `day_plan` only; to confirm, send `proposal_id` + `strategy_name` from it