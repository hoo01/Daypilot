from datetime import date, timedelta
from fastapi import APIRouter, Query
from pydantic import BaseModel
from schemas import RealtimeInput, RealtimeOutput
from agents.tools.realtime_tools import adjust_schedule
from agents.memory import MemoryAgent
from db import get_db
from db.collections import Collections
from telemetry import tracer, get_logger

_logger = get_logger("routes.schedule")

router = APIRouter(prefix="/schedule", tags=["schedule"])


@router.get("/today")
async def get_today_schedule(user_id: str = Query(...)) -> dict:
    """Return today's persisted schedule tasks, enriched with geo_segment per task."""
    today = date.today().isoformat()
    db = get_db()
    doc = await db[Collections.DAILY_SCHEDULES].find_one(
        {"user_id": user_id, "date": today},
        {"_id": 0, "tasks": 1},
    )
    if not doc:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="No schedule for today")

    
    

    tasks = doc.get("tasks", [])

    # Default: every task has no geo_segment (guaranteed even if geo enrichment fails)
    for t in tasks:
        t["geo_segment"] = None

    # Enrich tasks with geo_segment (origin → destination commute info)
    try:
        from agents.tools.geo_tools import get_geo_info

        mem = MemoryAgent(db)
        prefs = await mem.get_preferences(user_id)
        home = (prefs or {}).get("home_address") or "home"

        # Build time-ordered event list from tasks that have a location
        located = [
            {
                "location": t.get("location"),
                "start_time": t.get("start_time"),
                "end_time": t.get("end_time"),
                "task_id": t.get("task_id"),
            }
            for t in tasks
            if t.get("location")
        ]

        if located:
            geo = await get_geo_info(current_location=home, events=located)
            segments = geo.get("segments", [])
            # Map each segment back to its destination task (by order of located events)
            for ev, seg in zip(located, segments):
                if seg.get("mode") == "none" or not seg.get("maps_url"):
                    continue  # same-location or no route → no segment to show
                dur = seg.get("duration_minutes")
                geo_segment = {
                    "origin": seg.get("from"),
                    "destination": seg.get("to"),
                    "duration_text": f"{dur} min" if dur is not None else None,
                    "maps_url": seg.get("maps_url"),
                }
                for t in tasks:
                    if t.get("task_id") == ev["task_id"]:
                        t["geo_segment"] = geo_segment
                        break
    except Exception as e:
        _logger.error(f"[schedule/today] geo enrichment failed for {user_id}: {e}")
        # geo failure must not break schedule retrieval — tasks already have geo_segment=None

    return {"tasks": tasks}


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
    db = get_db()
    if body.proposal_type == "plan":
        strategies = body.proposal.get("strategies", [])
        top_name = body.proposal.get("top_recommendation", "")
        strategy = next(
            (s for s in strategies if s.get("name") == top_name),
            strategies[0] if strategies else None,
        )
        if not strategy:
            return {"status": "error", "detail": "strategy not found"}
        tasks = strategy.get("tasks", [])
        await db[Collections.DAILY_SCHEDULES].update_one(
            {"user_id": body.user_id, "date": today},
            {"$set": {
                "user_id": body.user_id,
                "date": today,
                "tasks": tasks,
                "strategy_name": top_name,
                "all_strategies": strategies,
                "confirmed": True,
            }},
            upsert=True,
        )
    else:
        tasks = body.proposal.get("updated_schedule", [])
        await db[Collections.DAILY_SCHEDULES].update_one(
            {"user_id": body.user_id, "date": today},
            {"$set": {
                "user_id": body.user_id,
                "date": today,
                "tasks": tasks,
                "strategy_name": "Adjusted",
                "confirmed": True,
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
