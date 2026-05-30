"""
Schedule Planning Agent — core logic.

All helpers and the ScheduleAgent class are verbatim from agents/schedule.py,
refactored into a self-contained module with no dependency on the monorepo root
config or BaseAgent.
"""
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

# Add monorepo root so shared schemas/ is importable locally.
# In Docker the WORKDIR /app + COPY schemas/ ./schemas/ handles this automatically.
_monorepo_root = Path(__file__).resolve().parent.parent.parent.parent.parent
if str(_monorepo_root) not in sys.path:
    sys.path.insert(0, str(_monorepo_root))

from schemas import ScheduleInput, ScheduleOutput, ScheduleTask  # noqa: E402

DEBUG = os.environ.get("DEBUG") == "1"


# ─────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────

def _parse_iso(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _naive_dt(ts: str) -> datetime:
    """Parse ISO 8601 and strip timezone for offset-naive comparison.

    Google Calendar events carry tz offsets (e.g. -07:00); replan_from_time
    and locked block timestamps are usually bare local times.  Stripping tz
    before comparing keeps everything consistent inside _enforce_constraints.
    """
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return dt.replace(tzinfo=None)


def _times_overlap(s1: str, e1: str, s2: str, e2: str) -> bool:
    # Use _naive_dt so timezone-aware (Google Calendar) and naive timestamps
    # can be compared without TypeError.
    return _naive_dt(s1) < _naive_dt(e2) and _naive_dt(s2) < _naive_dt(e1)


def _extract_json(raw: str) -> str:
    """Strip markdown code fences that some models wrap around JSON."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)
    return raw.strip()


def _minutes_between(start: str, end: str) -> float:
    return (_naive_dt(end) - _naive_dt(start)).total_seconds() / 60


# ─────────────────────────────────────────────────────────
# Prompt builder
# ─────────────────────────────────────────────────────────

def _build_prompt(inp: ScheduleInput) -> str:
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
        _lines = "\n".join(
            f'- "{t.title}" ({t.estimated_minutes} min, priority: {t.priority}, preferred: {t.preferred_time_of_day}, deadline: {t.deadline}, can_split: {t.can_split})'
            for t in goals.daily_sub_tasks
        )
        goal_sub_tasks_section = f"Goal sub-tasks for today:\n{_lines}"
    else:
        goal_sub_tasks_section = "(no goal sub-tasks for today)"

    if inp.recurring_tasks:
        lines = []
        for t in inp.recurring_tasks:
            line = f'- REQUIRED: "{t.title}" | type={t.type} | duration={t.duration_minutes}min'
            if t.preferred_time:
                line += f" | preferred_time={t.preferred_time}"
            if t.priority:
                line += f" | priority={t.priority}"
            lines.append(line)
        recurring_section = (
            "Each of these MUST appear in the output as a separate task with the EXACT title shown. "
            "Use the preferred_time when possible.\n\n" + "\n".join(lines)
        )
    else:
        recurring_section = "(none)"

    if inp.locked_blocks:
        lock_lines = [
            f"- LOCKED: {b.title} | {b.start_time} → {b.end_time} | type: {b.type}"
            for b in inp.locked_blocks
        ]
        locked_section = (
            "These blocks have already happened, are happening now, or are firm commitments.\n"
            "They MUST appear in the output EXACTLY as listed (same start_time, end_time, title, type).\n"
            "Only schedule new tasks in the gaps BETWEEN these locked blocks.\n\n"
            + "\n".join(lock_lines)
        )
        if inp.replan_from_time:
            locked_section += (
                f"\n\nOnly generate new/modified blocks AFTER {inp.replan_from_time}. "
                "Anything before that time should be preserved exactly from the locked blocks list."
            )
    else:
        locked_section = "(no locked blocks — full day is plannable)"

    calendar_section = (
        "\n".join(
            f"- {e.title}: {e.start_time} → {e.end_time}" + (f" @ {e.location}" if e.location else "")
            for e in inp.calendar_events
        )
        or "(none)"
    )

    now_iso = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    return f"""
You are DayPilot's Schedule Planning Agent.

# CRITICAL PRIORITY ORDER (highest to lowest)
1. **LOCKED BLOCKS** — every locked block MUST appear with the EXACT same title, start_time, end_time, and type. Never modify, rename, skip, or split them.
2. **RECURRING TASKS** — every recurring task MUST appear with its EXACT title.
3. **CALENDAR EVENTS** — preserve as-is. If replan_from_time is set, any calendar event whose start_time is BEFORE replan_from_time is FROZEN — its start_time and end_time must appear in the output EXACTLY as given. Only calendar events AFTER replan_from_time may be adjusted if genuinely necessary.
4. **GOAL TASKS** — fill remaining time with goal-related work.

If LOCKED BLOCKS conflict with CALENDAR EVENTS, the LOCKED BLOCKS win.

Your job: generate exactly 3 daily schedule strategies for a student.

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

## Recurring Tasks (MUST be scheduled today)
{recurring_section}

## Locked Blocks (DO NOT MOVE OR MODIFY)
{locked_section}

## CRITICAL — CALENDAR EVENTS ARE IMMUTABLE
Calendar events listed below come from the user's real Google Calendar.
You MUST output each calendar event with EXACTLY the same start_time, end_time,
title, and location as provided. NEVER shift their times, even by minutes, even
if commute or break timing seems tight. If a commute conflict exists, adjust
the SURROUNDING non-calendar tasks (shorten breaks, drop optional items),
NEVER the calendar event itself.

## Fixed Calendar Events
{calendar_section}

## Rules
1. Calendar events are IMMUTABLE — never move, shift, or rename them (see CRITICAL rule above)
2. Respect the cognitive load score — low score means fewer deep work blocks
3. Schedule deep work during the user's focus window when possible
4. Each strategy must cover the full day from wake-up to sleep
5. Include at least 2 breaks per strategy
6. "Most Productive" maximizes goal progress; "Most Relaxed" minimizes cognitive load; "Fastest" completes must-dos in minimum time
7. Add a clear reasoning explaining the tradeoffs of each strategy
8. Use ONLY these task types: deep_work, routine, break, commute, exercise, study, meal, personal, preparation, sleep, calendar_event
9. top_recommendation MUST be exactly one of: "Most Productive", "Most Relaxed", or "Fastest"
10. generated_at: use the timestamp {now_iso}
11. CRITICAL: All start_time and end_time MUST be full ISO 8601 strings with the date, e.g. "{inp.date}T09:00:00". NEVER use bare time strings like "09:00". Use date {inp.date} for same-day blocks; use the next calendar day for blocks after midnight.
12. CRITICAL — replan_from_time semantics: {f'''replan_from_time is {inp.replan_from_time}. EVERYTHING before this moment is FROZEN.
    - DO NOT modify, shift, or rename any calendar_event whose start_time is before {inp.replan_from_time}. Output their start_time and end_time EXACTLY as provided in "Fixed Calendar Events".
    - DO NOT insert any new task whose start_time is before {inp.replan_from_time}.
    - Only the time window AFTER {inp.replan_from_time} is plannable for new or rescheduled tasks.
    - locked_blocks before {inp.replan_from_time} represent things that already happened — include them with original times.
    - Calendar events before {inp.replan_from_time} that are NOT in locked_blocks are still completed/in-progress — include them with their ORIGINAL start_time and end_time unchanged.
    - Re-planning means: insert new tasks ONLY in gaps AFTER {inp.replan_from_time}.''' if inp.replan_from_time else '''(no replan_from_time — full day is plannable for non-calendar tasks; calendar events are still IMMUTABLE.)'''}
13. CRITICAL: Every recurring task listed above must appear with its EXACT title. Do not rename, merge, or skip any.

## Output Format
Respond with valid JSON only, snake_case field names, exactly matching this structure:
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

Generate all 3 strategies now.
"""


# ─────────────────────────────────────────────────────────
# Constraint enforcement
# ─────────────────────────────────────────────────────────

def _enforce_constraints(output: ScheduleOutput, inp: ScheduleInput) -> ScheduleOutput:
    locked = inp.locked_blocks
    recurring = inp.recurring_tasks

    # ── Normalize: locked_blocks take precedence — drop calendar_events that overlap them ──
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
                if e_start < lb_end and lb_start < e_end:  # strict overlap; touching is fine
                    return True
            return False

        filtered_calendar_events = [
            e for e in inp.calendar_events if not _overlaps_any_locked(e)
        ]
    else:
        filtered_calendar_events = list(inp.calendar_events)

    # ── Pre-build lookup sets for replan + location enforcement ──────────────

    # For Task 1: sets to identify "allowed" tasks before replan_from_time
    # All datetime comparisons use _naive_dt to handle timezone-aware calendar
    # events alongside naive replan_from_time / locked block timestamps.
    replan_dt = _naive_dt(inp.replan_from_time) if inp.replan_from_time else None

    # locked: match by task_id OR (title, start_time datetime)
    locked_task_ids: set[str] = {lb.task_id for lb in locked if lb.task_id}
    locked_title_time: set[tuple[str, datetime]] = {
        (lb.title, _naive_dt(lb.start_time)) for lb in locked
    }

    # calendar events: match by (title, start_time datetime)
    cal_title_time: set[tuple[str, datetime]] = {
        (e.title, _naive_dt(e.start_time)) for e in filtered_calendar_events
    }

    # For Task 2: map (title, start_time datetime) → original location
    cal_location_map: dict[tuple[str, datetime], str | None] = {
        (e.title, _naive_dt(e.start_time)): e.location
        for e in filtered_calendar_events
    }

    # ─────────────────────────────────────────────────────────────────────────

    fixed = []
    for strategy in output.strategies:
        tasks = list(strategy.tasks)

        # Inject locked blocks: remove overlapping tasks first, then add all locked
        if locked:
            tasks = [
                t for t in tasks
                if not any(
                    _times_overlap(t.start_time, t.end_time, lb.start_time, lb.end_time)
                    for lb in locked
                )
            ]
            tasks.extend(locked)

        # ── Task 1: strip Gemini-invented tasks before replan_from_time ──────
        if replan_dt is not None:
            def _allowed_before_replan(t: ScheduleTask) -> bool:
                try:
                    t_dt = _naive_dt(t.start_time)
                except Exception:
                    return True  # unparseable → keep and let validator catch it
                if t_dt >= replan_dt:
                    return True  # after replan window → always keep
                # Before replan: only locked blocks and real calendar events survive
                if t.task_id in locked_task_ids:
                    return True
                if (t.title, t_dt) in locked_title_time:
                    return True
                if (t.title, t_dt) in cal_title_time:
                    return True
                return False

            tasks = [t for t in tasks if _allowed_before_replan(t)]

        # ── Task 1.5: inject / restore frozen calendar events before replan ──
        # Gemini sometimes omits calendar events that are before replan_from_time.
        # Guarantee their presence with original data (title, start/end, location).
        if replan_dt is not None and filtered_calendar_events:
            frozen_events = [
                e for e in filtered_calendar_events
                if _naive_dt(e.start_time) < replan_dt
            ]
            for event in frozen_events:
                try:
                    e_dt = _naive_dt(event.start_time)
                except Exception:
                    continue  # bad timestamp in source — skip

                # 1) Exact match: (title, naive start_dt)
                exact_idx: int | None = None
                for i, t in enumerate(tasks):
                    try:
                        if t.title == event.title and _naive_dt(t.start_time) == e_dt:
                            exact_idx = i
                            break
                    except Exception:
                        pass

                if exact_idx is not None:
                    # Force original values (handles location + any minor drift)
                    tasks[exact_idx] = tasks[exact_idx].model_copy(update={
                        "start_time": event.start_time,
                        "end_time": event.end_time,
                        "title": event.title,
                        "location": event.location,
                    })
                    continue

                # 2) Loose match: same title + type=calendar_event (Gemini shifted time)
                loose_idx: int | None = None
                for i, t in enumerate(tasks):
                    if t.title == event.title and t.type == "calendar_event":
                        loose_idx = i
                        break

                if loose_idx is not None:
                    tasks[loose_idx] = tasks[loose_idx].model_copy(update={
                        "start_time": event.start_time,
                        "end_time": event.end_time,
                        "title": event.title,
                        "location": event.location,
                    })
                    continue

                # 3) Completely missing — inject canonical task
                tasks.append(ScheduleTask(
                    task_id=f"calendar-frozen-{event.id}",
                    title=event.title,
                    start_time=event.start_time,
                    end_time=event.end_time,
                    type="calendar_event",
                    location=event.location,
                    notes=None,
                ))

        # ── Task 2: restore original location for calendar_events ────────────
        if cal_location_map:
            corrected: list[ScheduleTask] = []
            for t in tasks:
                if t.type == "calendar_event":
                    try:
                        key = (t.title, _naive_dt(t.start_time))
                    except Exception:
                        corrected.append(t)
                        continue
                    if key in cal_location_map:
                        original_loc = cal_location_map[key]
                        if t.location != original_loc:
                            t = t.model_copy(update={"location": original_loc})
                corrected.append(t)
            tasks = corrected

        # Log missing recurring tasks (don't auto-insert — no free slot known)
        if DEBUG:
            missing = [rt for rt in recurring if not any(t.title == rt.title for t in tasks)]
            if missing:
                print(
                    f'Strategy "{strategy.name}" missing recurring tasks: '
                    + ", ".join(m.title for m in missing)
                )

        tasks.sort(key=lambda t: t.start_time)
        fixed.append(strategy.model_copy(update={"tasks": tasks}))

    return output.model_copy(update={"strategies": fixed})


# ─────────────────────────────────────────────────────────
# Validator — fix functions
# ─────────────────────────────────────────────────────────

def _normalize_timestamp(ts: str, target_date: str) -> str:
    if re.match(r"^\d{4}-\d{2}-\d{2}", ts) or "T" in ts:
        return ts
    if re.match(r"^\d{2}:\d{2}(:\d{2})?$", ts):
        time_part = ts if len(ts) == 8 else ts + ":00"
        return f"{target_date}T{time_part}"
    return ts


def _normalize_timestamps(tasks: list[ScheduleTask], target_date: str) -> list[ScheduleTask]:
    return [
        t.model_copy(update={
            "start_time": _normalize_timestamp(t.start_time, target_date),
            "end_time": _normalize_timestamp(t.end_time, target_date),
        })
        for t in tasks
    ]


def _fix_year(ts: str, target_year: str) -> str:
    year = ts[:4]
    if year.isdigit() and abs(int(year) - int(target_year)) == 1:
        return target_year + ts[4:]
    return ts


def _fix_year_typos(tasks: list[ScheduleTask], target_date: str) -> list[ScheduleTask]:
    target_year = target_date.split("-")[0]
    return [
        t.model_copy(update={
            "start_time": _fix_year(t.start_time, target_year),
            "end_time": _fix_year(t.end_time, target_year),
        })
        for t in tasks
    ]


def _merge_short_deep_work(
    tasks: list[ScheduleTask], locked: list[ScheduleTask]
) -> list[ScheduleTask]:
    MIN_MINUTES = 30
    result: list[ScheduleTask] = []

    for task in tasks:
        if task.type != "deep_work":
            result.append(task)
            continue

        is_locked = any(
            lb.title == task.title
            and lb.start_time == task.start_time
            and lb.end_time == task.end_time
            for lb in locked
        )
        if is_locked:
            result.append(task)
            continue

        if _minutes_between(task.start_time, task.end_time) >= MIN_MINUTES:
            result.append(task)
            continue

        # Merge into previous deep_work if possible; otherwise drop
        if result and result[-1].type == "deep_work":
            prev = result[-1]
            result[-1] = prev.model_copy(update={
                "end_time": task.end_time,
                "notes": (prev.notes or "") + " [merged short block]",
            })

    return result


# ─────────────────────────────────────────────────────────
# Validator — detect functions
# ─────────────────────────────────────────────────────────

def _detect_calendar_overlaps(tasks: list[ScheduleTask]) -> list[str]:
    cal = [t for t in tasks if t.type == "calendar_event"]
    issues = []
    for i in range(len(cal)):
        for j in range(i + 1, len(cal)):
            a, b = cal[i], cal[j]
            if _times_overlap(a.start_time, a.end_time, b.start_time, b.end_time):
                issues.append(f'"{a.title}" overlaps with "{b.title}"')
    return issues


def _detect_meal_times(tasks: list[ScheduleTask]) -> list[str]:
    issues = []
    for t in tasks:
        if t.type != "meal":
            continue
        m = re.search(r"T(\d{2}):", t.start_time)
        hour = int(m.group(1)) if m else 0
        title = t.title.lower()
        if "lunch" in title and not (11 <= hour <= 14):
            issues.append(f'"{t.title}" at {hour}:00 (expected 11-14)')
        if "dinner" in title and not (17 <= hour <= 21):
            issues.append(f'"{t.title}" at {hour}:00 (expected 17-21)')
    return issues


def _detect_time_order_issues(tasks: list[ScheduleTask]) -> list[str]:
    issues = []
    for i in range(1, len(tasks)):
        prev, curr = tasks[i - 1], tasks[i]
        if _naive_dt(curr.start_time) < _naive_dt(prev.start_time):
            issues.append(f'"{curr.title}" starts before "{prev.title}" (likely date error)')
    return issues


def _detect_missing_locked_blocks(
    tasks: list[ScheduleTask], locked: list[ScheduleTask]
) -> list[str]:
    issues = []
    for lb in locked:
        found = any(
            t.title == lb.title
            and t.start_time == lb.start_time
            and t.end_time == lb.end_time
            for t in tasks
        )
        if not found:
            issues.append(f'Locked block "{lb.title}" ({lb.start_time}) was modified or removed')
    return issues


# ─────────────────────────────────────────────────────────
# Validator — main entry
# ─────────────────────────────────────────────────────────

def _validate_and_fix(
    output: ScheduleOutput,
    target_date: str,
    locked: list[ScheduleTask],
) -> ScheduleOutput:
    extra_warnings: list[str] = []
    fixed = []

    for strategy in output.strategies:
        tasks = strategy.tasks

        # Fixes (normalize timestamps first — all subsequent steps depend on it)
        tasks = _normalize_timestamps(tasks, target_date)
        tasks = _fix_year_typos(tasks, target_date)
        tasks = _merge_short_deep_work(tasks, locked)

        # Detectors
        overlaps = _detect_calendar_overlaps(tasks)
        if overlaps:
            extra_warnings.append(f'[{strategy.name}] Calendar conflicts: {"; ".join(overlaps)}')

        meal_issues = _detect_meal_times(tasks)
        if meal_issues:
            extra_warnings.append(f'[{strategy.name}] Meal timing: {"; ".join(meal_issues)}')

        order_issues = _detect_time_order_issues(tasks)
        if order_issues:
            extra_warnings.append(f'[{strategy.name}] Time order: {"; ".join(order_issues)}')

        if locked:
            lock_issues = _detect_missing_locked_blocks(tasks, locked)
            if lock_issues:
                extra_warnings.append(
                    f'[{strategy.name}] Locked block violations: {"; ".join(lock_issues)}'
                )

        fixed.append(strategy.model_copy(update={"tasks": tasks}))

    return output.model_copy(update={
        "strategies": fixed,
        "warnings": output.warnings + extra_warnings,
    })


# ─────────────────────────────────────────────────────────
# Agent
# ─────────────────────────────────────────────────────────

class ScheduleAgent:
    """Synthesizes agent outputs into optimized daily schedule strategies."""

    def __init__(self) -> None:
        from app.config import get_settings
        from google import genai
        from google.genai.types import HttpOptions

        cfg = get_settings()
        self._model_name = cfg.planning_model
        self._client = genai.Client(
            api_key=cfg.gemini_api_key,
            http_options=HttpOptions(api_version="v1"),
        )

    async def _generate(self, prompt: str) -> str:
        response = self._client.models.generate_content(
            model=self._model_name,
            contents=prompt,
        )
        return response.text

    async def run(self, input_data: ScheduleInput) -> ScheduleOutput:
        prompt = _build_prompt(input_data)
        raw = await self._generate(prompt)

        cleaned = _extract_json(raw)

        if DEBUG:
            try:
                raw_parsed = json.loads(cleaned)
                first_tasks = raw_parsed.get("strategies", [{}])[0].get("tasks", [])[:3]
                print("[DEBUG] RAW Gemini output — first 3 tasks of strategy[0]:", json.dumps(first_tasks, indent=2))
                print("[DEBUG] RAW task count per strategy:", [
                    f"{s.get('name')}: {len(s.get('tasks', []))}"
                    for s in raw_parsed.get("strategies", [])
                ])
            except Exception as e:
                print("[DEBUG] RAW parse error:", e)
                print("[DEBUG] RAW string (first 500 chars):", repr(cleaned[:500]))

        try:
            parsed = ScheduleOutput(**json.loads(cleaned))
        except Exception as e:
            print("ERROR: failed to parse Gemini response.")
            print("Raw (first 500 chars):", repr(cleaned[:500]))
            raise

        if DEBUG:
            print("[DEBUG] PRE-enforce task counts:", [
                f"{s.name}: {len(s.tasks)}" for s in parsed.strategies
            ])
            print("[DEBUG] locked_blocks to inject:", [
                b.model_dump() for b in input_data.locked_blocks
            ])

        enforced = _enforce_constraints(parsed, input_data)

        if DEBUG:
            print("[DEBUG] POST-enforce task counts:", [
                f"{s.name}: {len(s.tasks)}" for s in enforced.strategies
            ])
            for s in enforced.strategies:
                presence = [
                    f"✓ {lb.title}" if any(t.title == lb.title for t in s.tasks) else f"✗ {lb.title}"
                    for lb in input_data.locked_blocks
                ]
                print(f"[DEBUG]   {s.name} locked presence:", presence)
                print(f"[DEBUG]   {s.name} first 2 tasks:", json.dumps([t.model_dump() for t in s.tasks[:2]], indent=2))

        validated = _validate_and_fix(enforced, input_data.date, input_data.locked_blocks)

        if DEBUG:
            print("[DEBUG] POST-validate task counts:", [
                f"{s.name}: {len(s.tasks)}" for s in validated.strategies
            ])
            for s in validated.strategies:
                presence = [
                    f"✓ {lb.title}" if any(t.title == lb.title for t in s.tasks) else f"✗ {lb.title}"
                    for lb in input_data.locked_blocks
                ]
                print(f"[DEBUG]   {s.name} locked presence:", presence)

        return validated
