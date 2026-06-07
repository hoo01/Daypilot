# DayPilot – Frontend Branch Handover

> Branch: `frontend` | Last updated: 2026-06-08 | Author: Wanrong

---

## 1. Branch Setup — Start Here

The `frontend` branch has been merged with the latest `main`. **All team members should work off `frontend`.**

To test the app without going through full Google OAuth, paste this into the browser DevTools console:
```js
localStorage.setItem('user_id', '"dev_user"')
```
Then navigate to `http://localhost:5173/today`.

---

## 2. What Changed on This Branch

### 2.1 Auth — Google OAuth (Two-Factor)

- Login now requires Google OAuth two-factor authorization.
- Use the DevTools shortcut above to bypass during local development/testing.

### 2.2 Async Refactor — Faster Agent Responses (@Yuqing)

- All synchronous Gemini SDK calls replaced with fully async calls (`await client.aio.models.generate_content(...)`).
- `asyncio.gather` now runs tool preloads in true parallel (previously they were serialized due to sync blocking).
- `relationship_tools.py` now caches results for 30 minutes (upcoming events don't change mid-session).
- `health_tools.py` caches results for 10 minutes.
- Switched `relationship_model` and `goal_model` to `gemini-2.5-flash-lite` (~2s vs ~15s).
- `thinking_budget=0` applied across all agents and tools to disable extended thinking.
- Result: latency reduced from ~30s+ to ~5–15s per turn.
- **Still slow — further optimization is welcome.** Check `docs/问题记录.md` for the full diagnosis and `docs/progress.md` for per-file changes.

### 2.3 Frontend Visual Redesign

- Redesigned in a **dark theme + high-saturation highlight** style.
- Layout restructured to better highlight **scheduling** and **AI-native** features (discussed in team meeting).
- Visual fine-tuning is still ongoing — not final.
- **To make further UI adjustments, use the `/impeccable` skill in Claude Code — it is significantly more efficient for frontend iteration.**

### 2.4 Layout Fixes

- `Shell.jsx`: `width: 100vw` → `width: 100%` (prevents scrollbar overflow); padding/header compacted for 100% browser zoom.
- `TodayPage.jsx`: compose bar no longer pushed off-screen when many task cards are added; right sidebar narrowed from 340px → 280px.
- `NavRail.jsx`: width 84px → 72px.
- Markdown rendering added to `ChatPage.jsx` and `AgentDrawer.jsx` (agent messages now render `**bold**`, bullet lists, headers, etc.).

### 2.5 Auth — HTTP Proxy Fix

- `agents/ingestion.py` previously had a **hardcoded proxy IP address**.
- It now reads from environment variables (`HTTP_PROXY`, `HTTPS_PROXY`, `https_proxy`) in order.
- **Action required:** Add `HTTP_PROXY=http://127.0.0.1:<your_port>` to your `.env` file if you are behind a proxy (e.g., in China). See `.env.example` for the full variable list.

---

## 3. Known Issues & Bugs

### 3.1 Gemini Error → Wrong Schedule Returned (@Jingyuan — Backend)

- **Symptom:** When Gemini returns an error response, the frontend always displays a fallback schedule of `9pm–11pm deep work block` regardless of actual user data.
- **How to reproduce:** Send a chat message; if this block appears, there is a Gemini error on the backend.
- **Debug:** Check the backend server error output. The root cause is a Gemini API error propagating silently — the backend should return a proper error response instead of a fallback schedule.

### 3.2 Geo Agent Navigation — Pending Test

- The geo agent is supposed to redirect the user to a specified map page.
- **Status: Not yet tested end-to-end.** Needs verification that clicking "Navigate" in the geo panel launches the correct Google Maps URL.

---

## 4. Pending Backend Items (from `docs/frontend_api_design.md`)

These two items are **agreed on design but not yet confirmed as implemented** — backend needs to verify:

| # | Item | Detail |
|---|------|--------|
| 1 | `GET /schedule/today` response — `geo_segment` field | The `geo_segment` object must be included in each task object. Schema: `{ origin, destination, duration_text, maps_url }`. Null if no travel needed. Backend must confirm this is included. |
| 2 | `POST /chat/` response — `schedule_updated` flag | When the coordinator agent replans the schedule (e.g., user reports a new event), the `/chat/` response must include `"schedule_updated": true`. Frontend uses this flag to re-fetch `/schedule/today` and refresh the task list. Backend must confirm this flag is emitted. |

---

## 5. Individual Action Items

### @Yuqing
- Review and validate the new async logic in `agents/tools/` and `api/routes/chat.py`.
- Response time is still 5–15s on cold start. Further optimization ideas: streaming responses, more aggressive caching, or reducing rounds of LLM calls.

### @Jingyuan
- Fix the Gemini error → fallback schedule bug (see 3.1 above).
- Confirm `GET /schedule/today` includes `geo_segment` in each task object.
- Confirm `POST /chat/` emits `schedule_updated: true` when a replan occurs.
- Test geo agent navigation end-to-end (see 3.2 above).

### @Vatsal
- Dynatrace monitoring is now running on the updated system (async backend + new frontend).
- Profile the new request flow and identify any remaining bottlenecks.
- If findings suggest code-level changes, go ahead and apply them **as long as they don't conflict with other teammates' logic**.

### @Everyone
- Pull `frontend` branch and run the full app locally.
- Test your own agent end-to-end: correct backend status codes, correct chat behavior, correct data display on the frontend.
- If you see the `9pm–11pm deep work` fallback, it's a Gemini backend error — report the server log output.

---

## 6. How to Run

**Backend:**
```bash
pip install -r requirements.txt
python scripts/seed_demo.py   # seed demo data (run once)
python main.py                # starts at http://localhost:8000
```

**Frontend:**
```bash
cd frontend
npm install
npm run dev                   # starts at http://localhost:5173
```

**Quick test (no OAuth):**
```js
// In browser DevTools console:
localStorage.setItem('user_id', '"dev_user"')
// Then navigate to http://localhost:5173/today
```

---

## 7. Environment Variables

Copy `.env.example` → `.env` and fill in all values. Key additions vs. the original:

| Variable | Notes |
|----------|-------|
| `HTTP_PROXY` | Add this if you need a proxy to reach Google APIs (e.g., in China). Format: `http://127.0.0.1:7897` |
| `DT_ENVIRONMENT`, `DT_API_TOKEN`, etc. | Dynatrace variables — see `docs/DYNATRACE.md` |

Contact Yuqing for `GEMINI_API_KEY`, `MONGODB_URI`, and Google OAuth credentials.

---

## 8. Reference Docs

| File | Purpose |
|------|---------|
| `docs/frontend_api_design.md` | Full API contract between frontend and backend |
| `docs/progress.md` | Detailed per-file changelog for the 2026-06-07 session |
| `docs/问题记录.md` | Root cause analysis for chat latency fix |
| `docs/handoff.md` | Original backend handoff |
| `docs/DYNATRACE.md` | Dynatrace setup and observability guide |
| `docs/api.md` | Backend API reference |
