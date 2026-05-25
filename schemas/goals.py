from pydantic import BaseModel, Field


class GoalItem(BaseModel):
    goal: str
    progress: int
    target: int
    deadline: str              # ISO 8601 date
    urgency: str               # "low" | "medium" | "high"
    suggested_blocks: list[str] = Field(default_factory=list)


class GoalsInput(BaseModel):
    user_id: str
    calendar_free_windows: list[str] = Field(default_factory=list)


class GoalsOutput(BaseModel):
    goal_status: str           # "on_track" | "behind_schedule" | "completed"
    progress_percent: float    # 0–100
    urgency: str               # "low" | "medium" | "high"
    goals: list[GoalItem] = Field(default_factory=list)
    suggested_blocks: list[str] = Field(default_factory=list)
