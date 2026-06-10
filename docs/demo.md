启动 .\start-dev.ps1
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
> It's Wednesday. Kai opens his laptop. He hasn't planned his day. DayPilot already knows about his class, his workout, and the commute he'll need to get there. He didn't tell it any of this today.

---

### [0:50–2:00] Core Demo

**Screen:** Kai types:
```
"What should I focus on today?"
```
→ Send → **"DayPilot is thinking about your day…" 加载动画（覆盖 ~20-30s 真实生成时间）**
→ 回复淡入：先几句 proactive insight，紧接展开完整当日 schedule

**Response:**
> "Here's what you should focus on today — you've got Leetcode practice this morning to keep your streak going, and **your ML class is at Leavey Library from 2–4 PM — I've already mapped your commute there and lined up the gym right after**. I've built today's plan around all of it."

**Screen 配合：** 镜头聚焦 insight → 1-2s 后展开完整 schedule，定格在 "2:00 PM – 4:00 PM: ML Class @ Leavey Library"，右侧 Map & Commute 卡片显示 "Leave by ... · 25 min · Leavey Library"

**Final subtitle:**
> He said nothing about his class today. DayPilot didn't just remember it — it already mapped his route and built his day around it.

---

### [2:00–2:20] Feedback Loop

**Screen:** Kai marks Leetcode incomplete → types:
```
"yes reschedule it"
```
→ DayPilot confirms → tomorrow's schedule updates in real time

**Subtitle:**
> That evening, Kai didn't finish his Leetcode. He marked it incomplete. DayPilot moved it to tomorrow. Closed loop.

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