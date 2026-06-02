from pathlib import Path

from google.adk.agents import LlmAgent
from motor.motor_asyncio import AsyncIOMotorDatabase

from agents.tools.goal_db import get_goal, set_goal_status
from agents.tools.goal_messaging import format_overdue_prompt

_PROMPT = (Path(__file__).parent / "prompts" / "overdue.md").read_text(encoding="utf-8")


def build_overdue_handler_agent(db: AsyncIOMotorDatabase, model: str) -> LlmAgent:
    async def _get_goal(goal_id: str):
        return await get_goal(db, goal_id)

    async def _set_status(goal_id: str, new_status: str, updated_deadline=None):
        return await set_goal_status(db, goal_id, new_status, updated_deadline=updated_deadline)

    _get_goal.__name__ = "get_goal"
    _set_status.__name__ = "set_goal_status"

    return LlmAgent(
        name="overdue_handler_agent",
        model=model,
        description="Handles replan and abandon decisions; enforces user confirmation before abandonment.",
        instruction=_PROMPT,
        tools=[_get_goal, _set_status, format_overdue_prompt],
    )
