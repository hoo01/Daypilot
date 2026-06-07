"""
FastAPI middleware for automatic request tracing and metrics.
"""

import time
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from opentelemetry import trace

from telemetry import tracer, meter, get_logger

logger = get_logger("http")

# Metrics
_request_duration = meter.create_histogram(
    "http.server.request.duration",
    unit="ms",
    description="HTTP request duration in milliseconds",
)
_request_count = meter.create_counter(
    "http.server.request.count",
    description="Total HTTP requests",
)
_error_count = meter.create_counter(
    "http.server.error.count",
    description="Total HTTP errors (4xx/5xx)",
)


class TelemetryMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        route = request.url.path
        method = request.method

        # Skip health checks from tracing noise
        if route == "/health":
            return await call_next(request)

        with tracer.start_as_current_span(
            f"{method} {route}",
            kind=trace.SpanKind.SERVER,
        ) as span:
            span.set_attribute("http.method", method)
            span.set_attribute("http.route", route)
            span.set_attribute("http.url", str(request.url))

            # Extract user_id from body if available (for POST requests)
            start = time.perf_counter()
            status_code = 500

            try:
                response = await call_next(request)
                status_code = response.status_code
                span.set_attribute("http.status_code", status_code)

                if status_code >= 400:
                    span.set_status(trace.StatusCode.ERROR, f"HTTP {status_code}")
                    _error_count.add(1, {"http.route": route, "http.status_code": str(status_code)})

                return response
            except Exception as exc:
                span.set_status(trace.StatusCode.ERROR, str(exc))
                span.record_exception(exc)
                _error_count.add(1, {"http.route": route, "http.status_code": "500"})
                raise
            finally:
                duration_ms = (time.perf_counter() - start) * 1000
                span.set_attribute("http.duration_ms", duration_ms)
                _request_duration.record(duration_ms, {"http.route": route, "http.method": method})
                _request_count.add(1, {"http.route": route, "http.method": method, "http.status_code": str(status_code)})
                logger.info(f"{method} {route} → {status_code} ({duration_ms:.0f}ms)")
