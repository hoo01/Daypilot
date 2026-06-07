# DayPilot — Dev Progress Log

*Branch: `frontend` · Last updated: 2026-06-07*

---

## Session Summary: Backend Connectivity + Auth Flow Fixes

All changes are uncommitted on the `frontend` branch (`git diff HEAD`).

---

## 1. Root Cause: httpx 0.28 Bug (ConnectError)

**Problem:** Every call to `client.models.generate_content(...)` (the synchronous genai API) creates its own internal `httpx.Client` with `trust_env=True` + a custom `ssl.SSLContext`. With `HTTPS_PROXY` set in the shell, this combination triggers an httpx 0.28 bug → `ConnectError: [Errno 54] Connection reset by peer`. The `httpx_async_client` we configure is only used by `client.aio.models.*` async calls.

**Fix:** Switched all 7 sync `generate_content` call sites to the async API (`client.aio.models.generate_content`). Also removed all `loop.run_in_executor` wrappers that were wrapping sync calls inside async functions.

---

## 2. Files Changed

### `main.py` (new)
- Added `has_aiohttp = False` patch to force google-genai to use httpx instead of aiohttp (aiohttp has TLS-in-TLS issues on Python 3.13 through HTTP CONNECT proxy)
- Patched `_GoogleLLM.api_client` via `cached_property` to inject the shared httpx client into ADK's Gemini model, bypassing the httpx 0.28 bug for ADK-internal calls
- Called `_prop.__set_name__(_GoogleLLM, "api_client")` to satisfy `cached_property`'s requirement

### `http_client.py` (new file)
- Process-wide singleton `httpx.AsyncClient` with `proxy=HTTPS_PROXY` (explicit arg, not `trust_env`) and `trust_env=False`
- All genai clients share this instance via `shared_async_client()`
- `close()` called in FastAPI lifespan teardown

### `agents/base.py`
- Added `ThinkingConfig(thinking_budget=0)` to disable thinking mode (linter addition)
- Added `gemini_api_version` setting reference
- **Changed** `_client.models.generate_content(...)` → `await _client.aio.models.generate_content(...)` (sync → async fix)

### `agents/tools/schedule_tools.py`
- Removed `import asyncio` (no longer needed)
- **Changed** `loop.run_in_executor(None, lambda: _genai_client.models.generate_content(...))` → `await _genai_client.aio.models.generate_content(...)` (sync → async fix)
- Added `_persist_schedule()` — saves the top-recommended strategy's tasks to `daily_schedules` MongoDB collection after planning

### `agents/tools/realtime_tools.py`
- Moved client creation from inside the function to module level
- **Changed** `client.models.generate_content(...)` → `await _client.aio.models.generate_content(...)` (sync → async fix)
- Added `ThinkingConfig(thinking_budget=0)`

### `agents/tools/relationship_tools.py`
- Added module-level shared client with `httpx_async_client`
- **Changed** inline `genai.Client(api_key=...)` + sync call → `await _client.aio.models.generate_content(...)` (sync → async fix)
- Added `ThinkingConfig(thinking_budget=0)`

### `agents/tools/goal_tools.py`
- Same changes as `relationship_tools.py`

### `agents/ingestion.py`
- Added shared genai client with `httpx_async_client`
- **Changed** `loop.run_in_executor(None, lambda: _genai_client.models.generate_content(...))` → `await _genai_client.aio.models.generate_content(...)` (sync → async fix)
- **Fixed `_build_authorized_http`**: Was hardcoded to `127.0.0.1:7897` (China-only proxy). Now reads `HTTPS_PROXY` / `HTTP_PROXY` env var and parses host+port dynamically. Falls back to no proxy (direct connection) if env var is unset — required for non-China machines.

### `api/routes/chat.py`
- Removed `import asyncio` (no longer needed)
- **Changed** `loop.run_in_executor(None, lambda: _genai_client.models.generate_content(...))` → `await _genai_client.aio.models.generate_content(...)` in `_consolidate_memory`
- Added `ThinkingConfig(thinking_budget=0)` for the memory consolidation call
- Removed `break` from `async for event in runner.run_async(...)` — breaking early injected `GeneratorExit` into ADK's async generator, corrupting OpenTelemetry span context and causing `ValueError: Token was created in a different Context`

### `api/routes/schedule.py`
- Added `GET /schedule/today?user_id=` endpoint — returns today's persisted tasks from `daily_schedules` collection, 404 if none exist

### `api/routes/auth.py`
- **Fixed OAuth callback**: Was returning JSON `{"status": "ok", ...}`. Now returns `RedirectResponse` to `{frontend_url}/today?user_id={user_id}` so the browser lands back in the app after Google OAuth
- Ingestion now runs via `asyncio.create_task(...)` (background) so the redirect is instant, not blocked by ingestion

### `config.py`
- Added `gemini_api_version: str = "v1"`
- Added `frontend_url: str = "http://localhost:5173"` (Vite dev server URL, used for OAuth redirect)
- Added `https_proxy: str = ""`
- Consolidated model names (removed preview/pro variants — all use `gemini-2.5-flash`)

### `db/collections.py`
- Added `DAILY_SCHEDULES = "daily_schedules"`

### `db/indexes.py`
- Added unique index on `(user_id, date)` for `daily_schedules` collection

### `api/app.py`
- Added `await http_client.close()` in FastAPI lifespan teardown

### `frontend/package.json`
- Added `NO_PROXY=localhost,127.0.0.1,::1 no_proxy=localhost,127.0.0.1,::1` to `dev` script — prevents Node.js from routing Vite's local proxy through the system HTTP proxy

### `frontend/src/components/NavRail.jsx`
- Replaced the non-functional ⚙ settings stub with a ⏻ sign-out button
- Sign-out calls `storage.clear()` and navigates to `/auth` — required to test the full auth flow from scratch

### `frontend/src/pages/TodayPage.jsx`
- Added `noSchedule` state
- 404 from `GET /schedule/today` now sets `noSchedule=true` and shows a "No schedule for today yet" empty state with a "Plan my day" CTA button — previously fell back silently to mock tasks with no indication
- Other errors (network etc.) still fall back to mock tasks

### `frontend/src/utils/api.js`
- Added `error.status = res.status` to thrown errors — allows TodayPage to distinguish 404 from other failures by checking `err.status === 404`

---

## 3. Auth Flow (End-to-End)

The correct flow after all fixes:

1. User visits app → no `user_id` in localStorage → `/auth` page shown
2. User clicks "Continue with Google" → frontend generates `userId`, saves to localStorage, calls `GET /api/auth/google?user_id=...` → backend returns `auth_url`
3. Browser redirects to Google OAuth
4. User grants permission → Google redirects to `http://localhost:8000/auth/callback?code=...&state={user_id}`
5. Backend: exchanges code for tokens → stores credentials in MongoDB → fires ingestion as background task → **redirects browser to `http://localhost:5173/today?user_id={user_id}`**
6. TodayPage loads, detects `?user_id=` param, confirms userId in localStorage
7. TodayPage fetches `GET /schedule/today` → 404 (no schedule yet) → shows "No schedule for today yet" state
8. User opens chat drawer → chats with agent → coordinator calls `plan_schedule` → schedule saved to `daily_schedules` → TodayPage refresh shows real tasks

---

## 4. Known Prerequisites

- **`.env` must have OAuth credentials set:**
  ```
  GOOGLE_CLIENT_ID=...apps.googleusercontent.com
  GOOGLE_CLIENT_SECRET=...
  GOOGLE_REDIRECT_URI=http://localhost:8000/auth/callback
  ```
  Without these, Google rejects the OAuth request with `invalid_request: Missing required parameter` (shows as `ERR_CONNECTION_RESET` in China because GFW blocks Google's error page).

- **Google Cloud Console** must have:
  - `http://localhost:8000/auth/callback` in Authorized Redirect URIs
  - Google Calendar API, Gmail API, People API enabled
  - Your Google account added as a test user (while app is in Testing status)

- **VPN must be in Global mode** in China to route browser traffic through it. Python API calls work because `HTTPS_PROXY` env var is set; browser traffic requires the VPN to act as a system proxy.

---

## 5. Still To Test

- [ ] Full OAuth flow end-to-end (blocked by OAuth credentials in `.env`)
- [ ] `plan_schedule` → tasks appear in TodayPage after chat
- [ ] `adjust_schedule` real-time replanning
- [ ] End-of-day feedback → goal state update → reschedule next turn
