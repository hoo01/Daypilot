import os
from google.adk.agents import Agent
from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset, StdioConnectionParams
from mcp import StdioServerParameters
from config import settings
from agents.tools import (
    read_user_context,
    write_entity_to_memory,
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

When something in the user's day changes (new meeting, running late, energy drop),
call adjust_schedule to dynamically replan.

You also have direct access to the MongoDB Knowledge Graph via MCP tools.
Use these when you need to answer specific questions about stored user data that the
specialist tools don't cover.

Always be proactive — surface insights the user hasn't asked for yet.
Keep responses concise and action-oriented.
"""

mongo_mcp = MCPToolset(
    connection_params=StdioConnectionParams(
        server_params=StdioServerParameters(
            command="npx",
            args=["-y", "mongodb-mcp-server"],
            env={**os.environ, "MDB_MCP_CONNECTION_STRING": settings.mongodb_uri},
        ),
    )
)

coordinator = Agent(
    name="daypilot_coordinator",
    model=settings.coordinator_model,
    description="DayPilot's root coordinator. Orchestrates all specialist tools.",
    instruction=INSTRUCTION,
    tools=[
        read_user_context,
        write_entity_to_memory,
        analyze_health,
        track_goals,
        get_relationship_context,
        plan_schedule,
        get_geo_info,
        adjust_schedule,
        mongo_mcp,
    ],
)
