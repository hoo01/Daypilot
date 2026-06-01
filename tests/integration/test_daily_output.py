"""N4 — 3 active goals → daily-output → goals_output len==3, no planned_date in any GoalSubTask."""
import pytest
from datetime import date, timedelta

from agents.tools.goal_db import create_goal
from tests.fixtures.domain.factories import make_goal, make_subtask
from tests.fixtures.goal_agent.reporting import step


@pytest.mark.scenario("N4")
@pytest.mark.category("daily_output")
async def test_N4_daily_output_returns_all_active_goals_without_planned_date(async_client, test_db):
    """3 active goals for same user → POST /v1/scheduled/daily-output → len==3, no planned_date."""
    today = date.today()
    deadline = today + timedelta(days=7)

    with step("Seed 3 IN_PROGRESS goals for user u_n4"):
        for i in range(1, 4):
            sub = make_subtask(f"tn4_{i}", goal_id=f"g_n4_{i}")
            goal = make_goal(
                goal_id=f"g_n4_{i}",
                user_id="u_n4",
                status="IN_PROGRESS",
                sub_tasks=[sub],
                total_effort_minutes=60 * i,
                deadline=deadline,
            )
            await create_goal(test_db, goal)

    with step("POST /v1/scheduled/daily-output for u_n4"):
        resp = await async_client.post(
            "/v1/scheduled/daily-output",
            json={"user_id": "u_n4"},
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()

    with step("Verify goals_output contains exactly 3 entries"):
        outputs = data.get("goals_output", [])
        assert len(outputs) == 3, (
            f"Expected 3 goals in daily output for u_n4, got {len(outputs)}. Data: {data}"
        )

    with step("Verify no GoalSubTask contains a planned_date field (Invariant I1)"):
        for goal_out in outputs:
            sub_tasks = goal_out.get("sub_tasks", [])
            for st in sub_tasks:
                assert "planned_date" not in st, (
                    f"GoalSubTask must never contain planned_date (I1). "
                    f"Found in goal {goal_out.get('goal_id')}: {st}"
                )

    with step("Verify all 3 goal_ids appear in output"):
        output_ids = {o["goal_id"] for o in outputs}
        for i in range(1, 4):
            assert f"g_n4_{i}" in output_ids, (
                f"Goal g_n4_{i} missing from daily output. Got ids: {output_ids}"
            )
