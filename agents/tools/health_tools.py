"""
Health tool — Owner: Vatsal

analyze_health() runs the PsychoBio pipeline and returns a dict matching
the HealthOutput schema (energy_level, focus_window, cognitive_load_score,
avoid_tasks) plus enriched fields for the coordinator prompt.

Pattern: same as relationship_tools.py — reads MongoDB, runs pipeline,
returns a plain dict.
"""

import time

from db import get_db
from agents.memory import MemoryAgent
from agents.health_agent.agents.graph_orchestrator import run_pipeline
from agents.health_agent.scenario_selector import (
    get_active_scenario,
    get_run_dir,
    get_target_date,
)
from agents.health_agent.schemas import HealthPipelineOutput
from opentelemetry import trace
from telemetry import tracer, meter, get_logger

_logger = get_logger("health_tools")
_cache: dict[str, tuple[float, dict]] = {}
_CACHE_TTL = 600  # 10 minutes — pipeline result is static per scenario+date

_health_duration = meter.create_histogram("health.analyze.duration", unit="ms", description="Health analysis total duration")
_health_cache_hits = meter.create_counter("health.cache.hits", description="Health cache hit count")
_health_pipeline_errors = meter.create_counter("health.pipeline.errors", description="Health pipeline errors")


async def analyze_health(user_id: str) -> dict:
    """
    Analyze the user's psychobiological state via the PsychoBio pipeline.
    Returns energy level, optimal focus window, cognitive load score,
    and tasks to avoid — matching HealthOutput schema.
    """
    # Fetch user's preferred focus window from MongoDB (falls back gracefully)
    try:
        mem = MemoryAgent(get_db())
        prefs = await mem.get_preferences(user_id)
        preferred_focus_window = prefs.get("focus_window", "9PM-1AM")
    except Exception:
        preferred_focus_window = "9PM-1AM"

    scenario = get_active_scenario()
    run_dir = get_run_dir()
    target_date = get_target_date()

    cache_key = f"{user_id}:{target_date}:{scenario}"
    now = time.monotonic()
    if cache_key in _cache:
        ts, cached = _cache[cache_key]
        if now - ts < _CACHE_TTL:
            _health_cache_hits.add(1, {"user.id": user_id})
            _logger.debug(f"Cache hit for {user_id} ({scenario}/{target_date})")
            return cached

    with tracer.start_as_current_span("health.run_pipeline") as span:
        span.set_attribute("user.id", user_id)
        span.set_attribute("health.scenario", scenario)
        span.set_attribute("health.target_date", target_date)
        start = time.perf_counter()

        try:
            state = await run_pipeline(user_id, target_date, run_dir)
            output = HealthPipelineOutput.from_state(
                state,
                preferred_focus_window=preferred_focus_window,
                scenario=scenario,
            )
            result = {
                "energy_level":         output.energy_level,
                "focus_window":         output.focus_window,
                "cognitive_load_score": output.cognitive_load_score,
                "avoid_tasks":          output.avoid_tasks,
                "node3_verdict":        output.node3_verdict,
                "node4_classification": output.node4_classification,
                "final_insight":        output.final_insight,
                "psi":                  output.psychological_strain_index,
                "pli":                  output.physical_load_index,
            }
            _cache[cache_key] = (now, result)
            span.set_attribute("health.verdict", result["node3_verdict"])
            span.set_attribute("health.psi", result["psi"])
            span.set_attribute("health.pli", result["pli"])
            _logger.info(f"Health analysis complete for {user_id}: verdict={result['node3_verdict']}, PSI={result['psi']:.0f}")
            return result
        except Exception as e:
            span.set_status(trace.StatusCode.ERROR, str(e))
            span.record_exception(e)
            _health_pipeline_errors.add(1, {"user.id": user_id, "scenario": scenario})
            _logger.error(f"Pipeline error for {user_id}: {e}")
            return _fallback(preferred_focus_window)
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            _health_duration.record(duration_ms, {"scenario": scenario})
            span.set_attribute("health.duration_ms", duration_ms)


def _fallback(preferred_focus_window: str) -> dict:
    """Neutral health context when pipeline cannot run."""
    return {
        "energy_level":         "medium",
        "focus_window":         preferred_focus_window,
        "cognitive_load_score": 0.65,
        "avoid_tasks":          [],
        "node3_verdict":        "NONE",
        "node4_classification": None,
        "final_insight":        None,
        "psi":                  50.0,
        "pli":                  0.0,
    }
