"""
Relationship & Context Agent

The "knows your life" engine. Surfaces people and dates that create implicit tasks.
"""
import json
from agents.base import BaseAgent
from agents.memory import MemoryAgent
from schemas import RelationshipInput, RelationshipOutput, UpcomingDate
from config import settings

class RelationshipAgent(BaseAgent):
    """Surfaces important people, upcoming dates, and proactive suggestions."""

    model_name = settings.relationship_model

    def __init__(self, memory: MemoryAgent):
        self.memory = memory

    async def run(self, input_data: RelationshipInput) -> RelationshipOutput:
        upcoming_events = await self.memory.query_upcoming(
            input_data.user_id, days=input_data.lookahead_days
        )

        # TODO: enrich with Gmail metadata and conversation history
        # TODO: call Gemini to generate proactive_suggestions based on upcoming_events

        upcoming_dates = [
            UpcomingDate(event=e.event, date=e.date, days_away=0)
            for e in upcoming_events
        ]

        return RelationshipOutput(
            important_people=[],
            upcoming_dates=upcoming_dates,
            proactive_suggestions=[
                f"{ud.event} in {ud.days_away} days" for ud in upcoming_dates
            ],
            social_priority_score=0.0,
        )
