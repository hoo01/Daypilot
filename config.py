from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    gemini_api_key: str

    # 重推理 agents (dev: gemini-2.5-flash, prod: gemini-3.1-pro-preview)
    coordinator_model: str = "gemini-2.5-flash"
    planning_model: str = "gemini-2.5-flash"
    relationship_model: str = "gemini-2.5-flash"

    # 高速 worker agents (dev: gemini-2.5-flash, prod: gemini-3.5-flash)
    health_model: str = "gemini-2.5-flash"
    goal_model: str = "gemini-2.5-flash"
    realtime_model: str = "gemini-2.5-flash"
    geo_model: str = "gemini-2.5-flash"

    # 数据摄入 (dev: gemini-2.5-flash, prod: gemini-3.1-flash-lite)
    ingestion_model: str = "gemini-2.5-flash"

    mongodb_uri: str
    mongodb_db_name: str = "daypilot"

    google_client_id: str
    google_client_secret: str
    google_redirect_uri: str = "http://localhost:8000/auth/callback"

    app_env: str = "development"
    app_secret_key: str = "change_me_in_production"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
