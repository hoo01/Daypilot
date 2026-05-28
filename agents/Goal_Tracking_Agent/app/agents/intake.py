"""Goal intake agent: multi-turn conversation for goal creation."""

from pathlib import Path
from motor.motor_asyncio import AsyncIOMotorDatabase

try:
    from google.adk.agents import LlmAgent  # type: ignore[import]
except ImportError:
    LlmAgent = None  # type: ignore[assignment,misc]

from app.tools.goal_db import create_goal, get_goal
from app.tools.subtask_db import bulk_set_sub_tasks
from app.tools.intake_session_db import (
    start_intake_session,
    resume_intake_session,
    append_intake_turn,
    save_intake_draft,
    complete_intake_session,
)


def _load_prompt(name: str) -> str:
    return (Path(__file__).parent.parent / "prompts" / f"{name}.md").read_text()


def build_goal_intake_agent(
    db: AsyncIOMotorDatabase,
    cfg: object,
    validation_loop: object,
    decomposition_agent: object,
    feasibility_workflow: object,
) -> object:
    """Build the goal_intake_agent with all tool closures bound to db."""

    # ── tool closures ─────────────────────────────────────────────────────────

    async def tool_start_intake_session(user_id: str) -> dict:
        """Start a new intake session for the given user."""
        session = await start_intake_session(db, user_id)
        return session.model_dump(mode="json")

    async def tool_resume_intake_session(session_id: str) -> dict | None:
        """Resume an existing open intake session."""
        session = await resume_intake_session(db, session_id)
        return session.model_dump(mode="json") if session else None

    async def tool_append_intake_turn(session_id: str, role: str, content: str) -> None:
        """Append a conversation turn to the session history."""
        from datetime import datetime, timezone
        from app.schemas.intake import IntakeTurn
        turn = IntakeTurn(role=role, content=content, timestamp=datetime.now(timezone.utc))
        await append_intake_turn(db, session_id, turn)

    async def tool_save_intake_draft(session_id: str, draft: dict, stage: str) -> None:
        """Persist the current goal draft and stage to the session."""
        await save_intake_draft(db, session_id, draft, stage)

    async def tool_create_goal(
        goal_id: str,
        user_id: str,
        title: str,
        goal_type: str,
        status: str,
        deadline: str,
        feasibility_score: float,
        feasibility_note: str,
        total_effort_minutes: int,
        suggested_blocks_count: int,
        suggested_split_ratio: list,
    ) -> dict:
        """Create a new goal in the database."""
        from datetime import datetime, timezone, date as date_type
        from app.schemas.domain import Goal
        goal = Goal(
            goal_id=goal_id,
            user_id=user_id,
            title=title,
            goal_type=goal_type,
            status=status,
            created_at=datetime.now(timezone.utc),
            deadline=date_type.fromisoformat(deadline),
            progress_percent=0.0,
            sub_tasks=[],
            feasibility_score=feasibility_score,
            feasibility_note=feasibility_note,
            total_effort_minutes=total_effort_minutes,
            suggested_blocks_count=suggested_blocks_count,
            suggested_split_ratio=suggested_split_ratio,
        )
        result = await create_goal(db, goal)
        return result.model_dump(mode="json")

    async def tool_bulk_set_sub_tasks(goal_id: str, sub_tasks: list) -> dict:
        """Replace the sub-tasks array for a goal."""
        from app.schemas.domain import SubTask
        parsed = [SubTask(**t) for t in sub_tasks]
        result = await bulk_set_sub_tasks(db, goal_id, parsed)
        return result.model_dump(mode="json")

    async def tool_complete_intake_session(session_id: str, goal_id: str) -> None:
        """Mark the intake session as completed with the resulting goal_id."""
        await complete_intake_session(db, session_id, goal_id)

    return LlmAgent(
        name="goal_intake_agent",
        model="gemini-2.5-flash",
        instruction=_load_prompt("intake"),
        tools=[
            tool_start_intake_session,
            tool_resume_intake_session,
            tool_append_intake_turn,
            tool_save_intake_draft,
            tool_create_goal,
            tool_bulk_set_sub_tasks,
            tool_complete_intake_session,
        ],
        sub_agents=[validation_loop, decomposition_agent, feasibility_workflow],
    )
