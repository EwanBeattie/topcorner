"""The 16 World Cup 2026 host venues with coordinates + timezone.

`venues.toml` maps each matchup to one of these city keys; the weather client
uses the coordinates here (no geocoding needed) to query the forecast.
"""
from __future__ import annotations

# key -> (display venue, latitude, longitude, IANA timezone)
HOST_CITIES: dict[str, dict] = {
    # Mexico
    "mexico_city": {"venue": "Estadio Azteca, Mexico City, Mexico",
                    "lat": 19.3029, "lon": -99.1505, "tz": "America/Mexico_City"},
    "guadalajara": {"venue": "Estadio Akron, Guadalajara, Mexico",
                    "lat": 20.6819, "lon": -103.4625, "tz": "America/Mexico_City"},
    "monterrey": {"venue": "Estadio BBVA, Monterrey, Mexico",
                  "lat": 25.6692, "lon": -100.2444, "tz": "America/Monterrey"},
    # Canada
    "toronto": {"venue": "BMO Field, Toronto, Canada",
                "lat": 43.6332, "lon": -79.4185, "tz": "America/Toronto"},
    "vancouver": {"venue": "BC Place, Vancouver, Canada",
                  "lat": 49.2768, "lon": -123.1120, "tz": "America/Vancouver"},
    # USA
    "new_york": {"venue": "MetLife Stadium, New York/New Jersey, USA",
                 "lat": 40.8136, "lon": -74.0744, "tz": "America/New_York"},
    "boston": {"venue": "Gillette Stadium, Boston, USA",
               "lat": 42.0909, "lon": -71.2643, "tz": "America/New_York"},
    "philadelphia": {"venue": "Lincoln Financial Field, Philadelphia, USA",
                     "lat": 39.9008, "lon": -75.1675, "tz": "America/New_York"},
    "miami": {"venue": "Hard Rock Stadium, Miami, USA",
              "lat": 25.9580, "lon": -80.2389, "tz": "America/New_York"},
    "atlanta": {"venue": "Mercedes-Benz Stadium, Atlanta, USA",
                "lat": 33.7553, "lon": -84.4006, "tz": "America/New_York"},
    "houston": {"venue": "NRG Stadium, Houston, USA",
                "lat": 29.6847, "lon": -95.4107, "tz": "America/Chicago"},
    "kansas_city": {"venue": "Arrowhead Stadium, Kansas City, USA",
                    "lat": 39.0489, "lon": -94.4839, "tz": "America/Chicago"},
    "dallas": {"venue": "AT&T Stadium, Dallas, USA",
               "lat": 32.7473, "lon": -97.0945, "tz": "America/Chicago"},
    "bay_area": {"venue": "Levi's Stadium, San Francisco Bay Area, USA",
                 "lat": 37.4030, "lon": -121.9700, "tz": "America/Los_Angeles"},
    "los_angeles": {"venue": "SoFi Stadium, Los Angeles, USA",
                    "lat": 33.9535, "lon": -118.3392, "tz": "America/Los_Angeles"},
    "seattle": {"venue": "Lumen Field, Seattle, USA",
                "lat": 47.5952, "lon": -122.3316, "tz": "America/Los_Angeles"},
}


def city(key: str) -> dict | None:
    return HOST_CITIES.get(key)
