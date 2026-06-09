import asyncio
import os
from google.adk.agents import Agent
from google.adk.agents.callback_context import CallbackContext
from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset, StdioConnectionParams
from google.genai import types as genai_types
from mcp import StdioServerParameters
from config import settings
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

## Two distinct response modes — pick exactly one per turn

**MODE A — Proactive insight (default for open/general questions)**
Triggers: "What should I focus on today?", "How's my day looking?", "What's up today?", or anything
that isn't an explicit planning request.
Action: Answer ONLY using the <user_context> already loaded above — write 3-4 short, specific,
warm sentences covering proactive suggestions, goal progress, and focus window/energy pattern.
HARD RULE: Do NOT call plan_schedule in this mode. Do NOT output a timed task list / schedule
table. If you find yourself writing "8:00 AM - 9:00 AM: ..." in MODE A, STOP — you are in the
wrong mode.

**MODE B — Schedule generation (only on explicit request)**
Triggers: ONLY explicit asks like "plan my day", "build/generate my schedule", "what does my
schedule look like today" (i.e. the user is asking FOR a schedule artifact, not just an opinion
on focus).
Action: Call plan_schedule and present the resulting strategies.

Why this distinction matters: plan_schedule is slow (it generates a full multi-strategy JSON
schedule) and produces a wall of text. Calling it for an open question like "what should I focus
on" makes the conversation feel sluggish and buries the quick personal insight the user actually
wanted under timing details they didn't ask for.

You can call additional tools when needed:
- write_entity_to_memory / store_conversation_memory: when user shares personal info
- retrieve_relevant_memories: to recall past context
- plan_schedule: ONLY when the user explicitly asks to plan/build/generate their schedule —
  generates detailed schedule options with health/goal/geo context.
  CRITICAL rules for calendar_events:
  1. Whenever the user mentions a specific event (e.g. "doctor appointment 3-4pm", "ML class at the library"), you MUST pass it as a SEPARATE calendar_event entry in the calendar_events argument — never merge it into a generic study/personal/break block.
  2. ALSO check <user_context> for "Upcoming events" happening TODAY (days_away: 0) — even if the user did NOT mention them in this message (e.g. user just says "plan my day"). Any such event with a stated time MUST also be passed as its own calendar_event entry. This is the core "DayPilot already knows" behavior — never silently drop a known event from today's plan just because the user didn't restate it.
  3. Use the exact title from the user's wording or the context entry (e.g. "Doctor Appointment", "ML Class"). Never use generic labels like "Event".
  4. If a location is given (by the user or in the context entry), you MUST include it in the location field of that calendar_event. If no location is given, omit it.
  5. The resulting schedule MUST visibly contain that event as its own task at the stated time. Before telling the user you added it, verify it actually appears in the schedule you generated.
- get_geo_info: when locations/commute are relevant
- adjust_schedule: when the user has an EXISTING active schedule for today and something changes mid-day (new event, task overrun, energy drop). Requires the current schedule as input — only use this when you have a schedule to pass.
- plan_schedule: also use this when rescheduling missed tasks to a future date (no existing schedule needed — it generates a fresh plan)
- analyze_health: for energy/sleep analysis. Returns energy_level,
  focus_window, cognitive_load_score, and avoid_tasks.

You also have access to Dynatrace observability tools for self-monitoring:
- Use Dynatrace to check your own health when the user asks about performance
- If you detect issues (slow responses, errors), proactively inform the user
- When asked "how are you performing?", query Dynatrace for latency, error rates, and token usage
- If health pipeline data seems stale or unavailable, check Dynatrace for recent errors

Always be proactive — surface insights the user hasn't asked for yet.
Keep responses concise and action-oriented.

IMPORTANT: After calling plan_schedule or adjust_schedule, ALWAYS present the result to the user and ask for confirmation before considering it final. Say something like "Here's your proposed schedule — shall I confirm this plan?" Never tell the user the schedule has been saved without their explicit agreement. NEVER claim you added or changed something unless it actually appears in the schedule you just generated — do not describe events or tasks that are not present in the tool output.
"""


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
                        f"When the user asks about rescheduling, proactively suggest moving these tasks to "
                        f"{pending.get('suggested_date')} and ask for confirmation. "
                        f"If the user confirms, call plan_schedule with target_date={pending.get('suggested_date')} "
                        f"to generate a new schedule for that day that incorporates the missed tasks. "
                        f"After presenting the plan, call clear_pending_reschedule to remove this pending item."
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


def build_coordinator(mcp_tools=None, dynatrace_mcp=None, goal_tracking_root=None) -> Agent:
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
    if dynatrace_mcp:
        tools.append(dynatrace_mcp)

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
        generate_content_config=genai_types.GenerateContentConfig(
            thinking_config=genai_types.ThinkingConfig(thinking_budget=0),
        ),
    )
    if sub_agents:
        agent_kwargs["sub_agents"] = sub_agents
    return Agent(**agent_kwargs)


# Default coordinator without MCP or goal agent (used if lifespan not set up)
coordinator = build_coordinator()