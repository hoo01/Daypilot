from typing import Optional
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    gemini_api_key: str
    gemini_api_version: str = "v1"

    coordinator_model: str = "gemini-2.5-flash"
    planning_model: str = "gemini-2.5-flash"
    relationship_model: str = "gemini-2.5-flash-lite"

    health_model: str = "gemini-2.5-flash"
    goal_model: str = "gemini-2.5-flash"
    goal_reasoning_model: str = "gemini-2.5-flash"
    goal_fast_model: str = "gemini-2.5-flash"
    realtime_model: str = "gemini-2.5-flash"
    geo_model: str = "gemini-2.5-flash"
    google_maps_api_key: str = ""

    ingestion_model: str = "gemini-2.5-flash"

    # Health-agent (previously in agents/health_agent/config.py)
    node4_model: str = "gemini-2.5-flash"
    memory_backend: str = "jsonl"   # "jsonl" | "bigquery"

    mongodb_uri: str
    mongodb_db_name: str = "daypilot"

    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/auth/callback"

    app_env: str = "development"
    app_secret_key: str = "change_me_in_production"

    memory_agent_url: str = "http://memory-agent"
    calendar_service_account_json: Optional[str] = None
    overload_threshold_minutes: int = 600
    intake_session_ttl_hours: int = 24

    https_proxy: str = ""
    frontend_url: str = "http://localhost:5173"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
