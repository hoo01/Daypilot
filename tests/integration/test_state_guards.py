"""X — 8 parameterized state guard assertions (Invariant I6)."""
import pytest
from agents.tools.goal_db import create_goal, get_goal
from tests.fixtures.domain.factories import (
    make_goal,
    make_subtask,
    make_subtask_completed_event,
    make_overdue_event,
)
from tests.fixtures.goal_agent.reporting import step

# X1-X4: COMPLETED state guards
# X5-X8: ABANDONED state guards
STATE_GUARD_CASES = [
    # (xid, initial_status, event_type, expected_behavior)
    ("X1", "COMPLETED", "overdue",             "ignored"),
    ("X2", "COMPLETED", "subtask_completed",   "ignored"),
    ("X3", "COMPLETED", "abandon",             "rejected"),
    ("X4", "COMPLETED", "replan",              "rejected"),
    ("X5", "ABANDONED", "overdue",             "ignored"),
    ("X6", "ABANDONED", "subtask_completed",   "ignored"),
    ("X7", "ABANDONED", "abandon",             "idempotent"),
    ("X8", "ABANDONED", "replan",              "rejected"),
]


@pytest.mark.scenario("X")
@pytest.mark.category("state_guard")
@pytest.mark.parametrize("xid,initial_status,event_type,expected", STATE_GUARD_CASES)
async def test_X_state_guard(xid, initial_status, event_type, expected, async_client, test_db):
    goal_id = f"g_{xid.lower()}"
    sub = make_subtask("t1", goal_id=goal_id)
    goal = make_goal(goal_id=goal_id, user_id="u_x", status=initial_status, sub_tasks=[sub])
    await create_goal(test_db, goal)

    if event_type == "overdue":
        payload = make_overdue_event(event_id=f"evt_{xid}", goal_id=goal_id, sub_task_ids=["t1"])
        resp = await async_client.post("/v1/events/overdue", json=payload)

        if expected == "ignored":
            assert resp.status_code == 200, f"{xid}: overdue on {initial_status} must return 200"
            g = await get_goal(test_db, goal_id)
            assert g.status == initial_status, (
                f"{xid}: {initial_status} goal status must not change on overdue. Got {g.status!r}"
            )

    elif event_type == "subtask_completed":
        payload = make_subtask_completed_event(event_id=f"evt_{xid}", sub_task_id="t1", goal_id=goal_id)
        resp = await async_client.post("/v1/events/subtask-completed", json=payload)

        if expected == "ignored":
            assert resp.status_code == 200, f"{xid}: subtask-completed on {initial_status} must return 200"
            g = await get_goal(test_db, goal_id)
            assert g.status == initial_status, (
                f"{xid}: {initial_status} status must not change on subtask-completed. Got {g.status!r}"
            )

    elif event_type == "abandon":
        resp = await async_client.post(f"/v1/goals/{goal_id}/abandon", json={"user_id": "u_x"})

        if expected == "rejected":
            assert resp.status_code in (400, 422), (
                f"{xid}: abandon on {initial_status} must be rejected (400/422), got {resp.status_code}"
            )
        elif expected == "idempotent":
            assert resp.status_code == 200, (
                f"{xid}: abandon on already-ABANDONED must be idempotent (200), got {resp.status_code}"
            )
            g = await get_goal(test_db, goal_id)
            assert g.status == "ABANDONED", f"{xid}: status must stay ABANDONED. Got {g.status!r}"

    elif event_type == "replan":
        from datetime import date, timedelta
        resp = await async_client.post(f"/v1/goals/{goal_id}/replan", json={
            "new_deadline": (date.today() + timedelta(days=14)).isoformat(),
            "user_id": "u_x",
        })

        if expected == "rejected":
            assert resp.status_code in (400, 422), (
                f"{xid}: replan on {initial_status} must be rejected (400/422), got {resp.status_code}: {resp.text}"
            )
