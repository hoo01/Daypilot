# DayPilot — Technical Framework

> "Your calendar knows your meetings. DayPilot knows your life."

---

## Team Responsibilities

| Member | Agent | File | Status |
|---|---|---|---|
| **Yuqing** | Ingestion Agent (cold start) | `agents/ingestion.py` | 🟢 Ready |
| **Yuqing** | Relationship & Context Agent | `agents/tools/relationship_tools.py` | 🟢 Ready |
| **Yuqing** | Real-time Adjustment Agent | `agents/tools/realtime_tools.py` | 🟢 Ready |
| **Vatsal** | Health & Energy Agent | `agents/health-agent/` | 🟢 Ready |
| **Astrid** | Goal Tracking Agent | `agents/Goal_Tracking_Agent/` | 🟢 Ready |
| **Jingyuan** | Schedule Planning Agent | `agents/Schedule_Planning_Agent/` | 🟢 Ready |
| **Shared** | Coordinator Agent | `agents/coordinator.py` | 🟢 Ready |
| **Shared** | Memory Agent | `agents/memory.py` | 🟢 Ready |
| **Unassigned** | Geo Agent | `agents/tools/geo_tools.py` | 🟡 Stub ready |

### How to implement your agent

All agents are now **ADK tool functions** — plain async Python functions registered on the coordinator.

1. Open your file in `agents/tools/` (e.g. `health_tools.py`)
2. Find the `# TODO` comments inside the async function
3. Call Gemini directly using `genai.Client` (see `relationship_tools.py` as a working example)
4. Parse the JSON response and return a plain `dict`
5. Input/output schemas are in `schemas/` — your return dict should match the Output schema fields
6. The stub already returns a valid dict — replace it once your implementation is ready

Reference implementation: [agents/tools/relationship_tools.py](agents/tools/relationship_tools.py)

### Quick start

```bash
# 1. Create your .env file with the following keys:
#    GEMINI_API_KEY=...        # get from aistudio.google.com
#    MONGODB_URI=...           # ask Yuqing for the shared Atlas URI
#    MONGODB_DB_NAME=daypilot
#    GOOGLE_CLIENT_ID=
#    GOOGLE_CLIENT_SECRET=
#    APP_SECRET_KEY=change_me_in_production

# 2. Install dependencies
pip install -r requirements.txt

# 3. (Optional) Seed demo data into MongoDB
python scripts/seed_demo.py

# 4. Start the server
python main.py
# → http://localhost:8000/docs  to explore all API endpoints
```

---

## 1. Core Insight & Differentiation

### The problem with every existing scheduler

Every scheduling tool — Motion, Reclaim, Akiflow — shares the same hidden assumption:

> **The user already knows what matters today. The tool just arranges it.**

They wait for input. They manage what you tell them. They are reactive by design.

### What DayPilot does differently

DayPilot flips this assumption. It surfaces what you haven't thought of yet — events you care about, people you love, deadlines creeping up — and weaves them proactively into your day.

Two concrete differentiators:

**① Knows your life, not just your meetings**
- Detects that your favorite artist's tickets drop in 3 days
- Notices your 3-month anniversary is next week
- Surfaces these as scheduled actions — without you asking

**② Time × Space planning**
- Every existing scheduler lives on a timeline with no awareness of geography
- DayPilot knows where you are, where you need to be, and how long it takes to get there
- Commute time back-calculates available work windows before you leave

### One-line pitch

> "Every scheduler assumes you know what matters today. DayPilot doesn't."

---

## 2. Multi-Agent Architecture

DayPilot is not a single agent. It is a **coordinated multi-agent system** where each agent has a single, well-defined responsibility.

### Agent overview

| Agent | Owner | Model | Role |
|---|---|---|---|
| Coordinator Agent | — | gemini-3.1-pro-preview | Orchestrates all agents, handles user chat |
| Ingestion Agent | — | gemini-3.1-flash-lite | Cold start + ongoing data ingestion |
| Memory Agent | — | — | Reads/writes Knowledge Graph (MongoDB) |
| Health & Energy Agent | Vatsal | gemini-3.1-pro-preview | Analyzes energy, sleep, cognitive readiness |
| Goal Tracking Agent | Astrid | gemini-2.5-flash | Tracks weekly goals, deadlines, progress |
| Relationship & Context Agent | — | gemini-3.1-pro-preview | People, anniversaries, social context |
| Schedule Planning Agent | Jingyuan | gemini-3.1-pro-preview | Generates optimized daily schedule options |
| Geo Agent | — | gemini-3.5-flash | Commute time, route planning, location awareness |
| Real-time Adjustment Agent | Yuqing | gemini-2.5-flash | Monitors disruptions, dynamically replans |

### Agent interaction flow

```
User Input
    ↓
Coordinator Agent   ←──────────────────────────────┐
    ↓                                              │
    ├──→ Ingestion Agent → Memory Agent            │
    │                           ↓                  │
    │                    Knowledge Graph           │
    │                           ↓                  │
    ├──→ Health & Energy Agent ──┐                 │
    ├──→ Goal Tracking Agent ────┤                 │
    ├──→ Relationship Agent ─────┼──→ Schedule     │
    ├──→ Geo Agent ──────────────┘    Planning     │
    │                                  Agent       │
    │                                    ↓         │
    └──→ Real-time Adjustment Agent ─────────────→ │
                                                   │
                             Action Agent ─────────┘
                                    ↓
               Google Calendar / Notification / Chat
```

---

## 3. The "Knows Your Life" Layer — Cold Start & Persistent Learning

This is DayPilot's core innovation and primary differentiator.

### Cold start philosophy

Most AI products start empty and ask users to fill them in. DayPilot starts by **reading what users have already written about themselves** across their digital life.

> "You've already told the world who you are. DayPilot just listens."

On first login, a single OAuth authorization triggers one-time ingestion:

| Source | What we read | What we learn |
|---|---|---|
| Google Calendar history | Past events, recurring patterns | Daily rhythms, priorities |
| Gmail metadata | Subscriptions, reservations, receipts | Interests, relationships, habits |
| Google Contacts (starred) | Who matters most | Relationship graph seed |
| Spotify (optional) | Listening history | Real preferences, not stated ones |

After ingestion, Gemini processes all data and bootstraps the Knowledge Graph instantly. The user opens DayPilot for the first time and it already knows them.

### Ongoing learning

The Knowledge Graph grows continuously from two sources:

**Passive:** Every calendar change, new email thread, or completed task feeds the Ingestion Agent.

**Active:** Every user conversation is processed by the Coordinator Agent for entity extraction.

```
User: "Mia and I have been together for 3 months"

Gemini extracts →
{
  "entity": "Mia",
  "type": "person",
  "relation": "partner",
  "since": "2026-02-23",
  "subject": "user"
}

→ Written to Knowledge Graph via Memory Agent
```

---

## 4. Knowledge Graph Design (MongoDB)

MongoDB is the persistence layer for all user knowledge. Three core collections:

### `entities` collection

```json
{
  "user_id": "string",
  "entity_name": "Mia",
  "entity_type": "person",
  "relations": [
    {
      "type": "partner",
      "since": "2026-02-23",
      "upcoming_dates": [
        { "event": "3-month anniversary", "date": "2026-05-23" }
      ]
    }
  ],
  "social_priority_score": 0.84,
  "created_at": "timestamp",
  "updated_at": "timestamp"
}
```

Supported entity types: `person`, `goal`, `preference`, `event`, `interest`

### `user_preferences` collection

```json
{
  "user_id": "string",
  "focus_window": "9PM-1AM",
  "cognitive_style": "deep work at night, routine tasks in morning",
  "energy_pattern": "low morning, peak evening",
  "task_preferences": {
    "avg_leetcode_duration_min": 45,
    "preferred_break_length_min": 10
  }
}
```

### `goal_state` collection

```json
{
  "user_id": "string",
  "goals": [
    {
      "goal": "10 Leetcode problems this week",
      "progress": 6,
      "target": 10,
      "deadline": "2026-06-01",
      "urgency": "medium",
      "suggested_blocks": ["2h Leetcode tonight"]
    }
  ]
}
```

---

## 5. Agent Specifications

### Coordinator Agent
**Role:** Orchestrator. The only agent that talks directly to the user.

**Responsibilities:**
- Receives all user input (chat or background events)
- Decides which downstream agents to invoke
- Passes outputs between agents
- Returns final merged response to user

**Pattern:** ReAct (Reason + Act) — evaluates context, selects tools, observes results

### Ingestion Agent
**Role:** Data pipeline from external world into Knowledge Graph.

**Inputs:** Google Calendar, Gmail metadata, Contacts, Spotify, wearable APIs

**Output:** Structured entity + relation objects → Memory Agent

**Triggers:**
- One-time on cold start (full historical read)
- Daily cron (incremental update)
- Event-driven (new calendar entry detected)

### Memory Agent
**Role:** Single source of truth for Knowledge Graph. All reads/writes go through here.

**Interface:**
```python
memory.write_entity(entity: Entity) → None
memory.read_entity(name: str) → Entity
memory.query_upcoming(days: int) → list[Event]
memory.update_preference(key: str, value: Any) → None
```

No agent writes directly to MongoDB. All database access is mediated by Memory Agent.

### Health & Energy Agent (Vatsal)
**Inputs:**
```json
{
  "sleep_duration_hours": 7.5,
  "sleep_quality": "good",
  "wearable_summary": "optional",
  "user_reported_energy": "medium",
  "previous_workload": "heavy"
}
```

**Output:**
```json
{
  "energy_level": "low-medium",
  "focus_window": "9PM-1AM",
  "cognitive_load_score": 0.72,
  "avoid_tasks": ["back-to-back deep work"]
}
```

### Goal Tracking Agent (Astrid)
**Inputs:** Weekly goals, deadlines, task completion history, calendar availability

**Output:**
```json
{
  "goal_status": "behind_schedule",
  "progress_percent": 60,
  "urgency": "high",
  "suggested_blocks": ["2h Leetcode session tonight"]
}
```

### Relationship & Context Agent
**Role:** The "knows your life" engine. Surfaces people and dates that create implicit tasks.

**Inputs:** Contacts, Calendar history, Gmail metadata, conversation history, Memory Agent

**Output:**
```json
{
  "important_people": ["Mia"],
  "upcoming_dates": [
    { "event": "3-month anniversary", "date": "2026-06-01" }
  ],
  "proactive_suggestions": [
    "Anniversary in 7 days — recommend making a reservation"
  ],
  "social_priority_score": 0.84
}
```

### Schedule Planning Agent (Jingyuan)
**Role:** Synthesizes all agent outputs into an optimized daily schedule.

**Inputs:** Health output, Goal output, Relationship output, Calendar events, Geo output, user preferences

**Output:** Multiple schedule strategies
```json
{
  "strategies": [
    {
      "name": "Most Productive",
      "tasks": [
        { "time": "9PM", "duration_min": 90, "task": "Leetcode x2", "location": "home" }
      ]
    },
    {
      "name": "Most Balanced",
      "tasks": [...]
    }
  ]
}
```

### Geo Agent
**Role:** Bridges time and space. Computes commute time and back-calculates task windows.

**Tools:** Google Routes API, Maps API

**Core logic:**
```python
# Given: user must leave at 11:30
# Given: commute = 30 min
# → Available work window = now → 11:20 (10 min buffer)
# → Back-calculate: how many Leetcode problems fit?
```

**Output:**
```json
{
  "departure_time": "11:20",
  "arrival_time": "11:50",
  "route": "subway Line 2",
  "available_window_min": 110,
  "recommended_tasks_before_departure": ["2 Leetcode problems"]
}
```

### Real-time Adjustment Agent (Yuqing)
**Role:** Monitors for disruptions and dynamically replans.

**Triggers:** New calendar event, user location change, task overrun, energy update from wearable

**Output:**
```json
{
  "what_changed": ["Gym moved from 4PM to 8PM"],
  "dropped_tasks": ["Optional reading session"],
  "updated_schedule": [...]
}
```

---

## 6. Tech Stack

### Core
| Layer | Technology |
|---|---|
| LLM | gemini-3.1-pro-preview / gemini-2.5-flash / gemini-3.1-flash-lite |
| Agent framework | Google Cloud Agent Builder |
| Backend | Python + FastAPI |
| Database | MongoDB Atlas (Knowledge Graph) |
| Partner track | MongoDB (Hackathon partner) |

### APIs & Integrations
| Service | Usage |
|---|---|
| Google Calendar API | Read/write schedule |
| Gmail API | Metadata only (no content) — cold start |
| Google Contacts API | Relationship graph seed |
| Google Routes API | Commute time calculation |
| Google OAuth 2.0 | Single auth flow for all Google services |
| Wearable APIs | Optional — health data |

### Frontend
- Web app with chat interface
- Real-time schedule view with time blocks
- Interactive task adjustment

---

## 7. Development Plan

### Week 1 — Foundation (Jingyuan leads)

**Priority order:**

1. Google OAuth 2.0 — single auth flow covering Calendar, Gmail, Contacts
2. MongoDB Atlas setup — collections and schema as defined in Section 4
3. Memory Agent — unified read/write interface
4. Ingestion Agent — cold start pipeline (Calendar + Gmail + Contacts)
5. Coordinator Agent skeleton — receives input, routes to agents, returns output
6. Pydantic schemas for all agent inputs/outputs — **all teammates must implement to spec**

**Deliverable:** A working pipeline where user logs in → data ingested → Knowledge Graph populated → Coordinator receives a test prompt and routes it correctly.

### Week 2 — Agent Development (parallel)

Each teammate implements their assigned agent against the Pydantic schemas defined in Week 1.

**Integration checkpoints:** Daily — each agent's output is validated against the schema before merging.

### Week 3 — Integration & Demo

- Full pipeline end-to-end
- Demo script execution and recording
- UI polish

---

## 8. Demo Script

**Scenario:** Kai wakes up on Wednesday and opens DayPilot.

He said nothing today. DayPilot already knows:

```
From Knowledge Graph:
- Mia = partner, since 2026-02-23 → anniversary in 8 days
- Favorite artist → tickets drop in 3 days
- Weekly goal: 10 Leetcode problems → 6 done, 4 remaining
- Today: ML class 2PM-4PM, studying in library all day
- Geo: library is 30 min from home

DayPilot proactively surfaces:
→ "Your 3-month anniversary with Mia is in 8 days.
   There's a restaurant near campus she mentioned once.
   Want me to block Saturday evening and make a reservation?"

→ "Your favorite artist's tickets drop in 3 days.
   Want a reminder set for the moment they go live?"

→ "You have 4 Leetcode problems left this week.
   Based on your focus window, I've blocked 9PM–11PM tonight.
   You need to leave for the library by 9:15AM — that gives you
   a 90-minute window this morning for 2 problems first."
```

Kai confirms. DayPilot writes to Calendar, sets reminders, and plans his route.

---

## 9. Judging Criteria Mapping

| Criterion | Our answer |
|---|---|
| Technical implementation | Multi-agent system, Knowledge Graph, real API integrations |
| Design & UX | Proactive suggestions surfaced naturally in chat; no onboarding form |
| Potential impact | Applicable to any user; scales to any life domain |
| Originality | No existing scheduler knows your life — only your meetings |

---

*Document version: 1.0 — May 2026*
*For internal team use — DayPilot, Rapid Agent Hackathon*
