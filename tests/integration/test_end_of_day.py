"""Integration tests for POST /v1/scheduled/end-of-day."""
import pytest
from datetime import date, timedelta

from agents.tools.goal_db import create_goal, get_goal
from tests.fixtures.domain.factories import make_goal, make_subtask
from tests.fixtures.goal_agent.reporting import step
from db.collections import Collections


TODAY = date.today()
TOMORROW = TODAY + timedelta(days=1)


@pytest.mark.scenario("EOD1")
@pytest.mark.category("end_of_day")
async def test_EOD1_incomplete_task_carried_to_tomorrow_when_on_track(async_client, test_db):
    """On-track goal: incomplete subtask planned_date bumped to tomorrow, no replan flag."""
    with step("Seed IN_PROGRESS goal with one incomplete subtask planned for today"):
        sub = make_subtask(
            "t_eod1", goal_id="g_eod1",
            is_completed=False, planned_date=TODAY,
            estimated_minutes=60,
        )
        goal = make_goal(
            goal_id="g_eod1", user_id="u_eod1",
            status="IN_PROGRESS",
            deadline=TODAY + timedelta(days=10),  # far deadline → on_track
            progress_percent=50.0,
            sub_tasks=[sub],
        )
        await create_goal(test_db, goal)

    with step("POST /v1/scheduled/end-of-day"):
        resp = await async_client.post(
            "/v1/scheduled/end-of-day",
            json={"user_id": "u_eod1", "date": TODAY.isoformat()},
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()

    with step("Verify response action is carried_over"):
        assert data["goals_processed"] == 1
        result = data["results"][0]
        assert result["action"] == "carried_over", (
            f"Expected 'carried_over', got {result['action']!r}"
        )
        assert result["incomplete_count"] == 1

    with step("Verify subtask planned_date updated to tomorrow in DB"):
        g = await get_goal(test_db, "g_eod1")
        subtask = next(t for t in g.sub_tasks if t.sub_task_id == "t_eod1")
        assert subtask.planned_date == TOMORROW, (
            f"Expected planned_date={TOMORROW}, got {subtask.planned_date}"
        )

    with step("Verify replan_requested_at is NOT set"):
        assert g.replan_requested_at is None


@pytest.mark.scenario("EOD2")
@pytest.mark.category("end_of_day")
async def test_EOD2_replan_requested_when_deadline_near_and_behind(async_client, test_db):
    """Level-2 condition: remaining_days <= 3 AND progress < 70 → replan_requested."""
    with step("Seed OVERDUE goal with 2-day deadline and low progress"):
        sub1 = make_subtask("t_eod2a", goal_id="g_eod2", is_completed=False,
                            planned_date=TODAY, estimated_minutes=60)
        sub2 = make_subtask("t_eod2b", goal_id="g_eod2", is_completed=False,
                            planned_date=TODAY, estimated_minutes=60)
        goal = make_goal(
            goal_id="g_eod2", user_id="u_eod2",
            status="IN_PROGRESS",
            deadline=TODAY + timedelta(days=2),  # <= 3 days
            progress_percent=20.0,               # < 70%
            sub_tasks=[sub1, sub2],
        )
        await create_goal(test_db, goal)

    with step("POST /v1/scheduled/end-of-day"):
        resp = await async_client.post(
            "/v1/scheduled/end-of-day",
            json={"user_id": "u_eod2", "date": TODAY.isoformat()},
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()

    with step("Verify response action is replan_requested"):
        assert data["goals_processed"] == 1
        result = data["results"][0]
        assert result["action"] == "replan_requested", (
            f"Expected 'replan_requested', got {result['action']!r}"
        )

    with step("Verify replan_requested_at is set on goal in DB"):
        g = await get_goal(test_db, "g_eod2")
        assert g.replan_requested_at is not None, "replan_requested_at must be set"

    with step("Verify goal status set to OVERDUE"):
        assert g.status == "OVERDUE"

    with step("Verify subtask planned_date NOT changed (no carryover for replan goals)"):
        for t in g.sub_tasks:
            assert t.planned_date == TODAY, (
                f"Replan path should not advance planned_date; got {t.planned_date}"
            )


@pytest.mark.scenario("EOD3")
@pytest.mark.category("end_of_day")
async def test_EOD3_no_action_when_all_tasks_completed(async_client, test_db):
    """Goal with all tasks completed today → not included in results."""
    with step("Seed goal where all subtasks are already completed"):
        sub = make_subtask("t_eod3", goal_id="g_eod3", is_completed=True, planned_date=TODAY)
        goal = make_goal(
            goal_id="g_eod3", user_id="u_eod3", status="IN_PROGRESS",
            deadline=TODAY + timedelta(days=7),
            sub_tasks=[sub],
        )
        await create_goal(test_db, goal)

    with step("POST /v1/scheduled/end-of-day"):
        resp = await async_client.post(
            "/v1/scheduled/end-of-day",
            json={"user_id": "u_eod3", "date": TODAY.isoformat()},
        )
        assert resp.status_code == 200
        data = resp.json()

    with step("Verify no goals processed (no incomplete tasks)"):
        assert data["goals_processed"] == 0
        assert data["results"] == []


@pytest.mark.scenario("EOD4")
@pytest.mark.category("end_of_day")
async def test_EOD4_abandoned_subtasks_not_counted_as_incomplete(async_client, test_db):
    """Abandoned subtasks planned for today are ignored — not treated as incomplete."""
    with step("Seed goal with one abandoned subtask and one completed subtask for today"):
        sub_abandoned = make_subtask(
            "t_eod4a", goal_id="g_eod4",
            is_completed=False, abandoned=True, planned_date=TODAY,
        )
        sub_done = make_subtask(
            "t_eod4b", goal_id="g_eod4",
            is_completed=True, planned_date=TODAY,
        )
        goal = make_goal(
            goal_id="g_eod4", user_id="u_eod4", status="IN_PROGRESS",
            deadline=TODAY + timedelta(days=7),
            sub_tasks=[sub_abandoned, sub_done],
        )
        await create_goal(test_db, goal)

    with step("POST /v1/scheduled/end-of-day"):
        resp = await async_client.post(
            "/v1/scheduled/end-of-day",
            json={"user_id": "u_eod4", "date": TODAY.isoformat()},
        )
        assert resp.status_code == 200
        data = resp.json()

    with step("Verify no action taken (abandoned task not counted as incomplete)"):
        assert data["goals_processed"] == 0, (
            f"Abandoned tasks must not count as incomplete. results: {data['results']}"
        )
