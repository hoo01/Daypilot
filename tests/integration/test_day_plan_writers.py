"""The schedule HTTP endpoints read and write only through DayPlanService.

Covers /schedule/confirm (incl. R10), /schedule/today and /schedule/day.
"""
import json
from datetime import datetime

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from api.routes import schedule as schedule_routes
from db.collections import Collections
from schemas.day_plan import DayPlanStatus, GeneratedPlan, GeneratePlan, ConfirmProposal
from schemas.schedule import ScheduleInput
from services.day_plan_repository import DayPlanRepository
from services.day_plan_service import DayPlanService, today_for
from tests.fixtures.day_plan import schedule_output, task, three_strategies

USER = "writer_user"


@pytest.fixture
def today():
    return today_for(USER)


@pytest.fixture
async def client(test_db):
    app = FastAPI()
    app.include_router(schedule_routes.router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def _gen(req):
    return GeneratedPlan(output=schedule_output(req.date, strategies=three_strategies(req.date)),
                         input=ScheduleInput(user_id=req.user_id, date=req.date))


def _service(test_db):
    return DayPlanService(DayPlanRepository(test_db), plan_generator=_gen, now=lambda: datetime(2000, 1, 1))


async def _propose(test_db, day):
    return await _service(test_db).handle(GeneratePlan(user_id=USER, date=day))


# ── /schedule/confirm ────────────────────────────────────────────────────────

async def test_R10_confirm_ignores_client_supplied_tasks_new_payload(client, test_db, today):
    proposed = await _propose(test_db, today)
    resp = await client.post("/schedule/confirm", json={
        "user_id": USER, "date": today, "proposal_id": proposed.proposal.proposal_id,
        "strategy_name": "Fastest",
        "tasks": [{"task_id": "evil", "title": "FORGED"}],
        "updated_schedule": [{"task_id": "evil", "title": "FORGED"}],
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "confirmed"
    assert body["day_plan"]["active"]["strategy_name"] == "Fastest"
    plan = await DayPlanRepository(test_db).get(USER, today)
    assert [t.title for t in plan.active.tasks] == ["Leetcode Practice"]


async def test_confirm_without_db_proposal_is_rejected_and_writes_nothing(client, test_db, today):
    resp = await client.post("/schedule/confirm", json={
        "user_id": USER, "date": today, "proposal_id": "anything", "strategy_name": "Adjusted",
        "updated_schedule": [task("FORGED", "09:00", "10:00", day=today).model_dump()]})
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "invalid_transition"
    assert await test_db[Collections.DAILY_SCHEDULES].count_documents({}) == 0


async def test_confirm_requires_proposal_id_and_date(client, test_db, today):
    await _propose(test_db, today)
    legacy = await client.post("/schedule/confirm", json={
        "user_id": USER, "target_date": today, "proposal_type": "plan",
        "proposal": {"top_recommendation": "Most Relaxed"}})
    assert legacy.status_code == 422
    assert (await DayPlanRepository(test_db).get(USER, today)).active is None


# ── /schedule/today and /schedule/day ────────────────────────────────────────

async def test_today_returns_active_tasks_only(client, test_db, today):
    await _propose(test_db, today)
    assert (await client.get("/schedule/today", params={"user_id": USER})).status_code == 404
    await _service(test_db).handle(ConfirmProposal(user_id=USER, date=today, strategy_name="Most Relaxed"))
    resp = await client.get("/schedule/today", params={"user_id": USER})
    assert resp.status_code == 200
    tasks = resp.json()["tasks"]
    assert [t["title"] for t in tasks] == ["Reading", "Walk"]
    assert all(t["geo_segment"] is None for t in tasks)


async def test_today_reads_legacy_confirmed_document(client, test_db, today):
    await test_db[Collections.DAILY_SCHEDULES].insert_one({
        "user_id": USER, "date": today, "confirmed": True, "strategy_name": "Most Relaxed",
        "tasks": [task("Reading", "10:00", "11:00", day=today).model_dump()]})
    resp = await client.get("/schedule/today", params={"user_id": USER})
    assert [t["title"] for t in resp.json()["tasks"]] == ["Reading"]


async def test_day_endpoint_returns_full_day_plan(client, test_db, today):
    await _propose(test_db, today)
    resp = await client.get("/schedule/day", params={"user_id": USER, "date": today})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "PROPOSED"
    assert body["proposal"]["top_recommendation"] == "Most Productive"
    empty = await client.get("/schedule/day", params={"user_id": USER, "date": "2030-01-01"})
    assert empty.json()["status"] == "EMPTY"
