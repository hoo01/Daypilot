# DayPilot

> "Your calendar knows your meetings. DayPilot knows your life."

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

Single FastAPI server with a Google ADK coordinator agent orchestrating specialist tool functions. MongoDB Atlas is the persistence layer for the Knowledge Graph, accessed via MCP.

```
User
  ↓
POST /chat/
  ↓
Coordinator Agent (Google ADK + Gemini)
  ├── read_user_context       → MongoDB Knowledge Graph
  ├── retrieve_relevant_memories → MongoDB Vector Search
  ├── analyze_health          → energy + focus window
  ├── track_goals             → goal progress + urgency
  ├── get_relationship_context → upcoming dates + proactive suggestions
  ├── plan_schedule           → 3 optimized daily strategies
  ├── adjust_schedule         → real-time replanning
  ├── write_entity_to_memory  → persist facts from conversation
  ├── store_conversation_memory → vector embedding → MongoDB
  └── MongoDB MCP             → direct Knowledge Graph queries
```

---

## Memory System

DayPilot has two memory layers:

**Knowledge Graph (MongoDB)**
- `entities` — people, interests, events, goals with relations and upcoming dates
- `user_preferences` — focus window, energy pattern, commute habits
- `goal_state` — weekly goals with progress tracking
- `conversation_memory` — vector embeddings for semantic retrieval (Atlas Vector Search)

**How memory grows**
- Cold start: Google OAuth → reads Calendar, Gmail, Contacts → Gemini extracts entities → MongoDB
- Per conversation: coordinator extracts facts → `write_entity_to_memory`
- After each turn: background consolidation → Gemini compresses insight → `store_conversation_memory`
- Next session: `retrieve_relevant_memories` semantically retrieves relevant past context

---

## Agent Tools

| Tool | Description | Status |
|---|---|---|
| `read_user_context` | Loads preferences, goals, upcoming events from MongoDB | Ready |
| `retrieve_relevant_memories` | Semantic search over past conversation memories | Ready |
| `get_relationship_context` | Surfaces upcoming important dates with Gemini suggestions | Ready |
| `track_goals` | Reads goal state, uses Gemini to assess urgency and suggest blocks | Ready |
| `plan_schedule` | Generates 3 daily schedule strategies with constraint enforcement | Ready |
| `adjust_schedule` | Real-time replanning when disruptions occur | Ready |
| `write_entity_to_memory` | Persists entities extracted from conversation | Ready |
| `store_conversation_memory` | Embeds and stores conversation insights for future retrieval | Ready |
| `analyze_health` | Energy and focus window analysis | Stub |
| `get_geo_info` | Commute time and departure window calculation | Stub |

---

## Tech Stack

| Layer | Technology |
|---|---|
| LLM | Gemini 2.5 Flash |
| Agent framework | Google ADK |
| Backend | Python + FastAPI |
| Database | MongoDB Atlas |
| MCP | mongodb-mcp-server (stdio) |
| Embeddings | gemini-embedding-001 (3072 dim) |
| Vector Search | MongoDB Atlas Vector Search |
| Auth | Google OAuth 2.0 (Calendar + Gmail + Contacts) |

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

---

## Judging Criteria

| Criterion | Our answer |
|---|---|
| Technical implementation | ADK multi-agent system, Knowledge Graph, Vector Search, MCP integration |
| Originality | Proactive life-awareness; no existing scheduler knows your life |
| Potential impact | Works for any user across any life domain |
| Design & UX | Zero onboarding; proactive suggestions surface naturally in chat |

---

*DayPilot — Google Cloud Rapid Agent Hackathon 2026*