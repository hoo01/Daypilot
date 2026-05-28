"""Shared pytest fixtures for unit and integration tests."""

import pytest
import pytest_asyncio
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock


# ── In-process MongoDB mock ────────────────────────────────────────────────────

@pytest.fixture
def mock_db():
    """Provide a mongomock-backed AsyncIOMotorDatabase for tests that need DB access."""
    try:
        from mongomock_motor import AsyncMongoMockClient
        client = AsyncMongoMockClient()
        return client["test_goal_tracking"]
    except ImportError:
        pytest.skip("mongomock-motor not installed")


# ── Mock Memory Agent ─────────────────────────────────────────────────────────

@pytest.fixture
def mock_memory_agent_client():
    """Return a mock httpx.AsyncClient whose POST always succeeds."""
    client = AsyncMock()
    response = MagicMock()
    response.status_code = 200
    response.raise_for_status = MagicMock()
    client.post = AsyncMock(return_value=response)
    return client


# ── Mock Calendar API ─────────────────────────────────────────────────────────

@pytest.fixture
def mock_calendar_service():
    """Return a mock Google Calendar API resource."""
    svc = MagicMock()
    svc.freebusy.return_value.query.return_value.execute.return_value = {
        "calendars": {"primary": {"busy": []}}
    }
    return svc


# ── Common domain fixtures ────────────────────────────────────────────────────

@pytest.fixture
def sample_sub_tasks():
    from app.schemas.domain import SubTask
    return [
        SubTask(
            sub_task_id=f"t{i}",
            goal_id="g001",
            title=f"Task {i}",
            estimated_minutes=30,
            priority="medium",
            deadline=date(2026, 6, 1),
            preferred_time_of_day="flexible",
            can_split=True,
            is_completed=(i % 2 == 0),  # even tasks are completed
        )
        for i in range(1, 6)
    ]


@pytest.fixture
def sample_goal(sample_sub_tasks):
    from app.schemas.domain import Goal
    return Goal(
        goal_id="g001",
        user_id="u001",
        title="Solve 5 Leetcode problems",
        goal_type="weekly",
        status="IN_PROGRESS",
        created_at=datetime.now(timezone.utc),
        deadline=date(2026, 6, 1),
        progress_percent=40.0,
        sub_tasks=sample_sub_tasks,
        feasibility_score=0.85,
        feasibility_note="",
        total_effort_minutes=150,
        suggested_blocks_count=2,
        suggested_split_ratio=[0.5, 0.5],
    )
