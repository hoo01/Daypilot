"""
Geo Agent

Computes commute time and back-calculates available work windows.
Uses Google Routes API.
"""
from agents.base import BaseAgent
from schemas import GeoInput, GeoOutput
from config import settings


class GeoAgent(BaseAgent):
    """Bridges time and space — commute-aware schedule planning."""

    model_name = settings.geo_model

    async def run(self, input_data: GeoInput) -> GeoOutput:
        # TODO: call Google Routes API to get commute_duration_min
        # commute_min = await self._get_commute(input_data.origin, input_data.destination)

        # Parse must_arrive_by → compute departure_time and available_window_min
        # departure_str = subtract (commute_min + input_data.departure_buffer_min) from must_arrive_by

        # Stub response — replace with real implementation
        return GeoOutput(
            departure_time="11:20",
            arrival_time="11:50",
            route="To be determined",
            commute_duration_min=30,
            available_window_min=110,
            recommended_tasks_before_departure=[],
        )

    async def _get_commute(self, origin: str, destination: str) -> int:
        """Returns commute duration in minutes via Google Routes API."""
        # TODO: implement Google Routes API call
        raise NotImplementedError
