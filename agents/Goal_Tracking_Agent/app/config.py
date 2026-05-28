from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # MongoDB
    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db_name: str = "goal_tracking"

    # Google / Gemini
    gemini_api_key: str = ""
    gcp_project: str = ""

    # Downstream services
    memory_agent_url: str = "http://localhost:8001"
    calendar_service_account_json: str = ""   # path or JSON content

    # Feasibility thresholds
    overload_threshold_minutes: int = 600     # 10 hours

    # Auth
    api_bearer_token: str = ""               # shared secret from Coordinator


@lru_cache
def get_settings() -> Settings:
    return Settings()
