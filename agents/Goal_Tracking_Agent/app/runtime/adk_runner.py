"""ADK Runner factory — builds one Runner per FastAPI lifespan."""

import logging
from typing import Any, AsyncGenerator, Optional

import httpx
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.runtime.session_service import MongoSessionService

try:
    from google.adk.runners import Runner  # type: ignore[import]
    from google.adk.types import Content, Part  # type: ignore[import]
    _ADK_AVAILABLE = True
except ImportError:
    _ADK_AVAILABLE = False
    Runner = None       # type: ignore[assignment,misc]
    Content = None      # type: ignore[assignment,misc]
    Part = None         # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)

APP_NAME = "goal_tracking_agent"


class AdkRunner:
    """Thin wrapper around google.adk.runners.Runner that holds the session service."""

    def __init__(self, runner: Any, session_service: MongoSessionService) -> None:
        self._runner = runner
        self.session_service = session_service

    async def run(
        self,
        *,
        user_id: str,
        session_id: str,
        message: str,
    ) -> str:
        """Run the root agent for one turn and return the final text response."""
        if not _ADK_AVAILABLE or self._runner is None:
            return "ADK not available in this environment"

        response_text = ""
        try:
            new_message = Content(role="user", parts=[Part(text=message)])
            async for event in self._runner.run_async(
                user_id=user_id,
                session_id=session_id,
                new_message=new_message,
            ):
                if hasattr(event, "is_final_response") and event.is_final_response():
                    if event.content and event.content.parts:
                        response_text = event.content.parts[0].text or ""
                    break
        except Exception as exc:
            logger.exception("ADK runner error: %s", exc)
            raise

        return response_text

    async def create_session(
        self,
        user_id: str,
        state: Optional[dict] = None,
        session_id: Optional[str] = None,
    ) -> Any:
        return await self.session_service.create_session(
            app_name=APP_NAME,
            user_id=user_id,
            state=state,
            session_id=session_id,
        )

    async def get_session(self, user_id: str, session_id: str) -> Any:
        return await self.session_service.get_session(
            app_name=APP_NAME,
            user_id=user_id,
            session_id=session_id,
        )


def build_runner(db: AsyncIOMotorDatabase, cfg: object) -> AdkRunner:
    """Build the full agent hierarchy and return an AdkRunner.

    Called once at FastAPI lifespan startup.  All agent tools are closures
    bound to `db`; the cfg object exposes config values.
    """
    http_client = httpx.AsyncClient()

    from app.agents.validation import build_validation_loop
    from app.agents.decomposition import build_decomposition_agent
    from app.agents.feasibility import build_feasibility_workflow
    from app.agents.intake import build_goal_intake_agent
    from app.agents.progress import build_progress_tracking_agent
    from app.agents.overdue import build_overdue_handler_agent
    from app.agents.weekly_memory import build_weekly_memory_writer
    from app.agents.daily_output import build_daily_output_builder
    from app.agents.root import build_root_agent

    validation_loop = build_validation_loop(db, cfg)
    decomposition_agent = build_decomposition_agent(db, cfg)
    feasibility_workflow = build_feasibility_workflow(db, cfg)

    goal_intake_agent = build_goal_intake_agent(
        db, cfg, validation_loop, decomposition_agent, feasibility_workflow
    )
    progress_tracking_agent = build_progress_tracking_agent(db, cfg)
    overdue_handler_agent = build_overdue_handler_agent(db, cfg)
    weekly_memory_writer = build_weekly_memory_writer(db, cfg, http_client)
    daily_output_builder = build_daily_output_builder(db, cfg)

    root_agent = build_root_agent(
        db,
        cfg,
        goal_intake_agent,
        progress_tracking_agent,
        overdue_handler_agent,
        weekly_memory_writer,
        daily_output_builder,
    )

    session_service = MongoSessionService(db)

    if _ADK_AVAILABLE and Runner is not None:
        runner = Runner(
            agent=root_agent,
            app_name=APP_NAME,
            session_service=session_service,
        )
    else:
        runner = None
        logger.warning("google-adk not installed; ADK runner disabled (tests only)")

    return AdkRunner(runner=runner, session_service=session_service)
