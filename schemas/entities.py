from datetime import datetime
from enum import Enum
from typing import Any
from pydantic import BaseModel, Field


class EntityType(str, Enum):
    person = "person"
    goal = "goal"
    preference = "preference"
    event = "event"
    interest = "interest"


class UpcomingEvent(BaseModel):
    event: str
    date: str  # ISO 8601 date string


class Relation(BaseModel):
    type: str
    since: str | None = None
    upcoming_dates: list[UpcomingEvent] = Field(default_factory=list)


class Entity(BaseModel):
    user_id: str
    entity_name: str
    entity_type: EntityType
    relations: list[Relation] = Field(default_factory=list)
    social_priority_score: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
