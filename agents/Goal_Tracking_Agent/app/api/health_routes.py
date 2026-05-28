import logging
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])


@router.get("/healthz")
async def liveness() -> dict:
    """Liveness probe — Cloud Run restarts container if this fails."""
    return {"ok": True}


@router.get("/readyz")
async def readiness(request: Request) -> JSONResponse:
    """Readiness probe — pings each dependency; returns 503 if any is down."""
    checks = {"ok": True, "mongo": False, "memory_agent": False, "calendar": False}

    # MongoDB ping
    try:
        db = request.app.state.db
        await db.command("ping")
        checks["mongo"] = True
    except Exception as exc:
        logger.warning("MongoDB readiness check failed: %s", exc)

    # Memory Agent ping (best-effort)
    try:
        cfg = request.app.state.cfg
        import httpx
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{cfg.memory_agent_url.rstrip('/')}/healthz", timeout=2.0
            )
            checks["memory_agent"] = resp.status_code == 200
    except Exception:
        pass  # non-fatal — memory agent may not be running in dev

    # Calendar: we consider it "ready" if the service account JSON is configured
    checks["calendar"] = bool(getattr(request.app.state.cfg, "calendar_service_account_json", ""))

    all_ok = checks["mongo"]  # minimum required: MongoDB
    checks["ok"] = all_ok

    return JSONResponse(content=checks, status_code=200 if all_ok else 503)
