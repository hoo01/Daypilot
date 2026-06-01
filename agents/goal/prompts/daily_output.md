# Daily Output Builder

You assemble GoalsOutput objects for all active goals of a user (or all users).

# Trigger

Activated via `POST /v1/scheduled/daily-output`.

# For Each Active Goal

1. Call `list_active_goals(user_id)`.
2. For each goal, compute `urgency`:
   - `deadline - today <= 1 day`: "high"
   - `deadline - today <= 3 days`: "medium"
   - otherwise: "low"
3. Build a `GoalsOutput` with:
   - `goal_id`, `urgency`, `feasibility_score`, `feasibility_note`
   - `total_effort_minutes`, `suggested_blocks_count`, `suggested_split_ratio`
   - `daily_sub_tasks`: list of incomplete sub-tasks converted to `GoalSubTask` schema

# CRITICAL: GoalSubTask Schema

Each `GoalSubTask` MUST contain ONLY these fields:
- `title`
- `estimated_minutes`
- `priority`
- `deadline`
- `preferred_time_of_day`
- `can_split`

**Never include `planned_date` in GoalSubTask.** That field belongs to `SubTask` (domain) and must not appear in the output payload.

# Output

Write to `state["output.daily"]` as a list of `GoalsOutput` objects.
Also write each to `event_log` with `event_type="daily_output"` for Schedule Agent consumption.
