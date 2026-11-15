import asyncio
import os
from google.adk.agents import Agent
from google.adk.agents.callback_context import CallbackContext
from google.adk.tools.mcp_tool.mcp_toolset import McpToolset, StdioConnectionParams
from google.genai import types as genai_types
from mcp import StdioServerParameters
from config import settings
from agents.tools.performance_tools import check_performance
from opentelemetry import trace
from telemetry import tracer, meter, get_logger

_logger = get_logger("coordinator")
_context_load_duration = meter.create_histogram(
    "coordinator.context_load.duration", unit="ms", description="Context preload duration"
)
_context_load_errors = meter.create_counter(
    "coordinator.context_load.errors", description="Context preload component errors"
)
from agents.tools import (
    read_user_context,
    write_entity_to_memory,
    store_conversation_memory,
    retrieve_relevant_memories,
    analyze_health,
    track_goals,
    get_relationship_context,
    get_geo_info,
)

# Read-only conversational agent. Schedule generation, confirmation and adjustment are
# code-owned (services/turn_orchestrator.py); this agent only answers questions and
# can't change the schedule.
INSTRUCTION = """
You are DayPilot, a proactive AI life assistant. You know the user's life — not just their meetings.

The following user context has already been loaded for this turn:
<user_context>
{user_context}
</user_context>

User ID: {user_id}

Answer from the context above in 3-4 short, specific, warm sentences: proactive suggestions,
goal progress, and the user's focus window / energy pattern. When the user asks what is on
their schedule, use the "Schedule" lines in the context — they are the stored state.

You can't create, confirm or change the schedule yourself; DayPilot's planner does that when
the user asks for it directly. If the user wants to change their schedule, invite them to say
what they need, for example "plan my day", "add a meeting at 3pm" or "go with the most
relaxed plan".

Tools you can use:
- write_entity_to_memory / store_conversation_memory: when the user shares personal info
- retrieve_relevant_memories: to recall past context
- analyze_health: energy / sleep analysis (energy_level, focus_window, cognitive_load_score, avoid_tasks)
- track_goals, get_relationship_context, get_geo_info, read_user_context: for more detail
- check_performance: when the user asks how you are performing (response times, errors);
  report the numbers it returns rather than estimating them

Surface insights the user hasn't asked for yet, and keep responses concise.
"""


async def _day_plan_summary(user_id: str) -> list[str]:
    """Stored schedule state for today, so answers about "my schedule" have a real basis."""
    from services.day_plan_repository import DayPlanRepository
    from services.day_plan_service import today_for

    today = today_for(user_id)
    plan = await DayPlanRepository().get(user_id, today)
    lines = []
    if plan.active:
        items = "; ".join(
            f"{t.start_time[11:16]}–{t.end_time[11:16]} {t.title}" for t in plan.active.tasks
        )
        lines.append(f'Schedule for today ({today}): confirmed "{plan.active.strategy_name}" plan, '
                     f"{len(plan.active.tasks)} tasks: {items or '(none)'}")
    else:
        lines.append(f"Schedule for today ({today}): nothing confirmed yet.")
    if plan.proposal:
        names = ", ".join(s.name for s in plan.proposal.strategies)
        lines.append(f"Schedule proposal waiting for the user's choice ({plan.proposal.kind}): {names} "
                     f"(recommended: {plan.proposal.top_recommendation}).")
    return lines


async def _preload_user_context(callback_context: CallbackContext) -> genai_types.Content | None:
    """Pre-loads user context in parallel before each agent turn."""
    import time
    user_id = callback_context.user_id or "demo_user"

    with tracer.start_as_current_span("coordinator.preload_context") as span:
        span.set_attribute("user.id", user_id)
        _start = time.perf_counter()

        try:
            ctx, goals, rel, health = await asyncio.gather(
                read_user_context(user_id),
                track_goals(user_id),
                get_relationship_context(user_id),
                analyze_health(user_id),
                return_exceptions=True,
            )

            # Track which components succeeded/failed
            for name, result in [("user_context", ctx), ("goals", goals), ("relationships", rel), ("health", health)]:
                if isinstance(result, Exception):
                    _context_load_errors.add(1, {"component": name})
                    span.set_attribute(f"context.{name}.error", str(result))
                    _logger.warning(f"Context component '{name}' failed for {user_id}: {result}")

            context_parts = []

            if not isinstance(goals, Exception) and goals.get("goals"):
                context_parts.append(f"Goals: {goals}")

            if not isinstance(rel, Exception):
                suggestions = rel.get("proactive_suggestions", [])
                upcoming = rel.get("upcoming_events", [])
                today_events = rel.get("today_calendar_events", [])
                if suggestions:
                    context_parts.append(f"Proactive suggestions: {suggestions}")
                if upcoming:
                    context_parts.append(f"Upcoming events: {upcoming}")
                if today_events:
                    context_parts.append(f"Today's Google Calendar events: {today_events}")

            if not isinstance(ctx, Exception):
                prefs = ctx.get("preferences", {})
                context_parts.append(
                    f"Focus window: {prefs.get('focus_window', '9PM-1AM')}, "
                    f"Energy pattern: {prefs.get('energy_pattern', 'unknown')}"
                )
                pending = prefs.get("pending_reschedule")
                if pending and pending.get("tasks"):
                    context_parts.append(
                        f"Missed tasks: the user did not complete {pending['tasks']} on "
                        f"{pending.get('original_date')}. They can ask to move them to "
                        f"{pending.get('suggested_date')}."
                    )

            if not isinstance(health, Exception) and health.get("node4_classification"):
                context_parts.append(
                    f"Health: {health['node4_classification']} "
                    f"(PSI={health['psi']:.0f}, energy={health['energy_level']}). "
                    f"{health.get('final_insight', '')}"
                )
            elif not isinstance(health, Exception):
                context_parts.append(
                    f"Health: energy={health.get('energy_level', 'medium')}, "
                    f"cognitive_load={health.get('cognitive_load_score', 0.65):.2f}"
                )

            try:
                context_parts.extend(await _day_plan_summary(user_id))
            except Exception as e:
                _context_load_errors.add(1, {"component": "day_plan"})
                _logger.warning(f"Context component 'day_plan' failed for {user_id}: {e}")

            callback_context.state["user_id"] = user_id
            callback_context.state["user_context"] = "\n".join(context_parts) if context_parts else "No context loaded."
            if not isinstance(health, Exception):
                callback_context.state["health_context"] = health

            span.set_attribute("context.parts_count", len(context_parts))
            # Capture the assembled context for Dynatrace visibility
            assembled = "\n".join(context_parts) if context_parts else "No context loaded."
            span.add_event("agent.output", {"coordinator.context": assembled[:4096]})
            _logger.info(f"[coordinator.preload] OK for {user_id} — {len(context_parts)} parts: {assembled[:500]}")

        except Exception as e:
            span.set_status(trace.StatusCode.ERROR, str(e))
            span.record_exception(e)
            callback_context.state["user_id"] = user_id
            callback_context.state["user_context"] = "Context unavailable."
            _logger.error(f"Context preload failed for {user_id}: {e}")

        finally:
            duration_ms = (time.perf_counter() - _start) * 1000
            _context_load_duration.record(duration_ms, {"user.id": user_id})
            span.set_attribute("context.duration_ms", duration_ms)
            _logger.debug(f"Context preload for {user_id} took {duration_ms:.0f}ms")

    return None


def get_mongo_mcp() -> McpToolset:
    """Create a new MCPToolset for MongoDB. Used at startup via lifespan."""
    return McpToolset(
        connection_params=StdioConnectionParams(
            server_params=StdioServerParameters(
                command="npx",
                args=["-y", "mongodb-mcp-server"],
                env={**os.environ, "MDB_MCP_CONNECTION_STRING": settings.mongodb_uri},
            ),
        )
    )


# Tools that never write daily_schedules (§6.3).
READ_ONLY_TOOLS = [
    read_user_context,
    write_entity_to_memory,
    store_conversation_memory,
    retrieve_relevant_memories,
    analyze_health,
    track_goals,
    get_relationship_context,
    get_geo_info,
    check_performance,
]

def build_coordinator(mcp_tools=None, dynatrace_mcp=None, goal_tracking_root=None) -> Agent:
    tools = list(READ_ONLY_TOOLS)
    if mcp_tools:
        # The MongoDB MCP toolset can write any collection, daily_schedules included,
        # so the read-only agent doesn't get it. (Parameter kept for api/app.py.)
        _logger.info("[coordinator] MongoDB MCP toolset not attached (read-only agent)")

    sub_agents = []
    if goal_tracking_root is not None:
        sub_agents.append(goal_tracking_root)

    agent_kwargs = dict(
        name="daypilot_coordinator",
        model=settings.coordinator_model,
        description="DayPilot's conversational agent (read-only for schedules).",
        instruction=INSTRUCTION,
        tools=tools,
        before_agent_callback=_preload_user_context,
        generate_content_config=genai_types.GenerateContentConfig(
            thinking_config=genai_types.ThinkingConfig(thinking_budget=0),
        ),
    )
    if sub_agents:
        agent_kwargs["sub_agents"] = sub_agents
    return Agent(**agent_kwargs)


# Default coordinator without MCP or goal agent (used if lifespan not set up)
coordinator = build_coordinator()