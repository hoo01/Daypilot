"""B1, B2 — floating-point boundary and deadline=today urgency."""
import pytest
from datetime import date, timedelta
from freezegun import freeze_time

from agents.tools.goal_db import create_goal, get_goal
from tests.fixtures.domain.factories import make_goal, make_subtask, make_subtask_completed_event
from tests.fixtures.goal_agent.reporting import step


@pytest.mark.scenario("B1")
@pytest.mark.category("boundary")
async def test_B1_last_subtask_pushes_progress_to_exactly_100(async_client, test_db):
    """Final subtask-completed pushes progress to exactly 100.0 (floating-point boundary)."""
    with step("Seed goal with 3 sub-tasks, 2 already complete (progress=66.67)"):
        sub_tasks = [
            make_subtask("tb1", goal_id="g_b1", is_completed=True),
            make_subtask("tb2", goal_id="g_b1", is_completed=True),
            make_subtask("tb3", goal_id="g_b1", is_completed=False),
        ]
        goal = make_goal(
            goal_id="g_b1", user_id="u_b1", status="IN_PROGRESS",
            sub_tasks=sub_tasks, progress_percent=66.67
        )
        await create_goal(test_db, goal)

    with step("POST subtask-completed for tb3 (last sub-task)"):
        resp = await async_client.post("/v1/events/subtask-completed", json=make_subtask_completed_event(
            event_id="evt_b1", sub_task_id="tb3", goal_id="g_b1"
        ))
        assert resp.status_code == 200

    with step("Verify progress_percent == 100.0 exactly (not 99.99 or 100.001)"):
        g = await get_goal(test_db, "g_b1")
        assert g.progress_percent == 100.0, (
            f"Expected exactly 100.0 on last sub-task completion, got {g.progress_percent}"
        )

    with step("Verify status transitions to COMPLETED at exactly 100.0"):
        assert g.status == "COMPLETED", (
            f"Expected COMPLETED when progress == 100.0, got {g.status!r}"
        )


@pytest.mark.scenario("B2")
@pytest.mark.category("boundary")
async def test_B2_deadline_today_has_high_urgency(async_client, test_db):
    """deadline = date.today() → daily output urgency must be 'high'."""
    today = date.today()

    with step(f"Seed goal with deadline == today ({today})"):
        goal = make_goal(
            goal_id="g_b2", user_id="u_b2", status="IN_PROGRESS",
            deadline=today, total_effort_minutes=60
        )
        await create_goal(test_db, goal)

    with step("POST /v1/scheduled/daily-output for u_b2"):
        resp = await async_client.post("/v1/scheduled/daily-output", json={"user_id": "u_b2"})
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()

    with step("Verify urgency == 'high' for goal with today's deadline"):
        outputs = data.get("goals_output", [])
        assert len(outputs) >= 1, "Expected at least 1 GoalsOutput in response"
        g_out = next((o for o in outputs if o["goal_id"] == "g_b2"), None)
        assert g_out is not None, "Goal g_b2 must appear in daily output"
        assert g_out["urgency"] == "high", (
            f"Goal with deadline=today must have urgency='high'. Got: {g_out['urgency']!r}"
        )
