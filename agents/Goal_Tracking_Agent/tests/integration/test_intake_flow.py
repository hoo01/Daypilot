"""Integration tests for the intake session DB layer (no ADK required)."""

import pytest
import pytest_asyncio
from datetime import datetime, timezone

pytest.importorskip("mongomock_motor")

from mongomock_motor import AsyncMongoMockClient

from app.tools.intake_session_db import (
    start_intake_session,
    resume_intake_session,
    append_intake_turn,
    save_intake_draft,
    complete_intake_session,
)
from app.schemas.intake import IntakeTurn


@pytest.fixture
def mongo_db():
    client = AsyncMongoMockClient()
    return client["test_goal_tracking"]


@pytest.mark.asyncio
async def test_start_intake_session_creates_open_session(mongo_db):
    session = await start_intake_session(mongo_db, user_id="u001")
    assert session.session_id is not None
    assert session.status == "open"
    assert session.stage == "initial"
    assert session.user_id == "u001"
    assert session.draft == {}
    assert session.history == []


@pytest.mark.asyncio
async def test_resume_intake_session_returns_session(mongo_db):
    session = await start_intake_session(mongo_db, user_id="u001")
    resumed = await resume_intake_session(mongo_db, session.session_id)
    assert resumed is not None
    assert resumed.session_id == session.session_id


@pytest.mark.asyncio
async def test_resume_nonexistent_session_returns_none(mongo_db):
    result = await resume_intake_session(mongo_db, "nonexistent-session-id")
    assert result is None


@pytest.mark.asyncio
async def test_append_intake_turn_adds_to_history(mongo_db):
    session = await start_intake_session(mongo_db, user_id="u001")
    turn = IntakeTurn(role="user", content="I want to solve 10 problems", timestamp=datetime.now(timezone.utc))
    await append_intake_turn(mongo_db, session.session_id, turn)

    updated = await resume_intake_session(mongo_db, session.session_id)
    # History is updated in MongoDB; the returned session from resume should reflect changes
    doc = await mongo_db["intake_sessions"].find_one({"session_id": session.session_id})
    assert doc is not None
    assert len(doc.get("history", [])) == 1
    assert doc["history"][0]["role"] == "user"


@pytest.mark.asyncio
async def test_save_intake_draft_persists_draft_and_stage(mongo_db):
    session = await start_intake_session(mongo_db, user_id="u001")
    draft = {"title": "Solve 10 problems", "deadline": "2026-06-01"}
    await save_intake_draft(mongo_db, session.session_id, draft, stage="validating")

    doc = await mongo_db["intake_sessions"].find_one({"session_id": session.session_id})
    assert doc["draft"]["title"] == "Solve 10 problems"
    assert doc["stage"] == "validating"


@pytest.mark.asyncio
async def test_complete_intake_session_marks_completed(mongo_db):
    session = await start_intake_session(mongo_db, user_id="u001")
    await complete_intake_session(mongo_db, session.session_id, goal_id="g_new_001")

    doc = await mongo_db["intake_sessions"].find_one({"session_id": session.session_id})
    assert doc["status"] == "completed"
    assert doc["goal_id"] == "g_new_001"

    # Completed session should not be resumable (status != "open")
    resumed = await resume_intake_session(mongo_db, session.session_id)
    assert resumed is None
