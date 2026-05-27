import json
from google import genai
from config import settings


async def adjust_schedule(
    user_id: str,
    current_schedule: list,
    trigger: str,
    trigger_detail: str,
) -> dict:
    """
    Dynamically replan the schedule when a disruption occurs.
    trigger: "new_event" | "location_change" | "task_overrun" | "energy_update"
    Returns updated schedule and a plain-language explanation of what changed.
    """
    if not current_schedule:
        return {
            "what_changed": [trigger_detail],
            "dropped_tasks": [],
            "added_tasks": [],
            "updated_schedule": [],
            "message": "No active schedule to adjust.",
        }

    prompt = f"""
You are DayPilot's real-time schedule adjustment engine.
The user's day has changed. Replan their schedule accordingly.

Rules:
- Keep tasks with type "calendar_event" — they are fixed and cannot be moved
- Tasks with type "deep_work", "break", "meal" can be rescheduled or dropped
- Preserve task_id values from the original schedule
- All times must remain in ISO 8601 format (e.g. "2026-05-25T21:00:00")
- Keep the total number of tasks reasonable — drop lower-priority ones if time is tight
- Write a short, friendly message (1-2 sentences) explaining what changed

Trigger type: {trigger}
What happened: {trigger_detail}

Current schedule:
{json.dumps(current_schedule, indent=2)}

Return valid JSON with this exact structure:
{{
  "what_changed": ["<one-line description>"],
  "dropped_tasks": ["<task title>", ...],
  "added_tasks": ["<task title>", ...],
  "updated_schedule": [ <same structure as input tasks> ],
  "message": "<friendly explanation for the user>"
}}
"""

    client = genai.Client(api_key=settings.gemini_api_key)
    response = client.models.generate_content(
        model=settings.realtime_model,
        contents=prompt,
        config=genai.types.GenerateContentConfig(
            response_mime_type="application/json",
        ),
    )

    try:
        result = json.loads(response.text)
        # Validate required keys are present
        result.setdefault("what_changed", [trigger_detail])
        result.setdefault("dropped_tasks", [])
        result.setdefault("added_tasks", [])
        result.setdefault("updated_schedule", current_schedule)
        result.setdefault("message", trigger_detail)
        return result
    except (json.JSONDecodeError, AttributeError):
        return {
            "what_changed": [trigger_detail],
            "dropped_tasks": [],
            "added_tasks": [],
            "updated_schedule": current_schedule,
            "message": f"Schedule updated due to: {trigger_detail}",
        }
