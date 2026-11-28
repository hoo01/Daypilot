import json
import logging as _logging
from datetime import datetime
from typing import Callable

from google import genai
from pydantic import BaseModel
from config import settings
import http_client as _http_client
from schemas.realtime import RealtimeOutput
from schemas.schedule import CalendarEvent, ScheduleTask

_log = _logging.getLogger(__name__)

_client = genai.Client(
    api_key=settings.gemini_api_key,
    http_options=genai.types.HttpOptions(httpx_async_client=_http_client.shared_async_client()),
)


# ─────────────────────────────────────────────────────────
# LLM② for adjustments — flat schema + pure generator
# ─────────────────────────────────────────────────────────

from agents.tools.schedule_tools import (  # noqa: E402  (shared repair helpers)
    MAX_ATTEMPTS,
    LLMJsonCall,
    TaskType,
    _extract_json,
    _normalize_tasks,
    _place_fixed_blocks,
    _retry_prompt,
    _unique_task_ids,
)


class LLMAdjustTask(BaseModel):
    task_id: str | None
    title: str
    start_time: str
    end_time: str
    type: TaskType
    location: str | None
    notes: str | None


class AdjustmentLLMSchema(BaseModel):
    what_changed: list[str]
    dropped_tasks: list[str]
    added_tasks: list[str]
    updated_schedule: list[LLMAdjustTask]
    message: str


async def _llm_json(model: str, prompt: str, schema: type) -> str:
    """Default LLM transport: Gemini with a response_schema. Tests inject a stub instead."""
    response = await _client.aio.models.generate_content(
        model=model,
        contents=prompt,
        config=genai.types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=schema,
            thinking_config=genai.types.ThinkingConfig(thinking_budget=0),
        ),
    )
    return response.text or ""


def _build_adjust_prompt(active: list[ScheduleTask], trigger: str, detail: str, date: str,
                         new_events: list[CalendarEvent]) -> str:
    current = json.dumps([t.model_dump() for t in active], indent=2)
    new_lines = "\n".join(
        f"- {e.title}: {e.start_time} → {e.end_time}" + (f" @ {e.location}" if e.location else "")
        for e in new_events
    ) or "(none)"
    return f"""
You are DayPilot's real-time schedule adjustment engine.
The user's day ({date}) has changed. Replan their schedule accordingly.

Rules:
- Keep tasks with type "calendar_event" exactly as they are (title, times, location)
- Add every new fixed event listed below as its own task with type "calendar_event"
- Tasks with type "deep_work", "break", "meal" can be rescheduled or dropped
- Preserve task_id values from the original schedule; use null for brand-new tasks
- All times are full ISO 8601 on {date}, e.g. "{date}T21:00:00"; tasks must not overlap
- Keep the total number of tasks reasonable — drop lower-priority ones if time is tight
- Write a short, friendly message (1-2 sentences) explaining what changed

Trigger type: {trigger}
What happened: {detail}

New fixed events:
{new_lines}

Current schedule:
{current}
"""


async def generate_adjustment(
    active_tasks: list[ScheduleTask],
    trigger: str,
    detail: str,
    *,
    date: str | None = None,
    new_events: list[CalendarEvent] | None = None,
    llm: LLMJsonCall | None = None,
    now: Callable[[], datetime] | None = None,
) -> RealtimeOutput:
    """LLM② for mid-day adjustments — pure (no DB writes).

    Same contract as generate_schedule: schema-constrained call, code repairs
    (timestamps, fixed blocks, overlaps), §5.3 invariant validation, one retry,
    then GenerationFailed. Never falls back to returning the old schedule.
    """
    from schemas.day_plan import GenerationFailed
    from services.day_plan_invariants import fixed_blocks_for_adjustment, missing_fixed_blocks, validate_tasks
    from services.day_plan_service import today_for

    from services.clock import now_local
    call = llm or _llm_json
    clock = now or now_local
    active_tasks = [t if isinstance(t, ScheduleTask) else ScheduleTask(**t) for t in active_tasks]
    new_events = list(new_events or [])
    date = date or (active_tasks[0].start_time[:10] if active_tasks else today_for(""))
    fixed = fixed_blocks_for_adjustment(active_tasks, new_events, date, clock())
    base_prompt = _build_adjust_prompt(active_tasks, trigger, detail, date, new_events)
    prompt = base_prompt
    problems: list[str] = []

    for attempt in range(1, MAX_ATTEMPTS + 1):
        raw = None
        try:
            raw = await call(settings.realtime_model, prompt, AdjustmentLLMSchema)
            parsed = AdjustmentLLMSchema.model_validate_json(_extract_json(raw))
            if not parsed.updated_schedule:
                raise ValueError("updated_schedule is empty")
            tasks = [
                ScheduleTask(task_id=t.task_id or f"adj-{i + 1}", title=t.title.strip(), start_time=t.start_time,
                             end_time=t.end_time, type=t.type, location=t.location, notes=t.notes)
                for i, t in enumerate(parsed.updated_schedule)
            ]
            tasks = _unique_task_ids(_place_fixed_blocks(_normalize_tasks(tasks, date), fixed))
            problems = validate_tasks(tasks, date) + missing_fixed_blocks(tasks, fixed)
            if not problems:
                return RealtimeOutput(
                    what_changed=parsed.what_changed or [detail],
                    dropped_tasks=parsed.dropped_tasks,
                    added_tasks=parsed.added_tasks,
                    updated_schedule=tasks,
                    message=parsed.message.strip() or detail,
                )
        except Exception as e:  # transport error, invalid JSON, schema mismatch, unparsable times
            problems = [f"{type(e).__name__}: {str(e)[:400]}"]
        _log.warning("[generate_adjustment] attempt %d/%d rejected: %s | raw=%r",
                     attempt, MAX_ATTEMPTS, problems[:5], (raw or "")[:500])
        prompt = _retry_prompt(base_prompt, problems)

    raise GenerationFailed(
        "generation_failed",
        "I couldn't work out a valid adjustment this time, so your schedule is unchanged. Please try again.",
    )


async def build_adjustment(req, *, llm: LLMJsonCall | None = None) -> RealtimeOutput:
    """Production AdjustGenerator for DayPlanService."""
    return await generate_adjustment(req.active_tasks, req.trigger, req.detail, date=req.date,
                                     new_events=req.new_events, llm=llm)
