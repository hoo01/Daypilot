from fastapi import APIRouter
from schemas import RealtimeInput, RealtimeOutput
from agents.tools.realtime_tools import adjust_schedule

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
