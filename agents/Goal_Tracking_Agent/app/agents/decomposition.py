"""Decomposition agent: one-shot structured sub-task generation."""

from pathlib import Path
from motor.motor_asyncio import AsyncIOMotorDatabase

try:
    from google.adk.agents import LlmAgent  # type: ignore[import]
except ImportError:
    LlmAgent = None  # type: ignore[assignment,misc]


def _load_prompt(name: str) -> str:
    return (Path(__file__).parent.parent / "prompts" / f"{name}.md").read_text()


def build_decomposition_agent(db: AsyncIOMotorDatabase, cfg: object) -> object:
    """Build the decomposition_agent.

    Single-turn structured-output call.  Gemini returns list[SubTask] as JSON.
    Writes the array to state["decomposition.sub_tasks"].
    """
    return LlmAgent(
        name="decomposition_agent",
        model="gemini-2.5-pro-preview",
        instruction=_load_prompt("decomposition"),
        output_key="decomposition.sub_tasks",
    )
