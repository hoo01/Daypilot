"""Progress tracking agent: handles overdue notifications from Schedule Agent."""

from pathlib import Path
from motor.motor_asyncio import AsyncIOMotorDatabase

try:
    from google.adk.agents import LlmAgent  # type: ignore[import]
except ImportError:
    LlmAgent = None  # type: ignore[assignment,misc]

from app.tools.goal_db import get_goal, set_goal_status, recompute_progress_percent
from app.tools.subtask_db import get_sub_task
from app.tools.messaging import format_behind_schedule_reminder


def _load_prompt(name: str) -> str:
    return (Path(__file__).parent.parent / "prompts" / f"{name}.md").read_text()


def build_progress_tracking_agent(db: AsyncIOMotorDatabase, cfg: object) -> object:
    """Build the progress_tracking_agent."""

    async def tool_get_sub_task(goal_id: str, sub_task_id: str) -> dict | None:
        """Fetch a sub-task by goal_id and sub_task_id. Returns None if not found."""
        st = await get_sub_task(db, goal_id, sub_task_id)
        return st.model_dump(mode="json") if st else None

    async def tool_recompute_progress_percent(goal_id: str) -> float:
        """Recalculate and persist progress_percent for the goal."""
        return await recompute_progress_percent(db, goal_id)

    async def tool_get_goal(goal_id: str) -> dict | None:
        """Fetch a goal by goal_id."""
        goal = await get_goal(db, goal_id)
        return goal.model_dump(mode="json") if goal else None

    async def tool_set_goal_status(goal_id: str, new_status: str) -> dict | None:
        """Transition a goal to a new lifecycle status."""
        result = await set_goal_status(db, goal_id, new_status)
        return result.model_dump(mode="json") if result else None

    return LlmAgent(
        name="progress_tracking_agent",
        model="gemini-2.5-flash",
        instruction=_load_prompt("progress"),
        tools=[
            tool_get_sub_task,
            tool_recompute_progress_percent,
            tool_get_goal,
            tool_set_goal_status,
            format_behind_schedule_reminder,
        ],
        output_key="overdue.reminders",
    )
