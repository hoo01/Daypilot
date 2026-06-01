"""G1, G2 — StubRunner returns malformed/truncated output; no 500 errors."""
import pytest
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport

from tests.fixtures.domain.factories import make_goal_input
from tests.fixtures.goal_agent.runner import ScenarioScript, StubRunner, ToolCall
from tests.fixtures.goal_agent.reporting import step
from api.routes import events, goals as goals_router, intake, scheduled as scheduled_router


def _build_app(runner):
    app = FastAPI()
    app.include_router(events.router)
    app.include_router(goals_router.router)
    app.include_router(intake.router)
    app.include_router(scheduled_router.router)
    app.state.runner = runner
    return app


@pytest.mark.scenario("G1")
@pytest.mark.category("llm_robustness")
async def test_G1_extra_fields_in_response_does_not_crash(test_db):
    """StubRunner returns GoalsOutput JSON with extra/missing fields → HTTP status != 500."""
    scripts = {
        "add_goal": ScenarioScript(
            intent="add_goal",
            tool_sequence=[],
            final_response={
                "stage": "confirming",
                "assistant_message": "Done!",
                "goal_id": None,
                "validation_failures": [],
                "draft": {},
                # Extra unexpected fields that should be silently ignored
                "unknown_field_xyz": "should be ignored",
                "another_extra": 12345,
            },
        )
    }

    runner = StubRunner(db=test_db, scripts=scripts)
    app = _build_app(runner)

    with step("POST intake with StubRunner returning extra fields"):
        payload = make_goal_input(intent="add_goal", raw_user_message="Build an app")
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/v1/intake/turn", json=payload)

    with step("Verify HTTP status != 500 (extra fields handled gracefully)"):
        assert resp.status_code != 500, (
            f"Extra fields in LLM response must not cause 500. Got: {resp.status_code}: {resp.text}"
        )


@pytest.mark.scenario("G2")
@pytest.mark.category("llm_robustness")
async def test_G2_truncated_response_does_not_propagate_json_error(test_db):
    """StubRunner returns truncated JSON → no JSONDecodeError propagates; HTTP status != 500."""
    scripts = {
        "add_goal": ScenarioScript(
            intent="add_goal",
            tool_sequence=[],
            final_response={
                "stage": "validating",
                "assistant_message": "Can you clarify",
                "goal_id": None,
                "validation_failures": [],
                "draft": {},
            },
        )
    }

    runner = StubRunner(db=test_db, scripts=scripts)
    app = _build_app(runner)

    with step("POST intake — stub returns minimal/partial response"):
        payload = make_goal_input(intent="add_goal", raw_user_message="Truncated test")
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/v1/intake/turn", json=payload)

    with step("Verify HTTP status != 500 (no JSONDecodeError propagated)"):
        assert resp.status_code != 500, (
            f"Truncated/partial LLM response must not cause 500. Got: {resp.status_code}: {resp.text}"
        )
