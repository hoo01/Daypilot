from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


# ── Domain exceptions ─────────────────────────────────────────────────────────

class GoalNotFound(Exception):
    def __init__(self, goal_id: str) -> None:
        self.goal_id = goal_id
        super().__init__(f"Goal not found: {goal_id}")


class IntakeSessionExpired(Exception):
    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        super().__init__(f"Intake session expired or not found: {session_id}")


class CalendarUnavailable(Exception):
    """Raised when the Google Calendar API is unreachable or returns an error."""


class AgentRunError(Exception):
    """Raised when the ADK runner surfaces an unrecoverable agent error."""


# ── FastAPI exception handlers ────────────────────────────────────────────────

def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(GoalNotFound)
    async def goal_not_found_handler(request: Request, exc: GoalNotFound) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"error": "goal_not_found", "goal_id": exc.goal_id},
        )

    @app.exception_handler(IntakeSessionExpired)
    async def intake_session_expired_handler(
        request: Request, exc: IntakeSessionExpired
    ) -> JSONResponse:
        return JSONResponse(
            status_code=410,
            content={
                "error": "intake_session_expired",
                "message": (
                    "Your previous goal setup session has expired. "
                    "Would you like to start a new one?"
                ),
            },
        )

    @app.exception_handler(AgentRunError)
    async def agent_run_error_handler(
        request: Request, exc: AgentRunError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=200,
            content={
                "error": "agent_run_error",
                "message": "I need a moment — could you try again?",
            },
        )
