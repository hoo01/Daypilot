"""
Instrumentation helpers — decorators and context managers for tracing tool calls,
LLM invocations, and pipeline nodes without heavy refactoring of existing code.
"""

import time
import functools
from typing import Any, Callable

from opentelemetry import trace

from telemetry import tracer, meter, get_logger

logger = get_logger("instrument")

# ── Metrics ─────────────────────────────────────────────────────────────────

tool_call_duration = meter.create_histogram(
    "agent.tool.duration", unit="ms", description="Tool call duration"
)
tool_call_count = meter.create_counter(
    "agent.tool.calls", description="Total tool invocations"
)
tool_call_errors = meter.create_counter(
    "agent.tool.errors", description="Tool call errors"
)
llm_call_duration = meter.create_histogram(
    "genai.request.duration", unit="ms", description="LLM call duration"
)
llm_call_count = meter.create_counter(
    "genai.requests", description="Total LLM calls"
)
pipeline_node_duration = meter.create_histogram(
    "health.pipeline.node.duration", unit="ms", description="Health pipeline node duration"
)


def traced_tool(name: str | None = None):
    """Decorator for async tool functions — creates a span and records metrics."""
    def decorator(func: Callable) -> Callable:
        tool_name = name or func.__name__

        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            with tracer.start_as_current_span(f"tool.{tool_name}") as span:
                span.set_attribute("tool.name", tool_name)

                # Try to extract user_id from first arg or kwargs
                user_id = kwargs.get("user_id") or (args[0] if args and isinstance(args[0], str) else None)
                if user_id:
                    span.set_attribute("user.id", user_id)

                start = time.perf_counter()
                try:
                    result = await func(*args, **kwargs)
                    span.set_attribute("tool.success", True)
                    tool_call_count.add(1, {"tool.name": tool_name, "tool.status": "success"})
                    # Capture tool output for Dynatrace observability
                    try:
                        import json as _json
                        output_str = _json.dumps(result, default=str) if isinstance(result, (dict, list)) else str(result)
                        span.add_event("agent.output", {"tool.output": output_str[:4096]})
                        logger.info(f"[tool.{tool_name}] OK — output: {output_str[:500]}")
                    except Exception:
                        pass
                    return result
                except Exception as exc:
                    span.set_status(trace.StatusCode.ERROR, str(exc))
                    span.record_exception(exc)
                    span.set_attribute("tool.success", False)
                    tool_call_count.add(1, {"tool.name": tool_name, "tool.status": "error"})
                    tool_call_errors.add(1, {"tool.name": tool_name})
                    logger.error(f"[tool.{tool_name}] FAILED — {type(exc).__name__}: {exc}")
                    raise
                finally:
                    duration_ms = (time.perf_counter() - start) * 1000
                    tool_call_duration.record(duration_ms, {"tool.name": tool_name})
                    span.set_attribute("tool.duration_ms", duration_ms)

        return wrapper
    return decorator


def traced_llm(model: str | None = None, operation: str = "generate"):
    """Decorator for functions that call an LLM — tracks model, duration, tokens."""
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            model_name = model or kwargs.get("model", "unknown")
            with tracer.start_as_current_span(f"genai.{operation}") as span:
                span.set_attribute("gen_ai.system", "gemini")
                span.set_attribute("gen_ai.request.model", model_name)
                span.set_attribute("gen_ai.operation.name", operation)

                start = time.perf_counter()
                try:
                    result = await func(*args, **kwargs)
                    span.set_attribute("gen_ai.success", True)
                    llm_call_count.add(1, {"gen_ai.model": model_name, "gen_ai.status": "success"})
                    # Capture LLM response for Dynatrace observability
                    try:
                        output_str = result.text if hasattr(result, 'text') else str(result)
                        span.add_event("agent.output", {"gen_ai.response.text": output_str[:4096]})
                        logger.info(f"[genai.{operation}] model={model_name} OK — response: {output_str[:500]}")
                    except Exception:
                        pass
                    return result
                except Exception as exc:
                    span.set_status(trace.StatusCode.ERROR, str(exc))
                    span.record_exception(exc)
                    llm_call_count.add(1, {"gen_ai.model": model_name, "gen_ai.status": "error"})
                    logger.error(f"[genai.{operation}] model={model_name} FAILED — {type(exc).__name__}: {exc}")
                    raise
                finally:
                    duration_ms = (time.perf_counter() - start) * 1000
                    llm_call_duration.record(duration_ms, {"gen_ai.model": model_name})
                    span.set_attribute("gen_ai.duration_ms", duration_ms)

        return wrapper
    return decorator


def traced_node(node_name: str):
    """Decorator for health pipeline node functions."""
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            with tracer.start_as_current_span(f"health.pipeline.{node_name}") as span:
                span.set_attribute("pipeline.node", node_name)

                start = time.perf_counter()
                try:
                    result = await func(*args, **kwargs)
                    span.set_attribute("pipeline.node.success", True)
                    # Capture node output for Dynatrace observability
                    try:
                        import json as _json
                        output_str = _json.dumps(result, default=str) if isinstance(result, (dict, list)) else str(result)
                        span.add_event("agent.output", {"pipeline.node.output": output_str[:4096]})
                        logger.info(f"[pipeline.{node_name}] OK — output: {output_str[:500]}")
                    except Exception:
                        pass
                    return result
                except Exception as exc:
                    span.set_status(trace.StatusCode.ERROR, str(exc))
                    span.record_exception(exc)
                    logger.error(f"[pipeline.{node_name}] FAILED — {type(exc).__name__}: {exc}")
                    raise
                finally:
                    duration_ms = (time.perf_counter() - start) * 1000
                    pipeline_node_duration.record(duration_ms, {"pipeline.node": node_name})
                    span.set_attribute("pipeline.node.duration_ms", duration_ms)

        return wrapper
    return decorator
