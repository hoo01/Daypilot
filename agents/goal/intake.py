import functools
import inspect
from pathlib import Path

from google.adk.agents import LlmAgent
from google.adk.tools.agent_tool import AgentTool
from google.adk.tools.tool_context import ToolContext
from motor.motor_asyncio import AsyncIOMotorDatabase

from agents.goal.validation import build_validation_loop
from agents.goal.decomposition import build_decomposition_agent
from agents.goal.feasibility import build_feasibility_workflow
from agents.tools.goal_db import create_goal, get_goal, list_active_goals
from agents.tools.subtask_db import bulk_set_sub_tasks
from agents.tools.intake_session_db import (
    start_intake_session,
    resume_intake_session,
    append_intake_turn,
    save_intake_draft,
    complete_intake_session,
)
from agents.tools.feasibility_calc import (
    time_feasibility,
    habit_feasibility,
    load_feasibility,
    synthesize_feasibility,
)

_PROMPT = (Path(__file__).parent / "prompts" / "intake.md").read_text(encoding="utf-8")


def build_goal_intake_agent(
    db: AsyncIOMotorDatabase,
    standard_model: str,
    fast_model: str,
    reasoning_model: str,
) -> LlmAgent:
    validation_loop = build_validation_loop(standard_model)
    decomposition_agent = build_decomposition_agent(reasoning_model)
    feasibility_workflow = build_feasibility_workflow(fast_model, standard_model, reasoning_model)

    def _make_db_tool(fn):
        """Binds db to a tool function, exposing the signature minus the 'db' param."""
        sig = inspect.signature(fn)
        params = list(sig.parameters.values())[1:]  # drop 'db'
        new_sig = sig.replace(parameters=params)

        @functools.wraps(fn)
        async def tool(*args, **kwargs):
            return await fn(db, *args, **kwargs)

        tool.__signature__ = new_sig
        return tool

    async def save_intake_tracking(
        session_id: str,
        stage: str,
        tool_context: ToolContext,
    ) -> str:
        """Persist intake session_id and stage into ADK state so it survives across HTTP turns."""
        tool_context.state["intake_session_id"] = session_id
        tool_context.state["intake_stage"] = stage
        return "ok"

    tools = [
        save_intake_tracking,
        _make_db_tool(create_goal),
        _make_db_tool(get_goal),
        _make_db_tool(list_active_goals),
        _make_db_tool(bulk_set_sub_tasks),
        _make_db_tool(start_intake_session),
        _make_db_tool(resume_intake_session),
        _make_db_tool(append_intake_turn),
        _make_db_tool(save_intake_draft),
        _make_db_tool(complete_intake_session),
        time_feasibility,
        habit_feasibility,
        load_feasibility,
        synthesize_feasibility,
    ]

    tools.extend([
        AgentTool(validation_loop),
        AgentTool(decomposition_agent),
        AgentTool(feasibility_workflow),
    ])

    return LlmAgent(
        name="goal_intake_agent",
        model=standard_model,
        description="Multi-turn goal intake: guides user through goal creation, validation, decomposition, feasibility.",
        instruction=_PROMPT,
        tools=tools,
    )
