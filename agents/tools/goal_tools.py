"""
Goal tool — Owner: Astrid

Implement the body of track_goals().
The coordinator calls this to understand how far behind the user is on weekly goals.
"""
from db import get_db
from agents.memory import MemoryAgent


async def track_goals(user_id: str) -> dict:
    """
    Retrieve current goal state and assess progress.
    Returns goal status, urgency, and suggested time blocks to catch up.
    """
    mem = MemoryAgent(get_db())
    goal_state = await mem.get_goal_state(user_id)

    # TODO (Astrid): use Gemini to reason over goal_state + current date
    # and produce urgency / suggested_blocks

    # Stub — replace with real implementation
    return {
        "goal_status": "on_track",
        "progress_percent": 60.0,
        "urgency": "medium",
        "goals": goal_state.get("goals", []),
        "suggested_blocks": [],
    }
