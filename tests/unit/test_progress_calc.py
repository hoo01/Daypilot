"""Unit tests for progress_calc functions."""
import pytest
from datetime import datetime, timedelta, timezone
from agents.tools.progress_calc import compute_progress_percent, compute_daily_rate
from agents.tools.goal_db import create_goal
from tests.fixtures.domain.factories import make_subtask, make_goal


class TestComputeProgressPercent:
    def test_returns_zero_for_empty_list(self):
        assert compute_progress_percent([]) == 0.0

    def test_zero_percent_when_none_completed(self):
        tasks = [make_subtask("t1", is_completed=False), make_subtask("t2", is_completed=False)]
        assert compute_progress_percent(tasks) == 0.0

    def test_hundred_percent_when_all_completed(self):
        tasks = [make_subtask("t1", is_completed=True), make_subtask("t2", is_completed=True)]
        assert compute_progress_percent(tasks) == 100.0

    def test_partial_completion(self):
        tasks = [
            make_subtask("t1", is_completed=True),
            make_subtask("t2", is_completed=False),
            make_subtask("t3", is_completed=False),
        ]
        result = compute_progress_percent(tasks)
        assert result == pytest.approx(33.33, abs=0.01), (
            f"1 of 3 completed should be ~33.33%, got {result}"
        )

    def test_two_thirds_completion(self):
        tasks = [
            make_subtask("t1", is_completed=True),
            make_subtask("t2", is_completed=True),
            make_subtask("t3", is_completed=False),
        ]
        result = compute_progress_percent(tasks)
        assert result == pytest.approx(66.67, abs=0.01)

    def test_single_task_completed(self):
        tasks = [make_subtask("t1", is_completed=True)]
        assert compute_progress_percent(tasks) == 100.0

    def test_single_task_not_completed(self):
        tasks = [make_subtask("t1", is_completed=False)]
        assert compute_progress_percent(tasks) == 0.0

    def test_returns_float(self):
        tasks = [make_subtask("t1", is_completed=True)]
        result = compute_progress_percent(tasks)
        assert isinstance(result, float)

    def test_result_rounds_to_two_decimal_places(self):
        tasks = [make_subtask(f"t{i}", is_completed=(i == 0)) for i in range(3)]
        result = compute_progress_percent(tasks)
        assert result == round(result, 2)


class TestComputeProgressPercentWithAbandoned:
    """Abandoned subtasks must be excluded from both numerator and denominator."""

    def test_all_abandoned_returns_zero(self):
        tasks = [
            make_subtask("t1", is_completed=False, abandoned=True),
            make_subtask("t2", is_completed=False, abandoned=True),
        ]
        assert compute_progress_percent(tasks) == 0.0

    def test_abandoned_not_counted_as_completed(self):
        tasks = [
            make_subtask("t1", is_completed=True),
            make_subtask("t2", is_completed=False, abandoned=True),
        ]
        # Only t1 is active; t1 is completed → 100%
        assert compute_progress_percent(tasks) == 100.0

    def test_abandoned_excluded_from_denominator(self):
        tasks = [
            make_subtask("t1", is_completed=True),
            make_subtask("t2", is_completed=False),
            make_subtask("t3", is_completed=False, abandoned=True),
        ]
        # Active: t1, t2. Completed: t1. → 50%
        assert compute_progress_percent(tasks) == 50.0

    def test_mix_of_completed_incomplete_and_abandoned(self):
        tasks = [
            make_subtask("t1", is_completed=True),
            make_subtask("t2", is_completed=True),
            make_subtask("t3", is_completed=False),
            make_subtask("t4", is_completed=False, abandoned=True),
            make_subtask("t5", is_completed=False, abandoned=True),
        ]
        # Active: t1, t2, t3. Completed: t1, t2. → 66.67%
        result = compute_progress_percent(tasks)
        assert result == pytest.approx(66.67, abs=0.01)

    def test_abandoned_completed_task_still_excluded(self):
        # A subtask that is both is_completed and abandoned should still be excluded
        tasks = [
            make_subtask("t1", is_completed=True, abandoned=True),
            make_subtask("t2", is_completed=False),
        ]
        # Active: t2 only. Completed: 0. → 0%
        assert compute_progress_percent(tasks) == 0.0


class TestComputeDailyRate:
    """compute_daily_rate requires a real DB — uses test_db fixture."""

    async def test_returns_zero_when_goal_not_found(self, test_db):
        rate = await compute_daily_rate(test_db, "nonexistent_goal")
        assert rate == 0.0

    async def test_returns_zero_when_no_completions(self, test_db):
        goal = make_goal(goal_id="g_rate_0", user_id="u_rate",
                         sub_tasks=[make_subtask("t1", goal_id="g_rate_0", is_completed=False)])
        await create_goal(test_db, goal)
        rate = await compute_daily_rate(test_db, "g_rate_0")
        assert rate == 0.0

    async def test_counts_recent_completions(self, test_db):
        now = datetime.now(timezone.utc)
        sub = make_subtask(
            "t1", goal_id="g_rate_1",
            estimated_minutes=60,
            is_completed=True,
            completed_at=now - timedelta(hours=2),  # completed today
        )
        goal = make_goal(goal_id="g_rate_1", user_id="u_rate", sub_tasks=[sub])
        await create_goal(test_db, goal)

        rate = await compute_daily_rate(test_db, "g_rate_1", window_days=7)
        # 60 minutes completed in window of max(min(0_days_created, 7), 1) = 1 day → 60 min/day
        assert rate == pytest.approx(60.0, abs=1.0)

    async def test_excludes_abandoned_from_rate(self, test_db):
        now = datetime.now(timezone.utc)
        tasks = [
            make_subtask("t1", goal_id="g_rate_2", estimated_minutes=60,
                         is_completed=True, completed_at=now - timedelta(hours=1)),
            make_subtask("t2", goal_id="g_rate_2", estimated_minutes=30,
                         is_completed=True, abandoned=True, completed_at=now - timedelta(hours=1)),
        ]
        goal = make_goal(goal_id="g_rate_2", user_id="u_rate", sub_tasks=tasks)
        await create_goal(test_db, goal)

        rate = await compute_daily_rate(test_db, "g_rate_2", window_days=7)
        # Only t1 (60 min) counts; t2 is abandoned
        assert rate == pytest.approx(60.0, abs=1.0)

    async def test_excludes_completions_outside_window(self, test_db):
        now = datetime.now(timezone.utc)
        tasks = [
            make_subtask("t1", goal_id="g_rate_3", estimated_minutes=60,
                         is_completed=True, completed_at=now - timedelta(days=10)),
        ]
        goal = make_goal(goal_id="g_rate_3", user_id="u_rate", sub_tasks=tasks)
        await create_goal(test_db, goal)

        rate = await compute_daily_rate(test_db, "g_rate_3", window_days=7)
        # Completion is outside the 7-day window → 0
        assert rate == 0.0
