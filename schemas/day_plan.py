"""DayPlan domain model — the single source of truth for a user's schedule on one date.

Core rule: LLMs may only *propose*; only code (DayPlanService) *commits*.
See docs/refactor/schedule_orchestrator.md §5.
"""
from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, computed_field

from schemas.realtime import RealtimeOutput
from schemas.schedule import CalendarEvent, ScheduleInput, ScheduleOutput, ScheduleStrategy, ScheduleTask

ADJUSTED_STRATEGY = "Adjusted"


# ─────────────────────────────────────────────────────────
# State
# ─────────────────────────────────────────────────────────

class DayPlanStatus(str, Enum):
    EMPTY = "EMPTY"
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    CONFIRMED_WITH_PROPOSAL = "CONFIRMED_WITH_PROPOSAL"


class ActivePlan(BaseModel):
    strategy_name: str            # "Most Productive" | "Most Relaxed" | "Fastest" | "Adjusted"
    tasks: list[ScheduleTask] = Field(default_factory=list)
    confirmed_at: str = ""        # ISO


class Proposal(BaseModel):
    proposal_id: str
    kind: Literal["plan", "adjust"]
    strategies: list[ScheduleStrategy] = Field(default_factory=list)
    top_recommendation: str
    explanation: str = ""
    # For adjust proposals: the DayPlan version this proposal was stored at. Any later
    # write to the plan bumps the version, so a mismatch at confirm time means the
    # active plan the adjustment was computed against is no longer current.
    based_on_version: int | None = None
    consumes_pending_reschedule: bool = False
    created_at: str = ""

    def find_strategy(self, name: str | None) -> ScheduleStrategy | None:
        wanted = (name or self.top_recommendation or "").strip().casefold()
        return next((s for s in self.strategies if s.name.strip().casefold() == wanted), None)


class DayPlan(BaseModel):
    user_id: str
    date: str                     # YYYY-MM-DD
    active: ActivePlan | None = None
    proposal: Proposal | None = None
    version: int = 0

    @computed_field  # serialized for clients; never stored (repository excludes it)
    @property
    def status(self) -> DayPlanStatus:
        if self.active is None:
            return DayPlanStatus.PROPOSED if self.proposal else DayPlanStatus.EMPTY
        return DayPlanStatus.CONFIRMED_WITH_PROPOSAL if self.proposal else DayPlanStatus.CONFIRMED


# ─────────────────────────────────────────────────────────
# Commands (§5.2)
# ─────────────────────────────────────────────────────────

class GeneratePlan(BaseModel):
    type: Literal["generate_plan"] = "generate_plan"
    user_id: str
    date: str
    new_events: list[CalendarEvent] = Field(default_factory=list)
    focus_tasks: list[str] = Field(default_factory=list)


AdjustTrigger = Literal["new_event", "task_overrun", "energy_update", "location_change"]


class AdjustPlan(BaseModel):
    type: Literal["adjust_plan"] = "adjust_plan"
    user_id: str
    date: str
    trigger: AdjustTrigger
    detail: str
    new_events: list[CalendarEvent] = Field(default_factory=list)


class ConfirmProposal(BaseModel):
    type: Literal["confirm_proposal"] = "confirm_proposal"
    user_id: str
    date: str
    proposal_id: str | None = None
    strategy_name: str | None = None     # None → the proposal's top recommendation


class DiscardProposal(BaseModel):
    type: Literal["discard_proposal"] = "discard_proposal"
    user_id: str
    date: str


class RescheduleMissed(BaseModel):
    type: Literal["reschedule_missed"] = "reschedule_missed"
    user_id: str
    target_date: str | None = None       # None → pending_reschedule.suggested_date


Command = Annotated[
    Union[GeneratePlan, AdjustPlan, ConfirmProposal, DiscardProposal, RescheduleMissed],
    Field(discriminator="type"),
]


# ─────────────────────────────────────────────────────────
# Generator boundary (LLM②) — requests the service hands to the pure generators
# ─────────────────────────────────────────────────────────

class PlanRequest(BaseModel):
    user_id: str
    date: str
    new_events: list[CalendarEvent] = Field(default_factory=list)
    focus_tasks: list[str] = Field(default_factory=list)


class GeneratedPlan(BaseModel):
    output: ScheduleOutput
    input: ScheduleInput          # the code-built input — the service derives fixed blocks from it


class AdjustRequest(BaseModel):
    user_id: str
    date: str
    active_tasks: list[ScheduleTask]
    trigger: AdjustTrigger
    detail: str
    new_events: list[CalendarEvent] = Field(default_factory=list)


# Re-exported for convenience: what an adjust generator returns.
GeneratedAdjustment = RealtimeOutput


# ─────────────────────────────────────────────────────────
# Domain errors
# ─────────────────────────────────────────────────────────

class DayPlanError(Exception):
    code = "day_plan_error"

    def __init__(self, reason: str, message: str | None = None):
        super().__init__(message or reason)
        self.reason = reason
        self.message = message or reason


class InvalidTransition(DayPlanError):
    """The command's precondition does not hold in the current state."""
    code = "invalid_transition"


class ConcurrentModification(DayPlanError):
    """The DayPlan changed between read and write (optimistic lock failure)."""
    code = "concurrent_modification"


class InvariantViolation(DayPlanError):
    """A proposed schedule breaks a §5.3 invariant; nothing was written."""
    code = "invariant_violation"


class GenerationFailed(DayPlanError):
    """LLM② could not produce a valid schedule after one retry; nothing was written."""
    code = "generation_failed"
