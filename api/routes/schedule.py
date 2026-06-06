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

    mem = MemoryAgent(get_db())

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
