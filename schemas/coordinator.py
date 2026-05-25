from pydantic import BaseModel, Field
from .schedule import ScheduleOutput
from .relationship import RelationshipOutput


class CoordinatorInput(BaseModel):
    user_id: str
    message: str                     # raw user message or background trigger
    session_id: str | None = None


class CoordinatorOutput(BaseModel):
    reply: str                       # message back to user
    schedule: ScheduleOutput | None = None
    relationship_alerts: RelationshipOutput | None = None
    actions_taken: list[str] = Field(default_factory=list)  # e.g. ["calendar_event_created"]
