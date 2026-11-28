"""Phase 3 — LLM① intent parsing (flat schema → discriminated Intent) and resolve_event.

The LLM is a stub; parse failures must degrade to Chat, never to a state change.
"""
import json
from datetime import datetime

import pytest

from agents.intent import (
    Adjust,
    Chat,
    Confirm,
    Discard,
    EventSpec,
    IntentContext,
    IntentLLMSchema,
    PlanDay,
    Reschedule,
    parse_intent,
    resolve_event,
)

DAY = "2026-11-20"
NOW = datetime(2026, 11, 20, 14, 37)


def flat(**kw):
    base = {"type": "chat", "target_date": None, "new_events": [], "focus_tasks": [], "trigger": None,
            "detail": None, "strategy_name": None}
    base.update(kw)
    return base


class StubLLM:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def __call__(self, model, prompt, schema):
        self.calls.append({"prompt": prompt, "schema": schema})
        if isinstance(self.response, Exception):
            raise self.response
        return self.response if isinstance(self.response, str) else json.dumps(self.response)


def ctx(**kw):
    base = dict(today=DAY, now=NOW, status="PROPOSED", strategy_names=["Most Productive", "Most Relaxed", "Fastest"],
                top_recommendation="Most Productive", proposal_kind="plan",
                calendar_events=[{"title": "ML Class", "start_time": f"{DAY}T16:00:00", "end_time": f"{DAY}T18:00:00"}],
                pending_reschedule={"tasks": ["Lab report"], "suggested_date": "2026-11-21"})
    base.update(kw)
    return IntentContext(**base)


# ── parsing ──────────────────────────────────────────────────────────────────

async def test_schema_handed_to_llm_is_the_flat_envelope():
    llm = StubLLM(flat(type="chat"))
    await parse_intent("hi", ctx(), llm=llm)
    assert llm.calls[0]["schema"] is IntentLLMSchema
    text = json.dumps(IntentLLMSchema.model_json_schema())
    assert '"default"' not in text and '"oneOf"' not in text and '"discriminator"' not in text


async def test_prompt_carries_state_so_the_model_knows_what_is_plausible():
    llm = StubLLM(flat())
    await parse_intent("hi", ctx(), llm=llm)
    p = llm.calls[0]["prompt"]
    for needle in ("PROPOSED", "Most Relaxed", "ML Class", "Lab report", "2026-11-21", DAY):
        assert needle in p


@pytest.mark.parametrize("payload,expected_type", [
    (flat(type="plan_day", target_date=DAY, focus_tasks=["Leetcode"]), PlanDay),
    (flat(type="adjust", trigger="new_event", detail="meeting at 3"), Adjust),
    (flat(type="confirm", strategy_name="Most Relaxed"), Confirm),
    (flat(type="discard"), Discard),
    (flat(type="reschedule_missed", target_date="2026-11-21"), Reschedule),
    (flat(type="chat"), Chat),
])
async def test_flat_envelope_maps_to_intent(payload, expected_type):
    intent = await parse_intent("x", ctx(), llm=StubLLM(payload))
    assert isinstance(intent, expected_type)


async def test_R2_confirm_phrase_maps_to_confirm_with_strategy():
    intent = await parse_intent("let's go with most relaxed", ctx(),
                                llm=StubLLM(flat(type="confirm", strategy_name="Most Relaxed")))
    assert intent == Confirm(type="confirm", strategy_name="Most Relaxed")


async def test_plan_day_keeps_events():
    payload = flat(type="plan_day", new_events=[{"title": "Doctor Appointment", "start_time": "15:00",
                                                 "end_time": "16:00", "time_hint": None,
                                                 "duration_minutes": None, "location": "Clinic"}])
    intent = await parse_intent("plan my day, doctor 3-4pm at the clinic", ctx(), llm=StubLLM(payload))
    assert intent.new_events[0].title == "Doctor Appointment"
    assert intent.new_events[0].location == "Clinic"


@pytest.mark.parametrize("response", [
    "not json",
    {"type": "launch_rockets"},
    flat(type="adjust", trigger=None, detail="??"),           # adjust without a trigger is incomplete
    flat(type="adjust", trigger="teleport", detail="x"),       # unknown trigger
    RuntimeError("503 from model"),
])
async def test_anything_unparsable_or_invalid_degrades_to_chat(response):
    assert isinstance(await parse_intent("x", ctx(), llm=StubLLM(response)), Chat)


# ── resolve_event (time math lives in code, not in the prompt) ───────────────

def test_resolve_explicit_iso_times():
    e = resolve_event(EventSpec(title="ML Class", start_time=f"{DAY}T14:00:00", end_time=f"{DAY}T16:00:00"), DAY, NOW)
    assert (e.start_time, e.end_time, e.title) == (f"{DAY}T14:00:00", f"{DAY}T16:00:00", "ML Class")


def test_resolve_clock_times_and_default_duration():
    e = resolve_event(EventSpec(title="Meeting", start_time="3pm"), DAY, NOW)
    assert (e.start_time, e.end_time) == (f"{DAY}T15:00:00", f"{DAY}T17:00:00")
    e = resolve_event(EventSpec(title="Meeting", start_time="15:30", duration_minutes=45), DAY, NOW)
    assert (e.start_time, e.end_time) == (f"{DAY}T15:30:00", f"{DAY}T16:15:00")


@pytest.mark.parametrize("hint,start,end", [
    ("morning", "08:00", "12:00"),
    ("afternoon", "12:00", "17:00"),
    ("evening", "18:00", "22:00"),
])
def test_resolve_time_hints(hint, start, end):
    e = resolve_event(EventSpec(title="Assignment 7", time_hint=hint), "2026-11-25", NOW)
    assert (e.start_time, e.end_time) == (f"2026-11-25T{start}:00", f"2026-11-25T{end}:00")


def test_resolve_hint_with_duration_starts_at_window_start():
    e = resolve_event(EventSpec(title="Gym", time_hint="evening", duration_minutes=60), DAY, NOW)
    assert (e.start_time, e.end_time) == (f"{DAY}T18:00:00", f"{DAY}T19:00:00")


def test_resolve_now_rounds_up_to_next_quarter_hour_for_two_hours():
    e = resolve_event(EventSpec(title="Assignment 7", time_hint="now"), DAY, NOW)
    assert (e.start_time, e.end_time) == (f"{DAY}T14:45:00", f"{DAY}T16:45:00")


def test_resolve_unspecified_on_today_behaves_like_now():
    e = resolve_event(EventSpec(title="Assignment 7"), DAY, NOW)
    assert e.start_time == f"{DAY}T14:45:00"


def test_unplaceable_events_return_none():
    assert resolve_event(EventSpec(title="Assignment 7"), "2026-11-25", NOW) is None       # future, no time
    assert resolve_event(EventSpec(title="X", start_time="whenever"), DAY, NOW) is None   # garbage time
    assert resolve_event(EventSpec(title="X", start_time="2026-12-01T10:00:00"), DAY, NOW) is None  # other day
    assert resolve_event(EventSpec(title="  ", start_time="15:00"), DAY, NOW) is None
