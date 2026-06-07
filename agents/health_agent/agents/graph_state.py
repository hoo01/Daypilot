"""
graph_state.py — Shared state schema for the PsychoBio ADK pipeline.

PsychobioState is passed as state_schema= to the ADK Workflow.
Field names are identical to the LangGraph version so node logic
reads ctx.state["node1_flags"] exactly as before.
"""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


class PsychobioState(BaseModel):
    """Schema for ADK session state."""

    # ── Inputs (written by CLI harness before graph starts) ──────────────────
    user_id: str = ""
    target_date: str = ""      # YYYY-MM-DD
    run_dir: str = ""          # absolute path to data directory

    # ── Node 1 writes ─────────────────────────────────────────────────────────
    # cold_start, hrv_suppressed, rhr_elevated, sleep_fragmented,
    # deep_sleep_reduced, late_night_awake_flag, deep_sleep_latency_flag,
    # rem_latency_flag, today_values{}, baseline_stats{}
    # psi_breakdown{} and pli_breakdown{} are added by Node 3
    node1_flags: dict[str, Any] = Field(default_factory=dict)

    # ── Node 2 writes ─────────────────────────────────────────────────────────
    # atl, ctl, tsb, physical_load_score, week_effort_current, week_effort_prior,
    # has_activity, relative_effort_today, rpe_today, average_speed_today,
    # sport_type, primary_degradation_pct, secondary_degradation_value,
    # fatigue_type_flag, discrepancy_flag, affective_fatigue_score, description_raw
    node2_metrics: dict[str, Any] = Field(default_factory=dict)

    # ── Node 3 writes ─────────────────────────────────────────────────────────
    psychological_strain_index: float = 0.0   # PSI 0–100
    physical_load_index: float = 0.0          # PLI 0–100
    node3_verdict: str = "NONE"               # NONE | PHYSICAL | PSYCHOLOGICAL | AMBIGUOUS

    # ── Node 4 writes (conditional on verdict) ───────────────────────────────
    node4_classification: str | None = None
    # ACUTE_COGNITIVE_LOAD | CHRONIC_COGNITIVE_FATIGUE | EARLY_BURNOUT_TRAJECTORY |
    # EMOTIONAL_VOLATILITY | WELL_RECOVERED | OPTIMAL_LOAD | PHYSICAL_OVERREACH |
    # RECOVERY_IN_PROGRESS
    final_insight: str | None = None
