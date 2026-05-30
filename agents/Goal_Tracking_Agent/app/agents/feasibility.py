"""Feasibility workflow: SequentialAgent( ParallelAgent(3 layers), synthesis )."""

from pathlib import Path
from motor.motor_asyncio import AsyncIOMotorDatabase

try:
    from google.adk.agents import LlmAgent, SequentialAgent, ParallelAgent  # type: ignore[import]
except ImportError:
    LlmAgent = None      # type: ignore[assignment,misc]
    SequentialAgent = None  # type: ignore[assignment,misc]
    ParallelAgent = None  # type: ignore[assignment,misc]

from app.tools.feasibility_calc import time_feasibility, habit_feasibility, load_feasibility, synthesize_feasibility
from app.tools.goal_db import list_active_goals
from app.tools.messaging import format_feasibility_proposal
from app.tools.calendar_api import free_slots_to_minutes


def _load_prompt(name: str) -> str:
    return (Path(__file__).parent.parent / "prompts" / f"{name}.md").read_text()


def build_feasibility_workflow(db: AsyncIOMotorDatabase, cfg: object) -> object:
    """Build the feasibility_workflow SequentialAgent.

    Structure:
        feasibility_workflow (SequentialAgent)
        └── feasibility_parallel (ParallelAgent)
            ├── time_feasibility_agent   writes state["feasibility.time"]
            ├── habit_feasibility_agent  writes state["feasibility.habit"]
            └── load_feasibility_agent   writes state["feasibility.load"]
        └── feasibility_synthesis_agent  reads all three, writes state["feasibility.proposal"]
    """

    # ── per-layer tool wrappers bound to the db ───────────────────────────────

    async def tool_list_active_goals_in_progress(user_id: str) -> list:
        """List all IN_PROGRESS goals for a user (for load feasibility check)."""
        goals = await list_active_goals(db, user_id, statuses=["IN_PROGRESS"])
        return [g.model_dump(mode="json") for g in goals]

    # ── layer agents ─────────────────────────────────────────────────────────

    time_feasibility_agent = LlmAgent(
        name="time_feasibility_agent",
        model="gemini-2.5-flash",
        instruction=_load_prompt("feasibility_time"),
        tools=[time_feasibility, free_slots_to_minutes],
        output_key="feasibility.time",
    )

    habit_feasibility_agent = LlmAgent(
        name="habit_feasibility_agent",
        model="gemini-2.5-flash",
        instruction=_load_prompt("feasibility_habit"),
        tools=[habit_feasibility],
        output_key="feasibility.habit",
    )

    load_feasibility_agent = LlmAgent(
        name="load_feasibility_agent",
        model="gemini-2.5-flash",
        instruction=_load_prompt("feasibility_load"),
        tools=[load_feasibility, tool_list_active_goals_in_progress],
        output_key="feasibility.load",
    )

    feasibility_parallel = ParallelAgent(
        name="feasibility_parallel",
        sub_agents=[time_feasibility_agent, habit_feasibility_agent, load_feasibility_agent],
    )

    # ── synthesis agent ───────────────────────────────────────────────────────

    feasibility_synthesis_agent = LlmAgent(
        name="feasibility_synthesis_agent",
        model="gemini-2.5-pro-preview",
        instruction=_load_prompt("feasibility_synthesis"),
        tools=[synthesize_feasibility, format_feasibility_proposal],
        output_key="feasibility.proposal",
    )

    return SequentialAgent(
        name="feasibility_workflow",
        sub_agents=[feasibility_parallel, feasibility_synthesis_agent],
    )
