from pathlib import Path

from google.adk.agents import LlmAgent, LoopAgent


_PROMPT = (Path(__file__).parent / "prompts" / "validation.md").read_text(encoding="utf-8")


def build_validation_loop(model: str) -> LoopAgent:
    goal_validator = LlmAgent(
        name="goal_validator",
        model=model,
        description="Checks goal draft against three validation dimensions; sets validation.passed.",
        instruction=_PROMPT,
    )
    return LoopAgent(
        name="validation_loop",
        description="Validates goal dimensions (quantifiable, time-bound, granularity); sets state['validation.passed'].",
        sub_agents=[goal_validator],
        max_iterations=5,
    )
