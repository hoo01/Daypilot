import os
from google.adk.agents import Agent
from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset, StdioConnectionParams
from mcp import StdioServerParameters
from config import settings
from agents.tools import (
    read_user_context,
    write_entity_to_memory,
    store_conversation_memory,
    retrieve_relevant_memories,
    analyze_health,
    track_goals,
    get_relationship_context,
    plan_schedule,
    get_geo_info,
    adjust_schedule,
)

INSTRUCTION = """
You are DayPilot, a proactive AI life assistant. You know the user's life — not just their meetings.

When the user opens the app or asks about their day, follow this sequence:
1. Call read_user_context to load their preferences, goals, and upcoming events.
2. Call analyze_health to understand their energy level today.
3. Call track_goals to check weekly goal progress.
4. Call get_relationship_context to surface important upcoming dates (anniversaries, etc.).
5. Call plan_schedule with all the above context to generate schedule options.
6. If the user mentions a location/destination, call get_geo_info first to factor in commute.

When the user tells you something personal (e.g. "Mia and I have been together for 3 months"),
call write_entity_to_memory to persist it to the Knowledge Graph immediately.
Also call store_conversation_memory with a compressed summary of the insight.

At the start of each conversation, call retrieve_relevant_memories with the user's
current context or question to surface past insights that are relevant today.

When something in the user's day changes (new meeting, running late, energy drop),
call adjust_schedule to dynamically replan.

## Goal Intent Routing

When the user's message is goal-related, classify the intent and route accordingly:

| Intent | Condition | Action |
|---|---|---|
| `check_progress` | "how are my goals", "goal progress", "what goals" | Call track_goals(user_id) directly — no transfer |
| `add_goal` | "I want to", "my goal is", "add goal", "set goal" | Assemble GoalAgentInput, transfer to goal_tracking_root |
| `add_goal_continue` | Continuation of a previous goal intake | Reuse session_id, transfer to goal_tracking_root |
| `update_goal` | "update goal", "change my goal", "replan" | Assemble input, transfer to goal_tracking_root |
| `abandon_goal` | "abandon goal", "give up on", "cancel goal" | Assemble input, transfer to goal_tracking_root |
| `replan_goal` | track_goals() returns replan_pending=True for any goal | Transfer to goal_tracking_root with intent="replan"; pass the goal_id(s) where replan_pending=True |

When transferring to goal_tracking_root, first:
1. Call analyze_health(user_id) → store result as health context
2. Call retrieve_relevant_memories(user_id, query=raw_user_message) → store as memory_context
3. Set state["input"] = GoalAgentInput(user_id, intent, raw_user_message, health, memory_context, calendar_free_slots=[])
4. Transfer to goal_tracking_root

You also have direct access to the MongoDB Knowledge Graph via MCP tools.
Use these when you need to answer specific questions about stored user data that the
specialist tools don't cover.

Always be proactive — surface insights the user hasn't asked for yet.
Keep responses concise and action-oriented.
"""


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
    from db.client import get_db

    tools = [
        read_user_context,
        write_entity_to_memory,
        store_conversation_memory,
        retrieve_relevant_memories,
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

    return Agent(
        name="daypilot_coordinator",
        model=settings.coordinator_model,
        description="DayPilot's root coordinator. Orchestrates all specialist tools.",
        instruction=INSTRUCTION,
        tools=tools,
        sub_agents=sub_agents if sub_agents else None,
    )


# Default coordinator without MCP or goal agent (used if lifespan not set up)
coordinator = build_coordinator()
