"""Integration tests for daily output — schema compliance (no planned_date in GoalSubTask)."""

import pytest
from datetime import date, datetime, timezone

pytest.importorskip("mongomock_motor")

from mongomock_motor import AsyncMongoMockClient

from app.schemas.output import GoalSubTask, GoalsOutput
from app.tools.goal_db import create_goal
from app.schemas.domain import Goal, SubTask


@pytest.fixture
def mongo_db():
    client = AsyncMongoMockClient()
    return client["test_goal_tracking"]


@pytest.fixture
def goal_with_planned_dates():
    """A Goal whose sub-tasks have planned_date set (as if Schedule Agent has scheduled them)."""
    sub_tasks = [
        SubTask(
            sub_task_id="st1",
            goal_id="g020",
            title="Write executive summary",
            estimated_minutes=60,
            priority="high",
            deadline=date(2026, 5, 29),
            preferred_time_of_day="morning",
            can_split=False,
            is_completed=False,
            planned_date=date(2026, 5, 28),  # planned_date is set on SubTask
        ),
        SubTask(
            sub_task_id="st2",
            goal_id="g020",
            title="Write methodology section",
            estimated_minutes=90,
            priority="medium",
            deadline=date(2026, 5, 30),
            preferred_time_of_day="afternoon",
            can_split=True,
            is_completed=False,
            planned_date=date(2026, 5, 29),
        ),
    ]
    return Goal(
        goal_id="g020",
        user_id="u010",
        title="Complete project proposal",
        goal_type="weekly",
        status="IN_PROGRESS",
        created_at=datetime.now(timezone.utc),
        deadline=date(2026, 5, 30),
        progress_percent=0.0,
        sub_tasks=sub_tasks,
        feasibility_score=0.8,
        feasibility_note="",
        total_effort_minutes=150,
        suggested_blocks_count=2,
        suggested_split_ratio=[0.5, 0.5],
    )


@pytest.mark.asyncio
async def test_goalsoutput_daily_sub_tasks_never_contain_planned_date(goal_with_planned_dates):
    """GoalSubTask objects in GoalsOutput must not expose planned_date."""
    goal = goal_with_planned_dates

    today = date.today()
    days_to = (goal.deadline - today).days
    urgency = "high" if days_to <= 0 else ("medium" if days_to <= 3 else "low")

    daily_sub_tasks = []
    for st in goal.sub_tasks:
        if st.is_completed:
            continue
        # This is the critical test: strip planned_date before constructing GoalSubTask
        sub_task_data = {
            "title": st.title,
            "estimated_minutes": st.estimated_minutes,
            "priority": st.priority,
            "deadline": st.deadline,
            "preferred_time_of_day": st.preferred_time_of_day,
            "can_split": st.can_split,
        }
        sub_task = GoalSubTask(**sub_task_data)
        daily_sub_tasks.append(sub_task)

    output = GoalsOutput(
        goal_id=goal.goal_id,
        urgency=urgency,
        feasibility_score=goal.feasibility_score,
        feasibility_note=goal.feasibility_note,
        total_effort_minutes=goal.total_effort_minutes,
        suggested_blocks_count=goal.suggested_blocks_count,
        suggested_split_ratio=goal.suggested_split_ratio,
        daily_sub_tasks=daily_sub_tasks,
    )

    # Verify no planned_date in any GoalSubTask
    for sub_task in output.daily_sub_tasks:
        assert "planned_date" not in sub_task.model_fields
        assert not hasattr(sub_task, "planned_date") or sub_task.model_fields.get("planned_date") is None


@pytest.mark.asyncio
async def test_goalsoutput_with_planned_date_in_input_raises(goal_with_planned_dates):
    """Constructing GoalSubTask with planned_date in the dict must raise."""
    import pytest
    from pydantic import ValidationError

    with pytest.raises((ValidationError, ValueError)):
        GoalSubTask(
            title="Test",
            estimated_minutes=60,
            priority="high",
            deadline=date(2026, 5, 30),
            preferred_time_of_day="morning",
            can_split=False,
            planned_date=date(2026, 5, 28),  # must be rejected
        )


@pytest.mark.asyncio
async def test_goal_sub_task_fields_exact(goal_with_planned_dates):
    """GoalSubTask has exactly the 6 fields from PRD §5."""
    expected = {"title", "estimated_minutes", "priority", "deadline", "preferred_time_of_day", "can_split"}
    actual = set(GoalSubTask.model_fields.keys())
    assert actual == expected, f"Extra: {actual - expected}, Missing: {expected - actual}"


@pytest.mark.asyncio
async def test_subtask_in_domain_has_planned_date(goal_with_planned_dates):
    """SubTask (domain model) does have planned_date — it's only excluded from GoalSubTask."""
    goal = goal_with_planned_dates
    for st in goal.sub_tasks:
        assert "planned_date" in SubTask.model_fields
        assert st.planned_date is not None  # we set them in the fixture


@pytest.mark.asyncio
async def test_create_and_retrieve_goal(mongo_db, goal_with_planned_dates):
    """create_goal and get_goal round-trip preserves planned_date on sub-tasks."""
    from app.tools.goal_db import get_goal

    await create_goal(mongo_db, goal_with_planned_dates)
    retrieved = await get_goal(mongo_db, "g020")
    assert retrieved is not None
    assert retrieved.goal_id == "g020"
    # planned_date survives the round-trip on SubTask
    assert retrieved.sub_tasks[0].planned_date == date(2026, 5, 28)
