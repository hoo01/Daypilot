from datetime import date
from pydantic import BaseModel, model_validator


class GoalSubTask(BaseModel):
    """Output sub-task schema sent to the Schedule Planning Agent.

    Intentionally excludes planned_date — that field lives only on SubTask
    (domain.py) and is set by the Schedule Agent, never returned by this service.
    """

    title: str
    estimated_minutes: int
    priority: str                   # "high" | "medium" | "low"
    deadline: date
    preferred_time_of_day: str      # "morning" | "afternoon" | "night" | "flexible"
    can_split: bool

    @model_validator(mode="before")
    @classmethod
    def reject_planned_date(cls, values: object) -> object:
        if isinstance(values, dict) and "planned_date" in values:
            raise ValueError(
                "GoalSubTask must not contain planned_date — "
                "that field belongs on SubTask (domain) only"
            )
        return values


class GoalsOutput(BaseModel):
    goal_id: str
    urgency: str                         # "high" | "medium" | "low"
    feasibility_score: float             # 0.0 – 1.0
    feasibility_note: str
    total_effort_minutes: int
    suggested_blocks_count: int
    suggested_split_ratio: list[float]
    daily_sub_tasks: list[GoalSubTask]
