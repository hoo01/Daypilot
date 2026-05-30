"""Unit tests for app/tools/feasibility_calc.py"""

from datetime import date, datetime, timezone
import pytest

from app.schemas.domain import Goal, SubTask
from app.tools.feasibility_calc import (
    FeasibilityLayerResult,
    time_feasibility,
    habit_feasibility,
    load_feasibility,
    synthesize_feasibility,
)


def _make_goal(status: str = "IN_PROGRESS", effort: int = 300) -> Goal:
    return Goal(
        goal_id="g_test",
        user_id="u_test",
        title="Test Goal",
        goal_type="weekly",
        status=status,
        created_at=datetime.now(timezone.utc),
        deadline=date(2026, 6, 7),
        progress_percent=0.0,
        sub_tasks=[],
        feasibility_score=1.0,
        feasibility_note="",
        total_effort_minutes=effort,
        suggested_blocks_count=3,
        suggested_split_ratio=[0.4, 0.4, 0.2],
    )


class TestTimeFeasibility:
    def test_feasible_when_enough_time(self):
        result = time_feasibility(
            total_effort_minutes=120,
            remaining_days=5,
            free_minutes=300,
        )
        assert result.feasible is True
        assert result.layer == "time"
        assert result.degraded is False

    def test_infeasible_when_not_enough_time(self):
        result = time_feasibility(
            total_effort_minutes=400,
            remaining_days=3,
            free_minutes=200,
        )
        assert result.feasible is False
        assert result.available_minutes == 200

    def test_degraded_when_free_minutes_none(self):
        result = time_feasibility(
            total_effort_minutes=120,
            remaining_days=5,
            free_minutes=None,
        )
        assert result.feasible is True
        assert result.degraded is True
        assert result.note == "calendar_slots_empty"

    def test_exact_match_is_feasible(self):
        result = time_feasibility(120, 5, 120)
        assert result.feasible is True

    def test_note_populated_when_infeasible(self):
        result = time_feasibility(300, 3, 100)
        assert result.note != ""


class TestHabitFeasibility:
    def test_no_memory_uses_fallback_weekly(self):
        result = habit_feasibility(
            total_effort_minutes=300,
            memory_context="",
            goal_type="weekly",
            deadline_days=7,
        )
        assert result.overrun_ratio == pytest.approx(0.30)
        assert result.adjusted_effort_minutes == 390  # 300 * 1.3
        assert result.degraded is False
        assert "no_memory_baseline" in result.note

    def test_no_memory_uses_fallback_daily(self):
        result = habit_feasibility(60, "", "daily", 1)
        assert result.overrun_ratio == pytest.approx(0.05)

    def test_no_memory_uses_fallback_long_term(self):
        result = habit_feasibility(120, "", "long_term", 30)
        assert result.overrun_ratio == pytest.approx(0.10)

    def test_parses_overrun_from_memory_percent_slower(self):
        memory = "User typically completes coding goals 40% slower than estimated."
        result = habit_feasibility(200, memory, "weekly", 7)
        assert result.overrun_ratio == pytest.approx(0.40)
        assert result.adjusted_effort_minutes == 280  # 200 * 1.4

    def test_feasible_with_short_adjusted_effort(self):
        result = habit_feasibility(60, "", "daily", 14)
        assert result.feasible is True

    def test_degraded_is_always_false(self):
        result = habit_feasibility(100, "", "weekly", 5)
        assert result.degraded is False


class TestLoadFeasibility:
    def test_no_overload_when_under_threshold(self):
        active_goals = [_make_goal("IN_PROGRESS", 200), _make_goal("IN_PROGRESS", 100)]
        result = load_feasibility(active_goals, 100, overload_threshold_minutes=600)
        assert result.overload_flag is False
        assert result.feasible is True

    def test_overload_when_over_threshold(self):
        active_goals = [_make_goal("IN_PROGRESS", 400), _make_goal("IN_PROGRESS", 300)]
        result = load_feasibility(active_goals, 100, overload_threshold_minutes=600)
        assert result.overload_flag is True
        assert result.feasible is False

    def test_only_in_progress_goals_counted(self):
        goals = [
            _make_goal("IN_PROGRESS", 300),
            _make_goal("COMPLETED", 500),    # should not count
            _make_goal("ABANDONED", 500),    # should not count
        ]
        result = load_feasibility(goals, 200, overload_threshold_minutes=600)
        # 300 (in_progress) + 200 (new) = 500 < 600 → not overloaded
        assert result.overload_flag is False

    def test_empty_active_goals(self):
        result = load_feasibility([], 100, 600)
        assert result.overload_flag is False

    def test_threshold_exact_boundary(self):
        result = load_feasibility([], 600, 600)
        assert result.overload_flag is False  # not strictly greater

    def test_layer_label_is_load(self):
        result = load_feasibility([], 100, 600)
        assert result.layer == "load"


class TestSynthesizeFeasibility:
    def _make_result(self, layer, feasible, degraded=False, overload=None):
        return FeasibilityLayerResult(
            layer=layer,
            feasible=feasible,
            overload_flag=overload,
            degraded=degraded,
        )

    def test_perfect_score_when_all_pass(self):
        t = self._make_result("time", True)
        h = self._make_result("habit", True)
        l = self._make_result("load", True, overload=False)
        score, note = synthesize_feasibility(t, h, l)
        assert score == pytest.approx(1.0)
        assert note == ""

    def test_subtract_0_3_when_time_infeasible(self):
        t = self._make_result("time", False)
        h = self._make_result("habit", True)
        l = self._make_result("load", True, overload=False)
        score, _ = synthesize_feasibility(t, h, l)
        assert score == pytest.approx(0.7)

    def test_subtract_0_2_when_habit_infeasible(self):
        t = self._make_result("time", True)
        h = self._make_result("habit", False)
        l = self._make_result("load", True, overload=False)
        score, _ = synthesize_feasibility(t, h, l)
        assert score == pytest.approx(0.8)

    def test_subtract_0_15_when_overload(self):
        t = self._make_result("time", True)
        h = self._make_result("habit", True)
        l = self._make_result("load", False, overload=True)
        score, _ = synthesize_feasibility(t, h, l)
        assert score == pytest.approx(0.85)

    def test_all_fail_gives_low_score(self):
        t = self._make_result("time", False)
        h = self._make_result("habit", False)
        l = self._make_result("load", False, overload=True)
        score, _ = synthesize_feasibility(t, h, l)
        assert score == pytest.approx(1.0 - 0.3 - 0.2 - 0.15)

    def test_degraded_caps_score_at_0_7(self):
        t = self._make_result("time", True, degraded=True)
        h = self._make_result("habit", True)
        l = self._make_result("load", True, overload=False)
        score, note = synthesize_feasibility(t, h, l)
        assert score <= 0.7
        assert "capped at 0.7" in note

    def test_score_never_below_zero(self):
        t = self._make_result("time", False)
        h = self._make_result("habit", False)
        l = self._make_result("load", False, overload=True)
        score, _ = synthesize_feasibility(t, h, l)
        assert score >= 0.0

    def test_score_clamped_to_one(self):
        t = self._make_result("time", True)
        h = self._make_result("habit", True)
        l = self._make_result("load", True, overload=False)
        score, _ = synthesize_feasibility(t, h, l)
        assert score <= 1.0

    def test_note_populated_when_score_below_threshold(self):
        t = self._make_result("time", False, degraded=False)
        h = self._make_result("habit", False)
        l = self._make_result("load", True, overload=False)
        score, note = synthesize_feasibility(t, h, l)
        assert score < 0.7
        assert note != ""
