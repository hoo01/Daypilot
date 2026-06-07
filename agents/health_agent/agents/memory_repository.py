"""
memory_repository.py — Longitudinal memory store for the PsychoBio Engine.

Provides read_history() and write_today() behind a swappable backend.
Default backend: JSONL (local files under memory/{user_id}/memory_log.jsonl).
Future backend: BigQuery — switch by setting MEMORY_BACKEND=bigquery.

Per-day record schema (also maps 1:1 to a BigQuery row):
{
  "user_id":         str,
  "date":            str,        # YYYY-MM-DD
  "readiness_score": float,      # 0–100, higher = better
  "mental_fatigue":  float,      # 0–100, higher = more strain
  "physical_fatigue": float,     # 0–100, higher = more load
  "node3_verdict":   str,        # NONE | PHYSICAL | PSYCHOLOGICAL | AMBIGUOUS
  "classification":  str,        # taxonomy label from Node 4
  "key_signals": {
    "hrv_pct_vs_baseline":        float,   # % change from 14d mean (negative = suppressed)
    "deep_sleep_pct_vs_baseline": float,   # % change from 14d mean (negative = reduced)
    "sleep_fragmented":           bool,
    "hrv_suppressed":             bool,
    "discrepancy_flag":           bool,
    "consecutive_psych_days":     int      # trailing days with PSYCHOLOGICAL/AMBIGUOUS verdict
  }
}
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Protocol, runtime_checkable

HEALTH_AGENT_ROOT = Path(__file__).parent.parent
MEMORY_DIR = HEALTH_AGENT_ROOT / "memory"


# ─────────────────────────────────────────────
# Backend protocol — both backends implement this
# ─────────────────────────────────────────────
@runtime_checkable
class MemoryBackend(Protocol):
    def read_history(self, user_id: str, n_days: int) -> list[dict]: ...
    def write_today(self, user_id: str, date: str, record: dict) -> None: ...


# ─────────────────────────────────────────────
# JSONL backend
# ─────────────────────────────────────────────
class JsonlBackend:
    """
    Stores one JSONL file per user: memory/{user_id}/memory_log.jsonl
    Each line is one JSON object (one day's record).
    Deduplication: if a record for the same date already exists, it is
    overwritten in-place rather than appended.
    """

    def _path(self, user_id: str) -> Path:
        return MEMORY_DIR / user_id / "memory_log.jsonl"

    def _load_all(self, user_id: str) -> list[dict]:
        path = self._path(user_id)
        if not path.exists():
            return []
        records = []
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue  # skip corrupted lines
        return records

    def _save_all(self, user_id: str, records: list[dict]) -> None:
        path = self._path(user_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            for record in records:
                f.write(json.dumps(record, separators=(",", ":")) + "\n")

    def read_history(self, user_id: str, n_days: int) -> list[dict]:
        """Return up to n_days records sorted by date ascending (oldest first)."""
        records = self._load_all(user_id)
        records.sort(key=lambda r: r.get("date", ""))
        return records[-n_days:] if len(records) > n_days else records

    def write_today(self, user_id: str, date: str, record: dict) -> None:
        """
        Write today's record. Computes consecutive_psych_days from history
        before writing, then deduplicates by date.
        """
        records = self._load_all(user_id)
        records.sort(key=lambda r: r.get("date", ""))

        # Compute consecutive_psych_days from the trailing history
        elevated_verdicts = {"PSYCHOLOGICAL", "AMBIGUOUS"}
        streak = 0
        for past in reversed(records):
            if past.get("date") == date:
                continue  # skip any prior entry for today (will be replaced)
            if past.get("node3_verdict") in elevated_verdicts:
                streak += 1
            else:
                break
        # If today itself is psychological/ambiguous, the streak continues
        if record.get("node3_verdict") in elevated_verdicts:
            streak += 1
        record["key_signals"]["consecutive_psych_days"] = streak

        # Deduplicate: replace existing entry for this date if present
        records = [r for r in records if r.get("date") != date]
        records.append(record)
        records.sort(key=lambda r: r.get("date", ""))

        self._save_all(user_id, records)


# ─────────────────────────────────────────────
# BigQuery backend stub
# ─────────────────────────────────────────────
class BigQueryBackend:
    """
    Production backend — reads/writes the psychobio_memory BigQuery table.

    NOT YET IMPLEMENTED. Set MEMORY_BACKEND=bigquery only after the team
    has provisioned the table and wired service account credentials.

    BigQuery table schema (mirrors the JSONL record 1:1):
      user_id           STRING    NOT NULL
      date              DATE      NOT NULL
      readiness_score   FLOAT64
      mental_fatigue    FLOAT64
      physical_fatigue  FLOAT64
      node3_verdict     STRING
      classification    STRING
      hrv_pct_vs_baseline        FLOAT64
      deep_sleep_pct_vs_baseline FLOAT64
      sleep_fragmented  BOOL
      hrv_suppressed    BOOL
      discrepancy_flag  BOOL
      consecutive_psych_days INT64
      inserted_at       TIMESTAMP

    Switch: set env var MEMORY_BACKEND=bigquery.
    No node code changes required — same interface as JsonlBackend.
    """

    def read_history(self, user_id: str, n_days: int) -> list[dict]:
        raise NotImplementedError(
            "BigQuery backend not yet implemented. "
            "Set MEMORY_BACKEND=jsonl or implement BigQueryBackend.read_history()."
        )

    def write_today(self, user_id: str, date: str, record: dict) -> None:
        raise NotImplementedError(
            "BigQuery backend not yet implemented. "
            "Set MEMORY_BACKEND=jsonl or implement BigQueryBackend.write_today()."
        )


# ─────────────────────────────────────────────
# Public interface — one class, swappable backend
# ─────────────────────────────────────────────
class MemoryRepository:
    """
    Public interface for the memory layer.

    Backend selection (in priority order):
      1. `backend` constructor argument (explicit override)
      2. MEMORY_BACKEND environment variable
      3. Default: "jsonl"

    Usage:
        mem = MemoryRepository()                    # uses MEMORY_BACKEND env var
        mem = MemoryRepository(backend="jsonl")     # explicit JSONL
        mem = MemoryRepository(backend="bigquery")  # explicit BigQuery (stub)

        history = mem.read_history("user_pwb", n_days=14)
        mem.write_today("user_pwb", "2026-05-29", record)
    """

    def __init__(self, backend: str | None = None):
        selected = backend or os.environ.get("MEMORY_BACKEND", "jsonl")
        if selected == "jsonl":
            self._backend: MemoryBackend = JsonlBackend()
        elif selected == "bigquery":
            self._backend = BigQueryBackend()
        else:
            raise ValueError(
                f"Unknown MEMORY_BACKEND '{selected}'. Valid options: jsonl, bigquery."
            )
        self._backend_name = selected

    @property
    def backend_name(self) -> str:
        return self._backend_name

    def read_history(self, user_id: str, n_days: int = 14) -> list[dict]:
        """Return up to n_days prior records, sorted oldest-first."""
        return self._backend.read_history(user_id, n_days)

    def write_today(self, user_id: str, date: str, record: dict) -> None:
        """Persist today's record. Overwrites any existing entry for this date."""
        self._backend.write_today(user_id, date, record)
