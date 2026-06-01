import logging
from datetime import datetime
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ReturnDocument

from db.collections import Collections
from schemas.goal_domain import Goal, SubTask

logger = logging.getLogger(__name__)

GOALS = Collections.GOALS


def _doc_to_goal(doc: dict) -> Goal:
    doc.pop("_id", None)
    return Goal(**doc)


def _extract_subtask(doc: dict, sub_task_id: str) -> Optional[SubTask]:
    for t in doc.get("sub_tasks", []):
        if t.get("sub_task_id") == sub_task_id:
            return SubTask(**t)
    return None


async def add_sub_task(
    db: AsyncIOMotorDatabase,
    goal_id: str,
    sub_task: SubTask,
) -> SubTask:
    result = await db[GOALS].update_one(
        {"goal_id": goal_id},
        {"$push": {"sub_tasks": sub_task.model_dump(mode="json")}},
    )
    if result.matched_count == 0:
        raise ValueError(f"Goal not found: {goal_id}")
    return sub_task


async def get_sub_task(
    db: AsyncIOMotorDatabase,
    goal_id: str,
    sub_task_id: str,
) -> Optional[SubTask]:
    doc = await db[GOALS].find_one(
        {"goal_id": goal_id, "sub_tasks.sub_task_id": sub_task_id},
        {"sub_tasks.$": 1},
    )
    if not doc or not doc.get("sub_tasks"):
        return None
    return SubTask(**doc["sub_tasks"][0])


async def update_sub_task(
    db: AsyncIOMotorDatabase,
    goal_id: str,
    sub_task_id: str,
    updates: dict,
) -> Optional[SubTask]:
    set_payload = {f"sub_tasks.$.{k}": v for k, v in updates.items()}
    doc = await db[GOALS].find_one_and_update(
        {"goal_id": goal_id, "sub_tasks.sub_task_id": sub_task_id},
        {"$set": set_payload},
        return_document=ReturnDocument.AFTER,
    )
    if doc is None:
        return None
    return _extract_subtask(doc, sub_task_id)


async def mark_sub_task_complete(
    db: AsyncIOMotorDatabase,
    goal_id: str,
    sub_task_id: str,
    completed_at: datetime,
) -> Optional[SubTask]:
    return await update_sub_task(
        db,
        goal_id,
        sub_task_id,
        {
            "is_completed": True,
            "completed_at": completed_at.isoformat(),
        },
    )


async def bulk_set_sub_tasks(
    db: AsyncIOMotorDatabase,
    goal_id: str,
    sub_tasks: list[SubTask],
) -> Goal:
    serialized = [t.model_dump(mode="json") for t in sub_tasks]
    doc = await db[GOALS].find_one_and_update(
        {"goal_id": goal_id},
        {"$set": {"sub_tasks": serialized}},
        return_document=ReturnDocument.AFTER,
    )
    if doc is None:
        raise ValueError(f"Goal not found: {goal_id}")
    return _doc_to_goal(doc)
