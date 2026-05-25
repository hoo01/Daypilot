from pydantic import BaseModel, Field


class UpcomingDate(BaseModel):
    event: str
    date: str          # ISO 8601
    days_away: int


class RelationshipInput(BaseModel):
    user_id: str
    lookahead_days: int = 14


class RelationshipOutput(BaseModel):
    important_people: list[str] = Field(default_factory=list)
    upcoming_dates: list[UpcomingDate] = Field(default_factory=list)
    proactive_suggestions: list[str] = Field(default_factory=list)
    social_priority_score: float = 0.0
