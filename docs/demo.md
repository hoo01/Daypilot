## Demo 脚本

### [0:00–0:12] Hook

**Screen:** Black

**Voiceover:**
> "What if your AI knew what mattered to you — before you had to say it?"

**Action:** 0.5s pause → DayPilot dashboard appears (schedule still empty) → right sidebar's three insight cards — "Today at a glance," "Health," "Mood check" — fade/slide in one by one

**Voiceover:**
> "This is DayPilot."

---

### [0:12–0:30] Cold Start

**Screen:** First login screen → Google OAuth authorization → progress bar fills → Knowledge Graph nodes emerge and connect

**Voiceover:**
> "First login. No onboarding form. DayPilot reads what you've already written about yourself — your calendar, your contacts, your inbox. You've already told the world who you are. DayPilot just listens."

---

### [0:30–0:50] Scene Setup

**Screen:** Browser opens DayPilot chat interface — Wednesday morning

**Subtitle:**
> It's Wednesday. Kai opens his laptop. He hasn't planned his day. DayPilot already knows about his class, his goal, and his anniversary next week. He didn't tell it any of this today.

---

### [0:50–1:40] Core Demo

**Screen:** Kai types:
```
"What should I focus on today?"
```
→ Send → **"DayPilot is thinking about your day…" 加载动画（覆盖 ~20-30s 真实生成时间）**
→ 回复淡入：先几句 proactive insight，紧接展开完整当日 schedule

**Response:**
> "Here's what you should focus on today — you have 4 Leetcode problems left this week (on track!), your 3-month anniversary with Mia is in 8 days, your favorite artist's tickets go on sale in 3 days, and **your ML class is at the library from 2–4 PM** — I've already built today's plan around it."

**Screen 配合：** 镜头聚焦 insight → 1-2s 后展开完整 schedule，定格在 "2:00 PM – 4:00 PM: ML class at library"

**Final subtitle:**
> He said nothing about his class today. DayPilot didn't just remember it — it already built his day around it.

---

### [1:40–2:00] Feedback Loop

**Screen:** Kai marks Leetcode incomplete → types:
```
"yes reschedule it"
```
→ DayPilot confirms → tomorrow's schedule updates in real time

**Subtitle:**
> That evening, Kai didn't finish his Leetcode. He marked it incomplete. DayPilot moved it to tomorrow. Closed loop.

---

### [2:00–2:20] Location Awareness

**Screen:** 7PM — an unprompted message appears from DayPilot:
> "Looks like you're still home — did dinner with Mia get rescheduled? Want me to find another time this week?"

**Subtitle:**
> DayPilot noticed Kai never left for dinner. It didn't wait to be asked. It doesn't just manage your schedule. It notices your life.

---

### [2:20–2:45] Technical Architecture

**Screen:** `docs/arch.html` — agents light up one by one

**Voiceover:**
> "DayPilot runs on a multi-agent system. Before every response, three context streams load in parallel — goal progress, relationship calendar, and health state. A Reasoning Agent checks in every day without being asked. A Geo Agent calculates when you need to leave. A Knowledge Graph in MongoDB remembers your life. Gemini doesn't just get a question. It gets your life."

---

### [2:45–3:00] Closing

**Screen:** Black background — DayPilot logo fades in — GitHub link appears

**Tech stack:**
> Google ADK · Gemini 2.5 Flash · MongoDB Atlas + MCP

**Final line (hold 5s):**
> "Your calendar knows your meetings. DayPilot knows your life."