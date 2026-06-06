"""
schemas.py — Output model for the Health Agent pipeline.

HealthPipelineOutput bridges ADK pipeline state to the root HealthOutput shape.
HealthPipelineInput is removed — run_pipeline() is called directly with positional args.
"""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel


# ── Focus window shift lookup ────────────────────────────────────────────────
# Applied only when PSI >= 65 (LOW energy). Maps preferred window → shifted window.
# Keys are the most common stored preference values.
_SHIFT_MAP = {
    "9PM-1AM":  "7PM-10PM",
    "10PM-2AM": "8PM-11PM",
    "8PM-12AM": "6PM-9PM",
    "9AM-1PM":  "7AM-10AM",
    "10AM-2PM": "8AM-11AM",
    "8AM-12PM": "6AM-9AM",
}


def _derive_focus_window(preferred: str, psi: float) -> str:
    """
    Return focus window adjusted for current PSI.
    PSI >= 65 (low energy): shift 2h earlier and shorten.
    PSI < 65: return preferred unchanged.
    """
    if psi >= 65:
        return _SHIFT_MAP.get(preferred, preferred)
    return preferred


class HealthPipelineOutput(BaseModel):
    """
    Response model for the health pipeline.

    Core psychobio fields mirror PsychobioState.
    Compatibility fields (energy_level, focus_window, cognitive_load_score,
    avoid_tasks) match the root HealthOutput schema so schedule_tools.py
    consumes this directly.
    """

    user_id: str
    target_date: str
    scenario: str    # which scenario was active — useful for debugging

    # Core psychobio outputs
    psychological_strain_index: float
    physical_load_index: float
    node3_verdict: str
    node4_classification: Optional[str] = None
    final_insight: Optional[str] = None

    # Root HealthOutput compatibility fields (match schemas.health.HealthOutput)
    energy_level: str              # "low" | "medium" | "high"
    focus_window: str              # e.g. "9PM-1AM"
    cognitive_load_score: float    # 0.0–1.0  (PSI / 100)
    avoid_tasks: list[str]         # derived from PSI thresholds

    @classmethod
    def from_state(
        cls,
        state: dict,
        preferred_focus_window: str = "9PM-1AM",
        scenario: str = "unknown",
    ) -> "HealthPipelineOutput":
        """Map a raw ADK final-state dict to a typed HealthPipelineOutput."""
        psi = state.get("psychological_strain_index", 0.0)

        if psi >= 65:
            energy = "low"
        elif psi >= 35:
            energy = "medium"
        else:
            energy = "high"

        # Derive avoid_tasks from PSI thresholds
        avoid: list[str] = []
        if psi >= 65:
            avoid = ["back-to-back deep work", "high-complexity tasks"]
        elif psi >= 35:
            avoid = ["extended focus sessions without breaks"]

        return cls(
            user_id=state.get("user_id", ""),
            target_date=state.get("target_date", ""),
            scenario=scenario,
            psychological_strain_index=round(psi, 2),
            physical_load_index=round(state.get("physical_load_index", 0.0), 2),
            node3_verdict=state.get("node3_verdict", "NONE"),
            node4_classification=state.get("node4_classification"),
            final_insight=state.get("final_insight"),
            energy_level=energy,
            focus_window=_derive_focus_window(preferred_focus_window, psi),
            cognitive_load_score=round(psi / 100, 3),
            avoid_tasks=avoid,
        )
