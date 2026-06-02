"""Integration tests for replan/reduce-scope flow and replan_pending propagation."""
import pytest
from datetime import date, datetime, timedelta, timezone

from agents.tools.goal_db import create_goal, get_goal
from tests.fixtures.domain.factories import make_goal, make_subtask
from tests.fixtures.goal_agent.reporting import step
from db.collections import Collections


TODAY = date.today()


# ---------------------------------------------------------------------------
# POST /v1/goals/{id}/replan
# ---------------------------------------------------------------------------

@pytest.mark.scenario("RP1")
@pytest.mark.category("replan_flow")
async def test_RP1_replan_clears_replan_requested_at(async_client, test_db):
    """replan_goal: updates deadline, sets IN_PROGRESS, clears replan_requested_at."""
    with step("Seed OVERDUE goal with replan_requested_at set"):
        goal = make_goal(
            goal_id="g_rp1", user_id="u_rp1", status="OVERDUE",
            deadline=TODAY + timedelta(days=1),
            replan_requested_at=datetime.now(timezone.utc),
        )
        await create_goal(test_db, goal)

    new_deadline = (TODAY + timedelta(days=14)).isoformat()

    with step("POST /v1/goals/g_rp1/replan with new deadline"):
        resp = await async_client.post("/v1/goals/g_rp1/replan", json={
            "user_id": "u_rp1",
            "new_deadline": new_deadline,
        })
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    with step("Verify goal status is IN_PROGRESS"):
        g = await get_goal(test_db, "g_rp1")
        assert g.status == "IN_PROGRESS", f"Expected IN_PROGRESS, got {g.status!r}"

    with step("Verify deadline updated"):
        assert g.deadline.isoformat() == new_deadline

    with step("Verify replan_requested_at is cleared"):
        assert g.replan_requested_at is None, (
            f"replan_requested_at must be None after replan; got {g.replan_requested_at}"
        )

    with step("Verify event_log entry written"):
        entry = await test_db[Collections.EVENT_LOG].find_one(
            {"goal_id": "g_rp1", "event_type": "replan"}
        )
        assert entry is not None


@pytest.mark.scenario("RP2")
@pytest.mark.category("replan_flow")
async def test_RP2_replan_blocked_on_terminal_goal(async_client, test_db):
    """replan_goal on COMPLETED goal → 422."""
    with step("Seed COMPLETED goal"):
        goal = make_goal(goal_id="g_rp2", user_id="u_rp2", status="COMPLETED")
        await create_goal(test_db, goal)

    with step("POST /v1/goals/g_rp2/replan → expect 422"):
        resp = await async_client.post("/v1/goals/g_rp2/replan", json={
            "user_id": "u_rp2",
            "new_deadline": (TODAY + timedelta(days=7)).isoformat(),
        })
        assert resp.status_code == 422, f"Expected 422, got {resp.status_code}: {resp.text}"


# ---------------------------------------------------------------------------
# POST /v1/goals/{id}/reduce-scope
# ---------------------------------------------------------------------------

@pytest.mark.scenario("RS1")
@pytest.mark.category("replan_flow")
async def test_RS1_reduce_scope_marks_subtasks_abandoned_and_clears_flag(async_client, test_db):
    """reduce-scope: listed subtasks get abandoned=True, replan flag cleared."""
    with step("Seed IN_PROGRESS goal with 3 subtasks and replan flag set"):
        subs = [
            make_subtask(f"t_rs1_{i}", goal_id="g_rs1", is_completed=False,
                         estimated_minutes=30)
            for i in range(3)
        ]
        goal = make_goal(
            goal_id="g_rs1", user_id="u_rs1", status="IN_PROGRESS",
            sub_tasks=subs,
            replan_requested_at=datetime.now(timezone.utc),
        )
        await create_goal(test_db, goal)

    with step("POST /v1/goals/g_rs1/reduce-scope — abandon t_rs1_1 and t_rs1_2"):
        resp = await async_client.post("/v1/goals/g_rs1/reduce-scope", json={
            "user_id": "u_rs1",
            "sub_task_ids": ["t_rs1_1", "t_rs1_2"],
        })
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    with step("Verify t_rs1_1 and t_rs1_2 are abandoned in DB"):
        g = await get_goal(test_db, "g_rs1")
        task_map = {t.sub_task_id: t for t in g.sub_tasks}
        assert task_map["t_rs1_1"].abandoned is True
        assert task_map["t_rs1_2"].abandoned is True
        assert task_map["t_rs1_0"].abandoned is False

    with step("Verify replan_requested_at cleared"):
        assert g.replan_requested_at is None

    with step("Verify event_log entry written"):
        entry = await test_db[Collections.EVENT_LOG].find_one(
            {"goal_id": "g_rs1", "event_type": "reduce_scope"}
        )
        assert entry is not None


@pytest.mark.scenario("RS2")
@pytest.mark.category("replan_flow")
async def test_RS2_reduce_scope_recalculates_progress_excluding_abandoned(async_client, test_db):
    """reduce-scope: progress_percent recomputed without abandoned tasks."""
    with step("Seed goal: t1 completed, t2 incomplete, t3 incomplete"):
        subs = [
            make_subtask("t_rs2_1", goal_id="g_rs2", is_completed=True),
            make_subtask("t_rs2_2", goal_id="g_rs2", is_completed=False),
            make_subtask("t_rs2_3", goal_id="g_rs2", is_completed=False),
        ]
        goal = make_goal(
            goal_id="g_rs2", user_id="u_rs2", status="IN_PROGRESS",
            progress_percent=33.33, sub_tasks=subs,
        )
        await create_goal(test_db, goal)

    with step("Abandon t_rs2_2 and t_rs2_3 via reduce-scope"):
        resp = await async_client.post("/v1/goals/g_rs2/reduce-scope", json={
            "user_id": "u_rs2",
            "sub_task_ids": ["t_rs2_2", "t_rs2_3"],
        })
        assert resp.status_code == 200

    with step("Verify progress_percent is now 100% (only t1 active and it's complete)"):
        g = await get_goal(test_db, "g_rs2")
        assert g.progress_percent == 100.0, (
            f"After abandoning all incomplete tasks, progress must be 100%. Got {g.progress_percent}"
        )

    with step("Verify goal auto-completed when progress hits 100%"):
        assert g.status == "COMPLETED", (
            f"Goal should be COMPLETED when all active tasks done. Got {g.status!r}"
        )


@pytest.mark.scenario("RS3")
@pytest.mark.category("replan_flow")
async def test_RS3_reduce_scope_blocked_on_terminal_goal(async_client, test_db):
    """reduce-scope on ABANDONED goal → 422."""
    with step("Seed ABANDONED goal"):
        goal = make_goal(goal_id="g_rs3", user_id="u_rs3", status="ABANDONED")
        await create_goal(test_db, goal)

    with step("POST /v1/goals/g_rs3/reduce-scope → expect 422"):
        resp = await async_client.post("/v1/goals/g_rs3/reduce-scope", json={
            "user_id": "u_rs3",
            "sub_task_ids": [],
        })
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# replan_pending propagation through daily-output
# ---------------------------------------------------------------------------

@pytest.mark.scenario("RP3")
@pytest.mark.category("replan_flow")
async def test_RP3_daily_output_sets_replan_pending_true_when_flag_set(async_client, test_db):
    """GoalsOutput.replan_pending=True when goal.replan_requested_at is set."""
    with step("Seed OVERDUE goal with replan_requested_at set"):
        goal = make_goal(
            goal_id="g_rp3", user_id="u_rp3", status="OVERDUE",
            replan_requested_at=datetime.now(timezone.utc),
        )
        await create_goal(test_db, goal)

    with step("POST /v1/scheduled/daily-output"):
        resp = await async_client.post(
            "/v1/scheduled/daily-output",
            json={"user_id": "u_rp3"},
        )
        assert resp.status_code == 200
        data = resp.json()

    with step("Verify replan_pending=True in goals_output"):
        outputs = data.get("goals_output", [])
        assert len(outputs) == 1
        assert outputs[0]["replan_pending"] is True, (
            f"Expected replan_pending=True, got {outputs[0].get('replan_pending')}"
        )


@pytest.mark.scenario("RP4")
@pytest.mark.category("replan_flow")
async def test_RP4_daily_output_replan_pending_false_when_no_flag(async_client, test_db):
    """GoalsOutput.replan_pending=False when goal.replan_requested_at is None."""
    with step("Seed normal IN_PROGRESS goal (no replan flag)"):
        goal = make_goal(
            goal_id="g_rp4", user_id="u_rp4", status="IN_PROGRESS",
            replan_requested_at=None,
        )
        await create_goal(test_db, goal)

    with step("POST /v1/scheduled/daily-output"):
        resp = await async_client.post(
            "/v1/scheduled/daily-output",
            json={"user_id": "u_rp4"},
        )
        assert resp.status_code == 200
        data = resp.json()

    with step("Verify replan_pending=False in goals_output"):
        outputs = data.get("goals_output", [])
        assert len(outputs) == 1
        assert outputs[0]["replan_pending"] is False
