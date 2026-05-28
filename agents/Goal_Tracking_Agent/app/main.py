import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings
from app.db.client import get_motor_client, get_database, close_motor_client
from app.db.indexes import ensure_indexes
from app.runtime.adk_runner import build_runner
from app.runtime.errors import register_exception_handlers
from app.api import (
    health_routes,
    intake_routes,
    event_routes,
    goal_routes,
    scheduled_routes,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = get_settings()
    client = get_motor_client(cfg.mongo_uri)
    db = get_database(client, cfg.mongo_db_name)
    await ensure_indexes(db)
    app.state.db = db
    app.state.runner = build_runner(db, cfg)
    app.state.cfg = cfg
    logger.info("Goal Tracking Agent started (db=%s)", cfg.mongo_db_name)
    yield
    await close_motor_client()
    logger.info("Goal Tracking Agent stopped")


def create_app() -> FastAPI:
    app = FastAPI(
        title="DayPilot Goal Tracking Agent",
        description="Manages the full lifecycle of user goals within the DayPilot system.",
        version="0.2.0",
        lifespan=lifespan,
    )
    register_exception_handlers(app)
    app.include_router(health_routes.router)
    app.include_router(intake_routes.router, prefix="/v1")
    app.include_router(event_routes.router, prefix="/v1")
    app.include_router(goal_routes.router, prefix="/v1")
    app.include_router(scheduled_routes.router, prefix="/v1")
    return app


app = create_app()
