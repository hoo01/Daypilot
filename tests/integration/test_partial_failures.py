"""P2 — write_weekly_summary raises HTTPStatusError; status='failed', goals intact, HTTP 200."""
import pytest
import httpx
from unittest.mock import AsyncMock, patch

from agents.tools.goal_db import create_goal, get_goal
from tests.fixtures.domain.factories import make_goal, make_subtask
from tests.fixtures.goal_agent.reporting import step


@pytest.mark.scenario("P2")
@pytest.mark.category("partial_failure")
async def test_P2_weekly_memory_write_failure_returns_200_with_errors(async_client, test_db):
    """write_weekly_summary raises HTTPStatusError → status='failed', goals intact, HTTP 200 with errors."""
    with step("Seed 1 active goal for user u_p2"):
        sub = make_subtask("tp2", goal_id="g_p2")
        goal = make_goal(
            goal_id="g_p2", user_id="u_p2", status="IN_PROGRESS",
            sub_tasks=[sub], progress_percent=50.0,
        )
        await create_goal(test_db, goal)

    with step("Patch write_weekly_summary to raise HTTPStatusError"):
        error_response = httpx.Response(503, text="Service Unavailable")
        http_error = httpx.HTTPStatusError(
            "503 Service Unavailable",
            request=httpx.Request("POST", "http://memory-agent/weekly"),
            response=error_response,
        )

        with patch(
            "api.routes.scheduled.write_weekly_summary",
            new=AsyncMock(side_effect=http_error),
        ):
            with step("POST /v1/scheduled/weekly-memory for u_p2"):
                resp = await async_client.post(
                    "/v1/scheduled/weekly-memory",
                    json={"user_id": "u_p2"},
                )

    with step("Verify HTTP 200 (partial failure must not cause 5xx)"):
        assert resp.status_code == 200, (
            f"Weekly memory write failure must return 200, got {resp.status_code}: {resp.text}"
        )

    with step("Verify response contains non-empty errors list"):
        data = resp.json()
        errors = data.get("errors", [])
        assert len(errors) > 0, (
            f"Response must contain errors when write_weekly_summary fails. Got: {data}"
        )

    with step("Verify goal g_p2 is intact after memory write failure"):
        g = await get_goal(test_db, "g_p2")
        assert g is not None, "Goal g_p2 must still exist after memory write failure"
        assert g.status == "IN_PROGRESS", (
            f"Goal status must be unchanged (IN_PROGRESS). Got: {g.status!r}"
        )
        assert g.progress_percent == 50.0, (
            f"Goal progress must be unchanged (50.0). Got: {g.progress_percent}"
        )
