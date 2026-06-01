from pathlib import Path

from google.adk.agents import LlmAgent, LoopAgent


_PROMPT = (Path(__file__).parent / "prompts" / "validation.md").read_text()


def build_validation_loop(model: str) -> LoopAgent:
    goal_validator = LlmAgent(
        name="goal_validator",
        model=model,
        description="Checks goal draft against three validation dimensions; sets validation.passed.",
        instruction=_PROMPT,
    )
    return LoopAgent(
        name="validation_loop",
        sub_agents=[goal_validator],
        max_iterations=5,
    )
