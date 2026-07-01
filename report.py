#!/usr/bin/env python3
"""Generate per-game World Cup reports comparing Betfair Exchange odds with the
topcorner.org crowd predictions.

Writes one Markdown file (reports/md/<home>_vs_<away>.md) and one JSON file
(reports/json/<home>_vs_<away>.json) per fixture. Upcoming games are refreshed
each run; once a game is played it is finalized with the actual score + accuracy
analysis and frozen (skipped on future runs).

Usage:
    python report.py                  # both sources, window from .env
    python report.py --hours 24       # override window
    python report.py --only topcorner # crowd/results only (no Betfair odds)
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter

import requests

import config
from betfair import scraper as betfair
from common import teams
from common.models import BetfairGame, CrowdGame
from reporting.writer import ReportWriter
from topcorner import scraper as topcorner
from weather.venues import load_venue_map, weather_for


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hours", type=int, default=config.WINDOW_HOURS,
                        help=f"Hours ahead for Betfair odds (default {config.WINDOW_HOURS}).")
    parser.add_argument("--only", choices=["betfair", "topcorner"],
                        help="Run a single source.")
    parser.add_argument("--md-dir", default=config.MD_DIR)
    parser.add_argument("--json-dir", default=config.JSON_DIR)
    parser.add_argument("--score-limit", type=int, default=config.CROWD_SCORE_LIMIT,
                        help="Max scorelines in the crowd distribution.")
    args = parser.parse_args(argv)

    betfair_games: list[BetfairGame] = []
    crowd_games: list[CrowdGame] = []

    if args.only != "topcorner":
        try:
            betfair_games = betfair.get_games(config.betfair_creds(), args.hours)
        except Exception as exc:  # noqa: BLE001 — report and continue
            print(f"[betfair] error: {exc}", file=sys.stderr)
    if args.only != "betfair":
        try:
            crowd_games = topcorner.get_all_games(
                config.topcorner_creds(),
                top_n=config.LEADERBOARD_TOP_N,
                throttle=config.TOPCORNER_THROTTLE,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[topcorner] error: {exc}", file=sys.stderr)

    crowd_by_key = {teams.match_key(cg.fixture.home, cg.fixture.away): cg
                    for cg in crowd_games}

    # My leaderboard rank (for the "predictions above you" section).
    my_rank = None
    if config.MY_USERNAME:
        for cg in crowd_games:
            for p in cg.predictions:
                if p.user_name.lower() == config.MY_USERNAME.lower() and p.rank:
                    my_rank = p.rank
                    break
            if my_rank:
                break

    # Decide which games to write: every in-window Betfair game (odds + crowd),
    # plus every played crowd game (so results get captured and frozen). The
    # filename is prefixed with the tournament game number for chronological sort.
    to_write: dict[str, tuple] = {}
    for bg in betfair_games:
        key = teams.match_key(bg.fixture.home, bg.fixture.away)
        cg = crowd_by_key.get(key)
        number = cg.number if cg else None
        slug = teams.numbered_slug(number, bg.fixture.home, bg.fixture.away)
        to_write[slug] = (number, bg.fixture.home, bg.fixture.away,
                          bg.fixture.kickoff, bg, cg)
    for cg in crowd_games:
        if not cg.played:
            continue
        slug = teams.numbered_slug(cg.number, cg.fixture.home, cg.fixture.away)
        if slug in to_write:
            continue
        to_write[slug] = (cg.number, cg.fixture.home, cg.fixture.away,
                          cg.fixture.kickoff, None, cg)

    venue_map = load_venue_map()
    weather_session = requests.Session()

    def weather_lookup(home, away, kickoff, number=None):
        return weather_for(home, away, kickoff, venue_map, weather_session, number)

    writer = ReportWriter(args.md_dir, args.json_dir, args.score_limit,
                          weather_lookup=weather_lookup,
                          my_username=config.MY_USERNAME, my_rank=my_rank,
                          top_dist_n=config.TOP_DIST_N)
    counts: Counter = Counter()
    for slug, (number, home, away, kickoff, bg, cg) in sorted(to_write.items()):
        status = writer.write(slug, number=number, home=home, away=away,
                              kickoff=kickoff, betfair=bg, crowd=cg)
        counts[status] += 1

    print(f"\nReports written to {args.md_dir}/ and {args.json_dir}/")
    print(f"  {counts['updated']} upcoming updated · "
          f"{counts['played']} newly frozen (played) · "
          f"{counts['frozen']} already-frozen skipped")
    if not to_write:
        print("  (nothing to write — no in-window Betfair games or played crowd games)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
