import time
from datetime import datetime, timedelta
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
from services.turn_orchestrator import TurnOrchestrator, legacy_pending_proposal

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
    # Transitional (removed in Phase 5): derived from day_plan for pre-refactor clients.
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
    if not settings.use_schedule_orchestrator:
        return await _legacy_chat(body, background_tasks, get_runner(request))

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
            pending_proposal=legacy_pending_proposal(plan),
            schedule_updated=bool(result and result.state_changed),
        )


async def _legacy_chat(body: ChatRequest, background_tasks: BackgroundTasks, runner: Runner) -> ChatResponse:
    """Pre-refactor path (settings.use_schedule_orchestrator=False): the coordinator drives
    schedule tools itself. Kept only for rollback; removed in Phase 5."""
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
                    from services.day_plan_repository import DayPlanRepository
                    from services.day_plan_service import today_for
                    cutoff = (datetime.now() - timedelta(seconds=45)).isoformat(timespec="seconds")
                    plan = await DayPlanRepository().get(body.user_id, today_for(body.user_id))
                    if plan.proposal and plan.proposal.created_at > cutoff:
                        pending_proposal = {
                            "type": plan.proposal.kind,
                            "date": plan.date,
                            "data": {
                                "strategies": [s.model_dump() for s in plan.proposal.strategies],
                                "top_recommendation": plan.proposal.top_recommendation,
                                "date": plan.date,
                            },
                        }
                        _logger.info(
                            f"[chat] DB fallback: recovered pending_proposal for {body.user_id} "
                            f"(status={plan.status.value}, created_at={plan.proposal.created_at})"
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
        record_chat(duration_ms, had_error="trouble connecting" in reply)
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