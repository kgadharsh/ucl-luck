"""Download raw results into data/raw/.

League results with bookmaker odds come from football-data.co.uk, and
Champions League and Europa League results come from openfootball.
Files already on disk are skipped, so it is safe to run again.

The league phase of the season in progress (fixtures and results, for src/forecast.py) comes from
Wikipedia's API; its text is available under CC BY-SA 4.0.

Transfermarkt's open dataset (starting elevens and player market values, CC0 on GitHub) is only
needed for src/real_madrid_squad.py and is about 135 MB, so it is fetched only on request.

Usage:
    python scripts/download_data.py                    # everything not yet on disk
    python scripts/download_data.py --refresh-current  # also re-fetch the season in progress
    python scripts/download_data.py --transfermarkt    # also the Transfermarkt files
"""

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

RAW = Path(__file__).resolve().parent.parent / "data" / "raw"
FIRST_SEASON = 2011


def current_season(today=None):
    """First year of the season in progress: 2026 (for 2026-27) from July 2026 to June 2027."""
    today = today or date.today()
    return today.year if today.month >= 7 else today.year - 1


LAST_SEASON = current_season()

# Big five leagues: England, Spain, Germany, Italy, France
LEAGUES = ["E0", "SP1", "D1", "I1", "F1"]
EUROPE = ["cl", "el"]  # Champions League, Europa League

PAUSE_SECONDS = 1  # be polite to free servers

# https://github.com/dcaribou/transfermarkt-datasets (its updates have been paused since July 2026,
# which doesn't matter for seasons that are over)
TRANSFERMARKT = "https://pub-e682421888d945d684bcae8890b0ec20.r2.dev/data/"
TRANSFERMARKT_FILES = ["competitions", "games", "game_lineups", "player_valuations"]

# Wikipedia asks API users to say who they are.
WIKIPEDIA = "https://en.wikipedia.org/w/api.php"
WIKIPEDIA_HEADERS = {"User-Agent": "ucl-luck/1.0 (https://github.com/kgadharsh/ucl-luck)"}


def seasons():
    for year in range(FIRST_SEASON, LAST_SEASON + 1):
        yield year


def fetch(url, dest, refresh=False, timeout=30, headers=None, valid=None):
    """Download url to dest. A failed download never removes a copy already on disk:
    the old file stays until a new one has arrived in full. If given, valid(data) says
    whether what arrived is usable (an error message with a 200 status is not)."""
    if dest.exists() and not refresh:
        return "kept"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers or {}), timeout=timeout) as response:
            data = response.read()
        if valid and not valid(data):
            raise ValueError("not what was asked for")
    except (urllib.error.URLError, TimeoutError, ValueError) as err:
        reason = err.code if isinstance(err, urllib.error.HTTPError) else err
        return f"kept old copy, fetch failed ({reason})" if dest.exists() else f"missing ({reason})"
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_suffix(dest.suffix + ".part")
    partial.write_bytes(data)
    partial.replace(dest)
    time.sleep(PAUSE_SECONDS)
    return "refreshed" if refresh else "downloaded"


def transfermarkt():
    for name in TRANSFERMARKT_FILES:
        result = fetch(f"{TRANSFERMARKT}{name}.csv.gz", RAW / "transfermarkt" / f"{name}.csv.gz", timeout=600)
        print(f"transfermarkt {name}: {result}")


def wikipedia_article(title, dest, refresh=False):
    """One article's wikitext, saved as the API sends it."""
    query = urllib.parse.urlencode({"action": "parse", "page": title, "prop": "wikitext", "format": "json",
                                    "formatversion": 2, "redirects": 1})

    def has_text(data):  # a page that doesn't exist (yet) comes back as {"error": ...}
        return "wikitext" in json.loads(data).get("parse", {})

    return fetch(f"{WIKIPEDIA}?{query}", dest, refresh, headers=WIKIPEDIA_HEADERS, valid=has_text)


def league_phase(year, refresh=False):
    """Wikipedia's article on the league phase of the season starting in `year`."""
    season = f"{year}-{(year + 1) % 100:02d}"
    return wikipedia_article(f"{year}\u2013{(year + 1) % 100:02d}_UEFA_Champions_League_league_phase",
                             RAW / "wikipedia" / f"{season}-league-phase.json", refresh)


def knockout_phase(year, refresh=False):
    """The articles on the knockout phase and the final, which exist from the play-off draw on."""
    season = f"{year}-{(year + 1) % 100:02d}"
    return {"knockout phase": wikipedia_article(f"{year}\u2013{(year + 1) % 100:02d}_UEFA_Champions_League_knockout_phase",
                                                 RAW / "wikipedia" / f"{season}-knockout-phase.json", refresh),
            "final": wikipedia_article(f"{year + 1}_UEFA_Champions_League_final",
                                       RAW / "wikipedia" / f"{season}-final.json", refresh)}


def main(refresh_current=False, with_transfermarkt=False):
    if with_transfermarkt:
        transfermarkt()
    for year in seasons():
        code = f"{year % 100:02d}{(year + 1) % 100:02d}"  # 2011 -> "1112"
        name = f"{year}-{(year + 1) % 100:02d}"  # 2011 -> "2011-12"

        # The season in progress changes after every matchday, so fetch it again.
        refresh = refresh_current and year == LAST_SEASON

        for league in LEAGUES:
            url = f"https://www.football-data.co.uk/mmz4281/{code}/{league}.csv"
            result = fetch(url, RAW / "leagues" / name / f"{league}.csv", refresh)
            print(f"{name} {league}: {result}")

        for comp in EUROPE:
            url = f"https://raw.githubusercontent.com/openfootball/champions-league/master/{name}/{comp}.txt"
            result = fetch(url, RAW / "europe" / name / f"{comp}.txt", refresh)
            print(f"{name} {comp}: {result}")

    # Only the season in progress: it is the one the forecast is about.
    print(f"{LAST_SEASON}-{(LAST_SEASON + 1) % 100:02d} league phase (Wikipedia): "
          f"{league_phase(LAST_SEASON, refresh=refresh_current)}")
    for name, result in knockout_phase(LAST_SEASON, refresh=refresh_current).items():
        print(f"{LAST_SEASON}-{(LAST_SEASON + 1) % 100:02d} {name} (Wikipedia): {result}")


if __name__ == "__main__":
    import sys

    main(refresh_current="--refresh-current" in sys.argv, with_transfermarkt="--transfermarkt" in sys.argv)
