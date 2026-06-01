"""POST /v1/intake/turn, POST /v1/intake/confirm — goal intake multi-turn endpoints."""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request

from db.client import get_db
from schemas.goal_domain import Goal
from schemas.goal_intake import (
    IntakeConfirmRequest,
    IntakeTurnRequest,
    IntakeTurnResponse,
    IntakeTurn,
)
from agents.tools.intake_session_db import (
    append_intake_turn,
    complete_intake_session,
    resume_intake_session,
    save_intake_draft,
    start_intake_session,
)
from agents.tools.goal_db import create_goal, get_goal
from agents.tools.subtask_db import bulk_set_sub_tasks

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/intake", tags=["intake"])


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


async def _run_goal_agent(runner, user_id: str, session_id: str, message: str, state: dict) -> dict:
    """Drive the goal agent runner; handles both StubRunner (coroutine) and real ADK Runner (async gen)."""
    import inspect
    call = runner.run_async(
        user_id=user_id,
        session_id=session_id,
        new_message=message,
        state=state,
    )
    if inspect.iscoroutine(call):
        return await call
    # Real ADK Runner: iterate async generator for final response
    reply = ""
    async for event in call:
        if hasattr(event, "is_final_response") and event.is_final_response():
            if event.content and event.content.parts:
                reply = event.content.parts[0].text
            break
    return {"assistant_message": reply, "stage": state.get("intake.stage", "initial")}


@router.post("/turn", response_model=IntakeTurnResponse)
async def intake_turn(body: IntakeTurnRequest, request: Request) -> IntakeTurnResponse:
    db = get_db()

    if body.session_id:
        session = await resume_intake_session(db, body.session_id)
        if session is None:
            raise HTTPException(
                status_code=410,
                detail={"error": "intake_session_expired"},
            )
    else:
        session = await start_intake_session(db, body.user_id)

    runner = request.app.state.runner

    state = {
        "input": {
            "user_id": body.user_id,
            "intent": body.intent,
            "raw_user_message": body.raw_user_message,
            "health": body.health,
            "memory_context": body.memory_context,
            "calendar_free_slots": body.calendar_free_slots,
        },
        "intake.session_id": session.session_id,
        "intake.stage": session.stage,
        "intake.draft": session.draft,
        "intake.history": [t.model_dump(mode="json") for t in session.history],
    }

    result = await _run_goal_agent(runner, body.user_id, session.session_id, body.raw_user_message, state)

    assistant_message = result.get("assistant_message", "")
    new_stage = result.get("stage", session.stage)
    goal_id = result.get("goal_id")
    validation_failures = result.get("validation_failures", [])
    new_draft = result.get("draft", session.draft)

    await save_intake_draft(db, session.session_id, new_draft, new_stage)

    user_turn = IntakeTurn(role="user", content=body.raw_user_message, timestamp=_now_utc())
    agent_turn = IntakeTurn(role="agent", content=assistant_message, timestamp=_now_utc())
    await append_intake_turn(db, session.session_id, user_turn)
    await append_intake_turn(db, session.session_id, agent_turn)

    return IntakeTurnResponse(
        session_id=session.session_id,
        stage=new_stage,
        assistant_message=assistant_message,
        goal_id=goal_id,
        validation_failures=validation_failures,
    )


@router.post("/confirm", response_model=Goal)
async def intake_confirm(body: IntakeConfirmRequest, request: Request) -> Goal:
    db = get_db()

    session = await resume_intake_session(db, body.session_id)
    if session is None:
        raise HTTPException(
            status_code=410,
            detail={"error": "intake_session_expired"},
        )

    if not body.confirmed:
        # User rejected — restart confirming stage
        await save_intake_draft(db, body.session_id, session.draft, "decomposing")
        raise HTTPException(
            status_code=400,
            detail={"error": "confirmation_rejected", "message": "Returning to decomposition stage"},
        )

    goal_id = session.draft.get("goal_id")
    if goal_id is None:
        raise HTTPException(status_code=400, detail={"error": "no_goal_in_draft"})

    goal = await get_goal(db, goal_id)
    if goal is None:
        raise HTTPException(status_code=404, detail={"error": "goal_not_found", "goal_id": goal_id})

    await complete_intake_session(db, body.session_id, goal_id)
    return goal
