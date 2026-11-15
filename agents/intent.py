"""LLM① — intent parsing. No tools, no side effects.

The model only *classifies* the user's message and extracts what they said; whether
the resulting command is legal is decided by DayPlanService, and all time arithmetic
happens in `resolve_event`. Any failure degrades to `Chat` — better one extra chat
turn than a wrong state change.

google-genai rejects discriminated unions in response_schema (oneOf/discriminator),
so the model fills the flat `IntentLLMSchema` and code splits it into the typed
`Intent` union below (design doc §6.1 fallback).
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date as _date, datetime, timedelta
from typing import Annotated, Awaitable, Callable, Literal, Union

from pydantic import BaseModel, Field, TypeAdapter

from config import settings
from schemas.schedule import CalendarEvent

_log = logging.getLogger(__name__)

TimeHint = Literal["morning", "afternoon", "evening", "now", "unspecified"]
AdjustTrigger = Literal["new_event", "task_overrun", "energy_update", "location_change"]
IntentType = Literal["plan_day", "adjust", "confirm", "discard", "reschedule_missed", "chat"]


# ─────────────────────────────────────────────────────────
# Domain intents (§6.1)
# ─────────────────────────────────────────────────────────

class EventSpec(BaseModel):
    title: str                    # the user's own words, or the original title from context
    start_time: str | None = None
    end_time: str | None = None
    time_hint: TimeHint | None = None
    duration_minutes: int | None = None
    location: str | None = None


class PlanDay(BaseModel):
    type: Literal["plan_day"] = "plan_day"
    target_date: str | None = None
    new_events: list[EventSpec] = Field(default_factory=list)
    focus_tasks: list[str] = Field(default_factory=list)


class Adjust(BaseModel):
    type: Literal["adjust"] = "adjust"
    trigger: AdjustTrigger
    detail: str
    new_events: list[EventSpec] = Field(default_factory=list)


class Confirm(BaseModel):
    type: Literal["confirm"] = "confirm"
    strategy_name: str | None = None      # None → the recommended strategy


class Discard(BaseModel):
    type: Literal["discard"] = "discard"


class Reschedule(BaseModel):
    type: Literal["reschedule_missed"] = "reschedule_missed"
    target_date: str | None = None


class Chat(BaseModel):
    type: Literal["chat"] = "chat"


Intent = Annotated[Union[PlanDay, Adjust, Confirm, Discard, Reschedule, Chat], Field(discriminator="type")]
_intent_adapter: TypeAdapter = TypeAdapter(Intent)


# ─────────────────────────────────────────────────────────
# Flat LLM schema (no defaults, no unions beyond nullable)
# ─────────────────────────────────────────────────────────

class LLMEventSpec(BaseModel):
    title: str
    start_time: str | None
    end_time: str | None
    time_hint: TimeHint | None
    duration_minutes: int | None
    location: str | None


class IntentLLMSchema(BaseModel):
    type: IntentType
    target_date: str | None
    new_events: list[LLMEventSpec]
    focus_tasks: list[str]
    trigger: AdjustTrigger | None
    detail: str | None
    strategy_name: str | None


def flat_to_intent(flat: IntentLLMSchema):
    """Split the flat envelope into the typed union. Raises if the combination is invalid."""
    events = [EventSpec(**e.model_dump()) for e in flat.new_events]
    t = flat.type
    if t == "plan_day":
        data = {"type": t, "target_date": flat.target_date, "new_events": events, "focus_tasks": flat.focus_tasks}
    elif t == "adjust":
        if flat.trigger is None:
            raise ValueError("adjust intent without a trigger")
        data = {"type": t, "trigger": flat.trigger, "detail": flat.detail or "", "new_events": events}
    elif t == "confirm":
        data = {"type": t, "strategy_name": flat.strategy_name}
    elif t == "reschedule_missed":
        data = {"type": t, "target_date": flat.target_date}
    else:
        data = {"type": t}
    return _intent_adapter.validate_python(data)


# ─────────────────────────────────────────────────────────
# Context + prompt
# ─────────────────────────────────────────────────────────

@dataclass
class IntentContext:
    today: str
    now: datetime
    status: str = "EMPTY"
    strategy_names: list[str] = field(default_factory=list)
    top_recommendation: str | None = None
    proposal_kind: str | None = None
    proposal_date: str | None = None
    calendar_events: list[dict] = field(default_factory=list)
    pending_reschedule: dict | None = None


def _build_intent_prompt(message: str, ctx: IntentContext) -> str:
    tomorrow = (_date.fromisoformat(ctx.today) + timedelta(days=1)).isoformat()
    proposal = (
        f"{ctx.proposal_kind} proposal for {ctx.proposal_date or ctx.today} with options "
        f"{', '.join(ctx.strategy_names)} (recommended: {ctx.top_recommendation})"
        if ctx.strategy_names else "none"
    )
    events = "\n".join(
        f"- {e.get('title')}: {e.get('start_time')} → {e.get('end_time')}"
        + (f" @ {e['location']}" if e.get("location") else "")
        for e in ctx.calendar_events
    ) or "(none)"
    pending = (
        f"missed tasks {ctx.pending_reschedule.get('tasks')} from {ctx.pending_reschedule.get('original_date')}, "
        f"suggested new date {ctx.pending_reschedule.get('suggested_date')}"
        if ctx.pending_reschedule and ctx.pending_reschedule.get("tasks") else "none"
    )
    return f"""You classify one message sent to DayPilot, a day-planning assistant. You do not reply to the user.

## Current state
Today: {ctx.today} (tomorrow is {tomorrow}); current time {ctx.now.strftime('%H:%M')}
Schedule status for today: {ctx.status}
Open proposal: {proposal}
Today's calendar events:
{events}
Pending reschedule: {pending}

## Intent types
- plan_day: the user asks to plan / build / generate a schedule (optionally for another date).
  target_date = YYYY-MM-DD if they name a date (e.g. tomorrow = {tomorrow}), else null.
  new_events = events or tasks with a time they mention in this message. focus_tasks = named things
  they want to get done without a time.
- adjust: something changed today and they want the confirmed schedule updated. trigger is one of
  new_event, task_overrun, energy_update, location_change; detail = a short summary in their words.
  new_events = any new event they mention.
- confirm: they accept a proposed option. strategy_name = the option they name, or null for the
  recommended one.
- discard: they reject the open proposal and want to keep things as they are.
- reschedule_missed: they agree to move their missed tasks to another day. target_date or null.
- chat: anything else — questions, opinions, small talk, unclear requests.

## Event fields
title: copy the user's wording or the title from today's calendar events; never a generic label.
start_time / end_time: what they said ("3pm", "15:00") or null. time_hint: morning / afternoon /
evening / now / unspecified when they only give a rough time. duration_minutes if stated.
location if stated, else null.

If you are unsure, answer chat.

User message: {json.dumps(message, ensure_ascii=False)}"""


LLMJsonCall = Callable[[str, str, type], Awaitable[str]]


async def _llm_json(model: str, prompt: str, schema: type) -> str:
    from agents.tools.schedule_tools import _genai_client
    from google import genai

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


async def parse_intent(message: str, ctx: IntentContext, *, llm: LLMJsonCall | None = None):
    """Return an Intent. Never raises: any failure is logged and becomes Chat()."""
    call = llm or _llm_json
    raw = None
    try:
        raw = await call(settings.intent_model, _build_intent_prompt(message, ctx), IntentLLMSchema)
        from agents.tools.schedule_tools import _extract_json
        return flat_to_intent(IntentLLMSchema.model_validate_json(_extract_json(raw)))
    except Exception as e:
        _log.warning("[intent] falling back to chat: %s: %s | raw=%r", type(e).__name__, str(e)[:300],
                     (raw or "")[:300])
        return Chat()


# ─────────────────────────────────────────────────────────
# resolve_event — all time arithmetic lives here, not in prompts
# ─────────────────────────────────────────────────────────

HINT_WINDOWS: dict[str, tuple[int, int]] = {
    "morning": (8, 12),
    "afternoon": (12, 17),
    "evening": (18, 22),
}
DEFAULT_DURATION_MIN = 120
_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")


def _to_iso(ts: str, target_date: str) -> datetime | None:
    from agents.tools.schedule_tools import _normalize_timestamp
    norm = _normalize_timestamp(ts.strip(), target_date)
    if re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$", norm):
        norm += ":00"
    if not _ISO_RE.match(norm):
        return None
    try:
        return datetime.fromisoformat(norm)
    except ValueError:
        return None


def _fmt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def _round_up_quarter(dt: datetime) -> datetime:
    dt = dt.replace(second=0, microsecond=0)
    extra = (-dt.minute) % 15
    return dt + timedelta(minutes=extra)


def resolve_event(spec: EventSpec, target_date: str, now: datetime) -> CalendarEvent | None:
    """Turn what the user said into a concrete event on `target_date`, or None if it
    can't be placed (the caller then treats the title as a flexible focus task)."""
    title = (spec.title or "").strip()
    if not title:
        return None
    duration = timedelta(minutes=spec.duration_minutes or DEFAULT_DURATION_MIN)
    day = _date.fromisoformat(target_date)
    day_start = datetime(day.year, day.month, day.day)

    if spec.start_time:
        start = _to_iso(spec.start_time, target_date)
        if start is None:
            return None
        end = _to_iso(spec.end_time, target_date) if spec.end_time else None
        if end is None or end <= start:
            end = start + duration
    elif spec.time_hint in HINT_WINDOWS:
        lo, hi = HINT_WINDOWS[spec.time_hint]
        start = day_start + timedelta(hours=lo)
        end = start + duration if spec.duration_minutes else day_start + timedelta(hours=hi)
    elif target_date == now.date().isoformat():   # "now" / unspecified, today only
        start = _round_up_quarter(now)
        end = start + duration
    else:
        return None

    if start.date() != day:
        return None
    return CalendarEvent(
        id="user-" + hashlib.sha1(f"{title}|{_fmt(start)}".encode()).hexdigest()[:10],
        title=title,
        start_time=_fmt(start),
        end_time=_fmt(end),
        location=(spec.location or None),
    )
