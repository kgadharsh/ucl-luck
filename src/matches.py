"""All matches (big-five leagues, Champions League, Europa League) in one table,
with one name per club so ratings carry over between competitions."""

from pathlib import Path

import pandas as pd

from parse_europe import load_europe
from parse_leagues import load_leagues

NAMES = Path(__file__).resolve().parent.parent / "data" / "team_names.csv"


def canonical_names(europe):
    """Map European names onto league names (or a shared alias); keep the rest with their country."""
    table = pd.read_csv(NAMES)
    lookup = {(row.european_name, row.country): row.canonical for row in table.itertuples()}
    for side in ("home", "away"):
        keys = zip(europe[side], europe[f"{side}_country"])
        europe[side] = [lookup.get(key, f"{key[0]} ({key[1]})") for key in keys]
    return europe


def load_matches():
    europe, _ = load_europe()
    europe = canonical_names(europe)
    # Newer files say "Finals, Quarterfinals"; older ones say "Quarterfinals".
    europe["round"] = (europe["stage"].fillna("")
                       .str.replace(r"^Finals, ", "", regex=True)
                       .str.replace(r"^Playoffs, Matchday \d+$", "Playoffs", regex=True))
    # The final is at a neutral ground; in 2019-20 the quarter- and semi-finals were
    # single matches in Lisbon because of COVID.
    lisbon = (europe["season"] == "2019-20") & europe["round"].isin(["Quarterfinals", "Semifinals"])
    europe["neutral"] = (europe["round"] == "Final") | lisbon
    leagues = load_leagues()
    leagues["neutral"] = False
    matches = pd.concat([leagues, europe], ignore_index=True)
    matches["date"] = pd.to_datetime(matches["date"])
    matches = matches.dropna(subset=["home_goals", "away_goals"])
    matches[["home_goals", "away_goals"]] = matches[["home_goals", "away_goals"]].astype(int)
    return matches.sort_values("date", kind="stable").reset_index(drop=True)


if __name__ == "__main__":
    matches = load_matches()
    league_teams = set(matches.loc[~matches.competition.isin(["CL", "EL"]), "home"])
    europe = matches[matches.competition.isin(["CL", "EL"])]
    big_five = {"ENG", "ESP", "GER", "ITA", "FRA"}
    unmatched = sorted({
        team for side in ("home", "away")
        for team, country in zip(europe[side], europe[f"{side}_country"])
        if country in big_five and team not in league_teams})
    print(f"{len(matches)} matches from {matches.date.min():%d %b %Y} to {matches.date.max():%d %b %Y}")
    print(f"Big-five European names not found in league data: {unmatched or 'none'}")
