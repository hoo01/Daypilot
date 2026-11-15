"""Phase 2 — the coordinator-facing tools are thin wrappers: pure generator + DayPlanService.

The module-level LLM call is replaced by a stub (dependency injection by module attribute).
"""
import json

import pytest

from agents.tools import realtime_tools, schedule_tools
from db.collections import Collections
from schemas.day_plan import ConfirmProposal, DayPlanStatus
from services.day_plan_repository import DayPlanRepository
from services.day_plan_service import DayPlanService, today_for

USER = "wrapper_user"


def _t(day, title, start, end, type="deep_work", location=None, task_id=None):
    return {"title": title, "start_time": f"{day}T{start}:00", "end_time": f"{day}T{end}:00",
            "type": type, "location": location, "notes": None, "task_id": task_id}


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
def stub_llm(monkeypatch):
    calls = []
    queue = []

    async def fake(model, prompt, schema):
        calls.append(schema)
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item if isinstance(item, str) else json.dumps(item)

    monkeypatch.setattr(schedule_tools, "_llm_json", fake)
    monkeypatch.setattr(realtime_tools, "_llm_json", fake)
    return queue, calls


async def test_plan_schedule_tool_stores_proposal_via_service(test_db, today, stub_llm):
    queue, _ = stub_llm
    queue.append(_plan_payload(today))
    result = await schedule_tools.plan_schedule(USER, calendar_events=[
        {"title": "ML Class", "start_time": f"{today}T14:00:00", "end_time": f"{today}T16:00:00", "location": "Lib"}])
    assert not result.get("error")
    plan = await DayPlanRepository(test_db).get(USER, today)
    assert plan.status == DayPlanStatus.PROPOSED
    assert plan.proposal.top_recommendation == "Most Relaxed"
    # the user-mentioned event was injected by code even though the LLM omitted it
    for s in plan.proposal.strategies:
        assert any(t.title == "ML Class" and t.location == "Lib" for t in s.tasks)


async def test_R8_plan_schedule_tool_failure_writes_nothing(test_db, today, stub_llm):
    queue, calls = stub_llm
    queue.extend(["garbage", "more garbage"])
    result = await schedule_tools.plan_schedule(USER)
    assert result["error"] is True and result["strategies"] == []
    assert len(calls) == 2
    assert await test_db[Collections.DAILY_SCHEDULES].count_documents({}) == 0


async def test_adjust_schedule_tool_uses_generator_and_service(test_db, today, stub_llm):
    queue, _ = stub_llm
    queue.append(_plan_payload(today))
    await schedule_tools.plan_schedule(USER)
    await DayPlanService(DayPlanRepository(test_db)).handle(
        ConfirmProposal(user_id=USER, date=today, strategy_name="Most Productive"))
    queue.append({"what_changed": ["added sync"], "dropped_tasks": [], "added_tasks": ["Sync"],
                  "updated_schedule": [_t(today, "Leetcode Practice", "09:00", "11:00"),
                                       _t(today, "Sync", "15:00", "16:00", "calendar_event")],
                  "message": "Added Sync at 3pm."})
    result = await realtime_tools.adjust_schedule(USER, [], "new_event", "3pm sync")
    assert not result.get("error")
    plan = await DayPlanRepository(test_db).get(USER, today)
    assert plan.status == DayPlanStatus.CONFIRMED_WITH_PROPOSAL
    assert plan.proposal.kind == "adjust" and plan.proposal.explanation == "Added Sync at 3pm."
    assert plan.active.strategy_name == "Most Productive"


async def test_adjust_schedule_tool_failure_writes_nothing(test_db, today, stub_llm):
    queue, _ = stub_llm
    queue.append(_plan_payload(today))
    await schedule_tools.plan_schedule(USER)
    confirmed = await DayPlanService(DayPlanRepository(test_db)).handle(
        ConfirmProposal(user_id=USER, date=today, strategy_name="Most Productive"))
    queue.extend(["bad", "bad"])
    result = await realtime_tools.adjust_schedule(USER, [], "task_overrun", "ran over")
    assert result["error"] is True
    after = await DayPlanRepository(test_db).get(USER, today)
    assert after.version == confirmed.version and after.proposal is None
