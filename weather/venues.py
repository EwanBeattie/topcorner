"""Resolve a fixture to its host venue (via venues.toml) and fetch its weather.

venues.toml maps each matchup slug ("canada_vs_bosnia") to a host-city key from
cities.HOST_CITIES. Unmapped or blank matchups simply get no weather section.
"""
from __future__ import annotations

import os
import tomllib
from datetime import datetime
from typing import Optional

import requests

from common.teams import slug
from .cities import HOST_CITIES
from .client import get_weather

_DEFAULT_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "venues.toml")


def load_venue_map(path: str = _DEFAULT_PATH) -> dict[str, str]:
    """Return {matchup_slug: city_key}, ignoring blank entries."""
    try:
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
    except FileNotFoundError:
        return {}
    venues = data.get("venues", data)  # accept [venues] table or flat keys
    return {k: v for k, v in venues.items() if isinstance(v, str) and v}


def weather_for(home: str, away: str, kickoff: datetime,
                venue_map: dict[str, str],
                session: Optional[requests.Session] = None) -> Optional[dict]:
    """Look up the venue for a fixture and fetch its kickoff weather, or None."""
    city_key = venue_map.get(slug(home, away))
    city = HOST_CITIES.get(city_key) if city_key else None
    if not city:
        return None
    w = get_weather(city["lat"], city["lon"], city["tz"], kickoff, session)
    if w is None:
        return None
    w["venue"] = city["venue"]
    w["city"] = city_key
    return w
