# DayPilot Backend Handoff

## Current Status

The backend is fully functional. Core demo flow works end-to-end.

---

## How to Run

```bash
pip install -r requirements.txt
python scripts/seed_demo.py   # populate demo data
python main.py                # start server at http://localhost:8000
```

Test with Swagger UI: `http://localhost:8000/docs`

Demo message:
```json
POST /chat/
{
  "user_id": "demo_user",
  "message": "Good morning"
}
```

Expected response: proactively mentions Mia anniversary (8 days), artist tickets (3 days), Leetcode 6/10.

---

## What's Done

- **Chat endpoint** (`POST /chat/`) — coordinator agent with ADK `before_agent_callback` preloads user context in parallel before every turn
- **Memory system** — MongoDB Knowledge Graph + Atlas Vector Search (3072-dim embeddings) for semantic memory retrieval
- **Memory consolidation** — background task after each chat turn, compresses insights into vector embeddings
- **Schedule planning** — 3 daily strategies with constraint enforcement (locked blocks, calendar events, replan_from_time)
- **Goal tracking** — reads goal state + Gemini reasoning for urgency/suggestions
- **Relationship context** — surfaces upcoming dates with proactive suggestions
- **Real-time adjustment** — replans schedule when disruptions occur
- **Geo tool** — multi-segment commute calculation (Google Routes API)
- **Feedback loop** — `POST /schedule/feedback` for end-of-day task completion; uncompleted tasks stored as `pending_reschedule`, coordinator reschedules on next turn
- **OAuth flow** — Google OAuth (Calendar + Gmail + Contacts), cold-start ingestion
- **MCP integration** — MongoDB MCP server for direct Knowledge Graph queries

---

## One Remaining Issue

**Cold-start ingestion doesn't work locally (China network).**

The ingestion agent uses `httplib2` to call Google Calendar/Gmail/Contacts APIs. `httplib2` doesn't pick up system proxy settings, so it can't reach Google even with VPN on.

**Fix is already in the code** (`agents/ingestion.py` — proxy port 7897 hardcoded). Just needs testing on a machine where Google APIs are accessible directly (or deploy to a server outside China).

Workaround for demo: `scripts/seed_demo.py` pre-populates all demo data. The AI response is identical to what real ingestion would produce.

---

## Key Files

| File | Purpose |
|---|---|
| `agents/coordinator.py` | ADK coordinator + `before_agent_callback` |
| `agents/tools/` | All tool functions (goal, schedule, relationship, geo, memory, realtime) |
| `agents/memory.py` | MongoDB interface + vector embedding |
| `agents/ingestion.py` | Cold-start Google data ingestion |
| `api/routes/chat.py` | Chat endpoint + memory consolidation |
| `api/routes/schedule.py` | Schedule adjust + feedback endpoints |
| `api/routes/auth.py` | OAuth flow |
| `scripts/seed_demo.py` | Seed demo data (run before demo) |
| `docs/api.md` | API reference for frontend |

---

## Demo Data (seed_demo.py)

- **User:** `demo_user`
- **Mia** — partner, 3-month anniversary June 10
- **Favorite Artist** — tickets on sale June 5
- **ML Class** — 2PM-4PM at library today
- **Leetcode goal** — 6/10 done, deadline June 6
- **Focus window** — 9PM-1AM

---

## Environment Variables Needed

```
GEMINI_API_KEY=...
MONGODB_URI=...
MONGODB_DB_NAME=daypilot
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
```

Contact Yuqing for the actual values.