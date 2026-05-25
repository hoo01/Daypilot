"""
Goal Tracking Agent — Owner: Astrid

Tracks weekly goals, deadlines, and progress. Suggests time blocks.
Implement the `run` method below. The input/output schemas are fixed.
"""
import json
from agents.base import BaseAgent
from agents.memory import MemoryAgent
from schemas import GoalsInput, GoalsOutput, GoalItem
from config import settings


class GoalsAgent(BaseAgent):
    """Tracks weekly goals, deadlines, and progress."""

    model_name = settings.goal_model

    def __init__(self, memory: MemoryAgent):
        self.memory = memory

    async def run(self, input_data: GoalsInput) -> GoalsOutput:
        # TODO (Astrid): load goal_state from memory, call Gemini to assess
        # goal_state = await self.memory.get_goal_state(input_data.user_id)
        #
        # prompt = f"""
        # You are a goal tracking assistant. Given the user's current goals and
        # available calendar windows, assess progress and suggest time blocks.
        # ...
        # """
        # raw = await self._generate(prompt)
        # data = json.loads(raw)
        # return GoalsOutput(**data)

        # Stub response — replace with real implementation
        return GoalsOutput(
            goal_status="on_track",
            progress_percent=60.0,
            urgency="medium",
            goals=[],
            suggested_blocks=[],
        )
