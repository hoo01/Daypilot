"""Phase 2 — LLM② generators are pure functions with schema + invariant validation and one retry.

The genai client is replaced by a stub `llm(model, prompt, schema) -> str`; no network.
"""
import json
from datetime import datetime

import pytest

from agents.tools.realtime_tools import AdjustmentLLMSchema, generate_adjustment
from agents.tools.schedule_tools import ScheduleLLMSchema, generate_schedule
from schemas.day_plan import GenerationFailed
from schemas.schedule import ScheduleInput
from services.day_plan_invariants import missing_fixed_blocks, validate_tasks
from tests.fixtures.day_plan import DAY, FIXED_NOW, cal_event, task

ML = cal_event("ML Class", "14:00", "16:00", location="Library", id="ml")


class StubLLM:
    """Returns queued raw responses (str) or raises queued exceptions."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    async def __call__(self, model, prompt, schema):
        self.calls.append({"model": model, "prompt": prompt, "schema": schema})
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r if isinstance(r, str) else json.dumps(r)


def t(title, start, end, type="deep_work", location=None, day=DAY):
    return {"title": title, "start_time": f"{day}T{start}:00", "end_time": f"{day}T{end}:00",
            "type": type, "location": location, "notes": None}


def strat(name, tasks):
    return {"name": name, "description": f"{name} plan", "tasks": tasks, "total_focus_hours": 2.0,
            "reasoning": "because"}


def plan_payload(tasks_by_strategy=None, top="Most Productive"):
    tasks_by_strategy = tasks_by_strategy or {
        "Most Productive": [t("Leetcode Practice", "09:00", "11:00"), t("ML Class", "14:00", "16:00", "calendar_event", "Library")],
        "Most Relaxed": [t("Reading", "10:00", "11:00", "personal"), t("ML Class", "14:00", "16:00", "calendar_event", "Library")],
        "Fastest": [t("Leetcode Practice", "08:00", "09:30"), t("ML Class", "14:00", "16:00", "calendar_event", "Library")],
    }
    return {"strategies": [strat(n, ts) for n, ts in tasks_by_strategy.items()],
            "top_recommendation": top, "warnings": []}


def _inp(**kw):
    return ScheduleInput(user_id="u", date=DAY, calendar_events=[ML], **kw)


def _assert_all_invariants(output, inp):
    from services.day_plan_invariants import fixed_blocks_for
    fixed = fixed_blocks_for(inp, FIXED_NOW)
    for s in output.strategies:
        assert validate_tasks(s.tasks, DAY) == [], (s.name, validate_tasks(s.tasks, DAY))
        assert missing_fixed_blocks(s.tasks, fixed) == [], s.name


# ── generate_schedule ────────────────────────────────────────────────────────

async def test_generate_schedule_uses_llm_schema_and_assigns_task_ids():
    llm = StubLLM(plan_payload())
    out = await generate_schedule(_inp(), llm=llm, now=lambda: FIXED_NOW)
    assert len(llm.calls) == 1
    assert llm.calls[0]["schema"] is ScheduleLLMSchema
    assert [s.name for s in out.strategies] == ["Most Productive", "Most Relaxed", "Fastest"]
    ids = [tk.task_id for s in out.strategies for tk in s.tasks]
    assert all(ids) and len(ids) == len(set(ids))
    _assert_all_invariants(out, _inp())


async def test_llm_schema_has_no_defaults_or_union_keywords():
    """The schema we hand Gemini must avoid constructs the SDK/API reject (see Phase 2 notes)."""
    text = json.dumps(ScheduleLLMSchema.model_json_schema()) + json.dumps(AdjustmentLLMSchema.model_json_schema())
    for bad in ('"default"', '"oneOf"', '"discriminator"'):
        assert bad not in text


async def test_R7_underscore_timestamps_overlaps_and_renamed_event_are_fixed_in_code():
    """R7: malformed-but-salvageable output is repaired deterministically and meets all invariants."""
    messy = {
        "Most Productive": [
            {**t("Leetcode Practice", "09:00", "11:00"), "start_time": "2026_11_20T09:00:00"},
            t("Deep Work", "10:30", "12:00"),                                  # overlaps Leetcode
            t("Event", "14:00", "16:00", "calendar_event"),                      # renamed ML Class, no location
            t("Personal Time", "15:00", "17:00", "personal"),                    # double-booked on ML Class
        ],
        "Most Relaxed": [t("Reading", "10:00", "11:00", "personal")],          # ML Class dropped entirely
        "Fastest": [{**t("Leetcode Practice", "08:00", "09:30"), "end_time": "2026_11_20T09:30:00"}],
    }
    llm = StubLLM(plan_payload(messy))
    out = await generate_schedule(_inp(), llm=llm, now=lambda: FIXED_NOW)
    assert len(llm.calls) == 1, "repairable output must not need a retry"
    _assert_all_invariants(out, _inp())
    for s in out.strategies:
        ml = [tk for tk in s.tasks if tk.title == "ML Class"]
        assert len(ml) == 1 and ml[0].location == "Library" and ml[0].type == "calendar_event"
        assert not any(tk.title == "Event" for tk in s.tasks)


async def test_malformed_json_retries_once_then_succeeds():
    llm = StubLLM("this is not json {", plan_payload())
    out = await generate_schedule(_inp(), llm=llm, now=lambda: FIXED_NOW)
    assert len(llm.calls) == 2
    assert "previous" in llm.calls[1]["prompt"].lower()
    assert len(out.strategies) == 3


async def test_schema_violation_retries_once_then_succeeds():
    bad = plan_payload()
    bad["strategies"][0]["tasks"][0]["type"] = "nap_time"          # not an allowed task type
    llm = StubLLM(bad, plan_payload())
    out = await generate_schedule(_inp(), llm=llm, now=lambda: FIXED_NOW)
    assert len(llm.calls) == 2 and len(out.strategies) == 3


async def test_unrepairable_dates_retry_then_succeed():
    wrong_day = plan_payload({"Most Productive": [t("Leetcode Practice", "09:00", "11:00", day="2026-12-25")]})
    llm = StubLLM(wrong_day, plan_payload())
    out = await generate_schedule(_inp(), llm=llm, now=lambda: FIXED_NOW)
    assert len(llm.calls) == 2
    _assert_all_invariants(out, _inp())


async def test_R8_two_failures_raise_generation_failed_without_fallback_schedule():
    llm = StubLLM("garbage", {"strategies": [], "top_recommendation": "Fastest", "warnings": []})
    with pytest.raises(GenerationFailed) as exc:
        await generate_schedule(_inp(), llm=llm, now=lambda: FIXED_NOW)
    assert exc.value.code == "generation_failed"
    assert len(llm.calls) == 2


async def test_llm_exceptions_count_as_failures():
    llm = StubLLM(RuntimeError("503"), RuntimeError("503"))
    with pytest.raises(GenerationFailed):
        await generate_schedule(_inp(), llm=llm, now=lambda: FIXED_NOW)
    assert len(llm.calls) == 2


async def test_focus_tasks_and_new_events_reach_the_prompt():
    llm = StubLLM(plan_payload())
    await generate_schedule(_inp(), focus_tasks=["Lab report"], notes=["Mom's birthday"], llm=llm,
                            now=lambda: FIXED_NOW)
    prompt = llm.calls[0]["prompt"]
    assert "Lab report" in prompt and "ML Class" in prompt and "Mom's birthday" in prompt


async def test_top_recommendation_falls_back_when_not_a_strategy():
    payload = plan_payload({"Most Relaxed": [t("Reading", "10:00", "11:00", "personal"),
                                             t("ML Class", "14:00", "16:00", "calendar_event", "Library")]},
                           top="Most Productive")
    out = await generate_schedule(_inp(), llm=StubLLM(payload), now=lambda: FIXED_NOW)
    assert out.top_recommendation == "Most Relaxed"


# ── generate_adjustment ──────────────────────────────────────────────────────

ACTIVE = [
    task("Leetcode Practice", "09:00", "11:00", task_id="lc"),
    task("ML Class", "14:00", "16:00", type="calendar_event", location="Library", task_id="ml"),
    task("Reading", "17:00", "18:00", type="personal", task_id="rd"),
]


def adj(updated, message="Moved things around."):
    return {"what_changed": ["moved reading"], "dropped_tasks": [], "added_tasks": [],
            "updated_schedule": updated, "message": message}


def at(title, start, end, type="deep_work", location=None, task_id=None):
    return {**t(title, start, end, type, location), "task_id": task_id}


async def test_generate_adjustment_happy_path_preserves_ids():
    updated = [at("Leetcode Practice", "09:00", "11:00", task_id="lc"),
               at("ML Class", "14:00", "16:00", "calendar_event", "Library", "ml"),
               at("Team sync", "16:30", "17:30", "calendar_event"),
               at("Reading", "18:00", "19:00", "personal", task_id="rd")]
    llm = StubLLM(adj(updated))
    out = await generate_adjustment(ACTIVE, "new_event", "4:30pm team sync", date=DAY, llm=llm, now=lambda: FIXED_NOW)
    assert llm.calls[0]["schema"] is AdjustmentLLMSchema
    assert [x.task_id for x in out.updated_schedule if x.task_id in {"lc", "ml", "rd"}] == ["lc", "ml", "rd"]
    assert all(x.task_id for x in out.updated_schedule)
    assert out.message == "Moved things around."


async def test_adjustment_restores_dropped_calendar_event_and_injects_new_event():
    updated = [at("Leetcode Practice", "09:00", "11:00", task_id="lc"),
               at("Study", "13:00", "17:00", "study"),                       # paved over ML Class
               at("Reading", "17:00", "18:00", "personal", task_id="rd")]
    new = [cal_event("Dentist", "11:30", "12:30", id="d")]
    out = await generate_adjustment(ACTIVE, "new_event", "dentist 11:30", date=DAY, new_events=new,
                                    llm=StubLLM(adj(updated)), now=lambda: FIXED_NOW)
    titles = [x.title for x in out.updated_schedule]
    assert "ML Class" in titles and "Dentist" in titles and "Study" not in titles
    assert validate_tasks(out.updated_schedule, DAY) == []


async def test_adjustment_resolves_overlaps_and_underscore_timestamps():
    updated = [{**at("Leetcode Practice", "09:00", "11:00", task_id="lc"), "start_time": "2026_11_20T09:00:00"},
               at("Walk", "10:00", "11:30", "exercise"),
               at("ML Class", "14:00", "16:00", "calendar_event", "Library", "ml")]
    out = await generate_adjustment(ACTIVE, "energy_update", "tired", date=DAY,
                                    llm=StubLLM(adj(updated)), now=lambda: FIXED_NOW)
    assert validate_tasks(out.updated_schedule, DAY) == []


async def test_adjustment_two_failures_raise_instead_of_returning_old_schedule():
    llm = StubLLM("nope", "still nope")
    with pytest.raises(GenerationFailed):
        await generate_adjustment(ACTIVE, "task_overrun", "ran over", date=DAY, llm=llm, now=lambda: FIXED_NOW)
    assert len(llm.calls) == 2


async def test_adjustment_retry_then_success():
    good = adj([at("Leetcode Practice", "09:00", "11:00", task_id="lc"),
                at("ML Class", "14:00", "16:00", "calendar_event", "Library", "ml")])
    llm = StubLLM({"what_changed": "oops"}, good)
    out = await generate_adjustment(ACTIVE, "task_overrun", "ran over", date=DAY, llm=llm, now=lambda: FIXED_NOW)
    assert len(llm.calls) == 2 and len(out.updated_schedule) == 2
