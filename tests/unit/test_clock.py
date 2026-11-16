"""Per-user timezone: "today" and "now" follow the timezone the client sends.

Pinned to 2026-11-16 03:39 UTC — the moment the deployed (UTC) service filed a Pacific
user's evening plan under the next day.
"""
from datetime import datetime, timezone

import pytest

import config
from services import clock
from services.day_plan_service import today_for

INSTANT = datetime(2026, 11, 16, 3, 39, tzinfo=timezone.utc)


@pytest.fixture
def pinned(monkeypatch):
    monkeypatch.setattr(clock, "_utcnow", lambda: INSTANT)
    monkeypatch.setattr(config.settings, "default_timezone", "")


def _with_tz(name, fn):
    token = clock.set_request_timezone(name)
    try:
        return fn()
    finally:
        clock.reset_request_timezone(token)


def test_request_timezone_decides_today_and_now(pinned):
    assert _with_tz("America/Los_Angeles", clock.today_local) == "2026-11-15"
    assert _with_tz("America/Los_Angeles", clock.now_local) == datetime(2026, 11, 15, 19, 39)
    assert _with_tz("Asia/Tokyo", clock.today_local) == "2026-11-16"
    assert _with_tz("Asia/Tokyo", clock.now_local) == datetime(2026, 11, 16, 12, 39)


def test_now_local_is_naive_like_the_stored_timestamps(pinned):
    assert _with_tz("America/Los_Angeles", clock.now_local).tzinfo is None


def test_today_for_follows_the_request_timezone(pinned):
    assert _with_tz("America/Los_Angeles", lambda: today_for("u")) == "2026-11-15"


def test_default_timezone_is_used_without_a_header(pinned, monkeypatch):
    monkeypatch.setattr(config.settings, "default_timezone", "America/New_York")
    assert clock.today_local() == "2026-11-15"
    assert clock.now_local() == datetime(2026, 11, 15, 22, 39)


@pytest.mark.parametrize("bad", ["Not/AZone", "", "   ", "../../etc/passwd", "x" * 200])
def test_invalid_timezone_falls_back_to_default(pinned, monkeypatch, bad):
    monkeypatch.setattr(config.settings, "default_timezone", "Europe/London")
    assert _with_tz(bad, clock.now_local) == datetime(2026, 11, 16, 3, 39)


def test_without_header_or_default_uses_server_local_time(pinned):
    expected = datetime.fromtimestamp(INSTANT.timestamp())   # server-local wall clock
    assert clock.now_local() == expected
    assert clock.today_local() == expected.date().isoformat()


def test_invalid_default_timezone_is_ignored(pinned, monkeypatch):
    monkeypatch.setattr(config.settings, "default_timezone", "Mars/Olympus")
    assert clock.now_local() == datetime.fromtimestamp(INSTANT.timestamp())
