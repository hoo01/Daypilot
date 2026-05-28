import asyncio
import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone

logger = logging.getLogger(__name__)


@dataclass
class FreeWindow:
    start: datetime
    end: datetime
    duration_minutes: int


async def fetch_free_windows(
    user_id: str,
    start: date,
    end: date,
    calendar_service: object,  # googleapiclient.discovery.Resource
) -> list[FreeWindow]:
    """Query Google Calendar free/busy API for the user's available time
    between start and end (inclusive).

    Only called by daily_output_builder (Cloud Scheduler) and time_feasibility_agent
    in a scheduled context.  During goal intake, the Coordinator pre-fetches slots
    and delivers them in GoalAgentInput.calendar_free_slots.

    Raises CalendarUnavailable on any API failure; callers handle degraded feasibility.
    """
    from app.runtime.errors import CalendarUnavailable

    start_dt = datetime.combine(start, datetime.min.time()).replace(tzinfo=timezone.utc)
    end_dt = datetime.combine(end, datetime.max.time()).replace(tzinfo=timezone.utc)

    body = {
        "timeMin": start_dt.isoformat(),
        "timeMax": end_dt.isoformat(),
        "items": [{"id": "primary"}],
    }

    try:
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: calendar_service.freebusy().query(body=body).execute(),  # type: ignore[union-attr]
        )
    except Exception as exc:
        logger.warning("Calendar API unavailable for user %s: %s", user_id, exc)
        raise CalendarUnavailable(str(exc)) from exc

    busy_slots: list[dict] = response.get("calendars", {}).get("primary", {}).get("busy", [])
    busy_set: set[tuple[datetime, datetime]] = set()
    for slot in busy_slots:
        b_start = datetime.fromisoformat(slot["start"])
        b_end = datetime.fromisoformat(slot["end"])
        busy_set.add((b_start, b_end))

    # Build free windows by taking the complement of busy slots within the range
    free_windows: list[FreeWindow] = []
    cursor = start_dt
    for b_start, b_end in sorted(busy_set):
        if cursor < b_start:
            duration = int((b_start - cursor).total_seconds() / 60)
            if duration > 0:
                free_windows.append(FreeWindow(start=cursor, end=b_start, duration_minutes=duration))
        cursor = max(cursor, b_end)
    if cursor < end_dt:
        duration = int((end_dt - cursor).total_seconds() / 60)
        if duration > 0:
            free_windows.append(FreeWindow(start=cursor, end=end_dt, duration_minutes=duration))

    return free_windows


def sum_free_minutes(windows: list[FreeWindow]) -> int:
    """Sum total available minutes across all FreeWindow objects."""
    return sum(w.duration_minutes for w in windows)


def free_slots_to_minutes(calendar_free_slots: list[dict]) -> int:
    """Convert GoalAgentInput.calendar_free_slots list[dict] to total free minutes.

    Each dict has keys: start, end, duration_minutes (or start/end only).
    """
    total = 0
    for slot in calendar_free_slots:
        if "duration_minutes" in slot:
            total += int(slot["duration_minutes"])
        elif "start" in slot and "end" in slot:
            try:
                s = datetime.fromisoformat(slot["start"])
                e = datetime.fromisoformat(slot["end"])
                total += int((e - s).total_seconds() / 60)
            except (ValueError, TypeError):
                pass
    return total
