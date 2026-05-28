"""Weekly memory writer: SequentialAgent(memory_analyzer, memory_writer)."""

from pathlib import Path
from motor.motor_asyncio import AsyncIOMotorDatabase

try:
    from google.adk.agents import LlmAgent, SequentialAgent  # type: ignore[import]
except ImportError:
    LlmAgent = None        # type: ignore[assignment,misc]
    SequentialAgent = None  # type: ignore[assignment,misc]

import httpx

from app.tools.goal_db import list_active_goals
from app.tools.memory_agent import write_weekly_summary


def _load_prompt(name: str) -> str:
    return (Path(__file__).parent.parent / "prompts" / f"{name}.md").read_text()


def build_weekly_memory_writer(
    db: AsyncIOMotorDatabase,
    cfg: object,
    http_client: httpx.AsyncClient,
) -> object:
    """Build the weekly_memory_writer SequentialAgent."""

    async def tool_list_all_goals_in_window(
        user_id: str, week_start: str, week_end: str
    ) -> list:
        """List goals created in the given week window (for memory analysis)."""
        from datetime import date
        all_goals = await list_active_goals(
            db, user_id, statuses=["COMPLETED", "ABANDONED", "PARTIALLY_COMPLETED"]
        )
        return [
            g.model_dump(mode="json") for g in all_goals
            if week_start <= str(g.created_at.date()) <= week_end
        ]

    async def tool_write_weekly_summary(
        user_id: str,
        week_start: str,
        summary_text: str,
    ) -> dict:
        """Write the compressed summary to the Memory Agent and persist an audit record."""
        import uuid
        from datetime import datetime, timezone, date as date_type
        from app.db.collections import WEEKLY_MEMORY_WRITES
        from app.schemas.domain import WeeklyMemoryWrite

        week_start_date = date_type.fromisoformat(week_start)
        from datetime import timedelta
        week_end_date = week_start_date + timedelta(days=6)
        write_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        try:
            await write_weekly_summary(
                user_id=user_id,
                week_start=week_start,
                summary_text=summary_text,
                memory_agent_url=getattr(cfg, "memory_agent_url", ""),
                http_client=http_client,
            )
            record = WeeklyMemoryWrite(
                write_id=write_id,
                user_id=user_id,
                week_start=week_start_date,
                week_end=week_end_date,
                summary_text=summary_text,
                written_at=now,
                status="success",
                error="",
            )
        except Exception as exc:
            record = WeeklyMemoryWrite(
                write_id=write_id,
                user_id=user_id,
                week_start=week_start_date,
                week_end=week_end_date,
                summary_text=summary_text,
                written_at=now,
                status="failed",
                error=str(exc),
            )

        await db[WEEKLY_MEMORY_WRITES].insert_one(record.model_dump(mode="json"))
        return record.model_dump(mode="json")

    memory_analyzer = LlmAgent(
        name="memory_analyzer",
        model="gemini-2.5-pro-preview",
        instruction=_load_prompt("weekly_memory"),
        tools=[tool_list_all_goals_in_window],
        output_key="weekly.analysis",
    )

    memory_writer = LlmAgent(
        name="memory_writer",
        model="gemini-2.5-flash",
        instruction=_load_prompt("weekly_memory"),
        tools=[tool_write_weekly_summary],
        output_key="weekly.write_result",
    )

    return SequentialAgent(
        name="weekly_memory_writer",
        sub_agents=[memory_analyzer, memory_writer],
    )
