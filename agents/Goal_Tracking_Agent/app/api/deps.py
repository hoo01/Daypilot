from fastapi import Depends, Request, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.runtime.adk_runner import AdkRunner

_bearer = HTTPBearer(auto_error=False)


def get_db(request: Request) -> AsyncIOMotorDatabase:
    return request.app.state.db


def get_runner(request: Request) -> AdkRunner:
    return request.app.state.runner


def get_cfg(request: Request):
    return request.app.state.cfg


async def verify_bearer(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> None:
    """Verify the shared Bearer token sent by the Coordinator Agent.

    Token verification is skipped when api_bearer_token is empty (dev mode).
    """
    cfg = request.app.state.cfg
    expected = getattr(cfg, "api_bearer_token", "")
    if not expected:
        return  # dev mode — no auth required
    if credentials is None or credentials.credentials != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
