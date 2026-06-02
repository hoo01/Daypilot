from pathlib import Path

import httpx
from google.adk.agents import LlmAgent, SequentialAgent
from motor.motor_asyncio import AsyncIOMotorDatabase

from agents.tools.goal_db import list_active_goals
from agents.tools.memory_agent_client import write_weekly_summary
from config import settings

_PROMPT = (Path(__file__).parent / "prompts" / "weekly_memory.md").read_text(encoding="utf-8")


def build_weekly_memory_writer(db: AsyncIOMotorDatabase, reasoning_model: str, standard_model: str) -> SequentialAgent:
    async def _list_goals(user_id: str, statuses=None):
        s = statuses or ["COMPLETED", "ABANDONED", "IN_PROGRESS"]
        return await list_active_goals(db, user_id, statuses=s)

    async def _write_summary(user_id: str, week_start: str, summary_text: str):
        async with httpx.AsyncClient(timeout=30.0) as client:
            await write_weekly_summary(
                user_id=user_id,
                week_start=week_start,
                summary_text=summary_text,
                memory_agent_url=settings.memory_agent_url,
                http_client=client,
            )

    _list_goals.__name__ = "list_active_goals"
    _write_summary.__name__ = "write_weekly_summary"

    memory_analyzer = LlmAgent(
        name="memory_analyzer",
        model=reasoning_model,
        description="Reads past week's goal data and writes a structured analysis to state['weekly.analysis'].",
        instruction=_PROMPT,
        tools=[_list_goals],
    )
    memory_writer = LlmAgent(
        name="memory_writer",
        model=standard_model,
        description="Compresses weekly analysis into a ≤500-char summary and calls write_weekly_summary.",
        instruction=_PROMPT,
        tools=[_write_summary],
    )

    return SequentialAgent(
        name="weekly_memory_writer",
        sub_agents=[memory_analyzer, memory_writer],
    )
