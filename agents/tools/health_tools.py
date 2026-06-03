"""
Health tool — Owner: Vatsal

analyze_health() is the coordinator's entry point to the PsychoBio pipeline.

Data source: bundled scenario datasets under agents/health_agent/datasets/.
At process startup, scenario_selector.py picks one scenario randomly and fixes
it for the session. analyze_health() always uses that scenario.

Preference: reads user's preferred focus window from MongoDB (via MemoryAgent).
Falls back to "9PM-1AM" if no preference is stored.

Returns a dict shaped like HealthOutput (energy_score, focus_windows,
cognitive_load) plus enriched fields (node3_verdict, node4_classification,
final_insight, psi, pli) for optional use by the coordinator prompt.
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
    Run the PsychoBio pipeline for the user and return their health context.

    The scenario (data source) is fixed for the process lifetime by
    scenario_selector. The target date is resolved from the scenario manifest
    relative to today.

    Returns keys: energy_score, focus_windows, cognitive_load, node3_verdict,
    node4_classification, final_insight, psi, pli, scenario.

    Falls back to neutral values if the pipeline errors.
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
            "energy_score":         output.energy_score,
            "focus_windows":        output.focus_windows,
            "cognitive_load":       output.cognitive_load,
            "node3_verdict":        output.node3_verdict,
            "node4_classification": output.node4_classification,
            "final_insight":        output.final_insight,
            "psi":                  output.psychological_strain_index,
            "pli":                  output.physical_load_index,
            "scenario":             output.scenario,
            "target_date":          output.target_date,
        }
    except Exception as e:
        print(f"[analyze_health] Pipeline error for {user_id} (scenario={scenario}): {e}")
        return _fallback(preferred_focus_window, scenario)


def _fallback(preferred_focus_window: str, scenario: str) -> dict:
    """Neutral health context when pipeline cannot run."""
    return {
        "energy_score":         "medium",
        "focus_windows":        [preferred_focus_window],
        "cognitive_load":       0.5,
        "node3_verdict":        "NONE",
        "node4_classification": None,
        "final_insight":        None,
        "psi":                  50.0,
        "pli":                  0.0,
        "scenario":             scenario,
        "target_date":          None,
    }
