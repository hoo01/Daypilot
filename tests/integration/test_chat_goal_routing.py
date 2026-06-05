"""
Tests for chat.py event-capture paths when the coordinator transfers to
goal_tracking_root → goal_intake_agent (3-level nesting).

Three paths under test:
  Path 1 — normal: is_final_response() fires with text → captured immediately.
  Path 2 — mixed event: intake agent returns text+function_call in one event
            (is_final_response()=False) → captured by last_agent_text fallback.
  Path 3 — no events with text: reply comes from session state output_key
            written by goal_tracking_root.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI

from api.routes.chat import router


# ---------------------------------------------------------------------------
# Minimal fake ADK event helpers
# ---------------------------------------------------------------------------

def _make_part(text=None, function_call=None):
    part = MagicMock()
    part.text = text
    part.function_call = function_call
    return part


def _make_event(
    author: str,
    text: str | None = None,
    is_final: bool = False,
    has_function_call: bool = False,
    has_function_response: bool = False,
):
    event = MagicMock()
    event.author = author
    event.is_final_response = MagicMock(return_value=is_final)
    event.get_function_calls = MagicMock(return_value=[MagicMock()] if has_function_call else [])
    event.get_function_responses = MagicMock(return_value=[MagicMock()] if has_function_response else [])

    if text:
        part = _make_part(text=text)
        content = MagicMock()
        content.parts = [part]
        event.content = content
    else:
        event.content = None

    return event


# ---------------------------------------------------------------------------
# Fake runner that yields a scripted sequence of events + has a fake session
# ---------------------------------------------------------------------------

class FakeRunner:
    def __init__(self, events, session_state=None):
        self._events = events
        self._session_state = session_state or {}
        self.session_service = self

    async def run_async(self, **kwargs):
        for event in self._events:
            yield event

    async def get_session(self, **kwargs):
        session = MagicMock()
        session.state = self._session_state
        return session

    async def create_session(self, **kwargs):
        pass


def _build_chat_app(runner):
    app = FastAPI()
    app.include_router(router)
    app.state.runner = runner
    return app


# ---------------------------------------------------------------------------
# Path 1: is_final_response() fires — normal coordinator reply
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_chat_path1_final_response_captured():
    """Coordinator emits is_final_response()=True with text → reply captured immediately."""
    events = [
        _make_event("daypilot_coordinator", text=None, has_function_call=True),
        _make_event("daypilot_coordinator", text="Here's your daily plan.", is_final=True),
    ]
    app = _build_chat_app(FakeRunner(events))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/chat/", json={
            "user_id": "u1",
            "message": "What's my plan today?",
            "session_id": "s1",
        })

    assert resp.status_code == 200
    data = resp.json()
    assert data["reply"] == "Here's your daily plan."


# ---------------------------------------------------------------------------
# Path 2: intake agent text mixed with function_call → last_agent_text fallback
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_chat_path2_last_agent_text_fallback():
    """
    goal_intake_agent emits text+function_call in one event (is_final_response()=False).
    No event has is_final_response()=True with text.
    last_agent_text fallback must surface the intake agent's clarifying question.
    """
    events = [
        # coordinator transfer call
        _make_event("daypilot_coordinator", text=None, has_function_call=True),
        # goal_tracking_root transfer call
        _make_event("goal_tracking_root", text=None, has_function_call=True),
        # intake agent: text + function_call in same event → is_final=False
        _make_event(
            "goal_intake_agent",
            text="What's your target deadline for this goal?",
            is_final=False,
            has_function_call=True,
        ),
        # goal_tracking_root function response (no new text)
        _make_event("goal_tracking_root", text=None, has_function_response=True),
        # coordinator function response (no new text)
        _make_event("daypilot_coordinator", text=None, has_function_response=True),
    ]
    app = _build_chat_app(FakeRunner(events))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/chat/", json={
            "user_id": "u2",
            "message": "I want to solve 10 Leetcode problems",
            "session_id": "s2",
        })

    assert resp.status_code == 200
    data = resp.json()
    assert data["reply"] == "What's your target deadline for this goal?"


# ---------------------------------------------------------------------------
# Path 3: no text in event stream → session state output_key fallback
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_chat_path3_session_state_fallback():
    """
    All events have no text content. goal_tracking_root stored its reply via
    output_key → session.state["goal_response"]. Must be returned as reply.
    """
    events = [
        _make_event("daypilot_coordinator", text=None, has_function_call=True),
        _make_event("goal_tracking_root", text=None, has_function_call=True),
        _make_event("daypilot_coordinator", text=None, has_function_response=True),
    ]
    session_state = {
        "goal_response": "Great! When do you want to finish these 10 problems?"
    }
    app = _build_chat_app(FakeRunner(events, session_state=session_state))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/chat/", json={
            "user_id": "u3",
            "message": "I want to solve 10 Leetcode problems",
            "session_id": "s3",
        })

    assert resp.status_code == 200
    data = resp.json()
    assert data["reply"] == "Great! When do you want to finish these 10 problems?"


# ---------------------------------------------------------------------------
# Edge: user message from author "user" must not be captured as reply
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_chat_user_events_not_captured_as_reply():
    """Events with author='user' must not leak into the reply."""
    events = [
        _make_event("user", text="I want to solve 10 Leetcode problems", is_final=False),
        _make_event("daypilot_coordinator", text="Got it, routing you now.", is_final=True),
    ]
    app = _build_chat_app(FakeRunner(events))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/chat/", json={
            "user_id": "u4",
            "message": "I want to solve 10 Leetcode problems",
            "session_id": "s4",
        })

    assert resp.status_code == 200
    data = resp.json()
    assert data["reply"] == "Got it, routing you now."
