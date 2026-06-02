import httpx
from config import settings


async def track_goals(user_id: str) -> dict:
    """
    Retrieve current goal state by calling the daily-output scheduled endpoint.
    Returns goal status, urgency, and replan_pending flag.
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            f"{settings.goal_agent_url}/v1/scheduled/daily-output",
            json={"user_id": user_id},
        )
        response.raise_for_status()
        data = response.json()  # DailyOutputResponse: {processed_users, goals_output, errors}

    goals_output = data.get("goals_output", [])
    if not goals_output:
        return {
            "goal_status": "no_goals",
            "progress_percent": 0.0,
            "urgency": "low",
            "goals": [],
            "replan_pending": False,
        }

    # Derive aggregate status for the Coordinator
    urgencies = [g["urgency"] for g in goals_output]
    top_urgency = "high" if "high" in urgencies else ("medium" if "medium" in urgencies else "low")
    avg_feasibility = sum(g["feasibility_score"] for g in goals_output) / len(goals_output)
    replan_pending = any(g.get("replan_pending", False) for g in goals_output)

    return {
        "goal_status": "on_track" if avg_feasibility >= 0.6 else "at_risk",
        "progress_percent": round(avg_feasibility * 100, 1),
        "urgency": top_urgency,
        "goals": goals_output,
        "replan_pending": replan_pending,
    }
