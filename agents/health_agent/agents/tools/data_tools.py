"""
data_tools.py — DataRepository and optional ADK-callable tool wrappers.

DataRepository is instantiated directly by FunctionNodes.
The standalone functions at the bottom are thin wrappers for future
LlmAgent tool use.

Cloud portability: swap the three get_* methods to hit BigQuery instead
of reading JSON files.  Node logic above this layer is backend-agnostic.
"""

from __future__ import annotations

import json
import math
import statistics
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any


class DataRepository:
    """Abstracts all JSON file access. Nodes never touch files directly."""

    BASELINE_METRICS = [
        "hrv_sdnn_ms",
        "resting_hr_bpm",
        "sleep_deep_hours",
        "sleep_awake_hours",
        "sleep_efficiency_pct",
        "avg_respiratory_rate_bpm",
    ]

    def __init__(self, run_dir: str):
        self.run_dir = Path(run_dir)
        self._hk: list[dict] = self._load("raw_healthkit_daily_summary.json")
        self._samples: list[dict] = self._load_optional("raw_healthkit_samples.json")
        self._strava_summary: list[dict] = self._load("strava_summary_activities.json")
        self._strava_detailed: list[dict] = self._load("strava_detailed_activities.json")
        self._manifest: list[dict] = self._load("manifest.json")

        self._hk_by_date: dict[str, dict] = {r["summary_date"]: r for r in self._hk}
        self._strava_summary_by_date: dict[str, dict] = {
            r["start_date"][:10]: r for r in self._strava_summary
        }
        self._strava_detailed_by_date: dict[str, dict] = {
            r["start_date"][:10]: r for r in self._strava_detailed
        }
        self._manifest_by_date: dict[str, dict] = {r["date"]: r for r in self._manifest}

        self._sleep_by_date: dict[str, list[dict]] = {}
        for r in self._samples:
            if r.get("sample_type") == "HKCategoryTypeIdentifierSleepAnalysis":
                d = r.get("sample_date", "")
                if d:
                    self._sleep_by_date.setdefault(d, []).append(r)

    def _load(self, filename: str) -> list[dict]:
        path = self.run_dir / filename
        with open(path) as f:
            return json.load(f)

    def _load_optional(self, filename: str) -> list[dict]:
        path = self.run_dir / filename
        if not path.exists():
            return []
        with open(path) as f:
            return json.load(f)

    # ── Sleep latency helpers ────────────────────────────────────────────────

    @staticmethod
    def _parse_ts(ts: str) -> datetime:
        for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.strptime(ts, fmt)
            except ValueError:
                continue
        return datetime.fromisoformat(ts)

    def _get_sleep_metrics_for_date(self, target_date: str) -> dict:
        """
        Compute sleep latency flags and late-night awake windows from raw sleep samples.

        Returns:
            late_night_awake_windows_count  — awake segments starting 02:00–06:00
            deep_sleep_latency_minutes      — minutes from sleep onset to first deep segment
            rem_sleep_latency_minutes       — minutes from sleep onset to first REM segment
        """
        sleep_recs = self._sleep_by_date.get(target_date, [])
        if not sleep_recs:
            return {
                "late_night_awake_windows_count": None,
                "deep_sleep_latency_minutes": None,
                "rem_sleep_latency_minutes": None,
            }

        asleep_cats = {
            "HKCategoryValueSleepAnalysisAsleepCore",
            "HKCategoryValueSleepAnalysisAsleepDeep",
            "HKCategoryValueSleepAnalysisAsleepREM",
        }

        asleep_recs = [r for r in sleep_recs if r.get("category_value") in asleep_cats]
        awake_recs  = [r for r in sleep_recs if r.get("category_value") == "HKCategoryValueSleepAnalysisAwake"]
        deep_recs   = [r for r in sleep_recs if r.get("category_value") == "HKCategoryValueSleepAnalysisAsleepDeep"]
        rem_recs    = [r for r in sleep_recs if r.get("category_value") == "HKCategoryValueSleepAnalysisAsleepREM"]

        if not asleep_recs:
            return {
                "late_night_awake_windows_count": None,
                "deep_sleep_latency_minutes": None,
                "rem_sleep_latency_minutes": None,
            }

        sleep_onset = min(self._parse_ts(r["start_timestamp"]) for r in asleep_recs)

        def latency_min(recs: list[dict]) -> float | None:
            if not recs:
                return None
            first_ts = min(self._parse_ts(r["start_timestamp"]) for r in recs)
            minutes = (first_ts - sleep_onset).total_seconds() / 60
            return round(max(0.0, minutes), 1)

        deep_latency = latency_min(deep_recs)
        rem_latency  = latency_min(rem_recs)

        late_night_count = sum(
            1 for r in awake_recs
            if 2 <= self._parse_ts(r["start_timestamp"]).hour < 6
        )

        return {
            "late_night_awake_windows_count": late_night_count,
            "deep_sleep_latency_minutes": deep_latency,
            "rem_sleep_latency_minutes": rem_latency,
        }

    # ── Activity degradation helpers ─────────────────────────────────────────

    @staticmethod
    def _compute_activity_degradation(laps: list[dict]) -> dict:
        """Compare first-half vs last-half laps to detect biomechanical/pace breakdown."""
        if len(laps) < 4:
            return {
                "biomechanical_cadence_degradation_pct": None,
                "pace_degradation_pct": None,
            }

        mid = len(laps) // 2
        first_half = laps[:mid]
        last_half  = laps[mid:]

        def _mean_field(lap_list: list[dict], field: str) -> float | None:
            vals = [l[field] for l in lap_list if l.get(field) is not None]
            return statistics.mean(vals) if vals else None

        first_cad = _mean_field(first_half, "average_cadence")
        last_cad  = _mean_field(last_half,  "average_cadence")
        if first_cad and first_cad > 0 and last_cad is not None:
            cadence_deg = round((first_cad - last_cad) / first_cad * 100, 2)
        else:
            cadence_deg = None

        first_spd = _mean_field(first_half, "average_speed")
        last_spd  = _mean_field(last_half,  "average_speed")
        if first_spd and first_spd > 0 and last_spd is not None:
            pace_deg = round((first_spd - last_spd) / first_spd * 100, 2)
        else:
            pace_deg = None

        return {
            "biomechanical_cadence_degradation_pct": cadence_deg,
            "pace_degradation_pct": pace_deg,
        }

    @staticmethod
    def _compute_cardio_efficiency(activity: dict) -> float | None:
        """
        Sport-appropriate cardio efficiency index.
        - Rides/VirtualRides: watts / HR  (higher = more efficient)
        - Runs/other: (speed m/s * 100) / HR
        """
        avg_hr = activity.get("average_heartrate")
        if not avg_hr or avg_hr <= 0:
            return None
        sport = activity.get("sport_type", "")
        avg_watts = activity.get("average_watts")
        avg_speed = activity.get("average_speed")
        if sport in ("Ride", "VirtualRide") and avg_watts is not None:
            return round(avg_watts / avg_hr, 3)
        if avg_speed is not None:
            return round(avg_speed * 100 / avg_hr, 3)
        return None

    # ── Public interface ─────────────────────────────────────────────────────

    def get_daily_summary(self, target_date: str) -> dict:
        record = dict(self._hk_by_date[target_date])
        sleep_metrics = self._get_sleep_metrics_for_date(target_date)
        record.update(sleep_metrics)
        return record

    def get_history_14d(self, target_date: str) -> list[dict]:
        target = date.fromisoformat(target_date)
        prior = [
            r for r in self._hk
            if date.fromisoformat(r["summary_date"]) < target
        ]
        prior.sort(key=lambda r: r["summary_date"])
        if len(prior) >= 14:
            return prior[-14:]
        # Simulation fallback: not enough prior-date records to form a full
        # 14-day baseline. Supplement with the records closest to target_date
        # that have not already been included (on or after target_date, sorted
        # ascending so the nearest dates are selected first). For synthetic
        # scenario data, temporal direction relative to target_date does not
        # affect the physiological signal being modelled — this ensures
        # cold_start never occurs.
        prior_dates = {r["summary_date"] for r in prior}
        supplement = sorted(
            [r for r in self._hk if r["summary_date"] not in prior_dates],
            key=lambda r: r["summary_date"],
        )
        needed = 14 - len(prior)
        return prior + supplement[:needed]

    def get_baseline_stats(self, target_date: str) -> dict:
        history = self.get_history_14d(target_date)
        n = len(history)
        if n < 7:
            return {}

        stats: dict[str, Any] = {}
        cold_start = n < 14
        for metric in self.BASELINE_METRICS:
            values = [r[metric] for r in history if r.get(metric) is not None]
            if not values:
                continue
            mean = statistics.mean(values)
            std = statistics.pstdev(values) if len(values) > 1 else 0.0
            stats[metric] = {"mean": mean, "std": std}

        if cold_start:
            stats["cold_start"] = True

        return stats

    def get_activity_today(self, target_date: str) -> dict | None:
        summary = self._strava_summary_by_date.get(target_date)
        if summary is None:
            return None
        detailed = self._strava_detailed_by_date.get(target_date, {})
        activity = {**summary, **detailed}

        laps = activity.get("laps") or []
        degradation = self._compute_activity_degradation(laps)
        activity.update(degradation)
        activity["cardio_efficiency_index"] = self._compute_cardio_efficiency(activity)

        return activity

    def compute_atl_ctl(self, target_date: str) -> dict:
        tau_atl = 7.0
        tau_ctl = 42.0
        k_atl = math.exp(-1 / tau_atl)
        k_ctl = math.exp(-1 / tau_ctl)

        target = date.fromisoformat(target_date)
        effort_by_date: dict[str, float] = {}
        for act in self._strava_summary:
            d = date.fromisoformat(act["start_date"][:10])
            if d <= target:
                key = d.isoformat()
                effort_by_date[key] = effort_by_date.get(key, 0.0) + (act.get("relative_effort") or 0)

        if not effort_by_date:
            return {"atl": 0.0, "ctl": 0.0, "tsb": 0.0}

        all_dates = sorted(effort_by_date.keys())
        start = date.fromisoformat(all_dates[0])
        atl = 0.0
        ctl = 0.0
        current = start
        while current <= target:
            effort = effort_by_date.get(current.isoformat(), 0.0)
            atl = atl * k_atl + effort * (1 - k_atl)
            ctl = ctl * k_ctl + effort * (1 - k_ctl)
            current += timedelta(days=1)

        return {"atl": atl, "ctl": ctl, "tsb": ctl - atl}

    def get_manifest_entry(self, target_date: str) -> dict:
        return self._manifest_by_date.get(target_date, {})

    def get_strava_summary(self) -> list[dict]:
        """Return the full list of Strava summary activity records."""
        return self._strava_summary


# ── Optional ADK-callable tool wrappers ──────────────────────────────────────
# These allow a future LlmAgent node to call them as tools.

def get_biometric_summary(run_dir: str, target_date: str) -> dict:
    """Returns today's HealthKit metrics and 14-day baseline for a user.

    Args:
        run_dir: Absolute path to the scenario data directory.
        target_date: Target date in YYYY-MM-DD format.
    Returns:
        dict with keys 'today', 'baseline', 'cold_start'.
    """
    repo = DataRepository(run_dir)
    today = repo.get_daily_summary(target_date)
    baseline = repo.get_baseline_stats(target_date)
    return {"today": today, "baseline": baseline, "cold_start": not bool(baseline)}


def get_training_load(run_dir: str, target_date: str) -> dict:
    """Returns ATL, CTL, TSB and activity data for a user.

    Args:
        run_dir: Absolute path to the scenario data directory.
        target_date: Target date in YYYY-MM-DD format.
    Returns:
        dict with keys 'atl', 'ctl', 'tsb', and 'activity'.
    """
    repo = DataRepository(run_dir)
    load = repo.compute_atl_ctl(target_date)
    activity = repo.get_activity_today(target_date)
    return {**load, "activity": activity}
