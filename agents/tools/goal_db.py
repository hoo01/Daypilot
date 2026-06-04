import logging
from datetime import datetime, timezone
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ReturnDocument

from db.collections import Collections
from schemas.goal_domain import Goal, VALID_GOAL_STATUSES

logger = logging.getLogger(__name__)

GOALS = Collections.GOALS


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _doc_to_goal(doc: dict) -> Goal:
    doc.pop("_id", None)
    return Goal(**doc)


async def create_goal(db: AsyncIOMotorDatabase, goal: Goal) -> Goal:
    data = goal.model_dump(mode="json")
    if not data.get("created_at"):
        data["created_at"] = _now_utc().isoformat()
    await db[GOALS].insert_one(data)
    return _doc_to_goal(data)


async def get_goal(db: AsyncIOMotorDatabase, goal_id: str) -> Optional[Goal]:
    doc = await db[GOALS].find_one({"goal_id": goal_id})
    if doc is None:
        return None
    return _doc_to_goal(doc)


async def update_goal(
    db: AsyncIOMotorDatabase,
    goal_id: str,
    updates: dict,
) -> Optional[Goal]:
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
    updated_deadline: Optional[str] = None,
) -> Optional[Goal]:
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
    """Atomic aggregation pipeline update — prevents lost-update race (Invariant I9).

    Abandoned subtasks are excluded from both numerator and denominator.
    """
    from pymongo import ReturnDocument as _RD

    doc = await db[GOALS].find_one_and_update(
        {"goal_id": goal_id},
        [
            {
                "$set": {
                    "progress_percent": {
                        "$let": {
                            "vars": {
                                "active": {
                                    "$filter": {
                                        "input": "$sub_tasks",
                                        "as": "t",
                                        "cond": {"$ne": ["$$t.abandoned", True]},
                                    }
                                }
                            },
                            "in": {
                                "$cond": {
                                    "if": {"$eq": [{"$size": "$$active"}, 0]},
                                    "then": 0.0,
                                    "else": {
                                        "$round": [
                                            {
                                                "$multiply": [
                                                    {
                                                        "$divide": [
                                                            {
                                                                "$size": {
                                                                    "$filter": {
                                                                        "input": "$$active",
                                                                        "as": "t",
                                                                        "cond": {
                                                                            "$and": [
                                                                                {"$ne": ["$$t.abandoned", True]},
                                                                                "$$t.is_completed",
                                                                            ]
                                                                        },
                                                                    }
                                                                }
                                                            },
                                                            {"$size": "$$active"},
                                                        ]
                                                    },
                                                    100,
                                                ]
                                            },
                                            2,
                                        ]
                                    },
                                }
                            },
                        }
                    }
                }
            }
        ],
        return_document=_RD.AFTER,
    )
    if doc is None:
        raise ValueError(f"Goal not found: {goal_id}")
    return float(doc["progress_percent"])
