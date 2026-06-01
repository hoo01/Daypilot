from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class IntakeTurn(BaseModel):
    role: str       # "user" | "agent"
    content: str
    timestamp: datetime


class IntakeSession(BaseModel):
    session_id: str
    user_id: str
    status: str     # "open" | "completed" | "expired"
    stage: str      # "initial" | "validating" | "decomposing" | "feasibility" | "confirming"
    draft: dict
    history: list[IntakeTurn]
    validation_failures: list[str]
    created_at: datetime
    last_active_at: datetime
    expires_at: datetime
    goal_id: Optional[str] = None


class IntakeTurnRequest(BaseModel):
    user_id: str
    intent: str                         # "add_goal" | "add_goal_continue"
    raw_user_message: str
    health: dict                        # HealthOutput fields
    memory_context: str
    calendar_free_slots: list[dict]
    session_id: Optional[str] = None


class IntakeTurnResponse(BaseModel):
    session_id: str
    stage: str
    assistant_message: str
    goal_id: Optional[str] = None
    validation_failures: list[str] = []


class IntakeConfirmRequest(BaseModel):
    session_id: str
    user_id: str
    confirmed: bool
