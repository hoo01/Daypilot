"""TurnOrchestrator — one chat turn, with code owning the control flow (§4).

    load_turn_context → LLM① parse_intent → chat?  → read-only agent (no state change)
                                          → schedule → DayPlanService.handle(command)
                                                       → reply rendered by code from state

The LLM never decides whether state changes; it only proposes an intent. Precondition
failures become friendly replies plus an explicit `error`, never an improvised answer.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date as _date, datetime, timedelta
from typing import Awaitable, Callable

from pydantic import BaseModel

from agents.intent import (
    Adjust,
    Chat,
    Confirm,
    Discard,
    IntentContext,
    PlanDay,
    Reschedule,
    parse_intent,
    resolve_event,
)
from schemas.day_plan import (
    AdjustPlan,
    ConcurrentModification,
    ConfirmProposal,
    DayPlan,
    DayPlanError,
    DiscardProposal,
    GenerationFailed,
    GeneratePlan,
    InvalidTransition,
    InvariantViolation,
    RescheduleMissed,
)
from services.day_plan_service import DayPlanService, today_for

_log = logging.getLogger(__name__)

IntentParser = Callable[[str, IntentContext], Awaitable[object]]
ChatResponder = Callable[[str, str, str], Awaitable[str]]          # (user_id, session_id, message) -> reply
CalendarLoader = Callable[[str], Awaitable[list[dict]]]


class TurnError(BaseModel):
    code: str          # "invalid_transition" | "concurrent_modification" | "generation_failed"
    message: str


class TurnResult(BaseModel):
    reply: str
    day_plan: DayPlan | None = None
    error: TurnError | None = None
    intent: str = "chat"
    state_changed: bool = False


@dataclass
class TurnContext:
    user_id: str
    today: str
    now: datetime
    plans: dict[str, DayPlan]
    pending_reschedule: dict | None = None
    calendar_events: list[dict] = field(default_factory=list)

    @property
    def today_plan(self) -> DayPlan:
        return self.plans[self.today]

    @property
    def proposal_plan(self) -> DayPlan:
        """The plan a bare "confirm"/"discard" refers to: the one holding the most recent
        proposal (today or a future day being planned), else today's."""
        with_proposal = [p for p in self.plans.values() if p.proposal is not None]
        if not with_proposal:
            return self.today_plan
        return max(with_proposal, key=lambda p: (p.proposal.created_at, p.date == self.today))


async def _default_calendar_loader(user_id: str) -> list[dict]:
    from agents.memory import MemoryAgent
    from db import get_db
    return await MemoryAgent(get_db()).get_today_calendar_events(user_id)


async def _no_chat_responder(user_id: str, session_id: str, message: str) -> str:  # pragma: no cover
    raise RuntimeError("TurnOrchestrator was built without a chat responder")


# ── reply rendering (code, from state) ───────────────────────────────────────

def _date_label(day: str, today: str) -> str:
    if day == today:
        return "today"
    if day == (_date.fromisoformat(today) + timedelta(days=1)).isoformat():
        return "tomorrow"
    return _date.fromisoformat(day).strftime("%A, %b %-d")


def _render_success(intent, plan: DayPlan, today: str) -> str:
    label = _date_label(plan.date, today)
    keep_note = " Your current schedule stays as it is until you confirm." if plan.active and plan.proposal else ""
    if isinstance(intent, (PlanDay, Reschedule)) and plan.proposal:
        p = plan.proposal
        top = p.find_strategy(None)
        why = f" — {top.reasoning.strip()}" if top and top.reasoning.strip() else ""
        names = ", ".join(s.name for s in p.strategies)
        lead = (f"Here's a plan for {label} that makes room for the tasks you missed."
                if isinstance(intent, Reschedule) else f"Here are {len(p.strategies)} options for {label}: {names}.")
        return f"{lead} I'd go with **{p.top_recommendation}**{why}. Pick one to lock it in, or tell me what to change.{keep_note}"
    if isinstance(intent, Adjust) and plan.proposal:
        expl = plan.proposal.explanation.strip() or "Here's an adjusted version of today's schedule."
        return f"{expl} Want me to apply this change?{keep_note}"
    if isinstance(intent, Confirm) and plan.active:
        return f"Done — the **{plan.active.strategy_name}** plan is locked in for {label}."
    if isinstance(intent, Discard):
        return "OK, I dropped that proposal." + (" Your confirmed schedule is unchanged." if plan.active else "")
    return "Done."


_INVALID_REPLIES = {
    "no_proposal": "There's no proposed schedule to confirm yet. Want me to plan your day?",
    "no_active_plan": "You don't have a confirmed schedule for today yet. Want me to plan your day first?",
    "no_pending_reschedule": "There are no missed tasks waiting to be rescheduled.",
    "past_date": "I can only plan today or a future day.",
    "bad_date": "I couldn't tell which day you meant — could you give me the date?",
}


def _render_error(e: DayPlanError) -> TurnError:
    if isinstance(e, InvalidTransition):
        return TurnError(code="invalid_transition", message=_INVALID_REPLIES.get(e.reason, e.message))
    if isinstance(e, ConcurrentModification):
        return TurnError(code="concurrent_modification", message=(
            "Your schedule changed while that was pending, so I didn't apply it. "
            "Tell me again what you'd like to change and I'll work from the latest version."))
    if isinstance(e, (GenerationFailed, InvariantViolation)):
        msg = e.message if isinstance(e, GenerationFailed) else (
            "I couldn't put together a valid schedule this time, so nothing was changed. Please try again.")
        return TurnError(code="generation_failed", message=msg)
    return TurnError(code=e.code, message=e.message)


# ── orchestrator ─────────────────────────────────────────────────────────────

class TurnOrchestrator:
    def __init__(
        self,
        service: DayPlanService | None = None,
        *,
        intent_parser: IntentParser | None = None,
        chat_responder: ChatResponder | None = None,
        calendar_loader: CalendarLoader | None = None,
        now: Callable[[], datetime] = datetime.now,
    ):
        self.service = service or DayPlanService()
        self._parse = intent_parser or (lambda message, ctx: parse_intent(message, ctx))
        self._chat = chat_responder or _no_chat_responder
        self._calendar = calendar_loader or _default_calendar_loader
        self._now = now

    async def load_turn_context(self, user_id: str) -> TurnContext:
        today = today_for(user_id)
        tomorrow = (_date.fromisoformat(today) + timedelta(days=1)).isoformat()
        plans = {d: await self.service.get(user_id, d) for d in (today, tomorrow)}
        try:
            pending = await self.service.pending_store.get(user_id)
        except Exception as e:
            _log.warning("[orchestrator] pending_reschedule unavailable for %s: %s", user_id, e)
            pending = None
        try:
            calendar = await self._calendar(user_id)
        except Exception as e:
            _log.warning("[orchestrator] calendar unavailable for %s: %s", user_id, e)
            calendar = []
        return TurnContext(user_id=user_id, today=today, now=self._now(), plans=plans,
                           pending_reschedule=pending, calendar_events=calendar)

    @staticmethod
    def intent_context(ctx: TurnContext) -> IntentContext:
        plan = ctx.proposal_plan
        p = plan.proposal
        return IntentContext(
            today=ctx.today, now=ctx.now, status=ctx.today_plan.status.value,
            strategy_names=[s.name for s in p.strategies] if p else [],
            top_recommendation=p.top_recommendation if p else None,
            proposal_kind=p.kind if p else None, proposal_date=plan.date if p else None,
            calendar_events=ctx.calendar_events, pending_reschedule=ctx.pending_reschedule,
        )

    async def run_turn(self, user_id: str, message: str, session_id: str) -> TurnResult:
        ctx = await self.load_turn_context(user_id)
        try:
            intent = await self._parse(message, self.intent_context(ctx))
        except Exception as e:  # parse_intent already never raises; guard injected parsers too
            _log.warning("[orchestrator] intent parser failed, using chat: %s", e)
            intent = Chat()
        _log.info("[orchestrator] %s intent=%s", user_id, getattr(intent, "type", "?"))

        if isinstance(intent, Chat):
            reply = await self._chat(user_id, session_id, message)
            return TurnResult(reply=reply, day_plan=ctx.today_plan, intent="chat")

        relevant = ctx.today_plan
        try:
            command, relevant = self._to_command(intent, ctx)
            plan = await self.service.handle(command)
        except DayPlanError as e:
            err = _render_error(e)
            _log.info("[orchestrator] %s %s rejected: %s (%s)", user_id, intent.type, e.reason, e.message)
            return TurnResult(reply=err.message, day_plan=relevant, error=err, intent=intent.type)
        return TurnResult(reply=_render_success(intent, plan, ctx.today), day_plan=plan,
                          intent=intent.type, state_changed=True)

    # ── intent → command (pure) ──────────────────────────────────────────────

    def _to_command(self, intent, ctx: TurnContext):
        uid = ctx.user_id
        if isinstance(intent, PlanDay):
            day = self._checked_date(intent.target_date, ctx.today)
            events, focus = [], list(intent.focus_tasks)
            for spec in intent.new_events:
                ev = resolve_event(spec, day, ctx.now)
                if ev is not None:
                    events.append(ev)
                elif spec.title.strip():
                    focus.append(spec.title.strip())   # no placeable time → flexible task
            plan = ctx.plans.get(day, ctx.today_plan)
            return GeneratePlan(user_id=uid, date=day, new_events=events, focus_tasks=focus), plan
        if isinstance(intent, Adjust):
            events = [ev for ev in (resolve_event(s, ctx.today, ctx.now) for s in intent.new_events) if ev]
            return AdjustPlan(user_id=uid, date=ctx.today, trigger=intent.trigger,
                              detail=intent.detail or "schedule change", new_events=events), ctx.today_plan
        if isinstance(intent, Confirm):
            plan = ctx.proposal_plan
            pid = plan.proposal.proposal_id if plan.proposal else None
            return ConfirmProposal(user_id=uid, date=plan.date, proposal_id=pid,
                                   strategy_name=intent.strategy_name), plan
        if isinstance(intent, Discard):
            plan = ctx.proposal_plan
            return DiscardProposal(user_id=uid, date=plan.date), plan
        if isinstance(intent, Reschedule):
            target = self._checked_date(intent.target_date, ctx.today) if intent.target_date else None
            return RescheduleMissed(user_id=uid, target_date=target), ctx.plans.get(target or "", ctx.today_plan)
        raise InvalidTransition("unknown_intent", "I'm not sure what you'd like me to do with your schedule.")

    @staticmethod
    def _checked_date(value: str | None, today: str) -> str:
        if not value:
            return today
        try:
            day = _date.fromisoformat(value.strip())
        except ValueError:
            raise InvalidTransition("bad_date", f"Unrecognised date {value!r}.")
        if day < _date.fromisoformat(today):
            raise InvalidTransition("past_date", "Can't plan a day in the past.")
        return day.isoformat()
