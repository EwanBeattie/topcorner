"""Per-game report writer: one Markdown file (for reading) and one JSON file
(for analysis) per fixture.

Behaviour:
  - Upcoming games are (re)written each run with the latest odds + crowd.
  - When a game has been played, the file is finalized with the actual score
    and accuracy analysis, then FROZEN — subsequent runs skip it, preserving the
    last odds we saw and the result.
  - Every file records a `last_updated` timestamp.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from common.models import BetfairGame, CrowdGame

LONDON = ZoneInfo("Europe/London")
COMPETITION = "World Cup 2026"


# --- timestamps -----------------------------------------------------------
def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _display_dt(dt: datetime) -> str:
    local = dt.astimezone(LONDON)
    tzname = local.tzname() or "UTC"
    utc = dt.astimezone(timezone.utc)
    return f"{local:%a %d %b %Y, %H:%M} {tzname} ({utc:%H:%M} UTC)"


# --- JSON assembly --------------------------------------------------------
def _favourite_outcome(match_odds: dict) -> Optional[str]:
    pairs = [(o, k) for k, o in
             (("HOME", match_odds.get("home")),
              ("DRAW", match_odds.get("draw")),
              ("AWAY", match_odds.get("away"))) if o]
    return min(pairs)[1] if pairs else None


def _betfair_section(betfair: Optional[BetfairGame], prev: Optional[dict]) -> Optional[dict]:
    if betfair is not None:
        mo = betfair.match_odds
        scores = [{"score": s, "odds": o} for s, o in betfair.correct_score.items()]
        # Most likely first: lowest odds first, missing prices last.
        scores.sort(key=lambda x: (x["odds"] is None, x["odds"] or 0))
        return {
            "match_odds": {"home": mo.home, "draw": mo.draw, "away": mo.away},
            "correct_score": scores,
        }
    # No fresh odds this run — carry over the last odds we captured.
    if prev and prev.get("betfair"):
        return prev["betfair"]
    return None


def _dist_from_preds(preds: list, limit: int) -> Optional[dict]:
    """Build a distribution block from a list of UserPredictions."""
    from collections import Counter
    if not preds:
        return None
    scores = Counter(p.score for p in preds).most_common()
    outcome = Counter(p.outcome for p in preds)
    return {
        "n": len(preds),
        "outcome": {k: outcome.get(k, 0) for k in ("HOME", "DRAW", "AWAY")},
        "scores": [{"score": s, "count": c} for s, c in scores[:limit]],
        "others_count": sum(c for _, c in scores[limit:]),
    }


def _crowd_section(crowd: Optional[CrowdGame], limit: int) -> Optional[dict]:
    if crowd is None or crowd.n == 0:
        return None
    return _dist_from_preds(crowd.predictions, limit)


def _above_me_section(crowd: Optional[CrowdGame], my_username: str,
                      my_rank: Optional[int], minimum: int = 10) -> Optional[dict]:
    """Predicted scores of players ranked above me who predicted this game.

    Always show at least `minimum` players: if fewer than that are above me,
    pad with the nearest players below (so rank 1 shows the 10 just below).
    """
    if not crowd or not my_username or not my_rank:
        return None
    ranked = [p for p in crowd.predictions if p.rank]
    above = sorted((p for p in ranked if p.rank < my_rank), key=lambda p: p.rank)
    below = sorted((p for p in ranked if p.rank > my_rank), key=lambda p: p.rank)
    selected = list(above)
    if len(selected) < minimum:
        selected += below[:minimum - len(selected)]
    return {
        "username": my_username,
        "my_rank": my_rank,
        "n_above": len(above),
        "predictions": [{"rank": p.rank, "user": p.user_name, "score": p.score}
                        for p in selected],
    }


def _analysis_section(crowd: Optional[CrowdGame], match_odds: dict) -> dict:
    fav = _favourite_outcome(match_odds)
    out: dict = {
        "crowd_modal_score": None,
        "crowd_modal_outcome": None,
        "market_favourite_outcome": fav,
        "exact_correct": None,
        "exact_correct_pct": None,
        "outcome_correct": None,
        "outcome_correct_pct": None,
    }
    if crowd and crowd.n:
        modal = crowd.modal_score()
        out["crowd_modal_score"] = modal[0] if modal else None
        oc = crowd.outcome_distribution().most_common(1)
        out["crowd_modal_outcome"] = oc[0][0] if oc else None

    if crowd and crowd.played and crowd.final_score and crowd.n:
        exact = crowd.exact_correct()
        outcome = crowd.outcome_correct()
        out["exact_correct"] = exact
        out["exact_correct_pct"] = round(exact / crowd.n, 3)
        out["outcome_correct"] = outcome
        out["outcome_correct_pct"] = round(outcome / crowd.n, 3)
        out["crowd_modal_score_correct"] = out["crowd_modal_score"] == crowd.final_score
        out["crowd_modal_outcome_correct"] = (
            out["crowd_modal_outcome"] == crowd.final_outcome
        )
        out["market_favourite_correct"] = (
            fav == crowd.final_outcome if fav else None
        )
    return out


def build_game_json(
    home: str,
    away: str,
    kickoff: datetime,
    betfair: Optional[BetfairGame],
    crowd: Optional[CrowdGame],
    prev: Optional[dict],
    score_limit: int = 19,
    number: Optional[int] = None,
    weather: Optional[dict] = None,
    my_username: str = "",
    my_rank: Optional[int] = None,
    top_dist_n: int = 20,
) -> dict:
    played = bool(crowd and crowd.played and crowd.final_score)
    top_preds = ([p for p in crowd.predictions if p.rank and p.rank <= top_dist_n]
                 if crowd else [])
    bf = _betfair_section(betfair, prev)
    match_odds = (bf or {}).get("match_odds", {}) if bf else {}
    # Keep the last weather we fetched if none this run (e.g. no venue / API down).
    if weather is None and prev:
        weather = prev.get("weather")

    result = {"home_goals": None, "away_goals": None, "outcome": None}
    if played:
        result = {
            "home_goals": crowd.final_home,
            "away_goals": crowd.final_away,
            "outcome": crowd.final_outcome,
        }

    return {
        "number": number,
        "match": f"{home} vs {away}",
        "home": home,
        "away": away,
        "competition": COMPETITION,
        "kickoff_utc": _iso(kickoff),
        "status": "played" if played else "upcoming",
        "frozen": played,
        "last_updated_utc": _iso(_now_utc()),
        "weather": weather,
        "result": result,
        "betfair": bf,
        "crowd": _crowd_section(crowd, score_limit),
        "crowd_top": _dist_from_preds(top_preds, score_limit),
        "top_dist_n": top_dist_n,
        "above_me": _above_me_section(crowd, my_username, my_rank),
        "analysis": _analysis_section(crowd, match_odds),
    }


# --- Markdown rendering ---------------------------------------------------
def _implied(odds) -> str:
    return f"{1 / odds:.1%}" if odds else "—"


def _odds(odds) -> str:
    return f"{odds:.2f}" if odds else "—"


def _md_table(headers: list[str], rows: list[list[str]], aligns: list[str]) -> list[str]:
    """Build a padded Markdown table so the raw source lines up as a grid too.

    `aligns` is one of 'l'/'r' per column (controls both padding and the
    separator-row colon). Returns the table as a list of lines.
    """
    widths = [max(3, len(h)) for h in headers]
    for row in rows:
        for c, cell in enumerate(row):
            widths[c] = max(widths[c], len(cell))

    def pad(cell: str, c: int) -> str:
        return cell.rjust(widths[c]) if aligns[c] == "r" else cell.ljust(widths[c])

    def sep(c: int) -> str:
        return "-" * (widths[c] - 1) + ":" if aligns[c] == "r" else "-" * widths[c]

    out = ["| " + " | ".join(pad(h, c) for c, h in enumerate(headers)) + " |",
           "| " + " | ".join(sep(c) for c in range(len(headers))) + " |"]
    out += ["| " + " | ".join(pad(cell, c) for c, cell in enumerate(row)) + " |"
            for row in rows]
    return out


def _weather_lines(w: Optional[dict]) -> list[str]:
    """Render the 'Weather at kickoff' section, or nothing if unavailable."""
    if not w:
        return []
    cond = f"{w.get('emoji', '')} {w.get('summary', '—')}".strip()
    temp, feels = w.get("temp_c"), w.get("feels_c")
    if temp is not None:
        cond += f" — {round(temp)} °C"
        if feels is not None:
            cond += f" (feels {round(feels)} °C)"

    hum = w.get("humidity_pct")
    cloud = w.get("cloud_pct")
    L = [
        "## Weather at kickoff",
        "",
        f"- **Venue:** {w.get('venue', '—')}",
        f"- **Conditions:** {cond}",
        f"- **Humidity:** {hum if hum is not None else '—'}%  ·  "
        f"**Cloud cover:** {cloud if cloud is not None else '—'}%",
    ]
    pp = w.get("precip_prob_pct")
    if pp is not None:
        L.append(f"- **Rain:** {pp}% chance")

    when = w.get("local_time")
    try:
        when = datetime.fromisoformat(w["local_time"]).strftime("%a %d %b, %H:%M")
    except (ValueError, KeyError, TypeError):
        pass
    label = "Forecast for" if w.get("source") == "forecast" else "Observed at"
    L += [f"- _{label} {when} local time_", ""]
    return L


def _dist_lines(title: str, dist: Optional[dict], home: str, away: str,
                played: bool, final_score: Optional[str]) -> list[str]:
    """Render one crowd distribution block (heading, split, modal, bar table)."""
    n = dist["n"] if dist else 0
    L = [f"## {title} — {n} predictions", ""]
    if not dist:
        return L + ["_No predictions._", ""]
    oc = dist["outcome"]
    split = (f"{home} {oc['HOME'] / n:.0%} · Draw {oc['DRAW'] / n:.0%} · "
             f"{away} {oc['AWAY'] / n:.0%}")
    L.append(f"- **Outcome split:** {split}")
    modal = dist["scores"][0] if dist["scores"] else None
    if modal:
        L.append(f"- **Most predicted score:** {modal['score']} "
                 f"({modal['count'] / n:.0%})")
    rows = []
    for s in dist["scores"]:
        mark = " ✅" if played and s["score"] == final_score else ""
        pct = s["count"] / n
        rows.append([f"{s['score']}{mark}", str(s["count"]), f"{pct:.0%}",
                     "█" * round(pct * 20)])
    if dist["others_count"]:
        rows.append([f"+{dist['others_count']} others", str(dist["others_count"]),
                     f"{dist['others_count'] / n:.0%}", ""])
    return L + [""] + _md_table(["Score", "Guesses", "Share", ""], rows,
                                ["l", "r", "r", "l"]) + [""]


def _above_me_lines(am: Optional[dict], played: bool,
                    final_score: Optional[str]) -> list[str]:
    """Render the predicted scores of players ranked above me."""
    if not am:
        return []
    preds = am["predictions"]
    my_rank = am["my_rank"]
    n_above = am.get("n_above", len(preds))
    padded = n_above < len(preds)
    title = "Predictions from players near you" if padded else "Predictions from above you"
    L = [f"## {title} — {am['username']}, rank {my_rank}", ""]
    if not preds:
        return L + ["_Nobody above you, or none have predicted this game._", ""]
    if padded:
        L += [f"_Only {n_above} above you predicted this game, so the nearest "
              f"players below are included._", ""]
    rows, marker_done = [], False
    for p in preds:
        if not marker_done and p["rank"] > my_rank:
            rows.append(["—", f"⟵ you ({am['username']})", "—"])
            marker_done = True
        mark = " ✅" if played and p["score"] == final_score else ""
        rows.append([str(p["rank"]), p["user"], f"{p['score']}{mark}"])
    return L + _md_table(["Rank", "Player", "Predicted"], rows,
                         ["r", "l", "l"]) + [""]


def render_markdown(d: dict) -> str:
    home, away = d["home"], d["away"]
    kickoff = datetime.fromisoformat(d["kickoff_utc"].replace("Z", "+00:00"))
    updated = datetime.fromisoformat(d["last_updated_utc"].replace("Z", "+00:00"))
    played = d["status"] == "played"
    badge = "✅ PLAYED — _frozen_" if played else "⚪ UPCOMING"

    num = d.get("number")
    L = [
        f"# {home} vs {away}",
        "",
        *( [f"- **Game #:** {num}"] if num else [] ),
        f"- **Competition:** {d['competition']} — Group Stage",
        f"- **Kickoff:** {_display_dt(kickoff)}",
        f"- **Status:** {badge}",
        f"- **Last updated:** {updated.astimezone(LONDON):%a %d %b %Y, %H:%M} "
        f"{updated.astimezone(LONDON).tzname() or 'UTC'}",
        "",
    ]
    L += _weather_lines(d.get("weather"))
    L += ["## Result", ""]
    final_score = None
    if played:
        r = d["result"]
        final_score = f"{r['home_goals']}-{r['away_goals']}"
        winner = {"HOME": home, "AWAY": away, "DRAW": "Draw"}[r["outcome"]]
        L += [f"- **Final score:** {r['home_goals']} – {r['away_goals']}",
              f"- **Outcome:** {winner} ({r['outcome']})", ""]
    else:
        L += ["_Not yet played._", ""]

    bf = d.get("betfair")
    L += ["## Betfair Exchange — Match Odds (decimal)", ""]
    if bf and bf.get("match_odds"):
        mo = bf["match_odds"]
        rows = [[home, _odds(mo["home"]), _implied(mo["home"])],
                ["Draw", _odds(mo["draw"]), _implied(mo["draw"])],
                [away, _odds(mo["away"]), _implied(mo["away"])]]
        L += _md_table(["Outcome", "Odds", "Implied"], rows, ["l", "r", "r"]) + [""]
    else:
        L += ["_No Betfair odds captured._", ""]

    L += ["## Betfair Exchange — Correct Score (decimal)", ""]
    if bf and bf.get("correct_score"):
        L += ["Most-likely first." + (" ✅ marks the score that occurred."
                                      if played else ""), ""]
        rows = []
        for row in bf["correct_score"]:
            mark = " ✅" if played and row["score"] == final_score else ""
            rows.append([f"{row['score']}{mark}", _odds(row["odds"]),
                         _implied(row["odds"])])
        L += _md_table(["Score", "Odds", "Implied"], rows, ["l", "r", "r"]) + [""]
    else:
        L += ["_No Betfair odds captured._", ""]

    L += _dist_lines("Maggots", d.get("crowd"), home, away, played, final_score)
    top_n = d.get("top_dist_n", 20)
    L += _dist_lines(f"Top {top_n}", d.get("crowd_top"),
                     home, away, played, final_score)
    L += _above_me_lines(d.get("above_me"), played, final_score)

    L += ["## Analysis", ""]
    a = d["analysis"]
    if played and a.get("exact_correct") is not None:
        n = (d.get("crowd") or {}).get("n", 0)
        fav = a.get("market_favourite_outcome")
        if fav is None:
            fav_line = "- **Market favourite:** — (no odds captured)"
        else:
            fav_line = (f"- **Market favourite:** {fav} — "
                        f"{'✅ correct' if a.get('market_favourite_correct') else '❌ wrong'}")
        L += [
            f"- **Actual score:** {final_score} ({d['result']['outcome']})",
            f"- **Exact score correctly predicted by:** {a['exact_correct']} / {n} "
            f"({a['exact_correct_pct']:.0%})",
            f"- **Outcome correctly predicted by:** {a['outcome_correct']} / {n} "
            f"({a['outcome_correct_pct']:.0%})",
            f"- **Crowd modal score:** {a['crowd_modal_score']} — "
            f"{'✅ right' if a.get('crowd_modal_score_correct') else '❌ wrong'}",
            f"- **Crowd modal outcome:** {a['crowd_modal_outcome']} — "
            f"{'✅ right' if a.get('crowd_modal_outcome_correct') else '❌ wrong'}",
            fav_line,
        ]
    else:
        fav = a.get("market_favourite_outcome")
        L += ["_Filled once the game has been played._", "",
              f"- Crowd modal score: {a.get('crowd_modal_score') or '—'}",
              f"- Crowd modal outcome: {a.get('crowd_modal_outcome') or '—'}",
              f"- Market favourite: {fav or '—'}"]
    L.append("")
    return "\n".join(L)


# --- writer ---------------------------------------------------------------
class ReportWriter:
    def __init__(self, md_dir: str, json_dir: str, score_limit: int = 19,
                 weather_lookup=None, my_username: str = "",
                 my_rank: Optional[int] = None, top_dist_n: int = 20):
        self.md_dir = md_dir
        self.json_dir = json_dir
        self.score_limit = score_limit
        # Optional callable (home, away, kickoff) -> weather dict | None.
        self.weather_lookup = weather_lookup
        self.my_username = my_username
        self.my_rank = my_rank
        self.top_dist_n = top_dist_n
        os.makedirs(md_dir, exist_ok=True)
        os.makedirs(json_dir, exist_ok=True)

    def _json_path(self, slug: str) -> str:
        return os.path.join(self.json_dir, f"{slug}.json")

    def _md_path(self, slug: str) -> str:
        return os.path.join(self.md_dir, f"{slug}.md")

    def _load_prev(self, slug: str) -> Optional[dict]:
        path = self._json_path(slug)
        if not os.path.exists(path):
            return None
        try:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, json.JSONDecodeError):
            return None

    def write(self, slug: str, *, home: str, away: str, kickoff: datetime,
              betfair: Optional[BetfairGame], crowd: Optional[CrowdGame],
              number: Optional[int] = None) -> str:
        """Write md+json for one game. Returns 'frozen' | 'played' | 'updated'."""
        prev = self._load_prev(slug)
        if prev and prev.get("frozen"):
            return "frozen"  # already finalized — leave it untouched

        weather = None
        if self.weather_lookup is not None:
            weather = self.weather_lookup(home, away, kickoff)

        data = build_game_json(home, away, kickoff, betfair, crowd, prev,
                               score_limit=self.score_limit, number=number,
                               weather=weather, my_username=self.my_username,
                               my_rank=self.my_rank, top_dist_n=self.top_dist_n)

        with open(self._json_path(slug), "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        with open(self._md_path(slug), "w", encoding="utf-8") as fh:
            fh.write(render_markdown(data))

        return "played" if data["frozen"] else "updated"
