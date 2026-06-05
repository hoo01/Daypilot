# DayPilot Frontend Design Document

> Logic-layer design document — pages, routing, data flow, API integration, state management
> Version: 0.3 | Last updated: 2026-06-05

---

## Tech Stack

| Item | Choice |
|------|--------|
| Framework | React + Vite |
| Routing | React Router v6 |
| Styling | Tailwind CSS |
| Global state | Zustand |
| HTTP requests | fetch API (native, no axios needed) |
| Local persistence | localStorage |

---

## Pages

4 pages total. Page 4 is a second-phase feature.

### `/auth` — Login / Authorization

- Shown when the app cold-starts and no `user_id` exists in localStorage
- Single entry point: Google OAuth button
- On click: call `GET /auth/google?user_id=xxx`, then `window.location.href = response.auth_url`
- After OAuth completes, Google redirects to backend `/auth/callback`, which then redirects to frontend `/today`
- **Pending with backend**: confirm the exact redirect URL (e.g. `http://localhost:5173/today` for local dev)

### `/today` — Today's Schedule (main page)

- Default landing page when `user_id` exists
- Layout:
  - Top: current date + schedule summary (from the `reply` field of the first `/chat/` call)
  - Body: task card list, sorted ascending by `scheduled_time`
  - Bottom: fixed "Submit today's progress" button
- Task card behavior detailed in the Task Card Interaction section below

### `/chat` — AI Chat

- Standard chat interface for conversing with the coordinator agent
- Message bubble stream + fixed input bar at the bottom
- `session_id` is stored in localStorage and sent with every request to maintain session continuity
- Can be entered from the feedback toast on `/today`

### `/history` — History / Feedback (phase 2)

- Shows completion history and agent adjustment logs for past days
- Not built in phase 1 — route reserved

---

## Routing and Navigation Logic

```
App cold start
  └─ user_id in localStorage?
       ├─ Yes → /today
       └─ No  → /auth

/auth
  └─ User clicks authorize
       └─ GET /auth/google → window.location.href = auth_url
            └─ OAuth completes → backend redirect → /today (store user_id here)

/today submit button
  └─ POST /schedule/feedback
       └─ Show response.message as toast
            └─ Toast includes "Ask in chat" shortcut → /chat

/chat user reports a new event ("I have a meeting at 10am")
  └─ POST /chat/
       └─ coordinator agent detects conflict, calls /schedule/adjust internally
            └─ response includes schedule_updated: true
                 └─ frontend re-fetches GET /schedule/today → refresh task list in-place
```

---

## Task Card Interaction

### Standard task card

- Displays: checkbox + task title + scheduled time
- Checkbox state is stored locally and not reported in real time — collected on final submit

### Task card with geo_segment

- Shows a map pin icon on the right to indicate travel info is available
- Clicking the card expands the geo panel; clicking again collapses it
- Geo panel contents:
  - Origin → Destination (from `geo_segment.origin` / `geo_segment.destination`)
  - Estimated travel time (from `geo_segment.duration_text`, displayed as-is)
  - "Navigate" button: `window.open(geo_segment.maps_url, '_blank')`

### Expand/collapse implementation (React)

```jsx
const [isExpanded, setIsExpanded] = useState(false)

{task.geo_segment && (
  <div onClick={() => setIsExpanded(!isExpanded)}>
    {/* card body */}
    {isExpanded && (
      <div className="geo-panel">
        <span>{task.geo_segment.origin} → {task.geo_segment.destination}</span>
        <span>{task.geo_segment.duration_text}</span>
        <a href={task.geo_segment.maps_url} target="_blank" rel="noreferrer">Navigate</a>
      </div>
    )}
  </div>
)}
```

---

## API Integration

Base URL: `http://localhost:8000`

### GET `/auth/google?user_id=xxx`
- Page: `/auth`
- Purpose: get the Google OAuth authorization URL
- Frontend behavior: `window.location.href = response.auth_url`

### GET `/auth/callback`
- Page: `/auth`
- Purpose: OAuth callback, triggered automatically by Google redirect, handled by backend
- Backend behavior: exchanges token, stores credentials, triggers cold-start ingestion, then redirects to `http://localhost:5173/today?user_id=xxx`
- Frontend behavior: on landing at `/today`, read `user_id` from URL params and store in localStorage, then strip the param from the URL
- The callback response body (`{"status":"ok","source":"cold_start","entities_ingested":2}`) is backend-internal — frontend does not consume it

### GET `/schedule/today?user_id=xxx` ⬅ new endpoint, backend needs to implement
- Page: `/today`
- Purpose: fetch today's task list on page load
- Expected response shape:
```json
{
  "date": "2026-06-05",
  "tasks": [
    {
      "id": "uuid",
      "title": "Go to the gym",
      "scheduled_time": "2026-06-05T15:00:00",
      "duration_minutes": 90,
      "geo_segment": {
        "origin": "USC Viterbi",
        "destination": "LA Fitness Downtown",
        "duration_text": "18 min drive",
        "maps_url": "https://www.google.com/maps/dir/?api=1&origin=...&destination=..."
      }
    },
    {
      "id": "uuid",
      "title": "Leetcode practice",
      "scheduled_time": "2026-06-05T21:00:00",
      "duration_minutes": 60,
      "geo_segment": null
    }
  ]
}
```

### POST `/chat/`
- Pages: `/today` (initial summary call), `/chat` (ongoing conversation)
- Request: `{ user_id, message, session_id? }`
- Response: `{ reply, session_id }`
- `/today` usage: send once on page load (e.g. "Good morning"), display `reply` as the top summary
- `/chat` usage: continuous conversation; store `session_id` in localStorage and include in every request

### POST `/schedule/feedback`
- Page: `/today`
- Trigger: user clicks the "Submit today's progress" button
- Frontend logic: iterate task list, filter unchecked tasks, build `uncompleted_tasks` array
- Request body:
```json
{
  "user_id": "demo_user",
  "date": "2026-06-05",
  "uncompleted_tasks": [
    { "title": "Leetcode Practice", "scheduled_time": "2026-06-05T21:00:00" }
  ]
}
```
- Response behavior:
  - Display `message` as a toast
  - Display `suggested_reschedule_date` in a confirmation dialog
  - Toast includes an "Ask in chat" shortcut button → `/chat`

### POST `/schedule/adjust`
- **Backend-internal only — frontend does not call this endpoint directly**
- Triggered internally by the coordinator agent when the user reports a new event or conflict via `/chat/`
- The agent detects the conflict (e.g. "I have a meeting at 10am"), replans internally, then returns `schedule_updated: true` in the `/chat/` response
- Frontend behavior on receiving `schedule_updated: true` from `/chat/`: re-fetch `GET /schedule/today` and refresh the task list in-place
- **Pending with backend**: confirm that `/chat/` response includes a `schedule_updated` flag when a replan occurs

### GET `/health`
- Page: global
- Trigger: called once on app startup
- If `status !== "ok"`, show a global banner indicating backend is unavailable

---

## State Management

### localStorage

| Key | Type | Description |
|-----|------|-------------|
| `user_id` | string | User identifier, written after OAuth completes |
| `session_id` | string | Chat session ID, written after first message, included in all subsequent requests |
| `today_schedule` | JSON array | Today's task list, written by `/schedule/today`, updated by `/schedule/adjust` |
| `last_feedback_date` | string | Date of last feedback submission, used to prevent duplicate submits |

### Zustand store (runtime state)

```js
{
  tasks: [],            // today's task list
  chatMessages: [],     // chat history (runtime only, not persisted)
  isBackendDown: false  // result of /health check
}
```

---

## Open Issues

| Status | Issue |
|--------|-------|
| ✅ Decided | `GET /schedule/today` — Solution A, backend to implement |
| ✅ Decided | Geo segment display — maps_url jump button, shown in expanded task card panel |
| ⏳ Pending | `geo_segment` field schema needs backend confirmation; must be included in each task object returned by `/schedule/today` |
| ✅ Decided | OAuth callback redirects to `http://localhost:5173/today?user_id=xxx`; frontend reads param on landing and stores in localStorage |
| ✅ Decided | `/schedule/adjust` is backend-internal only. Triggered by coordinator agent via `/chat/`. Frontend re-fetches `/schedule/today` when `/chat/` response includes `schedule_updated: true` |
| ⏳ Pending | Confirm that `/chat/` response includes a `schedule_updated: true` flag when a replan occurs |
