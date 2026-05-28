import logging
from fastapi import APIRouter, Depends, HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.api.deps import get_db, get_runner, verify_bearer
from app.runtime.adk_runner import AdkRunner
from app.runtime.errors import IntakeSessionExpired, GoalNotFound
from app.schemas.intake import IntakeTurnRequest, IntakeTurnResponse, IntakeConfirmRequest
from app.schemas.domain import Goal
from app.tools.intake_session_db import resume_intake_session, complete_intake_session
from app.tools.goal_db import get_goal
from app.tools.subtask_db import bulk_set_sub_tasks

logger = logging.getLogger(__name__)
router = APIRouter(tags=["intake"])


@router.post("/intake/turn", response_model=IntakeTurnResponse)
async def intake_turn(
    body: IntakeTurnRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
    runner: AdkRunner = Depends(get_runner),
    _: None = Depends(verify_bearer),
) -> IntakeTurnResponse:
    """One ADK turn in the goal intake conversation.

    - intent="add_goal"          → starts a new session
    - intent="add_goal_continue" → resumes an existing session by session_id
    """
    import json

    if body.intent == "add_goal_continue" and body.session_id:
        session = await resume_intake_session(db, body.session_id)
        if session is None:
            raise IntakeSessionExpired(body.session_id)
        session_id = session.session_id
        adk_session = await runner.get_session(body.user_id, session_id)
        if adk_session is None:
            # Re-create ADK session from existing Mongo intake session
            state = {"input": body.model_dump(mode="json"), "intake": {"session_id": session_id}}
            adk_session = await runner.create_session(body.user_id, state=state, session_id=session_id)
    else:
        # New session
        state = {"input": body.model_dump(mode="json")}
        adk_session = await runner.create_session(body.user_id, state=state)
        session_id = adk_session.id

    try:
        response_text = await runner.run(
            user_id=body.user_id,
            session_id=session_id,
            message=body.raw_user_message,
        )
    except Exception as exc:
        logger.exception("ADK runner error during intake turn: %s", exc)
        response_text = "I need a moment — could you try again?"

    # Read updated state from the session
    updated_session = await runner.get_session(body.user_id, session_id)
    state_dict = updated_session.state if updated_session else {}

    stage = state_dict.get("intake", {}).get("stage", "initial")
    validation_failures = state_dict.get("validation", {}).get("failures", [])
    goal_id = state_dict.get("intake", {}).get("draft", {}).get("goal_id")

    return IntakeTurnResponse(
        session_id=session_id,
        stage=stage,
        assistant_message=response_text,
        goal_id=goal_id,
        validation_failures=validation_failures,
    )


@router.post("/intake/confirm", response_model=Goal)
async def intake_confirm(
    body: IntakeConfirmRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
    runner: AdkRunner = Depends(get_runner),
    _: None = Depends(verify_bearer),
) -> Goal:
    """Finalize the intake session.

    If confirmed=True: writes the goal, sets sub-tasks, closes the session.
    If confirmed=False: resets the confirming stage for another attempt.
    """
    session = await resume_intake_session(db, body.session_id)
    if session is None:
        raise IntakeSessionExpired(body.session_id)

    if not body.confirmed:
        # Reset to decomposing stage so the user can edit sub-tasks
        from app.tools.intake_session_db import save_intake_draft
        await save_intake_draft(db, body.session_id, session.draft, "decomposing")
        raise HTTPException(status_code=400, detail="Confirmation declined — session reset to decomposing stage")

    # Retrieve the finalized goal_id from session draft
    goal_id = session.draft.get("goal_id")
    if not goal_id:
        raise HTTPException(status_code=422, detail="No goal_id found in session draft")

    goal = await get_goal(db, goal_id)
    if goal is None:
        raise GoalNotFound(goal_id)

    await complete_intake_session(db, body.session_id, goal_id)
    return goal
