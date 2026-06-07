from uuid import uuid4
from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel
from google.adk.runners import Runner
from google.genai import types
from google import genai
from api.dependencies import get_runner
from agents.memory import MemoryAgent
from db import get_db
from config import settings
import http_client

router = APIRouter(prefix="/chat", tags=["chat"])

_genai_client = genai.Client(
    api_key=settings.gemini_api_key,
    http_options=types.HttpOptions(httpx_async_client=http_client.shared_async_client()),
)


class ChatRequest(BaseModel):
    user_id: str
    message: str
    session_id: str | None = None


class ChatResponse(BaseModel):
    reply: str
    session_id: str
    pending_proposal: dict | None = None


async def _consolidate_memory(user_id: str, user_message: str, assistant_reply: str) -> None:
    """Background task: extract key insights from this turn and store as persistent memory."""
    prompt = f"""Extract the key personal facts or insights from this conversation turn that are worth remembering long-term.
Focus on: personal relationships, goals, preferences, important dates, life events.
Ignore: generic scheduling info, one-time task details.

User: {user_message}
Assistant: {assistant_reply}

If there is nothing worth remembering, return exactly: NOTHING
Otherwise return a single compressed sentence summarizing what to remember."""

    try:
        response = await _genai_client.aio.models.generate_content(
            model=settings.ingestion_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            ),
        )
        summary = response.text.strip()
        if summary and summary != "NOTHING":
            mem = MemoryAgent(get_db())
            await mem.store_memory(user_id, summary, {"source": "chat_consolidation"})
    except Exception:
        pass  # Memory consolidation is best-effort, never block the response


@router.post("/", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    background_tasks: BackgroundTasks,
    runner: Runner = Depends(get_runner),
) -> ChatResponse:
    """Main chat endpoint. All user messages go through the ADK coordinator."""
    session_id = body.session_id or str(uuid4())

    existing = await runner.session_service.get_session(
        app_name="daypilot", user_id=body.user_id, session_id=session_id
    )
    if existing is None:
        await runner.session_service.create_session(
            app_name="daypilot", user_id=body.user_id, session_id=session_id
        )

    content = types.Content(
        role="user",
        parts=[types.Part(text=body.message)],
    )

    reply = ""
    pending_proposal: dict | None = None
    _SCHEDULE_TOOLS = {"plan_schedule", "adjust_schedule"}

    try:
        async for event in runner.run_async(
            user_id=body.user_id,
            session_id=session_id,
            new_message=content,
        ):
            if event.is_final_response() and event.content and event.content.parts:
                reply = event.content.parts[0].text
            # Capture plan_schedule / adjust_schedule results to return as pending proposal
            if event.content and event.content.parts:
                for part in event.content.parts:
                    fr = getattr(part, "function_response", None)
                    if fr and getattr(fr, "name", "") in _SCHEDULE_TOOLS:
                        raw = getattr(fr, "response", None)
                        if isinstance(raw, dict):
                            pending_proposal = {
                                "type": "plan" if fr.name == "plan_schedule" else "adjust",
                                "date": raw.get("date", ""),
                                "data": raw,
                            }
    except Exception as e:
        print(f"[chat] LLM error for {body.user_id}: {e}")
        reply = "I'm having trouble connecting right now. Please try again in a moment."

    # Async memory consolidation — runs after response is sent, never blocks user
    if reply and "trouble connecting" not in reply:
        background_tasks.add_task(_consolidate_memory, body.user_id, body.message, reply)

    return ChatResponse(reply=reply, session_id=session_id, pending_proposal=pending_proposal)