"""
agents/schedule.py — MIGRATED

ScheduleAgent has been extracted to agents/Schedule_Planning_Agent/ and is now
served as an independent HTTP microservice.

  Local:      uvicorn app.main:app --port 8002
              POST http://localhost:8002/schedule/generate

  See:        agents/Schedule_Planning_Agent/docs/user_manual.md

Importing ScheduleAgent directly from this module is no longer supported.
"""
import warnings

warnings.warn(
    "agents.schedule.ScheduleAgent has moved to agents/Schedule_Planning_Agent. "
    "Call it via HTTP: POST /schedule/generate. "
    "See agents/Schedule_Planning_Agent/docs/user_manual.md.",
    DeprecationWarning,
    stacklevel=2,
)
