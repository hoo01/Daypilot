from datetime import datetime, timedelta, timezone

from motor.motor_asyncio import AsyncIOMotorDatabase

from schemas.goal_domain import SubTask


def compute_progress_percent(sub_tasks: list[SubTask]) -> float:
    """Equal-weight completion: completed / total * 100. Returns 0.0 if no sub-tasks.

    Abandoned subtasks are excluded from both numerator and denominator.
    """
    active = [t for t in sub_tasks if not t.abandoned]
    if not active:
        return 0.0
    completed = sum(1 for t in active if t.is_completed)
    return round(completed / len(active) * 100, 2)


async def compute_daily_rate(
    db: AsyncIOMotorDatabase,
    goal_id: str,
    window_days: int = 7,
) -> float:
    """Returns average completed effort (minutes/day) over the last window_days days.

    Uses completed_at timestamps on sub_tasks — no event_log query needed.
    Returns 0.0 if no completions exist yet or goal not found.
    """
    from agents.tools.goal_db import get_goal  # local import to avoid circular dependency

    goal = await get_goal(db, goal_id)
    if not goal:
        return 0.0

    days_since_created = (datetime.now(timezone.utc).date() - goal.created_at.date()).days
    N = max(min(days_since_created, window_days), 1)
    cutoff = datetime.now(timezone.utc) - timedelta(days=N)

    completed_minutes = sum(
        t.estimated_minutes
        for t in goal.sub_tasks
        if t.is_completed
        and not t.abandoned
        and t.completed_at is not None
        and t.completed_at >= cutoff
    )
    return completed_minutes / N
