"""
Health tool — Owner: Vatsal

analyze_health() runs the PsychoBio pipeline and returns a dict matching
the HealthOutput schema (energy_level, focus_window, cognitive_load_score,
avoid_tasks) plus enriched fields for the coordinator prompt.

Pattern: same as relationship_tools.py — reads MongoDB, runs pipeline,
returns a plain dict.
"""

from db import get_db
from agents.memory import MemoryAgent
from agents.health_agent.agents.graph_orchestrator import run_pipeline
from agents.health_agent.scenario_selector import (
    get_active_scenario,
    get_run_dir,
    get_target_date,
)
from agents.health_agent.schemas import HealthPipelineOutput


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

    try:
        state = await run_pipeline(user_id, target_date, run_dir)
        output = HealthPipelineOutput.from_state(
            state,
            preferred_focus_window=preferred_focus_window,
            scenario=scenario,
        )
        return {
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
    except Exception as e:
        print(f"[analyze_health] Pipeline error for {user_id}: {e}")
        return _fallback(preferred_focus_window)


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
