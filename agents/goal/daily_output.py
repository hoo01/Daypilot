from pathlib import Path

from google.adk.agents import LlmAgent
from motor.motor_asyncio import AsyncIOMotorDatabase

from agents.tools.goal_db import list_active_goals

_PROMPT = (Path(__file__).parent / "prompts" / "daily_output.md").read_text()


def build_daily_output_builder(db: AsyncIOMotorDatabase, model: str) -> LlmAgent:
    async def _list_goals(user_id: str):
        return await list_active_goals(db, user_id)

    _list_goals.__name__ = "list_active_goals"

    return LlmAgent(
        name="daily_output_builder",
        model=model,
        description="Assembles GoalsOutput for all active goals; strips planned_date from GoalSubTask.",
        instruction=_PROMPT,
        tools=[_list_goals],
    )
