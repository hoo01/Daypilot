# DayPilot Frontend Design Document

> UI/UX design + implementation spec — visual system, component behavior, page layouts, interaction flows
> Version: 1.0 | Last updated: 2026-06-06
> Companion to: `frontend_api_design.md` (v0.3)

---

## Tech Stack

| Item | Choice |
|------|--------|
| Framework | React + Vite |
| Routing | React Router v6 |
| Styling | Tailwind CSS + custom CSS variables (see Design Tokens) |
| Global state | Zustand |
| HTTP requests | fetch API (native) |
| Local persistence | localStorage |
| Chart library | Recharts (sparkline for mood curve) |

---

## Design Philosophy

DayPilot is a multi-agent AI scheduling assistant that integrates calendar, health, and geo into one daily interface. The visual language reflects that: **calm precision, not productivity hustle**. The product feels like a premium personal assistant, not a task manager.

**Core aesthetic**: Light glassmorphism. Soft green palette. Generous whitespace. Restrained typography. Every element earns its place.

**Demo note**: A dark theme variant (CSS variable swap) should be built as a secondary option for hackathon demo video use. The default product ships light.

---

## Design Tokens

All colors and surface styles live in `:root` CSS variables, carried over directly from the prototype. Tailwind is used for spacing and layout only — never for color overrides.

```css
:root {
  --bg: #edf3ed;
  --bg-deep: #e3ebe1;
  --surface: rgba(255, 255, 255, 0.42);
  --surface-strong: rgba(255, 255, 255, 0.62);
  --surface-soft: rgba(255, 255, 255, 0.26);
  --line: rgba(21, 29, 25, 0.08);
  --line-strong: rgba(21, 29, 25, 0.12);
  --text: #121817;
  --muted: #66716b;
  --muted-2: #87908b;
  --accent: #b8d3bc;
  --accent-2: #dae8c0;
  --accent-3: #a6c7ae;
  --accent-4: #8fb699;
  --glass: blur(24px) saturate(135%);
  --shadow: 0 28px 90px rgba(24, 30, 27, 0.08);
  --shadow-soft: 0 18px 44px rgba(24, 30, 27, 0.05);
  --radius-xl: 34px;
  --radius-lg: 24px;
  --radius-md: 18px;
  --radius-sm: 14px;

  /* Error / status */
  --error: #dc2626;
  --error-surface: rgba(220, 38, 38, 0.08);
}
```

**Dark theme variant** (applied via `[data-theme="dark"]` on `<html>`):

```css
[data-theme="dark"] {
  --bg: #0d1210;
  --bg-deep: #080e0c;
  --surface: rgba(255, 255, 255, 0.06);
  --surface-strong: rgba(255, 255, 255, 0.10);
  --surface-soft: rgba(255, 255, 255, 0.03);
  --line: rgba(255, 255, 255, 0.08);
  --line-strong: rgba(255, 255, 255, 0.12);
  --text: #f0f4f1;
  --muted: #8a9e91;
  --muted-2: #637068;
  --accent: #4ade80;
  --accent-2: #86efac;
  --accent-3: #22c55e;
  --accent-4: #16a34a;
}
```

---

## Global Layout Shell

All pages share the same outer shell structure:

- `body`: radial gradient background (green tones), `overflow: hidden`
- `.app`: `100vw × 100vh`, `padding: 20px`
- `.shell`: inner rounded container, `border-radius: 34px`, glassmorphism surface, `overflow: hidden`
- Inside shell: topbar (80px) + content area (remaining height)

The shell is a single persistent component wrapping all routes. Navigation tabs and brand mark live in the topbar.

---

## Global Components

### Backend Down Banner

- **Trigger**: `GET /health` on app startup returns `status !== "ok"` or network error
- **Position**: fixed, top of viewport, full width, z-index above shell
- **Style**: red background (`--error`), white text, 48px height
- **Content**: "DayPilot is currently unavailable. Please try again shortly."
- **Behavior**: non-dismissable, stays visible until health check passes (re-poll every 30s)
- **Zustand**: `isBackendDown` flag drives this component

### Toast

- **Trigger**: after `POST /schedule/feedback` succeeds
- **Position**: fixed bottom-center, appears above the submit button
- **Style**: glassmorphism surface, `--radius-md`, soft shadow
- **Content**: `response.message` text + "Ask in chat →" shortcut button
- **"Ask in chat" behavior**: navigate to `/chat?trigger=feedback`, which auto-sends a trigger message (see Chat page section)
- **Duration**: stays until user dismisses or navigates away

### Navigation Rail (left sidebar icon bar)

Same as prototype: 84px wide, icon buttons for Home (→ `/today`), Chat (→ `/chat`), History (→ `/history`, disabled in phase 1).

---

## Pages

---

### `/auth` — Login

**When shown**: app cold-starts and no `user_id` in localStorage.

**Layout**: full-screen centered, no shell wrapper.

```
[full screen, --bg background]

        [DayPilot logo / brand mark]
        [tagline: "Your AI-native daily co-pilot"]

        [Google OAuth button]
          → calls GET /auth/google?user_id=xxx
          → window.location.href = response.auth_url
```

**After OAuth**: Google redirects to backend `/auth/callback`, which redirects to `http://localhost:5173/today?user_id=xxx`. On landing at `/today`, frontend reads `user_id` from URL params, stores in localStorage, strips param from URL.

**Styling**: minimal, centered column, brand mark uses existing dark pill style from prototype.

---

### `/today` — Today's Schedule

**When shown**: default page when `user_id` exists in localStorage.

**Layout**: three-column grid inside content area.

```
[Rail 84px] | [Main column, flex 1.72] | [Sidebar 340px min]
```

#### Main column

**Top section**:
- Current date (formatted: "Sat, Jun 6")
- Daily quote: a short rotating line shown below the date
  - Sourced from a hardcoded frontend quotes array (no API call)
  - Categories: motivational, thought-provoking, or light humor — mixed
  - Selection: `quotes[dayOfYear % quotes.length]` so it changes daily and is deterministic
  - Displayed as a soft italic paragraph, muted color (`--muted`)
  - No loading state needed (fully offline)

**Body**: task card list, sorted ascending by `scheduled_time`. See Task Card section below.

**Bottom**: fixed "Submit today's progress" button
- Style: full-width within main column, dark pill button
- Disabled if `last_feedback_date === today` (prevent duplicate submit)
- On click: `POST /schedule/feedback` with uncompleted tasks payload
- On success: show toast → toast includes "Ask in chat →" button → `/chat?trigger=feedback`

#### Right sidebar

Two sections, separated by a soft divider:

**Section 1: Today at a glance**
- Static insight bars (from prototype): Commute risk, Focus window
- These are display-only in phase 1, values are hardcoded or derived from task data

**Section 2: Mood check**
- Header: "Mood check" + "Daily" badge
- Sub-label: "One daily check-in, shown as a soft green trend."
- 5 geometric icon selectors (see Mood Track section below)
- Recharts sparkline showing last 7 days of mood values

---

### `/chat` — AI Chat (full page)

**When shown**: user navigates via nav rail, or via "Ask in chat →" from toast.

**Layout**:
```
[Rail 84px] | [Chat column, full remaining width]
```

**Chat column structure**:
- Top: session title / date
- Body: scrollable message bubble stream
  - User bubbles: right-aligned, surface-strong background
  - Agent bubbles: left-aligned, surface background, slight left padding
- Bottom: fixed compose bar (input + send button)

**`session_id` handling**:
- Read from localStorage on mount
- Sent with every `POST /chat/` request
- Written to localStorage on first response

**Auto-trigger on `?trigger=feedback`**:
- On mount, detect `trigger=feedback` URL param
- Automatically send `POST /chat/` with message: `"I just submitted today's progress. What do you suggest for rescheduling?"`
- Agent reply will include `suggested_reschedule_date` naturally in the conversation
- Strip the param from URL after sending
- Show a subtle "DayPilot is responding..." indicator while waiting

**`schedule_updated` handling**:
- After any `POST /chat/` response, check for `schedule_updated: true`
- If true: re-fetch `GET /schedule/today` and update Zustand `tasks` array in-place
- The task list on `/today` will reflect changes if user navigates back

**Agent drawer** (also available from `/today`):
- Lightweight overlay version of chat, slides up from bottom
- Shares the same `session_id` and message history
- Suitable for quick inputs ("I have a meeting at 10am")
- Has a "Open full chat →" button that navigates to `/chat` preserving session

---

### `/history` — History (phase 2, reserved)

Route exists, renders a placeholder. Not built in phase 1.

---

## Task Cards

### Standard task card

```
[✓ checkbox] [task title]          [scheduled time]
             [task meta / subtitle]
```

- Checkbox state stored in local component state, collected on final submit
- Completed tasks: reduced opacity, title strikethrough

### Geo task card

```
[✓ checkbox] [task title]          [scheduled time]  [📍 pin icon]
             [origin → destination · duration]
             ─────────────────── [expanded: geo panel] ───────────────────
```

- Map pin icon on the right signals geo data available
- Clicking anywhere on card header row toggles expansion
- Expanded geo panel:
  - Route: `geo_segment.origin → geo_segment.destination`
  - Travel time: `geo_segment.duration_text` (displayed as-is)
  - Tags: "Maps route ready" chip
  - "Navigate" button: `window.open(geo_segment.maps_url, '_blank')`
- Only one geo card expanded at a time (collapsing others on open is optional, not required)

---

## Mood Track

### Location

Right sidebar on `/today`, Section 2.

### UI Structure

```
Mood check                              [Daily]
One daily check-in, shown as a soft green trend.

[○]  [◔]  [◑]  [◕]  [◉]    ← 5 geometric selectors
 1    2    3    4    5

[───── recharts sparkline, 7-day curve ─────]
```

### Geometric icons

| Icon | Value | Label |
|------|-------|-------|
| Empty circle | 1 | `drained` |
| Quarter fill | 2 | `low` |
| Half fill | 3 | `okay` |
| Three-quarter fill | 4 | `calm` |
| Full / double circle | 5 | `energized` |

Icons are SVG, rendered in `--accent-4` color. Selected state: filled background card with `--accent` tint, same as prototype mood check screenshot.

### Interaction

- User can select one icon per day
- Once selected, today's entry is saved immediately to localStorage
- Re-selecting a different icon updates today's entry
- Selected state persists on page refresh (read from localStorage on mount)

### localStorage schema

```json
{
  "mood_log": [
    {
      "date": "2026-06-06",
      "value": 3,
      "label": "okay",
      "source": "user_input"
    }
  ]
}
```

Key: `mood_log`, type: JSON array, max kept: 30 entries (rolling window).

### Sparkline

- Library: Recharts `<LineChart>` with `<Line type="monotone">`
- Data: last 7 entries from `mood_log`
- Height: 48px, no axes, no tooltip, `dot={false}`
- Stroke color: `var(--accent-4)`, `strokeWidth: 2`
- If fewer than 2 entries exist: hide sparkline, show "Keep checking in to see your trend" in muted text

### API integration

None. Mood is purely frontend/localStorage in phase 1. The `source: "user_input"` field is reserved for future Health Agent integration.

---

## State Management

### localStorage keys

| Key | Type | Description |
|-----|------|-------------|
| `user_id` | string | Written after OAuth callback |
| `session_id` | string | Written after first chat message |
| `today_schedule` | JSON array | Today's task list, cache of `/schedule/today` response |
| `last_feedback_date` | string | ISO date of last feedback submit, blocks duplicate submits |
| `mood_log` | JSON array | Rolling 30-day mood log, written on each mood selection |

### Zustand store

```js
{
  tasks: [],              // today's task list (source of truth at runtime)
  chatMessages: [],       // chat history, runtime only, not persisted
  isBackendDown: false,   // from /health check
}
```

---

## Routing Logic

```
App cold start
  └─ user_id in localStorage?
       ├─ Yes → /today
       └─ No  → /auth

/auth
  └─ OAuth completes → backend redirect → /today?user_id=xxx
       └─ store user_id → strip URL param → render /today

/today
  └─ on mount:
       ├─ GET /health → set isBackendDown
       └─ GET /schedule/today → set tasks
       (daily quote is computed locally, no API call)
  └─ submit button:
       └─ POST /schedule/feedback
            └─ show toast with "Ask in chat →" → /chat?trigger=feedback

/chat
  └─ on mount:
       ├─ read session_id from localStorage
       └─ if ?trigger=feedback: auto-send trigger message → agent replies with reschedule suggestion
  └─ on POST /chat/ response:
       └─ if schedule_updated: true → re-fetch GET /schedule/today → update tasks in Zustand
```

---

## Open Issues

| Status | Issue |
|--------|-------|
| ✅ Decided | Auth page: full-screen centered, Google OAuth button + logo |
| ✅ Decided | Backend down: top red banner, non-dismissable, re-polls every 30s |
| ✅ Decided | Feedback confirmation: no modal, redirect to /chat?trigger=feedback, agent replies naturally |
| ✅ Decided | Chat: both drawer (quick) and /chat full page coexist, shared session_id |
| ✅ Decided | Mood track: right sidebar, localStorage only, recharts sparkline, geometric icons |
| ✅ Decided | Mood → chat: no API linkage in phase 1, purely local feature |
| ✅ Decided | Dark theme: CSS variable swap via [data-theme="dark"], built as demo variant |
| ⏳ Pending | geo_segment schema needs backend confirmation |
| ⏳ Pending | Confirm /chat/ response includes schedule_updated: true flag on replan |
| ⏳ Pending | Confirm OAuth redirect URL for local dev: http://localhost:5173/today |
