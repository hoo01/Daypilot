"""
Schedule Planning Agent — Owner: Jingyuan

Synthesizes all agent outputs into an optimized daily schedule.
Implement the `run` method below. The input/output schemas are fixed.
"""
import json
from agents.base import BaseAgent
from schemas import ScheduleInput, ScheduleOutput, ScheduleStrategy, ScheduleTask
from config import settings


class ScheduleAgent(BaseAgent):
    """Synthesizes agent outputs into optimized daily schedule strategies."""

    model_name = settings.planning_model

    async def run(self, input_data: ScheduleInput) -> ScheduleOutput:
        prompt = f"""
You are an expert daily schedule optimizer. Given the inputs below, generate
2–3 schedule strategies (e.g. "Most Productive", "Most Balanced", "Minimal Effort").

Each strategy is a list of time blocks covering the user's full day.
Respect:
- Fixed calendar_events (cannot be moved)
- health.focus_window and health.avoid_tasks
- goals.suggested_blocks and goals.urgency
- relationship.upcoming_dates (book time for them if needed)
- geo.departure_time (leave buffer before commute)

Respond with valid JSON matching ScheduleOutput schema.

Input:
{input_data.model_dump_json(indent=2)}
"""
        # TODO (Jingyuan): uncomment and implement
        # raw = await self._generate(prompt)
        # data = json.loads(raw)
        # return ScheduleOutput(**data)

        # Stub response — replace with real implementation
        return ScheduleOutput(
            date=input_data.date,
            strategies=[
                ScheduleStrategy(
                    name="Most Productive",
                    tasks=[
                        ScheduleTask(time="9AM", duration_min=90, task="Deep work block", location="home"),
                        ScheduleTask(time="12PM", duration_min=60, task="Lunch break", location="home"),
                        ScheduleTask(time="9PM", duration_min=120, task="Focus session", location="home"),
                    ],
                    summary="Maximizes focus time around your energy peak.",
                )
            ],
            recommended_strategy="Most Productive",
        )
