"""
api/app.py — FastAPI application factory for the Health Agent microservice.

Follows the same factory pattern as the root monolith's api/app.py.
"""

from __future__ import annotations

from fastapi import FastAPI

from api.routes.health import router


def create_app() -> FastAPI:
    app = FastAPI(
        title="Health Agent",
        description="PsychoBio pipeline microservice — psychobiological strain analysis.",
        version="1.0.0",
    )
    app.include_router(router)
    return app


app = create_app()
