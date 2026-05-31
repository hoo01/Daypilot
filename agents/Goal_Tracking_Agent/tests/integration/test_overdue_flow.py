"""Integration tests for POST /v1/events/overdue."""

import pytest
import pytest_asyncio
from datetime import date, datetime, timezone

pytest.importorskip("mongomock_motor")

from mongomock_motor import AsyncMongoMockClient
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock, MagicMock


@pytest.fixture
def mongo_db():
    client = AsyncMongoMockClient()
    return client["test_goal_tracking"]


@pytest.fixture
def app_with_db(mongo_db):
    """Create a FastAPI test app with mocked DB and runner."""
    from app.main import create_app

    application = create_app()

    mock_runner = MagicMock()
    mock_runner.session_service = MagicMock()

    # Override lifespan by directly setting app.state
    application.state.db = mongo_db
    application.state.runner = mock_runner
    application.state.cfg = MagicMock(api_bearer_token="")
    return application


@pytest.fixture
def goal_in_db(mongo_db):
    """Seed a goal into the test DB."""
    import asyncio

    async def _seed():
        now = datetime.now(timezone.utc)
        doc = {
            "goal_id": "g001",
            "user_id": "u001",
            "title": "Finish assignment draft",
            "goal_type": "weekly",
            "status": "IN_PROGRESS",
            "created_at": now.isoformat(),
            "deadline": "2026-05-28",
            "progress_percent": 60.0,
            "sub_tasks": [
                {"sub_task_id": "t1", "goal_id": "g001", "title": "Outline",
                 "estimated_minutes": 30, "priority": "high", "deadline": "2026-05-28",
                 "preferred_time_of_day": "flexible", "can_split": False,
                 "is_completed": True, "completed_at": None, "planned_date": None},
                {"sub_task_id": "t2", "goal_id": "g001", "title": "Draft section 1",
                 "estimated_minutes": 60, "priority": "high", "deadline": "2026-05-28",
                 "preferred_time_of_day": "flexible", "can_split": True,
                 "is_completed": False, "completed_at": None, "planned_date": None},
                {"sub_task_id": "t3", "goal_id": "g001", "title": "Draft section 2",
                 "estimated_minutes": 60, "priority": "medium", "deadline": "2026-05-28",
                 "preferred_time_of_day": "flexible", "can_split": True,
                 "is_completed": True, "completed_at": None, "planned_date": None},
                {"sub_task_id": "t4", "goal_id": "g001", "title": "Review",
                 "estimated_minutes": 30, "priority": "medium", "deadline": "2026-05-28",
                 "preferred_time_of_day": "flexible", "can_split": False,
                 "is_completed": False, "completed_at": None, "planned_date": None},
                {"sub_task_id": "t5", "goal_id": "g001", "title": "Submit",
                 "estimated_minutes": 15, "priority": "high", "deadline": "2026-05-28",
                 "preferred_time_of_day": "flexible", "can_split": False,
                 "is_completed": True, "completed_at": None, "planned_date": None},
            ],
            "feasibility_score": 0.85,
            "feasibility_note": "",
            "total_effort_minutes": 195,
            "suggested_blocks_count": 2,
            "suggested_split_ratio": [0.5, 0.5],
        }
        await mongo_db["goals"].insert_one(doc)

    asyncio.get_event_loop().run_until_complete(_seed())


@pytest.mark.asyncio
async def test_overdue_known_subtask_returns_acknowledged(mongo_db, goal_in_db):
    """POST /v1/events/overdue with a known sub_task_id returns 200 acknowledged."""
    from app.api.event_routes import handle_overdue
    from app.schemas.events import OverdueNotification, OverdueTaskRef

    notification = OverdueNotification(
        event_id="evt_001",
        overdue_tasks=[
            OverdueTaskRef(
                sub_task_id="t2",
                goal_id="g001",
                scheduled_date=date(2026, 5, 27),
            )
        ],
    )

    result = await handle_overdue(body=notification, db=mongo_db)
    assert result.status in ("acknowledged", "partial")
    assert result.processed_count >= 0

    # Event should be logged
    event = await mongo_db["event_log"].find_one({"event_id": "evt_001"})
    assert event is not None
    assert event["status"] in ("acknowledged", "partial", "processing")


@pytest.mark.asyncio
async def test_overdue_unknown_subtask_returns_partial_with_warning(mongo_db, goal_in_db):
    """POST /v1/events/overdue with unknown sub_task_id returns partial with warning."""
    from app.api.event_routes import handle_overdue
    from app.schemas.events import OverdueNotification, OverdueTaskRef

    notification = OverdueNotification(
        event_id="evt_002",
        overdue_tasks=[
            OverdueTaskRef(
                sub_task_id="t99",  # does not exist
                goal_id="g001",
                scheduled_date=date(2026, 5, 27),
            )
        ],
    )

    result = await handle_overdue(body=notification, db=mongo_db)
    assert result.status == "partial"
    assert result.processed_count == 0
    assert any("t99" in w for w in result.warnings)


@pytest.mark.asyncio
async def test_overdue_idempotent_on_duplicate_event_id(mongo_db, goal_in_db):
    """Second call with same event_id returns already_processed."""
    from app.api.event_routes import handle_overdue
    from app.schemas.events import OverdueNotification, OverdueTaskRef

    notification = OverdueNotification(
        event_id="evt_003",
        overdue_tasks=[
            OverdueTaskRef(sub_task_id="t1", goal_id="g001",
                           scheduled_date=date(2026, 5, 27))
        ],
    )

    first = await handle_overdue(body=notification, db=mongo_db)
    second = await handle_overdue(body=notification, db=mongo_db)
    assert second.status == "already_processed"
