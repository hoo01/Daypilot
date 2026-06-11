# DayPilot Demo Script v2
> Target: 3 minutes | Track: Google Cloud Rapid Agent Hackathon — Dynatrace Track
> Last updated: 2026-06-10

---

## Time Breakdown

| Segment | Content | Duration |
|---------|---------|----------|
| 0:00–0:15 | Problem Hook | 15s |
| 0:15–1:25 | Core Demo Flow | 70s |
| — | ↳ Three proposals + pick one | 15s |
| — | ↳ Mid-day replanning (surprise meeting) | 15s |
| — | ↳ Evening feedback loop | 10s |
| 1:25–2:10 | Google Cloud Architecture | 45s |
| 2:10–2:50 | Dynatrace Observability + MCP | 40s |
| 2:50–3:00 | Closing | 10s |

---

## 0:00–0:20 — Problem Hook

**Screen:** Black. White text appears line by line.

**Voiceover:**
> "Your calendar knows your meetings. Your fitness app knows you're tired. Google Maps knows the traffic. But none of them talk to each other — and none of them know what matters to you today."

**Visual:** Three isolated app icons (Calendar / Health / Maps) with no connections between them.

**Voiceover:**
> "DayPilot connects all of it — and thinks for you."

---

## 0:20–1:10 — Core Demo Flow

**Screen:** DayPilot opens. Kai's schedule interface — Wednesday morning, schedule not yet built.

**Subtitle:**
> Wednesday morning. Kai opens DayPilot. He hasn't planned his day.

**Kai types:**
```
What should I focus on today?
```

**Screen:** "Planning your day…" loading indicator appears. Agent activity panel shows agents firing in parallel:
- `Health Agent` — reading sleep + HRV data
- `Geo Agent` — calculating commute
- `Goal Agent` — checking Leetcode streak

**Voiceover:**
> "Behind the scenes: a Health Agent reads his sleep data. A Geo Agent calculates his commute. A Goal Agent checks his streak. All in parallel. In under 3 seconds."

**DayPilot responds — three proposals appear side by side:**

> **Option A — Deep Work First**
> Morning: Leetcode (keep the streak) → Afternoon: ML class @ Leavey 2–4 PM → Evening: Gym
>
> **Option B — Recovery Day**
> Light morning (HRV low today) → ML class → Skip gym, rest
>
> **Option C — Compressed**
> Leetcode + gym before noon → Free afternoon before ML class

**Screen:** Three proposal cards, Kai clicks **Option A**.

**Schedule populates.** ML class block shows commute data automatically.

**Screen focus:** Map & Commute card expands — "Leave by 1:35 PM · 25 min · Leavey Library"

---

**Mid-morning — unexpected change:**

Kai types:
```
Just got a meeting 2pm–3pm
```

**Screen:** "Replanning…" → Schedule updates in real time — ML class shifts, commute recalculated, gym block moves.

**DayPilot responds:**
> "Got it — I've moved your ML class to 3–5 PM and pushed the gym to 5:30. Leave by 2:50 PM for the new slot. Leetcode is still this morning."

**Voiceover:**
> "One message. The entire day restructures around the new constraint."

---

**That evening:** Kai marks Leetcode incomplete → types:
```
yes reschedule it
```
→ Tomorrow's schedule updates in real time.

**Subtitle:**
> He never configured anything. DayPilot learned his patterns, offered choices, and adapted when life changed.

---

## 1:10–1:25 — Google Cloud Stack

**Screen:** `google_cloud_stack.html` — three cards fade in one by one.

**Voiceover:**
> "We used Google ADK to wire together a team of AI agents that coordinate your entire day."
> "Gemini is the brain — it reads your context and decides what actually matters."
> "We shipped on Cloud Run — one container, zero ops, live on Google infrastructure."
> "From agent logic to AI reasoning to live deployment — it's all Google Cloud."

---

## 1:25–2:00 — Google Cloud Architecture

**Screen:** `arch.html` — agents light up one by one as each is named.

**Voiceover:**
> "DayPilot is built on **Google Agent Development Kit**. A Coordinator Agent orchestrates six specialized sub-agents — Health, Geo, Goals, Memory, Relationship, and Schedule."

**Screen:** Coordinator node with six child agent nodes lighting up.

**Voiceover:**
> "Every LLM call runs through **Gemini 2.5 Flash** on Vertex AI. The entire backend is deployed on **Google Cloud Run** — serverless, auto-scaling, zero infrastructure management."

**Screen:** Cloud Run deployment dashboard or architecture diagram.

**Voiceover:**
> "The Coordinator doesn't just forward your message to Gemini. Before Gemini ever sees it, health state, goal progress, and relationship context are all pre-loaded in parallel. Gemini gets context, not just a prompt."

**Screen:** Code snippet — `asyncio.gather` preload block (4–5 lines, readable font).

---

## 2:00–2:45 — Dynatrace Observability + MCP

### Layer 1 — Passive Telemetry (0:00–0:15 of this segment)

**Screen:** Dynatrace Distributed Traces dashboard — list of `POST /chat/` and `GET /schedule/today` requests.

**Voiceover:**
> "Every agent tool call, every Gemini invocation, every health pipeline node is traced end-to-end via OpenTelemetry — exported directly to Dynatrace."

**Screen:** Click into a `POST /chat/` trace — waterfall expands:
```
chat.handle_request
  └─ coordinator.preload_context
       ├─ tool.read_user_context       (Xms)
       ├─ tool.retrieve_relevant_memories (Xms)
       └─ health.run_pipeline          (Xms)
  └─ tool.plan_schedule               (Xms)
  └─ genai.generate                   (Xms)
```

**Voiceover:**
> "You can see exactly which agent caused a slow response — down to the millisecond."

---

### Layer 2 — MCP Active Self-Monitoring (0:15–0:45 of this segment)

**Screen:** Cut back to DayPilot chat interface.

**Subtitle:**
> But DayPilot doesn't just send data to Dynatrace. It reads it.

**Kai types:**
```
How's your performance looking?
```

**Screen:** DayPilot responds (Coordinator queries Dynatrace via MCP):
> "Checking... Average response time: 2.1s. The health pipeline is the main contributor at 1.4s. No errors in the last hour. Token usage is nominal."

**Voiceover:**
> "Via the **Dynatrace MCP Server**, DayPilot's Coordinator Agent queries its own performance telemetry in natural language — and reasons about it. The AI watches itself."

---

## 2:45–3:00 — Closing

**Screen:** Black background. DayPilot logo fades in.

**Tech stack (on screen):**
> Google ADK · Gemini 2.5 Flash · Cloud Run · Dynatrace MCP

**Final line (hold 5s):**
> "DayPilot doesn't manage your calendar. It manages your day."

---

## Pre-Recording Checklist

- [ ] MCP OAuth error resolved — `How's your performance?` returns real Dynatrace data
- [ ] `arch.html` agent nodes animate correctly
- [ ] Demo account (`daypilot.demo@gmail.com`) has Kai's schedule seeded
- [ ] Map & Commute card shows live route for ML class
- [ ] Cloud Run deployment live with public URL
- [ ] Dark theme enabled for recording (`[data-theme="dark"]`)
