"""E1, E2, E3, E4 — degraded and edge paths."""
import pytest

from agents.tools.goal_db import create_goal
from agents.tools.feasibility_calc import habit_feasibility, time_feasibility
from tests.fixtures.domain.factories import (
    make_goal,
    make_subtask,
    make_overdue_event,
    make_subtask_scheduled_event,
)
from tests.fixtures.goal_agent.reporting import step
from db.collections import Collections


@pytest.mark.scenario("E1")
@pytest.mark.category("edge")
async def test_E1_new_user_empty_memory_context_uses_fallback(test_db):
    """Empty memory_context → degraded=False, note contains 'no_memory_baseline'."""
    with step("Call habit_feasibility with empty memory_context (new user)"):
        result = habit_feasibility(
            total_effort_minutes=120,
            memory_context="",
            goal_type="weekly",
            deadline_days=7,
        )

    with step("Verify degraded is False (fallback, not a system failure)"):
        assert result.degraded is False, (
            f"Empty memory context must NOT set degraded=True. Got degraded={result.degraded}"
        )

    with step("Verify feasibility_note contains 'no_memory_baseline'"):
        assert "no_memory_baseline" in result.note, (
            f"Note must contain 'no_memory_baseline'. Got: {result.note!r}"
        )


@pytest.mark.scenario("E2")
@pytest.mark.category("edge")
async def test_E2_empty_calendar_slots_degrades_time_feasibility(test_db):
    """calendar_free_slots == [] → time feasibility degrades; score capped at 0.7."""
    from agents.tools.feasibility_calc import synthesize_feasibility, FeasibilityLayerResult

    with step("Call time_feasibility with free_minutes=None (empty slots)"):
        time_result = time_feasibility(
            total_effort_minutes=120,
            remaining_days=3,
            free_minutes=None,
        )

    with step("Verify time_result.degraded == True"):
        assert time_result.degraded is True, (
            f"Empty calendar slots must set degraded=True. Got: {time_result.degraded}"
        )

    with step("Verify synthesized score is capped at 0.7"):
        habit_ok = FeasibilityLayerResult("habit", feasible=True, overload_flag=False, degraded=False)
        load_ok = FeasibilityLayerResult("load", feasible=True, overload_flag=False, degraded=False)
        score, _ = synthesize_feasibility(time_result, habit_ok, load_ok)
        assert score <= 0.7, (
            f"Score must be capped at 0.7 when any layer is degraded. Got: {score}"
        )


@pytest.mark.scenario("E3")
@pytest.mark.category("edge")
async def test_E3_unknown_subtask_id_returns_partial_ack(async_client, test_db):
    """Overdue notification with unknown sub_task_id → status=partial, warning written."""
    with step("Seed IN_PROGRESS goal without the referenced sub_task_id"):
        real_sub = make_subtask("t10", goal_id="g_e3")
        goal = make_goal(
            goal_id="g_e3", user_id="u_e3", status="IN_PROGRESS", sub_tasks=[real_sub]
        )
        await create_goal(test_db, goal)

    with step("POST overdue event referencing unknown sub_task_id t99"):
        payload = make_overdue_event(event_id="evt_e3", goal_id="g_e3", sub_task_ids=["t99"])
        resp = await async_client.post("/v1/events/overdue", json=payload)

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    ack = resp.json()

    with step("Verify ack.status == partial"):
        assert ack["status"] == "partial", (
            f"Expected partial for unknown sub_task_id, got {ack['status']!r}"
        )

    with step("Verify warnings contain 'unknown_sub_task_id: t99'"):
        assert any("unknown_sub_task_id" in w and "t99" in w for w in ack["warnings"]), (
            f"Expected unknown_sub_task_id warning. Got: {ack['warnings']}"
        )

    with step("Verify event_log entry has status == partial"):
        entry = await test_db[Collections.EVENT_LOG].find_one({"event_id": "evt_e3"})
        assert entry is not None, "event_log entry must exist"
        assert entry["status"] == "partial", (
            f"event_log.status must be 'partial'. Got: {entry['status']!r}"
        )


@pytest.mark.scenario("E4")
@pytest.mark.category("edge")
async def test_E4_duplicate_event_id_returns_already_processed(async_client, test_db):
    """Same event_id sent twice → second response status == already_processed."""
    with step("Seed CREATED goal with sub-task"):
        sub = make_subtask("t1", goal_id="g_e4")
        goal = make_goal(goal_id="g_e4", user_id="u_e4", status="CREATED", sub_tasks=[sub])
        await create_goal(test_db, goal)

    payload = make_subtask_scheduled_event(event_id="evt_e4", sub_task_id="t1", goal_id="g_e4")

    with step("POST subtask-scheduled (first time) → acknowledged"):
        resp1 = await async_client.post("/v1/events/subtask-scheduled", json=payload)
        assert resp1.status_code == 200
        assert resp1.json()["status"] == "acknowledged"

    with step("POST same event_id again → already_processed"):
        resp2 = await async_client.post("/v1/events/subtask-scheduled", json=payload)

    assert resp2.status_code == 200, f"Expected 200, got {resp2.status_code}: {resp2.text}"
    ack2 = resp2.json()

    with step("Verify second ack.status == already_processed (Invariant I5)"):
        assert ack2["status"] == "already_processed", (
            f"Expected already_processed for duplicate event_id. Got: {ack2['status']!r}"
        )
        assert ack2["processed_count"] == 0

    with step("Verify DB state unchanged (still only one event_log entry)"):
        count = await test_db[Collections.EVENT_LOG].count_documents({"event_id": "evt_e4"})
        assert count == 1, f"Expected exactly 1 event_log entry, got {count}"
