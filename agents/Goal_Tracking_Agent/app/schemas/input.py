from pydantic import BaseModel


class FocusWindow(BaseModel):
    start: str   # ISO datetime string
    end: str     # ISO datetime string


class HealthOutput(BaseModel):
    energy_score: float        # 0.0 – 1.0
    focus_windows: list[FocusWindow]
    cognitive_load: float      # 0.0 – 1.0


class GoalAgentInput(BaseModel):
    """Structured input assembled by the Coordinator Agent before activating
    the Goal Tracking Agent.  The Goal Agent never reads raw user chat directly.
    """

    user_id: str
    intent: str                          # routing key — see Architecture §3 intent table
    raw_user_message: str
    health: HealthOutput
    memory_context: str                  # compressed behavioral history; "" for new users
    calendar_free_slots: list[dict]      # pre-fetched available windows for feasibility Layer 1
