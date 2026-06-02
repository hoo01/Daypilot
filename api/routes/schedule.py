from datetime import date, timedelta
from fastapi import APIRouter
from pydantic import BaseModel
from schemas import RealtimeInput, RealtimeOutput
from agents.tools.realtime_tools import adjust_schedule
from agents.memory import MemoryAgent
from db import get_db

router = APIRouter(prefix="/schedule", tags=["schedule"])


@router.post("/adjust", response_model=RealtimeOutput)
async def adjust_schedule_endpoint(body: RealtimeInput) -> RealtimeOutput:
    """Trigger a real-time schedule adjustment when something changes."""
    result = await adjust_schedule(
        user_id=body.user_id,
        current_schedule=[t.model_dump() for t in body.current_schedule],
        trigger=body.trigger,
        trigger_detail=body.trigger_detail,
    )
    return RealtimeOutput(**result)


class UncompletedTask(BaseModel):
    title: str
    scheduled_time: str


class FeedbackRequest(BaseModel):
    user_id: str
    date: str
    uncompleted_tasks: list[UncompletedTask]


class FeedbackResponse(BaseModel):
    message: str
    uncompleted: list[str]
    suggested_reschedule_date: str


@router.post("/feedback", response_model=FeedbackResponse)
async def submit_feedback(body: FeedbackRequest) -> FeedbackResponse:
    """Receive end-of-day task feedback and update goal progress."""
    uncompleted_titles = [t.title for t in body.uncompleted_tasks]

    # Update goal_state: reduce progress for any Leetcode/goal-related tasks not completed
    mem = MemoryAgent(get_db())
    goal_state = await mem.get_goal_state(body.user_id)
    if goal_state and goal_state.get("goals"):
        updated = False
        for goal in goal_state["goals"]:
            for task in body.uncompleted_tasks:
                if any(kw in task.title.lower() for kw in ["leetcode", "study", "practice", "workout"]):
                    goal["progress"] = max(0, goal.get("progress", 0) - 1)
                    updated = True
        if updated:
            await mem.upsert_goal_state(body.user_id, goal_state)

    suggested_date = (date.fromisoformat(body.date) + timedelta(days=1)).isoformat()
    count = len(uncompleted_titles)
    message = (
        f"Got it! You didn't complete {count} task{'s' if count > 1 else ''} today. "
        f"Want me to reschedule them for tomorrow?"
    )

    # Store uncompleted tasks so coordinator picks them up next turn
    await mem.update_preference(body.user_id, "pending_reschedule", {
        "tasks": uncompleted_titles,
        "original_date": body.date,
        "suggested_date": suggested_date,
    })

    return FeedbackResponse(
        message=message,
        uncompleted=uncompleted_titles,
        suggested_reschedule_date=suggested_date,
    )
