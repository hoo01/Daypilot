"""Unit tests for feasibility_calc pure functions. Invariant I3: weights are fixed."""
import pytest
from agents.tools.feasibility_calc import (
    FeasibilityLayerResult,
    time_feasibility,
    habit_feasibility,
    load_feasibility,
    synthesize_feasibility,
)
from tests.fixtures.domain.factories import make_goal


class TestTimeFeasibility:
    def test_feasible_when_free_minutes_exceeds_effort(self):
        result = time_feasibility(total_effort_minutes=120, remaining_days=3, free_minutes=200)
        assert result.feasible is True
        assert result.degraded is False
        assert result.layer == "time"

    def test_infeasible_when_insufficient_free_time(self):
        result = time_feasibility(total_effort_minutes=300, remaining_days=2, free_minutes=100)
        assert result.feasible is False
        assert result.degraded is False

    def test_degraded_when_free_minutes_none(self):
        result = time_feasibility(total_effort_minutes=120, remaining_days=3, free_minutes=None)
        assert result.degraded is True
        assert result.feasible is True  # cannot assess — assume feasible


class TestHabitFeasibility:
    def test_fallback_for_empty_memory_context(self):
        result = habit_feasibility(
            total_effort_minutes=120,
            memory_context="",
            goal_type="weekly",
            deadline_days=7,
        )
        assert result.degraded is False, "Empty memory should use fallback, not degrade"
        assert "no_memory_baseline" in result.note

    def test_fallback_overrun_ratio_weekly(self):
        result = habit_feasibility(120, "", "weekly", 7)
        assert result.overrun_ratio == pytest.approx(0.30, abs=0.01)

    def test_fallback_overrun_ratio_long_term(self):
        result = habit_feasibility(120, "", "long_term", 30)
        assert result.overrun_ratio == pytest.approx(0.10, abs=0.01)

    def test_fallback_overrun_ratio_daily(self):
        result = habit_feasibility(60, "", "daily", 1)
        assert result.overrun_ratio == pytest.approx(0.05, abs=0.01)

    def test_parses_overrun_from_memory_context(self):
        memory = "User typically completes weekly coding goals 25% slower than estimated."
        result = habit_feasibility(120, memory, "weekly", 7)
        assert result.overrun_ratio == pytest.approx(0.25, abs=0.01)


class TestLoadFeasibility:
    def test_no_overload_with_empty_active_goals(self):
        result = load_feasibility(active_goals=[], new_effort_minutes=300, overload_threshold_minutes=600)
        assert result.overload_flag is False
        assert result.feasible is True

    def test_overload_when_total_exceeds_threshold(self):
        active = [make_goal(status="IN_PROGRESS", total_effort_minutes=400)]
        result = load_feasibility(active, new_effort_minutes=300, overload_threshold_minutes=600)
        assert result.overload_flag is True
        assert result.feasible is False

    def test_only_counts_in_progress_goals(self):
        goals = [
            make_goal(goal_id="g1", status="IN_PROGRESS", total_effort_minutes=300),
            make_goal(goal_id="g2", status="COMPLETED", total_effort_minutes=9999),
        ]
        result = load_feasibility(goals, new_effort_minutes=100, overload_threshold_minutes=600)
        assert result.overload_flag is False, "COMPLETED goals must not be counted in load check"


class TestSynthesizeFeasibility:
    """Invariant I3: scoring weights are fixed and must not change."""

    def _make_ok(self, layer: str) -> FeasibilityLayerResult:
        return FeasibilityLayerResult(layer=layer, feasible=True, overload_flag=False, degraded=False)

    def _make_fail(self, layer: str) -> FeasibilityLayerResult:
        return FeasibilityLayerResult(layer=layer, feasible=False, overload_flag=True, degraded=False)

    def test_score_1_0_when_all_layers_pass(self):
        score, _ = synthesize_feasibility(
            self._make_ok("time"), self._make_ok("habit"), self._make_ok("load")
        )
        assert score == pytest.approx(1.0)

    def test_time_infeasible_deducts_0_3(self):
        time_fail = FeasibilityLayerResult("time", feasible=False, overload_flag=False, degraded=False)
        score, _ = synthesize_feasibility(time_fail, self._make_ok("habit"), self._make_ok("load"))
        assert score == pytest.approx(0.7, abs=0.01)

    def test_habit_infeasible_deducts_0_2(self):
        habit_fail = FeasibilityLayerResult("habit", feasible=False, overload_flag=False, degraded=False)
        score, _ = synthesize_feasibility(self._make_ok("time"), habit_fail, self._make_ok("load"))
        assert score == pytest.approx(0.8, abs=0.01)

    def test_load_overloaded_deducts_0_15(self):
        load_over = FeasibilityLayerResult("load", feasible=False, overload_flag=True, degraded=False)
        score, _ = synthesize_feasibility(self._make_ok("time"), self._make_ok("habit"), load_over)
        assert score == pytest.approx(0.85, abs=0.01)

    def test_degraded_caps_score_at_0_7(self):
        time_deg = FeasibilityLayerResult("time", feasible=True, overload_flag=False, degraded=True)
        score, note = synthesize_feasibility(time_deg, self._make_ok("habit"), self._make_ok("load"))
        assert score <= 0.7, f"Degraded result must be capped at 0.7, got {score}"
        assert "0.7" in note or "capped" in note

    def test_all_fail_never_negative(self):
        time_fail = FeasibilityLayerResult("time", feasible=False, overload_flag=False, degraded=False)
        habit_fail = FeasibilityLayerResult("habit", feasible=False, overload_flag=False, degraded=False)
        load_over = FeasibilityLayerResult("load", feasible=False, overload_flag=True, degraded=False)
        score, _ = synthesize_feasibility(time_fail, habit_fail, load_over)
        assert score >= 0.0, "Score must never be negative"

    def test_score_rounds_to_2_decimal_places(self):
        time_fail = FeasibilityLayerResult("time", feasible=False, overload_flag=False, degraded=False)
        score, _ = synthesize_feasibility(time_fail, self._make_ok("habit"), self._make_ok("load"))
        assert score == round(score, 2), "Score must be rounded to 2 decimal places"
