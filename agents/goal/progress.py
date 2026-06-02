from pathlib import Path

from google.adk.agents import LlmAgent
from motor.motor_asyncio import AsyncIOMotorDatabase

from agents.tools.goal_db import get_goal, recompute_progress_percent
from agents.tools.subtask_db import get_sub_task
from agents.tools.goal_messaging import format_behind_schedule_reminder

_PROMPT = (Path(__file__).parent / "prompts" / "progress.md").read_text(encoding="utf-8")


def build_progress_tracking_agent(db: AsyncIOMotorDatabase, model: str) -> LlmAgent:
    async def _get_goal(goal_id: str):
        return await get_goal(db, goal_id)

    async def _recompute(goal_id: str):
        return await recompute_progress_percent(db, goal_id)

    async def _get_sub_task(goal_id: str, sub_task_id: str):
        return await get_sub_task(db, goal_id, sub_task_id)

    _get_goal.__name__ = "get_goal"
    _recompute.__name__ = "recompute_progress_percent"
    _get_sub_task.__name__ = "get_sub_task"

    return LlmAgent(
        name="progress_tracking_agent",
        model=model,
        description="Handles overdue notifications; recomputes progress; generates reminder strings.",
        instruction=_PROMPT,
        tools=[_get_goal, _recompute, _get_sub_task, format_behind_schedule_reminder],
    )
