"""Custom ADK SessionService backed by MongoDB intake_sessions collection.

Implements google.adk.sessions.BaseSessionService so that ADK session state
(including all state[] keys) persists across HTTP turns.
"""

import time
import uuid
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.db.collections import INTAKE_SESSIONS

logger = logging.getLogger(__name__)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Minimal Session dataclass — mirrors google.adk.sessions.Session API.
# The real Session is imported at runtime; this is used for type hints only
# when the ADK import fails in test environments.
# ---------------------------------------------------------------------------

try:
    from google.adk.sessions import Session, BaseSessionService  # type: ignore[import]
    _ADK_AVAILABLE = True
except ImportError:
    _ADK_AVAILABLE = False

    class Session:  # type: ignore[no-redef]
        def __init__(
            self,
            id: str,
            app_name: str,
            user_id: str,
            state: Optional[dict] = None,
            events: Optional[list] = None,
            last_update_time: Optional[float] = None,
        ) -> None:
            self.id = id
            self.app_name = app_name
            self.user_id = user_id
            self.state: dict[str, Any] = state or {}
            self.events: list = events or []
            self.last_update_time: float = last_update_time or time.time()

    class BaseSessionService:  # type: ignore[no-redef]
        pass


class MongoSessionService(BaseSessionService):  # type: ignore[misc]
    """ADK SessionService that persists sessions to MongoDB intake_sessions."""

    APP_NAME = "goal_tracking_agent"

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._db = db

    # ── helpers ──────────────────────────────────────────────────────────────

    def _collection(self):  # type: ignore[return]
        return self._db[INTAKE_SESSIONS]

    def _doc_to_session(self, doc: dict) -> Session:
        return Session(
            id=doc["session_id"],
            app_name=doc.get("app_name", self.APP_NAME),
            user_id=doc["user_id"],
            state=doc.get("state", {}),
            events=doc.get("events", []),
            last_update_time=doc.get("last_update_time", time.time()),
        )

    # ── BaseSessionService interface ──────────────────────────────────────────

    async def create_session(  # type: ignore[override]
        self,
        *,
        app_name: str = APP_NAME,
        user_id: str,
        state: Optional[dict[str, Any]] = None,
        session_id: Optional[str] = None,
    ) -> Session:
        sid = session_id or str(uuid.uuid4())
        now = _now_utc()
        doc = {
            "session_id": sid,
            "app_name": app_name,
            "user_id": user_id,
            "status": "open",
            "stage": "initial",
            "draft": {},
            "history": [],
            "validation_failures": [],
            "state": state or {},
            "events": [],
            "last_update_time": time.time(),
            "created_at": now.isoformat(),
            "last_active_at": now.isoformat(),
            "expires_at": (now + timedelta(hours=24)).isoformat(),
            "goal_id": None,
        }
        await self._collection().insert_one(doc)
        return self._doc_to_session(doc)

    async def get_session(  # type: ignore[override]
        self,
        *,
        app_name: str = APP_NAME,
        user_id: str,
        session_id: str,
        config: Any = None,
    ) -> Optional[Session]:
        now = _now_utc()
        doc = await self._collection().find_one(
            {
                "session_id": session_id,
                "user_id": user_id,
                "status": "open",
                "expires_at": {"$gt": now.isoformat()},
            }
        )
        if doc is None:
            return None
        return self._doc_to_session(doc)

    async def list_sessions(  # type: ignore[override]
        self,
        *,
        app_name: str = APP_NAME,
        user_id: str,
    ) -> list[Session]:
        sessions: list[Session] = []
        async for doc in self._collection().find({"user_id": user_id}):
            sessions.append(self._doc_to_session(doc))
        return sessions

    async def delete_session(  # type: ignore[override]
        self,
        *,
        app_name: str = APP_NAME,
        user_id: str,
        session_id: str,
    ) -> None:
        await self._collection().delete_one({"session_id": session_id, "user_id": user_id})

    async def append_event(  # type: ignore[override]
        self,
        session: Session,
        event: Any,
    ) -> Any:
        """Persist state mutations after each ADK event."""
        await self._collection().update_one(
            {"session_id": session.id},
            {
                "$set": {
                    "state": session.state,
                    "last_update_time": time.time(),
                    "last_active_at": _now_utc().isoformat(),
                }
            },
        )
        return event

    async def close(self) -> None:
        pass
