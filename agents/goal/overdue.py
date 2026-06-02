from pathlib import Path

import httpx
from google.adk.agents import LlmAgent
from motor.motor_asyncio import AsyncIOMotorDatabase

from agents.tools.goal_db import get_goal, set_goal_status, update_goal
from agents.tools.goal_messaging import format_overdue_prompt
from config import settings

_PROMPT = (Path(__file__).parent / "prompts" / "overdue.md").read_text(encoding="utf-8")


def build_overdue_handler_agent(db: AsyncIOMotorDatabase, model: str) -> LlmAgent:
    async def _get_goal(goal_id: str):
        return await get_goal(db, goal_id)

    async def _set_status(goal_id: str, new_status: str, updated_deadline=None):
        return await set_goal_status(db, goal_id, new_status, updated_deadline=updated_deadline)

    async def _call_replan(goal_id: str, new_deadline: str, user_id: str):
        """Extend deadline: POST /v1/goals/{goal_id}/replan"""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{settings.goal_agent_url}/v1/goals/{goal_id}/replan",
                json={"new_deadline": new_deadline, "user_id": user_id},
            )
            response.raise_for_status()
            return response.json()

    async def _call_reduce_scope(goal_id: str, sub_task_ids: list, user_id: str):
        """Drop subtasks: POST /v1/goals/{goal_id}/reduce-scope"""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{settings.goal_agent_url}/v1/goals/{goal_id}/reduce-scope",
                json={"sub_task_ids": sub_task_ids, "user_id": user_id},
            )
            response.raise_for_status()
            return response.json()

    async def _clear_replan_flag(goal_id: str):
        """Used for 'Keep as-is' — clears flag without changing goal."""
        return await update_goal(db, goal_id, {"replan_requested_at": None})

    _get_goal.__name__ = "get_goal"
    _set_status.__name__ = "set_goal_status"
    _call_replan.__name__ = "call_replan"
    _call_reduce_scope.__name__ = "call_reduce_scope"
    _clear_replan_flag.__name__ = "clear_replan_flag"

    return LlmAgent(
        name="overdue_handler_agent",
        model=model,
        description="Handles replan and abandon decisions; enforces user confirmation before abandonment.",
        instruction=_PROMPT,
        tools=[_get_goal, _set_status, format_overdue_prompt, _call_replan, _call_reduce_scope, _clear_replan_flag],
    )
