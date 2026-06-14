# topcorner — World Cup odds vs crowd report

Generates one report **per game** comparing two views of each World Cup match:

- **Betfair Exchange** — decimal match-odds (Home/Draw/Away) and correct-score
  odds (peer-to-peer prices, best available back price; 16 scorelines 0-0…3-3).
- **topcorner.org** — every leaderboard user's predicted scoreline, aggregated
  into a per-fixture distribution, plus the actual result once a game is played.
- **Weather at kickoff** — temperature, humidity, cloud cover and rain chance at
  the venue (via Open-Meteo, no API key), to gauge conditions for the players.

Each game produces a Markdown file (for reading) and a JSON file (for analysis).

## Layout

```
betfair/        Betfair Exchange API client (login → catalogue → marketbook)
topcorner/      topcorner.org client (login → leaderboard → per-user predictions + results)
common/         Shared models + team-name matching/slugs
reporting/      Per-game md + json writer (with freeze-on-played)
weather/        Open-Meteo client + host-city coords; venues.toml maps games→cities
config.py       Settings + credentials (from .env)
report.py       Orchestrates: fetch both sources, write per-game reports
reports/md/     Output: <home>_vs_<away>.md
reports/json/   Output: <home>_vs_<away>.json
```

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # then fill in credentials
```

**Secrets** go in `.env`:

- **Betfair**: `BETFAIR_USERNAME`, `BETFAIR_PASSWORD`, `BETFAIR_APP_KEY`.
  Create an app key (the free *delayed* key is fine) at
  <https://myaccount.betfair.com/accountdetails/mysecurity?showAPI=1>.
- **topcorner.org**: `TOPCORNER_USERNAME`, `TOPCORNER_PASSWORD`.

**Tunables** go in `settings.toml` (edit and re-run):

- `window_hours` (48) — hours ahead to pull Betfair odds.
- `leaderboard_top_n` (20) — only aggregate the top N leaderboard users into the
  crowd distribution; `0` = everyone. Fewer users = sharper signal + fewer requests.
- `crowd_score_limit` (19) — max scorelines shown before "+N others".
- `topcorner_throttle` (1.5) — min seconds between topcorner requests.
- `md_dir` / `json_dir` — output folders.

## Run

```bash
python report.py                  # both sources, window from .env
python report.py --hours 24       # override Betfair window
python report.py --only topcorner # crowd + results only (no Betfair odds)
```

## How it works

- **Betfair** odds are pulled for games kicking off in the next `WINDOW_HOURS`
  (the API only serves upcoming markets). Each such game gets/updates a report.
- **topcorner** is read each run: every fixture's crowd distribution, plus the
  actual score for finished games. One page per included leaderboard user
  (top `leaderboard_top_n`, or all), throttled `topcorner_throttle`s apart.
- **Weather** is fetched per game from Open-Meteo at the venue's coordinates and
  kickoff hour. `venues.toml` maps each matchup to one of the 16 host cities
  (in `weather/cities.py`); a blank mapping just omits the weather section.
- **Freeze:** once a game is played, its file is finalized with the actual
  score + accuracy analysis (exact-score and outcome hit-rates, whether the
  crowd/market favourite were right) and marked `frozen` — future runs skip it,
  preserving the last odds + weather captured before kickoff.
- Every file records `last_updated`.

## Notes

- Betfair uses the official Exchange API; the free delayed key is ~1 min delayed.
  Frozen "closing" odds are only as fresh as the last run before kickoff, so run
  the report reasonably close to kickoff for meaningful pre-match odds.
- Actual scores come from topcorner (Betfair drops markets once they start).
- Set `TOPCORNER_DUMP_HTML=1` to dump a sample user page if the site markup
  ever changes and the parser needs adjusting.
# topcorner
