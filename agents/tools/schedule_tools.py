import json
import re
from datetime import datetime, date, timedelta
from google import genai
from config import settings
from db import get_db
from db.collections import Collections
from agents.memory import MemoryAgent
from schemas.schedule import (
    ScheduleInput, ScheduleOutput, ScheduleTask, ScheduleStrategy,
    CalendarEvent, UserPreferences,
)
from telemetry.instrument import traced_tool
from schemas.health import HealthOutput


# ─────────────────────────────────────────────────────────
# Helpers (adapted from Jingyuan's Schedule Planning Agent)
# ─────────────────────────────────────────────────────────

def _naive_dt(ts: str) -> datetime:
    ts = ts.replace("_", "-").replace("Z", "+00:00").strip()
    # ISO 8601 allows "24:00:00" to mean midnight at the start of the next day,
    # but Python's fromisoformat rejects it — normalize before parsing.
    m = re.match(r"^(\d{4}-\d{2}-\d{2})T24:00:00(\.\d+)?$", ts)
    if m:
        next_day = date.fromisoformat(m.group(1)) + timedelta(days=1)
        return datetime(next_day.year, next_day.month, next_day.day)
    try:
        return datetime.fromisoformat(ts).replace(tzinfo=None)
    except ValueError:
        pass
    # Handle 12-hour formats like "7:30pm", "7:30 PM", "7:30am"
    m = re.match(r"^(\d{1,2}):(\d{2})\s*(am|pm)$", ts.lower())
    if m:
        hour, minute, ampm = int(m.group(1)), int(m.group(2)), m.group(3)
        if ampm == "pm" and hour != 12:
            hour += 12
        elif ampm == "am" and hour == 12:
            hour = 0
        today = datetime.utcnow().date()
        return datetime(today.year, today.month, today.day, hour, minute)
    raise ValueError(f"Cannot parse timestamp: {ts!r}")


def _times_overlap(s1: str, e1: str, s2: str, e2: str) -> bool:
    return _naive_dt(s1) < _naive_dt(e2) and _naive_dt(s2) < _naive_dt(e1)


def _minutes_between(start: str, end: str) -> float:
    return (_naive_dt(end) - _naive_dt(start)).total_seconds() / 60


def _extract_json(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)
    return raw.strip()


def _normalize_timestamp(ts: str, target_date: str) -> str:
    ts = ts.replace("_", "-")  # Gemini occasionally uses underscores instead of dashes
    if "T" in ts:
        date_part, time_part = ts.split("T", 1)
        # Only trust the date part if it's actually a valid YYYY-MM-DD value
        if re.match(r"^\d{4}-\d{2}-\d{2}$", date_part):
            # ISO 8601 allows "24:00:00" for midnight at the start of the next
            # day, but downstream parsers (Python, JS Date) reject it.
            if re.match(r"^24:00:00(\.\d+)?$", time_part):
                next_day = date.fromisoformat(date_part) + timedelta(days=1)
                return f"{next_day.isoformat()}T00:00:00"
            return ts
        # LLM put natural language before the T (e.g. "this afternoon after 4 pmT18:00:00")
        return f"{target_date}T{time_part}"
    if re.match(r"^\d{4}-\d{2}-\d{2}", ts):
        return ts
    if re.match(r"^\d{1,2}:\d{2}(:\d{2})?$", ts):
        hh, _, rest = ts.partition(":")
        time_part = f"{int(hh):02d}:{rest}"
        if len(time_part) == 5:
            time_part += ":00"
        return f"{target_date}T{time_part}"
    # 12-hour formats like "2PM", "2 pm", "2:00 PM", "2:00pm"
    m = re.match(r"^(\d{1,2})(?::(\d{2}))?\s*(am|pm)$", ts.strip().lower())
    if m:
        hour, minute, ampm = int(m.group(1)), int(m.group(2) or 0), m.group(3)
        if ampm == "pm" and hour != 12:
            hour += 12
        elif ampm == "am" and hour == 12:
            hour = 0
        return f"{target_date}T{hour:02d}:{minute:02d}:00"
    return ts


def _fix_year(ts: str, target_year: str) -> str:
    year = ts[:4]
    if year.isdigit() and abs(int(year) - int(target_year)) == 1:
        return target_year + ts[4:]
    return ts


def _normalize_tasks(tasks: list[ScheduleTask], target_date: str) -> list[ScheduleTask]:
    target_year = target_date.split("-")[0]
    return [
        t.model_copy(update={
            "start_time": _fix_year(_normalize_timestamp(t.start_time, target_date), target_year),
            "end_time": _fix_year(_normalize_timestamp(t.end_time, target_date), target_year),
        })
        for t in tasks
    ]


def _merge_short_deep_work(tasks: list[ScheduleTask]) -> list[ScheduleTask]:
    result: list[ScheduleTask] = []
    for task in tasks:
        if task.type != "deep_work":
            result.append(task)
            continue
        if _minutes_between(task.start_time, task.end_time) >= 30:
            result.append(task)
        elif result and result[-1].type == "deep_work":
            prev = result[-1]
            result[-1] = prev.model_copy(update={"end_time": task.end_time})
    return result


# ─────────────────────────────────────────────────────────
# Prompt builder (adapted from Jingyuan's _build_prompt)
# ─────────────────────────────────────────────────────────

def _build_prompt(inp: ScheduleInput, goal_context: dict | None = None,
                  focus_tasks: list[str] | None = None, notes: list[str] | None = None) -> str:
    prefs = inp.user_preferences
    health = inp.health
    goals = inp.goals

    pref_work = prefs.preferred_work_hours if prefs else "late_night"
    pref_commute = prefs.commute_minutes if prefs else 30
    pref_break = prefs.break_frequency if prefs else 90

    health_energy = health.energy_level if health else "medium"
    health_focus = health.focus_window if health else "9PM-1AM"
    health_cognitive = health.cognitive_load_score if health else 0.65
    health_avoid = ", ".join(health.avoid_tasks) if health and health.avoid_tasks else "(none)"

    goal_urgency = goals.urgency if goals else "medium"
    goal_feasibility = goals.feasibility_score if goals else 1.0
    goal_feasibility_note = goals.feasibility_note if goals and goals.feasibility_note else ""

    if goals and goals.daily_sub_tasks:
        lines = "\n".join(
            f'- "{t.title}" ({t.estimated_minutes} min, priority: {t.priority}, '
            f'preferred: {t.preferred_time_of_day}, deadline: {t.deadline}, can_split: {t.can_split})'
            for t in goals.daily_sub_tasks
        )
        goal_sub_tasks_section = f"Goal sub-tasks for today:\n{lines}"
    elif goal_context:
        summary = goal_context.get("summary", "")
        blocks = goal_context.get("suggested_blocks", [])
        goal_names = [g.get("name", "") for g in goal_context.get("goals", []) if g.get("name")]
        parts = []
        if goal_names:
            parts.append(f"Active goals: {', '.join(goal_names)}")
        if blocks:
            parts.append(f"Suggested blocks: {'; '.join(blocks)}")
        if summary:
            parts.append(f"Summary: {summary}")
        goal_sub_tasks_section = "\n".join(parts) if parts else "(no goal sub-tasks for today)"
    else:
        goal_sub_tasks_section = "(no goal sub-tasks for today)"

    if inp.locked_blocks:
        lock_lines = [
            f"- LOCKED: {b.title} | {b.start_time} → {b.end_time} | type: {b.type}"
            for b in inp.locked_blocks
        ]
        locked_section = (
            "These blocks MUST appear in the output EXACTLY as listed.\n"
            "Only schedule new tasks in the gaps BETWEEN these locked blocks.\n\n"
            + "\n".join(lock_lines)
        )
    else:
        locked_section = "(no locked blocks — full day is plannable)"

    calendar_section = (
        "\n".join(
            f"- {e.title}: {e.start_time} → {e.end_time}" + (f" @ {e.location}" if e.location else "")
            for e in inp.calendar_events
        ) or "(none)"
    )

    focus_section = (
        "\n".join(f'- "{t}"' for t in focus_tasks)
        if focus_tasks else "(none)"
    )
    notes_section = "\n".join(f"- {n}" for n in notes) if notes else "(none)"

    now_dt = datetime.now()
    is_today = inp.date == date.today().isoformat()
    tomorrow_date = (date.fromisoformat(inp.date) + timedelta(days=1)).isoformat()
    current_time_section = (
        f"Current local time: {now_dt.strftime('%H:%M')} (the schedule is being generated RIGHT NOW). "
        f"Any task whose entire window is before {now_dt.strftime('%H:%M')} on {inp.date} has ALREADY HAPPENED — "
        f"do not schedule it. If the focus window or sleep schedule extends past midnight into the early "
        f"hours of the NEXT calendar day, those tasks belong to {tomorrow_date} (e.g. \"00:00\"-\"02:00\" "
        f"after midnight tonight is \"{tomorrow_date}T00:00:00\"-\"{tomorrow_date}T02:00:00\", NOT "
        f"\"{inp.date}T00:00:00\", because {inp.date}'s midnight-to-morning window is already in the past."
        if is_today
        else f"Current local time: {now_dt.strftime('%H:%M')} on {date.today().isoformat()} "
             f"(this schedule is for a FUTURE date, {inp.date}, so plan the full day normally)"
    )

    return f"""You are DayPilot's Schedule Planning Agent.

# PRIORITY ORDER (highest to lowest)
1. LOCKED BLOCKS — never modify, rename, skip, or split them
2. CALENDAR EVENTS — immutable, never shift their times
3. GOAL TASKS — fill remaining gaps with goal-related work

Generate exactly 3 daily schedule strategies for a student.

## User Context
Date: {inp.date}
{current_time_section}
Preferred work hours: {pref_work}
Commute time: {pref_commute} minutes
Break frequency: every {pref_break} minutes

## Health & Energy
Energy level: {health_energy}
Best focus window: {health_focus}
Cognitive load score: {health_cognitive} (0=exhausted, 1=peak)
Avoid: {health_avoid}

## Goal Status
Urgency: {goal_urgency}
Feasibility: {goal_feasibility:.2f}{f" — {goal_feasibility_note}" if goal_feasibility_note else ""}
{goal_sub_tasks_section}

## Locked Blocks (DO NOT MOVE OR MODIFY)
{locked_section}

## Fixed Calendar Events (IMMUTABLE — never shift times even by minutes)
{calendar_section}

## Tasks that must be scheduled today (use these exact titles, one task each)
{focus_section}

## Other things happening on this date (no fixed time — mention in reasoning if relevant)
{notes_section}

## Rules
1. Calendar events are IMMUTABLE — never move, shift, or rename them
2. Schedule deep work during the user's focus window
3. If Date is today (see "Current local time" above), the schedule covers ONLY from the
   current local time through bedtime — do NOT include tasks or calendar events whose
   end_time is before the current local time. If Date is a future date, cover the full
   day from wake-up to sleep.
4. Include at least 2 breaks per strategy
5. NO OVERLAPPING TASKS: All tasks within a strategy MUST be sorted in chronological order by start_time. Each task's start_time must be >= the previous task's end_time. No two tasks may occupy the same time slot, even partially. Verify every task pair before outputting.
6. "Most Productive" maximizes goal progress; "Most Relaxed" minimizes cognitive load; "Fastest" completes must-dos in minimum time
7. Use ONLY these task types: deep_work, routine, break, commute, exercise, study, meal, personal, preparation, sleep, calendar_event
8. top_recommendation MUST be exactly one of: "Most Productive", "Most Relaxed", or "Fastest"
9. Task titles MUST use the specific goal or activity name — never generic labels like "Study Session (Goal Task)" or "Deep Work Block". If the goal is Leetcode, write "Leetcode Practice". If it's writing, write "Writing Session". Use the exact activity name.
10. Calendar event titles MUST be copied verbatim from the calendar_events input. Never rename them to generic labels like "Event", "Appointment", or "Meeting".
11. CRITICAL: All start_time and end_time MUST be full ISO 8601 strings, e.g. "{inp.date}T09:00:00"

## Output Format (valid JSON only)
{{
  "strategies": [
    {{
      "name": "Most Productive",
      "description": "...",
      "tasks": [
        {{
          "title": "...",
          "start_time": "{inp.date}T09:00:00",
          "end_time": "{inp.date}T10:30:00",
          "type": "deep_work",
          "location": null,
          "notes": null
        }}
      ],
      "total_focus_hours": 4.5,
      "reasoning": "..."
    }}
  ],
  "top_recommendation": "Most Productive",
  "warnings": []
}}

Generate all 3 strategies now."""


# ─────────────────────────────────────────────────────────
# Post-processing
# ─────────────────────────────────────────────────────────

def _enforce_constraints(output: ScheduleOutput, inp: ScheduleInput) -> ScheduleOutput:
    locked = inp.locked_blocks

    # Locked blocks take precedence — drop calendar events that overlap them
    if locked:
        locked_intervals = []
        for lb in locked:
            try:
                locked_intervals.append((_naive_dt(lb.start_time), _naive_dt(lb.end_time)))
            except Exception:
                pass

        def _overlaps_any_locked(event) -> bool:
            try:
                e_start = _naive_dt(event.start_time)
                e_end = _naive_dt(event.end_time)
            except Exception:
                return False
            for lb_start, lb_end in locked_intervals:
                if e_start < lb_end and lb_start < e_end:
                    return True
            return False

        filtered_calendar = [e for e in inp.calendar_events if not _overlaps_any_locked(e)]
    else:
        filtered_calendar = list(inp.calendar_events)

    replan_dt = _naive_dt(inp.replan_from_time) if inp.replan_from_time else None
    locked_task_ids: set[str] = {lb.task_id for lb in locked if lb.task_id}
    locked_title_time: set[tuple] = {(lb.title, _naive_dt(lb.start_time)) for lb in locked}
    cal_title_time: set[tuple] = {(e.title, _naive_dt(e.start_time)) for e in filtered_calendar}
    cal_location_map: dict = {
        (e.title, _naive_dt(e.start_time)): e.location for e in filtered_calendar
    }

    fixed = []
    for strategy in output.strategies:
        tasks = list(strategy.tasks)

        # Inject locked blocks — remove overlapping generated tasks first
        if locked:
            tasks = [
                t for t in tasks
                if not any(
                    _times_overlap(t.start_time, t.end_time, lb.start_time, lb.end_time)
                    for lb in locked
                )
            ]
            tasks.extend(locked)

        # Strip Gemini-invented tasks before replan_from_time
        if replan_dt is not None:
            def _allowed_before_replan(t: ScheduleTask) -> bool:
                try:
                    t_dt = _naive_dt(t.start_time)
                except Exception:
                    return True
                if t_dt >= replan_dt:
                    return True
                if t.task_id in locked_task_ids:
                    return True
                if (t.title, t_dt) in locked_title_time:
                    return True
                if (t.title, t_dt) in cal_title_time:
                    return True
                return False
            tasks = [t for t in tasks if _allowed_before_replan(t)]

        # Restore frozen calendar events before replan_from_time
        if replan_dt is not None and filtered_calendar:
            for event in [e for e in filtered_calendar if _naive_dt(e.start_time) < replan_dt]:
                try:
                    e_dt = _naive_dt(event.start_time)
                except Exception:
                    continue
                exact = next((i for i, t in enumerate(tasks)
                              if t.title == event.title and _naive_dt(t.start_time) == e_dt), None)
                if exact is not None:
                    tasks[exact] = tasks[exact].model_copy(update={
                        "start_time": event.start_time, "end_time": event.end_time,
                        "title": event.title, "location": event.location,
                    })
                    continue
                loose = next((i for i, t in enumerate(tasks)
                              if t.title == event.title and t.type == "calendar_event"), None)
                if loose is not None:
                    tasks[loose] = tasks[loose].model_copy(update={
                        "start_time": event.start_time, "end_time": event.end_time,
                        "title": event.title, "location": event.location,
                    })
                    continue
                tasks.append(ScheduleTask(
                    task_id=f"calendar-frozen-{event.id}",
                    title=event.title, start_time=event.start_time,
                    end_time=event.end_time, type="calendar_event", location=event.location,
                ))

        # Restore original location for calendar events
        if cal_location_map:
            corrected = []
            for t in tasks:
                if t.type == "calendar_event":
                    try:
                        key = (t.title, _naive_dt(t.start_time))
                        if key in cal_location_map and t.location != cal_location_map[key]:
                            t = t.model_copy(update={"location": cal_location_map[key]})
                    except Exception:
                        pass
                corrected.append(t)
            tasks = corrected

        # Calendar events are immutable — drop any generated task the LLM
        # double-booked on top of one (e.g. "Personal Time" overlapping "ML class")
        cal_tasks = [t for t in tasks if t.type == "calendar_event"]
        if cal_tasks:
            tasks = [
                t for t in tasks
                if t.type == "calendar_event" or not any(
                    _times_overlap(t.start_time, t.end_time, c.start_time, c.end_time)
                    for c in cal_tasks
                )
            ]

        tasks.sort(key=lambda t: t.start_time)
        fixed.append(strategy.model_copy(update={"tasks": tasks}))

    return output.model_copy(update={"strategies": fixed})


def _resolve_overlaps(tasks: list[ScheduleTask]) -> list[ScheduleTask]:
    """
    Ensure no two tasks overlap.  When a conflict is found, the earlier task's
    end_time is trimmed to the later task's start_time.  If trimming would leave
    a task shorter than MIN_DURATION_MIN it is dropped instead.

    Tie-breaking when two tasks share the same start_time: the LONGER task is
    sorted first so that it gets trimmed/dropped in favour of the shorter,
    more-specific task — which is usually the correct one.
    """
    MIN_DURATION_MIN = 15

    def _sort_key(t: ScheduleTask):
        try:
            s = _naive_dt(t.start_time)
            dur = (_naive_dt(t.end_time) - s).total_seconds()
        except Exception:
            return (datetime.max, 0.0)
        return (s, -dur)   # asc start, desc duration

    sorted_tasks = sorted(tasks, key=_sort_key)
    result: list[ScheduleTask] = []

    for task in sorted_tasks:
        if not result:
            result.append(task)
            continue

        prev = result[-1]
        try:
            prev_end   = _naive_dt(prev.end_time)
            curr_start = _naive_dt(task.start_time)
        except Exception:
            result.append(task)
            continue

        if prev_end > curr_start:
            # Overlap: trim the earlier task's end to the current task's start
            try:
                prev_start = _naive_dt(prev.start_time)
                new_dur_min = (curr_start - prev_start).total_seconds() / 60
            except Exception:
                new_dur_min = MIN_DURATION_MIN

            if new_dur_min >= MIN_DURATION_MIN:
                result[-1] = prev.model_copy(update={"end_time": task.start_time})
            else:
                result.pop()   # too short after trimming — remove it

        result.append(task)

    return result


def _validate_and_fix(output: ScheduleOutput, inp: ScheduleInput) -> ScheduleOutput:
    import re as _re
    warnings: list[str] = []
    fixed = []

    for strategy in output.strategies:
        tasks = _normalize_tasks(strategy.tasks, inp.date)
        tasks = _merge_short_deep_work(tasks)
        tasks = _resolve_overlaps(tasks)

        # Detect calendar overlaps
        cal = [t for t in tasks if t.type == "calendar_event"]
        for i in range(len(cal)):
            for j in range(i + 1, len(cal)):
                a, b = cal[i], cal[j]
                if _times_overlap(a.start_time, a.end_time, b.start_time, b.end_time):
                    warnings.append(f'[{strategy.name}] "{a.title}" overlaps "{b.title}"')

        # Detect meal timing issues
        for t in tasks:
            if t.type != "meal":
                continue
            m = _re.search(r"T(\d{2}):", t.start_time)
            hour = int(m.group(1)) if m else 0
            title = t.title.lower()
            if "lunch" in title and not (11 <= hour <= 14):
                warnings.append(f'[{strategy.name}] "{t.title}" at {hour}:00 (expected 11-14)')
            if "dinner" in title and not (17 <= hour <= 21):
                warnings.append(f'[{strategy.name}] "{t.title}" at {hour}:00 (expected 17-21)')

        # Detect time order issues
        for i in range(1, len(tasks)):
            prev, curr = tasks[i - 1], tasks[i]
            if _naive_dt(curr.start_time) < _naive_dt(prev.start_time):
                warnings.append(f'[{strategy.name}] "{curr.title}" starts before "{prev.title}"')

        # Detect missing locked blocks
        for lb in inp.locked_blocks:
            if not any(t.title == lb.title and t.start_time == lb.start_time for t in tasks):
                warnings.append(f'[{strategy.name}] Locked block "{lb.title}" was modified or removed')

        fixed.append(strategy.model_copy(update={"tasks": tasks}))

    return output.model_copy(update={
        "strategies": fixed,
        "warnings": output.warnings + warnings,
    })


# ─────────────────────────────────────────────────────────
# Fixed-block placement (shared with realtime_tools)
# ─────────────────────────────────────────────────────────

def _key(t) -> tuple:
    return (t.title, t.start_time, t.end_time)


def _overlaps(a: ScheduleTask, b: ScheduleTask) -> bool:
    try:
        return _times_overlap(a.start_time, a.end_time, b.start_time, b.end_time)
    except Exception:
        return False  # unparsable — left for validation to reject


def _place_fixed_blocks(tasks: list[ScheduleTask], fixed: list[ScheduleTask]) -> list[ScheduleTask]:
    """Deterministically guarantee invariant 2: every fixed block appears verbatim.

    Generated tasks colliding with a fixed block (including renamed/moved copies of it)
    are dropped; remaining generated tasks are de-overlapped; then the canonical fixed
    blocks are inserted (keeping the LLM's task_id when it reproduced one exactly).
    """
    if not fixed:
        return sorted(_resolve_overlaps(tasks), key=lambda t: t.start_time)
    fixed_keys = {_key(b) for b in fixed}
    matched_ids = {_key(t): t.task_id for t in tasks if _key(t) in fixed_keys}
    generated = [t for t in tasks if _key(t) not in fixed_keys and not any(_overlaps(t, b) for b in fixed)]
    generated = _resolve_overlaps(generated)
    canon = [b.model_copy(update={"task_id": matched_ids.get(_key(b), b.task_id)}) for b in fixed]
    return sorted(generated + canon, key=lambda t: t.start_time)


def _unique_task_ids(tasks: list[ScheduleTask]) -> list[ScheduleTask]:
    seen: set[str] = set()
    out = []
    for i, t in enumerate(tasks):
        tid = t.task_id or f"task-{i + 1}"
        while tid in seen:
            tid = f"{tid}-{i + 1}"
        seen.add(tid)
        out.append(t if tid == t.task_id else t.model_copy(update={"task_id": tid}))
    return out


# ─────────────────────────────────────────────────────────
# LLM② boundary — flat schema handed to Gemini as response_schema
# ─────────────────────────────────────────────────────────
# The domain models (ScheduleOutput etc.) carry defaults, which end up as "default"
# keywords in the generated schema; these LLM-facing models avoid that and constrain
# enums, then get mapped onto the domain models by code.

import logging as _logging
from typing import Awaitable, Callable, Literal

from pydantic import BaseModel

_log = _logging.getLogger(__name__)

import http_client as _http_client
_genai_client = genai.Client(
    api_key=settings.gemini_api_key,
    http_options=genai.types.HttpOptions(httpx_async_client=_http_client.shared_async_client()),
)

TaskType = Literal["deep_work", "routine", "break", "commute", "exercise", "study", "meal",
                   "personal", "preparation", "sleep", "calendar_event"]
StrategyName = Literal["Most Productive", "Most Relaxed", "Fastest"]


class LLMTask(BaseModel):
    title: str
    start_time: str
    end_time: str
    type: TaskType
    location: str | None
    notes: str | None


class LLMStrategy(BaseModel):
    name: StrategyName
    description: str
    tasks: list[LLMTask]
    total_focus_hours: float
    reasoning: str


class ScheduleLLMSchema(BaseModel):
    strategies: list[LLMStrategy]
    top_recommendation: StrategyName
    warnings: list[str]


LLMJsonCall = Callable[[str, str, type], Awaitable[str]]
MAX_ATTEMPTS = 2   # first try + one retry (§6.2)


async def _llm_json(model: str, prompt: str, schema: type) -> str:
    """Default LLM transport: Gemini with a response_schema. Tests inject a stub instead."""
    response = await _genai_client.aio.models.generate_content(
        model=model,
        contents=prompt,
        config=genai.types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=schema,
            thinking_config=genai.types.ThinkingConfig(thinking_budget=0),
        ),
    )
    return response.text or ""


def _retry_prompt(base: str, problems: list[str]) -> str:
    listed = "\n".join(f"- {p}" for p in problems[:12])
    return (f"{base}\n\n## Your previous output was rejected\n{listed}\n"
            f"Fix every problem above and return the complete corrected JSON object.")


def _llm_to_output(parsed: ScheduleLLMSchema, target_date: str, now: datetime) -> ScheduleOutput:
    strategies: list[ScheduleStrategy] = []
    for s in parsed.strategies:
        if any(x.name == s.name for x in strategies):
            continue  # keep the first strategy of each name
        slug = s.name.lower().replace(" ", "-")
        tasks = [
            ScheduleTask(task_id=f"{slug}-{i + 1}", title=t.title.strip(), start_time=t.start_time,
                         end_time=t.end_time, type=t.type, location=t.location, notes=t.notes)
            for i, t in enumerate(s.tasks)
        ]
        strategies.append(ScheduleStrategy(name=s.name, description=s.description, tasks=tasks,
                                           total_focus_hours=s.total_focus_hours, reasoning=s.reasoning))
    names = [x.name for x in strategies]
    top = parsed.top_recommendation if parsed.top_recommendation in names else (names[0] if names else "")
    return ScheduleOutput(date=target_date, strategies=strategies, top_recommendation=top,
                          warnings=list(parsed.warnings), generated_at=now.isoformat(timespec="seconds"))


async def generate_schedule(
    inp: ScheduleInput,
    *,
    goal_context: dict | None = None,
    focus_tasks: list[str] | None = None,
    notes: list[str] | None = None,
    llm: LLMJsonCall | None = None,
    now: Callable[[], datetime] | None = None,
) -> ScheduleOutput:
    """LLM② for plans — a pure function: no DB writes.

    Calls the LLM with ScheduleLLMSchema, repairs what code can repair (timestamps,
    overlaps, fixed blocks), validates the §5.3 invariants, retries once with the
    problems fed back, and raises GenerationFailed if it still isn't valid. It never
    returns a fallback schedule.
    """
    from schemas.day_plan import GenerationFailed
    from services.day_plan_invariants import fixed_blocks_for, missing_fixed_blocks, validate_tasks

    call = llm or _llm_json
    clock = now or datetime.now
    fixed = fixed_blocks_for(inp, clock())
    base_prompt = _build_prompt(inp, goal_context=goal_context, focus_tasks=focus_tasks, notes=notes)
    prompt = base_prompt
    problems: list[str] = []

    for attempt in range(1, MAX_ATTEMPTS + 1):
        raw = None
        try:
            raw = await call(settings.planning_model, prompt, ScheduleLLMSchema)
            parsed = ScheduleLLMSchema.model_validate_json(_extract_json(raw))
            output = _llm_to_output(parsed, inp.date, clock())
            output = _enforce_constraints(output, inp)
            output = _validate_and_fix(output, inp)
            output = output.model_copy(update={"strategies": [
                s.model_copy(update={"tasks": _unique_task_ids(_place_fixed_blocks(s.tasks, fixed))})
                for s in output.strategies
            ]})
            problems = [] if output.strategies else ["no strategies were returned"]
            for s in output.strategies:
                problems += [f"[{s.name}] {v}" for v in
                             validate_tasks(s.tasks, inp.date) + missing_fixed_blocks(s.tasks, fixed)]
            if not problems:
                missing_focus = [f for f in (focus_tasks or [])
                                 if not any(f.casefold() in t.title.casefold()
                                            for s in output.strategies for t in s.tasks)]
                if missing_focus:
                    output = output.model_copy(update={"warnings": output.warnings + [
                        f"Not every plan includes: {', '.join(missing_focus)}"]})
                return output
        except Exception as e:  # transport error, invalid JSON, schema mismatch, unparsable times
            problems = [f"{type(e).__name__}: {str(e)[:400]}"]
        _log.warning("[generate_schedule] attempt %d/%d rejected: %s | raw=%r",
                     attempt, MAX_ATTEMPTS, problems[:5], (raw or "")[:500])
        prompt = _retry_prompt(base_prompt, problems)

    raise GenerationFailed(
        "generation_failed",
        "I couldn't put together a valid schedule this time, so nothing was changed. Please try again.",
    )


async def build_schedule_input(req) -> tuple[ScheduleInput, dict | None, list[str]]:
    """Assemble the generator input from code-owned sources (§6.2): preferences, health,
    goals, today's Google Calendar events and the events the user mentioned this turn.
    Context sources are best-effort; a failing one is skipped, never invented."""
    import asyncio
    from agents.tools.goal_tools import track_goals
    from agents.tools.health_tools import analyze_health
    from agents.tools.relationship_tools import get_relationship_context
    from services.day_plan_service import today_for

    mem = MemoryAgent(get_db())
    prefs, health_raw, goals_raw, rel_raw = await asyncio.gather(
        mem.get_preferences(req.user_id),
        analyze_health(req.user_id),
        track_goals(req.user_id),
        get_relationship_context(req.user_id),
        return_exceptions=True,
    )
    prefs = prefs if isinstance(prefs, dict) else {}
    health = None
    if isinstance(health_raw, dict):
        try:
            health = HealthOutput(**health_raw)
        except Exception:
            health = None
    goal_context = goals_raw if isinstance(goals_raw, dict) else None
    rel = rel_raw if isinstance(rel_raw, dict) else {}

    events: list[CalendarEvent] = []
    if req.date == today_for(req.user_id):
        for i, e in enumerate(rel.get("today_calendar_events") or []):
            if e.get("title") and e.get("start_time") and e.get("end_time"):
                events.append(CalendarEvent(
                    id=f"gcal-{i}", title=e["title"],
                    start_time=_normalize_timestamp(e["start_time"], req.date),
                    end_time=_normalize_timestamp(e["end_time"], req.date),
                    location=e.get("location") or None,
                ))
    known = {(e.title, e.start_time) for e in events}
    events += [e for e in req.new_events if (e.title, e.start_time) not in known]

    notes = [u.get("event", "") for u in rel.get("upcoming_events") or []
             if u.get("date") == req.date and u.get("event")]

    commute = prefs.get("commute") if isinstance(prefs.get("commute"), dict) else {}
    inp = ScheduleInput(
        user_id=req.user_id,
        date=req.date,
        health=health,
        user_preferences=UserPreferences(
            preferred_work_hours=prefs.get("focus_window", "9PM-1AM"),
            commute_minutes=commute.get("library_from_home_min", 30),
            break_frequency=90,
        ),
        calendar_events=events,
    )
    return inp, goal_context, notes


async def build_plan(req, *, llm: LLMJsonCall | None = None):
    """Production PlanGenerator for DayPlanService: code-built input → generate_schedule."""
    from schemas.day_plan import GeneratedPlan
    inp, goal_context, notes = await build_schedule_input(req)
    output = await generate_schedule(inp, goal_context=goal_context, focus_tasks=req.focus_tasks,
                                     notes=notes, llm=llm)
    return GeneratedPlan(output=output, input=inp)


# ─────────────────────────────────────────────────────────
# Coordinator tools (thin wrappers: generator + DayPlanService)
# ─────────────────────────────────────────────────────────

async def _persist_schedule(user_id: str, target_date: str, schedule_dict: dict,
                            inp: ScheduleInput | None = None) -> None:
    """Record generated strategies as the day's proposal via DayPlanService.

    The active (confirmed) plan is never touched. Raises DayPlanError if the
    output violates an invariant — the caller must not present an unsaved plan.
    """
    from services.day_plan_invariants import fixed_blocks_for
    from services.day_plan_service import DayPlanService

    output = ScheduleOutput(**{k: v for k, v in schedule_dict.items() if k in ScheduleOutput.model_fields})
    fixed = fixed_blocks_for(inp, datetime.now()) if inp is not None else []
    await DayPlanService().propose_plan(user_id, target_date, output, fixed_blocks=fixed)


@traced_tool("confirm_schedule")
async def confirm_schedule(user_id: str, strategy_name: str, date: str = "") -> dict:
    """
    Save the user-confirmed schedule strategy as the active plan.
    Call this when the user explicitly confirms which plan they want
    (e.g., "yes confirm", "let's go with most relaxed", "I want the fastest plan").
    strategy_name: exactly "Most Productive", "Most Relaxed", or "Fastest"
    """
    from schemas.day_plan import ConfirmProposal, DayPlanError
    from services.day_plan_service import DayPlanService, today_for

    if not date:
        date = today_for(user_id)
    try:
        plan = await DayPlanService().handle(
            ConfirmProposal(user_id=user_id, date=date, strategy_name=strategy_name))
        return {"success": True, "strategy_name": plan.active.strategy_name, "task_count": len(plan.active.tasks)}
    except DayPlanError as e:
        return {"success": False, "message": e.message}
    except Exception as e:
        return {"success": False, "message": str(e)}


@traced_tool("plan_schedule")
async def plan_schedule(
    user_id: str,
    target_date: str = "",
    health_context: dict | None = None,
    goal_context: dict | None = None,
    relationship_context: dict | None = None,
    geo_context: dict | None = None,
    calendar_events: list | None = None,
) -> dict:
    """
    Generate 3 optimized daily schedule strategies.
    Respects fixed calendar events, energy windows, goal urgency, and commute constraints.

    calendar_events: list of dicts, one per user-mentioned event, each shaped EXACTLY like:
        {"title": "ML Class", "start_time": "2026-06-08T14:00:00", "end_time": "2026-06-08T16:00:00", "location": "library"}
    Use the user's exact wording for "title", full ISO 8601 timestamps ("YYYY-MM-DDTHH:MM:SS")
    for "start_time"/"end_time" (resolve "2PM-4PM" to today's date + 14:00/16:00), and omit
    "location" entirely if the user didn't give one. Missing or misnamed keys fall back to a
    generic placeholder, so get the keys right.
    """
    if not target_date or target_date.strip().lower() == "today":
        from services.day_plan_service import today_for
        target_date = today_for(user_id)

    # LLM may serialize dict args as JSON strings
    if isinstance(goal_context, str):
        try:
            goal_context = json.loads(goal_context)
        except Exception:
            goal_context = None
    if isinstance(health_context, str):
        try:
            health_context = json.loads(health_context)
        except Exception:
            health_context = None

    mem = MemoryAgent(get_db())
    prefs = await mem.get_preferences(user_id)

    health = None
    if health_context:
        try:
            health = HealthOutput(**health_context)
        except Exception:
            pass

    inp = ScheduleInput(
        user_id=user_id,
        date=target_date,
        health=health,
        user_preferences=UserPreferences(
            preferred_work_hours=prefs.get("focus_window", "9PM-1AM"),
            commute_minutes=prefs.get("commute", {}).get("library_from_home_min", 30),
            break_frequency=90,
        ),
        calendar_events=[
            CalendarEvent(
                id=str(i),
                title=e.get("title", e.get("name", e.get("summary", "Event"))),
                start_time=_normalize_timestamp(
                    e.get("start_time", e.get("start", target_date + "T00:00:00")),
                    target_date,
                ),
                end_time=_normalize_timestamp(
                    e.get("end_time", e.get("end", target_date + "T01:00:00")),
                    target_date,
                ),
                location=e.get("location"),
            )
            for i, e in enumerate(calendar_events or [])
            if isinstance(e, dict)
        ],
    )

    try:
        output = await generate_schedule(inp, goal_context=goal_context)
        result = output.model_dump()
        await _persist_schedule(user_id, target_date, result, inp)
        return result
    except Exception as _e:
        _log.error("[plan_schedule] failed: %s", _e)
        return {
            "date": target_date,
            "strategies": [],
            "top_recommendation": None,
            "warnings": [getattr(_e, "message", None) or "Schedule generation failed — please try again."],
            "error": True,
        }
