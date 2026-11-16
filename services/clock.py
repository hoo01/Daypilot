"""The user's clock: what "today" and "now" mean for the current request.

The browser sends its IANA timezone in the `X-Timezone` header; `capture_timezone`
(a router dependency) stores it in a context variable for the rest of the request.
Everything that reasons about the user's day — today_for(), the planner prompt,
resolve_event, "already over" filtering — reads time through here.

Resolution order: request header → settings.default_timezone → server local time.
Datetimes returned are naive wall-clock times in that zone, matching the naive
ISO strings stored in schedules.
"""
from __future__ import annotations

import re
from contextvars import ContextVar, Token
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import Header

_request_tz: ContextVar[str | None] = ContextVar("daypilot_request_tz", default=None)
_TZ_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_+\-]*(/[A-Za-z0-9_+\-]+){0,2}$")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _zone(name: str | None) -> ZoneInfo | None:
    if not name:
        return None
    name = name.strip()
    if len(name) > 64 or not _TZ_NAME_RE.match(name):
        return None
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return None


def set_request_timezone(name: str | None) -> Token:
    return _request_tz.set(name)


def reset_request_timezone(token: Token) -> None:
    _request_tz.reset(token)


def current_zone() -> ZoneInfo | None:
    """The zone in effect, or None for server-local time."""
    from config import settings
    return _zone(_request_tz.get()) or _zone(getattr(settings, "default_timezone", ""))


def now_local() -> datetime:
    instant = _utcnow()
    zone = current_zone()
    if zone is None:
        return datetime.fromtimestamp(instant.timestamp())     # server local wall clock
    return instant.astimezone(zone).replace(tzinfo=None)


def today_local() -> str:
    return now_local().date().isoformat()


async def capture_timezone(x_timezone: str | None = Header(default=None)) -> None:
    """Router dependency: remember the client's timezone for this request.

    Async on purpose — it runs in the request's own task, so the context variable is
    visible to the endpoint and everything it awaits. Invalid names are ignored.
    """
    _request_tz.set(x_timezone)
