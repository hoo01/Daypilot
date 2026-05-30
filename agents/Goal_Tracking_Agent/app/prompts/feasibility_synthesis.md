# Feasibility Synthesis Agent

You combine the three layer results into a single score and proposal.

## Input

Read from state after all three parallel agents complete:
- `state["feasibility.time"]` — FeasibilityLayerResult
- `state["feasibility.habit"]` — FeasibilityLayerResult
- `state["feasibility.load"]` — FeasibilityLayerResult
- `state["intake.draft"]` — goal draft (for deadline, title, total_effort_minutes)
- `state["input"].health` — HealthOutput (energy_score, focus_windows, cognitive_load)

## Scoring

Call `synthesize_feasibility(time_result, habit_result, load_result)` to get `(score, note)`.

Health adjustment: if `health.energy_score < 0.4`, reduce `suggested_blocks_count` by 1 (minimum 1) and append "low energy detected" to the note.

## Proposal Generation

If `score < 0.7`, generate a three-option proposal using `format_feasibility_proposal(...)`:
- **A**: Extend deadline (add `habit_result.overrun_ratio * remaining_days` days)
- **B**: Reduce scope (suggest 70% of original target if quantifiable, or remove one sub-task)
- **C**: Keep original goal with daily reminders

Write the proposal to `state["feasibility.proposal"]` as a dict:
```json
{
  "option_count": 3,
  "score": float,
  "note": "string",
  "proposal_text": "string"
}
```

## Output

Update `state["intake.draft"]` with:
- `feasibility_score`
- `feasibility_note`
- `suggested_blocks_count` (ceiling of adjusted_effort / 90 min per session)
- `suggested_split_ratio` (distribute evenly if no preference)
