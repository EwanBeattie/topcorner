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


class VenueMap:
    """Resolves a fixture to a host-city key, by matchup slug (group stage) or by
    tournament game number (knockouts, where teams resolve late)."""
    def __init__(self, by_slug: dict[str, str], by_number: dict[int, str]):
        self.by_slug = by_slug
        self.by_number = by_number

    def city_key(self, home: str, away: str, number=None) -> Optional[str]:
        if number is not None and number in self.by_number:
            return self.by_number[number]
        return self.by_slug.get(slug(home, away))


def load_venue_map(path: str = _DEFAULT_PATH) -> VenueMap:
    """Load matchup→city and number→city maps from venues.toml."""
    try:
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
    except FileNotFoundError:
        return VenueMap({}, {})
    by_slug = {k: v for k, v in data.get("venues", {}).items()
               if isinstance(v, str) and v}
    by_number = {int(k): v for k, v in data.get("venues_by_number", {}).items()
                 if isinstance(v, str) and v}
    return VenueMap(by_slug, by_number)


def weather_for(home: str, away: str, kickoff: datetime, venue_map: VenueMap,
                session: Optional[requests.Session] = None,
                number=None) -> Optional[dict]:
    """Look up the venue for a fixture and fetch its kickoff weather, or None."""
    city_key = venue_map.city_key(home, away, number)
    city = HOST_CITIES.get(city_key) if city_key else None
    if not city:
        return None
    w = get_weather(city["lat"], city["lon"], city["tz"], kickoff, session)
    if w is None:
        return None
    w["venue"] = city["venue"]
    w["city"] = city_key
    return w
