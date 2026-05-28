"""Root agent: goal_tracking_root LlmAgent with all sub-agents."""

from pathlib import Path
from motor.motor_asyncio import AsyncIOMotorDatabase

try:
    from google.adk.agents import LlmAgent  # type: ignore[import]
except ImportError:
    LlmAgent = None  # type: ignore[assignment,misc]

from app.tools.goal_db import (
    list_active_goals,
    get_goal,
    set_goal_status,
    recompute_progress_percent,
)
from app.tools.subtask_db import mark_sub_task_complete, update_sub_task


def _load_prompt(name: str) -> str:
    return (Path(__file__).parent.parent / "prompts" / f"{name}.md").read_text()


def build_root_agent(
    db: AsyncIOMotorDatabase,
    cfg: object,
    goal_intake_agent: object,
    progress_tracking_agent: object,
    overdue_handler_agent: object,
    weekly_memory_writer: object,
    daily_output_builder: object,
) -> object:
    """Build the goal_tracking_root LlmAgent."""

    async def tool_list_active_goals(user_id: str) -> list:
        """List all active goals for a user."""
        goals = await list_active_goals(db, user_id)
        return [g.model_dump(mode="json") for g in goals]

    async def tool_get_goal(goal_id: str) -> dict | None:
        goal = await get_goal(db, goal_id)
        return goal.model_dump(mode="json") if goal else None

    async def tool_set_goal_status(
        goal_id: str,
        new_status: str,
        updated_deadline: str | None = None,
    ) -> dict | None:
        """Transition goal status; optionally update deadline."""
        result = await set_goal_status(db, goal_id, new_status, updated_deadline)
        return result.model_dump(mode="json") if result else None

    async def tool_mark_sub_task_complete(
        goal_id: str,
        sub_task_id: str,
        completed_at: str,
    ) -> dict | None:
        """Mark a sub-task as completed."""
        from datetime import datetime
        dt = datetime.fromisoformat(completed_at)
        st = await mark_sub_task_complete(db, goal_id, sub_task_id, dt)
        return st.model_dump(mode="json") if st else None

    async def tool_update_sub_task_planned_date(
        goal_id: str,
        sub_task_id: str,
        planned_date: str,
    ) -> dict | None:
        """Set planned_date on a sub-task (triggered by subtask_scheduled event)."""
        st = await update_sub_task(db, goal_id, sub_task_id, {"planned_date": planned_date})
        return st.model_dump(mode="json") if st else None

    async def tool_recompute_progress_percent(goal_id: str) -> float:
        return await recompute_progress_percent(db, goal_id)

    return LlmAgent(
        name="goal_tracking_root",
        model="gemini-2.5-pro-preview",
        instruction=_load_prompt("root"),
        tools=[
            tool_list_active_goals,
            tool_get_goal,
            tool_set_goal_status,
            tool_mark_sub_task_complete,
            tool_update_sub_task_planned_date,
            tool_recompute_progress_percent,
        ],
        sub_agents=[
            goal_intake_agent,
            progress_tracking_agent,
            overdue_handler_agent,
            weekly_memory_writer,
            daily_output_builder,
        ],
    )
