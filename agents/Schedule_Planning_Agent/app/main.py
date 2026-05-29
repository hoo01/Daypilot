import logging
from fastapi import FastAPI
from app.api import health_routes, schedule_routes

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")


def create_app() -> FastAPI:
    app = FastAPI(
        title="DayPilot Schedule Planning Agent",
        description="Synthesizes all agent outputs into an optimized daily schedule.",
        version="0.1.0",
    )
    app.include_router(health_routes.router)
    app.include_router(schedule_routes.router)
    return app


app = create_app()
