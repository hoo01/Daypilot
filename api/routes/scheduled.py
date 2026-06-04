"""POST /v1/scheduled/daily-output, POST /v1/scheduled/weekly-memory — Cloud Scheduler endpoints."""
import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, Request
from pydantic import BaseModel
from pymongo.errors import DuplicateKeyError

from db.client import get_db
from db.collections import Collections
from schemas.goals import GoalsOutput, GoalSubTask
from agents.tools.goal_db import list_active_goals, update_goal, set_goal_status
from agents.tools.subtask_db import update_sub_task
from agents.tools.progress_calc import compute_daily_rate
from agents.tools.memory_agent_client import write_weekly_summary
from config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/scheduled", tags=["scheduled"])

EVENT_LOG = Collections.EVENT_LOG
WEEKLY_MEMORY_WRITES = Collections.WEEKLY_MEMORY_WRITES


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _most_recent_monday(ref: date) -> date:
    return ref - timedelta(days=ref.weekday())


class DailyOutputRequest(BaseModel):
    user_id: Optional[str] = None


class DailyOutputResponse(BaseModel):
    processed_users: int
    goals_output: list[GoalsOutput]
    errors: list[str]


class WeeklyMemoryRequest(BaseModel):
    user_id: Optional[str] = None
    week_start: Optional[date] = None


class WeeklyMemoryAck(BaseModel):
    processed_users: int
    skipped_users: int
    errors: list[str]


def _goal_to_goals_output(goal) -> GoalsOutput:
    """Convert a Goal domain object to GoalsOutput (strips planned_date from sub-tasks)."""
    today = date.today()
    days_left = (goal.deadline - today).days
    if days_left <= 1:
        urgency = "high"
    elif days_left <= 3:
        urgency = "medium"
    else:
        urgency = "low"

    sub_tasks = [
        GoalSubTask(
            title=t.title,
            estimated_minutes=t.estimated_minutes,
            priority=t.priority,
            deadline=t.deadline,
            preferred_time_of_day=t.preferred_time_of_day,
            can_split=t.can_split,
        )
        for t in goal.sub_tasks
        if not t.is_completed
    ]

    return GoalsOutput(
        goal_id=goal.goal_id,
        urgency=urgency,
        feasibility_score=goal.feasibility_score,
        feasibility_note=goal.feasibility_note,
        total_effort_minutes=goal.total_effort_minutes,
        suggested_blocks_count=goal.suggested_blocks_count,
        suggested_split_ratio=goal.suggested_split_ratio,
        daily_sub_tasks=sub_tasks,
        replan_pending=goal.replan_requested_at is not None,
    )


@router.post("/daily-output", response_model=DailyOutputResponse)
async def daily_output(body: DailyOutputRequest, request: Request) -> DailyOutputResponse:
    db = get_db()
    errors: list[str] = []
    all_output: list[GoalsOutput] = []

    if body.user_id:
        user_ids = [body.user_id]
    else:
        # All users with active goals
        pipeline = [
            {"$match": {"status": {"$in": ["CREATED", "IN_PROGRESS", "OVERDUE"]}}},
            {"$group": {"_id": "$user_id"}},
        ]
        user_ids = [doc["_id"] async for doc in db[Collections.GOALS].aggregate(pipeline)]

    processed = 0
    for uid in user_ids:
        try:
            goals = await list_active_goals(db, uid)
            for goal in goals:
                output = _goal_to_goals_output(goal)
                all_output.append(output)
                await db[EVENT_LOG].insert_one({
                    "event_id": str(uuid.uuid4()),
                    "event_type": "daily_output",
                    "goal_id": goal.goal_id,
                    "payload": output.model_dump(mode="json"),
                    "received_at": _now_utc().isoformat(),
                    "processed_at": _now_utc().isoformat(),
                    "status": "processed",
                    "warnings": [],
                })
            processed += 1
        except Exception as exc:
            logger.error("daily_output error for user %s: %s", uid, exc)
            errors.append(f"user {uid}: {exc}")

    return DailyOutputResponse(
        processed_users=processed,
        goals_output=all_output,
        errors=errors,
    )


class EndOfDayRequest(BaseModel):
    user_id: str
    date: Optional[date] = None


class GoalEndOfDayResult(BaseModel):
    goal_id: str
    goal_title: str
    action: str          # "carried_over" | "replan_requested"
    incomplete_count: int


class EndOfDayResponse(BaseModel):
    processed_date: date
    goals_processed: int
    results: list[GoalEndOfDayResult]
    errors: list[str]


@router.post("/end-of-day", response_model=EndOfDayResponse)
async def end_of_day(body: EndOfDayRequest) -> EndOfDayResponse:
    target_date = body.date or date.today()
    tomorrow = target_date + timedelta(days=1)
    db = get_db()
    results = []
    errors = []

    goals = await list_active_goals(db, body.user_id)
    for goal in goals:
        incomplete = [t for t in goal.sub_tasks
                      if not t.is_completed and not t.abandoned
                      and t.planned_date == target_date]
        if not incomplete:
            continue

        try:
            daily_rate = await compute_daily_rate(db, goal.goal_id)
            remaining_effort = sum(t.estimated_minutes for t in goal.sub_tasks
                                   if not t.is_completed and not t.abandoned)
            remaining_days = max((goal.deadline - target_date).days, 1)
            daily_rate_needed = remaining_effort / remaining_days

            needs_replan = (
                (daily_rate > 0 and daily_rate_needed > daily_rate * 1.5)
                or (remaining_days <= 3 and goal.progress_percent < 70)
            )

            if needs_replan:
                await update_goal(db, goal.goal_id,
                                  {"replan_requested_at": _now_utc().isoformat()})
                await set_goal_status(db, goal.goal_id, "OVERDUE")
                action = "replan_requested"
            else:
                for t in incomplete:
                    await update_sub_task(db, goal.goal_id, t.sub_task_id,
                                          {"planned_date": tomorrow.isoformat()})
                action = "carried_over"

            results.append(GoalEndOfDayResult(
                goal_id=goal.goal_id,
                goal_title=goal.title,
                action=action,
                incomplete_count=len(incomplete),
            ))
        except Exception as exc:
            logger.error("end_of_day error for goal %s: %s", goal.goal_id, exc)
            errors.append(f"goal {goal.goal_id}: {exc}")

    return EndOfDayResponse(
        processed_date=target_date,
        goals_processed=len(results),
        results=results,
        errors=errors,
    )


@router.post("/weekly-memory", response_model=WeeklyMemoryAck)
async def weekly_memory(body: WeeklyMemoryRequest, request: Request) -> WeeklyMemoryAck:
    db = get_db()
    errors: list[str] = []
    processed = 0
    skipped = 0

    if body.user_id:
        user_ids = [body.user_id]
    else:
        pipeline = [{"$group": {"_id": "$user_id"}}]
        user_ids = [doc["_id"] async for doc in db[Collections.GOALS].aggregate(pipeline)]

    week_start = body.week_start or _most_recent_monday(date.today())
    week_end = week_start + timedelta(days=6)

    async with httpx.AsyncClient(timeout=30.0) as http_client:
        for uid in user_ids:
            write_id = str(uuid.uuid4())
            record = {
                "write_id": write_id,
                "user_id": uid,
                "week_start": week_start.isoformat(),
                "week_end": week_end.isoformat(),
                "summary_text": "",
                "written_at": _now_utc().isoformat(),
                "status": "failed",
                "error": "",
            }
            try:
                await db[WEEKLY_MEMORY_WRITES].insert_one({**record})
            except DuplicateKeyError:
                skipped += 1
                continue

            try:
                goals = await list_active_goals(db, uid, statuses=["COMPLETED", "ABANDONED", "IN_PROGRESS"])
                completed = [g for g in goals if g.status == "COMPLETED"]
                abandoned = [g for g in goals if g.status == "ABANDONED"]
                summary = (
                    f"Week {week_start}: completed {len(completed)} goals, "
                    f"abandoned {len(abandoned)} goals out of {len(goals)} total. "
                    f"Goal titles: {', '.join(g.title for g in goals[:5])}."
                )

                await write_weekly_summary(
                    user_id=uid,
                    week_start=week_start.isoformat(),
                    summary_text=summary[:500],
                    memory_agent_url=settings.memory_agent_url,
                    http_client=http_client,
                )

                await db[WEEKLY_MEMORY_WRITES].update_one(
                    {"write_id": write_id},
                    {"$set": {"status": "success", "summary_text": summary[:500]}},
                )
                processed += 1
            except Exception as exc:
                logger.error("weekly_memory error for user %s: %s", uid, exc)
                await db[WEEKLY_MEMORY_WRITES].update_one(
                    {"write_id": write_id},
                    {"$set": {"status": "failed", "error": str(exc)}},
                )
                errors.append(f"user {uid}: {exc}")

    return WeeklyMemoryAck(
        processed_users=processed,
        skipped_users=skipped,
        errors=errors,
    )
