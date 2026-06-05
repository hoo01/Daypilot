import asyncio
import os
from google.adk.agents import Agent
from google.adk.agents.callback_context import CallbackContext
from google.adk.tools.agent_tool import AgentTool
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

When something in the user's day changes (new meeting, running late, energy drop),
call adjust_schedule to dynamically replan.

## Goal Intent Routing

**First, check state for an active intake session:**
If `state["intake_stage"]` is set and is not "completed", treat the user's message as intent=`add_goal_continue` regardless of content — the user is mid-intake.

Otherwise, classify by message content:

| Intent | Condition | Action |
|---|---|---|
| `check_progress` | "how are my goals", "goal progress", "what goals" | Call track_goals(user_id) directly — no transfer |
| `add_goal` | "I want to", "my goal is", "add goal", "set goal" | Assemble GoalAgentInput, call goal_tracking_root tool |
| `add_goal_continue` | state["intake_stage"] is set and not "completed" | Call goal_tracking_root tool with intent="add_goal_continue" |
| `update_goal` | "update goal", "change my goal", "replan" | Assemble input, call goal_tracking_root tool |
| `abandon_goal` | "abandon goal", "give up on", "cancel goal" | Assemble input, call goal_tracking_root tool |
| `replan_goal` | track_goals() returns replan_pending=True for any goal | Call goal_tracking_root tool with intent="replan"; pass the goal_id(s) where replan_pending=True |

When calling goal_tracking_root, first:
1. Call analyze_health(user_id) → store result as health context
2. Call retrieve_relevant_memories(user_id, query=raw_user_message) → store as memory_context
3. Call the goal_tracking_root tool and return its response word-for-word to the user.

For intent=`add_goal`: pass the user's raw message as the request.

For intent=`add_goal_continue`: build the request as a full context block so the intake agent can continue without losing history:
```
[INTAKE CONTINUATION]
Conversation so far:
<summarize all previous user messages and agent questions in this intake session, in order>

Current user reply: <raw_user_message>
```

You also have direct access to the MongoDB Knowledge Graph via MCP tools.
Use these when you need to answer specific questions about stored user data that the
specialist tools don't cover.
You can call additional tools when needed:
- write_entity_to_memory / store_conversation_memory: when user shares personal info
- retrieve_relevant_memories: to recall past context
- clear_pending_reschedule: after the user confirms a rescheduled task is handled
- plan_schedule: to generate detailed schedule options with health/goal/geo context
- get_geo_info: when locations/commute are relevant
- adjust_schedule: when the user's day changes
- analyze_health: for energy/sleep analysis

Always be proactive — surface insights the user hasn't asked for yet.
Keep responses concise and action-oriented.
"""


async def _preload_user_context(callback_context: CallbackContext) -> genai_types.Content | None:
    """Pre-loads user context in parallel before each agent turn."""
    from db.client import get_db
    from agents.tools.intake_session_db import find_open_intake_session

    user_id = callback_context.user_id or "demo_user"

    try:
        ctx, goals, rel = await asyncio.gather(
            read_user_context(user_id),
            track_goals(user_id),
            get_relationship_context(user_id),
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

        callback_context.state["user_id"] = user_id
        callback_context.state["user_context"] = "\n".join(context_parts) if context_parts else "No context loaded."

        # Detect active intake session from MongoDB so the coordinator can route continuations
        # without relying on the LLM to call save_intake_tracking.
        try:
            db = get_db()
            active_intake = await find_open_intake_session(db, user_id)
            if active_intake:
                callback_context.state["intake_session_id"] = active_intake.session_id
                callback_context.state["intake_stage"] = active_intake.stage
                callback_context.state["intake_draft"] = active_intake.draft
                callback_context.state["intake_history"] = [
                    t.model_dump(mode="json") for t in active_intake.history
                ]
            else:
                callback_context.state.pop("intake_session_id", None)
                callback_context.state.pop("intake_stage", None)
                callback_context.state.pop("intake_draft", None)
                callback_context.state.pop("intake_history", None)
        except Exception:
            pass

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

    if goal_tracking_root is not None:
        tools.append(AgentTool(goal_tracking_root))

    return Agent(
        name="daypilot_coordinator",
        model=settings.coordinator_model,
        description="DayPilot's root coordinator. Orchestrates all specialist tools.",
        instruction=INSTRUCTION,
        tools=tools,
        before_agent_callback=_preload_user_context,
    )


# Default coordinator without MCP or goal agent (used if lifespan not set up)
coordinator = build_coordinator()