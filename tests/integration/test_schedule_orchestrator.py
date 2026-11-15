"""Phase 3 — regression scenarios R1–R10 (docs/refactor/schedule_orchestrator.md §9.2).

Every turn goes through POST /chat/ → TurnOrchestrator → DayPlanService → repository,
with LLM① (intent), LLM② (generators) and the read-only chat agent replaced by stubs.
No network: memory consolidation is patched out as well.
"""
import json
from datetime import date as _date, datetime, timedelta

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from agents.intent import parse_intent
from agents.tools.realtime_tools import generate_adjustment
from agents.tools.schedule_tools import generate_schedule
from api.routes import chat as chat_routes
from api.routes import schedule as schedule_routes
from db.collections import Collections
from schemas.day_plan import ActivePlan, GeneratedPlan
from schemas.schedule import CalendarEvent, ScheduleInput
from services.day_plan_repository import DayPlanRepository
from services.day_plan_service import DayPlanService, PreferencesPendingStore, today_for
from services.turn_orchestrator import TurnOrchestrator
from tests.fixtures.day_plan import schedule_output, three_strategies

USER = "orch_user"
TODAY = today_for(USER)
TOMORROW = (_date.fromisoformat(TODAY) + timedelta(days=1)).isoformat()
NOW = datetime.fromisoformat(f"{TODAY}T08:00:00")


def flat(**kw):
    base = {"type": "chat", "target_date": None, "new_events": [], "focus_tasks": [], "trigger": None,
            "detail": None, "strategy_name": None}
    base.update(kw)
    return base


class IntentLLM:
    """LLM① stub: maps the user's message to a scripted flat intent JSON."""

    def __init__(self):
        self.script: dict[str, object] = {}
        self.calls = 0

    async def __call__(self, model, prompt, schema):
        self.calls += 1
        message = prompt.rsplit("User message:", 1)[1].strip().strip('"')
        r = self.script.get(message, flat())
        if isinstance(r, Exception):
            raise r
        return r if isinstance(r, str) else json.dumps(r)


class PlanGen:
    """LLM② stub at the PlanGenerator seam (records requests)."""

    def __init__(self):
        self.calls = []
        self.impl = None

    async def __call__(self, req):
        self.calls.append(req)
        if self.impl:
            return await self.impl(req)
        inp = ScheduleInput(user_id=req.user_id, date=req.date, calendar_events=list(req.new_events))
        return GeneratedPlan(output=schedule_output(req.date, strategies=three_strategies(req.date)), input=inp)


class ChatAgent:
    def __init__(self):
        self.calls = []

    async def __call__(self, user_id, session_id, message):
        self.calls.append(message)
        return "Focus on Leetcode this morning — your energy peaks before noon."


class AdjustLLM:
    """LLM② stub for adjustments: echoes the current schedule (drops nothing, adds nothing).
    Code must still inject the new fixed event."""

    def __init__(self):
        self.calls = 0

    async def __call__(self, model, prompt, schema):
        self.calls += 1
        current = json.loads(prompt.split("Current schedule:", 1)[1])
        return json.dumps({"what_changed": ["made room for the new meeting"], "dropped_tasks": [],
                           "added_tasks": [], "updated_schedule": current,
                           "message": "I added your meeting and moved things around it."})


@pytest.fixture
def world(test_db, monkeypatch):
    async def _no_consolidation(*a, **k):
        return None
    monkeypatch.setattr(chat_routes, "_consolidate_memory", _no_consolidation)

    intent_llm, plan_gen, chat_agent, adjust_llm = IntentLLM(), PlanGen(), ChatAgent(), AdjustLLM()

    async def adjust_gen(req):
        return await generate_adjustment(req.active_tasks, req.trigger, req.detail, date=req.date,
                                         new_events=req.new_events, llm=adjust_llm, now=lambda: NOW)

    service = DayPlanService(DayPlanRepository(test_db), plan_generator=plan_gen, adjust_generator=adjust_gen,
                             pending_store=PreferencesPendingStore(test_db), now=lambda: NOW)
    orchestrator = TurnOrchestrator(
        service,
        intent_parser=lambda message, ctx: parse_intent(message, ctx, llm=intent_llm),
        chat_responder=chat_agent,
        now=lambda: NOW,
    )
    app = FastAPI()
    app.include_router(chat_routes.router)
    app.include_router(schedule_routes.router)
    app.state.turn_orchestrator = orchestrator

    class W:
        pass
    w = W()
    w.app, w.db, w.service, w.intent, w.plan_gen, w.chat_agent, w.adjust_llm = (
        app, test_db, service, intent_llm, plan_gen, chat_agent, adjust_llm)
    w.repo = DayPlanRepository(test_db)
    return w


@pytest.fixture
async def client(world):
    async with AsyncClient(transport=ASGITransport(app=world.app), base_url="http://test") as c:
        yield c


async def say(client, message):
    resp = await client.post("/chat/", json={"user_id": USER, "message": message, "session_id": "s1"})
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _plan_and_confirm(world, client, strategy="Most Relaxed"):
    world.intent.script["plan my day"] = flat(type="plan_day")
    world.intent.script[f"go with {strategy}"] = flat(type="confirm", strategy_name=strategy)
    await say(client, "plan my day")
    return await say(client, f"go with {strategy}")


async def _snapshot(db):
    docs = await db[Collections.DAILY_SCHEDULES].find({}, {"_id": 0}).to_list(None)
    prefs = await db[Collections.USER_PREFERENCES].find({}, {"_id": 0}).to_list(None)
    return docs, prefs


# ── R1 ───────────────────────────────────────────────────────────────────────

async def test_R1_plan_again_after_confirm_creates_proposal_and_keeps_active(world, client):
    confirmed = await _plan_and_confirm(world, client, "Most Relaxed")
    assert confirmed["day_plan"]["status"] == "CONFIRMED"
    body = await say(client, "plan my day")
    plan = body["day_plan"]
    assert plan["status"] == "CONFIRMED_WITH_PROPOSAL"
    assert plan["active"] == confirmed["day_plan"]["active"]
    assert plan["proposal"]["kind"] == "plan"
    assert body["error"] is None


# ── R2 ───────────────────────────────────────────────────────────────────────

async def test_R2_natural_confirmation_phrase_confirms_named_strategy(world, client):
    world.intent.script["plan my day"] = flat(type="plan_day")
    world.intent.script["let's go with most relaxed"] = flat(type="confirm", strategy_name="most relaxed")
    await say(client, "plan my day")
    body = await say(client, "let's go with most relaxed")
    plan = body["day_plan"]
    assert plan["status"] == "CONFIRMED"
    assert plan["active"]["strategy_name"] == "Most Relaxed"
    assert plan["proposal"] is None
    assert "Most Relaxed" in body["reply"]
    stored = await world.repo.get(USER, TODAY)
    assert stored.active.strategy_name == "Most Relaxed" and stored.proposal is None


# ── R3 ───────────────────────────────────────────────────────────────────────

async def test_R3_confirm_without_proposal_is_invalid_transition(world, client):
    world.intent.script["confirm"] = flat(type="confirm")
    before = await _snapshot(world.db)
    body = await say(client, "confirm")
    assert body["error"]["code"] == "invalid_transition"
    assert body["day_plan"]["status"] == "EMPTY"
    assert await _snapshot(world.db) == before
    assert world.chat_agent.calls == [], "the LLM must not be asked to improvise a confirmation"


# ── R4 ───────────────────────────────────────────────────────────────────────

async def test_R4_new_event_on_confirmed_day_proposes_adjust_then_confirm_applies(world, client):
    confirmed = await _plan_and_confirm(world, client, "Most Relaxed")
    world.intent.script["add a meeting at 3"] = flat(
        type="adjust", trigger="new_event", detail="meeting at 3pm",
        new_events=[{"title": "Meeting", "start_time": "15:00", "end_time": None, "time_hint": None,
                     "duration_minutes": None, "location": None}])
    body = await say(client, "add a meeting at 3")
    plan = body["day_plan"]
    assert plan["status"] == "CONFIRMED_WITH_PROPOSAL"
    assert plan["active"] == confirmed["day_plan"]["active"], "active must not change before confirmation"
    proposal = plan["proposal"]
    assert proposal["kind"] == "adjust"
    adjusted = proposal["strategies"][0]["tasks"]
    meeting = [t for t in adjusted if t["title"] == "Meeting"]
    assert meeting and meeting[0]["start_time"] == f"{TODAY}T15:00:00" and meeting[0]["end_time"] == f"{TODAY}T17:00:00"
    # legacy compat field is derived from state
    assert body["pending_proposal"]["type"] == "adjust"
    assert body["pending_proposal"]["proposal_id"] == proposal["proposal_id"]

    resp = await client.post("/schedule/confirm", json={
        "user_id": USER, "date": TODAY, "proposal_id": proposal["proposal_id"], "strategy_name": "Adjusted"})
    assert resp.status_code == 200, resp.text
    stored = await world.repo.get(USER, TODAY)
    assert stored.active.strategy_name == "Adjusted"
    assert "Meeting" in [t.title for t in stored.active.tasks]
    assert stored.proposal is None


async def test_R4b_adjust_without_active_is_invalid_transition(world, client):
    world.intent.script["add a meeting at 3"] = flat(type="adjust", trigger="new_event", detail="meeting at 3pm")
    body = await say(client, "add a meeting at 3")
    assert body["error"]["code"] == "invalid_transition"
    assert body["day_plan"]["status"] == "EMPTY"
    assert world.adjust_llm.calls == 0


# ── R5 ───────────────────────────────────────────────────────────────────────

async def test_R5_confirming_stale_adjust_is_rejected(world, client):
    await _plan_and_confirm(world, client, "Most Relaxed")
    world.intent.script["add a meeting at 3"] = flat(
        type="adjust", trigger="new_event", detail="meeting at 3pm",
        new_events=[{"title": "Meeting", "start_time": "15:00", "end_time": "16:00", "time_hint": None,
                     "duration_minutes": None, "location": None}])
    await say(client, "add a meeting at 3")
    # active changes underneath the pending adjust proposal (another device)
    current = await world.repo.get(USER, TODAY)
    changed = await world.repo.save(current.model_copy(update={"active": ActivePlan(
        strategy_name="Fastest", tasks=three_strategies(TODAY)[2].tasks, confirmed_at="x")}), current.version)

    world.intent.script["yes"] = flat(type="confirm")
    body = await say(client, "yes")
    assert body["error"]["code"] == "concurrent_modification"
    after = await world.repo.get(USER, TODAY)
    assert after.version == changed.version and after.active.strategy_name == "Fastest"


# ── R6 ───────────────────────────────────────────────────────────────────────

async def test_R6_reschedule_missed_tasks_to_tomorrow(world, client):
    await world.db[Collections.USER_PREFERENCES].insert_one({"user_id": USER, "pending_reschedule": {
        "tasks": ["Leetcode Practice", "Lab report"], "original_date": TODAY, "suggested_date": TOMORROW}})
    world.intent.script["sure, move them to tomorrow"] = flat(type="reschedule_missed", target_date=None)
    body = await say(client, "sure, move them to tomorrow")
    plan = body["day_plan"]
    assert plan["date"] == TOMORROW
    assert plan["status"] == "PROPOSED"
    assert plan["proposal"]["consumes_pending_reschedule"] is True
    assert world.plan_gen.calls[-1].focus_tasks == ["Leetcode Practice", "Lab report"]
    prefs = await world.db[Collections.USER_PREFERENCES].find_one({"user_id": USER})
    assert prefs["pending_reschedule"] is not None, "only confirmation consumes pending_reschedule"

    # confirming via chat: the orchestrator targets the plan that holds the proposal (tomorrow)
    world.intent.script["take the fastest one"] = flat(type="confirm", strategy_name="Fastest")
    body = await say(client, "take the fastest one")
    assert body["day_plan"]["date"] == TOMORROW and body["day_plan"]["status"] == "CONFIRMED"
    prefs = await world.db[Collections.USER_PREFERENCES].find_one({"user_id": USER})
    assert prefs["pending_reschedule"] is None


async def test_R6b_reschedule_without_pending_is_invalid_transition(world, client):
    world.intent.script["reschedule my missed tasks"] = flat(type="reschedule_missed")
    body = await say(client, "reschedule my missed tasks")
    assert body["error"]["code"] == "invalid_transition"
    assert world.plan_gen.calls == []


# ── R7 ───────────────────────────────────────────────────────────────────────

async def test_R7_messy_generator_output_is_repaired_before_it_is_stored(world, client):
    ml = CalendarEvent(id="ml", title="ML Class", start_time=f"{TOMORROW}T14:00:00",
                       end_time=f"{TOMORROW}T16:00:00", location="Library")

    def t(title, start, end, type="deep_work", location=None):
        return {"title": title, "start_time": f"{TOMORROW}T{start}:00", "end_time": f"{TOMORROW}T{end}:00",
                "type": type, "location": location, "notes": None}

    messy = {"strategies": [
        {"name": "Most Productive", "description": "", "total_focus_hours": 3, "reasoning": "", "tasks": [
            {**t("Leetcode Practice", "09:00", "11:00"), "start_time": TOMORROW.replace("-", "_") + "T09:00:00"},
            t("Deep Work", "10:00", "12:00"),
            t("Event", "14:00", "16:00", "calendar_event")]},
        {"name": "Most Relaxed", "description": "", "total_focus_hours": 1, "reasoning": "", "tasks": [
            t("Reading", "10:00", "11:00", "personal")]},
    ], "top_recommendation": "Most Relaxed", "warnings": []}

    async def llm(model, prompt, schema):
        return json.dumps(messy)

    async def real_generator(req):
        inp = ScheduleInput(user_id=req.user_id, date=req.date, calendar_events=[ml])
        return GeneratedPlan(output=await generate_schedule(inp, llm=llm, now=lambda: NOW), input=inp)

    world.plan_gen.impl = real_generator
    world.intent.script["plan tomorrow"] = flat(type="plan_day", target_date=TOMORROW)
    body = await say(client, "plan tomorrow")
    assert body["error"] is None
    stored = await world.repo.get(USER, TOMORROW)
    from services.day_plan_invariants import missing_fixed_blocks, validate_tasks
    from services.day_plan_invariants import calendar_event_to_task
    for s in stored.proposal.strategies:
        assert validate_tasks(s.tasks, TOMORROW) == []
        assert missing_fixed_blocks(s.tasks, [calendar_event_to_task(ml)]) == []
        assert not any(x.title == "Event" for x in s.tasks)


# ── R8 ───────────────────────────────────────────────────────────────────────

async def test_R8_generation_failure_returns_error_and_writes_nothing(world, client):
    calls = []

    async def broken_llm(model, prompt, schema):
        calls.append(1)
        return "Sorry, here is your schedule: 9pm-11pm deep work"

    async def real_generator(req):
        inp = ScheduleInput(user_id=req.user_id, date=req.date)
        return GeneratedPlan(output=await generate_schedule(inp, llm=broken_llm, now=lambda: NOW), input=inp)

    world.plan_gen.impl = real_generator
    world.intent.script["plan my day"] = flat(type="plan_day")
    body = await say(client, "plan my day")
    assert len(calls) == 2, "exactly one retry"
    assert body["error"]["code"] == "generation_failed"
    assert body["day_plan"]["status"] == "EMPTY"
    assert body["pending_proposal"] is None
    assert await world.db[Collections.DAILY_SCHEDULES].count_documents({}) == 0
    assert "9pm" not in body["reply"].lower()


# ── R9 ───────────────────────────────────────────────────────────────────────

async def test_R9_open_question_goes_to_read_only_agent_without_db_writes(world, client):
    await _plan_and_confirm(world, client, "Most Relaxed")
    world.intent.script["what should I focus on today?"] = flat(type="chat")
    before = await _snapshot(world.db)
    body = await say(client, "what should I focus on today?")
    assert world.chat_agent.calls == ["what should I focus on today?"]
    assert body["reply"].startswith("Focus on Leetcode")
    assert body["day_plan"]["status"] == "CONFIRMED"
    assert body["error"] is None and body["schedule_updated"] is False
    assert await _snapshot(world.db) == before


async def test_R9b_intent_parser_failure_degrades_to_chat(world, client):
    world.intent.script["???"] = RuntimeError("model unavailable")
    before = await _snapshot(world.db)
    body = await say(client, "???")
    assert world.chat_agent.calls == ["???"]
    assert await _snapshot(world.db) == before
    assert body["error"] is None


# ── R10 ──────────────────────────────────────────────────────────────────────

async def test_R10_confirm_endpoint_ignores_forged_tasks(world, client):
    world.intent.script["plan my day"] = flat(type="plan_day")
    body = await say(client, "plan my day")
    pid = body["day_plan"]["proposal"]["proposal_id"]
    resp = await client.post("/schedule/confirm", json={
        "user_id": USER, "date": TODAY, "proposal_id": pid, "strategy_name": "Most Relaxed",
        "tasks": [{"title": "FORGED", "start_time": f"{TODAY}T00:00:00", "end_time": f"{TODAY}T23:59:00"}],
        "proposal": {"strategies": [{"name": "Most Relaxed", "tasks": [{"title": "FORGED"}]}]},
    })
    assert resp.status_code == 200
    stored = await world.repo.get(USER, TODAY)
    assert [t.title for t in stored.active.tasks] == ["Reading", "Walk"]


async def test_R10b_confirm_endpoint_rejects_unknown_proposal_id(world, client):
    world.intent.script["plan my day"] = flat(type="plan_day")
    await say(client, "plan my day")
    before = await world.repo.get(USER, TODAY)
    resp = await client.post("/schedule/confirm", json={
        "user_id": USER, "date": TODAY, "proposal_id": "made-up", "strategy_name": "Most Relaxed"})
    assert resp.status_code == 409
    assert (await world.repo.get(USER, TODAY)).version == before.version


# ── Discard + response contract ──────────────────────────────────────────────

async def test_discard_drops_proposal_keeps_active(world, client):
    confirmed = await _plan_and_confirm(world, client)
    await say(client, "plan my day")
    world.intent.script["never mind, keep my current plan"] = flat(type="discard")
    body = await say(client, "never mind, keep my current plan")
    assert body["day_plan"]["status"] == "CONFIRMED"
    assert body["day_plan"]["active"] == confirmed["day_plan"]["active"]


async def test_schedule_turn_reply_is_rendered_by_code_from_state(world, client):
    world.intent.script["plan my day"] = flat(type="plan_day")
    body = await say(client, "plan my day")
    assert body["schedule_updated"] is True
    assert "Most Productive" in body["reply"]          # top recommendation named from state
    assert world.chat_agent.calls == []                  # no LLM text for schedule turns
    assert body["pending_proposal"]["data"]["top_recommendation"] == "Most Productive"


async def test_plan_day_resolves_events_in_code(world, client):
    world.intent.script["plan my day, doctor 3-4pm at the clinic and finish assignment7 this evening"] = flat(
        type="plan_day", new_events=[
            {"title": "Doctor Appointment", "start_time": "3pm", "end_time": "4pm", "time_hint": None,
             "duration_minutes": None, "location": "Clinic"},
            {"title": "assignment7", "start_time": None, "end_time": None, "time_hint": "evening",
             "duration_minutes": None, "location": None}])
    await say(client, "plan my day, doctor 3-4pm at the clinic and finish assignment7 this evening")
    events = world.plan_gen.calls[-1].new_events
    assert [(e.title, e.start_time, e.end_time, e.location) for e in events] == [
        ("Doctor Appointment", f"{TODAY}T15:00:00", f"{TODAY}T16:00:00", "Clinic"),
        ("assignment7", f"{TODAY}T18:00:00", f"{TODAY}T22:00:00", None),
    ]


async def test_plan_for_past_date_is_rejected(world, client):
    world.intent.script["plan last monday"] = flat(type="plan_day", target_date="2001-01-01")
    body = await say(client, "plan last monday")
    assert body["error"]["code"] == "invalid_transition"
    assert world.plan_gen.calls == []


# ── feature flag: legacy path still reachable for rollback ───────────────────

async def test_flag_off_uses_legacy_coordinator_path(world, client, monkeypatch):
    import config

    class Part:
        text = "legacy reply"
        function_response = None

    class Event:
        content = type("C", (), {"parts": [Part()]})()

        def is_final_response(self):
            return True

    class Sessions:
        async def get_session(self, **kw):
            return object()

    class Runner:
        session_service = Sessions()

        async def run_async(self, **kw):
            yield Event()

    world.app.state.runner = Runner()
    monkeypatch.setattr(config.settings, "use_schedule_orchestrator", False)
    body = await say(client, "plan my day")
    assert body["reply"] == "legacy reply"
    assert world.intent.calls == 0
