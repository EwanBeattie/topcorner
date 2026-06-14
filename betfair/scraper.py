"""Betfair Exchange API client: pull World Cup match-odds + correct-score.

Flow (see Betfair Exchange API docs):
  1. login          -> session token (interactive identitysso endpoint)
  2. listCompetitions  -> find the FIFA World Cup competitionId
  3. listMarketCatalogue -> market IDs for MATCH_ODDS / CORRECT_SCORE in window
  4. listMarketBook   -> decimal EX best-offer prices

All prices returned are DECIMAL odds (best available back price).
"""
from __future__ import annotations

import re
import sys
from datetime import datetime, timedelta, timezone

import requests

from common.models import BetfairGame, Fixture, MatchOdds

LOGIN_URL = "https://identitysso.betfair.com/api/login"
KEEPALIVE_URL = "https://identitysso.betfair.com/api/keepAlive"
BETTING_URL = "https://api.betfair.com/exchange/betting/json-rpc/v1"

FOOTBALL_EVENT_TYPE = "1"
# listMarketBook accepts up to 200 market IDs per call.
MARKETBOOK_BATCH = 200
# Real scorelines like "2-1" (excludes bucket runners such as "Any Other Home Win").
_NUMERIC_SCORE = re.compile(r"^\d+-\d+$")


class BetfairError(RuntimeError):
    pass


class BetfairClient:
    def __init__(self, username: str, password: str, app_key: str):
        self._username = username
        self._password = password
        self.app_key = app_key
        self.session_token: str | None = None
        self._http = requests.Session()

    # --- auth -------------------------------------------------------------
    def login(self) -> None:
        resp = self._http.post(
            LOGIN_URL,
            data={"username": self._username, "password": self._password},
            headers={
                "Accept": "application/json",
                "X-Application": self.app_key,
                "Content-Type": "application/x-www-form-urlencoded",
            },
            timeout=20,
        )
        resp.raise_for_status()
        body = resp.json()
        if body.get("status") != "SUCCESS":
            raise BetfairError(
                f"Betfair login failed: status={body.get('status')} "
                f"error={body.get('error')}"
            )
        self.session_token = body["token"]

    def _rpc(self, method: str, params: dict) -> list | dict:
        if not self.session_token:
            raise BetfairError("Not logged in — call login() first.")
        payload = {
            "jsonrpc": "2.0",
            "method": f"SportsAPING/v1.0/{method}",
            "params": params,
            "id": 1,
        }
        resp = self._http.post(
            BETTING_URL,
            json=payload,
            headers={
                "X-Authentication": self.session_token,
                "X-Application": self.app_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            timeout=30,
        )
        resp.raise_for_status()
        body = resp.json()
        if "error" in body:
            raise BetfairError(f"{method} error: {body['error']}")
        return body["result"]

    # --- discovery --------------------------------------------------------
    def find_world_cup_competition_id(self) -> str:
        """Return the competitionId whose name matches the FIFA World Cup.

        Prefers an exact 'FIFA World Cup' name; ignores qualifiers / women's /
        youth competitions.
        """
        comps = self._rpc(
            "listCompetitions",
            {"filter": {"eventTypeIds": [FOOTBALL_EVENT_TYPE]}},
        )
        candidates = []
        for item in comps:
            name = item["competition"]["name"]
            low = name.lower()
            if "world cup" not in low:
                continue
            if any(bad in low for bad in ("qualif", "women", "u17", "u20", "u21", "club")):
                continue
            candidates.append((name, item["competition"]["id"], item.get("marketCount", 0)))
        if not candidates:
            raise BetfairError("Could not find a FIFA World Cup competition.")
        # Prefer exact-ish 'fifa world cup', else the one with most markets.
        candidates.sort(key=lambda c: ("fifa world cup" not in c[0].lower(), -c[2]))
        return candidates[0][1]

    def list_catalogue(self, competition_id: str, window_hours: int) -> list[dict]:
        now = datetime.now(timezone.utc)
        end = now + timedelta(hours=window_hours)
        return self._rpc(
            "listMarketCatalogue",
            {
                "filter": {
                    "eventTypeIds": [FOOTBALL_EVENT_TYPE],
                    "competitionIds": [competition_id],
                    "marketTypeCodes": ["MATCH_ODDS", "CORRECT_SCORE"],
                    "marketStartTime": {
                        "from": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "to": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    },
                },
                "marketProjection": [
                    "EVENT",
                    "MARKET_START_TIME",
                    "MARKET_DESCRIPTION",
                    "RUNNER_DESCRIPTION",
                ],
                "sort": "FIRST_TO_START",
                "maxResults": "1000",
            },
        )

    def list_market_book(self, market_ids: list[str]) -> dict[str, dict]:
        """Return {marketId: marketBook} for best back/lay exchange prices."""
        out: dict[str, dict] = {}
        for i in range(0, len(market_ids), MARKETBOOK_BATCH):
            batch = market_ids[i : i + MARKETBOOK_BATCH]
            result = self._rpc(
                "listMarketBook",
                {
                    "marketIds": batch,
                    "priceProjection": {"priceData": ["EX_BEST_OFFERS"]},
                },
            )
            for mb in result:
                out[mb["marketId"]] = mb
        return out

    # --- high level -------------------------------------------------------
    def get_world_cup_games(self, window_hours: int) -> list[BetfairGame]:
        comp_id = self.find_world_cup_competition_id()
        catalogue = self.list_catalogue(comp_id, window_hours)
        if not catalogue:
            return []

        books = self.list_market_book([m["marketId"] for m in catalogue])

        # Group markets by event (one match). selectionId -> runner name comes
        # from the catalogue; prices come from the book.
        games: dict[str, BetfairGame] = {}
        for market in catalogue:
            event = market["event"]
            event_id = event["id"]
            if event_id not in games:
                games[event_id] = _new_game(event)
            game = games[event_id]

            name_by_sel = {
                r["selectionId"]: r["runnerName"] for r in market.get("runners", [])
            }
            book = books.get(market["marketId"])
            prices = _best_back_by_selection(book) if book else {}
            mtype = market["description"]["marketType"]

            if mtype == "MATCH_ODDS":
                _fill_match_odds(game, name_by_sel, prices)
            elif mtype == "CORRECT_SCORE":
                for sel, name in name_by_sel.items():
                    key = _score_key(name)
                    # Keep only real scorelines ("h-a"); drop bucket runners
                    # like "Any Other Home Win".
                    if _NUMERIC_SCORE.match(key):
                        game.correct_score[key] = prices.get(sel)

        return sorted(games.values(), key=lambda g: g.fixture.kickoff)


# --- helpers --------------------------------------------------------------
def _new_game(event: dict) -> BetfairGame:
    home, away = _split_event_name(event["name"])
    kickoff = _parse_dt(event.get("openDate"))
    return BetfairGame(fixture=Fixture(home=home, away=away, kickoff=kickoff))


def _split_event_name(name: str) -> tuple[str, str]:
    for sep in (" v ", " vs ", " @ "):
        if sep in name:
            h, a = name.split(sep, 1)
            return h.strip(), a.strip()
    return name.strip(), ""


def _parse_dt(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _best_back_by_selection(book: dict) -> dict[int, float | None]:
    out: dict[int, float | None] = {}
    for runner in book.get("runners", []):
        atb = runner.get("ex", {}).get("availableToBack", [])
        out[runner["selectionId"]] = atb[0]["price"] if atb else None
    return out


def _fill_match_odds(game: BetfairGame, names: dict[int, str], prices: dict) -> None:
    home_n = game.fixture.home.lower()
    away_n = game.fixture.away.lower()
    for sel, name in names.items():
        low = name.strip().lower()
        price = prices.get(sel)
        if low == "the draw" or low == "draw":
            game.match_odds.draw = price
        elif low == home_n or low in home_n or home_n in low:
            game.match_odds.home = price
        elif low == away_n or low in away_n or away_n in low:
            game.match_odds.away = price


def _score_key(runner_name: str) -> str:
    """Betfair correct-score runner names look like '2 - 1'. Normalize to '2-1'.

    Bucket runners ('Any Other Home Win', etc.) are kept as their text.
    """
    parts = runner_name.replace(" ", "").split("-")
    if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
        return f"{int(parts[0])}-{int(parts[1])}"
    return runner_name.strip()


def get_games(creds, window_hours: int) -> list[BetfairGame]:
    """Convenience wrapper used by the report."""
    if not creds.ok:
        print(
            "[betfair] missing BETFAIR_USERNAME / BETFAIR_PASSWORD / BETFAIR_APP_KEY"
            " — skipping Betfair.",
            file=sys.stderr,
        )
        return []
    print("[betfair] logging in and fetching World Cup markets...", file=sys.stderr)
    client = BetfairClient(creds.username, creds.password, creds.app_key)
    client.login()
    games = client.get_world_cup_games(window_hours)
    print(f"[betfair] done: {len(games)} games in window.", file=sys.stderr)
    return games
