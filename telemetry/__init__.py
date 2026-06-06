"""
DayPilot Telemetry — OpenTelemetry instrumentation exporting to Dynatrace.

Usage:
    from telemetry import tracer, meter, get_logger

    with tracer.start_as_current_span("my_operation") as span:
        span.set_attribute("user_id", user_id)
        ...

    counter = meter.create_counter("my_counter")
    counter.add(1, {"key": "value"})

    logger = get_logger("my_module")
    logger.info("Something happened")
"""

from telemetry.setup import tracer, meter, get_logger, setup_telemetry

__all__ = ["tracer", "meter", "get_logger", "setup_telemetry"]
