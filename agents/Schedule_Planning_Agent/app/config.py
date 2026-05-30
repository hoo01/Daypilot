from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

# When running locally from the agents/Schedule_Planning_Agent/ dir, also read
# the monorepo root .env as a fallback so GEMINI_API_KEY doesn't need to be
# duplicated. Local .env (if present) takes precedence.
_here = Path(__file__).resolve().parent.parent          # agents/Schedule_Planning_Agent/
_root_env = _here.parent.parent / ".env"               # monorepo root .env


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=[str(_root_env), ".env"],              # root first, local overrides
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Google / Gemini
    gemini_api_key: str = ""
    planning_model: str = "gemini-2.5-flash"

    # Auth
    api_bearer_token: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
