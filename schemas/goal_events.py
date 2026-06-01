from datetime import datetime
from pydantic import BaseModel


class OverdueTaskRef(BaseModel):
    sub_task_id: str
    goal_id: str
    start_time: datetime   # originally-scheduled start from ScheduleAgent output; NOT planned_date


class OverdueNotification(BaseModel):
    event_id: str          # caller-generated UUID; idempotency key
    overdue_tasks: list[OverdueTaskRef]


class SubtaskScheduledEvent(BaseModel):
    event_id: str
    sub_task_id: str
    goal_id: str
    start_time: datetime   # scheduled start from Schedule Agent output


class SubtaskCompletedEvent(BaseModel):
    event_id: str
    sub_task_id: str
    goal_id: str
    completed_at: datetime


class EventAck(BaseModel):
    status: str            # "acknowledged" | "already_processed" | "partial"
    processed_count: int
    warnings: list[str]    # non-empty when sub_task_ids were unknown
