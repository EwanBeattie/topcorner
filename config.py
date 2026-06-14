"""Central config.

Two sources, deliberately separated:
  - secrets (logins, API key) come from `.env`
  - tunable settings come from `settings.toml`
"""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

_SETTINGS_PATH = os.path.join(os.path.dirname(__file__), "settings.toml")


def _load_settings() -> dict:
    try:
        with open(_SETTINGS_PATH, "rb") as fh:
            return tomllib.load(fh)
    except FileNotFoundError:
        return {}


_S = _load_settings()

# --- tunable settings (settings.toml) ---
WINDOW_HOURS: int = int(_S.get("window_hours", 48))
LEADERBOARD_TOP_N: int = int(_S.get("leaderboard_top_n", 0))
CROWD_SCORE_LIMIT: int = int(_S.get("crowd_score_limit", 19))
TOPCORNER_THROTTLE: float = float(_S.get("topcorner_throttle", 1.5))
MD_DIR: str = _S.get("md_dir", "reports/md")
JSON_DIR: str = _S.get("json_dir", "reports/json")


# --- secrets (.env) ---
@dataclass(frozen=True)
class BetfairCreds:
    username: str
    password: str
    app_key: str

    @property
    def ok(self) -> bool:
        return all([self.username, self.password, self.app_key])


@dataclass(frozen=True)
class TopcornerCreds:
    username: str
    password: str

    @property
    def ok(self) -> bool:
        return all([self.username, self.password])


def betfair_creds() -> BetfairCreds:
    return BetfairCreds(
        username=os.getenv("BETFAIR_USERNAME", ""),
        password=os.getenv("BETFAIR_PASSWORD", ""),
        app_key=os.getenv("BETFAIR_APP_KEY", ""),
    )


def topcorner_creds() -> TopcornerCreds:
    return TopcornerCreds(
        username=os.getenv("TOPCORNER_USERNAME", ""),
        password=os.getenv("TOPCORNER_PASSWORD", ""),
    )
