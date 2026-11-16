"""The X-Timezone request header drives "today"/"now" end to end (routes → orchestrator → service).

UTC is pinned to 2026-11-16 03:39 — still 2026-11-15 19:39 for a user in Los Angeles.
"""
import json
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import config
from agents.intent import parse_intent
from api.routes import chat as chat_routes
from api.routes import schedule as schedule_routes
from schemas.day_plan import GeneratedPlan
from schemas.schedule import ScheduleInput
from services import clock
from services.day_plan_repository import DayPlanRepository
from services.day_plan_service import DayPlanService, PreferencesPendingStore
from services.turn_orchestrator import TurnOrchestrator
from tests.fixtures.day_plan import schedule_output, three_strategies

USER = "tz_user"
LA = {"X-Timezone": "America/Los_Angeles"}
TOKYO = {"X-Timezone": "Asia/Tokyo"}


@pytest.fixture
def app(test_db, monkeypatch):
    monkeypatch.setattr(clock, "_utcnow", lambda: datetime(2026, 11, 16, 3, 39, tzinfo=timezone.utc))
    monkeypatch.setattr(config.settings, "default_timezone", "")

    async def _no_consolidation(*a, **k):
        return None
    monkeypatch.setattr(chat_routes, "_consolidate_memory", _no_consolidation)

    plan_calls = []

    async def plan_gen(req):
        plan_calls.append(req)
        return GeneratedPlan(output=schedule_output(req.date, strategies=three_strategies(req.date)),
                             input=ScheduleInput(user_id=req.user_id, date=req.date))

    async def intent_llm(model, prompt, schema):
        return json.dumps({"type": "plan_day", "target_date": None, "focus_tasks": [], "trigger": None,
                           "detail": None, "strategy_name": None,
                           "new_events": [{"title": "Assignment 7", "start_time": None, "end_time": None,
                                           "time_hint": "now", "duration_minutes": None, "location": None}]})

    async def chat_agent(user_id, session_id, message):
        return "unused"

    # No `now=` overrides: the defaults must follow the request timezone.
    service = DayPlanService(DayPlanRepository(test_db), plan_generator=plan_gen,
                             pending_store=PreferencesPendingStore(test_db))
    orchestrator = TurnOrchestrator(service, chat_responder=chat_agent,
                                    intent_parser=lambda m, ctx: parse_intent(m, ctx, llm=intent_llm))
    a = FastAPI()
    a.include_router(chat_routes.router)
    a.include_router(schedule_routes.router)
    a.state.turn_orchestrator = orchestrator
    a.state.plan_calls = plan_calls
    return a


@pytest.fixture
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_day_endpoint_uses_the_client_timezone(client):
    la = await client.get("/schedule/day", params={"user_id": USER}, headers=LA)
    tokyo = await client.get("/schedule/day", params={"user_id": USER}, headers=TOKYO)
    assert la.json()["date"] == "2026-11-15"
    assert tokyo.json()["date"] == "2026-11-16"


async def test_without_header_falls_back_to_server_time(client):
    expected = datetime.fromtimestamp(datetime(2026, 11, 16, 3, 39, tzinfo=timezone.utc).timestamp()).date()
    r = await client.get("/schedule/day", params={"user_id": USER})
    assert r.json()["date"] == expected.isoformat()


async def test_evening_plan_is_filed_under_the_users_today(client, app, test_db):
    r = await client.post("/chat/", json={"user_id": USER, "message": "plan my day, I need to do assignment 7 now",
                                          "session_id": "s"}, headers=LA)
    body = r.json()
    assert body["error"] is None
    assert body["day_plan"]["date"] == "2026-11-15"
    req = app.state.plan_calls[-1]
    assert req.date == "2026-11-15"
    # "now" is the user's 19:39, rounded up to the next quarter hour
    assert [(e.title, e.start_time) for e in req.new_events] == [("Assignment 7", "2026-11-15T19:45:00")]

    # and the Today endpoint, asked from the same timezone, sees that plan once confirmed
    pid = body["day_plan"]["proposal"]["proposal_id"]
    c = await client.post("/schedule/confirm", json={"user_id": USER, "date": "2026-11-15", "proposal_id": pid},
                          headers=LA)
    assert c.status_code == 200
    today = await client.get("/schedule/today", params={"user_id": USER}, headers=LA)
    assert today.status_code == 200 and today.json()["tasks"]
    assert (await client.get("/schedule/today", params={"user_id": USER}, headers=TOKYO)).status_code == 404
