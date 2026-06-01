"""POST /v1/events/* — idempotent event handlers (no ADK, no LLM)."""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from pymongo.errors import DuplicateKeyError

from db.client import get_db
from db.collections import Collections
from schemas.goal_domain import EventLogEntry
from schemas.goal_events import (
    EventAck,
    OverdueNotification,
    SubtaskCompletedEvent,
    SubtaskScheduledEvent,
)
from agents.tools.goal_db import get_goal, recompute_progress_percent, set_goal_status
from agents.tools.subtask_db import get_sub_task, mark_sub_task_complete, update_sub_task
from agents.tools.goal_messaging import format_behind_schedule_reminder

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/events", tags=["events"])

EVENT_LOG = Collections.EVENT_LOG


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


async def _insert_event_log(db, entry: EventLogEntry) -> bool:
    """Insert event log entry. Returns False if event_id already exists (duplicate)."""
    try:
        await db[EVENT_LOG].insert_one(entry.model_dump(mode="json"))
        return True
    except DuplicateKeyError:
        return False


async def _update_event_log(db, event_id: str, updates: dict) -> None:
    await db[EVENT_LOG].update_one({"event_id": event_id}, {"$set": updates})


@router.post("/overdue", response_model=EventAck)
async def handle_overdue(body: OverdueNotification) -> EventAck:
    db = get_db()

    entry = EventLogEntry(
        event_id=body.event_id,
        event_type="overdue",
        goal_id=body.overdue_tasks[0].goal_id if body.overdue_tasks else "",
        payload=body.model_dump(mode="json"),
        received_at=_now_utc(),
        status="processing",
        warnings=[],
    )
    inserted = await _insert_event_log(db, entry)
    if not inserted:
        return EventAck(status="already_processed", processed_count=0, warnings=[])

    warnings: list[str] = []
    errors: list[str] = []
    processed = 0

    for task_ref in body.overdue_tasks:
        goal = await get_goal(db, task_ref.goal_id)
        if goal is None:
            errors.append(f"unknown_goal_id: {task_ref.goal_id}")
            warnings.append(f"unknown_goal_id: {task_ref.goal_id}")
            continue

        # Terminal states: ignore silently
        if goal.status in ("COMPLETED", "ABANDONED"):
            continue

        sub_task = await get_sub_task(db, task_ref.goal_id, task_ref.sub_task_id)
        if sub_task is None:
            errors.append(f"unknown_sub_task_id: {task_ref.sub_task_id}")
            warnings.append(f"unknown_sub_task_id: {task_ref.sub_task_id}")
            continue

        # Recompute progress and generate reminder
        await recompute_progress_percent(db, task_ref.goal_id)
        refreshed_goal = await get_goal(db, task_ref.goal_id)
        if refreshed_goal:
            completed = sum(1 for t in refreshed_goal.sub_tasks if t.is_completed)
            total = len(refreshed_goal.sub_tasks)
            reminder = format_behind_schedule_reminder(
                refreshed_goal.title, completed, total, refreshed_goal.deadline
            )
            warnings.append(reminder)
        processed += 1

    # Reminders are informational — only error-type warnings trigger "partial"
    final_status = "partial" if errors else "acknowledged"
    await _update_event_log(db, body.event_id, {
        "status": final_status,
        "processed_at": _now_utc().isoformat(),
        "warnings": warnings,
    })
    return EventAck(status=final_status, processed_count=processed, warnings=warnings)


@router.post("/subtask-scheduled", response_model=EventAck)
async def handle_subtask_scheduled(body: SubtaskScheduledEvent) -> EventAck:
    db = get_db()

    entry = EventLogEntry(
        event_id=body.event_id,
        event_type="subtask_scheduled",
        goal_id=body.goal_id,
        sub_task_id=body.sub_task_id,
        payload=body.model_dump(mode="json"),
        received_at=_now_utc(),
        status="processing",
        warnings=[],
    )
    inserted = await _insert_event_log(db, entry)
    if not inserted:
        return EventAck(status="already_processed", processed_count=0, warnings=[])

    warnings: list[str] = []

    goal = await get_goal(db, body.goal_id)
    if goal is None:
        await _update_event_log(db, body.event_id, {
            "status": "failed",
            "processed_at": _now_utc().isoformat(),
            "warnings": [f"unknown_goal_id: {body.goal_id}"],
        })
        return EventAck(status="partial", processed_count=0, warnings=[f"unknown_goal_id: {body.goal_id}"])

    # Terminal states: ignore
    if goal.status in ("COMPLETED", "ABANDONED"):
        await _update_event_log(db, body.event_id, {
            "status": "processed",
            "processed_at": _now_utc().isoformat(),
        })
        return EventAck(status="acknowledged", processed_count=0, warnings=[])

    planned_date = body.start_time.date().isoformat()
    updated = await update_sub_task(db, body.goal_id, body.sub_task_id, {"planned_date": planned_date})
    if updated is None:
        warnings.append(f"unknown_sub_task_id: {body.sub_task_id}")

    if goal.status == "CREATED":
        await set_goal_status(db, body.goal_id, "IN_PROGRESS")

    final_status = "partial" if warnings else "acknowledged"
    await _update_event_log(db, body.event_id, {
        "status": final_status,
        "processed_at": _now_utc().isoformat(),
        "warnings": warnings,
    })
    return EventAck(status=final_status, processed_count=1, warnings=warnings)


@router.post("/subtask-completed", response_model=EventAck)
async def handle_subtask_completed(body: SubtaskCompletedEvent) -> EventAck:
    db = get_db()

    entry = EventLogEntry(
        event_id=body.event_id,
        event_type="subtask_completed",
        goal_id=body.goal_id,
        sub_task_id=body.sub_task_id,
        payload=body.model_dump(mode="json"),
        received_at=_now_utc(),
        status="processing",
        warnings=[],
    )
    inserted = await _insert_event_log(db, entry)
    if not inserted:
        return EventAck(status="already_processed", processed_count=0, warnings=[])

    goal = await get_goal(db, body.goal_id)
    if goal is None:
        await _update_event_log(db, body.event_id, {
            "status": "failed",
            "processed_at": _now_utc().isoformat(),
            "warnings": [f"unknown_goal_id: {body.goal_id}"],
        })
        return EventAck(status="partial", processed_count=0, warnings=[f"unknown_goal_id: {body.goal_id}"])

    # Terminal states: silently ignore
    if goal.status in ("COMPLETED", "ABANDONED"):
        await _update_event_log(db, body.event_id, {
            "status": "processed",
            "processed_at": _now_utc().isoformat(),
        })
        return EventAck(status="acknowledged", processed_count=0, warnings=[])

    updated = await mark_sub_task_complete(db, body.goal_id, body.sub_task_id, body.completed_at)
    warnings: list[str] = []
    if updated is None:
        warnings.append(f"unknown_sub_task_id: {body.sub_task_id}")

    new_pct = await recompute_progress_percent(db, body.goal_id)

    if new_pct == 100.0:
        await set_goal_status(db, body.goal_id, "COMPLETED")

    final_status = "partial" if warnings else "acknowledged"
    await _update_event_log(db, body.event_id, {
        "status": final_status,
        "processed_at": _now_utc().isoformat(),
        "warnings": warnings,
    })
    return EventAck(status=final_status, processed_count=1, warnings=warnings)
