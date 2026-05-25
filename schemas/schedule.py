from pydantic import BaseModel, Field
from .health import HealthOutput
from .goals import GoalsOutput
from .relationship import RelationshipOutput
from .geo import GeoOutput


class ScheduleTask(BaseModel):
    time: str                        # e.g. "9PM"
    duration_min: int
    task: str
    location: str = "home"
    notes: str | None = None


class ScheduleStrategy(BaseModel):
    name: str                        # e.g. "Most Productive" | "Most Balanced"
    tasks: list[ScheduleTask] = Field(default_factory=list)
    summary: str = ""


class ScheduleInput(BaseModel):
    user_id: str
    date: str                        # ISO 8601 date
    health: HealthOutput | None = None
    goals: GoalsOutput | None = None
    relationship: RelationshipOutput | None = None
    geo: GeoOutput | None = None
    calendar_events: list[dict] = Field(default_factory=list)


class ScheduleOutput(BaseModel):
    date: str
    strategies: list[ScheduleStrategy] = Field(default_factory=list)
    recommended_strategy: str = "Most Productive"
