import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo.errors import DuplicateKeyError

from app.api.deps import get_db, verify_bearer
from app.db.collections import EVENT_LOG
from app.schemas.events import (
    OverdueNotification,
    SubtaskScheduledEvent,
    SubtaskCompletedEvent,
    EventAck,
)
from app.tools.goal_db import set_goal_status, recompute_progress_percent, get_goal
from app.tools.subtask_db import get_sub_task, mark_sub_task_complete, update_sub_task
from app.tools.messaging import format_behind_schedule_reminder

logger = logging.getLogger(__name__)
router = APIRouter(tags=["events"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _write_event_log(
    db: AsyncIOMotorDatabase,
    event_id: str,
    event_type: str,
    goal_id: str,
    sub_task_id: str | None,
    payload: dict,
    status: str,
    warnings: list[str],
) -> None:
    doc = {
        "event_id": event_id,
        "event_type": event_type,
        "goal_id": goal_id,
        "sub_task_id": sub_task_id,
        "payload": payload,
        "received_at": _now().isoformat(),
        "processed_at": _now().isoformat(),
        "status": status,
        "warnings": warnings,
    }
    try:
        await db[EVENT_LOG].insert_one(doc)
    except DuplicateKeyError:
        pass  # idempotent — event already recorded


@router.post("/events/overdue", response_model=EventAck)
async def handle_overdue(
    body: OverdueNotification,
    db: AsyncIOMotorDatabase = Depends(get_db),
    _: None = Depends(verify_bearer),
) -> EventAck:
    """Handle overdue sub-task notifications from the Schedule Planning Agent."""
    # Idempotency check
    existing = await db[EVENT_LOG].find_one({"event_id": body.event_id})
    if existing and existing.get("status") not in ("processing",):
        return EventAck(
            status="already_processed",
            processed_count=existing.get("processed_count", 0),
            warnings=existing.get("warnings", []),
        )

    # Write initial processing record
    payload = body.model_dump(mode="json")
    await _write_event_log(
        db, body.event_id, "overdue",
        goal_id=body.overdue_tasks[0].goal_id if body.overdue_tasks else "",
        sub_task_id=None,
        payload=payload,
        status="processing",
        warnings=[],
    )

    processed_count = 0
    warnings: list[str] = []

    for ref in body.overdue_tasks:
        sub_task = await get_sub_task(db, ref.goal_id, ref.sub_task_id)
        if sub_task is None:
            warn = f"unknown_sub_task_id: {ref.sub_task_id}"
            warnings.append(warn)
            logger.warning("Overdue notification references unknown sub_task_id=%s goal_id=%s", ref.sub_task_id, ref.goal_id)
            continue

        # Recompute progress
        try:
            await recompute_progress_percent(db, ref.goal_id)
        except ValueError:
            warnings.append(f"goal_not_found: {ref.goal_id}")
            continue

        goal = await get_goal(db, ref.goal_id)
        if goal is None:
            warnings.append(f"goal_not_found: {ref.goal_id}")
            continue

        from datetime import date
        today = date.today()
        if goal.deadline < today and goal.progress_percent == 0.0:
            await set_goal_status(db, ref.goal_id, "OVERDUE")
        elif goal.deadline < today and goal.progress_percent < 100.0:
            completed = sum(1 for t in goal.sub_tasks if t.is_completed)
            reminder = format_behind_schedule_reminder(
                goal_title=goal.title,
                completed_count=completed,
                total_count=len(goal.sub_tasks),
                deadline=goal.deadline,
            )
            warnings.append(f"reminder:{reminder}")

        processed_count += 1

    final_status = "acknowledged" if not warnings else ("partial" if processed_count > 0 else "partial")

    # Update event_log with final status
    await db[EVENT_LOG].update_one(
        {"event_id": body.event_id},
        {"$set": {"status": final_status, "warnings": warnings, "processed_at": _now().isoformat()}},
    )

    return EventAck(status=final_status, processed_count=processed_count, warnings=warnings)


@router.post("/events/subtask-scheduled", response_model=EventAck)
async def handle_subtask_scheduled(
    body: SubtaskScheduledEvent,
    db: AsyncIOMotorDatabase = Depends(get_db),
    _: None = Depends(verify_bearer),
) -> EventAck:
    """Handle subtask-scheduled notification: set planned_date, transition CREATED→IN_PROGRESS."""
    existing = await db[EVENT_LOG].find_one({"event_id": body.event_id})
    if existing and existing.get("status") == "processed":
        return EventAck(status="already_processed", processed_count=1, warnings=[])

    warnings: list[str] = []
    planned_date_str = body.start_time.date().isoformat()

    sub_task = await update_sub_task(
        db, body.goal_id, body.sub_task_id, {"planned_date": planned_date_str}
    )
    if sub_task is None:
        warnings.append(f"unknown_sub_task_id: {body.sub_task_id}")

    # Transition CREATED → IN_PROGRESS if goal was still in CREATED status
    goal = await get_goal(db, body.goal_id)
    if goal and goal.status == "CREATED":
        await set_goal_status(db, body.goal_id, "IN_PROGRESS")

    await _write_event_log(
        db, body.event_id, "subtask_scheduled",
        goal_id=body.goal_id,
        sub_task_id=body.sub_task_id,
        payload=body.model_dump(mode="json"),
        status="partial" if warnings else "processed",
        warnings=warnings,
    )

    return EventAck(
        status="partial" if warnings else "acknowledged",
        processed_count=0 if warnings else 1,
        warnings=warnings,
    )


@router.post("/events/subtask-completed", response_model=EventAck)
async def handle_subtask_completed(
    body: SubtaskCompletedEvent,
    db: AsyncIOMotorDatabase = Depends(get_db),
    _: None = Depends(verify_bearer),
) -> EventAck:
    """Handle subtask-completed: mark done, recompute progress, check for COMPLETED goal."""
    existing = await db[EVENT_LOG].find_one({"event_id": body.event_id})
    if existing and existing.get("status") == "processed":
        return EventAck(status="already_processed", processed_count=1, warnings=[])

    warnings: list[str] = []

    sub_task = await mark_sub_task_complete(db, body.goal_id, body.sub_task_id, body.completed_at)
    if sub_task is None:
        warnings.append(f"unknown_sub_task_id: {body.sub_task_id}")

    try:
        new_pct = await recompute_progress_percent(db, body.goal_id)
        if new_pct >= 100.0:
            await set_goal_status(db, body.goal_id, "COMPLETED")
    except ValueError as exc:
        warnings.append(str(exc))

    await _write_event_log(
        db, body.event_id, "subtask_completed",
        goal_id=body.goal_id,
        sub_task_id=body.sub_task_id,
        payload=body.model_dump(mode="json"),
        status="partial" if warnings else "processed",
        warnings=warnings,
    )

    return EventAck(
        status="partial" if warnings else "acknowledged",
        processed_count=0 if warnings else 1,
        warnings=warnings,
    )
