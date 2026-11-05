"""Read a season's Champions League league-phase fixtures and results from Wikipedia.

scripts/download_data.py saves the page's wikitext (through the MediaWiki API) in
data/raw/wikipedia/. Every match is a "Football box" under a "Matchday N" heading:

    {{#invoke:Football box|main
    | date  = {{Start date|2026|9|8}}
    | team1 = {{fbaicon|ENG}} [[Manchester City F.C.|Manchester City]]
    | score = 2–0
    | team2 = {{fbaicon|POR}} [[FC Porto|Porto]]
    }}

A match that has not been played has no score there. Wikipedia text is available under
CC BY-SA 4.0 (https://creativecommons.org/licenses/by-sa/4.0/).
"""

import json
import re
from pathlib import Path

import pandas as pd

RAW = Path(__file__).resolve().parent.parent / "data" / "raw" / "wikipedia"

MATCHDAY = re.compile(r"\n=+\s*Matchday (\d+)\s*=+\n")
BOX = re.compile(r"\{\{#invoke:Football box\|main(.*?)\n\}\}", re.S)
FIELD = re.compile(r"\n\s*\|\s*(\w+)[ \t]*=[ \t]*(.*?)(?=\n\s*\|\s*\w+[ \t]*=|\Z)", re.S)
START_DATE = re.compile(r"Start date\|(\d{4})\|(\d{1,2})\|(\d{1,2})")
COUNTRY = re.compile(r"\{\{fbaicon\|([A-Z]{3})\}\}")
LINK = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")
SCORE = re.compile(r"^(\d+)\s*[–−-]\s*(\d+)")

COLUMNS = ["matchday", "date", "home_page", "home", "home_country", "away_page", "away", "away_country",
           "home_goals", "away_goals"]


def season_title(season):
    """'2026-27' -> the Wikipedia article '2026–27_UEFA_Champions_League_league_phase'."""
    return f"{season[:4]}–{season[5:]}_UEFA_Champions_League_league_phase"


def data_path(season):
    return RAW / f"{season}-league-phase.json"


def parse_team(raw):
    """(article title, name as shown, three-letter country code) from a team field."""
    code = COUNTRY.search(raw)
    link = LINK.search(raw)
    if link:
        page, shown = link.group(1).strip(), (link.group(2) or link.group(1)).strip()
    else:
        page = shown = re.sub(r"\{\{.*?\}\}", "", raw).strip()
    return page, shown, code.group(1) if code else None


def parse_score(raw):
    """(home goals, away goals), or None for a match not played yet."""
    text = re.sub(r"<[^>]*>|\{\{.*?\}\}|&nbsp;", "", raw).strip()
    found = SCORE.match(text)
    return (int(found.group(1)), int(found.group(2))) if found else None


def parse_wikitext(text):
    """Every match in the article, in the order it is listed, as a table."""
    rows = []
    parts = MATCHDAY.split(text)  # [before, "1", section 1, "2", section 2, ...]
    for matchday, section in zip(parts[1::2], parts[2::2]):
        for box in BOX.findall(section):
            fields = dict(FIELD.findall(box))
            when = START_DATE.search(fields.get("date", ""))
            home_page, home, home_country = parse_team(fields["team1"])
            away_page, away, away_country = parse_team(fields["team2"])
            score = parse_score(fields.get("score", ""))
            rows.append({
                "matchday": int(matchday),
                "date": pd.Timestamp(int(when.group(1)), int(when.group(2)), int(when.group(3))) if when else pd.NaT,
                "home_page": home_page, "home": home, "home_country": home_country,
                "away_page": away_page, "away": away, "away_country": away_country,
                "home_goals": score[0] if score else None, "away_goals": score[1] if score else None})
    return pd.DataFrame(rows, columns=COLUMNS)


def load_league_phase(season, path=None):
    """The league phase of one season, or None if it hasn't been downloaded."""
    path = Path(path) if path else data_path(season)
    if not path.exists():
        return None
    return parse_wikitext(json.loads(path.read_text(encoding="utf-8"))["parse"]["wikitext"])


def check_league_phase(matches, teams=36, games=8):
    """Why this table is not a whole league phase (36 clubs, 8 matches each), or None if it is."""
    if len(matches) != teams * games // 2:
        return f"{len(matches)} matches listed, expected {teams * games // 2}"
    if matches[["date", "home", "away"]].isna().any().any():
        return "a match has no date or no club"
    clubs = pd.concat([matches.home_page, matches.away_page]).value_counts()
    if len(clubs) != teams or (clubs != games).any():
        return f"{len(clubs)} clubs, and not every one plays {games} matches"
    return None


if __name__ == "__main__":
    import sys

    season = sys.argv[1] if len(sys.argv) > 1 else "2026-27"
    league = load_league_phase(season)
    if league is None:
        sys.exit(f"{data_path(season)} not found: run scripts/download_data.py")
    played = league.home_goals.notna()
    print(f"{season}: {len(league)} matches, {played.sum()} played, {league.date.min():%d %b %Y} to {league.date.max():%d %b %Y}")
    print(check_league_phase(league) or "a whole league phase")
