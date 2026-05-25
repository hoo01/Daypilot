"""
Health & Energy Agent — Owner: Vatsal

Analyzes sleep, energy, and cognitive readiness to inform schedule planning.
Implement the `run` method below. The input/output schemas are fixed.
"""
import json
from agents.base import BaseAgent
from schemas import HealthInput, HealthOutput
from config import settings


class HealthAgent(BaseAgent):
    """Analyzes energy, sleep, and cognitive readiness."""

    model_name = settings.health_model

    async def run(self, input_data: HealthInput) -> HealthOutput:
        prompt = f"""
You are a health and productivity analyst. Based on the user's health data below,
determine their energy level, optimal focus window, cognitive load score (0.0–1.0),
and tasks they should avoid.

Respond with valid JSON matching this schema:
{{
  "energy_level": "low|low-medium|medium|high",
  "focus_window": "e.g. 9PM-1AM",
  "cognitive_load_score": 0.72,
  "avoid_tasks": ["list of task types to avoid"]
}}

Health data:
{input_data.model_dump_json(indent=2)}
"""
        # TODO (Vatsal): uncomment and refine the prompt, then parse the response
        # raw = await self._generate(prompt)
        # data = json.loads(raw)
        # return HealthOutput(**data)

        # Stub response — replace with real implementation
        return HealthOutput(
            energy_level="medium",
            focus_window="9PM-1AM",
            cognitive_load_score=0.65,
            avoid_tasks=[],
        )
