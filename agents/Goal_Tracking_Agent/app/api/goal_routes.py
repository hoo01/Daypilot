import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from app.api.deps import get_db, verify_bearer
from app.db.collections import EVENT_LOG
from app.runtime.errors import GoalNotFound
from app.schemas.domain import Goal
from app.tools.goal_db import get_goal, list_active_goals, set_goal_status

logger = logging.getLogger(__name__)
router = APIRouter(tags=["goals"])


class ReplanRequest(BaseModel):
    new_deadline: str   # ISO date string
    user_id: str


class AbandonRequest(BaseModel):
    user_id: str
    reason: Optional[str] = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


@router.get("/goals", response_model=list[Goal])
async def list_goals(
    user_id: str = Query(...),
    status: Optional[str] = Query(None),
    db: AsyncIOMotorDatabase = Depends(get_db),
    _: None = Depends(verify_bearer),
) -> list[Goal]:
    """List goals for a user. Optionally filter by status."""
    if status:
        statuses = [status]
    else:
        statuses = ["CREATED", "IN_PROGRESS", "OVERDUE"]
    return await list_active_goals(db, user_id, statuses=statuses)


@router.get("/goals/{goal_id}", response_model=Goal)
async def get_goal_by_id(
    goal_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
    _: None = Depends(verify_bearer),
) -> Goal:
    """Fetch a single goal by goal_id."""
    goal = await get_goal(db, goal_id)
    if goal is None:
        raise GoalNotFound(goal_id)
    return goal


@router.post("/goals/{goal_id}/replan", response_model=Goal)
async def replan_goal(
    goal_id: str,
    body: ReplanRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
    _: None = Depends(verify_bearer),
) -> Goal:
    """Replan an overdue goal with a new deadline."""
    goal = await set_goal_status(db, goal_id, "IN_PROGRESS", updated_deadline=body.new_deadline)
    if goal is None:
        raise GoalNotFound(goal_id)

    await db[EVENT_LOG].insert_one({
        "event_id": str(uuid.uuid4()),
        "event_type": "replan",
        "goal_id": goal_id,
        "sub_task_id": None,
        "payload": {"new_deadline": body.new_deadline, "user_id": body.user_id},
        "received_at": _now().isoformat(),
        "processed_at": _now().isoformat(),
        "status": "processed",
        "warnings": [],
    })
    return goal


@router.post("/goals/{goal_id}/abandon", response_model=Goal)
async def abandon_goal(
    goal_id: str,
    body: AbandonRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
    _: None = Depends(verify_bearer),
) -> Goal:
    """Abandon a goal — requires explicit user confirmation (the caller is responsible
    for obtaining user confirmation before calling this endpoint)."""
    goal = await set_goal_status(db, goal_id, "ABANDONED")
    if goal is None:
        raise GoalNotFound(goal_id)

    await db[EVENT_LOG].insert_one({
        "event_id": str(uuid.uuid4()),
        "event_type": "abandon",
        "goal_id": goal_id,
        "sub_task_id": None,
        "payload": {"reason": body.reason, "user_id": body.user_id},
        "received_at": _now().isoformat(),
        "processed_at": _now().isoformat(),
        "status": "processed",
        "warnings": [],
    })
    return goal
