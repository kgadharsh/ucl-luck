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
from pathlib import Path

RAW = Path(__file__).resolve().parent.parent / "data" / "raw"
FIRST_SEASON = 2011
LAST_SEASON = 2026  # 2026-27, the season in progress

# Big five leagues: England, Spain, Germany, Italy, France
LEAGUES = ["E0", "SP1", "D1", "I1", "F1"]
EUROPE = ["cl", "el"]  # Champions League, Europa League

PAUSE_SECONDS = 1  # be polite to free servers


def seasons():
    for year in range(FIRST_SEASON, LAST_SEASON + 1):
        yield year


def fetch(url, dest):
    if dest.exists():
        return "kept"
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            data = response.read()
    except urllib.error.HTTPError as err:
        return f"missing ({err.code})"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    time.sleep(PAUSE_SECONDS)
    return "downloaded"


def main(refresh_current=False):
    for year in seasons():
        code = f"{year % 100:02d}{(year + 1) % 100:02d}"  # 2011 -> "1112"
        name = f"{year}-{(year + 1) % 100:02d}"  # 2011 -> "2011-12"

        if refresh_current and year == LAST_SEASON:
            # The season in progress changes after every matchday, so fetch it again.
            for old in (RAW / "leagues" / name).glob("*.csv"):
                old.unlink()
            for old in (RAW / "europe" / name).glob("*.txt"):
                old.unlink()

        for league in LEAGUES:
            url = f"https://www.football-data.co.uk/mmz4281/{code}/{league}.csv"
            result = fetch(url, RAW / "leagues" / name / f"{league}.csv")
            print(f"{name} {league}: {result}")

        for comp in EUROPE:
            url = f"https://raw.githubusercontent.com/openfootball/champions-league/master/{name}/{comp}.txt"
            result = fetch(url, RAW / "europe" / name / f"{comp}.txt")
            print(f"{name} {comp}: {result}")


if __name__ == "__main__":
    import sys

    main(refresh_current="--refresh-current" in sys.argv)
