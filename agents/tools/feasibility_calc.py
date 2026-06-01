from dataclasses import dataclass, field
from typing import Optional
from schemas.goal_domain import Goal


@dataclass
class FeasibilityLayerResult:
    layer: str                              # "time" | "habit" | "load"
    feasible: bool
    available_minutes: Optional[int] = None
    adjusted_effort_minutes: Optional[int] = None
    overrun_ratio: Optional[float] = None
    overload_flag: Optional[bool] = None
    degraded: bool = False
    note: str = ""


_FALLBACK_OVERRUN_RATIOS: dict[str, float] = {
    "weekly": 0.30,
    "long_term": 0.10,
    "daily": 0.05,
}

_MEMORY_KEYWORDS: dict[str, str] = {
    "coding": "weekly",
    "leetcode": "weekly",
    "problem": "weekly",
    "writing": "long_term",
    "reading": "long_term",
    "essay": "long_term",
    "paper": "long_term",
}


def _parse_overrun_from_memory(memory_context: str, goal_type: str) -> float:
    import re

    lower = memory_context.lower()
    patterns = [
        r"(\d+(?:\.\d+)?)\s*%\s*slower",
        r"overrun.{0,10}?(\d+(?:\.\d+)?)\s*%",
        r"(\d+(?:\.\d+)?)\s*%\s*longer",
        r"overrun_ratio\s*[=:]\s*(\d+(?:\.\d+)?)",
    ]
    for pattern in patterns:
        m = re.search(pattern, lower)
        if m:
            return float(m.group(1)) / 100.0

    return _FALLBACK_OVERRUN_RATIOS.get(goal_type, 0.10)


def time_feasibility(
    total_effort_minutes: int,
    remaining_days: int,
    free_minutes: Optional[int],
) -> FeasibilityLayerResult:
    """Layer 1: check if available calendar time covers total effort."""
    if free_minutes is None:
        return FeasibilityLayerResult(
            layer="time",
            feasible=True,
            available_minutes=None,
            adjusted_effort_minutes=total_effort_minutes,
            degraded=True,
            note="calendar_slots_empty",
        )

    feasible = free_minutes >= total_effort_minutes
    note = "" if feasible else (
        f"Need {total_effort_minutes} min but only {free_minutes} min available "
        f"over {remaining_days} days (short by {total_effort_minutes - free_minutes} min)"
    )
    return FeasibilityLayerResult(
        layer="time",
        feasible=feasible,
        available_minutes=free_minutes,
        adjusted_effort_minutes=total_effort_minutes,
        degraded=False,
        note=note,
    )


def habit_feasibility(
    total_effort_minutes: int,
    memory_context: str,
    goal_type: str,
    deadline_days: int,
) -> FeasibilityLayerResult:
    """Layer 2: adjust effort using historical behavioral context."""
    no_history = not memory_context.strip()
    overrun_ratio = _parse_overrun_from_memory(memory_context, goal_type)
    adjusted = int(total_effort_minutes * (1 + overrun_ratio))
    feasible = adjusted <= deadline_days * 8 * 60

    base_note = "no_memory_baseline; using LLM general estimates" if no_history else ""
    infeasible_note = (
        f"Adjusted effort {adjusted} min exceeds available window for {deadline_days}-day deadline"
        if not feasible else ""
    )
    note = "; ".join(filter(None, [base_note, infeasible_note]))

    return FeasibilityLayerResult(
        layer="habit",
        feasible=feasible,
        adjusted_effort_minutes=adjusted,
        overrun_ratio=overrun_ratio,
        degraded=False,
        note=note,
    )


def load_feasibility(
    active_goals: list[Goal],
    new_effort_minutes: int,
    overload_threshold_minutes: int,
) -> FeasibilityLayerResult:
    """Layer 3: check if total active workload exceeds the overload threshold."""
    existing_effort = sum(
        g.total_effort_minutes
        for g in active_goals
        if g.status == "IN_PROGRESS"
    )
    total = existing_effort + new_effort_minutes
    overload = total > overload_threshold_minutes
    note = (
        f"Total active effort {total} min exceeds threshold {overload_threshold_minutes} min"
        if overload else ""
    )
    return FeasibilityLayerResult(
        layer="load",
        feasible=not overload,
        overload_flag=overload,
        adjusted_effort_minutes=new_effort_minutes,
        degraded=False,
        note=note,
    )


def synthesize_feasibility(
    time_result: FeasibilityLayerResult,
    habit_result: FeasibilityLayerResult,
    load_result: FeasibilityLayerResult,
) -> tuple[float, str]:
    """Combine all three layer results into a (feasibility_score, note) pair.

    Scoring weights:
      time infeasible  → -0.3
      habit infeasible → -0.2
      load overloaded  → -0.15
      any degraded     → cap at 0.7
    """
    score = 1.0

    if not time_result.feasible:
        score -= 0.3
    if not habit_result.feasible:
        score -= 0.2
    if load_result.overload_flag:
        score -= 0.15

    notes: list[str] = []
    if time_result.note:
        notes.append(f"[time] {time_result.note}")
    if habit_result.note:
        notes.append(f"[habit] {habit_result.note}")
    if load_result.note:
        notes.append(f"[load] {load_result.note}")

    any_degraded = time_result.degraded or habit_result.degraded or load_result.degraded
    if any_degraded:
        score = min(score, 0.7)
        notes.append("Note: calendar availability could not be verified; score is capped at 0.7.")

    score = round(max(0.0, min(1.0, score)), 2)

    if score < 0.7 and not notes:
        reasons: list[str] = []
        if not time_result.feasible:
            reasons.append("insufficient calendar time")
        if not habit_result.feasible:
            reasons.append("adjusted effort exceeds deadline window")
        if load_result.overload_flag:
            reasons.append("active workload overloaded")
        notes.append("; ".join(reasons) or "feasibility score below threshold")

    combined_note = " | ".join(notes) if score < 0.7 or any_degraded else ""
    return score, combined_note
