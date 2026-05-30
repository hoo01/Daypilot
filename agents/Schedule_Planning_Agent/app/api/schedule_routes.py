import logging
from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import verify_bearer
from app.agent.schedule_agent import ScheduleAgent

# Schemas are on sys.path via the monorepo root insertion in schedule_agent.py
from schemas import ScheduleInput, ScheduleOutput

logger = logging.getLogger(__name__)
router = APIRouter(tags=["schedule"])

_agent: ScheduleAgent | None = None


def _get_agent() -> ScheduleAgent:
    global _agent
    if _agent is None:
        _agent = ScheduleAgent()
    return _agent


@router.post("/schedule/generate", response_model=ScheduleOutput)
async def generate_schedule(
    body: ScheduleInput,
    _: None = Depends(verify_bearer),
) -> ScheduleOutput:
    """Generate 3 daily schedule strategies from the provided context."""
    try:
        return await _get_agent().run(body)
    except Exception as exc:
        logger.exception("Schedule generation failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )
