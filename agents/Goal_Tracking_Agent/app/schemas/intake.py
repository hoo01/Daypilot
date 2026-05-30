from datetime import datetime
from typing import Optional
from pydantic import BaseModel
from app.schemas.input import HealthOutput


class IntakeTurn(BaseModel):
    role: str        # "user" | "agent"
    content: str
    timestamp: datetime


class IntakeSession(BaseModel):
    session_id: str
    user_id: str
    status: str      # "open" | "completed" | "expired"
    stage: str       # "initial" | "validating" | "decomposing" | "feasibility" | "confirming"
    draft: dict      # partial Goal fields; schema-free to accommodate incremental collection
    history: list[IntakeTurn]
    validation_failures: list[str]
    created_at: datetime
    last_active_at: datetime
    expires_at: datetime   # TTL index target; set to created_at + 24h
    goal_id: Optional[str] = None


class IntakeTurnRequest(BaseModel):
    # GoalAgentInput fields (PRD §6) — field names match exactly
    user_id: str
    intent: str                          # "add_goal" | "add_goal_continue"
    raw_user_message: str
    health: HealthOutput
    memory_context: str
    calendar_free_slots: list[dict]
    # HTTP session layer — not part of GoalAgentInput
    session_id: Optional[str] = None     # None to start a new session


class IntakeTurnResponse(BaseModel):
    session_id: str
    stage: str
    assistant_message: str
    goal_id: Optional[str] = None        # populated only when stage == "confirming"
    validation_failures: list[str]


class IntakeConfirmRequest(BaseModel):
    session_id: str
    user_id: str
    confirmed: bool   # False triggers restart of the confirming stage
