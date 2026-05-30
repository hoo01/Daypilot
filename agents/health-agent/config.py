"""
config.py — Pydantic settings for the Health Agent microservice.

Aligns with the root monolith's config.py pattern (pydantic_settings.BaseSettings).
All values are loaded from .env automatically; override via environment variables.
"""

from pydantic_settings import BaseSettings


class HealthAgentSettings(BaseSettings):
    # Gemini / Google AI
    gemini_api_key: str
    node4_model: str = "gemini-2.5-flash"
    google_cloud_project: str = ""
    google_cloud_location: str = "us-central1"

    # Memory backend: "jsonl" (local) | "bigquery" (production)
    memory_backend: str = "jsonl"

    # HTTP server
    host: str = "0.0.0.0"
    port: int = 8001

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"   # tolerate legacy vars (e.g. ADK_MEMORY_BACKEND)


settings = HealthAgentSettings()
