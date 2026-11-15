"""Phase 1 — pure tests: status derivation, legacy document mapping, invariants. No DB, no LLM."""
from datetime import datetime

import pytest

from schemas.day_plan import ActivePlan, DayPlan, DayPlanStatus, Proposal
from services.day_plan_invariants import (
    fixed_blocks_for,
    missing_fixed_blocks,
    validate_tasks,
)
from services.day_plan_repository import document_to_day_plan
from schemas.schedule import ScheduleInput, ScheduleTask
from tests.fixtures.day_plan import DAY, NEXT_DAY, cal_event, task, three_strategies


def _active():
    return ActivePlan(strategy_name="Most Relaxed", tasks=[task("Reading", "10:00", "11:00")],
                      confirmed_at="2026-11-19T08:00:00")


def _proposal():
    return Proposal(proposal_id="p1", kind="plan", strategies=three_strategies(),
                    top_recommendation="Most Productive", created_at="2026-11-19T08:00:00")


# ── 5.1 status derivation ────────────────────────────────────────────────────

@pytest.mark.parametrize("active,proposal,expected", [
    (False, False, DayPlanStatus.EMPTY),
    (False, True, DayPlanStatus.PROPOSED),
    (True, False, DayPlanStatus.CONFIRMED),
    (True, True, DayPlanStatus.CONFIRMED_WITH_PROPOSAL),
])
def test_status_is_derived_from_active_and_proposal(active, proposal, expected):
    plan = DayPlan(user_id="u", date=DAY,
                   active=_active() if active else None,
                   proposal=_proposal() if proposal else None)
    assert plan.status == expected


def test_status_is_serialized_but_not_required_on_input():
    plan = DayPlan(user_id="u", date=DAY, active=_active())
    dumped = plan.model_dump(mode="json")
    assert dumped["status"] == "CONFIRMED"
    # round-trip: a dumped plan (with status) parses back
    assert DayPlan.model_validate(dumped).status == DayPlanStatus.CONFIRMED


# ── 5.4 legacy document mapping ──────────────────────────────────────────────

def _legacy_strategies():
    return [s.model_dump() for s in three_strategies()]


def test_legacy_confirmed_document_maps_to_active():
    doc = {
        "user_id": "u", "date": DAY, "confirmed": True,
        "strategy_name": "Most Relaxed",
        "tasks": [task("Reading", "10:00", "11:00").model_dump()],
        "all_strategies": _legacy_strategies(),
        "generated_at": "2026-11-19T07:00:00",
    }
    plan = document_to_day_plan(doc)
    assert plan.status == DayPlanStatus.CONFIRMED
    assert plan.active.strategy_name == "Most Relaxed"
    assert [t.title for t in plan.active.tasks] == ["Reading"]
    assert plan.proposal is None
    assert plan.version == 0


def test_legacy_unconfirmed_document_maps_to_plan_proposal():
    doc = {
        "user_id": "u", "date": DAY, "confirmed": False,
        "strategy_name": "Fastest",
        "tasks": [task("Leetcode Practice", "08:00", "09:30").model_dump()],
        "all_strategies": _legacy_strategies(),
        "generated_at": "2026-11-19T07:00:00",
    }
    plan = document_to_day_plan(doc)
    assert plan.status == DayPlanStatus.PROPOSED
    assert plan.active is None
    assert plan.proposal.kind == "plan"
    assert plan.proposal.top_recommendation == "Fastest"
    assert [s.name for s in plan.proposal.strategies] == ["Most Productive", "Most Relaxed", "Fastest"]


def test_legacy_proposal_id_is_stable_across_reads():
    doc = {"user_id": "u", "date": DAY, "all_strategies": _legacy_strategies(),
           "strategy_name": "Fastest", "generated_at": "2026-11-19T07:00:00"}
    assert document_to_day_plan(doc).proposal.proposal_id == document_to_day_plan(dict(doc)).proposal.proposal_id


def test_legacy_adjusted_document_without_strategies_maps_to_active_only():
    doc = {"user_id": "u", "date": DAY, "confirmed": True, "strategy_name": "Adjusted",
           "tasks": [task("Reading", "10:00", "11:00").model_dump()]}
    plan = document_to_day_plan(doc)
    assert plan.active.strategy_name == "Adjusted"
    assert plan.proposal is None


def test_new_format_document_is_read_as_is():
    plan = DayPlan(user_id="u", date=DAY, active=_active(), proposal=_proposal(), version=7)
    doc = {"_id": "x", **plan.model_dump(mode="json")}
    parsed = document_to_day_plan(doc)
    assert parsed == plan


def test_missing_document_is_empty_plan():
    plan = document_to_day_plan(None, user_id="u", date=DAY)
    assert plan.status == DayPlanStatus.EMPTY
    assert plan.version == 0


# ── 5.3 invariants ───────────────────────────────────────────────────────────

def test_valid_tasks_have_no_violations():
    assert validate_tasks([task("A", "09:00", "10:00"), task("B", "10:00", "11:00")], DAY) == []


def test_overlap_is_a_violation():
    v = validate_tasks([task("A", "09:00", "10:30"), task("B", "10:00", "11:00")], DAY)
    assert any("overlap" in m for m in v)


@pytest.mark.parametrize("bad", ["2026_11_20T09:00:00", "9:00 AM", "2026-11-20 09:00", "2026-11-20T09:00"])
def test_non_iso_timestamp_is_a_violation(bad):
    t = task("A", "09:00", "10:00").model_copy(update={"start_time": bad})
    assert validate_tasks([t], DAY)


def test_task_on_another_date_is_a_violation():
    v = validate_tasks([task("A", "09:00", "10:00", day="2026-11-25")], DAY)
    assert any("date" in m for m in v)


def test_end_before_start_is_a_violation():
    assert validate_tasks([task("A", "11:00", "10:00")], DAY)


def test_cross_midnight_tasks_are_allowed():
    late = ScheduleTask(task_id="late", title="Night coding", type="deep_work",
                        start_time=f"{DAY}T23:00:00", end_time=f"{NEXT_DAY}T01:00:00")
    early = task("Wind down", "01:00", "02:00", day=NEXT_DAY)
    assert validate_tasks([late, early], DAY) == []


def test_next_day_daytime_task_is_a_violation():
    assert validate_tasks([task("A", "14:00", "15:00", day=NEXT_DAY)], DAY)


def test_empty_title_is_a_violation():
    assert validate_tasks([task("A", "09:00", "10:00").model_copy(update={"title": " "})], DAY)


def test_renamed_calendar_event_is_missing():
    fixed = [task("ML Class", "14:00", "16:00", type="calendar_event", location="Library")]
    tasks = [task("Event", "14:00", "16:00", type="calendar_event", location="Library")]
    assert missing_fixed_blocks(tasks, fixed)


def test_moved_or_relocated_calendar_event_is_missing():
    fixed = [task("ML Class", "14:00", "16:00", type="calendar_event", location="Library")]
    assert missing_fixed_blocks([task("ML Class", "14:30", "16:00", type="calendar_event", location="Library")], fixed)
    assert missing_fixed_blocks([task("ML Class", "14:00", "16:00", type="calendar_event", location=None)], fixed)
    assert missing_fixed_blocks([task("ML Class", "14:00", "16:00", type="calendar_event", location="Library")], fixed) == []


def test_fixed_blocks_for_input_drops_calendar_events_overlapping_locked_blocks():
    locked = task("Morning Routine", "07:00", "08:00", type="routine")
    inp = ScheduleInput(
        user_id="u", date=DAY, locked_blocks=[locked],
        calendar_events=[cal_event("Standup", "07:30", "08:00"), cal_event("ML Class", "14:00", "16:00")],
    )
    titles = [b.title for b in fixed_blocks_for(inp, now=datetime(2026, 11, 19, 8, 0))]
    assert titles == ["Morning Routine", "ML Class"]


def test_fixed_blocks_for_today_skip_blocks_already_over():
    inp = ScheduleInput(user_id="u", date=DAY, calendar_events=[
        cal_event("Breakfast meeting", "08:00", "09:00"), cal_event("ML Class", "14:00", "16:00"),
    ])
    titles = [b.title for b in fixed_blocks_for(inp, now=datetime(2026, 11, 20, 12, 0))]
    assert titles == ["ML Class"]
