"""topcorner.org client: log in, read the leaderboard, pull each user's
predicted scorelines, and aggregate them into a per-fixture crowd distribution.

Login is django-allauth: GET the login page for the CSRF token, then POST
login/password back. The leaderboard (/leaderboard/) is public; the per-user
prediction pages (/fixtures/user/<id>/) require a logged-in session.
"""
from __future__ import annotations

import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

from common.models import CrowdGame, Fixture, UserPrediction
from common.teams import match_key

BASE = "https://topcorner.org"
LOGIN_URL = f"{BASE}/accounts/login/"
LEADERBOARD_URL = f"{BASE}/leaderboard/"
USER_URL = f"{BASE}/fixtures/user/{{user_id}}/"

USER_LINK_RE = re.compile(r"/fixtures/user/(\d+)/")
# Fixtures are grouped under day headers; kickoff times on the page are UK local.
SITE_TZ = ZoneInfo("Europe/London")

# Set TOPCORNER_DUMP_HTML=1 to save the first user page to disk so the
# prediction-row selectors can be confirmed/adjusted against real markup.
DUMP_HTML = os.getenv("TOPCORNER_DUMP_HTML") == "1"


class TopcornerError(RuntimeError):
    pass


class TopcornerClient:
    def __init__(self, username: str, password: str, throttle: float = 1.5):
        self._username = username
        self._password = password
        # Minimum seconds between requests — be polite to a small community site.
        self._throttle = throttle
        self._last_request = 0.0
        self._http = requests.Session()
        self._http.headers["User-Agent"] = "Mozilla/5.0 (topcorner-report)"
        self._dumped = False

    # --- http -------------------------------------------------------------
    def _wait(self) -> None:
        """Sleep so consecutive requests are at least `throttle` seconds apart."""
        gap = self._throttle - (time.monotonic() - self._last_request)
        if gap > 0:
            time.sleep(gap)
        self._last_request = time.monotonic()

    def _get(self, url: str, tries: int = 3) -> requests.Response:
        """Throttled GET with retry — topcorner.org is occasionally slow."""
        for attempt in range(tries):
            self._wait()
            try:
                resp = self._http.get(url, timeout=30)
                resp.raise_for_status()
                return resp
            except requests.RequestException:
                if attempt == tries - 1:
                    raise
        raise AssertionError("unreachable")

    # --- auth -------------------------------------------------------------
    def login(self) -> None:
        page = self._get(LOGIN_URL)
        token = self._csrf_token(page.text)
        if not token:
            raise TopcornerError("Could not find CSRF token on login page.")
        self._wait()
        resp = self._http.post(
            LOGIN_URL,
            data={
                "csrfmiddlewaretoken": token,
                "login": self._username,
                "password": self._password,
            },
            headers={"Referer": LOGIN_URL},
            timeout=30,
        )
        resp.raise_for_status()
        # allauth re-renders the login form (with an error) on failure, and
        # redirects away on success. Detect a lingering password field.
        if 'name="password"' in resp.text and "/accounts/logout" not in resp.text:
            raise TopcornerError(
                "topcorner login failed — check TOPCORNER_USERNAME / PASSWORD."
            )

    @staticmethod
    def _csrf_token(html: str) -> str | None:
        m = re.search(r'name="csrfmiddlewaretoken"\s+value="([^"]+)"', html)
        return m.group(1) if m else None

    # --- leaderboard ------------------------------------------------------
    def get_user_directory(self) -> list[tuple[int, str]]:
        """Return [(user_id, display_name)] in leaderboard order (rank 1 first).

        The leaderboard lists users ranked, so document order = rank order; we
        preserve it (deduping repeats) so callers can take the top N.
        """
        resp = self._get(LEADERBOARD_URL)
        soup = BeautifulSoup(resp.text, "lxml")
        users: dict[int, str] = {}  # insertion order = rank order
        for a in soup.find_all("a", href=USER_LINK_RE):
            m = USER_LINK_RE.search(a["href"])
            if not m:
                continue
            uid = int(m.group(1))
            name = a.get_text(strip=True)
            if name:
                users.setdefault(uid, name)
        return list(users.items())

    # --- predictions ------------------------------------------------------
    def get_user_predictions(self, user_id: int, user_name: str) -> list["_Row"]:
        resp = self._get(USER_URL.format(user_id=user_id))
        if DUMP_HTML and not self._dumped:
            path = f"topcorner_user_{user_id}.html.debug"
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(resp.text)
            print(f"[topcorner] dumped sample user page -> {path}", file=sys.stderr)
            self._dumped = True
        return _parse_user_predictions(resp.text, user_id, user_name)

    # --- high level -------------------------------------------------------
    def get_all_games(self, top_n: int = 0) -> list[CrowdGame]:
        """Aggregate users' predictions into one CrowdGame per fixture,
        covering the whole tournament (upcoming and already-played).

        If `top_n` > 0, only the top `top_n` leaderboard users are included.
        Played fixtures carry their actual result (read from the page) so the
        report can freeze them and compute prediction accuracy.
        """
        directory = self.get_user_directory()
        if top_n and top_n > 0:
            directory = directory[:top_n]
        total = len(directory)
        scope = f"top {total}" if (top_n and top_n > 0) else f"all {total}"
        print(f"[topcorner] fetching predictions for {scope} leaderboard users "
              f"(~{self._throttle:.1f}s apart)...", file=sys.stderr)
        games: dict[tuple[str, str], CrowdGame] = {}
        skipped = 0

        for i, (uid, name) in enumerate(directory, 1):
            print(f"\r[topcorner] {i}/{total} users  ({name[:20]:<20})",
                  end="", file=sys.stderr, flush=True)
            try:
                rows = self.get_user_predictions(uid, name)
            except requests.RequestException:  # timeout/HTTP/conn — skip user
                skipped += 1
                continue
            for r in rows:
                key = match_key(r.home, r.away)
                game = games.get(key)
                if game is None:
                    game = CrowdGame(
                        fixture=Fixture(home=r.home, away=r.away, kickoff=r.kickoff)
                    )
                    games[key] = game
                # Capture the result the first time we see a finished row for it.
                if r.played and game.final_home is None:
                    game.played = True
                    game.final_home = r.actual_home
                    game.final_away = r.actual_away
                if r.pick_home is not None:
                    game.predictions.append(UserPrediction(
                        user_id=uid, user_name=name,
                        home_goals=r.pick_home, away_goals=r.pick_away,
                    ))

        # Number games by tournament order. Page order (insertion order, taken
        # from the first user with a full fixture list) is the site's kickoff
        # order and is stable across runs.
        ordered = list(games.values())
        for i, game in enumerate(ordered, 1):
            game.number = i

        note = f" ({skipped} skipped)" if skipped else ""
        played = sum(1 for g in ordered if g.played)
        print(f"\r[topcorner] done: {total} users{note}, "
              f"{len(ordered)} games ({played} played)." + " " * 10, file=sys.stderr)
        return ordered


@dataclass
class _Row:
    """One fixture row from a user's page (the user's pick + the fixture itself,
    plus the actual result if the game is finished)."""
    home: str
    away: str
    kickoff: datetime
    played: bool
    actual_home: Optional[int]
    actual_away: Optional[int]
    pick_home: Optional[int]
    pick_away: Optional[int]


def _parse_user_predictions(html: str, user_id: int, user_name: str) -> list[_Row]:
    """Extract fixture rows from a user's predictions page.

    Page layout (confirmed): fixtures are `<a class="fxc-row">` links grouped
    under `<div class="fxc-day" data-day="YYYY-MM-DD">` headers. Within a row:
      .fxc-home .fxc-name / .fxc-away .fxc-name  -> team names
      .fxc-mid .fxc-time                         -> kickoff time (UK local), upcoming
      .fxc-mid .fxc-score                        -> actual result (finished games)
      .fxc-pred .pick                            -> THIS user's predicted score
      class "is-finished"                        -> game has been played
    """
    soup = BeautifulSoup(html, "lxml")
    out: list[_Row] = []

    for row in soup.select("a.fxc-row"):
        home_el = row.select_one(".fxc-home .fxc-name")
        away_el = row.select_one(".fxc-away .fxc-name")
        if not home_el or not away_el:
            continue
        played = "is-finished" in row.get("class", [])

        actual_h = actual_a = None
        if played:
            actual = _two_goals(row.select_one(".fxc-mid .fxc-score"))
            if actual:
                actual_h, actual_a = actual

        pick_h = pick_a = None
        pick = _two_goals(row.select_one(".fxc-pred .pick"))
        if pick:
            pick_h, pick_a = pick

        # Emit every fixture row (even with no pick) so the tournament ordering
        # can be derived from page order; predictions are recorded when present.
        out.append(_Row(
            home=home_el.get_text(strip=True),
            away=away_el.get_text(strip=True),
            kickoff=_row_kickoff(row),
            played=played,
            actual_home=actual_h, actual_away=actual_a,
            pick_home=pick_h, pick_away=pick_a,
        ))
    return out


def _two_goals(el) -> Optional[tuple[int, int]]:
    """Pull two integers (home, away) from a score/pick span, or None."""
    if el is None:
        return None
    nums = re.findall(r"\d+", el.get_text())
    if len(nums) < 2:
        return None
    return int(nums[0]), int(nums[1])


def _row_kickoff(row) -> datetime:
    """Combine the row's day header (date) and `.fxc-time` (UK local) into UTC.

    Finished rows have no time shown; we use midday so the date stays stable.
    """
    day = row.find_previous(class_="fxc-day")
    date_str = day.get("data-day") if day else None
    if not date_str:
        return datetime.now(timezone.utc)

    time_el = row.select_one(".fxc-time")
    time_str = time_el.get_text(strip=True) if time_el else "12:00"
    local = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M").replace(
        tzinfo=SITE_TZ
    )
    return local.astimezone(timezone.utc)


def get_all_games(creds, top_n: int = 0, throttle: float = 1.5) -> list[CrowdGame]:
    """Convenience wrapper used by the report. Returns tournament fixtures with
    their crowd distribution (and result, if played), limited to the top `top_n`
    leaderboard users when `top_n` > 0."""
    if not creds.ok:
        print(
            "[topcorner] missing TOPCORNER_USERNAME / TOPCORNER_PASSWORD"
            " — skipping topcorner.",
            file=sys.stderr,
        )
        return []
    client = TopcornerClient(creds.username, creds.password, throttle=throttle)
    client.login()
    return client.get_all_games(top_n=top_n)
