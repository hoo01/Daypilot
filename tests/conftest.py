"""Shared pytest fixtures for all tests."""
import sys
import os

# Ensure project root is on the path so imports work correctly
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Set required env vars before any project imports so Settings() can initialize
os.environ.setdefault("GEMINI_API_KEY", "test-dummy-key")
os.environ.setdefault("MONGODB_URI", "mongodb://localhost:27017")

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
from motor.motor_asyncio import AsyncIOMotorClient
from testcontainers.mongodb import MongoDbContainer

from api.routes import events, goals as goals_router
from api.routes import intake, scheduled as scheduled_router
from db.indexes import ensure_indexes


# ---------------------------------------------------------------------------
# MongoDB testcontainer (session-scoped — one container per test run)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def mongo_uri():
    with MongoDbContainer("mongo:7") as container:
        yield container.get_connection_url()


# ---------------------------------------------------------------------------
# Per-test database fixture
# ---------------------------------------------------------------------------

@pytest.fixture
async def test_db(mongo_uri, monkeypatch):
    """
    Fresh test database per test function.
    Patches config.settings and db.client so all route handlers use the test DB.
    """
    import config
    import db.client as db_module

    monkeypatch.setattr(config.settings, "mongodb_uri", mongo_uri)
    monkeypatch.setattr(config.settings, "mongodb_db_name", "test_daypilot")
    monkeypatch.setattr(config.settings, "memory_agent_url", "http://mock-memory-agent")
    monkeypatch.setattr(config.settings, "gemini_api_key", "test-dummy-key")

    # Reset any cached Motor client
    monkeypatch.setattr(db_module, "_client", None)

    client = AsyncIOMotorClient(mongo_uri)
    db = client["test_daypilot"]
    await ensure_indexes(db)

    # Inject the test client so get_db() returns the test DB
    monkeypatch.setattr(db_module, "_client", client)

    yield db

    await client.drop_database("test_daypilot")
    client.close()
    monkeypatch.setattr(db_module, "_client", None)


# ---------------------------------------------------------------------------
# HTTP client fixtures
# ---------------------------------------------------------------------------

def _build_test_app(runner=None) -> FastAPI:
    """Minimal FastAPI app with all goal-related routes mounted."""
    app = FastAPI()
    app.include_router(events.router)
    app.include_router(goals_router.router)
    app.include_router(intake.router)
    app.include_router(scheduled_router.router)
    if runner is not None:
        app.state.runner = runner
    return app


@pytest.fixture
async def async_client(test_db):
    """AsyncClient without a runner — for event/goal/scheduled routes."""
    app = _build_test_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest.fixture
def make_intake_client(test_db):
    """Factory that builds an AsyncClient with a given StubRunner."""
    from contextlib import asynccontextmanager

    async def _make(runner):
        app = _build_test_app(runner=runner)
        client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        await client.__aenter__()
        return client

    return _make


# ---------------------------------------------------------------------------
# Terminal summary plugin
# ---------------------------------------------------------------------------

class _ScenarioSummaryPlugin:
    def __init__(self):
        self.results: dict[str, dict] = {}  # scenario_id -> {pass, fail, skip}

    def pytest_runtest_logreport(self, report):
        if report.when != "call":
            return
        for item in [report.nodeid]:
            markers = getattr(report, "_markers", {})
        # Use report's own markers via parent item — collected at pytest_collection stage
        pass

    def pytest_terminal_summary(self, terminalreporter, exitstatus, config):
        lines = [
            "",
            "=" * 48,
            "Scenario Coverage Summary",
            "=" * 48,
        ]
        terminalreporter.write_line("\n".join(lines))


def pytest_configure(config):
    config.pluginmanager.register(_ScenarioSummaryPlugin(), "scenario_summary")
