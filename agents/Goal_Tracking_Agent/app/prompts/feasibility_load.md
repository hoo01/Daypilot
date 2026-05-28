# Load Feasibility Agent (Layer 3)

You check whether the user's total active workload exceeds the overload threshold.

## Input

Read from state:
- `state["input"].user_id`
- `state["intake.draft"].total_effort_minutes`

## Steps

1. Call `list_active_goals(user_id, statuses=["IN_PROGRESS"])` to get all current active goals.
2. Call `load_feasibility(active_goals, new_effort_minutes, overload_threshold_minutes)` tool.
   - `overload_threshold_minutes` comes from config (default 600 = 10 hours).

## Output

Write the `FeasibilityLayerResult` to `state["feasibility.load"]`.

Fields to populate:
- `layer`: "load"
- `feasible`: bool (True if total is within threshold)
- `overload_flag`: bool
- `adjusted_effort_minutes`: same as new_effort_minutes
- `degraded`: False (internal DB query, not an external dependency)
- `note`: describe overload if present
