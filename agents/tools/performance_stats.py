"""
In-process rolling-window stats for DayPilot self-monitoring.

chat_handler and health_tools record into this module;
check_performance reads from it. No external dependency.
"""

import time
from collections import deque

_chat: deque = deque(maxlen=200)    # (monotonic_ts, duration_ms, had_error)
_health: deque = deque(maxlen=200)  # (monotonic_ts, duration_ms)


def record_chat(duration_ms: float, had_error: bool = False) -> None:
    _chat.append((time.monotonic(), duration_ms, had_error))


def record_health(duration_ms: float) -> None:
    _health.append((time.monotonic(), duration_ms))


def get_stats(window_seconds: float = 3600.0) -> dict:
    now = time.monotonic()
    chat_rows   = [(d, e) for t, d, e in _chat   if now - t < window_seconds]
    health_rows = [d      for t, d    in _health  if now - t < window_seconds]

    chat_avg   = sum(d for d, _ in chat_rows) / len(chat_rows) if chat_rows else None
    health_avg = sum(health_rows) / len(health_rows) if health_rows else None
    errors     = sum(1 for _, e in chat_rows if e)

    return {
        "chat_count":    len(chat_rows),
        "chat_avg_ms":   chat_avg,
        "health_count":  len(health_rows),
        "health_avg_ms": health_avg,
        "error_count":   errors,
    }
