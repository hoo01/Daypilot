import json
from google import genai
from config import settings
import http_client as _http_client
from telemetry.instrument import traced_tool

_client = genai.Client(
    api_key=settings.gemini_api_key,
    http_options=genai.types.HttpOptions(httpx_async_client=_http_client.shared_async_client()),
)


@traced_tool("get_today_schedule")
async def get_today_schedule(user_id: str, date: str = "") -> dict:
    """
    Retrieve the user's currently active/confirmed schedule for today.
    Returns the task list and strategy name. Call this BEFORE adjust_schedule
    to get the current_schedule argument.
    """
    from services.day_plan_repository import DayPlanRepository
    from services.day_plan_service import today_for

    if not date:
        date = today_for(user_id)
    try:
        plan = await DayPlanRepository().get(user_id, date)
        if plan.active is None:
            return {"found": False, "tasks": [], "strategy_name": None, "date": date}
        return {
            "found": True,
            "tasks": [t.model_dump() for t in plan.active.tasks],
            "strategy_name": plan.active.strategy_name,
            "confirmed": True,
            "date": date,
        }
    except Exception as e:
        return {"found": False, "tasks": [], "strategy_name": None, "date": date, "error": str(e)}


@traced_tool("adjust_schedule")
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
    from schemas.day_plan import DayPlanError
    from schemas.realtime import RealtimeOutput
    from services.day_plan_service import DayPlanService, today_for

    service = DayPlanService()
    date = today_for(user_id)
    plan = await service.get(user_id, date)
    if plan.active is not None:
        # The DB active plan is the source of truth, not whatever the LLM passed in.
        current_schedule = [t.model_dump() for t in plan.active.tasks]
    result = await _run_adjust_llm(current_schedule, trigger, trigger_detail)
    if plan.active is not None and result.get("updated_schedule"):
        try:
            await service.propose_adjustment(user_id, date, RealtimeOutput(**result))
        except DayPlanError as e:
            result["error"] = True
            result["message"] = f"I couldn't produce a valid adjustment ({e.message}). Please try again."
        except Exception as e:  # malformed LLM output that doesn't fit RealtimeOutput
            result["error"] = True
            result["message"] = f"I couldn't produce a valid adjustment ({e}). Please try again."
    return result


async def _run_adjust_llm(current_schedule: list, trigger: str, trigger_detail: str) -> dict:
    """The raw LLM adjustment call (no persistence)."""
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

    response = await _client.aio.models.generate_content(
        model=settings.realtime_model,
        contents=prompt,
        config=genai.types.GenerateContentConfig(
            response_mime_type="application/json",
            thinking_config=genai.types.ThinkingConfig(thinking_budget=0),
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
