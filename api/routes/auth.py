import asyncio
from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials

from db import get_db
from db.collections import Collections
from agents.ingestion import IngestionAgent, SCOPES
from agents.memory import MemoryAgent
from config import settings

router = APIRouter(prefix="/auth", tags=["auth"])

# Store flows between authorization and callback to preserve code_verifier
_pending_flows: dict[str, Flow] = {}


def _build_flow() -> Flow:
    return Flow.from_client_config(
        {
            "web": {
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uris": [settings.google_redirect_uri],
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        },
        scopes=SCOPES,
        redirect_uri=settings.google_redirect_uri,
    )


@router.get("/google")
async def initiate_google_auth(user_id: str):
    """Return the Google OAuth URL. Frontend should redirect the user there."""
    flow = _build_flow()
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        state=user_id,
        prompt="consent",
    )
    _pending_flows[user_id] = flow
    return {"auth_url": auth_url}


@router.get("/callback")
async def google_auth_callback(code: str, state: str):
    """Handle OAuth callback. Exchanges code, stores credentials, then redirects to the frontend."""
    user_id = state

    flow = _pending_flows.pop(user_id, None) or _build_flow()
    try:
        flow.fetch_token(code=code)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Token exchange failed: {e}")

    creds: Credentials = flow.credentials
    creds_dict = {
        "access_token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes or []),
    }

    db = get_db()
    await db[Collections.USER_CREDENTIALS].update_one(
        {"user_id": user_id},
        {"$set": {"user_id": user_id, "credentials": creds_dict}},
        upsert=True,
    )

    # Run ingestion in background — don't block the redirect
    asyncio.create_task(
        IngestionAgent(MemoryAgent(db)).run({
            "user_id": user_id,
            "credentials": creds_dict,
            "source": "cold_start",
        })
    )

    return RedirectResponse(url=f"{settings.frontend_url}/today?user_id={user_id}")


@router.post("/ingest/{user_id}")
async def trigger_ingestion(user_id: str):
    """Re-run ingestion for a user using stored credentials."""
    db = get_db()
    doc = await db[Collections.USER_CREDENTIALS].find_one({"user_id": user_id})
    if not doc:
        raise HTTPException(status_code=404, detail="No credentials found for this user. Complete OAuth first.")

    agent = IngestionAgent(MemoryAgent(db))
    result = await agent.run({
        "user_id": user_id,
        "credentials": doc["credentials"],
        "source": "incremental",
    })
    return result
