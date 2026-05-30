import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.db.collections import INTAKE_SESSIONS
from app.schemas.intake import IntakeSession, IntakeTurn


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _doc_to_session(doc: dict) -> IntakeSession:
    doc.pop("_id", None)
    return IntakeSession(**doc)


async def start_intake_session(
    db: AsyncIOMotorDatabase,
    user_id: str,
) -> IntakeSession:
    """Create a new IntakeSession with status='open', stage='initial',
    and expires_at = utcnow() + 24 hours.
    """
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
        expires_at=now + timedelta(hours=24),
        goal_id=None,
    )
    await db[INTAKE_SESSIONS].insert_one(session.model_dump(mode="json"))
    return session


async def resume_intake_session(
    db: AsyncIOMotorDatabase,
    session_id: str,
) -> Optional[IntakeSession]:
    """Fetch an open IntakeSession by session_id.

    Returns None if the session does not exist, has status != 'open', or
    has passed its expires_at.
    """
    now = _now_utc()
    doc = await db[INTAKE_SESSIONS].find_one(
        {
            "session_id": session_id,
            "status": "open",
            "expires_at": {"$gt": now.isoformat()},
        }
    )
    if doc is None:
        return None
    return _doc_to_session(doc)


async def append_intake_turn(
    db: AsyncIOMotorDatabase,
    session_id: str,
    turn: IntakeTurn,
) -> None:
    """Append one IntakeTurn to the session's history and update last_active_at."""
    now = _now_utc()
    await db[INTAKE_SESSIONS].update_one(
        {"session_id": session_id},
        {
            "$push": {"history": turn.model_dump(mode="json")},
            "$set": {"last_active_at": now.isoformat()},
        },
    )


async def save_intake_draft(
    db: AsyncIOMotorDatabase,
    session_id: str,
    draft: dict,
    stage: str,
) -> None:
    """Persist the current partial goal draft and intake stage to the session."""
    now = _now_utc()
    await db[INTAKE_SESSIONS].update_one(
        {"session_id": session_id},
        {
            "$set": {
                "draft": draft,
                "stage": stage,
                "last_active_at": now.isoformat(),
            }
        },
    )


async def complete_intake_session(
    db: AsyncIOMotorDatabase,
    session_id: str,
    goal_id: str,
) -> None:
    """Mark the session as status='completed' and record the resulting goal_id."""
    now = _now_utc()
    await db[INTAKE_SESSIONS].update_one(
        {"session_id": session_id},
        {
            "$set": {
                "status": "completed",
                "goal_id": goal_id,
                "last_active_at": now.isoformat(),
            }
        },
    )
