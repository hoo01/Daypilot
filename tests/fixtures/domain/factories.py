"""
Cross-agent reusable domain factories.
IMPORT RULE: only import from schemas.* and stdlib — never from agents.*, db.*, or runtime libs.
"""
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from schemas.goal_domain import Goal, SubTask
from schemas.goal_events import (
    OverdueNotification,
    OverdueTaskRef,
    SubtaskCompletedEvent,
    SubtaskScheduledEvent,
)
from schemas.goals import GoalSubTask, GoalsOutput


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _today_plus(days: int) -> date:
    return date.today() + timedelta(days=days)


def make_health_output(
    energy_score: float = 0.75,
    focus_windows: Optional[list[dict]] = None,
    cognitive_load: float = 0.3,
) -> dict:
    return {
        "energy_score": energy_score,
        "focus_windows": focus_windows or [],
        "cognitive_load": cognitive_load,
    }


def make_goal_input(
    user_id: str = "u_test",
    intent: str = "add_goal",
    raw_user_message: str = "I want to solve 5 Leetcode problems by next Friday.",
    health: Optional[dict] = None,
    memory_context: str = "",
    calendar_free_slots: Optional[list[dict]] = None,
    session_id: Optional[str] = None,
) -> dict:
    payload: dict = {
        "user_id": user_id,
        "intent": intent,
        "raw_user_message": raw_user_message,
        "health": health or make_health_output(),
        "memory_context": memory_context,
        "calendar_free_slots": calendar_free_slots or [],
    }
    if session_id is not None:
        payload["session_id"] = session_id
    return payload


def make_subtask(
    sub_task_id: str = "t1",
    goal_id: str = "g_test",
    title: str = "Task 1",
    estimated_minutes: int = 30,
    priority: str = "medium",
    deadline: Optional[date] = None,
    preferred_time_of_day: str = "flexible",
    can_split: bool = True,
    is_completed: bool = False,
    completed_at: Optional[datetime] = None,
    planned_date: Optional[date] = None,
    abandoned: bool = False,
) -> SubTask:
    return SubTask(
        sub_task_id=sub_task_id,
        goal_id=goal_id,
        title=title,
        estimated_minutes=estimated_minutes,
        priority=priority,
        deadline=deadline or _today_plus(7),
        preferred_time_of_day=preferred_time_of_day,
        can_split=can_split,
        is_completed=is_completed,
        completed_at=completed_at,
        planned_date=planned_date,
        abandoned=abandoned,
    )


def make_goal(
    goal_id: str = "g_test",
    user_id: str = "u_test",
    title: str = "Solve 5 Leetcode problems",
    goal_type: str = "weekly",
    status: str = "CREATED",
    deadline: Optional[date] = None,
    sub_tasks: Optional[list[SubTask]] = None,
    feasibility_score: float = 0.85,
    feasibility_note: str = "",
    total_effort_minutes: int = 150,
    suggested_blocks_count: int = 2,
    suggested_split_ratio: Optional[list[float]] = None,
    progress_percent: float = 0.0,
    replan_requested_at: Optional[datetime] = None,
) -> Goal:
    return Goal(
        goal_id=goal_id,
        user_id=user_id,
        title=title,
        goal_type=goal_type,
        status=status,
        created_at=_now_utc(),
        deadline=deadline or _today_plus(7),
        progress_percent=progress_percent,
        sub_tasks=sub_tasks or [],
        feasibility_score=feasibility_score,
        feasibility_note=feasibility_note,
        total_effort_minutes=total_effort_minutes,
        suggested_blocks_count=suggested_blocks_count,
        suggested_split_ratio=suggested_split_ratio or [0.5, 0.5],
        replan_requested_at=replan_requested_at,
    )


def make_goals_output(
    goal_id: str = "g_test",
    urgency: str = "medium",
    feasibility_score: float = 0.85,
    feasibility_note: str = "",
    total_effort_minutes: int = 150,
    suggested_blocks_count: int = 2,
    suggested_split_ratio: Optional[list[float]] = None,
    daily_sub_tasks: Optional[list[GoalSubTask]] = None,
) -> GoalsOutput:
    return GoalsOutput(
        goal_id=goal_id,
        urgency=urgency,
        feasibility_score=feasibility_score,
        feasibility_note=feasibility_note,
        total_effort_minutes=total_effort_minutes,
        suggested_blocks_count=suggested_blocks_count,
        suggested_split_ratio=suggested_split_ratio or [0.5, 0.5],
        daily_sub_tasks=daily_sub_tasks or [],
    )


def make_overdue_event(
    event_id: str = "evt_test",
    goal_id: str = "g_test",
    sub_task_ids: Optional[list[str]] = None,
    start_time: Optional[datetime] = None,
) -> dict:
    tasks = sub_task_ids or ["t1"]
    st = (start_time or _now_utc()).isoformat()
    return OverdueNotification(
        event_id=event_id,
        overdue_tasks=[
            OverdueTaskRef(sub_task_id=sid, goal_id=goal_id, start_time=start_time or _now_utc())
            for sid in tasks
        ],
    ).model_dump(mode="json")


def make_subtask_scheduled_event(
    event_id: str = "evt_test",
    sub_task_id: str = "t1",
    goal_id: str = "g_test",
    start_time: Optional[datetime] = None,
) -> dict:
    return SubtaskScheduledEvent(
        event_id=event_id,
        sub_task_id=sub_task_id,
        goal_id=goal_id,
        start_time=start_time or _now_utc(),
    ).model_dump(mode="json")


def make_subtask_completed_event(
    event_id: str = "evt_test",
    sub_task_id: str = "t1",
    goal_id: str = "g_test",
    completed_at: Optional[datetime] = None,
) -> dict:
    return SubtaskCompletedEvent(
        event_id=event_id,
        sub_task_id=sub_task_id,
        goal_id=goal_id,
        completed_at=completed_at or _now_utc(),
    ).model_dump(mode="json")
