"""GET /v1/goals, POST /v1/goals/{id}/abandon, POST /v1/goals/{id}/replan"""
import logging
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from db.client import get_db
from db.collections import Collections
from schemas.goal_domain import Goal, EventLogEntry
from agents.tools.goal_db import get_goal, list_active_goals, set_goal_status

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/goals", tags=["goals"])

EVENT_LOG = Collections.EVENT_LOG

TERMINAL_STATES = {"COMPLETED", "ABANDONED"}

VALID_TRANSITIONS: dict[str, set[str]] = {
    "CREATED": {"IN_PROGRESS", "ABANDONED"},
    "IN_PROGRESS": {"COMPLETED", "PARTIALLY_COMPLETED", "OVERDUE", "ABANDONED"},
    "OVERDUE": {"IN_PROGRESS", "ABANDONED"},
    "PARTIALLY_COMPLETED": {"ABANDONED"},
    "COMPLETED": set(),
    "ABANDONED": set(),
}


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


class AbandonRequest(BaseModel):
    user_id: str
    reason: Optional[str] = None


class ReplanRequest(BaseModel):
    new_deadline: date
    user_id: str


@router.get("", response_model=list[Goal])
async def list_goals(
    user_id: str = Query(...),
    status: Optional[str] = Query(None),
) -> list[Goal]:
    db = get_db()
    statuses = [status] if status else ["CREATED", "IN_PROGRESS", "OVERDUE"]
    return await list_active_goals(db, user_id, statuses=statuses)


@router.get("/{goal_id}", response_model=Goal)
async def get_goal_by_id(goal_id: str) -> Goal:
    db = get_db()
    goal = await get_goal(db, goal_id)
    if goal is None:
        raise HTTPException(status_code=404, detail={"error": "goal_not_found", "goal_id": goal_id})
    return goal


@router.post("/{goal_id}/abandon", response_model=Goal)
async def abandon_goal(goal_id: str, body: AbandonRequest) -> Goal:
    db = get_db()
    goal = await get_goal(db, goal_id)
    if goal is None:
        raise HTTPException(status_code=404, detail={"error": "goal_not_found", "goal_id": goal_id})

    if goal.status == "ABANDONED":
        return goal

    if goal.status == "COMPLETED":
        raise HTTPException(
            status_code=422,
            detail={"error": "illegal_transition", "message": f"Cannot abandon a COMPLETED goal (goal_id={goal_id})"},
        )

    updated = await set_goal_status(db, goal_id, "ABANDONED")
    if updated is None:
        raise HTTPException(status_code=404, detail={"error": "goal_not_found", "goal_id": goal_id})

    await db[EVENT_LOG].insert_one(EventLogEntry(
        event_id=f"abandon-{goal_id}-{int(_now_utc().timestamp())}",
        event_type="abandon",
        goal_id=goal_id,
        payload={"reason": body.reason, "user_id": body.user_id},
        received_at=_now_utc(),
        processed_at=_now_utc(),
        status="processed",
        warnings=[],
    ).model_dump(mode="json"))

    return updated


@router.post("/{goal_id}/replan", response_model=Goal)
async def replan_goal(goal_id: str, body: ReplanRequest) -> Goal:
    db = get_db()
    goal = await get_goal(db, goal_id)
    if goal is None:
        raise HTTPException(status_code=404, detail={"error": "goal_not_found", "goal_id": goal_id})

    if goal.status in TERMINAL_STATES:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "illegal_transition",
                "message": f"Cannot replan a {goal.status} goal (goal_id={goal_id})",
            },
        )

    updated = await set_goal_status(
        db, goal_id, "IN_PROGRESS", updated_deadline=body.new_deadline.isoformat()
    )
    if updated is None:
        raise HTTPException(status_code=404, detail={"error": "goal_not_found", "goal_id": goal_id})

    await db[EVENT_LOG].insert_one(EventLogEntry(
        event_id=f"replan-{goal_id}-{int(_now_utc().timestamp())}",
        event_type="replan",
        goal_id=goal_id,
        payload={"new_deadline": body.new_deadline.isoformat(), "user_id": body.user_id},
        received_at=_now_utc(),
        processed_at=_now_utc(),
        status="processed",
        warnings=[],
    ).model_dump(mode="json"))

    return updated
