from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from db import close_db
from api.routes import chat, schedule

app = FastAPI(title="DayPilot", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat.router)
app.include_router(schedule.router)


@app.on_event("shutdown")
async def shutdown():
    await close_db()


@app.get("/health")
async def health_check():
    return {"status": "ok"}
