from abc import ABC, abstractmethod
from typing import Any
from google import genai
from google.genai.types import HttpOptions, GenerateContentConfig, ThinkingConfig
from config import settings
import http_client

_client = genai.Client(
    api_key=settings.gemini_api_key,
    http_options=HttpOptions(
        api_version=settings.gemini_api_version,
        httpx_async_client=http_client.shared_async_client(),
    ),
)

_NO_THINKING = GenerateContentConfig(thinking_config=ThinkingConfig(thinking_budget=0))


class BaseAgent(ABC):
    """All agents inherit from here. Override model_name if needed."""

    model_name: str = settings.realtime_model

    async def _generate(self, prompt: str) -> str:
        response = await _client.aio.models.generate_content(
            model=self.model_name,
            contents=prompt,
            config=_NO_THINKING,
        )
        return response.text

    @abstractmethod
    async def run(self, input_data: Any) -> Any:
        """Execute the agent. Subclasses must implement this."""
        ...
