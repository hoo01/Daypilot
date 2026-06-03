"""
scenario_selector.py — Bundled scenario selection for the health pipeline.

At import time, one scenario is chosen randomly from the four 2026 simulator
scenarios. That choice is fixed for the lifetime of the process (module-level
singleton). All calls to get_active_scenario() return the same scenario.

target_date resolution:
    Pick the latest date in the scenario manifest that is <= today.
    If today is beyond all manifest dates, use the last manifest date.
    This keeps the health signal "current" relative to today even though
    the data is synthetic.
"""

from __future__ import annotations

import json
import random
from datetime import date
from pathlib import Path

# The four simulator scenarios with 2026 dates (deployable)
_SCENARIO_NAMES = [
    "healthy_baseline",
    "training_overreach",
    "emotional_volatility",
    "progressive_work_burnout_sim",
]

_DATASETS_DIR = Path(__file__).parent / "datasets"


def _load_manifest(scenario_name: str) -> list[dict]:
    manifest_path = _DATASETS_DIR / scenario_name / "manifest.json"
    with open(manifest_path) as f:
        return json.load(f)


def _pick_scenario() -> str:
    """Pick one scenario randomly. Called once at module import."""
    return random.choice(_SCENARIO_NAMES)


# Module-level singleton: fixed for the lifetime of the process
_active_scenario: str = _pick_scenario()


def get_active_scenario() -> str:
    """Return the scenario name chosen at startup."""
    return _active_scenario


def get_run_dir() -> str:
    """Return the absolute path to the active scenario's dataset directory."""
    return str(_DATASETS_DIR / _active_scenario)


def get_target_date() -> str:
    """
    Return the best target date for today within the active scenario.

    Picks the latest manifest date that is <= today (real calendar date).
    Falls back to the last manifest date if today is beyond the scenario range.
    """
    today_str = date.today().isoformat()
    manifest = _load_manifest(_active_scenario)
    manifest_dates = sorted(r["date"] for r in manifest)

    # Latest manifest date <= today
    eligible = [d for d in manifest_dates if d <= today_str]
    if eligible:
        return eligible[-1]
    # today is before the scenario start — use the first date
    return manifest_dates[0]
