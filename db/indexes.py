from pymongo import ASCENDING, DESCENDING
from pymongo import IndexModel
from motor.motor_asyncio import AsyncIOMotorDatabase

from db.collections import Collections


async def ensure_indexes(db: AsyncIOMotorDatabase) -> None:
    """Create all indexes for the daypilot database. Called once from FastAPI lifespan."""

    await db[Collections.GOALS].create_indexes([
        IndexModel([("goal_id", ASCENDING)], unique=True, name="goal_id_unique"),
        IndexModel([("user_id", ASCENDING), ("status", ASCENDING)], name="user_status"),
        IndexModel([("user_id", ASCENDING), ("deadline", ASCENDING)], name="user_deadline"),
        IndexModel([("status", ASCENDING), ("deadline", ASCENDING)], name="status_deadline"),
        IndexModel([("sub_tasks.sub_task_id", ASCENDING)], name="subtask_id"),
    ])

    await db[Collections.INTAKE_SESSIONS].create_indexes([
        IndexModel([("session_id", ASCENDING)], unique=True, name="session_id_unique"),
        IndexModel([("user_id", ASCENDING), ("status", ASCENDING)], name="user_status"),
        IndexModel([("expires_at", ASCENDING)], expireAfterSeconds=0, name="ttl_expires"),
    ])

    await db[Collections.WEEKLY_MEMORY_WRITES].create_indexes([
        IndexModel(
            [("user_id", ASCENDING), ("week_start", ASCENDING)],
            unique=True,
            name="user_week_unique",
        ),
    ])

    await db[Collections.EVENT_LOG].create_indexes([
        IndexModel([("event_id", ASCENDING)], unique=True, name="event_id_unique"),
        IndexModel([("goal_id", ASCENDING), ("received_at", DESCENDING)], name="goal_events"),
        IndexModel([("event_type", ASCENDING), ("received_at", DESCENDING)], name="type_time"),
    ])
