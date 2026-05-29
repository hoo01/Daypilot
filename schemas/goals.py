from datetime import date
from pydantic import BaseModel


class GoalsInput(BaseModel):
    """Input to Goal Tracking Agent."""
    user_id: str
    calendar_free_windows: list[str] = []


class GoalSubTask(BaseModel):
    """A specific actionable sub-task for today.
    
    Aligned with Goal Tracking Agent's app/schemas/output.py.
    Intentionally excludes planned_date — that lives on SubTask (domain)
    and is set by Schedule Agent, never returned by Goal Agent.
    """
    title: str
    estimated_minutes: int
    priority: str                    # "high" | "medium" | "low"
    deadline: date
    preferred_time_of_day: str       # "morning" | "afternoon" | "night" | "flexible"
    can_split: bool


class GoalsOutput(BaseModel):
    """Output from Goal Tracking Agent."""
    goal_id: str
    urgency: str                          # "high" | "medium" | "low"
    feasibility_score: float              # 0.0 – 1.0
    feasibility_note: str
    total_effort_minutes: int
    suggested_blocks_count: int
    suggested_split_ratio: list[float]
    daily_sub_tasks: list[GoalSubTask] = []