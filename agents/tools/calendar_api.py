from dataclasses import dataclass
from datetime import date, datetime
from typing import Any


@dataclass
class FreeWindow:
    start: datetime
    end: datetime
    duration_minutes: int


class CalendarUnavailable(Exception):
    """Raised when the Google Calendar API is unreachable or returns an error."""


async def fetch_free_windows(
    user_id: str,
    start: date,
    end: date,
    calendar_client: Any,
) -> list[FreeWindow]:
    """
    Query Google Calendar free/busy API for available time between start and end.

    Only called by daily_output_builder (Cloud Scheduler context). During intake,
    the Coordinator pre-fetches slots into GoalAgentInput.calendar_free_slots.

    Raises CalendarUnavailable on API errors; callers apply degraded feasibility.
    """
    if calendar_client is None:
        raise CalendarUnavailable("No calendar client configured")

    try:
        body = {
            "timeMin": datetime.combine(start, datetime.min.time()).isoformat() + "Z",
            "timeMax": datetime.combine(end, datetime.max.time()).isoformat() + "Z",
            "items": [{"id": "primary"}],
        }
        result = calendar_client.freebusy().query(body=body).execute()
        busy_periods = result.get("calendars", {}).get("primary", {}).get("busy", [])

        # Convert busy periods to free windows (simplified: return empty if any busy)
        # Full implementation depends on calendar_client details; this is the interface stub.
        return []
    except Exception as exc:
        raise CalendarUnavailable(str(exc)) from exc


def sum_free_minutes(windows: list[FreeWindow]) -> int:
    """Sum total available minutes across all FreeWindow objects."""
    return sum(w.duration_minutes for w in windows)
