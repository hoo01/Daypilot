from contextlib import asynccontextmanager
from contextlib import AsyncExitStack

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService

from db import close_db, get_db
from db.indexes import ensure_indexes
from api.routes import chat, schedule, auth
from api.routes import events, goals as goals_router, intake, scheduled as scheduled_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    from agents.coordinator import get_mongo_mcp, build_coordinator

    exit_stack = AsyncExitStack()
    await exit_stack.__aenter__()

    try:
        from agents.health_agent.scenario_selector import get_active_scenario, get_target_date
        print(f"[Health] Active scenario: {get_active_scenario()}, target_date={get_target_date()}")
    except Exception as e:
        print(f"[Health] Scenario selector unavailable: {e}")

    db = get_db()
    await ensure_indexes(db)

    try:
        mongo_mcp = get_mongo_mcp()
        await exit_stack.enter_async_context(mongo_mcp)
        coordinator = build_coordinator(mcp_tools=mongo_mcp)
    except Exception:
        coordinator = build_coordinator()

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
    import http_client
    await http_client.close()


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
app.include_router(events.router)
app.include_router(goals_router.router)
app.include_router(intake.router)
app.include_router(scheduled_router.router)


@app.get("/health")
async def health_check():
    return {"status": "ok"}
