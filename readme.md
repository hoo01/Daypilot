# DayPilot

> "Your calendar knows your meetings. DayPilot knows your life."

**Demo Video:** https://youtu.be/NF6q8QUmsBw?si=tSWPXdPFkXY8iYmR

![Daypilot screenshot](docs/images/Daypilot_Home_Page.png)

---

## Quick Start

```bash
# 1. Copy .env and fill in keys
cp .env.example .env
# Required: GEMINI_API_KEY, MONGODB_URI, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET

# 2. Install dependencies
pip install -r requirements.txt

# 3. Seed demo data
python scripts/seed_demo.py

# 4. Start the server
python main.py
# → http://localhost:8000/docs
```

---

## What is DayPilot?

Every scheduling tool — Motion, Reclaim, Akiflow — assumes you already know what matters today. They arrange what you tell them. They are reactive by design.

DayPilot flips this. It surfaces what you haven't thought of yet and weaves it proactively into your day.

- Notices your 3-month anniversary is next week
- Detects your favorite artist's tickets drop in 3 days
- Knows you have 4 Leetcode problems left and your focus window is 9PM–1AM
- Back-calculates when you need to leave given your commute

> "Every scheduler assumes you know what matters today. DayPilot doesn't."

---

## Architecture

Single FastAPI server. Schedule state is **code-owned**: LLMs only *propose* (classify the
user's intent, generate candidate schedules); only code (`DayPlanService`) *commits*. See
[docs/refactor/schedule_orchestrator.md](docs/refactor/schedule_orchestrator.md).

```
User
  ↓
POST /chat/  →  TurnOrchestrator.run_turn                       (services/turn_orchestrator.py)
  ├── load_turn_context: DayPlan (today/tomorrow) + pending_reschedule + today's calendar
  ├── LLM① parse_intent → plan_day | adjust | confirm | discard | reschedule_missed | chat
  │      (agents/intent.py — response_schema, no tools, failures degrade to chat)
  │
  ├── chat ─────────► read-only Coordinator Agent (Google ADK + Gemini)
  │                    before_agent_callback preloads, in parallel:
  │                    read_user_context · track_goals · get_relationship_context ·
  │                    analyze_health · DayPlan summary
  │                    tools: memory tools, analyze_health, track_goals, get_geo_info,
  │                    get_relationship_context, check_performance — none write schedules
  │
  └── schedule ─────► DayPlanService.handle(command)            (services/day_plan_service.py)
                       1. precondition check on the stored DayPlan (InvalidTransition)
                       2. LLM② generate_schedule / generate_adjustment — pure functions:
                          response_schema → code repairs → §5.3 invariants → 1 retry →
                          GenerationFailed (never a fallback schedule)
                       3. DayPlanRepository.save(plan, expected_version)  ← only writer of
                          daily_schedules (optimistic locking)
  ↓
ChatResponse { reply, session_id, day_plan, error }   ← the UI renders day_plan only

POST /schedule/confirm { user_id, date, proposal_id, strategy_name } → ConfirmProposal
GET  /schedule/day     full DayPlan · GET /schedule/today  active tasks + geo segments
POST /schedule/feedback (end-of-day checkbox)
  ├── Stores pending_reschedule in user_preferences (progress is cumulative — skipping a task never decrements it)
  └── "move them to tomorrow" → RescheduleMissed → proposal; confirming it clears pending_reschedule
```

A DayPlan (one per `user_id + date`) holds `active` (the confirmed plan), `proposal` (options
waiting for a decision) and `version`; its status (`EMPTY`, `PROPOSED`, `CONFIRMED`,
`CONFIRMED_WITH_PROPOSAL`) is derived from the first two.

---

## Memory System

**Knowledge Graph (MongoDB Atlas)**
- `entities` — people, interests, events with relations and upcoming dates
- `user_preferences` — focus window, energy pattern, commute, pending reschedules
- `goal_state` — weekly goals with progress tracking
- `conversation_memory` — vector embeddings (Atlas Vector Search, 3072-dim)

**How memory grows**
- Cold start: Google OAuth → reads Calendar, Gmail, Contacts → Gemini extracts entities → MongoDB
- Per turn: `before_agent_callback` preloads context in parallel (no per-request tool call latency); relationship context and health analysis are cached (30 min / 10 min TTL) — first call is cold, subsequent calls are instant
- After each turn: background consolidation → Gemini compresses insight → `store_conversation_memory`
- Next session: `retrieve_relevant_memories` semantically retrieves relevant past context
- End of day: `/schedule/feedback` stores uncompleted tasks → the user can ask to move them to the next day

---

## Agent Tools

| Tool | Description | Status |
|---|---|---|
| `read_user_context` | Loads preferences, goals, upcoming events from MongoDB | Ready |
| `track_goals` | Reads goal state, uses Gemini to assess urgency and suggest blocks | Ready |
| `get_relationship_context` | Surfaces upcoming important dates with Gemini suggestions | Ready |
| `retrieve_relevant_memories` | Semantic search over past conversation memories | Ready |
| `get_geo_info` | Multi-segment commute calculation via Google Routes API | Ready |
| `write_entity_to_memory` | Persists entities extracted from conversation | Ready |
| `store_conversation_memory` | Embeds and stores conversation insights | Ready |
| `analyze_health` | PsychoBio pipeline — energy_level, focus_window, cognitive_load_score, avoid_tasks | Ready |
| `check_performance` | Response-time / error stats for "how are you performing?" | Ready |

Schedule generation and adjustment are not agent tools: `generate_schedule` and
`generate_adjustment` (LLM②) are called by `DayPlanService`. The MongoDB MCP toolset is no
longer attached to the chat agent, because it could write `daily_schedules`.

---

## Tech Stack

| Layer | Technology |
|---|---|
| LLM | Gemini 2.5 Flash (coordinator) · Gemini 2.5 Flash-Lite (preload tools) |
| Agent framework | Google ADK (`before_agent_callback`, `MCPToolset`) |
| Backend | Python + FastAPI |
| Database | MongoDB Atlas (Knowledge Graph + Vector Search) |
| MCP | mongodb-mcp-server (stdio subprocess) |
| Embeddings | gemini-embedding-001 (3072 dim) |
| Vector Search | MongoDB Atlas Vector Search |
| Auth | Google OAuth 2.0 (Calendar + Gmail + Contacts) |
| Geo | Google Routes API (transit → walking → driving fallback) |

---

## Demo Scenario

Kai opens DayPilot on Wednesday morning. He says nothing.

DayPilot already knows:
- Mia = partner → 3-month anniversary in 8 days
- Favorite artist → tickets drop in 3 days
- Leetcode goal: 6/10 done, 4 remaining, deadline Friday
- Today: ML class 2PM–4PM at library (30 min from home)
- Focus window: 9PM–1AM

DayPilot proactively surfaces:
```
"Your 3-month anniversary with Mia is in 8 days. Want me to block
Saturday evening and look up restaurants near campus?"

"Your favorite artist's tickets drop in 3 days. Want a reminder
the moment they go live?"

"You have 4 Leetcode problems left this week. I've blocked 9PM–11PM
tonight. Leave for the library by 9:15AM — that gives you a 90-minute
window this morning for 2 problems first."
```

That evening, Kai didn't finish his Leetcode session. He checks the box in the UI. DayPilot asks if he wants to reschedule — he says yes, and it automatically slots it into tomorrow.

---

## API Reference

See [docs/api.md](docs/api.md) for full endpoint documentation.

Key endpoints:
- `POST /chat/` — main conversation interface (returns the resulting `day_plan`)
- `GET /schedule/day` — the full DayPlan for a date
- `POST /schedule/confirm` — confirm a stored proposal by `proposal_id` + `strategy_name`
- `POST /schedule/feedback` — end-of-day task completion feedback
- `POST /schedule/adjust` — stateless adjustment preview (persists nothing)
- `GET /auth/google` — Google OAuth login

---

## Judging Criteria

| Criterion | Our answer |
|---|---|
| Technical implementation | ADK `before_agent_callback`, Knowledge Graph, Vector Search, MCP, Google Routes API |
| Originality | Proactive life-awareness + closed feedback loop; no existing scheduler knows your life |
| Potential impact | Works for any user across any life domain |
| Design & UX | Zero onboarding; proactive suggestions surface naturally in chat; end-of-day feedback loop |

---

## Observability — Dynatrace + OpenTelemetry

Every agent call, LLM invocation, health pipeline node, and HTTP request is instrumented with OpenTelemetry and exported to Dynatrace. The coordinator agent can also query Dynatrace about its own performance via MCP.

**What's instrumented:** HTTP middleware, all 10 agent tools (`@traced_tool`), Gemini LLM calls (`@traced_llm`), the full 4-node health pipeline, coordinator context preload, chat endpoint, and background memory consolidation.

**Self-monitoring:** Set `DT_MODE=on_demand` and the coordinator can answer "how's your latency?" by querying its own traces in Dynatrace.

**Claude Code integration:** The `.mcp.json` connects the Dynatrace MCP server — ask natural language questions about telemetry directly from your terminal.

See **[docs/DYNATRACE.md](docs/DYNATRACE.md)** for the full guide — setup, every instrumented component, DQL query examples, and testing instructions.

---

*DayPilot — Google Cloud Rapid Agent Hackathon 2026*