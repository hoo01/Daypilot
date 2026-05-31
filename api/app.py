from contextlib import asynccontextmanager
from contextlib import AsyncExitStack

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService

from db import close_db
from api.routes import chat, schedule, auth


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Pre-warm MCP at startup so requests don't wait for npx subprocess
    from agents.coordinator import get_mongo_mcp, build_coordinator

    exit_stack = AsyncExitStack()
    await exit_stack.__aenter__()

    try:
        mongo_mcp = get_mongo_mcp()
        await exit_stack.enter_async_context(mongo_mcp)
        coordinator = build_coordinator(mcp_tools=mongo_mcp)
    except Exception:
        # If MCP fails to start, run without it
        from agents.coordinator import coordinator as default_coordinator
        coordinator = default_coordinator

    session_service = InMemorySessionService()
    runner = Runner(
        agent=coordinator,
        app_name="daypilot",
        session_service=session_service,
    )
    app.state.runner = runner

    yield

    await exit_stack.aclose()
    await close_db()


app = FastAPI(title="DayPilot", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat.router)
app.include_router(schedule.router)
app.include_router(auth.router)


@app.get("/health")
async def health_check():
    return {"status": "ok"}
