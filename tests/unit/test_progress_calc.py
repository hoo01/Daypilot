"""Unit tests for progress_calc pure function."""
import pytest
from agents.tools.progress_calc import compute_progress_percent
from tests.fixtures.domain.factories import make_subtask


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
