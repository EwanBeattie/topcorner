"""Team-name normalization and fixture matching across the two sources.

Betfair and topcorner.org will spell national teams differently
("USA" vs "United States", "Korea Republic" vs "South Korea"). We normalize
both sides to a canonical token and match fixtures on
(home, away, kickoff date).
"""
from __future__ import annotations

import re
import unicodedata

# Canonical aliases -> the form we compare on. Keys are normalized (lowercased,
# accent-stripped). Extend as needed when a join misses.
_ALIASES = {
    "usa": "united states",
    "us": "united states",
    "united states of america": "united states",
    "korea republic": "south korea",
    "republic of korea": "south korea",
    "korea dpr": "north korea",
    "ir iran": "iran",
    "iran islamic republic": "iran",
    "czechia": "czech republic",
    "ivory coast": "cote divoire",
    "cote d ivoire": "cote divoire",
    "bosnia and herzegovina": "bosnia",
    "bosnia herzegovina": "bosnia",
    "cape verde": "cabo verde",
    "china pr": "china",
    "turkiye": "turkey",
    "uae": "united arab emirates",
    "drc": "dr congo",
    "congo dr": "dr congo",
    "republic of ireland": "ireland",
}


def normalize_team(name: str) -> str:
    """Lowercase, strip accents/punctuation, collapse spaces, apply aliases."""
    if not name:
        return ""
    n = unicodedata.normalize("NFKD", name)
    n = "".join(c for c in n if not unicodedata.combining(c))
    n = n.lower().strip()
    n = re.sub(r"[^a-z0-9 ]+", " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    return _ALIASES.get(n, n)


def match_key(home: str, away: str) -> tuple[str, str]:
    """Normalized (home, away) key — identifies the same fixture across sources
    despite spelling differences (USA vs United States, etc.)."""
    return (normalize_team(home), normalize_team(away))


def slug(home: str, away: str) -> str:
    """Stable filename stem for a fixture, e.g. 'canada_vs_bosnia'.

    Derived from the normalized names so the same match always maps to the same
    file regardless of which source named it.
    """
    h, a = match_key(home, away)
    return f"{h}_vs_{a}".replace(" ", "_")


def numbered_slug(number, home: str, away: str, width: int = 3) -> str:
    """Filename stem prefixed with the tournament game number so files sort
    chronologically, e.g. '012_canada_vs_bosnia'. Zero-padded so 2 sorts before
    10. Falls back to '000' when the number is unknown."""
    base = slug(home, away)
    n = number if number is not None else 0
    return f"{n:0{width}d}_{base}"
