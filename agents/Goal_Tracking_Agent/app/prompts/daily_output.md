# Daily Output Builder

You assemble one GoalsOutput per active goal for all users (or a specific user_id if provided).

## Steps

1. Call `list_active_goals(user_id, statuses=["CREATED", "IN_PROGRESS", "OVERDUE"])`.
2. For each goal:
   a. Compute remaining effort: `total_effort_minutes * (1 - progress_percent / 100)`.
   b. Determine urgency based on deadline proximity:
      - deadline today or past → "high"
      - deadline within 3 days → "medium"
      - otherwise → "low"
   c. For each sub-task that is not yet completed, create a `GoalSubTask` with fields:
      `title`, `estimated_minutes`, `priority`, `deadline`, `preferred_time_of_day`, `can_split`.
      **CRITICAL: Never include `planned_date` in GoalSubTask. The validator will raise ValueError.**
   d. Assemble `GoalsOutput` with `feasibility_score`, `feasibility_note`, `suggested_blocks_count`,
      `suggested_split_ratio`, `urgency`, `daily_sub_tasks`.

3. Write the full list to `state["output.daily"]`.
4. Persist each GoalsOutput to the event_log collection as `event_type="daily_output"`.

## Schema Enforcement

Before writing any GoalSubTask, validate that it contains ONLY:
- title, estimated_minutes, priority, deadline, preferred_time_of_day, can_split

If planned_date appears in any sub-task source data, strip it before creating GoalSubTask. Log a warning if this occurs.
