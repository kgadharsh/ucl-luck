"""Parse openfootball Champions League and Europa League text files into one table.

Each match line looks like one of these:
    20:45  Manchester City (ENG)   v SSC Napoli (ITA)         1-1 (0-0)
           Liverpool FC (ENG)      v Paris Saint-Germain FC (FRA)  1-4 pen. 0-1 a.e.t. (0-1, 0-1)
Date lines ("Tue Sep 27", "Wed Sep 14 2011") and stage lines ("▪ Round of 16") set context
for the matches that follow them.
"""

import re
from datetime import date
from pathlib import Path

import pandas as pd

RAW = Path(__file__).resolve().parent.parent / "data" / "raw" / "europe"

MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], start=1)}

DATE_LINE = re.compile(r"^\s*(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+(\w{3})\s+(\d{1,2})(?:\s+(\d{4}))?\s*$")
MATCH_LINE = re.compile(
    r"^\s*(?:\d{1,2}[:.]\d{2}\s+)?"
    r"(?P<home>.+?\([A-Z]{3}\))\s+v\s+(?P<away>.+?\([A-Z]{3}\))\s+"
    r"(?P<score>\d+-\d+.*?)\s*$")
TEAM = re.compile(r"^(?P<name>.+?)\s*\((?P<country>[A-Z]{3})\)$")
PENS = re.compile(r"(\d+)-(\d+)\s+pen\.")
AET = re.compile(r"(\d+)-(\d+)\s+a\.e\.t\.")
FIRST_SCORE = re.compile(r"^(\d+)-(\d+)")
BRACKETS = re.compile(r"\(([^)]*)\)")

# Stages that are knockout rounds (English and the German names some files use)
KNOCKOUT = re.compile(
    r"round of (16|32)|quarter|semi|final|play-?off|knockout|"
    r"sechzehntel|achtel|viertel|halbfinale|finale",
    re.IGNORECASE)


# The 2019-20 competitions were suspended in March 2020 and finished in August 2020: the last
# round-of-16 second legs and the single-match quarter-finals, semi-finals and final. Those
# August dates belong to the season's second year, unlike every other season's July to December.
FINISHED_LATE = {"2019-20": (7, 8)}


def season_year(name, month):
    """Matches from July to December belong to the season's first year, except a season that
    finished late."""
    first = int(name[:4])
    if month in FINISHED_LATE.get(name, ()):
        return first + 1
    return first if month >= 7 else first + 1


def parse_score(text):
    """Return (home 90 min, away 90 min, extra time?, home pens, away pens)."""
    pens = PENS.search(text)
    aet = AET.search(text)
    if aet:
        # After extra time, the first score in brackets is the 90-minute score.
        inside = BRACKETS.search(text[aet.end():])
        first = FIRST_SCORE.match(inside.group(1).strip()) if inside else None
        home90, away90 = (int(first.group(1)), int(first.group(2))) if first else (None, None)
    else:
        first = FIRST_SCORE.match(text)
        home90, away90 = int(first.group(1)), int(first.group(2))
    return (home90, away90, bool(aet),
            int(pens.group(1)) if pens else None,
            int(pens.group(2)) if pens else None,
            (int(aet.group(1)), int(aet.group(2))) if aet else None)


def parse_file(path, competition, season):
    rows, unparsed = [], []
    stage, day = None, None
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith(("=", "#")):
            continue
        if line.lstrip().startswith("▪"):
            stage = line.lstrip("▪ ").strip()
            continue
        found = DATE_LINE.match(line)
        if found:
            month = MONTHS[found.group(1)]
            year = int(found.group(3)) if found.group(3) else season_year(season, month)
            day = date(year, month, int(found.group(2)))
            continue
        found = MATCH_LINE.match(line)
        if not found:
            unparsed.append(line.strip())
            continue
        home, away = TEAM.match(found.group("home").strip()), TEAM.match(found.group("away").strip())
        home90, away90, extra, home_pens, away_pens, after_et = parse_score(found.group("score"))
        rows.append({
            "competition": competition,
            "season": season,
            "stage": stage,
            "knockout": bool(stage and KNOCKOUT.search(stage)),
            "date": day,
            "home": home.group("name"),
            "home_country": home.group("country"),
            "away": away.group("name"),
            "away_country": away.group("country"),
            "home_goals": home90,
            "away_goals": away90,
            "extra_time": extra,
            "home_goals_aet": after_et[0] if after_et else None,
            "away_goals_aet": after_et[1] if after_et else None,
            "home_pens": home_pens,
            "away_pens": away_pens,
            "raw_score": found.group("score"),
        })
    return rows, unparsed


def load_europe():
    rows, unparsed = [], []
    for path in sorted(RAW.glob("*/*.txt")):
        competition = path.stem.upper()  # "CL" or "EL"
        found, missed = parse_file(path, competition, path.parent.name)
        rows += found
        unparsed += [f"{path.parent.name}/{path.name}: {line}" for line in missed]
    return pd.DataFrame(rows), unparsed


if __name__ == "__main__":
    matches, unparsed = load_europe()
    print(matches.groupby(["season", "competition"]).size().unstack())
    print(f"\n{len(matches)} matches, {matches.knockout.sum()} in knockout rounds")
    print(f"{len(unparsed)} lines not parsed")
    for line in unparsed[:30]:
        print("  ", line)
