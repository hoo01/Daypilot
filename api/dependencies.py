from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from agents.coordinator import coordinator

_session_service = InMemorySessionService()

runner = Runner(
    agent=coordinator,
    app_name="daypilot",
    session_service=_session_service,
)


def get_runner() -> Runner:
    return runner
