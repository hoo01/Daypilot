# PRD: Goal Tracking Agent
**Project:** DayPilot Multi-Agent Scheduling System  
**Agent Owner:** Astrid  
**Version:** 0.2  
**Last Updated:** 2026-05-27  
**Status:** All TBDs resolved — ready for implementation

---

## 1. Overview

The Goal Tracking Agent is responsible for managing the full lifecycle of user goals within the DayPilot system. It handles goal intake, validation, sub-task decomposition, feasibility assessment, progress tracking, and behavioral pattern learning. It serves as the primary source of goal-related context for the Schedule Planning Agent.

### Design Principle
The Goal Tracking Agent is an **advisor, not a decision-maker**. It surfaces insights, warnings, and proposals to the user, but the user retains full control over all final decisions.

### Architecture Pattern
The Goal Tracking Agent follows a **request-response, event-driven** model. It does not poll or maintain continuous state loops. It is activated by the Coordinator Agent when user intent is classified as goal-related, and reacts to overdue notifications pushed by the Schedule Planning Agent.

---

## 2. Scope

### In Scope
- Goal creation, validation, and structured storage
- Sub-task decomposition and effort estimation
- Feasibility checking (time, historical habit, and load dimensions)
- Progress tracking and behind-schedule detection
- Overdue and abandonment handling with user prompting
- Weekly behavioral pattern summarization and Memory writes
- Output generation for downstream consumption by the Schedule Planning Agent

### Out of Scope
- Daily time-slot scheduling (owned by Schedule Planning Agent)
- Time-conflict resolution between tasks (owned by Schedule Planning Agent)
- Health/energy data analysis (owned by Health & Energy Agent)
- Real-time schedule disruption handling (owned by Real-time Adjustment Agent)
- Intent classification from raw user input (owned by Coordinator Agent)
- Polling or continuous schedule monitoring (event-driven only; no shared polling utility needed)

---

## 3. Goal Lifecycle

A goal transitions through the following states:

```
CREATED → IN_PROGRESS → COMPLETED
                      → PARTIALLY_COMPLETED
                      → OVERDUE (→ user decides: replan or ABANDONED)
                      → ABANDONED
```

### State Transition Rules

| Transition | Trigger |
|---|---|
| CREATED → IN_PROGRESS | Schedule Agent confirms at least one sub-task has been added to the daily plan (status update notification) |
| IN_PROGRESS → COMPLETED | All sub-tasks are checked off by the user |
| IN_PROGRESS → PARTIALLY_COMPLETED | Deadline reached, progress > 0% but < 100% |
| IN_PROGRESS → OVERDUE | Deadline reached, progress = 0% |
| ANY → ABANDONED | User explicitly cancels the goal |
| OVERDUE → IN_PROGRESS | User chooses to replan after overdue prompt |

**Note:** OVERDUE and ABANDONED are semantically distinct. Overdue means the user failed to meet the deadline without a conscious decision to stop. Abandoned means the user made an active choice to discontinue the goal, typically after recognizing it as too difficult or no longer relevant.

---

## 4. Core Modules

### 4.1 Goal Intake Mode

**Trigger:** The Coordinator Agent identifies the user's intent as goal-related and delegates control to the Goal Tracking Agent with a structured activation payload. The Goal Tracking Agent does **not** perform raw intent classification itself — this is entirely owned by the Coordinator Agent, which is the only agent that interacts directly with the user's raw chat input (ReAct pattern).

Once activated, the Goal Tracking Agent **takes over the conversation window** for a multi-turn guided intake session. The session continues until a complete, validated goal specification has been written to the database.

**Goal Intake Flow:**
```
Coordinator detects goal intent → activates Goal Tracking Agent
→ Goal Tracking Agent takes over conversation
→ Multi-turn guided Q&A (see 4.2 for validation rules)
→ Goal spec confirmed by user
→ Write goal to database
→ Auto-generate sub-tasks (see 4.3)
→ Present sub-tasks to user for confirmation
→ Exit Goal Intake Mode, return control to Coordinator
```

**Conversation Style:** The agent uses guiding questions rather than direct rejection. Instead of saying "your goal is too vague," it asks:
- *"What would count as completing this goal?"*
- *"When do you need to finish this by?"*
- *"How many [tasks/pages/problems] are you aiming for?"*

---

### 4.2 Goal Validation

Before a goal is accepted into the system, it must pass validation across three dimensions:

| Dimension | Requirement | Example Fail | Example Pass |
|---|---|---|---|
| Quantifiable | Clear completion criteria | "study more" | "solve 10 Leetcode problems" |
| Time-bound | Explicit deadline | "finish soon" | "by this Friday" |
| Appropriate granularity | Not too abstract | "become a better person" | "finish the assignment draft" |

If any dimension fails, the agent re-enters the guided Q&A loop and does **not** accept the goal until all three are satisfied.

---

### 4.3 Sub-task Decomposition

Once a goal passes validation, the agent automatically decomposes it into sub-tasks.

**Rules:**
- Quantifiable goals (e.g., "solve 10 problems") → generate N checkboxes directly
- Descriptive goals (e.g., "write a 5-page paper draft") → LLM decomposes into logical sub-tasks (e.g., outline, draft section 1, draft section 2, review)
- User can add, remove, or rename sub-tasks via chat after generation

**Progress Calculation:**  
Progress is based purely on sub-task completion, not time elapsed.

```
progress_percent = (checked_sub_tasks / total_sub_tasks) × 100
```

All sub-tasks are weighted equally in v1. Weighted sub-tasks (by difficulty or importance) are deferred to v2.

**Completion Determination:**  
A sub-task is marked complete when the user checks it off manually. Behavioral inference (e.g., detecting gym attendance from location data) is explicitly out of scope.

---

### 4.4 Feasibility Check

Feasibility is evaluated at two moments:
1. **At goal creation** — before the goal is written to the database
2. **Periodically during tracking** — triggered by an overdue notification from the Schedule Agent, after which feasibility is recalculated

**Health data input:** The Coordinator Agent provides `HealthOutput` (energy score, focus window, cognitive load) as part of the structured input payload passed to the Goal Tracking Agent. The Goal Tracking Agent does **not** call the Health & Energy Agent directly — it consumes the pre-assembled data from the Coordinator, consistent with the same pattern used by the Schedule Planning Agent.

**Three evaluation layers:**

#### Layer 1: Time Feasibility (no Memory required)
Pure calculation based on deadline, estimated total effort, and calendar availability.

```
available_time = remaining_days × avg_daily_free_hours (from Calendar API)
feasible = available_time >= total_effort_minutes / 60
```

#### Layer 2: Habit Feasibility (requires Memory read)
Reads the user's historical goal completion patterns from the Memory Agent.

Example logic:
- Memory indicates user typically takes 40% longer than estimated for similar goals
- Adjusted estimate is applied to the feasibility check
- If the adjusted estimate makes the goal infeasible, a proposal is generated

**First-time users (no Memory data):**  
Falls back to LLM-based general estimates using common knowledge (e.g., average time to solve a Leetcode medium problem is ~30–45 minutes).

#### Layer 3: Load Feasibility (internal database only)
Counts the total effort across all currently active goals to detect overload.

```
total_active_effort = sum(remaining_effort for all IN_PROGRESS goals)
overload_flag = total_active_effort > configurable_threshold
```

**Health conflict check:**  
If the Coordinator-provided `HealthOutput` indicates low energy or a focus window mismatch (e.g., user wants to do deep work at a time the Health Agent flags as low cognitive capacity), the Goal Tracking Agent flags this conflict and adjusts its `suggested_blocks` accordingly before passing output to the Schedule Agent. The Goal Agent resolves goal-level conflicts; the Schedule Agent resolves time-slot conflicts only.

**When infeasibility is detected**, the agent generates a proposal with concrete options:

```
Your goal: "Solve 20 Leetcode problems in 7 days"
Based on your history, similar goals typically take ~40% longer than planned.
Suggested adjustments:
  A. Extend deadline to 10 days
  B. Reduce target to 14 problems
  C. Keep original goal — I will send daily reminders to help you stay on track
How would you like to proceed?
```

If the user rejects all proposals and insists on the original goal, the agent proceeds without modification and relies on normal progress tracking and reminders.

---

### 4.5 Progress Tracking & Behind-Schedule Detection

The Goal Tracking Agent is **event-driven** — it does not poll independently. It reacts to overdue task notifications pushed by the Schedule Planning Agent. No shared polling utility is needed.

**Inbound notification from Schedule Agent:**

The Schedule Agent's `ScheduleTask` schema uses `task_id` as its internal identifier, which is auto-generated by Gemini and has no inherent link to the Goal Agent's `sub_task_id`. To close this gap, the Schedule Agent must embed the Goal Agent's `sub_task_id` and `goal_id` in either the `task_id` or `notes` field of each scheduled task at the time of scheduling. This is a required integration contract between the two agents.

The `planned_date` field is not needed in the overdue notification — it is redundant and can be derived directly from `start_time` in the Schedule Agent's output.

**Overdue notification format (inbound from Schedule Agent):**
```json
{
  "overdue_tasks": [
    {
      "sub_task_id": "t2",
      "goal_id": "g001",
      "start_time": "2026-05-27T21:00:00"
    }
  ]
}
```

**Upon receiving this notification, the Goal Tracking Agent:**
1. Updates the corresponding goal's progress
2. Recalculates feasibility given the new progress state
3. Triggers a user-facing reminder if the goal is now at risk

**Reminder format (example):**
> *"You're behind on your goal 'Finish assignment draft' — 2 of 5 sub-tasks remain and your deadline is tomorrow. Would you like to replan or adjust the goal?"*

**IN_PROGRESS trigger (inbound from Schedule Agent):**

When the Schedule Agent successfully schedules a sub-task into the daily plan for the first time, it sends a status update to the Goal Agent:
```json
{
  "scheduled_tasks": [
    {
      "sub_task_id": "t1",
      "goal_id": "g001",
      "start_time": "2026-05-27T21:00:00"
    }
  ]
}
```
The Goal Agent uses this to transition the goal from CREATED → IN_PROGRESS and to set `planned_date` on the corresponding `SubTask` record.

---

### 4.6 Overdue & Abandonment Handling

When a goal reaches OVERDUE state, the agent prompts the user:

> *"Your goal '[goal name]' has passed its deadline. Would you like to replan it, or mark it as abandoned?"*

- **Replan** → Goal returns to IN_PROGRESS; deadline is updated; updated `GoalsOutput` is sent to the Schedule Agent for re-planning
- **Abandon** → Goal is archived with status ABANDONED; event is recorded for the next weekly Memory write

The agent does not automatically archive or delete goals — all state changes require explicit user confirmation.

---

### 4.7 Memory Read & Write

#### Reading from Memory
The Coordinator Agent includes relevant Memory context in the input payload passed to the Goal Tracking Agent (consistent with the pattern used for Health data). The Goal Tracking Agent uses this to inform:
- Feasibility assessments (historical completion rates, time estimation accuracy)
- Preferred working style (e.g., user tends to work in long focused blocks late at night)

#### Writing to Memory
Writes occur **once per week** as a batch summary. The agent analyzes the past week's goal completion data and distills behavioral patterns into compressed entries.

**Examples of what gets written:**
- Completion rate by goal type (coding, writing, fitness, etc.)
- Average overrun ratio (estimated vs. actual time)
- Abandonment patterns (goal types most frequently abandoned, deadline proximity at abandonment)
- Correlation between goal outcomes and energy levels (if Health data is available in payload)

**Write format (compressed summary):**
```
User typically completes Leetcode goals 30% slower than estimated.
Goals set with <3 days deadline have a 70% abandonment rate.
Recommend suggesting buffer time when user sets short-deadline coding goals.
```

---

## 5. Output Interface (to Schedule Planning Agent)

The Goal Tracking Agent outputs a structured payload for each active goal. This is consumed by the Schedule Planning Agent for daily plan generation.

```python
class GoalSubTask(BaseModel):
    title: str                    # e.g., "Solve 2 Leetcode Hard problems"
    estimated_minutes: int        # e.g., 90
    priority: str                 # "high" | "medium" | "low"
    deadline: date                # Latest date this sub-task must be completed
    preferred_time_of_day: str    # "morning" | "afternoon" | "night" | "flexible"
    can_split: bool               # Whether this sub-task can be further broken up

class GoalsOutput(BaseModel):
    goal_id: str
    urgency: str                        # "high" | "medium" | "low"
    feasibility_score: float            # 0.0 – 1.0
    feasibility_note: str               # Human-readable explanation if score < 0.7
    total_effort_minutes: int           # Total estimated remaining effort
    suggested_blocks_count: int         # Recommended number of work sessions
    suggested_split_ratio: list[float]  # e.g., [0.4, 0.4, 0.2] across remaining days
    daily_sub_tasks: list[GoalSubTask]  # Today's recommended sub-tasks
```

**Boundary clarification:**
- The Goal Tracking Agent outputs **constraints and recommendations** — deadline, total effort, priority, preferred time of day, feasibility score
- The Schedule Planning Agent decides **exactly when** each sub-task is scheduled — specific day, time slot, duration
- This eliminates circular communication: the Schedule Agent never needs to push back on specific dates assigned by the Goal Agent, since the Goal Agent never assigns specific dates

---

## 6. Input Interface (from Coordinator Agent)

The Goal Tracking Agent receives a structured input payload assembled by the Coordinator Agent. It never reads raw user chat directly.

```python
class GoalAgentInput(BaseModel):
    user_id: str
    intent: str                         # e.g., "add_goal" | "check_progress" | "update_goal"
    raw_user_message: str               # Original user message, for LLM context
    health: HealthOutput                # Pre-assembled from Health & Energy Agent
    memory_context: str                 # Relevant compressed memory entries
    calendar_free_slots: list[dict]     # Available time windows for feasibility check
```

---

## 7. Inter-Agent Interfaces Summary

| Direction | Counterpart | Type | Content |
|---|---|---|---|
| Inbound | Coordinator Agent | Activation payload | `GoalAgentInput` with health data, memory context, calendar slots |
| Outbound | Schedule Planning Agent | On update | `GoalsOutput` per active goal |
| Inbound | Schedule Planning Agent | Event notification | Overdue sub-task list with `sub_task_id`, `goal_id`, `start_time` |
| Inbound | Schedule Planning Agent | Status update | Sub-task scheduled → triggers CREATED → IN_PROGRESS |
| Read/Write | Memory Agent | Via Coordinator | Read: behavioral patterns; Write: weekly batch summary |
| Read | Calendar API | Direct | Available time slots for feasibility Layer 1 |

---

## 8. Data Model

```python
class Goal(BaseModel):
    goal_id: str
    user_id: str
    title: str                          # Validated, quantifiable goal description
    goal_type: str                      # "weekly" | "daily" | "long_term"
    status: str                         # See lifecycle states in Section 3
    created_at: datetime
    deadline: date
    progress_percent: float             # 0.0 – 100.0, computed from sub-task completion
    sub_tasks: list[SubTask]
    feasibility_score: float
    feasibility_note: str
    total_effort_minutes: int
    suggested_blocks_count: int
    suggested_split_ratio: list[float]

class SubTask(BaseModel):
    sub_task_id: str
    goal_id: str
    title: str
    estimated_minutes: int
    priority: str                       # "high" | "medium" | "low"
    deadline: date
    preferred_time_of_day: str          # "morning" | "afternoon" | "night" | "flexible"
    can_split: bool
    is_completed: bool
    completed_at: Optional[datetime]
    planned_date: Optional[date]        # Set when Schedule Agent confirms scheduling
```

---

## 9. Tools & Dependencies

| Tool | Access | Purpose |
|---|---|---|
| Calendar API | Read (direct) | Fetch available time slots for feasibility Layer 1 |
| Task Database | Read / Write | Persist and query goal and sub-task records |
| Memory Agent | Read / Write (via Coordinator) | Access and store user behavioral patterns |
| Gemini (LLM) | Core | Sub-task decomposition, feasibility estimation, proposal generation, user-facing message generation |

---

## 10. Tech Stack

### Core
| Layer | Technology |
|---|---|
| LLM | gemini-2.5-pro-preview / gemini-2.5-flash / gemini-2.5-flash-lite |
| Agent Framework | Google Cloud Agent Builder |
| Backend | Python + FastAPI |
| Database | MongoDB Atlas (Knowledge Graph) |
| Partner Track | MongoDB (Hackathon partner) |

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

## 11. Resolved Design Decisions

| # | Question | Resolution |
|---|---|---|
| Q1 | Who handles intent routing? | Coordinator Agent — it is the only agent with access to raw user input (ReAct pattern). Goal Agent receives structured `GoalAgentInput`, never raw chat. |
| Q2 | Does Goal Agent pull Health data directly or via Coordinator? | Via Coordinator — consistent with how Schedule Agent receives `HealthOutput`. Coordinator assembles all agent outputs before dispatching. |
| Q3 | Overdue notification format from Schedule Agent | `sub_task_id` + `goal_id` must be embedded in Schedule Agent's `task_id` or `notes` field at scheduling time. `planned_date` dropped — derived from `start_time`. |
| Q4 | Shared polling utility with Real-time Agent? | Not needed — both agents are event-driven (request-response). No continuous polling in the system. |
| Q5 | Weighted sub-task scoring? | Deferred to v2. V1 uses equal weighting: `progress = checked / total × 100`. No impact on Schedule Agent interface since it only consumes `priority` string. |
