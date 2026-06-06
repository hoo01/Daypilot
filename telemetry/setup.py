"""
OpenTelemetry setup for DayPilot — exports traces, metrics, and logs to Dynatrace via OTLP.

Environment variables:
    DT_ENVIRONMENT        — Dynatrace environment URL (e.g. https://abc.apps.dynatrace.com)
    DT_API_TOKEN          — Dynatrace API token with metrics/traces/logs ingest scope
    DT_MODE               — "always" | "on_demand" | "off" (controls agent self-monitoring)
    OTEL_SERVICE_NAME     — Override service name (default: "daypilot")
"""

import os
import logging

from opentelemetry import trace, metrics
from opentelemetry._logs import set_logger_provider
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import Resource, SERVICE_NAME, SERVICE_VERSION
from opentelemetry.semconv.resource import ResourceAttributes

# Conditional imports — graceful fallback if Dynatrace endpoint not configured
_DYNATRACE_CONFIGURED = bool(os.environ.get("DT_API_TOKEN"))

_resource = Resource.create({
    SERVICE_NAME: os.environ.get("OTEL_SERVICE_NAME", "daypilot"),
    SERVICE_VERSION: "0.1.0",
    "deployment.environment": os.environ.get("APP_ENV", "development"),
})


def _get_otlp_endpoint() -> str:
    """Build the Dynatrace OTLP endpoint from DT_ENVIRONMENT.

    DT_ENVIRONMENT is typically https://<id>.apps.dynatrace.com
    but OTLP ingest uses https://<id>.live.dynatrace.com/api/v2/otlp
    """
    dt_env = os.environ.get("DT_ENVIRONMENT", "").rstrip("/")
    if not dt_env:
        return ""
    # Convert apps.dynatrace.com → live.dynatrace.com for OTLP ingest
    otlp_base = dt_env.replace(".apps.dynatrace.com", ".live.dynatrace.com")
    return f"{otlp_base}/api/v2/otlp"


def _build_tracer_provider() -> TracerProvider:
    provider = TracerProvider(resource=_resource)

    endpoint = _get_otlp_endpoint()
    if endpoint and _DYNATRACE_CONFIGURED:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        exporter = OTLPSpanExporter(
            endpoint=f"{endpoint}/v1/traces",
            headers={"Authorization": f"Api-Token {os.environ.get('DT_API_TOKEN', '')}"},
        )
        logging.getLogger("daypilot.setup").info(f"OTLP traces endpoint: {endpoint}/v1/traces")
        provider.add_span_processor(BatchSpanProcessor(exporter))
    # No console exporter — our structured logging handles local dev visibility

    return provider


def _build_meter_provider() -> MeterProvider:
    readers = []

    endpoint = _get_otlp_endpoint()
    if endpoint and _DYNATRACE_CONFIGURED:
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter

        exporter = OTLPMetricExporter(
            endpoint=f"{endpoint}/v1/metrics",
            headers={"Authorization": f"Api-Token {os.environ.get('DT_API_TOKEN', '')}"},
        )
        logging.getLogger("daypilot.setup").info(f"OTLP metrics endpoint: {endpoint}/v1/metrics")
        readers.append(PeriodicExportingMetricReader(exporter, export_interval_millis=30000))

    return MeterProvider(resource=_resource, metric_readers=readers)


def _build_logger_provider() -> LoggerProvider:
    provider = LoggerProvider(resource=_resource)

    endpoint = _get_otlp_endpoint()
    if endpoint and _DYNATRACE_CONFIGURED:
        from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter

        exporter = OTLPLogExporter(
            endpoint=f"{endpoint}/v1/logs",
            headers={"Authorization": f"Api-Token {os.environ.get('DT_API_TOKEN', '')}"},
        )
        logging.getLogger("daypilot.setup").info(f"OTLP logs endpoint: {endpoint}/v1/logs")
        provider.add_log_record_processor(BatchLogRecordProcessor(exporter))

    return provider


def setup_telemetry():
    """Initialize OTel providers globally. Call once at app startup."""
    tracer_provider = _build_tracer_provider()
    meter_provider = _build_meter_provider()
    logger_provider = _build_logger_provider()

    trace.set_tracer_provider(tracer_provider)
    metrics.set_meter_provider(meter_provider)
    set_logger_provider(logger_provider)

    # Attach OTel log handler to root 'daypilot' logger so all get_logger() calls
    # automatically export to Dynatrace while preserving existing StreamHandler output
    otel_handler = LoggingHandler(level=logging.INFO, logger_provider=logger_provider)
    logging.getLogger("daypilot").addHandler(otel_handler)


# Initialize on import for simplicity — providers are lightweight even without exporters
setup_telemetry()

# Public API
tracer = trace.get_tracer("daypilot", "0.1.0")
meter = metrics.get_meter("daypilot", "0.1.0")


def get_logger(name: str) -> logging.Logger:
    """Get a structured logger for the given module."""
    logger = logging.getLogger(f"daypilot.{name}")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("[%(asctime)s] %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S")
        )
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG if os.environ.get("APP_ENV") == "development" else logging.INFO)
    return logger


def get_dt_mode() -> str:
    """Return the current Dynatrace integration mode."""
    return os.environ.get("DT_MODE", "on_demand")
