"""
autonomic_decoupler.py — Node 3: Autonomic Decoupler (ADK FunctionNode).

Deterministic rule engine. Takes Node 1 and Node 2 outputs and computes
PSI (Psychological Strain Index) and PLI (Physical Load Index) scores,
then routes the graph based on verdict.

NEVER add an LLM to this node. See ADR-003.

Reads:  ctx.state["node1_flags"], ctx.state["node2_metrics"]
Writes: ctx.state["psychological_strain_index"],
        ctx.state["physical_load_index"],
        ctx.state["node3_verdict"],
        ctx.state["node1_flags"] (adds psi_breakdown, pli_breakdown)
Sets:   ctx.route to the verdict string for conditional edge routing
"""

from __future__ import annotations

from google.adk.workflow import FunctionNode
from telemetry import tracer, meter, get_logger

_logger = get_logger("health.node3")
_psi_gauge = meter.create_histogram("health.psi", description="Psychological Strain Index")
_pli_gauge = meter.create_histogram("health.pli", description="Physical Load Index")
_verdict_counter = meter.create_counter("health.verdict", description="Verdict distribution")


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


async def _autonomic_decoupler_fn(ctx) -> None:
    """
    Node 3: Autonomic Decoupler — deterministic PSI/PLI scoring and verdict.

    NEVER add an LLM here. This node must remain deterministic and auditable.

    Routing via ctx.route:
        "PSYCHOLOGICAL" → Node 4 (Insights Engine)
        "AMBIGUOUS"     → Node 4
        "PHYSICAL"      → END
        "NONE"          → END
    """
    flags   = ctx.state.get("node1_flags", {})
    metrics = ctx.state.get("node2_metrics", {})

    cold_start = flags.get("cold_start", False)
    if cold_start:
        ctx.state["psychological_strain_index"] = 0.0
        ctx.state["physical_load_index"]        = 0.0
        ctx.state["node3_verdict"]              = "NONE"
        ctx.route = "NONE"
        return

    bs = flags.get("baseline_stats", {})
    tv = flags.get("today_values", {})

    # ── PSI (Psychological Strain Index) ────────────────────────────────────

    # HRV suppression: largest single contributor (35%)
    mean_hrv  = bs.get("hrv_sdnn_ms", {}).get("mean", 0)
    today_hrv = tv.get("hrv_sdnn_ms") or 0
    hrv_pct_suppression = max(0, (mean_hrv - today_hrv) / mean_hrv * 100) if mean_hrv else 0
    hrv_component = _clamp(hrv_pct_suppression / 30 * 100, 0, 100) * 0.35

    # Excess awake time (25%)
    mean_awake  = bs.get("sleep_awake_hours", {}).get("mean", 0)
    std_awake   = bs.get("sleep_awake_hours", {}).get("std", 0)
    today_awake = tv.get("sleep_awake_hours") or 0
    awake_zscore    = max(0, (today_awake - mean_awake) / max(0.01, std_awake))
    awake_component = _clamp(awake_zscore / 3 * 100, 0, 100) * 0.25

    # Deep sleep deficit (20%)
    mean_deep  = bs.get("sleep_deep_hours", {}).get("mean", 0)
    std_deep   = bs.get("sleep_deep_hours", {}).get("std", 0)
    today_deep = tv.get("sleep_deep_hours") or 0
    deep_zscore    = max(0, (mean_deep - today_deep) / max(0.01, std_deep))
    deep_component = _clamp(deep_zscore / 3 * 100, 0, 100) * 0.20

    # RPE dissociation (15%) — amplified when discrepancy flag or affective score confirmed
    has_activity          = metrics.get("has_activity", False)
    rpe_today             = metrics.get("rpe_today")
    relative_effort_today = metrics.get("relative_effort_today") or 0
    discrepancy_flag      = metrics.get("discrepancy_flag", False)
    affective_score       = metrics.get("affective_fatigue_score", 0.0)

    if has_activity and rpe_today is not None and relative_effort_today > 0:
        rpe_zscore    = (rpe_today - 5.5) / 1.5
        effort_zscore = (relative_effort_today - 30) / 15
        base_dissociation = max(0, rpe_zscore - effort_zscore)

        if discrepancy_flag:
            dissociation_multiplier = 1.3
        elif affective_score > 0.5:
            dissociation_multiplier = 1.15
        else:
            dissociation_multiplier = 1.0

        dissociation_component = _clamp(
            base_dissociation * dissociation_multiplier / 3 * 100, 0, 100
        ) * 0.15
    else:
        dissociation_component = 0.0

    # Resting HR elevation (5%)
    mean_rhr  = bs.get("resting_hr_bpm", {}).get("mean", 0)
    std_rhr   = bs.get("resting_hr_bpm", {}).get("std", 0)
    today_rhr = tv.get("resting_hr_bpm") or 0
    rhr_zscore    = max(0, (today_rhr - mean_rhr) / max(0.01, std_rhr))
    rhr_component = _clamp(rhr_zscore / 3 * 100, 0, 100) * 0.05

    # Sleep latency PSI contribution (8% combined)
    deep_latency_min = tv.get("deep_sleep_latency_minutes")
    rem_latency_min  = tv.get("rem_sleep_latency_minutes")
    late_night_count = tv.get("late_night_awake_windows_count") or 0

    latency_component = 0.0
    if deep_latency_min is not None and deep_latency_min > 60:
        latency_component += _clamp((deep_latency_min - 60) / 90 * 100, 0, 100) * 0.03
    if rem_latency_min is not None and rem_latency_min > 120:
        latency_component += _clamp((rem_latency_min - 120) / 60 * 100, 0, 100) * 0.03
    if late_night_count >= 2:
        latency_component += _clamp((late_night_count - 1) / 3 * 100, 0, 100) * 0.02

    PSI = (hrv_component + awake_component + deep_component
           + dissociation_component + rhr_component + latency_component)

    # ── PLI (Physical Load Index) ────────────────────────────────────────────

    # ATL (acute training load) — 40%
    atl = metrics.get("atl", 0.0)
    atl_component = _clamp(atl / 80 * 100, 0, 100) * 0.40

    # Week-over-week volume spike — 35%
    week_effort_current = metrics.get("week_effort_current", 0.0)
    week_effort_prior   = metrics.get("week_effort_prior", 0.0)
    if week_effort_prior > 0:
        wow_pct = max(0, (week_effort_current - week_effort_prior) / week_effort_prior * 100)
    else:
        wow_pct = 0
    wow_component = _clamp(wow_pct / 50 * 100, 0, 100) * 0.35

    # Degradation-aware component — 15% (replaces raw speed proxy from pre-Stage-1)
    fatigue_type = metrics.get("fatigue_type_flag", "NOMINAL")
    primary_deg  = metrics.get("primary_degradation_pct")

    if has_activity and primary_deg is not None:
        if fatigue_type == "NEUROMUSCULAR":
            deg_score = _clamp(primary_deg / 15 * 100, 0, 100)
        elif fatigue_type == "CARDIORESPIRATORY":
            deg_score = _clamp(primary_deg / 12 * 100, 0, 100)
        else:
            deg_score = _clamp(primary_deg / 10 * 100, 0, 100)
        degradation_component = deg_score * 0.15
    else:
        degradation_component = 0.0

    # Sleep efficiency deficit — 10%
    mean_eff  = bs.get("sleep_efficiency_pct", {}).get("mean", 0)
    std_eff   = bs.get("sleep_efficiency_pct", {}).get("std", 0)
    today_eff = tv.get("sleep_efficiency_pct") or 0
    eff_zscore    = max(0, (mean_eff - today_eff) / max(0.01, std_eff))
    eff_component = _clamp(eff_zscore / 3 * 100, 0, 100) * 0.10

    PLI = atl_component + wow_component + degradation_component + eff_component

    # ── Store breakdowns (piggybacked into node1_flags for Node 4) ───────────
    psi_breakdown = {
        "hrv_component":          round(hrv_component, 2),
        "awake_component":        round(awake_component, 2),
        "deep_component":         round(deep_component, 2),
        "dissociation_component": round(dissociation_component, 2),
        "rhr_component":          round(rhr_component, 2),
        "latency_component":      round(latency_component, 2),
    }
    pli_breakdown = {
        "atl_component":          round(atl_component, 2),
        "wow_component":          round(wow_component, 2),
        "degradation_component":  round(degradation_component, 2),
        "eff_component":          round(eff_component, 2),
    }
    ctx.state["node1_flags"] = {**flags, "psi_breakdown": psi_breakdown, "pli_breakdown": pli_breakdown}

    # ── Routing rules (UNVALIDATED_HEURISTIC thresholds — Phase 7 for calibration) ──
    if PSI > 45 and PLI < 45:
        verdict = "PSYCHOLOGICAL"
    elif PLI > 60 and PSI < 35:
        verdict = "PHYSICAL"
    elif PSI > 45 and PLI > 45:
        verdict = "AMBIGUOUS"
    else:
        verdict = "NONE"

    ctx.state["psychological_strain_index"] = round(PSI, 2)
    ctx.state["physical_load_index"]        = round(PLI, 2)
    ctx.state["node3_verdict"]              = verdict

    # Set ctx.route so ADK conditional edges can match
    ctx.route = verdict


async def _traced_autonomic_decoupler_fn(ctx) -> None:
    """Traced wrapper for Node 3."""
    import time
    with tracer.start_as_current_span("health.node3.autonomic_decoupler") as span:
        span.set_attribute("pipeline.node", "autonomic_decoupler")
        start = time.perf_counter()
        await _autonomic_decoupler_fn(ctx)
        duration_ms = (time.perf_counter() - start) * 1000
        psi = ctx.state.get("psychological_strain_index", 0)
        pli = ctx.state.get("physical_load_index", 0)
        verdict = ctx.state.get("node3_verdict", "UNKNOWN")
        span.set_attribute("node3.psi", psi)
        span.set_attribute("node3.pli", pli)
        span.set_attribute("node3.verdict", verdict)
        span.set_attribute("node3.duration_ms", duration_ms)
        _psi_gauge.record(psi)
        _pli_gauge.record(pli)
        _verdict_counter.add(1, {"verdict": verdict})
        span.add_event("agent.output", {
            "node3.verdict": verdict,
            "node3.psi": str(psi),
            "node3.pli": str(pli),
        })
        _logger.info(f"[node3.autonomic_decoupler] OK — verdict={verdict}, PSI={psi:.1f}, PLI={pli:.1f}")


# ADK FunctionNode — instantiated once, reused across runs
autonomic_decoupler = FunctionNode(
    func=_traced_autonomic_decoupler_fn,
    name="autonomic_decoupler",
)
