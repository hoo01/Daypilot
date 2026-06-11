import time
from datetime import datetime, timedelta
from uuid import uuid4
from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel
from google.adk.runners import Runner
from google.genai import types
from google import genai
from api.dependencies import get_runner
from agents.memory import MemoryAgent
from db import get_db
from db.collections import Collections
from config import settings
import http_client
from telemetry import tracer, meter, get_logger

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
    pending_proposal: dict | None = None
    schedule_updated: bool = False


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


@router.post("/", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    background_tasks: BackgroundTasks,
    runner: Runner = Depends(get_runner),
) -> ChatResponse:
    """Main chat endpoint. All user messages go through the ADK coordinator."""
    with tracer.start_as_current_span("chat.handle_request") as span:
        chat_start = time.perf_counter()
        session_id = body.session_id or str(uuid4())
        span.set_attribute("user.id", body.user_id)
        span.set_attribute("session.id", session_id)
        span.set_attribute("chat.message_length", len(body.message))

        existing = await runner.session_service.get_session(
            app_name="daypilot", user_id=body.user_id, session_id=session_id
        )
        if existing is None:
            await runner.session_service.create_session(
                app_name="daypilot", user_id=body.user_id, session_id=session_id
            )
            span.set_attribute("session.is_new", True)

        content = types.Content(
            role="user",
            parts=[types.Part(text=body.message)],
        )

        reply = ""
        pending_proposal: dict | None = None
        _SCHEDULE_TOOLS = {"plan_schedule", "adjust_schedule"}
        try:
            llm_start = time.perf_counter()
            async for event in runner.run_async(
                user_id=body.user_id,
                session_id=session_id,
                new_message=content,
            ):
                if event.is_final_response() and event.content and event.content.parts:
                    # parts[0].text can be None when the part is a function call, so scan all parts
                    for part in event.content.parts:
                        if getattr(part, "text", None):
                            reply = part.text
                            break
                # Capture plan_schedule / adjust_schedule results to return as pending proposal
                if event.content and event.content.parts:
                    for part in event.content.parts:
                        fr = getattr(part, "function_response", None)
                        if fr and getattr(fr, "name", "") in _SCHEDULE_TOOLS:
                            raw = getattr(fr, "response", None)
                            # ADK may return a proto Struct instead of a plain dict
                            if raw is not None and not isinstance(raw, dict):
                                try:
                                    raw = dict(raw)
                                except Exception:
                                    raw = None
                            if isinstance(raw, dict):
                                pending_proposal = {
                                    "type": "plan" if fr.name == "plan_schedule" else "adjust",
                                    "date": raw.get("date", ""),
                                    "data": raw,
                                }
            llm_ms = (time.perf_counter() - llm_start) * 1000
            _chat_llm_duration.record(llm_ms, {"user.id": body.user_id})
            span.set_attribute("chat.llm_duration_ms", llm_ms)

            # Fallback: if event-based detection missed a plan_schedule call
            # (e.g. LLM reproduced the schedule from context without re-calling the tool,
            # or ADK emitted the function_response in an unexpected event structure),
            # check the DB for a record generated within the last 45 seconds.
            if not pending_proposal:
                try:
                    today = datetime.utcnow().date().isoformat()
                    cutoff = (datetime.utcnow() - timedelta(seconds=45)).isoformat()
                    db = get_db()
                    # Check both confirmed and unconfirmed — when a plan is already confirmed,
                    # _persist_schedule updates all_strategies but keeps confirmed=True,
                    # so the old confirmed=False filter missed these refreshed proposals.
                    record = await db[Collections.DAILY_SCHEDULES].find_one(
                        {
                            "user_id": body.user_id,
                            "date": today,
                            "generated_at": {"$gt": cutoff},
                        }
                    )
                    if record and record.get("all_strategies"):
                        pending_proposal = {
                            "type": "plan",
                            "date": record["date"],
                            "data": {
                                "strategies": record["all_strategies"],
                                "top_recommendation": record.get("strategy_name", ""),
                                "date": record["date"],
                            },
                        }
                        _logger.info(
                            f"[chat] DB fallback: recovered pending_proposal for {body.user_id} "
                            f"(confirmed={record.get('confirmed')}, generated_at={record.get('generated_at')})"
                        )
                except Exception as _fb_err:
                    _logger.warning(f"[chat] DB fallback check failed: {_fb_err}")

            if not reply:
                _logger.warning(f"[chat] Empty reply for {body.user_id} — no text found in final response events")
                reply = "I wasn't able to generate a response. Please try again."
        except Exception as e:
            span.record_exception(e)
            _logger.error(f"LLM error for {body.user_id}: {e}")
            reply = "I'm having trouble connecting right now. Please try again in a moment."

        # Async memory consolidation — runs after response is sent, never blocks user
        if reply and "trouble connecting" not in reply:
            background_tasks.add_task(_consolidate_memory, body.user_id, body.message, reply)
            _memory_consolidation_count.add(1, {"user.id": body.user_id})

        span.set_attribute("chat.reply_length", len(reply))
        span.add_event("chat.input", {"user.message": body.message[:2048]})
        span.add_event("agent.output", {"gen_ai.response.text": reply[:4096]})
        duration_ms = (time.perf_counter() - chat_start) * 1000
        _chat_duration.record(duration_ms, {"user.id": body.user_id})
        if "trouble connecting" in reply:
            _logger.error(f"[chat] FAILED for {body.user_id} — {duration_ms:.0f}ms — returned error fallback")
        else:
            _logger.info(f"[chat] OK for {body.user_id} — {duration_ms:.0f}ms — reply: {reply[:500]}")

        return ChatResponse(
            reply=reply,
            session_id=session_id,
            pending_proposal=pending_proposal,
            schedule_updated=pending_proposal is not None,
        )