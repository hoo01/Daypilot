"""Goal Tracking Root Agent — builds the full goal_tracking_root LlmAgent hierarchy."""
from pathlib import Path

from google.adk.agents import LlmAgent
from motor.motor_asyncio import AsyncIOMotorDatabase

from agents.goal.intake import build_goal_intake_agent
from agents.goal.progress import build_progress_tracking_agent
from agents.goal.overdue import build_overdue_handler_agent
from agents.goal.weekly_memory import build_weekly_memory_writer
from agents.goal.daily_output import build_daily_output_builder
from agents.tools.goal_db import (
    get_goal,
    list_active_goals,
    set_goal_status,
    recompute_progress_percent,
)
from agents.tools.subtask_db import mark_sub_task_complete

_ROOT_PROMPT = (Path(__file__).parent / "goal" / "prompts" / "root.md").read_text()


def build_goal_tracking_root(db: AsyncIOMotorDatabase, cfg) -> LlmAgent:
    """Build the goal_tracking_root LlmAgent with the full sub-agent hierarchy.

    Args:
        db: Motor AsyncIOMotorDatabase instance (same daypilot database).
        cfg: Settings instance from config.py.
    """
    standard_model = cfg.goal_model
    reasoning_model = cfg.goal_reasoning_model
    fast_model = cfg.goal_fast_model

    goal_intake_agent = build_goal_intake_agent(db, standard_model, fast_model, reasoning_model)
    progress_tracking_agent = build_progress_tracking_agent(db, standard_model)
    overdue_handler_agent = build_overdue_handler_agent(db, standard_model)
    weekly_memory_writer = build_weekly_memory_writer(db, reasoning_model, standard_model)
    daily_output_builder = build_daily_output_builder(db, standard_model)

    async def _get_goal(goal_id: str):
        return await get_goal(db, goal_id)

    async def _list_active_goals(user_id: str):
        return await list_active_goals(db, user_id)

    async def _set_goal_status(goal_id: str, new_status: str, updated_deadline=None):
        return await set_goal_status(db, goal_id, new_status, updated_deadline=updated_deadline)

    async def _recompute_progress(goal_id: str):
        return await recompute_progress_percent(db, goal_id)

    async def _mark_complete(goal_id: str, sub_task_id: str, completed_at):
        return await mark_sub_task_complete(db, goal_id, sub_task_id, completed_at)

    _get_goal.__name__ = "get_goal"
    _list_active_goals.__name__ = "list_active_goals"
    _set_goal_status.__name__ = "set_goal_status"
    _recompute_progress.__name__ = "recompute_progress_percent"
    _mark_complete.__name__ = "mark_sub_task_complete"

    return LlmAgent(
        name="goal_tracking_root",
        model=reasoning_model,
        description="Goal Tracking Agent root. Routes by intent to the appropriate sub-agent or tool.",
        instruction=_ROOT_PROMPT,
        sub_agents=[
            goal_intake_agent,
            progress_tracking_agent,
            overdue_handler_agent,
            weekly_memory_writer,
            daily_output_builder,
        ],
        tools=[
            _get_goal,
            _list_active_goals,
            _set_goal_status,
            _recompute_progress,
            _mark_complete,
        ],
    )
