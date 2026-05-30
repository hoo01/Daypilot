"""
schemas.py — Typed I/O models for the Health Agent microservice.

HealthPipelineInput  — what callers send to POST /health/analyse
HealthPipelineOutput — what the API returns, bridging ADK state to the
                       root monolith's HealthOutput / ScheduleInput shape.

energy_level and cognitive_load_score are compatibility fields so the root
CoordinatorAgent can consume health-agent output the same way it reads the
stub HealthAgent in the monolith.
"""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel


class HealthPipelineInput(BaseModel):
    """Request body for POST /health/analyse."""

    user_id: str
    target_date: str   # YYYY-MM-DD
    run_dir: str       # absolute path to scenario data directory


class HealthPipelineOutput(BaseModel):
    """
    Response model for POST /health/analyse.

    Core psychobio fields mirror PsychobioState (graph_state.py).
    Compatibility fields (energy_level, cognitive_load_score) match the
    root HealthOutput schema so the Coordinator can consume this directly.
    """

    user_id: str
    target_date: str

    # ── Core psychobio outputs ────────────────────────────────────────────────
    psychological_strain_index: float        # PSI 0–100
    physical_load_index: float               # PLI 0–100
    node3_verdict: str                       # NONE | PHYSICAL | PSYCHOLOGICAL | AMBIGUOUS
    node4_classification: Optional[str] = None
    final_insight: Optional[str] = None

    # ── Root monolith compatibility fields ────────────────────────────────────
    energy_level: str                        # LOW | MEDIUM | HIGH (derived from PSI)
    cognitive_load_score: float              # 0.0–1.0 (PSI / 100)

    @classmethod
    def from_state(cls, state: dict) -> "HealthPipelineOutput":
        """Map a raw ADK final-state dict to a typed HealthPipelineOutput."""
        psi = state.get("psychological_strain_index", 0.0)

        if psi >= 65:
            energy = "LOW"
        elif psi >= 35:
            energy = "MEDIUM"
        else:
            energy = "HIGH"

        return cls(
            user_id=state.get("user_id", ""),
            target_date=state.get("target_date", ""),
            psychological_strain_index=round(psi, 2),
            physical_load_index=round(state.get("physical_load_index", 0.0), 2),
            node3_verdict=state.get("node3_verdict", "NONE"),
            node4_classification=state.get("node4_classification"),
            final_insight=state.get("final_insight"),
            energy_level=energy,
            cognitive_load_score=round(psi / 100, 3),
        )
