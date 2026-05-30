"""
strava_contextualizer.py — Node 2: Strava Contextualizer (ADK FunctionNode).

ATL/CTL/TSB, weekly load, sport-type degradation analysis, keyword NLP.
No LLM in Phase 1 keyword path. Runs in PARALLEL with Node 1.

Reads:  ctx.state["run_dir"], ctx.state["target_date"]
Writes: ctx.state["node2_metrics"]
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from google.adk.workflow import FunctionNode

from agents.tools.data_tools import DataRepository


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


# Keywords weighted by severity for affective fatigue scoring
_FATIGUE_KEYWORDS: list[tuple[str, float]] = [
    ("exhausted",   1.0),
    ("dead legs",   0.9),
    ("dead",        0.8),
    ("drained",     0.9),
    ("flat",        0.7),
    ("sluggish",    0.7),
    ("heavy",       0.6),
    ("tired",       0.6),
    ("struggled",   0.7),
    ("dig deep",    0.8),
    ("empty",       0.8),
    ("nothing left", 0.9),
    ("no energy",   0.8),
    ("hard",        0.4),
    ("tough",       0.4),
]


def _keyword_affective_score(description: str | None) -> float:
    """
    Fast keyword pass over activity description. No LLM.
    Returns affective_fatigue_score in [0.0, 1.0].
    """
    if not description:
        return 0.0
    text = description.lower()
    total = 0.0
    for keyword, weight in _FATIGUE_KEYWORDS:
        if keyword in text:
            total += weight
    return min(1.0, total / 2.0)   # normalise: two strong hits → 1.0


async def _strava_contextualizer_fn(ctx) -> None:
    """
    Node 2: Strava Contextualizer.

    Phase A: Compute ATL/CTL/TSB and weekly effort windows.
    Phase B: Keyword NLP on activity description for affective pre-fatigue.
    Sport-type branching determines which degradation metric is primary.

    Writes to ctx.state:
        node2_metrics (dict): atl, ctl, tsb, physical_load_score,
            week_effort_current, week_effort_prior, has_activity,
            relative_effort_today, rpe_today, average_speed_today,
            sport_type, primary_degradation_pct, secondary_degradation_value,
            fatigue_type_flag, discrepancy_flag, affective_fatigue_score,
            description_raw
    """
    run_dir     = ctx.state["run_dir"]
    target_date = ctx.state["target_date"]

    repo = DataRepository(run_dir)

    # ── Phase A: ATL / CTL / TSB ──────────────────────────────────────────────
    atl_ctl = repo.compute_atl_ctl(target_date)
    atl = atl_ctl["atl"]
    ctl = atl_ctl["ctl"]
    tsb = atl_ctl["tsb"]

    physical_load_score = _clamp(atl / 80 * 100, 0, 100)

    # Weekly effort windows
    target             = date.fromisoformat(target_date)
    week_start_current = (target - timedelta(days=6)).isoformat()
    week_start_prior   = (target - timedelta(days=13)).isoformat()
    week_end_prior     = (target - timedelta(days=7)).isoformat()

    week_effort_current = 0.0
    week_effort_prior   = 0.0
    for act in repo.get_strava_summary():
        act_date = act["start_date"][:10]
        effort   = act.get("relative_effort") or 0
        if week_start_current <= act_date <= target_date:
            week_effort_current += effort
        if week_start_prior <= act_date <= week_end_prior:
            week_effort_prior += effort

    # ── Activity for today ───────────────────────────────────────────────────
    activity = repo.get_activity_today(target_date)

    metrics: dict[str, Any] = {
        "atl":                        atl,
        "ctl":                        ctl,
        "tsb":                        tsb,
        "physical_load_score":        physical_load_score,
        "week_effort_current":        week_effort_current,
        "week_effort_prior":          week_effort_prior,
        "has_activity":               activity is not None,
        "relative_effort_today":      None,
        "rpe_today":                  None,
        "average_speed_today":        None,
        "sport_type":                 None,
        # New Stage 1 fields
        "primary_degradation_pct":    None,
        "secondary_degradation_value": None,
        "fatigue_type_flag":          "NOMINAL",
        "discrepancy_flag":           False,
        "affective_fatigue_score":    0.0,
        "description_raw":            None,
    }

    if activity:
        metrics["relative_effort_today"] = activity.get("relative_effort")
        metrics["rpe_today"]             = activity.get("perceived_exertion")
        metrics["average_speed_today"]   = activity.get("average_speed")
        sport_type                       = activity.get("sport_type")
        metrics["sport_type"]            = sport_type

        description = activity.get("description") or activity.get("name")
        metrics["description_raw"] = description

        cadence_deg = activity.get("biomechanical_cadence_degradation_pct")
        pace_deg    = activity.get("pace_degradation_pct")
        cardio_eff  = activity.get("cardio_efficiency_index")

        # ── Sport-type branching (Stage 1, Fix 3) ────────────────────────────
        if sport_type == "Run":
            primary_deg   = cadence_deg
            secondary_deg = pace_deg
        elif sport_type in ("Ride", "VirtualRide"):
            primary_deg   = pace_deg
            secondary_deg = cardio_eff
        elif sport_type == "Swim":
            primary_deg   = pace_deg
            secondary_deg = None
        else:
            primary_deg   = pace_deg
            secondary_deg = cardio_eff

        metrics["primary_degradation_pct"]     = primary_deg
        metrics["secondary_degradation_value"] = secondary_deg

        # ── Fatigue-type classification ───────────────────────────────────────
        if cadence_deg is not None and pace_deg is not None:
            if cadence_deg > 5:
                fatigue_type = "NEUROMUSCULAR"
            elif pace_deg > 8 and cadence_deg < 3:
                fatigue_type = "CARDIORESPIRATORY"
            else:
                fatigue_type = "NOMINAL"
        else:
            fatigue_type = "NOMINAL"
        metrics["fatigue_type_flag"] = fatigue_type

        # ── Discrepancy flag (high perceived cost, normal external output) ─────
        rpe_today = metrics["rpe_today"]
        high_perceived_cost = rpe_today is not None and rpe_today > 6.5
        external_output_normal = (
            (primary_deg is None or primary_deg < 5)
            and (pace_deg is None or pace_deg < 8)
        )
        metrics["discrepancy_flag"] = bool(high_perceived_cost and external_output_normal)

        # ── Phase B: keyword NLP on description ──────────────────────────────
        # Also trigger discrepancy if description contains drain language
        affective_score = _keyword_affective_score(description)
        metrics["affective_fatigue_score"] = affective_score
        # If description signals pre-fatigue AND discrepancy isn't already set, check again
        if affective_score > 0.5 and high_perceived_cost:
            metrics["discrepancy_flag"] = True

    ctx.state["node2_metrics"] = metrics


# ADK FunctionNode — instantiated once, reused across runs
strava_contextualizer = FunctionNode(
    func=_strava_contextualizer_fn,
    name="strava_contextualizer",
)
