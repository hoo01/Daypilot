"""
Geo tool — Owner: TBD

Compute commute time via Google Routes API and back-calculate available work windows.
"""


async def get_geo_info(
    origin: str,
    destination: str,
    must_arrive_by: str,
    departure_buffer_min: int = 10,
) -> dict:
    """
    Calculate commute duration and the latest departure time.
    Returns available work window before the user needs to leave.
    """
    # TODO: call Google Routes API to get commute_duration_min
    # departure_time = must_arrive_by - commute_duration_min - departure_buffer_min

    # Stub — replace with real implementation
    return {
        "departure_time": "11:20",
        "arrival_time": "11:50",
        "route": "To be determined",
        "commute_duration_min": 30,
        "available_window_min": 110,
        "recommended_tasks_before_departure": [],
    }
