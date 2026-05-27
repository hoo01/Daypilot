from pydantic import BaseModel, Field
from .health import HealthOutput
from .goals import GoalsOutput
from .relationship import RelationshipOutput
from .geo import GeoOutput


# ─────────────────────────────────────────────────────────
# Core building blocks
# ─────────────────────────────────────────────────────────

class ScheduleTask(BaseModel):
    """Single time block in a schedule."""
    task_id: str
    title: str
    start_time: str                    # ISO 8601, e.g. "2026-05-25T21:00:00"
    end_time: str                      # ISO 8601
    type: str                          # "deep_work" | "routine" | "break" | ...
    location: str | None = None
    notes: str | None = None


class CalendarEvent(BaseModel):
    """A real event pulled from Google Calendar."""
    id: str
    title: str
    start_time: str
    end_time: str
    location: str | None = None


class RecurringTask(BaseModel):
    """User's regular habits / commitments (for cold start)."""
    title: str
    type: str
    frequency: str                     # "daily" | "weekly" | "weekdays" | "weekends"
    day_of_week: int | None = None
    preferred_time: str | None = None
    duration_minutes: int
    priority: str | None = None


class UserPreferences(BaseModel):
    """Long-term user preferences."""
    preferred_work_hours: str = "late_night"
    commute_minutes: int = 30
    break_frequency: int = 90


# ─────────────────────────────────────────────────────────
# Strategy & Output
# ─────────────────────────────────────────────────────────

class ScheduleStrategy(BaseModel):
    """One scheduling option (e.g. Most Productive)."""
    name: str
    description: str = ""
    tasks: list[ScheduleTask] = Field(default_factory=list)
    total_focus_hours: float = 0.0
    reasoning: str = ""


# ─────────────────────────────────────────────────────────
# Input / Output
# ─────────────────────────────────────────────────────────

class ScheduleInput(BaseModel):
    """All inputs Schedule Agent needs to plan a day."""
    user_id: str
    date: str

    health: HealthOutput | None = None
    goals: GoalsOutput | None = None
    relationship: RelationshipOutput | None = None
    geo: GeoOutput | None = None

    calendar_events: list[CalendarEvent] = Field(default_factory=list)

    recurring_tasks: list[RecurringTask] = Field(default_factory=list)
    user_preferences: UserPreferences | None = None

    locked_blocks: list[ScheduleTask] = Field(default_factory=list)
    replan_from_time: str | None = None


class ScheduleOutput(BaseModel):
    """Final schedule with multiple strategies."""
    date: str
    strategies: list[ScheduleStrategy] = Field(default_factory=list)
    top_recommendation: str = "Most Productive"
    warnings: list[str] = Field(default_factory=list)
    generated_at: str = ""