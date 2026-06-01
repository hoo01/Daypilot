"""S1, S2, S3, S4 — state transitions via event endpoints."""
import pytest
from datetime import date, timedelta

from agents.tools.goal_db import create_goal, get_goal, set_goal_status
from tests.fixtures.domain.factories import (
    make_goal,
    make_subtask,
    make_subtask_scheduled_event,
    make_subtask_completed_event,
    make_overdue_event,
)
from tests.fixtures.goal_agent.reporting import step


@pytest.mark.scenario("S1")
@pytest.mark.category("state")
async def test_S1_subtask_scheduled_transitions_to_in_progress(async_client, test_db):
    """subtask-scheduled event → goal CREATED → IN_PROGRESS; planned_date written."""
    with step("Seed CREATED goal with one sub-task"):
        sub = make_subtask("t1", goal_id="g_s1")
        goal = make_goal(goal_id="g_s1", user_id="u_s1", status="CREATED", sub_tasks=[sub])
        await create_goal(test_db, goal)

    with step("POST subtask-scheduled event"):
        payload = make_subtask_scheduled_event(
            event_id="evt_s1", sub_task_id="t1", goal_id="g_s1"
        )
        resp = await async_client.post("/v1/events/subtask-scheduled", json=payload)

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    ack = resp.json()

    with step("Verify EventAck status == acknowledged"):
        assert ack["status"] == "acknowledged", (
            f"Expected acknowledged, got {ack['status']!r}. Warnings: {ack['warnings']}"
        )

    with step("Verify goal status transitioned to IN_PROGRESS"):
        g = await get_goal(test_db, "g_s1")
        assert g is not None
        assert g.status == "IN_PROGRESS", (
            f"Expected IN_PROGRESS after subtask-scheduled, got {g.status!r}"
        )

    with step("Verify planned_date written to sub-task"):
        t = next((t for t in g.sub_tasks if t.sub_task_id == "t1"), None)
        assert t is not None, "Sub-task t1 must exist"
        assert t.planned_date is not None, (
            "planned_date must be set on sub-task after subtask-scheduled event"
        )


@pytest.mark.scenario("S2")
@pytest.mark.category("state")
async def test_S2_subtask_completed_increments_progress_then_completes(async_client, test_db):
    """3 subtask-completed events → progress increments accurately → final status COMPLETED."""
    with step("Seed goal with 3 sub-tasks (0% progress)"):
        sub_tasks = [
            make_subtask("t1", goal_id="g_s2", is_completed=False),
            make_subtask("t2", goal_id="g_s2", is_completed=False),
            make_subtask("t3", goal_id="g_s2", is_completed=False),
        ]
        goal = make_goal(
            goal_id="g_s2", user_id="u_s2", status="IN_PROGRESS",
            sub_tasks=sub_tasks, progress_percent=0.0
        )
        await create_goal(test_db, goal)

    with step("Complete t1 → expect progress ~33.33%, status IN_PROGRESS"):
        resp = await async_client.post("/v1/events/subtask-completed", json=make_subtask_completed_event(
            event_id="evt_s2_1", sub_task_id="t1", goal_id="g_s2"
        ))
        assert resp.status_code == 200
        g = await get_goal(test_db, "g_s2")
        assert g.progress_percent == pytest.approx(33.33, abs=0.01), (
            f"Expected ~33.33%, got {g.progress_percent}"
        )
        assert g.status == "IN_PROGRESS"

    with step("Complete t2 → expect progress ~66.67%, status IN_PROGRESS"):
        resp = await async_client.post("/v1/events/subtask-completed", json=make_subtask_completed_event(
            event_id="evt_s2_2", sub_task_id="t2", goal_id="g_s2"
        ))
        assert resp.status_code == 200
        g = await get_goal(test_db, "g_s2")
        assert g.progress_percent == pytest.approx(66.67, abs=0.01)
        assert g.status == "IN_PROGRESS"

    with step("Complete t3 (last) → expect progress == 100.0, status COMPLETED"):
        resp = await async_client.post("/v1/events/subtask-completed", json=make_subtask_completed_event(
            event_id="evt_s2_3", sub_task_id="t3", goal_id="g_s2"
        ))
        assert resp.status_code == 200
        g = await get_goal(test_db, "g_s2")
        assert g.progress_percent == 100.0, (
            f"Expected exactly 100.0, got {g.progress_percent}. "
            f"Sub-tasks: {[(t.sub_task_id, t.is_completed) for t in g.sub_tasks]}"
        )
        assert g.status == "COMPLETED", (
            f"Expected COMPLETED after all sub-tasks done, got {g.status!r}"
        )


@pytest.mark.scenario("S3")
@pytest.mark.category("state")
async def test_S3_overdue_notification_generates_reminder(async_client, test_db):
    """Overdue notification → progress recalculated → reminder in EventAck.warnings."""
    with step("Seed IN_PROGRESS goal with 2 of 3 sub-tasks complete"):
        sub_tasks = [
            make_subtask("t1", goal_id="g_s3", is_completed=True),
            make_subtask("t2", goal_id="g_s3", is_completed=True),
            make_subtask("t3", goal_id="g_s3", is_completed=False),
        ]
        goal = make_goal(
            goal_id="g_s3", user_id="u_s3", status="IN_PROGRESS",
            sub_tasks=sub_tasks, progress_percent=66.67
        )
        await create_goal(test_db, goal)

    with step("POST overdue notification for t3"):
        payload = make_overdue_event(event_id="evt_s3", goal_id="g_s3", sub_task_ids=["t3"])
        resp = await async_client.post("/v1/events/overdue", json=payload)

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    ack = resp.json()

    with step("Verify ack.status == acknowledged, warnings contain reminder:"):
        assert ack["status"] == "acknowledged", (
            f"Expected acknowledged, got {ack['status']!r}"
        )
        reminder_warnings = [w for w in ack["warnings"] if w.startswith("reminder:")]
        assert len(reminder_warnings) > 0, (
            f"Expected at least one 'reminder:' warning. Got: {ack['warnings']}"
        )


@pytest.mark.scenario("S4")
@pytest.mark.category("state")
async def test_S4_replan_updates_deadline_and_status(async_client, test_db):
    """POST /v1/goals/{id}/replan → status IN_PROGRESS; deadline updated."""
    with step("Seed OVERDUE goal"):
        goal = make_goal(
            goal_id="g_s4", user_id="u_s4", status="OVERDUE",
            deadline=date.today() - timedelta(days=1)
        )
        await create_goal(test_db, goal)

    new_deadline = date.today() + timedelta(days=14)

    with step("POST /v1/goals/g_s4/replan with new deadline"):
        resp = await async_client.post("/v1/goals/g_s4/replan", json={
            "new_deadline": new_deadline.isoformat(),
            "user_id": "u_s4",
        })

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()

    with step("Verify status == IN_PROGRESS and deadline updated"):
        assert data["status"] == "IN_PROGRESS", (
            f"Expected IN_PROGRESS after replan, got {data['status']!r}"
        )
        assert data["deadline"] == new_deadline.isoformat(), (
            f"Expected deadline {new_deadline}, got {data['deadline']!r}"
        )
