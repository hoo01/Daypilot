import asyncio
import os
from google.adk.agents import Agent
from google.adk.agents.callback_context import CallbackContext
from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset, StdioConnectionParams
from google.genai import types as genai_types
from mcp import StdioServerParameters
from config import settings
from agents.tools import (
    read_user_context,
    write_entity_to_memory,
    store_conversation_memory,
    retrieve_relevant_memories,
    clear_pending_reschedule,
    analyze_health,
    track_goals,
    get_relationship_context,
    plan_schedule,
    get_geo_info,
    adjust_schedule,
)

INSTRUCTION = """
You are DayPilot, a proactive AI life assistant. You know the user's life — not just their meetings.

The following user context has already been loaded for this turn:
<user_context>
{user_context}
</user_context>

User ID: {user_id}

Based on this context, proactively surface what matters today:
- If goals exist with progress, mention them specifically (e.g. "You have 4 Leetcode problems left this week").
- If proactive_suggestions exist in the relationship context, quote them directly.
- Suggest a daily schedule that fits the user's energy and focus window.

You can call additional tools when needed:
- write_entity_to_memory / store_conversation_memory: when user shares personal info
- retrieve_relevant_memories: to recall past context
- plan_schedule: to generate detailed schedule options with health/goal/geo context
- get_geo_info: when locations/commute are relevant
- adjust_schedule: when the user's day changes
- analyze_health: run the full psychobiological pipeline to get today's
  energy_score, focus_windows, cognitive_load, and a final_insight string.
  Always call this before plan_schedule so the schedule reflects the user's
  real psychobiological state. Pass only user_id.

Always be proactive — surface insights the user hasn't asked for yet.
Keep responses concise and action-oriented.
"""


async def _preload_user_context(callback_context: CallbackContext) -> genai_types.Content | None:
    """Pre-loads user context in parallel before each agent turn."""
    user_id = callback_context.user_id or "demo_user"

    try:
        ctx, goals, rel, health = await asyncio.gather(
            read_user_context(user_id),
            track_goals(user_id),
            get_relationship_context(user_id),
            analyze_health(user_id),
            return_exceptions=True,
        )

        context_parts = []

        if not isinstance(goals, Exception) and goals.get("goals"):
            context_parts.append(f"Goals: {goals}")

        if not isinstance(rel, Exception):
            suggestions = rel.get("proactive_suggestions", [])
            upcoming = rel.get("upcoming_events", [])
            if suggestions:
                context_parts.append(f"Proactive suggestions: {suggestions}")
            if upcoming:
                context_parts.append(f"Upcoming events: {upcoming}")

        if not isinstance(ctx, Exception):
            prefs = ctx.get("preferences", {})
            context_parts.append(
                f"Focus window: {prefs.get('focus_window', '9PM-1AM')}, "
                f"Energy pattern: {prefs.get('energy_pattern', 'unknown')}"
            )
            pending = prefs.get("pending_reschedule")
            if pending and pending.get("tasks"):
                context_parts.append(
                    f"PENDING RESCHEDULE: The user did not complete these tasks yesterday "
                    f"({pending.get('original_date')}): {pending['tasks']}. "
                    f"Suggested reschedule date: {pending.get('suggested_date')}. "
                    f"If the user confirms, call adjust_schedule to add these tasks to the new date "
                    f"and then clear pending_reschedule by calling write_entity_to_memory or update via MCP."
                )

        if not isinstance(health, Exception) and health.get("node4_classification"):
            context_parts.append(
                f"Health: {health['node4_classification']} "
                f"(PSI={health['psi']:.0f}, energy={health['energy_score']}). "
                f"{health.get('final_insight', '')}"
            )
        elif not isinstance(health, Exception):
            context_parts.append(
                f"Health: energy={health.get('energy_score', 'medium')}, "
                f"cognitive_load={health.get('cognitive_load', 0.5):.2f}"
            )

        callback_context.state["user_id"] = user_id
        callback_context.state["user_context"] = "\n".join(context_parts) if context_parts else "No context loaded."
        if not isinstance(health, Exception):
            callback_context.state["health_context"] = health

    except Exception:
        callback_context.state["user_id"] = user_id
        callback_context.state["user_context"] = "Context unavailable."

    return None


def get_mongo_mcp() -> MCPToolset:
    """Create a new MCPToolset for MongoDB. Used at startup via lifespan."""
    return MCPToolset(
        connection_params=StdioConnectionParams(
            server_params=StdioServerParameters(
                command="npx",
                args=["-y", "mongodb-mcp-server"],
                env={**os.environ, "MDB_MCP_CONNECTION_STRING": settings.mongodb_uri},
            ),
        )
    )


def build_coordinator(mcp_tools=None, goal_tracking_root=None) -> Agent:
    tools = [
        read_user_context,
        write_entity_to_memory,
        store_conversation_memory,
        retrieve_relevant_memories,
        clear_pending_reschedule,
        analyze_health,
        track_goals,
        get_relationship_context,
        plan_schedule,
        get_geo_info,
        adjust_schedule,
    ]
    if mcp_tools:
        tools.append(mcp_tools)

    sub_agents = []
    if goal_tracking_root is not None:
        sub_agents.append(goal_tracking_root)

    agent_kwargs = dict(
        name="daypilot_coordinator",
        model=settings.coordinator_model,
        description="DayPilot's root coordinator. Orchestrates all specialist tools.",
        instruction=INSTRUCTION,
        tools=tools,
        before_agent_callback=_preload_user_context,
    )
    if sub_agents:
        agent_kwargs["sub_agents"] = sub_agents
    return Agent(**agent_kwargs)


# Default coordinator without MCP or goal agent (used if lifespan not set up)
coordinator = build_coordinator()