# DayPilot – Change Log (frontend branch)

## Session: 2026-06-07

### 1. Backend – Latency Reduction

**Root cause diagnosed**: Three sequential LLM rounds were running with `gemini-2.5-flash`, which uses adaptive "thinking" (extended internal reasoning) adding 30-45 s per call:
- Round 1 (parallel pre-load): `track_goals` + `get_relationship_context` — **both make LLM calls** before the coordinator even starts
- Round 2: Coordinator LLM
- Round 3: `plan_schedule` tool (another LLM call)
- Compounded total: 60-90 s end-to-end

**Fix – `config.py`**
- All models remain `gemini-2.5-flash` (`gemini-2.0-flash` was retired and returns 404)
- Added `gemini_api_version: str = "v1"` setting (previously hardcoded in `agents/base.py`)
- Speed fix is achieved by setting `thinking_budget=0` on every `generate_content` call (see below)

**Fix – `agents/base.py`**
- Replaced hardcoded `api_version="v1"` with `api_version=settings.gemini_api_version`
- Added `thinking_budget=0` to the `_generate` helper used by all BaseAgent subclasses

**Fix – `agents/coordinator.py`**
- Added `generate_content_config=GenerateContentConfig(thinking_config=ThinkingConfig(thinking_budget=0))` to the ADK `Agent()` constructor — disables thinking for the coordinator's LLM turn

**Fix – `agents/tools/goal_tools.py`, `relationship_tools.py`, `schedule_tools.py`, `realtime_tools.py`**
- Added `thinking_config=ThinkingConfig(thinking_budget=0)` to every `GenerateContentConfig` in each tool's `generate_content` call

**Fix – `agents/ingestion.py`**, **`api/routes/chat.py`**
- Same `thinking_budget=0` applied to memory consolidation and ingestion calls

> **Note**: `gemini-2.0-flash` was retired (returns 404). The correct approach is `gemini-2.5-flash` with `thinking_budget=0`.  
> Model names and API version are configurable via `.env` — the defaults in `config.py` are the fallback values.

---

### 2. Frontend – Markdown Rendering

**Problem**: Chat responses from the LLM contain Markdown (`**bold**`, `* bullets`, `##` headers) that were being displayed as raw plain text.

**Fix – `frontend/package.json`**
- Added `react-markdown` (npm) and `remark-gfm` (npm) via `npm install`
- These are **npm packages**, not Python — they do **not** belong in `requirements.txt`

**Fix – `frontend/src/pages/ChatPage.jsx`**
- Imported `ReactMarkdown` and `remarkGfm`
- Agent messages now rendered through `<ReactMarkdown remarkPlugins={[remarkGfm]}>` with styled component overrides for `p`, `ul`, `ol`, `li`, `strong`, `code`
- User messages stay as plain text (users don't type Markdown)

**Fix – `frontend/src/components/AgentDrawer.jsx`**
- Same Markdown rendering applied to the quick-ask drawer's agent messages

---

### 3. Frontend – TodayPage Layout (Scroll + Compose Bar)

**Problem**: After scheduling (which adds 12-15 task cards), the task list grew to fill all space and pushed the bottom compose bar + submit button below the `overflow: hidden` clip boundary — making them invisible. Scrolling also didn't trigger correctly.

**Root cause**: The header section and bottom section of the left flex column had no `flexShrink: 0` constraint. Under flex pressure from many task cards, the compose bar was squeezed off-screen.

**Fix – `frontend/src/pages/TodayPage.jsx`**
- Added `flexShrink: 0` to the top header `<div>` (date, quote, task list header)
- Added `flexShrink: 0` to the bottom compose/submit `<div>`
- The middle task list (`flex: 1, minHeight: 0, overflowY: auto`) now always gets the bounded remaining height and scrolls correctly
- Added `gridTemplateRows: '1fr'` to TodayPage's grid — makes the single grid row fill the exact container height rather than sizing to content, fixing the height chain for the inner flex layout
- Added `minHeight: 0` to the right sidebar `<aside>` so it can scroll independently

---

### 4. Frontend – Full-Page Layout at 100% Zoom

**Problem**: Content was only fully visible at 80% browser zoom. Root causes:
- `width: 100vw` can exceed the viewport width by the scrollbar width on some OSes
- 20px padding on all sides consumed too much vertical space on shorter screens
- 340px fixed right sidebar was too wide, leaving the main task column cramped
- Topbar chips and tabs were large, using excessive horizontal space

**Fix – `frontend/src/components/Shell.jsx`**
- `width: 100vw` → `width: 100%` (avoids scrollbar-width overflow)
- Outer padding `20px` → `12px`
- Header height `80px` → `64px`, padding made more compact
- Tab pill font/padding reduced
- Date and backend status chips reduced to `font-size: 12px`, `padding: 7px 11px`
- Backend chip simplified: shows a colored dot + "Backend Offline" only when down; just "Backend" when healthy
- Content grid: `gridTemplateRows: '1fr'` added so the grid row fills the exact remaining height
- NavRail column: `84px` → `72px`
- Content area gap: `16px` → `12px`, padding: `0 16px 16px` → `0 12px 12px`

**Fix – `frontend/src/components/NavRail.jsx`**
- Width `84px` → `72px` to match Shell grid column

**Fix – `frontend/src/pages/TodayPage.jsx`**
- Right sidebar: `340px` → `280px` (frees ~120px for the main task column)
- Grid gap: `16px` → `12px`

---

## Files Changed

| File | Change |
|---|---|
| `config.py` | All models stay `gemini-2.5-flash`; added `gemini_api_version` setting |
| `agents/base.py` | `api_version` from config; `thinking_budget=0` on `_generate` |
| `agents/coordinator.py` | `thinking_budget=0` via `generate_content_config` on ADK Agent |
| `agents/tools/goal_tools.py` | `thinking_budget=0` on generate_content call |
| `agents/tools/relationship_tools.py` | `thinking_budget=0` on generate_content call |
| `agents/tools/schedule_tools.py` | `thinking_budget=0` on generate_content call |
| `agents/tools/realtime_tools.py` | `thinking_budget=0` on generate_content call |
| `agents/ingestion.py` | `thinking_budget=0` on generate_content call |
| `api/routes/chat.py` | Removed timeout; `thinking_budget=0` on consolidation call |
| `frontend/package.json` | Added `react-markdown`, `remark-gfm` |
| `frontend/src/pages/ChatPage.jsx` | Markdown rendering for agent messages |
| `frontend/src/components/AgentDrawer.jsx` | Markdown rendering for agent messages |
| `frontend/src/pages/TodayPage.jsx` | `flexShrink: 0` on header/footer; `gridTemplateRows: 1fr`; sidebar 280px |
| `frontend/src/components/Shell.jsx` | Width fix, compact padding/header, `gridTemplateRows: 1fr` |
| `frontend/src/components/NavRail.jsx` | Width 72px |

## Not Changed

- `requirements.txt` — not touched; `react-markdown`/`remark-gfm` are npm packages only
- Agent tool logic (goal_tools, relationship_tools, schedule_tools) — model switch via config is sufficient; no code changes needed in tools
