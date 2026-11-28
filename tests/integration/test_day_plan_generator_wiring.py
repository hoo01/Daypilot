"""Phase 5 — DayPlanService's production generators (build_plan / build_adjustment).

Context sources (health, goals, relationships) and the LLM are stubbed; the code-owned
input assembly and the service write path run for real against the test Mongo.
"""
import json
from datetime import datetime

import pytest

from agents.tools import goal_tools, health_tools, realtime_tools, relationship_tools, schedule_tools
from db.collections import Collections
from schemas.day_plan import AdjustPlan, ConfirmProposal, DayPlanStatus, GenerationFailed, GeneratePlan, PlanRequest
from schemas.schedule import CalendarEvent
from services.day_plan_repository import DayPlanRepository
from services.day_plan_service import DayPlanService, today_for

USER = "wiring_user"


def _t(day, title, start, end, type="deep_work", location=None):
    return {"title": title, "start_time": f"{day}T{start}:00", "end_time": f"{day}T{end}:00",
            "type": type, "location": location, "notes": None}


def _plan_payload(day):
    def s(name, tasks):
        return {"name": name, "description": "", "tasks": tasks, "total_focus_hours": 1.0, "reasoning": ""}
    return {"strategies": [
        s("Most Productive", [_t(day, "Leetcode Practice", "09:00", "11:00")]),
        s("Most Relaxed", [_t(day, "Reading", "10:00", "11:00", "personal")]),
        s("Fastest", [_t(day, "Leetcode Practice", "08:00", "09:00")]),
    ], "top_recommendation": "Most Relaxed", "warnings": []}


@pytest.fixture
def today():
    return today_for(USER)


@pytest.fixture
def stubs(monkeypatch, today):
    prompts, queue = [], []

    # Pin "now" to early morning so today's 23:00 events are never filtered out as past.
    pinned = datetime.fromisoformat(f"{today}T00:05:00")

    class PinnedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return pinned

    monkeypatch.setattr(schedule_tools, "datetime", PinnedDatetime)
    monkeypatch.setattr(realtime_tools, "datetime", PinnedDatetime)

    async def fake_llm(model, prompt, schema):
        prompts.append(prompt)
        item = queue.pop(0)
        return item if isinstance(item, str) else json.dumps(item)

    async def fake_health(user_id):
        return {"energy_level": "high", "focus_window": "9AM-12PM", "cognitive_load_score": 0.8, "avoid_tasks": []}

    async def fake_goals(user_id):
        return {"goals": [{"name": "Leetcode"}], "summary": "2 problems left"}

    async def fake_rel(user_id):
        return {
            "today_calendar_events": [{"title": "ML Class", "start_time": f"{today}T23:00:00",
                                       "end_time": f"{today}T23:45:00", "location": "Library"}],
            "upcoming_events": [{"event": "Mom's birthday", "date": today, "days_away": 0}],
        }

    monkeypatch.setattr(schedule_tools, "_llm_json", fake_llm)
    monkeypatch.setattr(realtime_tools, "_llm_json", fake_llm)
    monkeypatch.setattr(health_tools, "analyze_health", fake_health)
    monkeypatch.setattr(goal_tools, "track_goals", fake_goals)
    monkeypatch.setattr(relationship_tools, "get_relationship_context", fake_rel)
    return queue, prompts


async def test_build_schedule_input_is_assembled_by_code(test_db, today, stubs):
    new = CalendarEvent(id="d", title="Dentist", start_time=f"{today}T22:00:00", end_time=f"{today}T22:30:00")
    inp, goal_context, notes = await schedule_tools.build_schedule_input(
        PlanRequest(user_id=USER, date=today, new_events=[new]))
    assert [(e.title, e.location) for e in inp.calendar_events] == [("ML Class", "Library"), ("Dentist", None)]
    assert inp.health.energy_level == "high"
    assert goal_context["summary"] == "2 problems left"
    assert notes == ["Mom's birthday"]


async def test_google_calendar_events_only_apply_to_today(test_db, today, stubs):
    inp, _, _ = await schedule_tools.build_schedule_input(PlanRequest(user_id=USER, date="2099-01-01"))
    assert inp.calendar_events == []


async def test_default_service_generates_with_calendar_events_injected(test_db, today, stubs):
    queue, prompts = stubs
    queue.append(_plan_payload(today))          # the LLM forgets ML Class entirely
    service = DayPlanService(DayPlanRepository(test_db), now=lambda: datetime.fromisoformat(f"{today}T00:05:00"))
    plan = await service.handle(GeneratePlan(user_id=USER, date=today, focus_tasks=["Lab report"]))
    assert plan.status == DayPlanStatus.PROPOSED
    assert "Lab report" in prompts[0] and "ML Class" in prompts[0]
    for s in plan.proposal.strategies:
        assert any(t.title == "ML Class" and t.location == "Library" for t in s.tasks)


async def test_default_service_generation_failure_writes_nothing(test_db, today, stubs):
    queue, prompts = stubs
    queue.extend(["garbage", "still garbage"])
    with pytest.raises(GenerationFailed):
        await DayPlanService(DayPlanRepository(test_db), now=lambda: datetime.fromisoformat(f"{today}T00:05:00")).handle(GeneratePlan(user_id=USER, date=today))
    assert len(prompts) == 2
    assert await test_db[Collections.DAILY_SCHEDULES].count_documents({}) == 0


async def test_default_service_adjusts_from_stored_active_plan(test_db, today, stubs):
    queue, prompts = stubs
    queue.append(_plan_payload(today))
    service = DayPlanService(DayPlanRepository(test_db), now=lambda: datetime.fromisoformat(f"{today}T00:05:00"))
    await service.handle(GeneratePlan(user_id=USER, date=today))
    await service.handle(ConfirmProposal(user_id=USER, date=today, strategy_name="Most Productive"))
    queue.append({"what_changed": ["added sync"], "dropped_tasks": [], "added_tasks": ["Sync"],
                  "updated_schedule": [{**_t(today, "Leetcode Practice", "09:00", "11:00"), "task_id": None}],
                  "message": "Added your sync."})
    sync = CalendarEvent(id="s", title="Sync", start_time=f"{today}T23:00:00", end_time=f"{today}T23:30:00")
    plan = await service.handle(AdjustPlan(user_id=USER, date=today, trigger="new_event", detail="sync at 11pm",
                                           new_events=[sync]))
    assert '"Leetcode Practice"' in prompts[-1]          # the stored active plan was sent to LLM②
    assert plan.proposal.kind == "adjust" and plan.proposal.explanation == "Added your sync."
    assert any(t.title == "Sync" for t in plan.proposal.strategies[0].tasks)
    assert plan.active.strategy_name == "Most Productive"
