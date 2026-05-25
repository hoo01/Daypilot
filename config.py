from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    gemini_api_key: str

    # 重推理 agents
    coordinator_model: str = "gemini-3.1-pro-preview"
    planning_model: str = "gemini-3.1-pro-preview"
    relationship_model: str = "gemini-3.1-pro-preview"

    # 高速 worker agents
    health_model: str = "gemini-3.5-flash"
    goal_model: str = "gemini-3.5-flash"
    realtime_model: str = "gemini-3.5-flash"
    geo_model: str = "gemini-3.5-flash"

    # 数据摄入
    ingestion_model: str = "gemini-3.1-flash-lite"

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
