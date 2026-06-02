# DayPilot API Reference

Base URL: `http://localhost:8000`

---

## Chat

### POST /chat/

Main chat endpoint. All user messages go through the coordinator agent.

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
  "reply": "You have 4 Leetcode problems left this week...",
  "session_id": "uuid"
}
```

---

## Schedule

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

Real-time schedule adjustment when something changes mid-day.

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