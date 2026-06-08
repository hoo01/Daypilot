import json
import re
from datetime import datetime, date
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

def _build_prompt(inp: ScheduleInput, goal_context: dict | None = None) -> str:
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

    now_iso = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    return f"""You are DayPilot's Schedule Planning Agent.

# PRIORITY ORDER (highest to lowest)
1. LOCKED BLOCKS — never modify, rename, skip, or split them
2. CALENDAR EVENTS — immutable, never shift their times
3. GOAL TASKS — fill remaining gaps with goal-related work

Generate exactly 3 daily schedule strategies for a student.

## User Context
Date: {inp.date}
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

## Rules
1. Calendar events are IMMUTABLE — never move, shift, or rename them
2. Schedule deep work during the user's focus window
3. Each strategy must cover the full day from wake-up to sleep
4. Include at least 2 breaks per strategy
5. "Most Productive" maximizes goal progress; "Most Relaxed" minimizes cognitive load; "Fastest" completes must-dos in minimum time
6. Use ONLY these task types: deep_work, routine, break, commute, exercise, study, meal, personal, preparation, sleep, calendar_event
7. top_recommendation MUST be exactly one of: "Most Productive", "Most Relaxed", or "Fastest"
8. Task titles MUST use the specific goal or activity name — never generic labels like "Study Session (Goal Task)" or "Deep Work Block". If the goal is Leetcode, write "Leetcode Practice". If it's writing, write "Writing Session". Use the exact activity name.
9. Calendar event titles MUST be copied verbatim from the calendar_events input. Never rename them to generic labels like "Event", "Appointment", or "Meeting".
10. CRITICAL: All start_time and end_time MUST be full ISO 8601 strings, e.g. "{inp.date}T09:00:00"

## Output Format (valid JSON only)
{{
  "date": "{inp.date}",
  "strategies": [
    {{
      "name": "Most Productive",
      "description": "...",
      "tasks": [
        {{
          "task_id": "unique-string",
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
  "warnings": [],
  "generated_at": "{now_iso}"
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


def _validate_and_fix(output: ScheduleOutput, inp: ScheduleInput) -> ScheduleOutput:
    import re as _re
    warnings: list[str] = []
    fixed = []

    for strategy in output.strategies:
        tasks = _normalize_tasks(strategy.tasks, inp.date)
        tasks = _merge_short_deep_work(tasks)

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
# Tool function
# ─────────────────────────────────────────────────────────

import logging as _logging
_log = _logging.getLogger(__name__)

import http_client as _http_client
_genai_client = genai.Client(
    api_key=settings.gemini_api_key,
    http_options=genai.types.HttpOptions(httpx_async_client=_http_client.shared_async_client()),
)


async def _persist_schedule(user_id: str, target_date: str, schedule_dict: dict) -> None:
    """Save the top-recommended strategy's tasks to daily_schedules collection."""
    try:
        top_name = schedule_dict.get("top_recommendation", "")
        strategies = schedule_dict.get("strategies", [])
        strategy = next(
            (s for s in strategies if s.get("name") == top_name),
            strategies[0] if strategies else None,
        )
        if not strategy:
            return
        tasks = strategy.get("tasks", [])
        db = get_db()
        await db[Collections.DAILY_SCHEDULES].update_one(
            {"user_id": user_id, "date": target_date},
            {"$set": {
                "user_id": user_id,
                "date": target_date,
                "tasks": tasks,
                "strategy_name": strategy.get("name", ""),
            }},
            upsert=True,
        )
    except Exception:
        pass  # never block schedule generation


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
    if not target_date:
        target_date = date.today().isoformat()

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
    if isinstance(relationship_context, str):
        try:
            relationship_context = json.loads(relationship_context)
        except Exception:
            relationship_context = None

    mem = MemoryAgent(get_db())
    prefs = await mem.get_preferences(user_id)

    # Build typed health object
    health = None
    if health_context:
        try:
            health = HealthOutput(**health_context)
        except Exception:
            pass

    # Build schedule input
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
        ],
    )

    prompt = _build_prompt(inp, goal_context=goal_context)
    response = None

    try:
        response = await _genai_client.aio.models.generate_content(
            model=settings.planning_model,
            contents=prompt,
            config=genai.types.GenerateContentConfig(
                response_mime_type="application/json",
                thinking_config=genai.types.ThinkingConfig(thinking_budget=0),
            ),
        )
        cleaned = _extract_json(response.text)
        output = ScheduleOutput(**json.loads(cleaned))
        output = _enforce_constraints(output, inp)
        output = _validate_and_fix(output, inp)
        result = output.model_dump()
        await _persist_schedule(user_id, target_date, result)
        return result
    except Exception as _e:
        _log.error("[plan_schedule] failed: %s", _e, exc_info=True)
        _log.error("[plan_schedule] raw response: %r", response.text if response else "<api call never returned>")
        return {
            "date": target_date,
            "strategies": [],
            "top_recommendation": None,
            "warnings": ["Schedule generation failed — please try again."],
            "error": True,
        }