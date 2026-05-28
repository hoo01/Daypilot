import logging
from datetime import datetime, timezone
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ReturnDocument

from app.db.collections import GOALS
from app.schemas.domain import Goal, VALID_GOAL_STATUSES

logger = logging.getLogger(__name__)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _doc_to_goal(doc: dict) -> Goal:
    doc.pop("_id", None)
    return Goal(**doc)


async def create_goal(db: AsyncIOMotorDatabase, goal: Goal) -> Goal:
    """Insert a new Goal document into the goals collection.

    Sets created_at to utcnow() if not provided. Raises DuplicateKeyError if
    goal_id already exists.
    """
    data = goal.model_dump(mode="json")
    if not data.get("created_at"):
        data["created_at"] = _now_utc().isoformat()
    await db[GOALS].insert_one(data)
    return _doc_to_goal(data)


async def get_goal(db: AsyncIOMotorDatabase, goal_id: str) -> Optional[Goal]:
    """Fetch a single Goal by goal_id.  Returns None if not found."""
    doc = await db[GOALS].find_one({"goal_id": goal_id})
    if doc is None:
        return None
    return _doc_to_goal(doc)


async def update_goal(
    db: AsyncIOMotorDatabase,
    goal_id: str,
    updates: dict,
) -> Optional[Goal]:
    """Apply a partial update to a Goal document using $set.

    Returns the updated Goal, or None if goal_id not found.
    """
    doc = await db[GOALS].find_one_and_update(
        {"goal_id": goal_id},
        {"$set": updates},
        return_document=ReturnDocument.AFTER,
    )
    if doc is None:
        return None
    return _doc_to_goal(doc)


async def list_active_goals(
    db: AsyncIOMotorDatabase,
    user_id: str,
    statuses: list[str] = ("CREATED", "IN_PROGRESS", "OVERDUE"),
) -> list[Goal]:
    """Return all goals for user_id whose status is in statuses, sorted by deadline."""
    cursor = db[GOALS].find(
        {"user_id": user_id, "status": {"$in": list(statuses)}}
    ).sort("deadline", 1)
    goals: list[Goal] = []
    async for doc in cursor:
        goals.append(_doc_to_goal(doc))
    return goals


async def set_goal_status(
    db: AsyncIOMotorDatabase,
    goal_id: str,
    new_status: str,
    updated_deadline: Optional[str] = None,  # ISO date string
) -> Optional[Goal]:
    """Transition a goal to new_status.

    Validates new_status against the legal lifecycle states.  If updated_deadline
    is provided, updates the deadline field atomically in the same operation.
    """
    if new_status not in VALID_GOAL_STATUSES:
        raise ValueError(f"Invalid status: {new_status}")

    update: dict = {"status": new_status}
    if updated_deadline:
        update["deadline"] = updated_deadline

    doc = await db[GOALS].find_one_and_update(
        {"goal_id": goal_id},
        {"$set": update},
        return_document=ReturnDocument.AFTER,
    )
    if doc is None:
        return None
    return _doc_to_goal(doc)


async def recompute_progress_percent(db: AsyncIOMotorDatabase, goal_id: str) -> float:
    """Recalculate and persist progress_percent for the given goal.

    Reads the embedded sub_tasks, applies the equal-weight formula, writes
    back with $set, and returns the new value.
    Raises ValueError if goal_id does not exist.
    """
    from app.tools.progress_calc import compute_progress_percent
    from app.schemas.domain import SubTask

    doc = await db[GOALS].find_one({"goal_id": goal_id})
    if doc is None:
        raise ValueError(f"Goal not found: {goal_id}")

    sub_tasks = [SubTask(**t) for t in doc.get("sub_tasks", [])]
    new_pct = compute_progress_percent(sub_tasks)

    await db[GOALS].update_one(
        {"goal_id": goal_id},
        {"$set": {"progress_percent": new_pct}},
    )
    return new_pct
