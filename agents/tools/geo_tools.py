"""
Geo tool — multi-segment commute calculator.

Computes commute duration for each leg of the user's day via Google Routes API
(transit → walking → driving fallback) and generates Google Maps deep-link URLs.
"""

import logging
from datetime import datetime, timezone
from urllib.parse import quote

import httpx

from config import settings

logger = logging.getLogger(__name__)

_ROUTES_ENDPOINT = "https://routes.googleapis.com/directions/v2:computeRoutes"
_MOCK_DURATIONS = {"transit": 25, "walking": 8, "driving": 15}


# ─────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────

def _safe_departure_time(ts: str | None) -> str | None:
    """Return RFC3339 Z string if ts is a future time; None otherwise."""
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        if dt <= datetime.now(timezone.utc):
            return None  # past → omit, API defaults to now
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return None


def _build_maps_url(origin: str, destination: str) -> str:
    return (
        "https://www.google.com/maps/dir/?api=1"
        f"&origin={quote(origin)}"
        f"&destination={quote(destination)}"
    )


async def _call_routes_api(
    origin: str,
    destination: str,
    departure_time: str | None,
    mode: str,  # "transit" | "walking" | "driving"
) -> int | None:
    """Return commute minutes; None if no route available for this mode."""

    # Mock when no API key configured
    if not settings.google_maps_api_key:
        return _MOCK_DURATIONS.get(mode)

    travel_mode_map = {"transit": "TRANSIT", "walking": "WALK", "driving": "DRIVE"}
    travel_mode = travel_mode_map[mode]

    # TODO: 当前只支持地址字符串 {"address": x}。未来前端若传 GPS 坐标,
    # 需支持 {"location": {"latLng": {"latitude":.., "longitude":..}}}
    body: dict = {
        "origin": {"address": origin},
        "destination": {"address": destination},
        "travelMode": travel_mode,
    }

    safe_dt = _safe_departure_time(departure_time)
    if safe_dt:
        body["departureTime"] = safe_dt

    headers = {
        "X-Goog-Api-Key": settings.google_maps_api_key,
        "X-Goog-FieldMask": "routes.duration",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(_ROUTES_ENDPOINT, json=body, headers=headers)

        if resp.status_code != 200:
            logger.warning("Routes API [%s] %s → %s: HTTP %s — %s",
                           mode, origin, destination, resp.status_code, resp.text[:200])
            return None

        routes = resp.json().get("routes", [])
        if not routes:
            return None

        duration_str = routes[0].get("duration", "")
        if not duration_str:
            return None

        seconds = int(duration_str.rstrip("s"))
        return round(seconds / 60)

    except Exception as exc:
        logger.warning("Routes API [%s] %s → %s: %s", mode, origin, destination, exc)
        return None


# ─────────────────────────────────────────────────────────
# Tool function
# ─────────────────────────────────────────────────────────

async def get_geo_info(
    current_location: str,
    events: list[dict],
) -> dict:
    """
    Compute commute duration for each leg of the user's day.

    Args:
        current_location: user's starting point (address string).
        events: time-ordered list of dicts, each:
            {"location": str | None, "start_time": ISO8601, "end_time": ISO8601}

    Returns:
        {"segments": [
            {"from": str, "to": str, "duration_minutes": int | None,
             "mode": "transit"|"walking"|"driving"|"none"|"unknown",
             "maps_url": str, "error": str | None},
            ...
        ]}

    Tries transit → walking → driving in order.
    If all three modes fail, the segment is marked with duration_minutes=None,
    mode="unknown", and an error string so the caller can surface the issue.

    Same-location legs return duration=0, mode="none", maps_url="".
    Events with null/empty/virtual location (online/virtual/remote/zoom/tbd)
    are skipped; the next segment departs from the last valid location.

    duration uses Google Routes API with departure_time = previous event's
    end_time (time-specific traffic). maps_url is a Google Maps deep-link
    for frontend navigation (does not preset departure time).
    """
    _VIRTUAL = {"online", "virtual", "remote", "zoom", "tbd"}

    segments = []
    prev_location = current_location
    prev_end_time: str | None = None

    for event in events:
        event_location = (event.get("location") or "").strip()

        # Skip events with no physical location or virtual/online keywords
        if not event_location or event_location.lower() in _VIRTUAL:
            continue

        if event_location == prev_location.strip():
            # Same location — no commute needed
            segments.append({
                "from": prev_location,
                "to": event_location,
                "duration_minutes": 0,
                "mode": "none",
                "maps_url": "",
                "error": None,
            })
        else:
            duration: int | None = None
            mode = "unknown"
            error: str | None = None

            for try_mode in ("transit", "walking", "driving"):
                result = await _call_routes_api(
                    prev_location, event_location, prev_end_time, mode=try_mode
                )
                if result is not None:
                    duration = result
                    mode = try_mode
                    break
            else:
                error = "No route found for any mode (transit/walking/driving)"
                logger.warning("get_geo_info: %s", error)

            segment: dict = {
                "from": prev_location,
                "to": event_location,
                "duration_minutes": duration,
                "mode": mode,
                "maps_url": _build_maps_url(prev_location, event_location) if duration is not None else "",
                "error": error,
            }
            segments.append(segment)

        prev_location = event_location
        prev_end_time = event.get("end_time")

    return {"segments": segments}
