from datetime import date, timedelta
from fastapi import APIRouter, Query
from pydantic import BaseModel
from schemas import RealtimeInput, RealtimeOutput
from agents.tools.realtime_tools import adjust_schedule
from agents.tools.schedule_tools import _persist_schedule
from agents.memory import MemoryAgent
from db import get_db
from db.collections import Collections
from telemetry import tracer, get_logger

_logger = get_logger("routes.schedule")

router = APIRouter(prefix="/schedule", tags=["schedule"])


@router.get("/today")
async def get_today_schedule(user_id: str = Query(...)) -> dict:
    """Return today's persisted schedule tasks for a user."""
    today = date.today().isoformat()
    db = get_db()
    doc = await db[Collections.DAILY_SCHEDULES].find_one(
        {"user_id": user_id, "date": today},
        {"_id": 0, "tasks": 1},
    )
    if not doc:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="No schedule for today")
    return {"tasks": doc.get("tasks", [])}


@router.post("/adjust", response_model=RealtimeOutput)
async def adjust_schedule_endpoint(body: RealtimeInput) -> RealtimeOutput:
    """Trigger a real-time schedule adjustment when something changes."""
    try:
        result = await adjust_schedule(
            user_id=body.user_id,
            current_schedule=[t.model_dump() for t in body.current_schedule],
            trigger=body.trigger,
            trigger_detail=body.trigger_detail,
        )
        return RealtimeOutput(**result)
    except Exception as e:
        print(f"[schedule/adjust] Error for {body.user_id}: {e}")
        return RealtimeOutput(
            updated_schedule=[],
            message="I'm having trouble adjusting the schedule right now. Please try again in a moment.",
        )


class ScheduleConfirmRequest(BaseModel):
    user_id: str
    target_date: str
    proposal: dict
    proposal_type: str  # "plan" | "adjust"


@router.post("/confirm")
async def confirm_schedule(body: ScheduleConfirmRequest) -> dict:
    """Persist a pending schedule proposal after user confirmation."""
    today = body.target_date or date.today().isoformat()
    if body.proposal_type == "plan":
        await _persist_schedule(body.user_id, today, body.proposal)
    else:
        tasks = body.proposal.get("updated_schedule", [])
        db = get_db()
        await db[Collections.DAILY_SCHEDULES].update_one(
            {"user_id": body.user_id, "date": today},
            {"$set": {
                "user_id": body.user_id,
                "date": today,
                "tasks": tasks,
                "strategy_name": "Adjusted",
            }},
            upsert=True,
        )
    return {"status": "confirmed"}


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
