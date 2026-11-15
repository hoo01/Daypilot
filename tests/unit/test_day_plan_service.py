"""Phase 1 — DayPlanRepository (versioned single writer) and DayPlanService transition rules.

Uses the testcontainers Mongo from conftest. Generators are stubs; no LLM, no network.
"""
import asyncio

import pytest

from db.collections import Collections
from schemas.day_plan import (
    ActivePlan,
    AdjustPlan,
    ConcurrentModification,
    ConfirmProposal,
    DayPlan,
    DayPlanStatus,
    DiscardProposal,
    GeneratedPlan,
    GeneratePlan,
    InvalidTransition,
    InvariantViolation,
    RescheduleMissed,
)
from schemas.realtime import RealtimeOutput
from schemas.schedule import ScheduleInput
from services.day_plan_repository import DayPlanRepository
from services.day_plan_service import DayPlanService
from tests.fixtures.day_plan import (
    DAY,
    FIXED_NOW,
    NEXT_DAY,
    cal_event,
    schedule_output,
    task,
    three_strategies,
)

USER = "svc_user"


class PlanGenStub:
    def __init__(self, outputs=None, calendar=None):
        self.calls = []
        self._outputs = outputs
        self._calendar = calendar or []

    async def __call__(self, req):
        self.calls.append(req)
        day = req.date
        out = self._outputs.pop(0) if self._outputs else schedule_output(day)
        inp = ScheduleInput(user_id=req.user_id, date=day, calendar_events=list(self._calendar) + list(req.new_events))
        return GeneratedPlan(output=out, input=inp)


class AdjustGenStub:
    def __init__(self, updated=None, message="Moved reading to make room."):
        self.calls = []
        self._updated = updated
        self._message = message

    async def __call__(self, req):
        self.calls.append(req)
        tasks = self._updated if self._updated is not None else list(req.active_tasks) + [
            task("Team sync", "17:00", "18:00", type="calendar_event", day=req.date)]
        return RealtimeOutput(what_changed=["added Team sync"], updated_schedule=tasks, message=self._message)


class PendingStub:
    def __init__(self, pending=None):
        self.pending = pending
        self.cleared = 0

    async def get(self, user_id):
        return self.pending

    async def clear(self, user_id):
        self.pending = None
        self.cleared += 1


@pytest.fixture
def repo(test_db):
    return DayPlanRepository(test_db)


@pytest.fixture
def make_service(repo):
    def _make(plan_gen=None, adjust_gen=None, pending=None):
        return DayPlanService(
            repo,
            plan_generator=plan_gen or PlanGenStub(),
            adjust_generator=adjust_gen or AdjustGenStub(),
            pending_store=pending or PendingStub(),
            now=lambda: FIXED_NOW,
        )
    return _make


async def _seed_confirmed(service, strategy="Most Relaxed", day=DAY):
    await service.handle(GeneratePlan(user_id=USER, date=day))
    return await service.handle(ConfirmProposal(user_id=USER, date=day, strategy_name=strategy))


# ── Repository ───────────────────────────────────────────────────────────────

async def test_repository_get_missing_returns_empty(repo):
    plan = await repo.get(USER, DAY)
    assert plan.status == DayPlanStatus.EMPTY and plan.version == 0


async def test_repository_save_increments_version(repo):
    saved = await repo.save(DayPlan(user_id=USER, date=DAY), expected_version=0)
    assert saved.version == 1
    saved2 = await repo.save(saved, expected_version=1)
    assert saved2.version == 2
    assert (await repo.get(USER, DAY)).version == 2


async def test_repository_rejects_stale_version(repo):
    await repo.save(DayPlan(user_id=USER, date=DAY), expected_version=0)
    with pytest.raises(ConcurrentModification):
        await repo.save(DayPlan(user_id=USER, date=DAY), expected_version=0)
    with pytest.raises(ConcurrentModification):
        await repo.save(DayPlan(user_id=USER, date=DAY), expected_version=5)


async def test_repository_concurrent_saves_only_one_wins(repo):
    base = await repo.save(DayPlan(user_id=USER, date=DAY), expected_version=0)
    results = await asyncio.gather(
        repo.save(base, expected_version=base.version),
        repo.save(base, expected_version=base.version),
        return_exceptions=True,
    )
    assert sum(isinstance(r, ConcurrentModification) for r in results) == 1
    assert (await repo.get(USER, DAY)).version == 2


async def test_repository_upgrades_legacy_document_and_unsets_old_fields(repo, test_db):
    await test_db[Collections.DAILY_SCHEDULES].insert_one({
        "user_id": USER, "date": DAY, "confirmed": True, "strategy_name": "Most Relaxed",
        "tasks": [task("Reading", "10:00", "11:00").model_dump()],
        "all_strategies": [s.model_dump() for s in three_strategies()],
        "generated_at": "2026-11-19T07:00:00",
    })
    plan = await repo.get(USER, DAY)
    assert plan.status == DayPlanStatus.CONFIRMED and plan.version == 0
    await repo.save(plan, expected_version=0)
    raw = await test_db[Collections.DAILY_SCHEDULES].find_one({"user_id": USER, "date": DAY})
    for legacy in ("tasks", "strategy_name", "all_strategies", "confirmed", "generated_at"):
        assert legacy not in raw
    assert raw["version"] == 1 and raw["active"]["strategy_name"] == "Most Relaxed"
    assert "status" not in raw


# ── GeneratePlan ─────────────────────────────────────────────────────────────

async def test_generate_from_empty_creates_proposal(make_service):
    plan = await make_service().handle(GeneratePlan(user_id=USER, date=DAY))
    assert plan.status == DayPlanStatus.PROPOSED
    assert plan.proposal.kind == "plan"
    assert plan.proposal.top_recommendation == "Most Productive"
    assert len(plan.proposal.strategies) == 3


async def test_R1_generate_when_confirmed_keeps_active(make_service):
    """R1 (service level): regenerating never touches active."""
    service = make_service()
    confirmed = await _seed_confirmed(service, "Most Relaxed")
    plan = await service.handle(GeneratePlan(user_id=USER, date=DAY))
    assert plan.status == DayPlanStatus.CONFIRMED_WITH_PROPOSAL
    assert plan.active == confirmed.active


async def test_generate_rejects_output_violating_invariants_and_writes_nothing(make_service, repo):
    bad = schedule_output(strategies=[three_strategies()[0].model_copy(update={"tasks": [
        task("A", "09:00", "10:30"), task("B", "10:00", "11:00")]})])
    with pytest.raises(InvariantViolation):
        await make_service(plan_gen=PlanGenStub(outputs=[bad])).handle(GeneratePlan(user_id=USER, date=DAY))
    assert (await repo.get(USER, DAY)).version == 0


async def test_generate_rejects_output_dropping_calendar_event(make_service, repo):
    gen = PlanGenStub(calendar=[cal_event("ML Class", "14:00", "16:00", location="Library")])
    with pytest.raises(InvariantViolation):
        await make_service(plan_gen=gen).handle(GeneratePlan(user_id=USER, date=DAY))
    assert (await repo.get(USER, DAY)).version == 0


async def test_generate_rejects_empty_strategies(make_service):
    empty = schedule_output(strategies=[])
    empty = empty.model_copy(update={"strategies": []})
    with pytest.raises(InvariantViolation):
        await make_service(plan_gen=PlanGenStub(outputs=[empty])).handle(GeneratePlan(user_id=USER, date=DAY))


# ── AdjustPlan ───────────────────────────────────────────────────────────────

async def test_adjust_requires_active(make_service, repo):
    with pytest.raises(InvalidTransition):
        await make_service().handle(AdjustPlan(user_id=USER, date=DAY, trigger="new_event", detail="3pm sync"))
    assert (await repo.get(USER, DAY)).version == 0


async def test_adjust_creates_adjust_proposal_and_keeps_active(make_service):
    service = make_service()
    confirmed = await _seed_confirmed(service)
    plan = await service.handle(AdjustPlan(user_id=USER, date=DAY, trigger="new_event", detail="3pm sync"))
    assert plan.active == confirmed.active
    assert plan.proposal.kind == "adjust"
    assert [s.name for s in plan.proposal.strategies] == ["Adjusted"]
    assert plan.proposal.top_recommendation == "Adjusted"
    assert plan.proposal.explanation
    assert plan.proposal.based_on_version == plan.version


async def test_adjust_generator_receives_active_tasks_from_db(make_service):
    gen = AdjustGenStub()
    service = make_service(adjust_gen=gen)
    confirmed = await _seed_confirmed(service)
    await service.handle(AdjustPlan(user_id=USER, date=DAY, trigger="task_overrun", detail="ran over"))
    assert gen.calls[0].active_tasks == confirmed.active.tasks


async def test_adjust_rejects_output_dropping_existing_calendar_event(make_service, repo):
    service = make_service(adjust_gen=AdjustGenStub(updated=[task("Reading", "10:00", "11:00")]))
    await service.handle(GeneratePlan(user_id=USER, date=DAY))
    # confirm a strategy that contains a calendar event
    plan = await repo.get(USER, DAY)
    strategies = [plan.proposal.strategies[0].model_copy(update={"tasks": [
        task("ML Class", "14:00", "16:00", type="calendar_event")]})]
    plan = plan.model_copy(update={"proposal": plan.proposal.model_copy(update={"strategies": strategies,
                                                                                "top_recommendation": "Most Productive"})})
    plan = await repo.save(plan, expected_version=plan.version)
    await service.handle(ConfirmProposal(user_id=USER, date=DAY))
    before = await repo.get(USER, DAY)
    with pytest.raises(InvariantViolation):
        await service.handle(AdjustPlan(user_id=USER, date=DAY, trigger="energy_update", detail="tired"))
    assert (await repo.get(USER, DAY)).version == before.version


# ── ConfirmProposal ──────────────────────────────────────────────────────────

async def test_R3_confirm_without_proposal_is_invalid_transition(make_service, repo):
    with pytest.raises(InvalidTransition) as exc:
        await make_service().handle(ConfirmProposal(user_id=USER, date=DAY))
    assert exc.value.code == "invalid_transition"
    assert (await repo.get(USER, DAY)).version == 0


async def test_R2_confirm_named_strategy_sets_active_and_clears_proposal(make_service):
    service = make_service()
    await service.handle(GeneratePlan(user_id=USER, date=DAY))
    plan = await service.handle(ConfirmProposal(user_id=USER, date=DAY, strategy_name="most relaxed"))
    assert plan.status == DayPlanStatus.CONFIRMED
    assert plan.active.strategy_name == "Most Relaxed"
    assert [t.title for t in plan.active.tasks] == ["Reading", "Walk"]
    assert plan.proposal is None


async def test_confirm_without_name_uses_top_recommendation(make_service):
    service = make_service()
    await service.handle(GeneratePlan(user_id=USER, date=DAY))
    plan = await service.handle(ConfirmProposal(user_id=USER, date=DAY))
    assert plan.active.strategy_name == "Most Productive"


async def test_confirm_unknown_strategy_is_invalid_transition(make_service, repo):
    service = make_service()
    proposed = await service.handle(GeneratePlan(user_id=USER, date=DAY))
    with pytest.raises(InvalidTransition):
        await service.handle(ConfirmProposal(user_id=USER, date=DAY, strategy_name="Laziest"))
    assert (await repo.get(USER, DAY)).version == proposed.version


async def test_confirm_with_stale_proposal_id_is_rejected(make_service, repo):
    service = make_service()
    first = await service.handle(GeneratePlan(user_id=USER, date=DAY))
    second = await service.handle(GeneratePlan(user_id=USER, date=DAY))
    assert first.proposal.proposal_id != second.proposal.proposal_id
    with pytest.raises(InvalidTransition):
        await service.handle(ConfirmProposal(user_id=USER, date=DAY, proposal_id=first.proposal.proposal_id))
    ok = await service.handle(ConfirmProposal(user_id=USER, date=DAY, proposal_id=second.proposal.proposal_id))
    assert ok.status == DayPlanStatus.CONFIRMED


async def test_confirm_adjust_updates_active(make_service):
    service = make_service()
    await _seed_confirmed(service)
    await service.handle(AdjustPlan(user_id=USER, date=DAY, trigger="new_event", detail="3pm sync"))
    plan = await service.handle(ConfirmProposal(user_id=USER, date=DAY))
    assert plan.active.strategy_name == "Adjusted"
    assert "Team sync" in [t.title for t in plan.active.tasks]
    assert plan.proposal is None


async def test_R5_confirm_adjust_after_active_changed_is_concurrent_modification(make_service, repo):
    """R5: the adjust proposal was computed against an active plan that has since changed."""
    service = make_service()
    await _seed_confirmed(service)
    proposed = await service.handle(AdjustPlan(user_id=USER, date=DAY, trigger="new_event", detail="3pm sync"))
    # Someone else (another tab / device) rewrites active, leaving the proposal in place.
    changed = proposed.model_copy(update={"active": ActivePlan(
        strategy_name="Fastest", tasks=[task("Leetcode Practice", "08:00", "09:30")], confirmed_at="x")})
    changed = await repo.save(changed, expected_version=proposed.version)
    with pytest.raises(ConcurrentModification) as exc:
        await service.handle(ConfirmProposal(user_id=USER, date=DAY))
    assert exc.value.code == "concurrent_modification"
    after = await repo.get(USER, DAY)
    assert after.active.strategy_name == "Fastest" and after.version == changed.version


async def test_confirm_loses_race_with_concurrent_writer(make_service, repo, monkeypatch):
    """Optimistic lock: a write landing between the service's read and its save is detected."""
    service = make_service()
    proposed = await service.handle(GeneratePlan(user_id=USER, date=DAY))
    real_get = repo.get

    async def get_then_race(user_id, date):
        snapshot = await real_get(user_id, date)
        await repo.save(snapshot, expected_version=snapshot.version)  # concurrent writer bumps version
        return snapshot

    monkeypatch.setattr(repo, "get", get_then_race)
    with pytest.raises(ConcurrentModification):
        await service.handle(ConfirmProposal(user_id=USER, date=DAY))
    monkeypatch.setattr(repo, "get", real_get)
    assert (await repo.get(USER, DAY)).active is None
    assert (await repo.get(USER, DAY)).version == proposed.version + 1


# ── DiscardProposal ──────────────────────────────────────────────────────────

async def test_discard_requires_proposal(make_service):
    with pytest.raises(InvalidTransition):
        await make_service().handle(DiscardProposal(user_id=USER, date=DAY))


async def test_discard_clears_proposal_keeps_active(make_service):
    service = make_service()
    confirmed = await _seed_confirmed(service)
    await service.handle(GeneratePlan(user_id=USER, date=DAY))
    plan = await service.handle(DiscardProposal(user_id=USER, date=DAY))
    assert plan.status == DayPlanStatus.CONFIRMED
    assert plan.active == confirmed.active


# ── RescheduleMissed ─────────────────────────────────────────────────────────

PENDING = {"tasks": ["Leetcode Practice", "Lab report"], "original_date": DAY, "suggested_date": NEXT_DAY}


async def test_reschedule_requires_pending(make_service):
    with pytest.raises(InvalidTransition):
        await make_service(pending=PendingStub(None)).handle(RescheduleMissed(user_id=USER))
    with pytest.raises(InvalidTransition):
        await make_service(pending=PendingStub({"tasks": []})).handle(RescheduleMissed(user_id=USER))


async def test_R6_reschedule_generates_next_day_with_missed_tasks_and_confirm_clears_pending(make_service):
    gen, pending = PlanGenStub(), PendingStub(dict(PENDING))
    service = make_service(plan_gen=gen, pending=pending)
    plan = await service.handle(RescheduleMissed(user_id=USER))
    assert plan.date == NEXT_DAY
    assert gen.calls[0].focus_tasks == ["Leetcode Practice", "Lab report"]
    assert plan.proposal.consumes_pending_reschedule is True
    assert pending.cleared == 0, "pending must survive until the plan is confirmed"
    await service.handle(ConfirmProposal(user_id=USER, date=NEXT_DAY))
    assert pending.cleared == 1 and pending.pending is None


async def test_reschedule_explicit_target_date(make_service):
    gen = PlanGenStub()
    plan = await make_service(plan_gen=gen, pending=PendingStub(dict(PENDING))).handle(
        RescheduleMissed(user_id=USER, target_date="2026-11-23"))
    assert plan.date == "2026-11-23" and gen.calls[0].date == "2026-11-23"


async def test_regular_plan_confirm_does_not_clear_pending(make_service):
    pending = PendingStub(dict(PENDING))
    service = make_service(pending=pending)
    await service.handle(GeneratePlan(user_id=USER, date=NEXT_DAY))
    await service.handle(ConfirmProposal(user_id=USER, date=NEXT_DAY))
    assert pending.cleared == 0
