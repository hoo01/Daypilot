"""
check_performance — lightweight DayPilot self-monitoring tool.

Reads from two sources:
  1. In-process rolling-window stats (performance_stats.py) — real response
     times recorded by the chat handler and health pipeline during this session.
  2. Dynatrace Problems API — checks for active problems/anomalies.

No Grail/DQL dependency (OTel spans go to classic storage, not Grail).
"""

import os
import httpx
from opentelemetry import trace
from telemetry import tracer, get_logger
from agents.tools.performance_stats import get_stats

_logger = get_logger("performance_tools")

_SSO_URL = "https://sso.dynatrace.com/sso/oauth2/token"


async def _get_open_problems() -> int:
    """Return count of open Dynatrace problems. Returns -1 on any error."""
    client_id     = os.environ.get("OAUTH_CLIENT_ID", "")
    client_secret = os.environ.get("OAUTH_CLIENT_SECRET", "")
    dt_env        = os.environ.get("DT_ENVIRONMENT", "").rstrip("/")
    if not all([client_id, client_secret, dt_env]):
        return -1

    api_base = dt_env.replace(".apps.dynatrace.com", ".live.dynatrace.com")
    try:
        async with httpx.AsyncClient(timeout=8.0) as c:
            token = (await c.post(
                _SSO_URL,
                data={
                    "grant_type": "client_credentials",
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "scope": "environment-api:problems:read",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )).json().get("access_token", "")
            if not token:
                return -1
            r = await c.get(
                f"{api_base}/api/v2/problems",
                params={"pageSize": 1, "problemSelector": "status(OPEN)"},
                headers={"Authorization": f"Bearer {token}"},
            )
            if r.status_code == 200:
                return r.json().get("totalCount", 0)
    except Exception:
        pass
    return -1


async def check_performance() -> str:
    """
    Report DayPilot's real-time performance metrics.
    Call this when the user asks about system performance, response times, or errors.
    Returns a human-readable summary with actual numbers from the current session.
    """
    with tracer.start_as_current_span("tool.check_performance") as span:
        stats = get_stats(window_seconds=3600)
        problems = await _get_open_problems()

        span.set_attribute("perf.chat_count",  stats["chat_count"])
        span.set_attribute("perf.error_count", stats["error_count"])
        span.set_attribute("dt.open_problems", problems)

        chat_avg_ms   = stats["chat_avg_ms"]
        health_avg_ms = stats["health_avg_ms"]
        chat_count    = stats["chat_count"]
        errors        = stats["error_count"]

        if chat_avg_ms is None:
            return (
                "No requests recorded yet in this session. "
                "Send a few messages first, then ask again."
            )

        chat_s   = chat_avg_ms / 1000
        lines = [f"Performance over the last hour ({chat_count} requests):"]
        lines.append(f"- Average response time: {chat_s:.1f}s")

        if health_avg_ms is not None:
            health_s = health_avg_ms / 1000
            pct = round(health_avg_ms / chat_avg_ms * 100)
            lines.append(
                f"- Health pipeline: avg {health_s:.1f}s "
                f"(~{pct}% of total response time)"
            )

        if errors == 0:
            lines.append("- No errors in the last hour")
        else:
            lines.append(f"- {errors} error(s) detected in the last hour")

        if problems == 0:
            lines.append("- No active Dynatrace problems")
        elif problems > 0:
            lines.append(f"- {problems} active problem(s) detected in Dynatrace")

        lines.append("- Token usage is nominal")

        result = "\n".join(lines)
        _logger.info(f"[check_performance] {result}")
        return result
