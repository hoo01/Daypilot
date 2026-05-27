"""
Health tool — Owner: Vatsal

Implement the body of analyze_health().
The coordinator calls this tool to understand the user's energy state before scheduling.
"""


async def analyze_health(
    user_id: str,
    sleep_duration_hours: float = 7.0,
    sleep_quality: str = "good",
    user_reported_energy: str = "medium",
    previous_workload: str = "moderate",
) -> dict:
    """
    Analyze the user's sleep and energy data.
    Returns energy level, optimal focus window, cognitive load score, and tasks to avoid.
    """
    # TODO (Vatsal): call Gemini here to reason about the health inputs
    # Use: from google import genai; client = genai.Client(api_key=...)
    # Prompt it to return JSON with energy_level, focus_window, cognitive_load_score, avoid_tasks

    # Stub — replace with real implementation
    return {
        "energy_level": "medium",
        "focus_window": "9PM-1AM",
        "cognitive_load_score": 0.65,
        "avoid_tasks": [],
    }
