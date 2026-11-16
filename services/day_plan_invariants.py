"""§5.3 invariants — pure checks, shared by DayPlanService (before every write) and
the LLM② generators (to decide whether to retry).

Each check returns a list of human-readable violations; an empty list means valid.
"""
from __future__ import annotations

import re
from datetime import date as _date, datetime, timedelta
from typing import Iterable

from schemas.schedule import CalendarEvent, ScheduleInput, ScheduleTask

ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")

# A day's plan may run past midnight (late focus windows, an overnight sleep block).
# Tasks may *start* on the next calendar day only before NIGHT_SPILLOVER_END_HOUR, and
# must *end* no later than SPILLOVER_END_LIMIT_HOUR on the next day.
NIGHT_SPILLOVER_END_HOUR = 6
SPILLOVER_END_LIMIT_HOUR = 12


def _parse(ts: str) -> datetime | None:
    if not isinstance(ts, str) or not ISO_RE.match(ts):
        return None
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


def validate_tasks(tasks: Iterable[ScheduleTask], target_date: str) -> list[str]:
    """Format, date range, non-empty titles, and no overlaps."""
    violations: list[str] = []
    day = _date.fromisoformat(target_date)
    next_day = day + timedelta(days=1)
    spill_limit = datetime(next_day.year, next_day.month, next_day.day, NIGHT_SPILLOVER_END_HOUR)
    end_limit = datetime(next_day.year, next_day.month, next_day.day, SPILLOVER_END_LIMIT_HOUR)
    day_start = datetime(day.year, day.month, day.day)

    timed: list[tuple[datetime, datetime, ScheduleTask]] = []
    for t in tasks:
        label = f'"{t.title}"'
        if not (t.title or "").strip():
            violations.append(f"task {t.task_id!r} has an empty title")
        start, end = _parse(t.start_time), _parse(t.end_time)
        if start is None or end is None:
            violations.append(f"{label} has a non-ISO timestamp ({t.start_time!r} → {t.end_time!r})")
            continue
        if end <= start:
            violations.append(f"{label} ends before it starts")
            continue
        if not (day_start <= start < spill_limit) or end > end_limit:
            violations.append(f"{label} is outside the target date {target_date}")
            continue
        if start.date() == next_day and start.hour >= NIGHT_SPILLOVER_END_HOUR:
            violations.append(f"{label} is outside the target date {target_date}")
            continue
        timed.append((start, end, t))

    timed.sort(key=lambda x: x[0])
    for i, (s1, e1, a) in enumerate(timed):
        for s2, e2, b in timed[i + 1:]:
            if s2 >= e1:
                break
            if a.type == "calendar_event" and b.type == "calendar_event":
                # Both are the user's real commitments (their own calendar double-books);
                # dropping either would lose user data, so this pair is tolerated.
                continue
            violations.append(f'"{a.title}" overlaps "{b.title}"')
    return violations


def _block_key(b: ScheduleTask | CalendarEvent) -> tuple:
    return (b.title, b.start_time, b.end_time)


def missing_fixed_blocks(tasks: Iterable[ScheduleTask], fixed: Iterable[ScheduleTask | CalendarEvent]) -> list[str]:
    """Every fixed block (calendar event / locked block) must appear verbatim:
    same title, start, end and — when the fixed block has one — location."""
    by_key: dict[tuple, list[ScheduleTask]] = {}
    for t in tasks:
        by_key.setdefault(_block_key(t), []).append(t)
    violations = []
    for b in fixed:
        candidates = by_key.get(_block_key(b), [])
        if not candidates:
            violations.append(f'fixed block "{b.title}" ({b.start_time} → {b.end_time}) is missing or was altered')
            continue
        if b.location and not any(c.location == b.location for c in candidates):
            violations.append(f'fixed block "{b.title}" lost its location {b.location!r}')
    return violations


def calendar_event_to_task(e: CalendarEvent) -> ScheduleTask:
    return ScheduleTask(
        task_id=f"calendar-{e.id}",
        title=e.title,
        start_time=e.start_time,
        end_time=e.end_time,
        type="calendar_event",
        location=e.location,
    )


def _still_relevant(block: ScheduleTask, target_date: str, now: datetime) -> bool:
    """On today's plan, blocks that already ended need not be (re)scheduled."""
    if target_date != now.date().isoformat():
        return True
    end = _parse(block.end_time)
    return end is None or end > now


def fixed_blocks_for(inp: ScheduleInput, now: datetime) -> list[ScheduleTask]:
    """The blocks a generated plan for `inp` must preserve: locked blocks, plus calendar
    events that don't collide with a locked block (locked wins, as in _enforce_constraints)."""
    locked = list(inp.locked_blocks)
    locked_iv = [(_parse(b.start_time), _parse(b.end_time)) for b in locked]

    def collides(e: CalendarEvent) -> bool:
        s, en = _parse(e.start_time), _parse(e.end_time)
        if s is None or en is None:
            return False
        return any(ls is not None and le is not None and s < le and ls < en for ls, le in locked_iv)

    blocks = locked + [calendar_event_to_task(e) for e in inp.calendar_events if not collides(e)]
    return [b for b in blocks if _still_relevant(b, inp.date, now)]


def fixed_blocks_for_adjustment(active_tasks: Iterable[ScheduleTask], new_events: Iterable[CalendarEvent],
                                target_date: str, now: datetime) -> list[ScheduleTask]:
    """An adjustment must keep the active plan's calendar events and add the new ones."""
    blocks = [t for t in active_tasks if t.type == "calendar_event"]
    blocks += [calendar_event_to_task(e) for e in new_events]
    return [b for b in blocks if _still_relevant(b, target_date, now)]
