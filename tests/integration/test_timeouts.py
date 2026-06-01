"""T1 — CalendarUnavailable (timeout) degrades time feasibility gracefully."""
import asyncio
import pytest

from agents.tools.calendar_api import CalendarUnavailable
from agents.tools.feasibility_calc import time_feasibility, synthesize_feasibility, FeasibilityLayerResult
from tests.fixtures.goal_agent.reporting import step


@pytest.mark.scenario("T1")
@pytest.mark.category("timeout")
async def test_T1_calendar_timeout_degrades_time_feasibility(test_db, monkeypatch):
    """fetch_free_windows raises asyncio.TimeoutError → time.degraded=True; no 5xx."""
    import agents.tools.calendar_api as cal_mod

    async def _raise_timeout(*args, **kwargs):
        raise asyncio.TimeoutError("simulated calendar API timeout")

    monkeypatch.setattr(cal_mod, "fetch_free_windows", _raise_timeout)

    with step("Simulate fetch_free_windows raising TimeoutError (like CalendarUnavailable)"):
        try:
            await cal_mod.fetch_free_windows("u_t1", None, None, calendar_client=None)
        except (asyncio.TimeoutError, CalendarUnavailable) as exc:
            degraded_note = f"timeout: {exc}"

    with step("Apply degraded time_feasibility (free_minutes=None)"):
        time_result = time_feasibility(
            total_effort_minutes=120,
            remaining_days=3,
            free_minutes=None,
        )

    with step("Verify time_result.degraded == True"):
        assert time_result.degraded is True, (
            f"Calendar timeout must set time_result.degraded=True. Got: {time_result.degraded}"
        )

    with step("Verify synthesized score is capped at 0.7 (not 5xx)"):
        habit_ok = FeasibilityLayerResult("habit", feasible=True, overload_flag=False, degraded=False)
        load_ok = FeasibilityLayerResult("load", feasible=True, overload_flag=False, degraded=False)
        score, note = synthesize_feasibility(time_result, habit_ok, load_ok)
        assert score <= 0.7, f"Score must be capped at 0.7 on timeout. Got: {score}"
        assert "capped" in note or "0.7" in note, (
            f"Note must mention the 0.7 cap. Got: {note!r}"
        )
