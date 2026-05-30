"""
healthkit_sentinel.py — Node 1: HealthKit Sentinel (ADK FunctionNode).

Pure Python biometric flag detection. No LLM. Deterministic.
Runs in parallel with Node 2 (Strava Contextualizer).

Reads:  ctx.state["run_dir"], ctx.state["target_date"]
Writes: ctx.state["node1_flags"]
"""

from __future__ import annotations

from typing import Any

from google.adk.workflow import FunctionNode

from agents.tools.data_tools import DataRepository


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


async def _healthkit_sentinel_fn(ctx) -> None:
    """
    Node 1: HealthKit Sentinel.

    Reads today's HealthKit data, computes deviation flags against the
    user's 14-day rolling baseline, and emits sleep latency triangulation
    flags. No LLM. Deterministic.

    Writes to ctx.state:
        node1_flags (dict): cold_start, hrv_suppressed, rhr_elevated,
            sleep_fragmented, deep_sleep_reduced, late_night_awake_flag,
            deep_sleep_latency_flag, rem_latency_flag, today_values,
            baseline_stats
    """
    run_dir     = ctx.state["run_dir"]
    target_date = ctx.state["target_date"]

    repo     = DataRepository(run_dir)
    baseline = repo.get_baseline_stats(target_date)
    today    = repo.get_daily_summary(target_date)

    flags: dict[str, Any] = {}

    if not baseline:
        flags["cold_start"]     = True
        flags["today_values"]   = {}
        flags["baseline_stats"] = {}
        ctx.state["node1_flags"] = flags
        return

    cold_start = baseline.get("cold_start", False)
    flags["cold_start"] = cold_start

    today_values = {
        "hrv_sdnn_ms":                    today.get("hrv_sdnn_ms"),
        "resting_hr_bpm":                 today.get("resting_hr_bpm"),
        "sleep_efficiency_pct":           today.get("sleep_efficiency_pct"),
        "sleep_awake_hours":              today.get("sleep_awake_hours"),
        "sleep_deep_hours":               today.get("sleep_deep_hours"),
        "avg_respiratory_rate_bpm":       today.get("avg_respiratory_rate_bpm"),
        # Sleep latency fields (None if no raw samples available)
        "late_night_awake_windows_count": today.get("late_night_awake_windows_count"),
        "deep_sleep_latency_minutes":     today.get("deep_sleep_latency_minutes"),
        "rem_sleep_latency_minutes":      today.get("rem_sleep_latency_minutes"),
    }
    flags["today_values"]   = today_values
    flags["baseline_stats"] = {k: v for k, v in baseline.items() if k != "cold_start"}

    if cold_start:
        ctx.state["node1_flags"] = flags
        return

    # ── Existing biometric deviation flags ───────────────────────────────────
    # UNVALIDATED_HEURISTIC thresholds — to be calibrated in Phase 7
    hrv_mean = baseline["hrv_sdnn_ms"]["mean"]
    hrv_std  = baseline["hrv_sdnn_ms"]["std"]
    flags["hrv_suppressed"] = today_values["hrv_sdnn_ms"] < (hrv_mean - 1.5 * hrv_std)

    rhr_mean = baseline["resting_hr_bpm"]["mean"]
    rhr_std  = baseline["resting_hr_bpm"]["std"]
    flags["rhr_elevated"] = today_values["resting_hr_bpm"] > (rhr_mean + 1.5 * rhr_std)

    flags["sleep_fragmented"] = (
        today_values["sleep_efficiency_pct"] < 80.0
        or today_values["sleep_awake_hours"] > 1.5
    )

    deep_mean = baseline["sleep_deep_hours"]["mean"]
    deep_std  = baseline["sleep_deep_hours"]["std"]
    flags["deep_sleep_reduced"] = today_values["sleep_deep_hours"] < (deep_mean - 1.0 * deep_std)

    # ── Sleep latency triangulation (Stage 1, Fix 2) ─────────────────────────
    late_night_count = today_values.get("late_night_awake_windows_count")
    deep_latency_min = today_values.get("deep_sleep_latency_minutes")
    rem_latency_min  = today_values.get("rem_sleep_latency_minutes")

    # Late-night sympathetic leakage: ≥2 awake windows after 02:00
    if late_night_count is not None:
        flags["late_night_awake_flag"] = late_night_count >= 2
    else:
        flags["late_night_awake_flag"] = None

    # Deep sleep latency:
    #   rapid (<20 min) → skeletal muscle debt (body crashes into deep sleep)
    #   delayed (>60 min) → elevated arousal / psychological stress
    if deep_latency_min is not None:
        if deep_latency_min < 20:
            flags["deep_sleep_latency_flag"] = "RAPID_ONSET"
        elif deep_latency_min > 60:
            flags["deep_sleep_latency_flag"] = "DELAYED_ONSET"
        else:
            flags["deep_sleep_latency_flag"] = "NORMAL"
    else:
        flags["deep_sleep_latency_flag"] = None

    # REM latency:
    #   delayed (>120 min) → CNS hyperarousal, mind unable to down-regulate
    if rem_latency_min is not None:
        if rem_latency_min > 120:
            flags["rem_latency_flag"] = "DELAYED"
        else:
            flags["rem_latency_flag"] = "NORMAL"
    else:
        flags["rem_latency_flag"] = None

    ctx.state["node1_flags"] = flags


# ADK FunctionNode — instantiated once, reused across runs
healthkit_sentinel = FunctionNode(
    func=_healthkit_sentinel_fn,
    name="healthkit_sentinel",
)
