import time
from uuid import uuid4
from fastapi import APIRouter, BackgroundTasks, Request
from pydantic import BaseModel
from google.adk.runners import Runner
from google.genai import types
from google import genai
from api.dependencies import get_runner
from agents.memory import MemoryAgent
from db import get_db
from config import settings
import http_client
from telemetry import tracer, meter, get_logger
from agents.tools.performance_stats import record_chat
from services.day_plan_service import DayPlanService
from services.turn_orchestrator import TurnOrchestrator

router = APIRouter(prefix="/chat", tags=["chat"])

_logger = get_logger("chat")
_genai_client = genai.Client(
    api_key=settings.gemini_api_key,
    http_options=types.HttpOptions(httpx_async_client=http_client.shared_async_client()),
)

_chat_duration = meter.create_histogram("chat.duration", unit="ms", description="Chat endpoint total duration")
_chat_llm_duration = meter.create_histogram("chat.llm.duration", unit="ms", description="LLM runner duration within chat")
_memory_consolidation_count = meter.create_counter("chat.memory_consolidations", description="Memory consolidation tasks queued")


class ChatRequest(BaseModel):
    user_id: str
    message: str
    session_id: str | None = None


class ChatResponse(BaseModel):
    reply: str
    session_id: str
    day_plan: dict | None = None          # the DayPlan after this turn — the only thing clients render
    error: dict | None = None             # {"code": "generation_failed" | "invalid_transition" | ..., "message"}


async def _consolidate_memory(user_id: str, user_message: str, assistant_reply: str) -> None:
    """Background task: extract key insights from this turn and store as persistent memory."""
    with tracer.start_as_current_span("chat.memory_consolidation") as span:
        span.set_attribute("user.id", user_id)
        prompt = f"""Extract the key personal facts or insights from this conversation turn that are worth remembering long-term.
Focus on: personal relationships, goals, preferences, important dates, life events.
Ignore: generic scheduling info, one-time task details.

User: {user_message}
Assistant: {assistant_reply}

If there is nothing worth remembering, return exactly: NOTHING
Otherwise return a single compressed sentence summarizing what to remember."""

        try:
            start = time.perf_counter()
            response = await _genai_client.aio.models.generate_content(
                model=settings.ingestion_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    thinking_config=types.ThinkingConfig(thinking_budget=0),
                ),
            )
            llm_ms = (time.perf_counter() - start) * 1000
            span.set_attribute("genai.duration_ms", llm_ms)
            span.set_attribute("gen_ai.request.model", settings.ingestion_model)

            summary = response.text.strip()
            span.add_event("agent.output", {"gen_ai.response.text": summary[:2048]})
            if summary and summary != "NOTHING":
                mem = MemoryAgent(get_db())
                await mem.store_memory(user_id, summary, {"source": "chat_consolidation"})
                span.set_attribute("memory.stored", True)
                _logger.info(f"[memory_consolidation] OK for {user_id} — stored: {summary[:200]}")
            else:
                span.set_attribute("memory.stored", False)
                _logger.info(f"[memory_consolidation] OK for {user_id} — nothing worth storing")
        except Exception as e:
            span.record_exception(e)
            _logger.warning(f"Memory consolidation failed for {user_id}: {e}")


def runner_chat_responder(runner: Runner):
    """Adapt the ADK runner (read-only coordinator) to the orchestrator's ChatResponder."""
    async def respond(user_id: str, session_id: str, message: str) -> str:
        existing = await runner.session_service.get_session(
            app_name="daypilot", user_id=user_id, session_id=session_id
        )
        if existing is None:
            await runner.session_service.create_session(
                app_name="daypilot", user_id=user_id, session_id=session_id
            )
        content = types.Content(role="user", parts=[types.Part(text=message)])
        reply = ""
        async for event in runner.run_async(user_id=user_id, session_id=session_id, new_message=content):
            if event.is_final_response() and event.content and event.content.parts:
                # parts[0].text can be None when the part is a function call, so scan all parts
                for part in event.content.parts:
                    if getattr(part, "text", None):
                        reply = part.text
                        break
        return reply
    return respond


def _get_orchestrator(request: Request) -> TurnOrchestrator:
    injected = getattr(request.app.state, "turn_orchestrator", None)
    if injected is not None:
        return injected
    return TurnOrchestrator(DayPlanService(), chat_responder=runner_chat_responder(get_runner(request)))


@router.post("/", response_model=ChatResponse)
async def chat(body: ChatRequest, background_tasks: BackgroundTasks, request: Request) -> ChatResponse:
    """Main chat endpoint: intent parsing → DayPlanService (schedule) or read-only agent (chat)."""
    with tracer.start_as_current_span("chat.handle_request") as span:
        chat_start = time.perf_counter()
        session_id = body.session_id or str(uuid4())
        span.set_attribute("user.id", body.user_id)
        span.set_attribute("session.id", session_id)
        span.set_attribute("chat.message_length", len(body.message))

        result = None
        try:
            llm_start = time.perf_counter()
            result = await _get_orchestrator(request).run_turn(body.user_id, body.message, session_id)
            llm_ms = (time.perf_counter() - llm_start) * 1000
            _chat_llm_duration.record(llm_ms, {"user.id": body.user_id})
            span.set_attribute("chat.llm_duration_ms", llm_ms)
            span.set_attribute("chat.intent", result.intent)
            reply = result.reply
            if not reply:
                _logger.warning(f"[chat] Empty reply for {body.user_id} (intent={result.intent})")
                reply = "I wasn't able to generate a response. Please try again."
        except Exception as e:
            span.record_exception(e)
            _logger.error(f"[chat] turn failed for {body.user_id}: {e}")
            reply = "I'm having trouble connecting right now. Please try again in a moment."

        failed = result is None
        # Memory consolidation only for conversational turns; schedule turns carry no
        # long-term personal facts and their replies are rendered by code.
        if result is not None and result.intent == "chat" and result.reply:
            background_tasks.add_task(_consolidate_memory, body.user_id, body.message, reply)
            _memory_consolidation_count.add(1, {"user.id": body.user_id})

        span.set_attribute("chat.reply_length", len(reply))
        span.add_event("chat.input", {"user.message": body.message[:2048]})
        span.add_event("agent.output", {"gen_ai.response.text": reply[:4096]})
        duration_ms = (time.perf_counter() - chat_start) * 1000
        _chat_duration.record(duration_ms, {"user.id": body.user_id})
        record_chat(duration_ms, had_error=failed)
        _logger.info(f"[chat] {'FAILED' if failed else 'OK'} for {body.user_id} — {duration_ms:.0f}ms — "
                     f"intent={getattr(result, 'intent', None)} error={getattr(result, 'error', None)}")

        plan = result.day_plan if result else None
        return ChatResponse(
            reply=reply,
            session_id=session_id,
            day_plan=plan.model_dump(mode="json") if plan else None,
            error=result.error.model_dump() if result and result.error else None,
        )
