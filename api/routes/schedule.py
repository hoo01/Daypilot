from fastapi import APIRouter, Depends
from schemas import RealtimeInput, RealtimeOutput, ScheduleInput, ScheduleOutput
from agents import RealtimeAgent, ScheduleAgent
from api.dependencies import get_realtime, get_schedule

router = APIRouter(prefix="/schedule", tags=["schedule"])


@router.post("/generate", response_model=ScheduleOutput)
async def generate_schedule(
    body: ScheduleInput,
    schedule: ScheduleAgent = Depends(get_schedule),
) -> ScheduleOutput:
    """Generate a daily schedule from aggregated agent outputs."""
    return await schedule.run(body)


@router.post("/adjust", response_model=RealtimeOutput)
async def adjust_schedule(
    body: RealtimeInput,
    realtime: RealtimeAgent = Depends(get_realtime),
) -> RealtimeOutput:
    """Trigger a real-time schedule adjustment when something changes."""
    return await realtime.run(body)