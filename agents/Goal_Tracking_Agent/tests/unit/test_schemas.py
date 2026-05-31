"""Schema contract tests: field names match PRD §5 and §8; GoalSubTask has no planned_date."""

import inspect
from datetime import date, datetime, timezone
import pytest
from pydantic import ValidationError

from app.schemas.output import GoalSubTask, GoalsOutput
from app.schemas.domain import Goal, SubTask
from app.schemas.events import OverdueNotification, OverdueTaskRef, EventAck
from app.schemas.input import GoalAgentInput, HealthOutput


# ── PRD §5 output schema checks ───────────────────────────────────────────────

class TestGoalSubTaskSchema:
    """GoalSubTask must match PRD §5 exactly and NEVER include planned_date."""

    EXPECTED_FIELDS = {"title", "estimated_minutes", "priority", "deadline", "preferred_time_of_day", "can_split"}

    def test_fields_match_prd_section_5(self):
        actual = set(GoalSubTask.model_fields.keys())
        assert actual == self.EXPECTED_FIELDS, (
            f"GoalSubTask fields don't match PRD §5.\n"
            f"  Extra:   {actual - self.EXPECTED_FIELDS}\n"
            f"  Missing: {self.EXPECTED_FIELDS - actual}"
        )

    def test_planned_date_field_absent(self):
        assert "planned_date" not in GoalSubTask.model_fields, (
            "GoalSubTask must NOT have a planned_date field (Architecture invariant)"
        )

    def test_planned_date_rejected_at_construction(self):
        with pytest.raises((ValidationError, ValueError)):
            GoalSubTask(
                title="Test",
                estimated_minutes=30,
                priority="medium",
                deadline=date(2026, 6, 1),
                preferred_time_of_day="flexible",
                can_split=True,
                planned_date=date(2026, 5, 28),  # must be rejected
            )

    def test_valid_construction(self):
        st = GoalSubTask(
            title="Solve problem 1",
            estimated_minutes=45,
            priority="high",
            deadline=date(2026, 5, 30),
            preferred_time_of_day="morning",
            can_split=False,
        )
        assert st.title == "Solve problem 1"
        assert st.estimated_minutes == 45
        assert not hasattr(st, "planned_date") or "planned_date" not in st.model_fields

    def test_priority_values(self):
        for priority in ("high", "medium", "low"):
            st = GoalSubTask(
                title="T",
                estimated_minutes=30,
                priority=priority,
                deadline=date(2026, 6, 1),
                preferred_time_of_day="flexible",
                can_split=True,
            )
            assert st.priority == priority

    def test_preferred_time_of_day_values(self):
        for tod in ("morning", "afternoon", "night", "flexible"):
            st = GoalSubTask(
                title="T",
                estimated_minutes=30,
                priority="low",
                deadline=date(2026, 6, 1),
                preferred_time_of_day=tod,
                can_split=True,
            )
            assert st.preferred_time_of_day == tod


class TestGoalsOutputSchema:
    """GoalsOutput must match PRD §5 exactly."""

    EXPECTED_FIELDS = {
        "goal_id", "urgency", "feasibility_score", "feasibility_note",
        "total_effort_minutes", "suggested_blocks_count", "suggested_split_ratio",
        "daily_sub_tasks",
    }

    def test_fields_match_prd_section_5(self):
        actual = set(GoalsOutput.model_fields.keys())
        assert actual == self.EXPECTED_FIELDS

    def test_valid_construction(self):
        out = GoalsOutput(
            goal_id="g001",
            urgency="high",
            feasibility_score=0.85,
            feasibility_note="",
            total_effort_minutes=120,
            suggested_blocks_count=2,
            suggested_split_ratio=[0.5, 0.5],
            daily_sub_tasks=[],
        )
        assert out.goal_id == "g001"


# ── PRD §8 domain schema checks ───────────────────────────────────────────────

class TestGoalSchema:
    """Goal must match PRD §8 exactly."""

    EXPECTED_FIELDS = {
        "goal_id", "user_id", "title", "goal_type", "status", "created_at",
        "deadline", "progress_percent", "sub_tasks", "feasibility_score",
        "feasibility_note", "total_effort_minutes", "suggested_blocks_count",
        "suggested_split_ratio",
    }

    def test_fields_match_prd_section_8(self):
        actual = set(Goal.model_fields.keys())
        assert actual == self.EXPECTED_FIELDS, (
            f"Goal fields don't match PRD §8.\n"
            f"  Extra:   {actual - self.EXPECTED_FIELDS}\n"
            f"  Missing: {self.EXPECTED_FIELDS - actual}"
        )


class TestSubTaskSchema:
    """SubTask must match PRD §8 exactly (including planned_date which IS valid here)."""

    EXPECTED_FIELDS = {
        "sub_task_id", "goal_id", "title", "estimated_minutes", "priority",
        "deadline", "preferred_time_of_day", "can_split", "is_completed",
        "completed_at", "planned_date",
    }

    def test_fields_match_prd_section_8(self):
        actual = set(SubTask.model_fields.keys())
        assert actual == self.EXPECTED_FIELDS, (
            f"SubTask fields don't match PRD §8.\n"
            f"  Extra:   {actual - self.EXPECTED_FIELDS}\n"
            f"  Missing: {self.EXPECTED_FIELDS - actual}"
        )

    def test_planned_date_is_optional(self):
        st = SubTask(
            sub_task_id="t1",
            goal_id="g001",
            title="Task",
            estimated_minutes=30,
            priority="medium",
            deadline=date(2026, 6, 1),
            preferred_time_of_day="flexible",
            can_split=True,
            is_completed=False,
        )
        assert st.planned_date is None

    def test_planned_date_can_be_set(self):
        st = SubTask(
            sub_task_id="t1",
            goal_id="g001",
            title="Task",
            estimated_minutes=30,
            priority="medium",
            deadline=date(2026, 6, 1),
            preferred_time_of_day="flexible",
            can_split=True,
            is_completed=False,
            planned_date=date(2026, 5, 28),
        )
        assert st.planned_date == date(2026, 5, 28)


# ── PRD §4.5/§7 event schema checks ──────────────────────────────────────────

class TestOverdueNotificationSchema:
    """OverdueNotification uses scheduled_date (day-level) not per-window start_time."""

    def test_overdue_task_ref_uses_scheduled_date(self):
        assert "scheduled_date" in OverdueTaskRef.model_fields
        assert "planned_date" not in OverdueTaskRef.model_fields
        assert "start_time" not in OverdueTaskRef.model_fields

    def test_overdue_notification_valid(self):
        notif = OverdueNotification(
            event_id="evt_001",
            overdue_tasks=[
                OverdueTaskRef(
                    sub_task_id="t2",
                    goal_id="g001",
                    scheduled_date=date(2026, 5, 27),
                )
            ],
        )
        assert notif.event_id == "evt_001"
        assert notif.overdue_tasks[0].scheduled_date == date(2026, 5, 27)


# ── PRD §6 input schema checks ────────────────────────────────────────────────

class TestGoalAgentInputSchema:
    """GoalAgentInput must match PRD §6 exactly."""

    EXPECTED_FIELDS = {
        "user_id", "intent", "raw_user_message", "health",
        "memory_context", "calendar_free_slots",
    }

    def test_fields_match_prd_section_6(self):
        actual = set(GoalAgentInput.model_fields.keys())
        assert actual == self.EXPECTED_FIELDS
