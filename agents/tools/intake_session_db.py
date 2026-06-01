import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

from db.collections import Collections
from schemas.goal_intake import IntakeSession, IntakeTurn

INTAKE_SESSIONS = Collections.INTAKE_SESSIONS


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _doc_to_session(doc: dict) -> IntakeSession:
    doc.pop("_id", None)
    return IntakeSession(**doc)


async def start_intake_session(
    db: AsyncIOMotorDatabase,
    user_id: str,
    ttl_hours: int = 24,
) -> IntakeSession:
    now = _now_utc()
    session = IntakeSession(
        session_id=str(uuid.uuid4()),
        user_id=user_id,
        status="open",
        stage="initial",
        draft={},
        history=[],
        validation_failures=[],
        created_at=now,
        last_active_at=now,
        expires_at=now + timedelta(hours=ttl_hours),
        goal_id=None,
    )
    await db[INTAKE_SESSIONS].insert_one(session.model_dump(mode="json"))
    return session


async def resume_intake_session(
    db: AsyncIOMotorDatabase,
    session_id: str,
) -> Optional[IntakeSession]:
    now = _now_utc()
    doc = await db[INTAKE_SESSIONS].find_one({
        "session_id": session_id,
        "status": "open",
        "expires_at": {"$gt": now.isoformat()},
    })
    if doc is None:
        return None
    return _doc_to_session(doc)


async def append_intake_turn(
    db: AsyncIOMotorDatabase,
    session_id: str,
    turn: IntakeTurn,
) -> None:
    await db[INTAKE_SESSIONS].update_one(
        {"session_id": session_id},
        {
            "$push": {"history": turn.model_dump(mode="json")},
            "$set": {"last_active_at": _now_utc().isoformat()},
        },
    )


async def save_intake_draft(
    db: AsyncIOMotorDatabase,
    session_id: str,
    draft: dict,
    stage: str,
) -> None:
    await db[INTAKE_SESSIONS].update_one(
        {"session_id": session_id},
        {"$set": {"draft": draft, "stage": stage, "last_active_at": _now_utc().isoformat()}},
    )


async def complete_intake_session(
    db: AsyncIOMotorDatabase,
    session_id: str,
    goal_id: str,
) -> None:
    await db[INTAKE_SESSIONS].update_one(
        {"session_id": session_id},
        {"$set": {"status": "completed", "goal_id": goal_id, "last_active_at": _now_utc().isoformat()}},
    )
