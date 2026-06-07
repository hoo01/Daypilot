import json
from datetime import date
from google import genai
from config import settings
from db import get_db
from agents.memory import MemoryAgent
import http_client as _http_client

_client = genai.Client(
    api_key=settings.gemini_api_key,
    http_options=genai.types.HttpOptions(httpx_async_client=_http_client.shared_async_client()),
)


async def track_goals(user_id: str) -> dict:
    """
    Retrieve current goal state and assess progress using Gemini.
    Returns goal status, urgency, and suggested time blocks to catch up.
    """
    mem = MemoryAgent(get_db())
    goal_state = await mem.get_goal_state(user_id)
    prefs = await mem.get_preferences(user_id)

    if not goal_state or not goal_state.get("goals"):
        return {
            "goal_status": "no_goals",
            "progress_percent": 0.0,
            "urgency": "low",
            "goals": [],
            "suggested_blocks": [],
        }

    prompt = f"""You are a goal tracking assistant. Analyze the user's current goal progress and return actionable insights.

Today: {date.today().isoformat()}
User focus window: {prefs.get("focus_window", "unknown")}
User energy pattern: {prefs.get("energy_pattern", "unknown")}

Goal state:
{json.dumps(goal_state.get("goals", []), indent=2)}

Return a JSON object with:
- goal_status: "on_track" | "behind_schedule" | "at_risk" | "completed"
- progress_percent: number 0-100 (average across all goals)
- urgency: "low" | "medium" | "high" | "critical"
- goals: the original goals array with updated urgency per goal
- suggested_blocks: list of strings like "2h Leetcode tonight 9PM-11PM"
- summary: one sentence describing the overall goal situation

Return ONLY valid JSON."""

    response = await _client.aio.models.generate_content(
        model=settings.goal_model,
        contents=prompt,
        config=genai.types.GenerateContentConfig(
            response_mime_type="application/json",
            thinking_config=genai.types.ThinkingConfig(thinking_budget=0),
        ),
    )

    try:
        result = json.loads(response.text)
    except (json.JSONDecodeError, ValueError):
        goals = goal_state.get("goals", [])
        return {
            "goal_status": "on_track",
            "progress_percent": 60.0,
            "urgency": "medium",
            "goals": goals,
            "suggested_blocks": [],
            "summary": "Goal tracking data loaded.",
        }

    return result
