"""Daily output builder: assembles GoalsOutput for the Schedule Planning Agent."""

import logging
from pathlib import Path
from datetime import date, datetime, timezone
from motor.motor_asyncio import AsyncIOMotorDatabase

try:
    from google.adk.agents import LlmAgent  # type: ignore[import]
except ImportError:
    LlmAgent = None  # type: ignore[assignment,misc]

from app.tools.goal_db import list_active_goals
from app.tools.calendar_api import fetch_free_windows, sum_free_minutes
from app.tools.feasibility_calc import synthesize_feasibility

logger = logging.getLogger(__name__)


def _load_prompt(name: str) -> str:
    return (Path(__file__).parent.parent / "prompts" / f"{name}.md").read_text()


def build_daily_output_builder(
    db: AsyncIOMotorDatabase,
    cfg: object,
    calendar_service: object | None = None,
) -> object:
    """Build the daily_output_builder LlmAgent."""

    async def tool_list_active_goals(user_id: str) -> list:
        """List all active goals for a user."""
        goals = await list_active_goals(db, user_id)
        return [g.model_dump(mode="json") for g in goals]

    async def tool_build_goals_output(user_id: str) -> list:
        """Assemble GoalsOutput list for all active goals of a user.

        Strips planned_date from every GoalSubTask to enforce the output contract.
        """
        from app.schemas.output import GoalsOutput, GoalSubTask
        from app.db.collections import EVENT_LOG
        import uuid

        goals = await list_active_goals(db, user_id)
        today = date.today()
        outputs = []

        for goal in goals:
            remaining_effort = int(
                goal.total_effort_minutes * (1 - goal.progress_percent / 100)
            )

            days_to_deadline = (goal.deadline - today).days
            if days_to_deadline <= 0:
                urgency = "high"
            elif days_to_deadline <= 3:
                urgency = "medium"
            else:
                urgency = "low"

            daily_sub_tasks = []
            for st in goal.sub_tasks:
                if st.is_completed:
                    continue
                # CRITICAL: never pass planned_date to GoalSubTask
                sub_task_data = {
                    "title": st.title,
                    "estimated_minutes": st.estimated_minutes,
                    "priority": st.priority,
                    "deadline": str(st.deadline),
                    "preferred_time_of_day": st.preferred_time_of_day,
                    "can_split": st.can_split,
                }
                if "planned_date" in sub_task_data:
                    logger.warning(
                        "planned_date leaked into GoalSubTask for goal %s — stripping",
                        goal.goal_id,
                    )
                    sub_task_data.pop("planned_date", None)
                daily_sub_tasks.append(GoalSubTask(**sub_task_data))

            out = GoalsOutput(
                goal_id=goal.goal_id,
                urgency=urgency,
                feasibility_score=goal.feasibility_score,
                feasibility_note=goal.feasibility_note,
                total_effort_minutes=remaining_effort,
                suggested_blocks_count=goal.suggested_blocks_count,
                suggested_split_ratio=goal.suggested_split_ratio,
                daily_sub_tasks=daily_sub_tasks,
            )
            outputs.append(out)

            # Persist to event_log for Schedule Agent consumption
            event = {
                "event_id": str(uuid.uuid4()),
                "event_type": "daily_output",
                "goal_id": goal.goal_id,
                "sub_task_id": None,
                "payload": out.model_dump(mode="json"),
                "received_at": datetime.now(timezone.utc).isoformat(),
                "processed_at": datetime.now(timezone.utc).isoformat(),
                "status": "processed",
                "warnings": [],
            }
            await db[EVENT_LOG].insert_one(event)

        return [o.model_dump(mode="json") for o in outputs]

    return LlmAgent(
        name="daily_output_builder",
        model="gemini-2.5-flash",
        instruction=_load_prompt("daily_output"),
        tools=[tool_list_active_goals, tool_build_goals_output],
        output_key="output.daily",
    )
