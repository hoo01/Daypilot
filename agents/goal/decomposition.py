from pathlib import Path

from google.adk.agents import LlmAgent

from schemas.goal_domain import SubTask

_PROMPT = (Path(__file__).parent / "prompts" / "decomposition.md").read_text(encoding="utf-8")


def build_decomposition_agent(model: str) -> LlmAgent:
    return LlmAgent(
        name="decomposition_agent",
        model=model,
        description="One-shot structured output: decomposes a validated goal into a list of SubTask objects.",
        instruction=_PROMPT,
        output_schema=list[SubTask],
    )
