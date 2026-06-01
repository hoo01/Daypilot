"""C1 — concurrent subtask-completed, no lost update (Invariant I9)."""
import asyncio
import pytest
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI

from agents.tools.goal_db import create_goal, get_goal
from tests.fixtures.domain.factories import make_goal, make_subtask, make_subtask_completed_event
from tests.fixtures.goal_agent.reporting import step
from api.routes import events, goals as goals_router


@pytest.mark.scenario("C1")
@pytest.mark.category("concurrency")
async def test_C1_concurrent_subtask_completed_no_lost_update(test_db):
    """Two subtask-completed events fire simultaneously → progress_percent == 100.0 (no lost update)."""
    with step("Seed IN_PROGRESS goal with 2 incomplete sub-tasks"):
        sub_tasks = [
            make_subtask("tc1", goal_id="g_c1", is_completed=False),
            make_subtask("tc2", goal_id="g_c1", is_completed=False),
        ]
        goal = make_goal(
            goal_id="g_c1", user_id="u_c1", status="IN_PROGRESS",
            sub_tasks=sub_tasks, progress_percent=0.0
        )
        await create_goal(test_db, goal)

    # Build two independent clients (they'll share the same DB via patched _client)
    app = FastAPI()
    app.include_router(events.router)
    app.include_router(goals_router.router)

    payload_tc1 = make_subtask_completed_event(event_id="evt_c1_a", sub_task_id="tc1", goal_id="g_c1")
    payload_tc2 = make_subtask_completed_event(event_id="evt_c1_b", sub_task_id="tc2", goal_id="g_c1")

    with step("Fire both subtask-completed events simultaneously via asyncio.gather"):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c1, \
                   AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c2:
            results = await asyncio.gather(
                c1.post("/v1/events/subtask-completed", json=payload_tc1),
                c2.post("/v1/events/subtask-completed", json=payload_tc2),
            )

    r1, r2 = results
    with step("Verify both requests returned 200"):
        assert r1.status_code == 200, f"Request 1 failed: {r1.status_code} {r1.text}"
        assert r2.status_code == 200, f"Request 2 failed: {r2.status_code} {r2.text}"

    with step("Verify progress_percent == 100.0 (no lost update, Invariant I9)"):
        g = await get_goal(test_db, "g_c1")
        assert g is not None
        assert g.progress_percent == 100.0, (
            f"Expected exactly 100.0 after both sub-tasks completed concurrently, "
            f"got {g.progress_percent}. "
            f"Sub-tasks: {[(t.sub_task_id, t.is_completed) for t in g.sub_tasks]}"
        )

    with step("Verify goal status == COMPLETED"):
        assert g.status == "COMPLETED", (
            f"Expected COMPLETED after 100% progress, got {g.status!r}"
        )
