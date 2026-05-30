from fastapi import Header, HTTPException, status
from app.config import get_settings


async def verify_bearer(authorization: str = Header(default="")) -> None:
    """Optional Bearer auth — skipped when API_BEARER_TOKEN is empty."""
    cfg = get_settings()
    if not cfg.api_bearer_token:
        return
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or token != cfg.api_bearer_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
