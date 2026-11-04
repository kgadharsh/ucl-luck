"""Download raw results into data/raw/.

League results with bookmaker odds come from football-data.co.uk, and
Champions League and Europa League results come from openfootball.
Files already on disk are skipped, so it is safe to run again.

Usage:
    python scripts/download_data.py                    # everything not yet on disk
    python scripts/download_data.py --refresh-current  # also re-fetch the season in progress
"""

import time
import urllib.error
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


def seasons():
    for year in range(FIRST_SEASON, LAST_SEASON + 1):
        yield year


def fetch(url, dest, refresh=False):
    """Download url to dest. A failed download never removes a copy already on disk:
    the old file stays until a new one has arrived in full."""
    if dest.exists() and not refresh:
        return "kept"
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            data = response.read()
    except (urllib.error.URLError, TimeoutError) as err:
        reason = err.code if isinstance(err, urllib.error.HTTPError) else err
        return f"kept old copy, fetch failed ({reason})" if dest.exists() else f"missing ({reason})"
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_suffix(dest.suffix + ".part")
    partial.write_bytes(data)
    partial.replace(dest)
    time.sleep(PAUSE_SECONDS)
    return "refreshed" if refresh else "downloaded"


def main(refresh_current=False):
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


if __name__ == "__main__":
    import sys

    main(refresh_current="--refresh-current" in sys.argv)
