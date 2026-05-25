from fastapi import APIRouter, Depends
from schemas import RealtimeInput, RealtimeOutput
from agents import RealtimeAgent
from api.dependencies import get_realtime

router = APIRouter(prefix="/schedule", tags=["schedule"])


@router.post("/adjust", response_model=RealtimeOutput)
async def adjust_schedule(
    body: RealtimeInput,
    realtime: RealtimeAgent = Depends(get_realtime),
) -> RealtimeOutput:
    """Trigger a real-time schedule adjustment when something changes."""
    return await realtime.run(body)
