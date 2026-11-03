"""Load football-data.co.uk league results, with bookmaker closing odds, into one table."""

from pathlib import Path

import numpy as np
import pandas as pd

RAW = Path(__file__).resolve().parent.parent / "data" / "raw" / "leagues"

COUNTRY = {"E0": "ENG", "SP1": "ESP", "D1": "GER", "I1": "ITA", "F1": "FRA"}

# Closing odds, best first. Pinnacle (PS) is the sharpest bookmaker; the market
# average (Avg) and Bet365 are fallbacks for seasons or matches where it is missing.
CLOSING = [("PSCH", "PSCD", "PSCA"), ("AvgCH", "AvgCD", "AvgCA"), ("B365CH", "B365CD", "B365CA")]


def read_csv(path):
    for encoding in ("utf-8-sig", "latin-1"):
        try:
            return pd.read_csv(path, encoding=encoding, on_bad_lines="skip")
        except UnicodeDecodeError:
            continue
    raise ValueError(f"Could not read {path}")


def parse_dates(column):
    """Dates are dd/mm/yy in older files and dd/mm/yyyy in newer ones."""
    long = pd.to_datetime(column, format="%d/%m/%Y", errors="coerce")
    short = pd.to_datetime(column, format="%d/%m/%y", errors="coerce")
    return long.fillna(short).dt.date


def closing_probabilities(frame):
    """Turn closing odds into probabilities, removing the bookmaker's margin."""
    odds = pd.DataFrame(np.nan, index=frame.index, columns=["H", "D", "A"])
    source = pd.Series(None, index=frame.index, dtype=object)
    for cols in CLOSING:
        if not set(cols) <= set(frame.columns):
            continue
        fill = odds["H"].isna() & frame[list(cols)].notna().all(axis=1)
        odds.loc[fill, ["H", "D", "A"]] = frame.loc[fill, list(cols)].to_numpy(dtype=float)
        source[fill] = cols[0][:-2]
    inverse = 1 / odds
    probs = inverse.div(inverse.sum(axis=1), axis=0)  # normalise: margin removed proportionally
    probs.columns = ["book_home", "book_draw", "book_away"]
    probs["book_source"] = source
    return probs


def load_leagues():
    frames = []
    for path in sorted(RAW.glob("*/*.csv")):
        frame = read_csv(path).dropna(subset=["HomeTeam", "AwayTeam", "FTHG", "FTAG"])
        frame = frame.reset_index(drop=True)
        table = pd.DataFrame({
            "competition": path.stem,
            "season": path.parent.name,
            "stage": "League",
            "knockout": False,
            "date": parse_dates(frame["Date"]),
            "home": frame["HomeTeam"].str.strip(),
            "home_country": COUNTRY[path.stem],
            "away": frame["AwayTeam"].str.strip(),
            "away_country": COUNTRY[path.stem],
            "home_goals": frame["FTHG"].astype(int),
            "away_goals": frame["FTAG"].astype(int),
        })
        frames.append(pd.concat([table, closing_probabilities(frame)], axis=1))
    return pd.concat(frames, ignore_index=True)


if __name__ == "__main__":
    leagues = load_leagues()
    print(leagues.groupby(["season", "competition"]).size().unstack())
    print("\nClosing odds source by season:")
    print(leagues.groupby("season").book_source.value_counts(dropna=False).unstack().fillna(0).astype(int))
    print(f"\n{leagues.date.isna().sum()} rows without a date")
