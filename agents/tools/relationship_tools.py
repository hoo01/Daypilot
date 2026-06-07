import json
import time
from datetime import date
from google import genai
from config import settings
from db import get_db
from agents.memory import MemoryAgent
import http_client as _http_client
from telemetry.instrument import traced_tool

_client = genai.Client(
    api_key=settings.gemini_api_key,
    http_options=genai.types.HttpOptions(httpx_async_client=_http_client.shared_async_client()),
)

_cache: dict[str, tuple[float, dict]] = {}
_CACHE_TTL = 1800  # 30 minutes — upcoming events don't change within a session


def _days_away(date_str: str) -> int:
    try:
        return (date.fromisoformat(date_str) - date.today()).days
    except ValueError:
        return 0


@traced_tool("get_relationship_context")
async def get_relationship_context(user_id: str, lookahead_days: int = 14) -> dict:
    """
    Query the Knowledge Graph for important upcoming dates and people.
    Returns natural-language proactive suggestions for the coordinator to surface.
    """
    cache_key = f"{user_id}:{date.today().isoformat()}"
    now = time.monotonic()
    if cache_key in _cache:
        ts, cached = _cache[cache_key]
        if now - ts < _CACHE_TTL:
            return cached

    mem = MemoryAgent(get_db())
    upcoming = await mem.query_upcoming(user_id, days=lookahead_days)

    if not upcoming:
        return {
            "upcoming_events": [],
            "proactive_suggestions": [],
            "important_people": [],
        }

    events_with_days = [
        {"event": e.event, "date": e.date, "days_away": _days_away(e.date)}
        for e in upcoming
    ]

    prompt = f"""
You are DayPilot, a proactive AI life assistant.
Given the user's upcoming personal events below, generate a short, actionable suggestion for each one.

Today: {date.today().isoformat()}

Upcoming events:
{json.dumps(events_with_days, indent=2)}

Rules:
- Sound natural and warm, not robotic
- State how many days away the event is
- Suggest ONE concrete action the user could take
- End with a brief yes/no question
- Skip events with no obvious action (e.g. generic recurring reminders)

Return a JSON array of strings, one per actionable event.
Example output:
["Your 3-month anniversary with Mia is in 8 days. Want me to block Saturday evening and look up restaurants near campus?",
 "Your favorite artist's tickets drop in 3 days. Want a reminder the moment they go live?"]
"""

    response = await _client.aio.models.generate_content(
        model=settings.relationship_model,
        contents=prompt,
        config=genai.types.GenerateContentConfig(
            response_mime_type="application/json",
            thinking_config=genai.types.ThinkingConfig(thinking_budget=0),
        ),
    )

    try:
        suggestions = json.loads(response.text)
        if not isinstance(suggestions, list):
            suggestions = [str(suggestions)]
    except (json.JSONDecodeError, AttributeError):
        suggestions = [f"{e['event']} in {e['days_away']} days" for e in events_with_days]

    result = {
        "upcoming_events": events_with_days,
        "proactive_suggestions": suggestions,
        "important_people": [],
    }
    _cache[cache_key] = (now, result)
    return result
