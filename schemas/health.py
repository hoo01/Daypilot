from pydantic import BaseModel


class HealthInput(BaseModel):
    """Legacy input model — not used by the pipeline path."""
    sleep_duration_hours: float
    sleep_quality: str
    user_reported_energy: str
    previous_workload: str
    wearable_summary: str | None = None


class HealthOutput(BaseModel):
    energy_score: str          # "low" | "medium" | "high"
    focus_windows: list[str]   # primary first; e.g. ["9PM-1AM"]
    cognitive_load: float      # 0.0–1.0  (PSI / 100)
