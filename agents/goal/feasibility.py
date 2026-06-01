from pathlib import Path

from google.adk.agents import LlmAgent, ParallelAgent, SequentialAgent

_TIME_PROMPT = (Path(__file__).parent / "prompts" / "feasibility_time.md").read_text()
_HABIT_PROMPT = (Path(__file__).parent / "prompts" / "feasibility_habit.md").read_text()
_LOAD_PROMPT = (Path(__file__).parent / "prompts" / "feasibility_load.md").read_text()
_SYNTHESIS_PROMPT = (Path(__file__).parent / "prompts" / "feasibility_synthesis.md").read_text()


def build_feasibility_workflow(
    fast_model: str,
    standard_model: str,
    reasoning_model: str,
) -> SequentialAgent:
    time_agent = LlmAgent(
        name="time_feasibility_agent",
        model=fast_model,
        description="Layer 1: checks calendar time availability; writes feasibility.time.",
        instruction=_TIME_PROMPT,
    )
    habit_agent = LlmAgent(
        name="habit_feasibility_agent",
        model=standard_model,
        description="Layer 2: adjusts effort using behavioral history; writes feasibility.habit.",
        instruction=_HABIT_PROMPT,
    )
    load_agent = LlmAgent(
        name="load_feasibility_agent",
        model=fast_model,
        description="Layer 3: checks active workload vs overload threshold; writes feasibility.load.",
        instruction=_LOAD_PROMPT,
    )
    synthesis_agent = LlmAgent(
        name="feasibility_synthesis_agent",
        model=reasoning_model,
        description="Synthesizes all three layer results into feasibility_score + 3-option proposal.",
        instruction=_SYNTHESIS_PROMPT,
    )

    feasibility_parallel = ParallelAgent(
        name="feasibility_parallel",
        sub_agents=[time_agent, habit_agent, load_agent],
    )
    return SequentialAgent(
        name="feasibility_workflow",
        sub_agents=[feasibility_parallel, synthesis_agent],
    )
