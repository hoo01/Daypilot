"""
Integration tests for POST /schedule/generate.

Gemini calls are fully mocked — no real API key required.
The tests verify the full request → ScheduleInput → ScheduleAgent.run()
→ ScheduleOutput → JSON response pipeline.
"""
import json
from datetime import date
from unittest.mock import AsyncMock, patch

import pytest

DATE = "2026-05-28"


def _make_strategy(name: str) -> dict:
    return {
        "name": name,
        "description": f"{name} strategy",
        "tasks": [
            {
                "task_id": f"{name.lower().replace(' ', '-')}-t1",
                "title": "Wake up",
                "start_time": f"{DATE}T07:00:00",
                "end_time": f"{DATE}T07:30:00",
                "type": "routine",
                "location": None,
                "notes": None,
            },
            {
                "task_id": f"{name.lower().replace(' ', '-')}-t2",
                "title": "Deep work",
                "start_time": f"{DATE}T09:00:00",
                "end_time": f"{DATE}T11:00:00",
                "type": "deep_work",
                "location": None,
                "notes": None,
            },
            {
                "task_id": f"{name.lower().replace(' ', '-')}-t3",
                "title": "Break",
                "start_time": f"{DATE}T11:00:00",
                "end_time": f"{DATE}T11:15:00",
                "type": "break",
                "location": None,
                "notes": None,
            },
            {
                "task_id": f"{name.lower().replace(' ', '-')}-t4",
                "title": "Sleep",
                "start_time": f"{DATE}T23:00:00",
                "end_time": f"{DATE}T23:59:00",
                "type": "sleep",
                "location": None,
                "notes": None,
            },
        ],
        "total_focus_hours": 2.0,
        "reasoning": f"Reasoning for {name}",
    }


MOCK_GEMINI_OUTPUT = json.dumps({
    "date": DATE,
    "strategies": [
        _make_strategy("Most Productive"),
        _make_strategy("Most Relaxed"),
        _make_strategy("Fastest"),
    ],
    "top_recommendation": "Most Productive",
    "warnings": [],
    "generated_at": f"{DATE}T12:00:00Z",
})

MINIMAL_INPUT = {
    "user_id": "test_user",
    "date": DATE,
    "calendar_events": [],
    "health": {
        "energy_level": "medium",
        "focus_window": "9PM-1AM",
        "cognitive_load_score": 0.72,
        "avoid_tasks": [],
    },
    "goals": {
        "goal_id": "goal-test",
        "urgency": "low",
        "feasibility_score": 1.0,
        "feasibility_note": "",
        "total_effort_minutes": 60,
        "suggested_blocks_count": 1,
        "suggested_split_ratio": [1.0],
        "daily_sub_tasks": [
            {
                "title": "Study session",
                "estimated_minutes": 60,
                "priority": "medium",
                "deadline": str(date(2026, 5, 30)),
                "preferred_time_of_day": "night",
                "can_split": False,
            }
        ],
    },
    "user_preferences": {
        "preferred_work_hours": "late_night",
        "commute_minutes": 30,
        "break_frequency": 90,
    },
}


@pytest.fixture(autouse=True)
def reset_agent_singleton(monkeypatch):
    """Reset the module-level singleton so each test starts fresh."""
    import app.api.schedule_routes as sr
    monkeypatch.setattr(sr, "_agent", None)


@patch("app.agent.schedule_agent.ScheduleAgent.__init__", return_value=None)
@patch("app.agent.schedule_agent.ScheduleAgent._generate", new_callable=AsyncMock)
async def test_generate_returns_200(mock_generate, mock_init, http_client):
    mock_generate.return_value = MOCK_GEMINI_OUTPUT

    resp = await http_client.post("/schedule/generate", json=MINIMAL_INPUT)

    assert resp.status_code == 200
    body = resp.json()
    assert body["date"] == DATE
    assert len(body["strategies"]) == 3
    assert body["top_recommendation"] == "Most Productive"


@patch("app.agent.schedule_agent.ScheduleAgent.__init__", return_value=None)
@patch("app.agent.schedule_agent.ScheduleAgent._generate", new_callable=AsyncMock)
async def test_generate_strategy_names(mock_generate, mock_init, http_client):
    mock_generate.return_value = MOCK_GEMINI_OUTPUT

    resp = await http_client.post("/schedule/generate", json=MINIMAL_INPUT)

    names = [s["name"] for s in resp.json()["strategies"]]
    assert "Most Productive" in names
    assert "Most Relaxed" in names
    assert "Fastest" in names


@patch("app.agent.schedule_agent.ScheduleAgent.__init__", return_value=None)
@patch("app.agent.schedule_agent.ScheduleAgent._generate", new_callable=AsyncMock)
async def test_generate_tasks_have_required_fields(mock_generate, mock_init, http_client):
    mock_generate.return_value = MOCK_GEMINI_OUTPUT

    resp = await http_client.post("/schedule/generate", json=MINIMAL_INPUT)

    for strategy in resp.json()["strategies"]:
        for task in strategy["tasks"]:
            assert "task_id" in task
            assert "title" in task
            assert "start_time" in task
            assert "end_time" in task
            assert "type" in task


@patch("app.agent.schedule_agent.ScheduleAgent.__init__", return_value=None)
@patch("app.agent.schedule_agent.ScheduleAgent._generate", new_callable=AsyncMock)
async def test_generate_with_locked_blocks(mock_generate, mock_init, http_client):
    """Locked blocks should appear in every strategy after _enforce_constraints."""
    locked_output = json.loads(MOCK_GEMINI_OUTPUT)
    # Remove the locked block from strategies so enforce_constraints must inject it
    for s in locked_output["strategies"]:
        s["tasks"] = [t for t in s["tasks"] if t["type"] != "calendar_event"]
    mock_generate.return_value = json.dumps(locked_output)

    payload = dict(MINIMAL_INPUT)
    payload["locked_blocks"] = [
        {
            "task_id": "locked-1",
            "title": "Dentist appointment",
            "start_time": f"{DATE}T14:00:00",
            "end_time": f"{DATE}T15:00:00",
            "type": "calendar_event",
        }
    ]

    resp = await http_client.post("/schedule/generate", json=payload)
    assert resp.status_code == 200

    for strategy in resp.json()["strategies"]:
        titles = [t["title"] for t in strategy["tasks"]]
        assert "Dentist appointment" in titles


@patch("app.agent.schedule_agent.ScheduleAgent.__init__", return_value=None)
@patch("app.agent.schedule_agent.ScheduleAgent._generate", new_callable=AsyncMock)
async def test_missing_required_field_returns_422(mock_generate, mock_init, http_client):
    """ScheduleInput without user_id should be rejected by FastAPI validation."""
    bad_payload = dict(MINIMAL_INPUT)
    del bad_payload["user_id"]

    resp = await http_client.post("/schedule/generate", json=bad_payload)
    assert resp.status_code == 422


async def test_health_returns_ok(http_client):
    resp = await http_client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
