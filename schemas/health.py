from pydantic import BaseModel


class HealthInput(BaseModel):
    sleep_duration_hours: float
    sleep_quality: str               # "poor" | "fair" | "good" | "excellent"
    user_reported_energy: str        # "low" | "medium" | "high"
    previous_workload: str           # "light" | "moderate" | "heavy"
    wearable_summary: str | None = None


class HealthOutput(BaseModel):
    energy_level: str                # e.g. "low-medium"
    focus_window: str                # e.g. "9PM-1AM"
    cognitive_load_score: float      # 0.0–1.0
    avoid_tasks: list[str]           # e.g. ["back-to-back deep work"]
