# DayPilot Frontend Visual Design Document

> Visual design specification — style, layout, components, interaction patterns
> Version: 1.0 | Last updated: 2026-06-05
> Companion to: `frontend_api_design.md` (logic layer)

---

## Design Philosophy

DayPilot is a functional, AI-powered daily planner. The visual language prioritizes **calm clarity over decoration** — every element earns its place. The aesthetic is warm and organic, inspired by Things 3 and Daylio: rounded forms, breathing space, and a palette that feels like morning light rather than a dashboard.

---

## Design Tokens

### Color

| Token | Value | Usage |
|-------|-------|-------|
| `--green-50` | `#f0f5f0` | AI summary card background |
| `--green-100` | `#e8f0e9` | Tags, active nav, geo panel background |
| `--green-200` | `#c5ddc8` | Borders, dividers, secondary elements |
| `--green-400` | `#7aaa7e` | Primary accent — checkboxes, buttons, icons |
| `--green-600` | `#4a7a4e` | Text on green backgrounds, strong accent |
| `--warm-50` | `#faf9f5` | Insights card background |
| `--warm-200` | `#e0ddd0` | Insights card border |
| `--warm-600` | `#7a7060` | Insights label text |
| `--surface` | `#f5f8f5` | Task card background |
| `--surface-border` | `#ddeedd` | Task card border |
| `--text-primary` | system | Main text |
| `--text-secondary` | system | Muted text, timestamps |
| `--text-tertiary` | system | Hints, placeholders |

### Typography

| Role | Font | Size | Weight |
|------|------|------|--------|
| Page title / date | DM Serif Display | 22px | 400 |
| Section heading | DM Serif Display | 16px | 400 |
| Body / task title | DM Sans | 14px | 400 |
| Task time / meta | DM Sans | 12px | 400 |
| Labels / tags | DM Sans | 11px | 500 |
| Micro / hints | DM Sans | 10px | 400 |

Google Fonts import:
```
https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&family=DM+Sans:wght@400;500&display=swap
```

### Spacing & Radius

| Token | Value |
|-------|-------|
| Card border-radius | `10px` |
| Inner panel radius | `6px` |
| Tag / pill radius | `20px` |
| Nav icon radius | `8px` |
| Base gap (task list) | `8px` |
| Card padding | `10px 12px` |
| Page padding | `24px` |

---

## Global Layout — Scheme E

```
┌──────┬──────────────────────┬─────────────────┐
│ Nav  │   Main column        │  Insights panel │
│ (icon│   Task list          │  Single card    │
│ only)│   + Submit button    │  with bullet    │
│      │   + Prompt box       │  items          │
└──────┴──────────────────────┴─────────────────┘
```

### Left nav bar
- Width: `48px`, fixed, full height
- Background: `--green-50` with a subtle right border (`0.5px solid --green-200`)
- Contains: `Today` icon (top), `Chat` icon, spacer, user avatar (bottom)
- Active state: icon background `--green-100`, icon color `--green-600`
- Inactive state: icon color `--text-tertiary`
- Hover: show tooltip to the right (label text, `DM Sans 12px`, dark pill)
- No text labels — icons only

Icons (Tabler outline):
| Page | Icon |
|------|------|
| Today | `ti-calendar-event` |
| Chat | `ti-message-2` |
| User avatar | `ti-user-circle` |

### Main column
- Flex: `1.4`
- Padding: `24px 20px`
- Contains: page header → task list → Submit Today button → prompt box

### Insights panel (right)
- Flex: `1`
- Padding: `24px 16px`
- Left border: `0.5px solid --green-200`
- Scrollable independently if content overflows
- Contains: single Insights card

---

## Page: `/today`

### Page header
- Date: `DM Serif Display 22px`, e.g. "Thursday, Jun 5"
- No subtitle or AI summary in the header (moved to insights panel)

### Task list

Each task is a **card (Scheme A)**:

```
┌─────────────────────────────────────────────┐  ← border-radius: 10px
│  ○  Task title                    3:00 PM 📍 │  ← background: --surface
└─────────────────────────────────────────────┘
```

**Standard task card:**
- Background: `--surface` (`#f5f8f5`)
- Border: `0.5px solid --surface-border`
- Border-radius: `10px`
- Padding: `10px 12px`
- Row: checkbox (16px circle) · task title (DM Sans 14px 500) · time (12px, right-aligned)
- Checkbox unchecked: `1.5px solid --green-200` circle
- Checkbox checked: filled `--green-400`, task title gets `line-through` + `opacity: 0.5`

**Geo task card (additional):**
- Left border: `3px solid --green-400` (overrides standard `0.5px`)
- Map pin icon (`ti-map-pin`, 13px, `--green-400`) shown in the header row
- Clicking the card expands the geo panel below the header row
- Clicking again collapses it

**Geo panel (expanded, Scheme C):**
```
┌─────────────────────────────────────────────┐
│ ⚡ Leave by 2:42 PM              18 min drive│  ← divider below
│ USC Viterbi → LA Fitness    [Navigate ↗]    │
└─────────────────────────────────────────────┘
```
- Background: `--green-100` (`#eaf3eb`)
- Border-radius: `6px`
- Top row: `ti-clock-bolt` icon + "Leave by HH:MM" (DM Sans 11px 500, `--green-600`) + duration (right, `--green-400`)
- Divider: `0.5px solid --green-200`
- Bottom row: origin → destination (11px, `--text-tertiary`) + Navigate pill button
- Navigate button: `background: --green-200`, `color: --green-600`, `border-radius: 10px`, opens `geo_segment.maps_url` in new tab
- `leave_by` time = `scheduled_time − duration_minutes` (computed on frontend, no extra API field needed for now; add to schema later if backend wants to own this)

### Submit Today button
- Position: directly below the last task card, full width
- Background: `--green-400`
- Text: "Submit today's progress" — DM Sans 14px 500, white
- Border-radius: `10px`
- Height: `44px`
- On click: `POST /schedule/feedback` → show toast with `message` + optional reschedule dialog

### Prompt box
- Position: fixed at the bottom of the main column, below Submit Today
- Background: white, border `0.5px solid --green-200`, border-radius `10px`
- Placeholder: "Ask anything about your day…"
- Send button: `--green-400` filled square, `ti-arrow-up` icon
- On submit: `POST /chat/` → navigate to `/chat` and show response

---

## Page: `/chat`

Separate full page, navigated to via left nav or prompt box submission.

### Layout
Same global shell (left nav + main column), no right insights panel on this page.

### Message stream
- User messages: right-aligned, background `--green-100`, border-radius `10px 10px 2px 10px`, DM Sans 14px, max-width 70%
- AI messages: left-aligned, **no bubble background**, DM Sans 14px, `--text-primary`, max-width 80%
- Timestamp: DM Sans 10px `--text-tertiary`, shown below each message
- If `/chat/` response contains `schedule_updated: true` → show inline notice: "Your schedule has been updated ↗ Back to Today"

### Input bar
- Same style as prompt box on `/today`
- `session_id` stored in localStorage, sent with every message
- Sticky at bottom of viewport

---

## Page: `/auth`

### Layout
Full viewport, centered card. Background: a subtle warm off-white (`#faf9f5`), no pattern.

### Card
- Width: `400px`
- Background: white
- Border: `0.5px solid --warm-200`
- Border-radius: `16px`
- Padding: `40px`
- Shadow: none

### Card contents (top to bottom)

1. **Logo**
   - Icon: `ti-navigation` (or custom SVG pilot/compass mark), `24px`, `--green-400`
   - Wordmark: "DayPilot" — DM Serif Display 26px, `--text-primary`
   - Icon and wordmark inline, gap `8px`

2. **Tagline**
   - "Your AI-powered daily co-pilot."
   - DM Sans 14px, `--text-secondary`
   - Margin-top: `8px`

3. **Google login button**
   - Margin-top: `32px`
   - Full width, height `44px`
   - Background: white, border `1px solid #ddd`, border-radius `10px`
   - Google "G" logo (SVG inline) + "Continue with Google" — DM Sans 14px 500
   - On click: `GET /auth/google?user_id=xxx` → `window.location.href = response.auth_url`

4. **Footer note**
   - "We only read your calendar and email to build your schedule."
   - DM Sans 11px, `--text-tertiary`, centered
   - Margin-top: `20px`

---

## Insights Panel

### Card structure
- Background: `--warm-50` (`#faf9f5`)
- Border: `0.5px solid --warm-200`
- Border-radius: `10px`
- Padding: `12px 14px`
- Header: "Insights" — DM Serif Display 14px, `--text-primary`
- Updated daily by the agent; no timestamp shown

### Item structure
Each insight is a labeled bullet:

```
[Insight]   You tend to skip evening tasks on gym days.
[Pattern]   3 of last 5 Fridays ended with incomplete tasks.
[Suggestion] Consider moving Leetcode to earlier in the day.
```

- Label tag: DM Sans 10px 500, uppercase, colored pill
  - `Insight` → `--green-100` bg, `--green-600` text
  - `Pattern` → `--warm-200` bg, `--warm-600` text
  - `Suggestion` → `#e8f0fb` bg, `#4a6a8a` text (soft blue)
- Item text: DM Sans 12px, `--text-secondary`, `line-height: 1.6`
- Divider between items: `0.5px solid --warm-200`

---

## Component: Toast notification

Triggered after `POST /schedule/feedback`.

- Position: bottom-center, `24px` from bottom
- Background: `--text-primary` (dark)
- Text: white, DM Sans 13px
- Border-radius: `10px`
- Padding: `10px 16px`
- Contains: message text + optional "Ask in chat →" link button
- Auto-dismiss after `4000ms`

---

## Open Design Items

| Status | Item |
|--------|------|
| ⏳ Pending | `leave_by` field — currently computed on frontend (`scheduled_time − duration_minutes`); confirm if backend should own this |
| ⏳ Pending | Logo icon — `ti-navigation` is a placeholder; consider custom SVG mark |
| ⏳ Pending | Empty state design for task list (no tasks today) |
| ⏳ Pending | Loading skeleton for task list on page load |
| ⏳ Pending | `/history` page — deferred to phase 2 |
| ✅ Decided | All decisions above locked |
