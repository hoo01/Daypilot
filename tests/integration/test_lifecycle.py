"""L1, L3 — abandon and expired-session lifecycle paths."""
import pytest
from datetime import datetime, timedelta, timezone

from agents.tools.goal_db import create_goal, get_goal
from tests.fixtures.domain.factories import make_goal
from tests.fixtures.goal_agent.reporting import step
from db.collections import Collections


@pytest.mark.scenario("L1")
@pytest.mark.category("lifecycle")
async def test_L1_abandon_goal_transitions_to_abandoned(async_client, test_db):
    """POST /v1/goals/{id}/abandon → status ABANDONED; event_log entry written."""
    with step("Seed IN_PROGRESS goal"):
        goal = make_goal(goal_id="g_l1", user_id="u_l1", status="IN_PROGRESS")
        await create_goal(test_db, goal)

    with step("POST /v1/goals/g_l1/abandon"):
        resp = await async_client.post("/v1/goals/g_l1/abandon", json={
            "user_id": "u_l1",
            "reason": "Changed priorities",
        })

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()

    with step("Verify status == ABANDONED"):
        assert data["status"] == "ABANDONED", (
            f"Expected ABANDONED, got {data['status']!r}"
        )

    with step("Verify goal in DB has status ABANDONED"):
        g = await get_goal(test_db, "g_l1")
        assert g.status == "ABANDONED", f"DB goal must be ABANDONED, got {g.status!r}"

    with step("Verify event_log has an abandon entry"):
        entry = await test_db[Collections.EVENT_LOG].find_one({"goal_id": "g_l1", "event_type": "abandon"})
        assert entry is not None, "event_log must have an entry for the abandon event"


@pytest.mark.scenario("L3")
@pytest.mark.category("lifecycle")
async def test_L3_expired_session_returns_410(async_client, test_db):
    """Expired intake session → POST /v1/intake/turn → HTTP 410 Gone."""
    with step("Insert expired intake session directly into DB"):
        now = datetime.now(timezone.utc)
        expired_session = {
            "session_id": "sess_expired",
            "user_id": "u_l3",
            "status": "open",
            "stage": "validating",
            "draft": {},
            "history": [],
            "validation_failures": [],
            "created_at": (now - timedelta(hours=25)).isoformat(),
            "last_active_at": (now - timedelta(hours=25)).isoformat(),
            "expires_at": (now - timedelta(hours=1)).isoformat(),  # already expired
            "goal_id": None,
        }
        await test_db[Collections.INTAKE_SESSIONS].insert_one(expired_session)

    with step("POST /v1/intake/turn with expired session_id → expect 410"):
        payload = {
            "user_id": "u_l3",
            "intent": "add_goal_continue",
            "raw_user_message": "continuing my goal",
            "health": {"energy_score": 0.7, "focus_windows": [], "cognitive_load": 0.3},
            "memory_context": "",
            "calendar_free_slots": [],
            "session_id": "sess_expired",
        }
        resp = await async_client.post("/v1/intake/turn", json=payload)

    with step("Verify HTTP 410 and error body"):
        assert resp.status_code == 410, (
            f"Expected 410 Gone for expired session, got {resp.status_code}: {resp.text}"
        )
        body = resp.json()
        detail = body.get("detail", body)
        error_text = str(detail)
        assert "intake_session_expired" in error_text, (
            f"Response must contain 'intake_session_expired'. Got: {error_text!r}"
        )
