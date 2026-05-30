"""Unit tests for pure helper functions in schedule_agent."""
import pytest
from datetime import datetime

from app.agent.schedule_agent import (
    _naive_dt,
    _times_overlap,
    _normalize_timestamp,
    _minutes_between,
    _fix_year,
    _extract_json,
)


class TestNaiveDt:
    def test_bare_iso(self):
        dt = _naive_dt("2026-05-28T09:00:00")
        assert dt == datetime(2026, 5, 28, 9, 0, 0)
        assert dt.tzinfo is None

    def test_utc_z(self):
        dt = _naive_dt("2026-05-28T09:00:00Z")
        assert dt == datetime(2026, 5, 28, 9, 0, 0)
        assert dt.tzinfo is None

    def test_positive_offset(self):
        dt = _naive_dt("2026-05-28T09:00:00+05:30")
        assert dt == datetime(2026, 5, 28, 9, 0, 0)
        assert dt.tzinfo is None

    def test_negative_offset(self):
        dt = _naive_dt("2026-05-28T14:45:00-07:00")
        assert dt == datetime(2026, 5, 28, 14, 45, 0)
        assert dt.tzinfo is None


class TestTimesOverlap:
    def test_clear_overlap(self):
        assert _times_overlap(
            "2026-05-28T09:00:00", "2026-05-28T11:00:00",
            "2026-05-28T10:00:00", "2026-05-28T12:00:00",
        )

    def test_no_overlap(self):
        assert not _times_overlap(
            "2026-05-28T09:00:00", "2026-05-28T10:00:00",
            "2026-05-28T10:00:00", "2026-05-28T11:00:00",
        )

    def test_contained(self):
        assert _times_overlap(
            "2026-05-28T09:00:00", "2026-05-28T12:00:00",
            "2026-05-28T10:00:00", "2026-05-28T11:00:00",
        )

    def test_touching_no_overlap(self):
        # end == start of next → no overlap (strict)
        assert not _times_overlap(
            "2026-05-28T09:00:00", "2026-05-28T10:00:00",
            "2026-05-28T10:00:00", "2026-05-28T11:00:00",
        )

    def test_mixed_tz(self):
        # Calendar event with tz offset vs. naive locked block
        assert _times_overlap(
            "2026-05-28T14:45:00-07:00", "2026-05-28T15:45:00-07:00",
            "2026-05-28T14:50:00", "2026-05-28T16:00:00",
        )


class TestNormalizeTimestamp:
    def test_full_iso_unchanged(self):
        ts = "2026-05-28T09:00:00"
        assert _normalize_timestamp(ts, "2026-05-28") == ts

    def test_bare_hhmm_gets_date(self):
        result = _normalize_timestamp("09:00", "2026-05-28")
        assert result == "2026-05-28T09:00:00"

    def test_bare_hhmmss_gets_date(self):
        result = _normalize_timestamp("09:00:00", "2026-05-28")
        assert result == "2026-05-28T09:00:00"

    def test_already_has_date(self):
        ts = "2026-05-28T21:30:00"
        assert _normalize_timestamp(ts, "2026-05-28") == ts


class TestMinutesBetween:
    def test_one_hour(self):
        assert _minutes_between("2026-05-28T09:00:00", "2026-05-28T10:00:00") == 60.0

    def test_half_hour(self):
        assert _minutes_between("2026-05-28T09:00:00", "2026-05-28T09:30:00") == 30.0

    def test_zero(self):
        assert _minutes_between("2026-05-28T09:00:00", "2026-05-28T09:00:00") == 0.0

    def test_overnight(self):
        mins = _minutes_between("2026-05-28T23:00:00", "2026-05-29T01:00:00")
        assert mins == 120.0


class TestFixYear:
    def test_off_by_one_corrected(self):
        assert _fix_year("2025-05-28T09:00:00", "2026") == "2026-05-28T09:00:00"

    def test_correct_year_unchanged(self):
        assert _fix_year("2026-05-28T09:00:00", "2026") == "2026-05-28T09:00:00"

    def test_two_years_off_unchanged(self):
        assert _fix_year("2024-05-28T09:00:00", "2026") == "2024-05-28T09:00:00"


class TestExtractJson:
    def test_plain_json(self):
        raw = '{"key": "value"}'
        assert _extract_json(raw) == '{"key": "value"}'

    def test_markdown_json_fence(self):
        raw = "```json\n{\"key\": \"value\"}\n```"
        assert _extract_json(raw) == '{"key": "value"}'

    def test_markdown_fence_no_lang(self):
        raw = "```\n{\"key\": \"value\"}\n```"
        assert _extract_json(raw) == '{"key": "value"}'
