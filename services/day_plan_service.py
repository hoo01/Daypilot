"""DayPlanService — executes schedule Commands as deterministic state transitions.

Every transition: (1) check the precondition against the stored DayPlan, (2) call a
pure LLM② generator when needed, (3) validate §5.3 invariants, (4) write once through
DayPlanRepository.save(plan, expected_version). LLMs never decide whether a write happens.
"""
from __future__ import annotations

import uuid
from datetime import date as _date, datetime, timedelta
from typing import Awaitable, Callable, Protocol

from schemas.day_plan import (
    ADJUSTED_STRATEGY,
    ActivePlan,
    AdjustPlan,
    AdjustRequest,
    ConcurrentModification,
    ConfirmProposal,
    DayPlan,
    DiscardProposal,
    GeneratedPlan,
    GeneratePlan,
    InvalidTransition,
    InvariantViolation,
    PlanRequest,
    Proposal,
    RescheduleMissed,
)
from schemas.realtime import RealtimeOutput
from schemas.schedule import CalendarEvent, ScheduleOutput, ScheduleStrategy, ScheduleTask
from services.day_plan_invariants import (
    fixed_blocks_for,
    fixed_blocks_for_adjustment,
    missing_fixed_blocks,
    validate_tasks,
)
from services.clock import now_local, today_local
from services.day_plan_repository import DayPlanRepository

PlanGenerator = Callable[[PlanRequest], Awaitable[GeneratedPlan]]
AdjustGenerator = Callable[[AdjustRequest], Awaitable[RealtimeOutput]]


def today_for(user_id: str) -> str:
    """The user's current date. Single helper so every caller agrees on "today".

    Follows the timezone of the current request (X-Timezone header), see services/clock.py.
    """
    return today_local()


class PendingRescheduleStore(Protocol):
    async def get(self, user_id: str) -> dict | None: ...
    async def clear(self, user_id: str) -> None: ...


class PreferencesPendingStore:
    """pending_reschedule lives in user_preferences (written by POST /schedule/feedback)."""

    def __init__(self, db=None):
        self._db = db

    def _mem(self):
        from agents.memory import MemoryAgent
        from db import get_db
        return MemoryAgent(self._db if self._db is not None else get_db())

    async def get(self, user_id: str) -> dict | None:
        prefs = await self._mem().get_preferences(user_id)
        return prefs.get("pending_reschedule")

    async def clear(self, user_id: str) -> None:
        await self._mem().update_preference(user_id, "pending_reschedule", None)


async def _default_plan_generator(req: PlanRequest) -> GeneratedPlan:
    from agents.tools.schedule_tools import build_plan  # lazy: avoids an import cycle
    return await build_plan(req)


async def _default_adjust_generator(req: AdjustRequest) -> RealtimeOutput:
    from agents.tools.realtime_tools import build_adjustment  # lazy: avoids an import cycle
    return await build_adjustment(req)


class DayPlanService:
    def __init__(
        self,
        repository: DayPlanRepository | None = None,
        *,
        plan_generator: PlanGenerator | None = None,
        adjust_generator: AdjustGenerator | None = None,
        pending_store: PendingRescheduleStore | None = None,
        now: Callable[[], datetime] = now_local,
    ):
        self.repo = repository or DayPlanRepository()
        self._plan_generator = plan_generator or _default_plan_generator
        self._adjust_generator = adjust_generator or _default_adjust_generator
        self.pending_store = pending_store or PreferencesPendingStore()
        self._now = now

    # ── public API ───────────────────────────────────────────────────────────

    async def get(self, user_id: str, date: str) -> DayPlan:
        return await self.repo.get(user_id, date)

    async def handle(self, cmd) -> DayPlan:
        if isinstance(cmd, GeneratePlan):
            return await self._generate(cmd.user_id, cmd.date, cmd.new_events, cmd.focus_tasks, consumes=False)
        if isinstance(cmd, AdjustPlan):
            return await self._adjust(cmd)
        if isinstance(cmd, ConfirmProposal):
            return await self._confirm(cmd)
        if isinstance(cmd, DiscardProposal):
            return await self._discard(cmd)
        if isinstance(cmd, RescheduleMissed):
            return await self._reschedule(cmd)
        raise TypeError(f"Unknown command: {type(cmd).__name__}")

    async def propose_plan(self, user_id: str, date: str, output: ScheduleOutput, *,
                           fixed_blocks: list[ScheduleTask] | None = None,
                           consumes_pending: bool = False) -> DayPlan:
        """Store an already-generated plan as the proposal (active untouched)."""
        strategies = self._checked_strategies(output.strategies, date, fixed_blocks or [])
        top = output.top_recommendation
        if not any(s.name == top for s in strategies):
            top = strategies[0].name
        proposal = Proposal(
            proposal_id=self._new_id(), kind="plan", strategies=strategies, top_recommendation=top,
            consumes_pending_reschedule=consumes_pending, created_at=self._stamp(),
        )
        plan = await self.repo.get(user_id, date)
        return await self.repo.save(plan.model_copy(update={"proposal": proposal}), plan.version)

    async def propose_adjustment(self, user_id: str, date: str, result: RealtimeOutput, *,
                                 new_events: list[CalendarEvent] | None = None) -> DayPlan:
        """Store an already-generated adjustment of the active plan as the proposal."""
        plan = await self.repo.get(user_id, date)
        if plan.active is None:
            raise InvalidTransition("no_active_plan", "There's no confirmed schedule to adjust yet.")
        fixed = fixed_blocks_for_adjustment(plan.active.tasks, new_events or [], date, self._now())
        tasks = sorted(result.updated_schedule, key=lambda t: t.start_time)
        strategy = ScheduleStrategy(name=ADJUSTED_STRATEGY, description="; ".join(result.what_changed),
                                    tasks=tasks)
        [strategy] = self._checked_strategies([strategy], date, fixed)
        proposal = Proposal(
            proposal_id=self._new_id(), kind="adjust", strategies=[strategy],
            top_recommendation=ADJUSTED_STRATEGY,
            explanation=result.message or "; ".join(result.what_changed),
            # The version this proposal will be stored at (see Proposal.based_on_version).
            based_on_version=plan.version + 1,
            created_at=self._stamp(),
        )
        return await self.repo.save(plan.model_copy(update={"proposal": proposal}), plan.version)

    # ── transitions ──────────────────────────────────────────────────────────

    async def _generate(self, user_id: str, date: str, new_events, focus_tasks, *, consumes: bool) -> DayPlan:
        generated = await self._plan_generator(PlanRequest(
            user_id=user_id, date=date, new_events=list(new_events), focus_tasks=list(focus_tasks)))
        fixed = fixed_blocks_for(generated.input, self._now())
        return await self.propose_plan(user_id, date, generated.output, fixed_blocks=fixed,
                                       consumes_pending=consumes)

    async def _adjust(self, cmd: AdjustPlan) -> DayPlan:
        plan = await self.repo.get(cmd.user_id, cmd.date)
        if plan.active is None:
            raise InvalidTransition("no_active_plan", "There's no confirmed schedule to adjust yet.")
        result = await self._adjust_generator(AdjustRequest(
            user_id=cmd.user_id, date=cmd.date, active_tasks=plan.active.tasks,
            trigger=cmd.trigger, detail=cmd.detail, new_events=cmd.new_events))
        return await self.propose_adjustment(cmd.user_id, cmd.date, result, new_events=cmd.new_events)

    async def _confirm(self, cmd: ConfirmProposal) -> DayPlan:
        plan = await self.repo.get(cmd.user_id, cmd.date)
        proposal = plan.proposal
        if proposal is None:
            raise InvalidTransition("no_proposal", "There's no proposed schedule to confirm yet.")
        if cmd.proposal_id and cmd.proposal_id != proposal.proposal_id:
            raise InvalidTransition("proposal_outdated",
                                    "That proposal has been replaced by a newer one.")
        strategy = proposal.find_strategy(cmd.strategy_name)
        if strategy is None:
            names = ", ".join(s.name for s in proposal.strategies)
            raise InvalidTransition("unknown_strategy",
                                    f"There's no '{cmd.strategy_name}' option. Available: {names}.")
        if proposal.kind == "adjust" and proposal.based_on_version != plan.version:
            raise ConcurrentModification("active_changed",
                                         "Your schedule changed after this adjustment was proposed.")
        # Re-check invariants on the exact tasks being committed (defence in depth).
        self._checked_strategies([strategy], plan.date, [])

        updated = plan.model_copy(update={
            "active": ActivePlan(strategy_name=strategy.name, tasks=strategy.tasks, confirmed_at=self._stamp()),
            "proposal": None,
        })
        saved = await self.repo.save(updated, plan.version)
        if proposal.consumes_pending_reschedule:
            # Cleared only once the rescheduled day is actually confirmed (§5.2).
            await self.pending_store.clear(cmd.user_id)
        return saved

    async def _discard(self, cmd: DiscardProposal) -> DayPlan:
        plan = await self.repo.get(cmd.user_id, cmd.date)
        if plan.proposal is None:
            raise InvalidTransition("no_proposal", "There's no proposed schedule to discard.")
        return await self.repo.save(plan.model_copy(update={"proposal": None}), plan.version)

    async def _reschedule(self, cmd: RescheduleMissed) -> DayPlan:
        pending = await self.pending_store.get(cmd.user_id)
        if not pending or not pending.get("tasks"):
            raise InvalidTransition("no_pending_reschedule", "There are no missed tasks waiting to be rescheduled.")
        target = cmd.target_date or pending.get("suggested_date") or (
            _date.fromisoformat(today_for(cmd.user_id)) + timedelta(days=1)).isoformat()
        return await self._generate(cmd.user_id, target, [], list(pending["tasks"]), consumes=True)

    # ── helpers ──────────────────────────────────────────────────────────────

    def _checked_strategies(self, strategies, date: str, fixed: list[ScheduleTask]) -> list[ScheduleStrategy]:
        if not strategies:
            raise InvariantViolation("no_strategies", "The generated schedule had no options.")
        problems = []
        for s in strategies:
            for v in validate_tasks(s.tasks, date) + missing_fixed_blocks(s.tasks, fixed):
                problems.append(f"[{s.name}] {v}")
        if problems:
            raise InvariantViolation("invariants", "; ".join(problems))
        return list(strategies)

    def _stamp(self) -> str:
        return self._now().isoformat(timespec="seconds")

    @staticmethod
    def _new_id() -> str:
        return uuid.uuid4().hex
