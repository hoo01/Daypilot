from dataclasses import dataclass, field
from typing import Any, Callable

from motor.motor_asyncio import AsyncIOMotorDatabase


@dataclass
class ToolCall:
    fn: Callable
    kwargs: dict = field(default_factory=dict)


@dataclass
class ScenarioScript:
    intent: str
    tool_sequence: list[ToolCall]
    final_response: dict


class StubRunner:
    """
    Drop-in replacement for google.adk.runners.Runner.
    Dispatches by state["input"]["intent"] to a fixed ScenarioScript.
    Tools execute for real against the test MongoDB; only the LLM step is faked.
    """

    def __init__(self, db: AsyncIOMotorDatabase, scripts: dict[str, ScenarioScript]):
        self.db = db
        self.scripts = scripts

    async def run_async(
        self,
        user_id: str,
        session_id: str,
        new_message: Any,
        state: dict,
    ) -> dict:
        intent = state.get("input", {}).get("intent", "")
        script = self.scripts.get(intent)
        if script is None:
            raise ValueError(f"StubRunner: no script registered for intent '{intent}'")
        for tool_call in script.tool_sequence:
            await tool_call.fn(self.db, **tool_call.kwargs)
        return script.final_response
