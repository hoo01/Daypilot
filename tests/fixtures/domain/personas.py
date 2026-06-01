"""Pre-canned user states for integration tests."""
from tests.fixtures.domain.factories import make_goal_input, make_health_output


def new_user(intent: str = "add_goal", raw_message: str = "") -> dict:
    """First-time user. Empty memory_context — falls back to LLM-derived estimates."""
    return make_goal_input(
        intent=intent,
        raw_user_message=raw_message,
        memory_context="",
        health=make_health_output(energy_score=0.7),
        calendar_free_slots=[
            {"start": "2026-05-30T09:00:00Z", "end": "2026-05-30T12:00:00Z", "duration_minutes": 180}
        ],
    )


def experienced_user(intent: str = "add_goal", raw_message: str = "") -> dict:
    """User with history. Coding goals average 25% overrun."""
    return make_goal_input(
        intent=intent,
        raw_user_message=raw_message,
        memory_context=(
            "User typically completes weekly coding goals 25% slower than estimated. "
            "Completion rate for weekly goals: 0.78."
        ),
        health=make_health_output(energy_score=0.75),
        calendar_free_slots=[
            {"start": "2026-05-30T09:00:00Z", "end": "2026-05-30T12:00:00Z", "duration_minutes": 180},
            {"start": "2026-05-31T09:00:00Z", "end": "2026-05-31T11:00:00Z", "duration_minutes": 120},
        ],
    )


def infeasible_user(intent: str = "add_goal", raw_message: str = "") -> dict:
    """High-risk user. Short-deadline goals have a 70% abandonment rate."""
    return make_goal_input(
        intent=intent,
        raw_user_message=raw_message,
        memory_context=(
            "User typically completes Leetcode goals 40% slower than estimated. "
            "Short-deadline goals (<3 days) have 70% abandonment rate."
        ),
        health=make_health_output(energy_score=0.4, cognitive_load=0.7),
        calendar_free_slots=[
            {"start": "2026-05-30T09:00:00Z", "end": "2026-05-30T11:00:00Z", "duration_minutes": 120},
        ],
    )
