"""N1, N2, N3 — normal intake flows via StubRunner."""
import pytest
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI

from agents.tools.goal_db import create_goal
from tests.fixtures.domain.factories import (
    make_goal,
    make_goal_input,
    make_subtask,
    make_health_output,
)
from tests.fixtures.domain.personas import experienced_user, infeasible_user, new_user
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


@pytest.mark.scenario("N1")
@pytest.mark.category("normal")
async def test_N1_clear_quantifiable_goal_single_turn(test_db):
    """Clear, quantifiable, time-bound goal → single intake turn → stage == 'confirming'."""
    goal = make_goal(goal_id="g_n1", user_id="u_n1", status="CREATED")
    sub_tasks = [
        make_subtask(f"t{i}", goal_id="g_n1")
        for i in range(1, 6)
    ]
    goal_with_tasks = make_goal(
        goal_id="g_n1", user_id="u_n1", status="CREATED", sub_tasks=sub_tasks
    )

    async def _seed_goal(db):
        await create_goal(db, goal_with_tasks)

    scripts = {
        "add_goal": ScenarioScript(
            intent="add_goal",
            tool_sequence=[ToolCall(fn=_seed_goal, kwargs={})],
            final_response={
                "stage": "confirming",
                "assistant_message": "Great! I've set up your goal with 5 sub-tasks.",
                "goal_id": "g_n1",
                "validation_failures": [],
                "draft": {"goal_id": "g_n1"},
            },
        )
    }

    runner = StubRunner(db=test_db, scripts=scripts)
    app = _build_app(runner)

    with step("POST /v1/intake/turn with clear goal → expect confirming stage"):
        payload = make_goal_input(
            user_id="u_n1",
            intent="add_goal",
            raw_user_message="I want to solve 5 Leetcode medium problems by next Friday.",
        )
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/v1/intake/turn", json=payload)

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()

    with step("Verify stage == confirming and goal created in DB"):
        assert data["stage"] == "confirming", (
            f"Expected 'confirming', got {data['stage']!r}"
        )
        assert data["session_id"], "session_id must be set"

    with step("Verify goal in DB has status CREATED"):
        from agents.tools.goal_db import get_goal
        g = await get_goal(test_db, "g_n1")
        assert g is not None, "Goal must exist in DB after intake turn"
        assert g.status == "CREATED", f"Expected CREATED, got {g.status!r}"
        assert len(g.sub_tasks) == 5, f"Expected 5 sub-tasks, got {len(g.sub_tasks)}"

    with step("Verify no planned_date in GoalSubTask sub-tasks"):
        for t in g.sub_tasks:
            assert not hasattr(t, "planned_date") or t.planned_date is None, (
                f"Sub-task {t.sub_task_id} must not have planned_date set at intake time"
            )


@pytest.mark.scenario("N2")
@pytest.mark.category("normal")
async def test_N2_vague_goal_triggers_validation_loop(test_db):
    """Vague goal → validation loop → first response must not contain forbidden words."""
    scripts = {
        "add_goal": ScenarioScript(
            intent="add_goal",
            tool_sequence=[],
            final_response={
                "stage": "validating",
                "assistant_message": "What would count as completing this goal — is there a number, a deliverable, or a specific outcome you're aiming for?",
                "goal_id": None,
                "validation_failures": ["quantifiable"],
                "draft": {},
            },
        )
    }

    runner = StubRunner(db=test_db, scripts=scripts)
    app = _build_app(runner)

    with step("POST vague goal → expect validating stage"):
        payload = new_user(intent="add_goal", raw_message="I want to study more.")
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/v1/intake/turn", json=payload)

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()

    with step("Verify first response does not contain forbidden words (Invariant I10)"):
        msg = data["assistant_message"].lower()
        forbidden = ["invalid", "rejected", "fail"]
        for word in forbidden:
            assert word not in msg, (
                f"Response must not contain '{word}' (Invariant I10). "
                f"Got: {data['assistant_message']!r}"
            )

    with step("Verify stage is validating"):
        assert data["stage"] == "validating", f"Expected validating, got {data['stage']!r}"
        assert "validation_failures" in data
        assert len(data["validation_failures"]) > 0


@pytest.mark.scenario("N3")
@pytest.mark.category("normal")
async def test_N3_infeasible_goal_presents_three_options(test_db):
    """Infeasible goal → agent presents exactly A., B., C. options (Invariant I4)."""
    scripts = {
        "add_goal": ScenarioScript(
            intent="add_goal",
            tool_sequence=[],
            final_response={
                "stage": "feasibility",
                "assistant_message": (
                    "Based on your history, similar goals typically take ~40% longer than planned "
                    "(original: 600 min, adjusted: 840 min). Suggested adjustments:\n"
                    "A. Extend deadline to 2026-06-08\n"
                    "B. Reduce target to 9 problems\n"
                    "C. Keep original goal — I will send daily reminders to help you stay on track."
                ),
                "goal_id": None,
                "validation_failures": [],
                "draft": {"feasibility_score": 0.4},
            },
        )
    }

    runner = StubRunner(db=test_db, scripts=scripts)
    app = _build_app(runner)

    with step("POST infeasible goal → expect feasibility proposal with 3 options"):
        payload = infeasible_user(
            intent="add_goal",
            raw_message="I want to solve 20 Leetcode hard problems in 2 days.",
        )
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/v1/intake/turn", json=payload)

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()

    with step("Verify response contains exactly A., B., C. (Invariant I4)"):
        msg = data["assistant_message"]
        for option in ["A.", "B.", "C."]:
            assert option in msg, (
                f"Response must contain '{option}'. Got: {msg!r}"
            )
