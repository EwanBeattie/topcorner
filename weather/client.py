"""Weather lookup via Open-Meteo (free, no API key).

We query the forecast endpoint with an explicit date range, which serves both
near-future (forecast) and recent-past (observed) hours — fine for a tournament
happening now. We pick the hour matching kickoff in the venue's local time.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import requests

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

_HOURLY = ",".join([
    "temperature_2m",
    "apparent_temperature",
    "relative_humidity_2m",
    "cloud_cover",
    "precipitation_probability",
    "weather_code",
])

# WMO weather codes -> (emoji, plain-English summary).
_WMO = {
    0: ("☀️", "Clear"), 1: ("🌤️", "Mainly clear"), 2: ("⛅", "Partly cloudy"),
    3: ("☁️", "Overcast"), 45: ("🌫️", "Fog"), 48: ("🌫️", "Fog"),
    51: ("🌦️", "Light drizzle"), 53: ("🌦️", "Drizzle"), 55: ("🌦️", "Heavy drizzle"),
    56: ("🌧️", "Freezing drizzle"), 57: ("🌧️", "Freezing drizzle"),
    61: ("🌧️", "Light rain"), 63: ("🌧️", "Rain"), 65: ("🌧️", "Heavy rain"),
    66: ("🌧️", "Freezing rain"), 67: ("🌧️", "Freezing rain"),
    71: ("🌨️", "Light snow"), 73: ("🌨️", "Snow"), 75: ("🌨️", "Heavy snow"),
    77: ("🌨️", "Snow grains"),
    80: ("🌦️", "Light showers"), 81: ("🌦️", "Showers"), 82: ("⛈️", "Violent showers"),
    85: ("🌨️", "Snow showers"), 86: ("🌨️", "Snow showers"),
    95: ("⛈️", "Thunderstorm"), 96: ("⛈️", "Thunderstorm w/ hail"),
    99: ("⛈️", "Thunderstorm w/ hail"),
}


def _summary(code) -> tuple[str, str]:
    return _WMO.get(code, ("", "—"))


def get_weather(lat: float, lon: float, tz: str, kickoff_utc: datetime,
                session: Optional[requests.Session] = None) -> Optional[dict]:
    """Return weather at kickoff for a venue, or None if it can't be fetched."""
    local = kickoff_utc.astimezone(ZoneInfo(tz))
    date_str = local.strftime("%Y-%m-%d")
    target = local.strftime("%Y-%m-%dT%H:00")
    http = session or requests
    params = {
        "latitude": lat, "longitude": lon,
        "hourly": _HOURLY, "timezone": tz,
        "start_date": date_str, "end_date": date_str,
    }
    hourly = None
    for attempt in range(2):
        try:
            resp = http.get(FORECAST_URL, params=params, timeout=20)
            resp.raise_for_status()
            hourly = resp.json().get("hourly", {})
            break
        except (requests.RequestException, ValueError):
            if attempt == 1:
                return None
    if not hourly:
        return None

    times = hourly.get("time", [])
    if not times:
        return None
    idx = times.index(target) if target in times else _nearest(times, target)

    def at(field):
        vals = hourly.get(field) or []
        return vals[idx] if idx < len(vals) else None

    code = at("weather_code")
    emoji, summary = _summary(code)
    return {
        "local_time": target,
        "temp_c": at("temperature_2m"),
        "feels_c": at("apparent_temperature"),
        "humidity_pct": at("relative_humidity_2m"),
        "cloud_pct": at("cloud_cover"),
        "precip_prob_pct": at("precipitation_probability"),
        "weather_code": code,
        "emoji": emoji,
        "summary": summary,
        "source": "forecast" if kickoff_utc > datetime.now(timezone.utc) else "observed",
    }


def _nearest(times: list[str], target: str) -> int:
    """Index of the hour closest to target (times share the same date)."""
    t = datetime.fromisoformat(target)
    return min(range(len(times)),
              key=lambda i: abs(datetime.fromisoformat(times[i]) - t))
