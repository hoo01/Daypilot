"""Phase 3 — the coordinator is a read-only conversational agent (§6.3)."""
import re

from agents.coordinator import INSTRUCTION, _day_plan_summary, build_coordinator
from schemas.day_plan import GeneratedPlan, GeneratePlan, ConfirmProposal
from schemas.schedule import ScheduleInput
from services.day_plan_repository import DayPlanRepository
from services.day_plan_service import DayPlanService, today_for
from tests.fixtures.day_plan import schedule_output, three_strategies

SCHEDULE_WRITERS = {"plan_schedule", "adjust_schedule", "confirm_schedule", "get_today_schedule",
                    "clear_pending_reschedule"}
KEEP = {"read_user_context", "write_entity_to_memory", "store_conversation_memory", "retrieve_relevant_memories",
        "analyze_health", "track_goals", "get_relationship_context", "get_geo_info", "check_performance"}


def _tool_names(agent):
    return {getattr(t, "__name__", type(t).__name__) for t in agent.tools}


def test_read_only_coordinator_has_no_schedule_write_tools():
    names = _tool_names(build_coordinator(read_only=True))
    assert names.isdisjoint(SCHEDULE_WRITERS)
    assert KEEP <= names


def test_read_only_coordinator_does_not_mount_mongo_mcp():
    sentinel = object()
    agent = build_coordinator(mcp_tools=sentinel, read_only=True)
    assert sentinel not in agent.tools


def test_default_coordinator_follows_the_feature_flag():
    assert _tool_names(build_coordinator()).isdisjoint(SCHEDULE_WRITERS)


def test_instruction_has_no_shouted_schedule_rules():
    assert not re.search(r"\b(CRITICAL|MUST|ALWAYS|NEVER)\b", INSTRUCTION)
    assert "plan_schedule" not in INSTRUCTION and "confirm_schedule" not in INSTRUCTION


async def test_preload_summary_reflects_stored_day_plan(test_db):
    user = "coord_user"
    day = today_for(user)

    async def gen(req):
        return GeneratedPlan(output=schedule_output(req.date, strategies=three_strategies(req.date)),
                             input=ScheduleInput(user_id=req.user_id, date=req.date))

    assert "nothing confirmed" in (await _day_plan_summary(user))[0]
    service = DayPlanService(DayPlanRepository(test_db), plan_generator=gen)
    await service.handle(GeneratePlan(user_id=user, date=day))
    await service.handle(ConfirmProposal(user_id=user, date=day, strategy_name="Most Relaxed"))
    await service.handle(GeneratePlan(user_id=user, date=day))
    lines = await _day_plan_summary(user)
    assert '"Most Relaxed"' in lines[0] and "Reading" in lines[0] and "2 tasks" in lines[0]
    assert "proposal" in lines[1] and "Most Productive" in lines[1]
