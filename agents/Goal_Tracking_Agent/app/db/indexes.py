from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING, IndexModel
from app.db.collections import GOALS, INTAKE_SESSIONS, WEEKLY_MEMORY_WRITES, EVENT_LOG

GOALS_INDEXES = [
    IndexModel([("goal_id", ASCENDING)], unique=True, name="goal_id_unique"),
    IndexModel([("user_id", ASCENDING), ("status", ASCENDING)], name="user_status"),
    IndexModel([("user_id", ASCENDING), ("deadline", ASCENDING)], name="user_deadline"),
    IndexModel([("status", ASCENDING), ("deadline", ASCENDING)], name="status_deadline"),
    IndexModel([("sub_tasks.sub_task_id", ASCENDING)], name="subtask_id"),
]

INTAKE_SESSIONS_INDEXES = [
    IndexModel([("session_id", ASCENDING)], unique=True, name="session_id_unique"),
    IndexModel([("user_id", ASCENDING), ("status", ASCENDING)], name="user_status"),
    IndexModel([("expires_at", ASCENDING)], expireAfterSeconds=0, name="ttl_expires"),
]

WEEKLY_MEMORY_INDEXES = [
    IndexModel(
        [("user_id", ASCENDING), ("week_start", ASCENDING)],
        unique=True,
        name="user_week_unique",
    ),
]

EVENT_LOG_INDEXES = [
    IndexModel([("event_id", ASCENDING)], unique=True, name="event_id_unique"),
    IndexModel([("goal_id", ASCENDING), ("received_at", DESCENDING)], name="goal_events"),
    IndexModel([("event_type", ASCENDING), ("received_at", DESCENDING)], name="type_time"),
]


async def ensure_indexes(db: AsyncIOMotorDatabase) -> None:
    await db[GOALS].create_indexes(GOALS_INDEXES)
    await db[INTAKE_SESSIONS].create_indexes(INTAKE_SESSIONS_INDEXES)
    await db[WEEKLY_MEMORY_WRITES].create_indexes(WEEKLY_MEMORY_INDEXES)
    await db[EVENT_LOG].create_indexes(EVENT_LOG_INDEXES)
