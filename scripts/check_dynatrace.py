"""Dynatrace connectivity check: sends one test span / metric / log the same way
telemetry/setup.py does (OTLP/HTTP + Api-Token) and prints what Dynatrace answers.
Then checks whether the API token can read metrics back.

Usage: python scripts/check_dynatrace.py .   (reads ./.env; prints no secrets)
"""
import os
import sys
import time

from dotenv import load_dotenv

load_dotenv(os.path.join(sys.argv[1], ".env"))

import requests
from opentelemetry.exporter.otlp.proto.common._log_encoder import encode_logs
from opentelemetry.exporter.otlp.proto.common.metrics_encoder import encode_metrics
from opentelemetry.exporter.otlp.proto.common.trace_encoder import encode_spans
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceResponse
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceResponse
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import InMemoryLogExporter, SimpleLogRecordProcessor
from opentelemetry.sdk.metrics import Histogram, MeterProvider
from opentelemetry.sdk.metrics.export import AggregationTemporality, InMemoryMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

dt_env = os.environ.get("DT_ENVIRONMENT", "").rstrip("/")
token = os.environ.get("DT_API_TOKEN", "")
live = dt_env.replace(".apps.dynatrace.com", ".live.dynatrace.com")
otlp = f"{live}/api/v2/otlp"
hdr = {"Authorization": f"Api-Token {token}", "Content-Type": "application/x-protobuf"}
res = Resource.create({"service.name": "daypilot-connectivity-check"})
print(f"tenant host : {live.split('//')[-1].split('.')[0][:4]}…  token set: {bool(token)}")


def post(kind, body, resp_cls=None):
    r = requests.post(f"{otlp}/v1/{kind}", data=body, headers=hdr, timeout=20)
    detail = ""
    if resp_cls is not None and r.status_code == 200 and r.content:
        msg = resp_cls()
        msg.ParseFromString(r.content)
        ps = msg.partial_success
        rejected = getattr(ps, "rejected_spans", 0) or getattr(ps, "rejected_data_points", 0)
        detail = f" partial_success: rejected={rejected} msg={ps.error_message!r}" if (rejected or ps.error_message) else " (all accepted)"
    elif r.status_code != 200:
        detail = " " + r.text[:300]
    print(f"{kind:8s}: HTTP {r.status_code}{detail}")


# traces
mem = InMemorySpanExporter()
tp = TracerProvider(resource=res)
tp.add_span_processor(SimpleSpanProcessor(mem))
with tp.get_tracer("check").start_as_current_span("connectivity_check"):
    pass
post("traces", encode_spans(mem.get_finished_spans()).SerializeToString(), ExportTraceServiceResponse)

# metrics: the SDK default (CUMULATIVE, what telemetry/setup.py sends today) vs DELTA
for label, temporality in (("cumulative", AggregationTemporality.CUMULATIVE), ("delta", AggregationTemporality.DELTA)):
    reader = InMemoryMetricReader(preferred_temporality={Histogram: temporality})
    mp = MeterProvider(resource=res, metric_readers=[reader])
    h = mp.get_meter("check").create_histogram(f"connectivity_check.duration_{label}", unit="ms")
    h.record(123.0, {"check": label})
    print(f"[{label}] ", end="")
    post("metrics", encode_metrics(reader.get_metrics_data()).SerializeToString(), ExportMetricsServiceResponse)

# logs
log_mem = InMemoryLogExporter()
lp = LoggerProvider(resource=res)
lp.add_log_record_processor(SimpleLogRecordProcessor(log_mem))
import logging
lg = logging.getLogger("dtcheck")
lg.addHandler(LoggingHandler(logger_provider=lp))
lg.warning("daypilot connectivity check")
post("logs", encode_logs(log_mem.get_finished_logs()).SerializeToString())

# read-back: can this token query metrics (needed to pull latency numbers out programmatically)?
r = requests.get(f"{live}/api/v2/metrics", params={"pageSize": 1},
                 headers={"Authorization": f"Api-Token {token}"}, timeout=20)
print(f"metrics read (GET /api/v2/metrics): HTTP {r.status_code} {'' if r.ok else r.text[:200]}")
r = requests.get(f"{live}/api/v2/metrics/query",
                 params={"metricSelector": "chat.duration", "resolution": "Inf", "from": "now-30d"},
                 headers={"Authorization": f"Api-Token {token}"}, timeout=20)
print(f"query chat.duration (30d): HTTP {r.status_code} {r.text[:300]}")
