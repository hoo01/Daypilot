from abc import ABC, abstractmethod
from typing import Any
from google import genai
from google.genai.types import HttpOptions
from config import settings

_client = genai.Client(
    api_key=settings.gemini_api_key,
    http_options=HttpOptions(api_version="v1"),
)


class BaseAgent(ABC):
    """All agents inherit from here. Override model_name if needed."""

    model_name: str = settings.realtime_model  # default: 高速 flash

    async def _generate(self, prompt: str) -> str:
        response = _client.models.generate_content(
            model=self.model_name,
            contents=prompt,
        )
        return response.text

    @abstractmethod
    async def run(self, input_data: Any) -> Any:
        """Execute the agent. Subclasses must implement this."""
        ...
