from pydantic import BaseModel, Field
from .schedule import ScheduleTask


class RealtimeInput(BaseModel):
    user_id: str
    current_schedule: list[ScheduleTask] = Field(default_factory=list)
    trigger: str                     # "new_event" | "location_change" | "task_overrun" | "energy_update"
    trigger_detail: str              # human-readable description of what changed


class RealtimeOutput(BaseModel):
    what_changed: list[str] = Field(default_factory=list)
    dropped_tasks: list[str] = Field(default_factory=list)
    added_tasks: list[str] = Field(default_factory=list)
    updated_schedule: list[ScheduleTask] = Field(default_factory=list)
    message: str = ""                # user-facing explanation of changes
