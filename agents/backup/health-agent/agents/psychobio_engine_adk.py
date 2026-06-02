"""
psychobio_engine_adk.py — CLI harness for the ADK PsychoBio Engine.

Usage:
    python -m agents.psychobio_engine_adk --scenario progressive_work_burnout
    python -m agents.psychobio_engine_adk --scenario progressive_work_burnout --date 2026-06-20
    python -m agents.psychobio_engine_adk --scenario training_overreach --model gemini-2.5-flash

This file is the ADK equivalent of the LangGraph psychobio_engine.py CLI.
Same diagnostic output format. Same scenario paths. Different graph backend.
"""

from __future__ import annotations

import asyncio
import argparse
import os
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).parent.parent

SCENARIO_DATA_DIRS = {
    # Curated hand-crafted sample (Jan 2025 dates) — primary validation dataset
    "progressive_work_burnout": "datasets/progressive_work_burnout/user_001/20260526T021707Z",
    # Simulator-generated run (May–Jun 2026 dates) — for June spot-checks
    "progressive_work_burnout_sim": "datasets/progressive_work_burnout_sim",
    "training_overreach":       "datasets/training_overreach",
    "healthy_baseline":         "datasets/healthy_baseline",
    "emotional_volatility":     "datasets/emotional_volatility",
}


def _load_env(env_path: Path) -> None:
    """Load .env file without requiring python-dotenv."""
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            v = v.strip()
            if v and k.strip() not in os.environ:
                os.environ[k.strip()] = v


def print_diagnostic(state: dict, repo: Any) -> None:
    """Print the same diagnostic format as the LangGraph reference engine."""
    flags   = state.get("node1_flags", {})
    metrics = state.get("node2_metrics", {})
    bs      = flags.get("baseline_stats", {})
    tv      = flags.get("today_values", {})
    psi_bd  = flags.get("psi_breakdown", {})
    pli_bd  = flags.get("pli_breakdown", {})

    print("\n" + "=" * 70)
    print(f"  PSYCHOBIO ENGINE (ADK) — {state.get('target_date')}")
    print("=" * 70)

    print("\n── NODE 1: HealthKit Sentinel ──")
    if flags.get("cold_start"):
        print("  Cold start — insufficient baseline (< 7 days history)")
    else:
        print("  Flags raised:")
        for f in ["hrv_suppressed", "rhr_elevated", "sleep_fragmented", "deep_sleep_reduced"]:
            print(f"    {f}: {flags.get(f)}")
        print("  Sleep latency flags:")
        print(f"    late_night_awake_flag:   {flags.get('late_night_awake_flag')} "
              f"(count={tv.get('late_night_awake_windows_count', 'N/A')})")
        print(f"    deep_sleep_latency_flag: {flags.get('deep_sleep_latency_flag')} "
              f"({tv.get('deep_sleep_latency_minutes', 'N/A')} min)")
        print(f"    rem_latency_flag:        {flags.get('rem_latency_flag')} "
              f"({tv.get('rem_sleep_latency_minutes', 'N/A')} min)")
        print("  Today values vs 14d baseline:")
        for metric in ["hrv_sdnn_ms", "resting_hr_bpm", "sleep_efficiency_pct",
                        "sleep_deep_hours", "sleep_awake_hours", "avg_respiratory_rate_bpm"]:
            today_val = tv.get(metric, "N/A")
            baseline  = bs.get(metric, {})
            mean = baseline.get("mean", "N/A")
            std  = baseline.get("std", "N/A")
            if isinstance(mean, float):
                print(f"    {metric}: today={today_val:.2f}  mean={mean:.2f}  std={std:.2f}")
            else:
                print(f"    {metric}: today={today_val}  mean={mean}  std={std}")

    print("\n── NODE 2: Strava Contextualizer ──")
    print(f"  ATL={metrics.get('atl', 0):.2f}  CTL={metrics.get('ctl', 0):.2f}  TSB={metrics.get('tsb', 0):.2f}")
    print(f"  Physical Load Score: {metrics.get('physical_load_score', 0):.1f}/100")
    print(f"  Week effort current: {metrics.get('week_effort_current', 0):.0f}  prior: {metrics.get('week_effort_prior', 0):.0f}")
    if metrics.get("has_activity"):
        print(f"  Activity: sport={metrics.get('sport_type')}  effort={metrics.get('relative_effort_today')}  "
              f"RPE={metrics.get('rpe_today')}  speed={metrics.get('average_speed_today')} m/s")
        print(f"  Fatigue type: {metrics.get('fatigue_type_flag')}  "
              f"Primary degradation: {metrics.get('primary_degradation_pct')}%")
        print(f"  Discrepancy flag: {metrics.get('discrepancy_flag')}  "
              f"Affective score: {metrics.get('affective_fatigue_score', 0.0):.2f}")
        if metrics.get("description_raw"):
            print(f"  Description: \"{metrics.get('description_raw')}\"")
    else:
        print("  Activity: rest day (no activity)")

    print("\n── NODE 3: Autonomic Decoupler ──")
    print(f"  PSI = {state.get('psychological_strain_index', 0):.2f}/100")
    if psi_bd:
        print(f"    HRV={psi_bd.get('hrv_component', 0):.2f}  Awake={psi_bd.get('awake_component', 0):.2f}  "
              f"Deep={psi_bd.get('deep_component', 0):.2f}  RPE-dissoc={psi_bd.get('dissociation_component', 0):.2f}  "
              f"RHR={psi_bd.get('rhr_component', 0):.2f}  Latency={psi_bd.get('latency_component', 0):.2f}")
    print(f"  PLI = {state.get('physical_load_index', 0):.2f}/100")
    if pli_bd:
        print(f"    ATL={pli_bd.get('atl_component', 0):.2f}  WoW={pli_bd.get('wow_component', 0):.2f}  "
              f"Degradation={pli_bd.get('degradation_component', 0):.2f}  SleepEff={pli_bd.get('eff_component', 0):.2f}")
    print(f"  Verdict: {state.get('node3_verdict')}")

    if state.get("node4_classification") or state.get("final_insight"):
        print("\n── NODE 4: Insights Engine ──")
        print(f"  Classification: {state.get('node4_classification')}")
        print(f"  Insight: {state.get('final_insight')}")

    # Evaluation against manifest
    manifest = repo.get_manifest_entry(state.get("target_date", ""))
    if manifest:
        expected_verdict        = manifest.get("expected_node3_verdict", "?")
        expected_classification = manifest.get("expected_node4_classification")
        actual_verdict          = state.get("node3_verdict")
        match = actual_verdict == expected_verdict
        print("\n── EVALUATION ──")
        print(f"  Expected verdict:        {expected_verdict}")
        print(f"  Actual verdict:          {actual_verdict}")
        print(f"  Expected classification: {expected_classification}")
        print(f"  Actual classification:   {state.get('node4_classification')}")
        print(f"  Verdict Match: {'✓ PASS' if match else '✗ FAIL'}")
    print("=" * 70 + "\n")


async def main() -> None:
    # Load .env from repo root
    _load_env(REPO_ROOT / ".env")

    parser = argparse.ArgumentParser(description="PsychoBio Engine — ADK")
    parser.add_argument(
        "--scenario",
        required=True,
        choices=sorted(SCENARIO_DATA_DIRS.keys()),
    )
    parser.add_argument(
        "--date",
        default=None,
        help="YYYY-MM-DD target date. Defaults to last day in data.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Gemini model for Node 4 (e.g. gemini-2.5-pro). Overrides NODE4_MODEL env var.",
    )
    args = parser.parse_args()

    if args.model:
        os.environ["NODE4_MODEL"] = args.model

    run_dir = str(REPO_ROOT / SCENARIO_DATA_DIRS[args.scenario])

    # Import here so env vars are set before module-level constants are read
    from agents.tools.data_tools import DataRepository
    from agents.graph_orchestrator import run_pipeline

    repo = DataRepository(run_dir)

    if args.date:
        target_date = args.date
    else:
        dates = [r["summary_date"] for r in repo._hk]
        target_date = sorted(dates)[-1]

    print(f"Running scenario '{args.scenario}' for date {target_date} [ADK]")
    print(f"Run dir: {run_dir}")
    print(f"Node 4 model: {os.environ.get('NODE4_MODEL', 'gemini-2.5-flash')}")

    final_state = await run_pipeline(
        user_id="user_001",
        target_date=target_date,
        run_dir=run_dir,
    )

    print_diagnostic(final_state, repo)


if __name__ == "__main__":
    asyncio.run(main())
