from datetime import date, timedelta
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from schemas import RealtimeInput, RealtimeOutput
from schemas.day_plan import ADJUSTED_STRATEGY, ConfirmProposal, DayPlanError
from agents.tools.realtime_tools import _run_adjust_llm
from agents.memory import MemoryAgent
from db import get_db
from services.day_plan_service import DayPlanService, today_for
from telemetry import tracer, get_logger

_logger = get_logger("routes.schedule")

router = APIRouter(prefix="/schedule", tags=["schedule"])


def _day_plan_error(e: DayPlanError) -> HTTPException:
    return HTTPException(status_code=409, detail={"code": e.code, "reason": e.reason, "message": e.message})


@router.get("/day")
async def get_day_plan(user_id: str = Query(...), date: str | None = Query(None)) -> dict:
    """Return the full DayPlan (active + proposal + version + status) for a date."""
    plan = await DayPlanService().get(user_id, date or today_for(user_id))
    return plan.model_dump(mode="json")


@router.get("/today")
async def get_today_schedule(user_id: str = Query(...)) -> dict:
    """Return today's confirmed (active) schedule tasks, enriched with geo_segment per task."""
    db = get_db()
    plan = await DayPlanService().get(user_id, today_for(user_id))
    if plan.active is None:
        raise HTTPException(status_code=404, detail="No schedule for today")

    tasks = [t.model_dump() for t in plan.active.tasks]

    # Default: every task has no geo_segment (guaranteed even if geo enrichment fails)
    for t in tasks:
        t["geo_segment"] = None

    # Enrich tasks with geo_segment (origin → destination commute info)
    try:
        from agents.tools.geo_tools import get_geo_info

        mem = MemoryAgent(db)
        prefs = await mem.get_preferences(user_id)
        home = (prefs or {}).get("home_address") or "home"

        # Build time-ordered event list from destination tasks that have a location.
        # Commute blocks (type=="commute" or title starts with "Commute") are excluded
        # so geo_segment is only ever attached to the actual destination event.
        located = [
            {
                "location": t.get("location"),
                "start_time": t.get("start_time"),
                "end_time": t.get("end_time"),
                "task_id": t.get("task_id"),
            }
            for t in tasks
            if t.get("location")
            and t.get("type") != "commute"
            and not (t.get("title") or "").lower().startswith("commute")
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
        # Stateless preview: nothing is persisted here. Adjustments that should become the
        # user's plan go through the chat orchestrator → DayPlanService.
        result = await _run_adjust_llm(
            [t.model_dump() for t in body.current_schedule], body.trigger, body.trigger_detail,
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
    date: str | None = None
    proposal_id: str | None = None
    strategy_name: str | None = None
    # Legacy payload (pre-orchestrator frontend). Only used to infer which strategy the
    # user picked — any tasks sent by the client are ignored (§5.3 invariant 4).
    target_date: str | None = None
    proposal: dict | None = None
    proposal_type: str | None = None


@router.post("/confirm")
async def confirm_schedule(body: ScheduleConfirmRequest) -> dict:
    """Confirm one strategy of the stored proposal. The tasks always come from the DB."""
    day = body.date or body.target_date or today_for(body.user_id)
    strategy_name = body.strategy_name
    if strategy_name is None and body.proposal_type == "adjust":
        strategy_name = ADJUSTED_STRATEGY
    if strategy_name is None and body.proposal:
        strategy_name = body.proposal.get("top_recommendation") or None
    try:
        plan = await DayPlanService().handle(ConfirmProposal(
            user_id=body.user_id, date=day, proposal_id=body.proposal_id, strategy_name=strategy_name,
        ))
    except DayPlanError as e:
        raise _day_plan_error(e)
    return {"status": "confirmed", "day_plan": plan.model_dump(mode="json")}


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
