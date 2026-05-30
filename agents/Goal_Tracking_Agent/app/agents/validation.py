"""Validation loop: LoopAgent wrapping goal_validator LlmAgent."""

from pathlib import Path
from motor.motor_asyncio import AsyncIOMotorDatabase

try:
    from google.adk.agents import LlmAgent, LoopAgent  # type: ignore[import]
except ImportError:
    LlmAgent = None  # type: ignore[assignment,misc]
    LoopAgent = None  # type: ignore[assignment,misc]


def _load_prompt(name: str) -> str:
    return (Path(__file__).parent.parent / "prompts" / f"{name}.md").read_text()


def build_validation_loop(db: AsyncIOMotorDatabase, cfg: object) -> object:
    """Build the validation_loop (LoopAgent wrapping goal_validator).

    The goal_validator checks all three dimensions (quantifiable, time-bound,
    appropriate granularity) against state["intake.draft"].  It writes
    state["validation.passed"] and state["validation.failures"] then escalates
    when done.  No user I/O occurs mid-loop.
    """
    goal_validator = LlmAgent(
        name="goal_validator",
        model="gemini-2.5-flash",
        instruction=_load_prompt("validation"),
        output_key="validation.passed",
    )

    validation_loop = LoopAgent(
        name="validation_loop",
        sub_agents=[goal_validator],
        max_iterations=5,
    )
    return validation_loop
