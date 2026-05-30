import logging
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel
from pymongo.errors import DuplicateKeyError

from app.api.deps import get_db, get_runner, verify_bearer
from app.runtime.adk_runner import AdkRunner
from app.schemas.output import GoalsOutput
from app.tools.goal_db import list_active_goals

logger = logging.getLogger(__name__)
router = APIRouter(tags=["scheduled"])


class DailyOutputRequest(BaseModel):
    user_id: Optional[str] = None


class DailyOutputResponse(BaseModel):
    processed_users: int
    goals_output: list[GoalsOutput]
    errors: list[str]


class WeeklyMemoryRequest(BaseModel):
    user_id: Optional[str] = None
    week_start: Optional[str] = None  # ISO date; defaults to most recent Monday


class WeeklyMemoryAck(BaseModel):
    processed_users: int
    skipped_users: int
    errors: list[str]


def _most_recent_monday() -> date:
    today = date.today()
    return today - timedelta(days=today.weekday())


@router.post("/scheduled/daily-output", response_model=DailyOutputResponse)
async def scheduled_daily_output(
    body: DailyOutputRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
    runner: AdkRunner = Depends(get_runner),
    _: None = Depends(verify_bearer),
) -> DailyOutputResponse:
    """Build and persist GoalsOutput for all active users (or a specific user)."""
    from app.agents.daily_output import build_daily_output_builder
    from app.config import get_settings

    cfg = get_settings()
    all_outputs: list[GoalsOutput] = []
    errors: list[str] = []
    processed = 0

    if body.user_id:
        user_ids = [body.user_id]
    else:
        # Collect all distinct user_ids with active goals
        raw = await db["goals"].distinct("user_id", {"status": {"$in": ["CREATED", "IN_PROGRESS", "OVERDUE"]}})
        user_ids = list(raw)

    for uid in user_ids:
        try:
            goals = await list_active_goals(db, uid)
            today = date.today()
            from app.schemas.output import GoalSubTask
            for goal in goals:
                remaining_effort = int(goal.total_effort_minutes * (1 - goal.progress_percent / 100))
                days_to = (goal.deadline - today).days
                urgency = "high" if days_to <= 0 else ("medium" if days_to <= 3 else "low")
                daily_sub_tasks = [
                    GoalSubTask(
                        title=st.title,
                        estimated_minutes=st.estimated_minutes,
                        priority=st.priority,
                        deadline=st.deadline,
                        preferred_time_of_day=st.preferred_time_of_day,
                        can_split=st.can_split,
                    )
                    for st in goal.sub_tasks
                    if not st.is_completed
                ]
                all_outputs.append(GoalsOutput(
                    goal_id=goal.goal_id,
                    urgency=urgency,
                    feasibility_score=goal.feasibility_score,
                    feasibility_note=goal.feasibility_note,
                    total_effort_minutes=remaining_effort,
                    suggested_blocks_count=goal.suggested_blocks_count,
                    suggested_split_ratio=goal.suggested_split_ratio,
                    daily_sub_tasks=daily_sub_tasks,
                ))
            processed += 1
        except Exception as exc:
            logger.exception("daily_output error for user %s: %s", uid, exc)
            errors.append(f"user:{uid} error:{exc}")

    return DailyOutputResponse(processed_users=processed, goals_output=all_outputs, errors=errors)


@router.post("/scheduled/weekly-memory", response_model=WeeklyMemoryAck)
async def scheduled_weekly_memory(
    body: WeeklyMemoryRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
    runner: AdkRunner = Depends(get_runner),
    _: None = Depends(verify_bearer),
) -> WeeklyMemoryAck:
    """Analyze the past week's goal data and write a compressed summary to Memory Agent."""
    from app.db.collections import WEEKLY_MEMORY_WRITES
    import uuid
    from datetime import datetime, timezone

    week_start_date = (
        date.fromisoformat(body.week_start) if body.week_start else _most_recent_monday()
    )
    week_end_date = week_start_date + timedelta(days=6)
    week_start_str = str(week_start_date)
    week_end_str = str(week_end_date)

    if body.user_id:
        user_ids = [body.user_id]
    else:
        raw = await db["goals"].distinct("user_id")
        user_ids = list(raw)

    processed = 0
    skipped = 0
    errors: list[str] = []

    for uid in user_ids:
        # Idempotency check
        existing = await db[WEEKLY_MEMORY_WRITES].find_one(
            {"user_id": uid, "week_start": week_start_str}
        )
        if existing:
            skipped += 1
            continue

        try:
            # Gather goals in the window
            all_statuses = ["COMPLETED", "ABANDONED", "PARTIALLY_COMPLETED", "OVERDUE", "IN_PROGRESS"]
            goals = await list_active_goals(db, uid, statuses=all_statuses)
            window_goals = [
                g for g in goals
                if week_start_str <= str(g.created_at.date()) <= week_end_str
            ]

            if not window_goals:
                # Nothing to analyze — write a placeholder
                summary = f"No goals recorded in week of {week_start_str}."
            else:
                completed = [g for g in window_goals if g.status == "COMPLETED"]
                abandoned = [g for g in window_goals if g.status == "ABANDONED"]
                comp_rate = len(completed) / len(window_goals) if window_goals else 0
                abandon_rate = len(abandoned) / len(window_goals) if window_goals else 0
                summary = (
                    f"Week of {week_start_str}: {len(window_goals)} goals tracked. "
                    f"Completion rate: {comp_rate:.0%}. Abandonment rate: {abandon_rate:.0%}. "
                    f"Weekly goal completion: {sum(1 for g in completed if g.goal_type=='weekly')}/{sum(1 for g in window_goals if g.goal_type=='weekly')}."
                )

            from app.tools.memory_agent import write_weekly_summary
            from app.config import get_settings
            from app.schemas.domain import WeeklyMemoryWrite
            import httpx

            cfg = get_settings()
            now = datetime.now(timezone.utc)
            write_id = str(uuid.uuid4())

            try:
                async with httpx.AsyncClient() as client:
                    await write_weekly_summary(
                        user_id=uid,
                        week_start=week_start_str,
                        summary_text=summary,
                        memory_agent_url=cfg.memory_agent_url,
                        http_client=client,
                    )
                status = "success"
                error = ""
            except Exception as exc:
                status = "failed"
                error = str(exc)
                logger.warning("Memory Agent write failed for user %s: %s", uid, exc)

            record = WeeklyMemoryWrite(
                write_id=write_id,
                user_id=uid,
                week_start=week_start_date,
                week_end=week_end_date,
                summary_text=summary,
                written_at=now,
                status=status,
                error=error,
            )
            try:
                await db[WEEKLY_MEMORY_WRITES].insert_one(record.model_dump(mode="json"))
            except DuplicateKeyError:
                skipped += 1
                continue

            processed += 1

        except Exception as exc:
            logger.exception("weekly_memory error for user %s: %s", uid, exc)
            errors.append(f"user:{uid} error:{exc}")

    return WeeklyMemoryAck(processed_users=processed, skipped_users=skipped, errors=errors)
