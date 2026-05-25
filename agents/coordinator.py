"""
Coordinator Agent

Orchestrator. The only agent that talks directly to the user.
Uses ReAct (Reason + Act) pattern: evaluates context, selects agents, merges results.
"""
import json
from agents.base import BaseAgent
from agents.memory import MemoryAgent
from agents.health import HealthAgent
from agents.goals import GoalsAgent
from agents.relationship import RelationshipAgent
from agents.schedule import ScheduleAgent
from agents.geo import GeoAgent
from agents.realtime import RealtimeAgent
from schemas import (
    CoordinatorInput, CoordinatorOutput,
    HealthInput, GoalsInput, RelationshipInput, ScheduleInput,
)
from config import settings


class CoordinatorAgent(BaseAgent):
    """Orchestrates all agents and is the sole interface to the user."""

    model_name = settings.coordinator_model

    def __init__(
        self,
        memory: MemoryAgent,
        health: HealthAgent,
        goals: GoalsAgent,
        relationship: RelationshipAgent,
        schedule: ScheduleAgent,
        geo: GeoAgent,
        realtime: RealtimeAgent,
    ):
        self.memory = memory
        self.health = health
        self.goals = goals
        self.relationship = relationship
        self.schedule = schedule
        self.geo = geo
        self.realtime = realtime

    async def run(self, input_data: CoordinatorInput) -> CoordinatorOutput:
        user_id = input_data.user_id

        # Step 1: extract any entities from user message and persist
        await self._extract_and_persist(user_id, input_data.message)

        # Step 2: gather context from all agents in parallel
        # (in production, use asyncio.gather for true parallelism)
        prefs = await self.memory.get_preferences(user_id)

        health_output = await self.health.run(HealthInput(
            sleep_duration_hours=prefs.get("sleep_duration_hours", 7.0),
            sleep_quality=prefs.get("sleep_quality", "good"),
            user_reported_energy=prefs.get("user_reported_energy", "medium"),
            previous_workload=prefs.get("previous_workload", "moderate"),
        ))

        goals_output = await self.goals.run(GoalsInput(user_id=user_id))

        relationship_output = await self.relationship.run(
            RelationshipInput(user_id=user_id)
        )

        # Step 3: build schedule
        from datetime import date
        schedule_output = await self.schedule.run(ScheduleInput(
            user_id=user_id,
            date=date.today().isoformat(),
            health=health_output,
            goals=goals_output,
            relationship=relationship_output,
        ))

        # Step 4: compose reply
        reply = await self._compose_reply(
            input_data.message, schedule_output, relationship_output
        )

        return CoordinatorOutput(
            reply=reply,
            schedule=schedule_output,
            relationship_alerts=relationship_output,
            actions_taken=[],
        )

    async def _extract_and_persist(self, user_id: str, message: str) -> None:
        """Extract entities from user message and write to Knowledge Graph."""
        # TODO: implement entity extraction via Gemini + memory.write_entity
        pass

    async def _compose_reply(self, message: str, schedule, relationship) -> str:
        """Generate the final user-facing reply."""
        suggestions = "\n".join(
            f"- {s}" for s in relationship.proactive_suggestions
        )
        best = schedule.strategies[0] if schedule.strategies else None
        tasks_str = ""
        if best:
            tasks_str = "\n".join(
                f"  {t.time} ({t.duration_min}min): {t.task}" for t in best.tasks
            )

        return (
            f"{suggestions}\n\nHere's your recommended schedule for today:\n{tasks_str}"
        ).strip()
