"""Read a season's Champions League knockout ties from Wikipedia.

scripts/download_data.py saves two articles in data/raw/wikipedia/: the knockout phase (play-offs,
round of 16, quarter-finals and semi-finals, each a "Sports series" table) and the final. A tie is
one row, written with the club that hosted the first leg first and its goals first in every score:

    |[[AS Monaco FC|Monaco]]|FRA|4–5|[[Paris Saint-Germain FC|Paris Saint-Germain]]|FRA|2–3|2–2
    |[[Galatasaray S.K. (football)|Galatasaray]]|TUR|7–5|[[Juventus FC|Juventus]]|ITA|5–2|2–3 (aet)

A leg not played yet is left empty (or the row is missing altogether). Wikipedia text is available
under CC BY-SA 4.0 (https://creativecommons.org/licenses/by-sa/4.0/).
"""

import json
import re
from pathlib import Path

import pandas as pd

from parse_league_phase import LINK, RAW, parse_team

ROUNDS = (("Playoffs", "Knockout phase play-offs"), ("Round of 16", "Round of 16"),
          ("Quarterfinals", "Quarter-finals"), ("Semifinals", "Semi-finals"))
SERIES = re.compile(r"\{\{#invoke:Sports series\|main(.*?)\n\}\}", re.S)
FINAL_BOX = re.compile(r"\{\{#invoke:football box\|main(.*?)\n\}\}", re.S | re.I)
INFOBOX = re.compile(r"\{\{Infobox football match(.*?)\n\}\}", re.S | re.I)  # how the article looks before the match
FIELD = re.compile(r"\n\s*\|\s*(\w+)[ \t]*=[ \t]*(.*?)(?=\n\s*\|\s*\w+[ \t]*=|\Z)", re.S)
START_DATE = re.compile(r"Start date\|(\d{4})\|(\d{1,2})\|(\d{1,2})")
SCORE = re.compile(r"^\s*(\d+)\s*[–−-]\s*(\d+)")
SHOOT_OUT = re.compile(r"(\d+)\s*[–−-]\s*(\d+)\s*(?:p\b|pen)", re.I)


def knockout_title(season):
    return f"{season[:4]}–{season[5:]}_UEFA_Champions_League_knockout_phase"


def final_title(season):
    return f"{int(season[:4]) + 1}_UEFA_Champions_League_final"


def knockout_path(season):
    return RAW / f"{season}-knockout-phase.json"


def final_path(season):
    return RAW / f"{season}-final.json"


def split_row(line):
    """The fields of one table row, which are separated by | but may hold links that contain one."""
    fields, depth, current = [], 0, ""
    for char in line:
        if char == "|" and depth == 0:
            fields.append(current)
            current = ""
            continue
        depth += {"[": 1, "]": -1}.get(char, 0)
        current += char
    fields.append(current)
    return [f.strip() for f in fields[1:]] if line.startswith("|") else []


def parse_leg(raw):
    """(goals of the club that hosted the first leg, goals of the other, extra time?, shoot-out), or None."""
    found = SCORE.match(raw or "")
    if not found:
        return None
    shoot = SHOOT_OUT.search(raw[found.end():])
    return {"goals": (int(found.group(1)), int(found.group(2))), "aet": bool(re.search(r"a\.?e\.?t", raw, re.I)),
            "pens": (int(shoot.group(1)), int(shoot.group(2))) if shoot else None}


def section(text, heading):
    found = re.search(rf"\n==\s*{re.escape(heading)}\s*==\n(.*?)(?=\n==[^=]|\Z)", text, re.S)
    return found.group(1) if found else ""


def parse_ties(text):
    """{round: [tie, ...]} for the rounds the article lists. A tie has team1 (the first-leg host) and
    team2 as (article, name shown), leg1 and leg2 as goals (team1 first) or None, whether extra time was
    played, and the shoot-out score if there was one."""
    found = {}
    for name, heading in ROUNDS:
        series = SERIES.search(section(text, heading))
        ties = []
        for line in (series.group(1).splitlines() if series else []):
            fields = split_row(line.strip())
            if len(fields) < 6 or not LINK.search(fields[0]):
                continue
            leg1, leg2 = parse_leg(fields[5]), parse_leg(fields[6] if len(fields) > 6 else "")
            page1, shown1, _ = parse_team(fields[0])
            page2, shown2, _ = parse_team(fields[3])
            played = [leg for leg in (leg1, leg2) if leg]
            ties.append({"round": name, "team1": (page1, shown1), "team2": (page2, shown2),
                         "leg1": leg1["goals"] if leg1 else None, "leg2": leg2["goals"] if leg2 else None,
                         "aet": any(leg["aet"] for leg in played), "pens": next((leg["pens"] for leg in played if leg["pens"]), None)})
        if ties:
            found[name] = ties
    return found


def parse_final(text):
    """The final: both clubs, and once played the score (after extra time), shoot-out and date."""
    box = FINAL_BOX.search(text) or INFOBOX.search(text)
    if not box:
        return None
    fields = dict(FIELD.findall(box.group(1)))
    if not (LINK.search(fields.get("team1", "")) and LINK.search(fields.get("team2", ""))):
        return None  # the finalists aren't known yet
    if "team1score" in fields:  # the infobox: the score and the shoot-out are in separate fields
        fields["score"] = f"{fields['team1score'].strip()}–{fields.get('team2score', '').strip()}"
        if fields.get("penalties1", "").strip().isdigit() and fields.get("penalties2", "").strip().isdigit():
            fields["penaltyscore"] = f"{fields['penalties1'].strip()}–{fields['penalties2'].strip()}"
    page1, shown1, _ = parse_team(fields["team1"])
    page2, shown2, _ = parse_team(fields["team2"])
    when = START_DATE.search(fields.get("date", ""))
    score = SCORE.match(re.sub(r"<[^>]*>|\{\{.*?\}\}|&nbsp;", "", fields.get("score", "")))
    shoot = SCORE.match(fields.get("penaltyscore", ""))
    return {"team1": (page1, shown1), "team2": (page2, shown2),
            "date": pd.Timestamp(int(when.group(1)), int(when.group(2)), int(when.group(3))) if when else None,
            "goals": (int(score.group(1)), int(score.group(2))) if score else None,
            "pens": (int(shoot.group(1)), int(shoot.group(2))) if shoot else None}


def load_knockouts(season):
    """{"ties": {round: [tie]}, "final": the final or None}, or None if the knockout article isn't downloaded."""
    if not knockout_path(season).exists():
        return None
    ties = parse_ties(json.loads(knockout_path(season).read_text(encoding="utf-8"))["parse"]["wikitext"])
    final = None
    if final_path(season).exists():
        final = parse_final(json.loads(final_path(season).read_text(encoding="utf-8"))["parse"]["wikitext"])
    return {"ties": ties, "final": final}


def tie_winner(tie):
    """1 if team1 went through, 2 if team2 did, None if the tie isn't over (or can't be told)."""
    if tie["leg2"] is None:
        return None
    one, two = tie["leg1"][0] + tie["leg2"][0], tie["leg1"][1] + tie["leg2"][1]
    if one != two:
        return 1 if one > two else 2
    if tie["pens"] and tie["pens"][0] != tie["pens"][1]:
        return 1 if tie["pens"][0] > tie["pens"][1] else 2
    return None


def final_winner(final):
    if not final or not final["goals"]:
        return None
    one, two = final["goals"]
    if one != two:
        return 1 if one > two else 2
    if final["pens"] and final["pens"][0] != final["pens"][1]:
        return 1 if final["pens"][0] > final["pens"][1] else 2
    return None


if __name__ == "__main__":
    import sys

    season = sys.argv[1] if len(sys.argv) > 1 else "2026-27"
    loaded = load_knockouts(season)
    if loaded is None:
        sys.exit(f"{knockout_path(season)} not found: run scripts/download_data.py")
    for name, ties in loaded["ties"].items():
        print(f"{name}: {len(ties)} ties, {sum(tie_winner(t) is not None for t in ties)} decided")
    print("final:", loaded["final"])
