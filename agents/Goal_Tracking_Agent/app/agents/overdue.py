"""Overdue handler agent: replan vs. abandon conversational decision tree."""

from pathlib import Path
from motor.motor_asyncio import AsyncIOMotorDatabase

try:
    from google.adk.agents import LlmAgent  # type: ignore[import]
except ImportError:
    LlmAgent = None  # type: ignore[assignment,misc]

from app.tools.goal_db import get_goal, set_goal_status
from app.tools.messaging import format_overdue_prompt


def _load_prompt(name: str) -> str:
    return (Path(__file__).parent.parent / "prompts" / f"{name}.md").read_text()


def build_overdue_handler_agent(db: AsyncIOMotorDatabase, cfg: object) -> object:
    """Build the overdue_handler_agent."""

    async def tool_get_goal(goal_id: str) -> dict | None:
        goal = await get_goal(db, goal_id)
        return goal.model_dump(mode="json") if goal else None

    async def tool_set_goal_status(
        goal_id: str,
        new_status: str,
        updated_deadline: str | None = None,
    ) -> dict | None:
        """Transition a goal to new_status; optionally update the deadline (ISO date string)."""
        result = await set_goal_status(db, goal_id, new_status, updated_deadline)
        return result.model_dump(mode="json") if result else None

    return LlmAgent(
        name="overdue_handler_agent",
        model="gemini-2.5-flash",
        instruction=_load_prompt("overdue"),
        tools=[
            tool_get_goal,
            tool_set_goal_status,
            format_overdue_prompt,
        ],
    )
