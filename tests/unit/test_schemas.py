"""Unit tests for goal-related schema contracts."""
import pytest
from pydantic import ValidationError

from schemas.goals import GoalSubTask, GoalsOutput
from schemas.goal_domain import Goal, SubTask, VALID_GOAL_STATUSES
from schemas.goal_events import OverdueTaskRef, EventAck


class TestGoalSubTaskContract:
    """Invariant I1: GoalSubTask must never carry planned_date."""

    def test_planned_date_field_absent_from_model(self):
        fields = GoalSubTask.model_fields
        assert "planned_date" not in fields, (
            "GoalSubTask must not have a planned_date field — it belongs only on SubTask (domain)"
        )

    def test_goalsub_task_exact_fields(self):
        expected = {"title", "estimated_minutes", "priority", "deadline", "preferred_time_of_day", "can_split"}
        actual = set(GoalSubTask.model_fields.keys())
        assert actual == expected, (
            f"GoalSubTask field mismatch. Expected: {expected}. Actual: {actual}"
        )

    def test_goalsub_task_valid_construction(self):
        from datetime import date
        task = GoalSubTask(
            title="Write chapter outline",
            estimated_minutes=45,
            priority="high",
            deadline=date(2026, 6, 10),
            preferred_time_of_day="morning",
            can_split=False,
        )
        assert task.title == "Write chapter outline"
        assert not hasattr(task, "planned_date")

    def test_goalsub_task_rejects_planned_date_kwarg(self):
        from datetime import date
        with pytest.raises((ValidationError, TypeError)):
            GoalSubTask(
                title="Task",
                estimated_minutes=30,
                priority="medium",
                deadline=date(2026, 6, 10),
                preferred_time_of_day="flexible",
                can_split=True,
                planned_date=date(2026, 6, 5),  # must be rejected
            )


class TestGoalsOutputContract:
    def test_goals_output_has_daily_sub_tasks(self):
        from datetime import date
        output = GoalsOutput(
            goal_id="g1",
            urgency="medium",
            feasibility_score=0.8,
            feasibility_note="",
            total_effort_minutes=120,
            suggested_blocks_count=2,
            suggested_split_ratio=[0.5, 0.5],
            daily_sub_tasks=[],
        )
        assert output.goal_id == "g1"
        assert output.daily_sub_tasks == []


class TestOverdueTaskRefContract:
    """Invariant I2: OverdueTaskRef uses start_time, not planned_date."""

    def test_start_time_field_present(self):
        fields = OverdueTaskRef.model_fields
        assert "start_time" in fields, "OverdueTaskRef must have start_time (not planned_date)"

    def test_planned_date_field_absent(self):
        fields = OverdueTaskRef.model_fields
        assert "planned_date" not in fields, (
            "OverdueTaskRef must not have planned_date — PRD §11 Q3 resolved this to start_time"
        )


class TestValidGoalStatuses:
    def test_all_lifecycle_states_present(self):
        expected = {"CREATED", "IN_PROGRESS", "COMPLETED", "PARTIALLY_COMPLETED", "OVERDUE", "ABANDONED"}
        assert VALID_GOAL_STATUSES == expected

    def test_terminal_states_included(self):
        assert "COMPLETED" in VALID_GOAL_STATUSES
        assert "ABANDONED" in VALID_GOAL_STATUSES
