"""Builders for DayPlan / schedule tests. Pure data, no I/O."""
from __future__ import annotations

from datetime import datetime

from schemas.schedule import CalendarEvent, ScheduleOutput, ScheduleStrategy, ScheduleTask

DAY = "2026-11-20"          # a fixed future date so "now" filtering never kicks in
NEXT_DAY = "2026-11-21"
FIXED_NOW = datetime(2026, 11, 19, 8, 0, 0)


def ts(hhmm: str, day: str = DAY) -> str:
    return f"{day}T{hhmm}:00"


def task(title: str, start: str, end: str, *, type: str = "deep_work", day: str = DAY,
         task_id: str | None = None, location: str | None = None) -> ScheduleTask:
    return ScheduleTask(
        task_id=task_id or f"{title.lower().replace(' ', '-')}-{start}",
        title=title,
        start_time=ts(start, day),
        end_time=ts(end, day),
        type=type,
        location=location,
    )


def strategy(name: str, tasks: list[ScheduleTask]) -> ScheduleStrategy:
    return ScheduleStrategy(name=name, description=f"{name} plan", tasks=tasks)


def three_strategies(day: str = DAY) -> list[ScheduleStrategy]:
    return [
        strategy("Most Productive", [
            task("Leetcode Practice", "09:00", "11:00", day=day),
            task("Lunch", "12:00", "13:00", type="meal", day=day),
        ]),
        strategy("Most Relaxed", [
            task("Reading", "10:00", "11:00", type="personal", day=day),
            task("Walk", "15:00", "16:00", type="exercise", day=day),
        ]),
        strategy("Fastest", [
            task("Leetcode Practice", "08:00", "09:30", day=day),
        ]),
    ]


def schedule_output(day: str = DAY, top: str = "Most Productive",
                    strategies: list[ScheduleStrategy] | None = None) -> ScheduleOutput:
    return ScheduleOutput(date=day, strategies=strategies or three_strategies(day), top_recommendation=top)


def cal_event(title: str, start: str, end: str, *, day: str = DAY, location: str | None = None,
              id: str | None = None) -> CalendarEvent:
    return CalendarEvent(id=id or title, title=title, start_time=ts(start, day), end_time=ts(end, day),
                         location=location)
