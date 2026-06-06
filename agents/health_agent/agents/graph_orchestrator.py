"""
graph_orchestrator.py — ADK Workflow wiring and Runner.

Topology:
    START → (node1, node2) in parallel  [fan-out]
    (node1, node2) → join → node3       [fan-in via JoinNode]
    node3 → {
        "PSYCHOLOGICAL" → node4
        "AMBIGUOUS"     → node4
        "PHYSICAL"      → END  (no conditional edge → workflow ends naturally)
        "NONE"          → END
    }
    node4 → END

Local:  Runner uses InMemorySessionService (dev/test).
Cloud:  Swap InMemorySessionService for VertexAiSessionService.
"""

from __future__ import annotations

from google.adk.workflow import FunctionNode, JoinNode, Workflow, START
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types as genai_types

from agents.health_agent.agents.nodes.healthkit_sentinel    import healthkit_sentinel
from agents.health_agent.agents.nodes.strava_contextualizer import strava_contextualizer
from agents.health_agent.agents.nodes.autonomic_decoupler   import autonomic_decoupler
from agents.health_agent.agents.nodes.insights_engine       import insights_engine
from agents.health_agent.agents.graph_state                 import PsychobioState


# ── Fan-in join: waits for BOTH node1 and node2 before firing node3 ─────────
_fan_in_join = JoinNode(name="fan_in_join")


# ── Workflow graph ────────────────────────────────────────────────────────────
#
# Note on conditional routing:
#   autonomic_decoupler sets ctx.route = verdict (e.g. "PSYCHOLOGICAL")
#   Edges with route= are only followed when the route matches.
# Node 4 always runs — unconditional edge from node3 to node4.
# Every run produces AI insights and a psychobiological score regardless of verdict.
root_workflow = Workflow(
    name="psychobio_root",
    state_schema=PsychobioState,
    edges=[
        # Fan-out: START fires both node1 and node2 in parallel
        (START, (healthkit_sentinel, strava_contextualizer)),

        # Fan-in: both nodes feed the join, join feeds node3
        (healthkit_sentinel,    _fan_in_join),
        (strava_contextualizer, _fan_in_join),
        (_fan_in_join, autonomic_decoupler),

        # Unconditional: node4 always runs after node3
        (autonomic_decoupler, insights_engine),
    ],
)


# ── Session service (swap for VertexAiSessionService in production) ──────────
_session_service = InMemorySessionService()


# ── Runner ───────────────────────────────────────────────────────────────────
runner = Runner(
    agent=root_workflow,
    app_name="psychobio_engine",
    session_service=_session_service,
)


async def run_pipeline(user_id: str, target_date: str, run_dir: str) -> dict:
    """
    Run the full PsychoBio pipeline for a user+date and return the final state.

    Args:
        user_id:     User identifier (e.g. "user_001").
        target_date: Date to analyse in YYYY-MM-DD format.
        run_dir:     Absolute path to the scenario data directory.

    Returns:
        Final session state dict with all node outputs populated.
    """
    initial_state = {
        "user_id":     user_id,
        "target_date": target_date,
        "run_dir":     run_dir,
    }

    session = await _session_service.create_session(
        app_name="psychobio_engine",
        user_id=user_id,
        state=initial_state,
    )

    # The trigger message is minimal — nodes read from session.state, not the message.
    trigger = genai_types.Content(
        parts=[genai_types.Part(text=f"Analyse {user_id} on {target_date}")]
    )

    async for _event in runner.run_async(
        user_id=user_id,
        session_id=session.id,
        new_message=trigger,
    ):
        pass  # Let all nodes run to completion

    final_session = await _session_service.get_session(
        app_name="psychobio_engine",
        user_id=user_id,
        session_id=session.id,
    )
    return dict(final_session.state)
