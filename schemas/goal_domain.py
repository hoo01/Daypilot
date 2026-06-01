from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel


class SubTask(BaseModel):
    sub_task_id: str
    goal_id: str
    title: str
    estimated_minutes: int
    priority: str                       # "high" | "medium" | "low"
    deadline: date
    preferred_time_of_day: str          # "morning" | "afternoon" | "night" | "flexible"
    can_split: bool
    is_completed: bool
    completed_at: Optional[datetime] = None
    planned_date: Optional[date] = None  # set by Schedule Agent via /v1/events/subtask-scheduled


class Goal(BaseModel):
    goal_id: str
    user_id: str
    title: str
    goal_type: str                      # "weekly" | "daily" | "long_term"
    status: str                         # see VALID_GOAL_STATUSES
    created_at: datetime
    deadline: date
    progress_percent: float             # 0.0 – 100.0
    sub_tasks: list[SubTask]
    feasibility_score: float
    feasibility_note: str
    total_effort_minutes: int
    suggested_blocks_count: int
    suggested_split_ratio: list[float]


VALID_GOAL_STATUSES = {
    "CREATED", "IN_PROGRESS", "COMPLETED", "PARTIALLY_COMPLETED", "OVERDUE", "ABANDONED"
}


class EventLogEntry(BaseModel):
    event_id: str
    event_type: str        # "overdue" | "subtask_scheduled" | "subtask_completed" | "daily_output"
    goal_id: str
    sub_task_id: Optional[str] = None
    payload: dict
    received_at: datetime
    processed_at: Optional[datetime] = None
    status: str            # "processing" | "processed" | "partial" | "failed"
    warnings: list[str] = []
