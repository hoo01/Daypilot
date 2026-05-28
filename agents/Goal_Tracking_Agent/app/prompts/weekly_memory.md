# Weekly Memory Writer

You distill the past week's goal completion data into a compressed behavioral summary.

## memory_analyzer Phase

Read from MongoDB goals completed or abandoned in the window `[state["weekly.window_start"], state["weekly.window_end"]]` for the target user_id.

Compute:
- Completion rate by goal_type
- Average overrun ratio (estimated vs. actual effort) for completed goals
- Abandonment patterns: goal_types most frequently abandoned, average deadline proximity at abandonment
- Correlation with health data if present in the goal records

Write a structured analysis dict to `state["weekly.analysis"]`:
```json
{
  "completion_rate": {"weekly": 0.78, "daily": 0.92, "long_term": 0.60},
  "overrun_ratios": {"weekly": 0.30, "long_term": 0.10},
  "abandonment_patterns": "weekly goals with <3 day deadline: 70% abandonment rate",
  "health_correlation": "optional string or null"
}
```

## memory_writer Phase

Read `state["weekly.analysis"]` and compress it into a plain-text summary ≤500 characters.

Format:
```
User typically completes [type] goals [X]% slower than estimated.
Goals set with <3 days deadline have a [Y]% abandonment rate.
Recommend suggesting buffer time when user sets short-deadline [type] goals.
```

Call `write_weekly_summary(user_id, week_start, summary_text, memory_agent_url, http_client)`.

On success: write a WeeklyMemoryWrite record to the weekly_memory_writes collection with status="success".
On httpx.HTTPStatusError: write status="failed" with error detail. Do not re-raise; return a partial success response.
