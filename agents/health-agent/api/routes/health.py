"""
api/routes/health.py — FastAPI route handlers for the Health Agent microservice.

Exposes:
    POST /health/analyse  — run the full PsychoBio ADK pipeline
    GET  /health/ping     — health check
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from schemas import HealthPipelineInput, HealthPipelineOutput
from agents.graph_orchestrator import run_pipeline

router = APIRouter()


@router.post("/health/analyse", response_model=HealthPipelineOutput)
async def analyse(body: HealthPipelineInput) -> HealthPipelineOutput:
    """
    Run the PsychoBio pipeline for a user+date and return a typed result.

    The Coordinator (or any caller) sends user_id, target_date, and run_dir.
    The response is a HealthPipelineOutput compatible with the root monolith's
    HealthOutput / ScheduleInput schema.
    """
    try:
        state = await run_pipeline(
            user_id=body.user_id,
            target_date=body.target_date,
            run_dir=body.run_dir,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return HealthPipelineOutput.from_state(state)


@router.get("/health/ping")
async def ping() -> dict:
    """Health check — used by the orchestrator to verify the service is up."""
    return {"status": "ok", "service": "health-agent"}
