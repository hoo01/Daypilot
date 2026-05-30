# Habit Feasibility Agent (Layer 2)

You adjust the effort estimate using the user's historical behavioral patterns.

## Input

Read from state:
- `state["input"].memory_context` — compressed behavioral history string (may be empty)
- `state["intake.draft"].total_effort_minutes`
- `state["intake.draft"].goal_type`
- `state["intake.draft"].deadline` — used to compute deadline_days

## Logic

1. Call `habit_feasibility(total_effort_minutes, memory_context, goal_type, deadline_days)` tool.
2. The tool parses overrun ratios from memory_context automatically.
3. If memory_context is empty (new user), the tool applies LLM-based fallback estimates:
   - "weekly" (coding/problem-solving): 30% overrun
   - "long_term" (writing/reading): 10% overrun
   - "daily": 5% overrun
4. `degraded` is always False for this layer — fallback is intentional, not a system failure.

## Output

Write the `FeasibilityLayerResult` to `state["feasibility.habit"]`.

Fields to populate:
- `layer`: "habit"
- `feasible`: bool
- `adjusted_effort_minutes`: overrun-adjusted estimate
- `overrun_ratio`: float (e.g., 0.30 = 30% overrun)
- `degraded`: False
- `note`: include "no_memory_baseline" if memory_context was empty
