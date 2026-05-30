"""Unit tests for app/tools/progress_calc.py"""

from datetime import date
import pytest

from app.schemas.domain import SubTask
from app.tools.progress_calc import compute_progress_percent


def _make_task(sub_task_id: str, is_completed: bool) -> SubTask:
    return SubTask(
        sub_task_id=sub_task_id,
        goal_id="g001",
        title=f"Task {sub_task_id}",
        estimated_minutes=30,
        priority="medium",
        deadline=date(2026, 6, 1),
        preferred_time_of_day="flexible",
        can_split=True,
        is_completed=is_completed,
    )


class TestComputeProgressPercent:
    def test_empty_list_returns_zero(self):
        assert compute_progress_percent([]) == 0.0

    def test_all_incomplete(self):
        tasks = [_make_task(f"t{i}", False) for i in range(4)]
        assert compute_progress_percent(tasks) == 0.0

    def test_all_complete(self):
        tasks = [_make_task(f"t{i}", True) for i in range(4)]
        assert compute_progress_percent(tasks) == 100.0

    def test_half_complete(self):
        tasks = [_make_task(f"t{i}", i < 5) for i in range(10)]
        assert compute_progress_percent(tasks) == 50.0

    def test_one_of_three(self):
        tasks = [
            _make_task("t1", True),
            _make_task("t2", False),
            _make_task("t3", False),
        ]
        assert compute_progress_percent(tasks) == pytest.approx(33.33, abs=0.01)

    def test_result_is_rounded_to_two_decimals(self):
        tasks = [_make_task(f"t{i}", i == 0) for i in range(3)]
        result = compute_progress_percent(tasks)
        assert result == round(result, 2)

    def test_single_completed_task(self):
        tasks = [_make_task("t1", True)]
        assert compute_progress_percent(tasks) == 100.0

    def test_single_incomplete_task(self):
        tasks = [_make_task("t1", False)]
        assert compute_progress_percent(tasks) == 0.0
