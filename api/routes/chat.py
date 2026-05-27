from uuid import uuid4
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from google.adk.runners import Runner
from google.genai import types
from api.dependencies import get_runner

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatRequest(BaseModel):
    user_id: str
    message: str
    session_id: str | None = None


class ChatResponse(BaseModel):
    reply: str
    session_id: str


@router.post("/", response_model=ChatResponse)
async def chat(body: ChatRequest, runner: Runner = Depends(get_runner)) -> ChatResponse:
    """Main chat endpoint. All user messages go through the ADK coordinator."""
    session_id = body.session_id or str(uuid4())

    # Create session if it doesn't exist yet
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
    async for event in runner.run_async(
        user_id=body.user_id,
        session_id=session_id,
        new_message=content,
    ):
        if event.is_final_response() and event.content and event.content.parts:
            reply = event.content.parts[0].text
            break

    return ChatResponse(reply=reply, session_id=session_id)
