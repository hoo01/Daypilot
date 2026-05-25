"""
Real-time Adjustment Agent — Owner: Yuqing

Monitors for disruptions (new events, location changes, task overruns, energy updates)
and dynamically replans the current schedule.
"""
import json
from agents.base import BaseAgent
from schemas import RealtimeInput, RealtimeOutput, ScheduleTask
from config import settings


class RealtimeAgent(BaseAgent):
    """Monitors disruptions and dynamically replans the schedule."""

    model_name = settings.realtime_model

    async def run(self, input_data: RealtimeInput) -> RealtimeOutput:
        prompt = f"""
You are a real-time schedule adjustment assistant. The user's day has changed.
Given their current schedule and what changed, produce an updated schedule.

Rules:
- Keep fixed commitments (e.g. classes, meetings) unchanged
- Drop or reschedule optional tasks to fit the new constraints
- Explain what changed in plain language (max 2 sentences)

Respond with valid JSON:
{{
  "what_changed": ["..."],
  "dropped_tasks": ["..."],
  "added_tasks": ["..."],
  "updated_schedule": [ {{ "time": "...", "duration_min": 60, "task": "...", "location": "..." }} ],
  "message": "..."
}}

Current schedule:
{json.dumps([t.model_dump() for t in input_data.current_schedule], indent=2)}

Trigger: {input_data.trigger}
Detail: {input_data.trigger_detail}
"""
        # TODO (Yuqing): uncomment when ready
        # raw = await self._generate(prompt)
        # data = json.loads(raw)
        # return RealtimeOutput(**data)

        # Stub response — replace with real implementation
        return RealtimeOutput(
            what_changed=[input_data.trigger_detail],
            dropped_tasks=[],
            added_tasks=[],
            updated_schedule=input_data.current_schedule,
            message=f"Schedule updated due to: {input_data.trigger_detail}",
        )
