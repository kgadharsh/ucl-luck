"""Collect everything the dashboard shows into site/data.json.

Run after evaluate_elo.py, evaluate_dc.py, knockouts.py and (optionally) update.py and forecast.py.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from brackets import build_brackets
from dixon_coles import outcome_probs, walk_forward_goals
from elo import run_elo
from evaluate_dc import ELO_SETTINGS
from evaluate_elo import TUNE, WARM_UP, walk_forward_probs
from knockouts import LAST_AWAY_GOALS_SEASON, ROUNDS, actual_winner, tie_scores
from matches import load_matches
from outcomes import outcome_codes
from preview import write_preview
from replays import season_replays

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"
SITE = ROOT / "site"
# The week 1-2 evaluation behind the scores table (README) ran on matches up to this date.
# The calibration chart uses exactly the same matches, so the two agree and neither drifts
# as the season in progress adds games.
EVALUATED_THROUGH = pd.Timestamp("2026-11-02")
# The season forecast (src/forecast.py) is shown only while it is current: if its data stops arriving,
# the old forecast must not stay on the page as if it were today's.
FORECAST_FRESH_DAYS = 14


def calibration_points(p_home, won, bins=10, minimum=30):
    points = []
    edges = np.linspace(0, 1, bins + 1)
    for low, high in zip(edges[:-1], edges[1:]):
        inside = (p_home >= low) & (p_home < high)
        n = int(inside.sum())
        if n < minimum:
            continue
        rate = float(won[inside].mean())
        points.append({"predicted": float(p_home[inside].mean()), "actual": rate,
                       "error": float(1.96 * np.sqrt(rate * (1 - rate) / n)), "n": n})
    return points


def calibration(matches):
    settings = pd.read_csv(RESULTS / "dixon_coles_settings.csv").iloc[0]
    test_seasons = sorted(set(matches.season) - {WARM_UP} - set(TUNE))
    inside = matches.season.isin(test_seasons) & (matches.date <= EVALUATED_THROUGH)
    start, end = matches.date[inside].min(), matches.date[inside].max() + pd.Timedelta(days=1)
    lam, nu = walk_forward_goals(matches, start, end, xi=settings.xi,
                                 prior_weight=settings.prior_weight, newcomer=settings.newcomer)
    diffs, _ = run_elo(matches, **ELO_SETTINGS)
    elo, outcome = walk_forward_probs(matches, diffs)
    book = matches[["book_home", "book_draw", "book_away"]].to_numpy(float)
    use = (inside & ~matches.competition.isin(["CL", "EL"])).to_numpy() & ~np.isnan(book).any(axis=1)
    dc = outcome_probs(lam[use], nu[use], settings.rho)
    won = outcome[use] == 0
    return [
        {"name": "Dixon–Coles", "points": calibration_points(dc[:, 0], won)},
        {"name": "Elo", "points": calibration_points(elo[use, 0], won)},
        {"name": "Bookmakers", "points": calibration_points(book[use, 0], won)},
    ]


def clubs_table(ties):
    rows = []
    for team in pd.unique(pd.concat([ties.team_a, ties.team_b])):
        mine = ties[(ties.team_a == team) | (ties.team_b == team)]
        if len(mine) < 8:
            continue
        p = np.where(mine.team_a == team, mine.p_a, 1 - mine.p_a)
        won = int((mine.winner == team).sum())
        rows.append({"club": team, "ties": len(mine), "won": won, "expected": float(p.sum()),
                     "z": float((won - p.sum()) / np.sqrt((p * (1 - p)).sum()))})
    return sorted(rows, key=lambda r: -r["z"])


def rounds_table(ties):
    rows = []
    for rnd in ROUNDS:
        part = ties[ties["round"] == rnd]
        if not len(part):
            continue
        won = float((part.p_winner >= 0.5).mean())
        rows.append({"round": rnd, "ties": len(part),
                     "expected": float(np.maximum(part.p_a, 1 - part.p_a).mean()),
                     "won": won, "error": float(1.96 * np.sqrt(won * (1 - won) / len(part)))})
    return rows


def first_legs(matches):
    """Every real two-legged European knockout tie: the first-leg score, who went through,
    and whether the away-goals rule applied. Plus typical goals in a second leg."""
    europe = matches[matches.competition.isin(["CL", "EL"]) & matches.knockout].copy()
    europe["pair"] = [frozenset((h, a)) for h, a in zip(europe.home, europe.away)]
    ties = []
    second_home, second_away = [], []
    for (_, season, _, _), legs in europe.groupby(["competition", "season", "round", "pair"]):
        if len(legs) != 2:
            continue
        legs = legs.sort_values("date")
        first, second = legs.iloc[0], legs.iloc[1]
        away_rule = season <= LAST_AWAY_GOALS_SEASON
        winner = actual_winner(legs, away_rule)
        ties.append([int(first.home_goals), int(first.away_goals), int(winner == first.home), int(away_rule)])
        second_home.append(second.home_goals)
        second_away.append(second.away_goals)
    return {
        "ties": ties,
        "second_leg_home_goals": float(np.mean(second_home)),
        "second_leg_away_goals": float(np.mean(second_away)),
    }


def real_madrid_section(headline):
    """The Real Madrid analysis (src/real_madrid.py), if it was run on the same ties as the rest of
    the page. Left out otherwise: an analysis of 44 ties next to a page that says 50 would contradict itself."""
    path = RESULTS / "real_madrid.json"
    if not path.exists():
        return None
    analysis = json.loads(path.read_text(encoding="utf-8"))
    if (analysis["won"], analysis["ties"]) != (headline["real_won"], headline["real_ties"]):
        print(f"Warning: results/real_madrid.json is out of date ({analysis['won']} of {analysis['ties']} ties, "
              f"the page has {headline['real_won']} of {headline['real_ties']}). Run src/real_madrid.py. Leaving it out.")
        return None
    # The line-up check needs Transfermarkt's files, so it is run separately. Only used if it covers the same seasons.
    squad_path = RESULTS / "real_madrid_squad.json"
    if squad_path.exists():
        squad = json.loads(squad_path.read_text(encoding="utf-8"))
        if squad.get("through_season") == analysis.get("through_season"):
            analysis["squad"] = squad
        else:
            print("Warning: results/real_madrid_squad.json covers different seasons. Run src/real_madrid_squad.py. Leaving it out.")
    return analysis


# What the dashboard shows for a prediction still waiting for kick-off.
UPCOMING = ["competition", "date", "kickoff", "home", "away", "p_home", "p_draw", "p_away",
            "odds_home", "odds_draw", "odds_away"]


def today():
    return pd.Timestamp(datetime.now(timezone.utc).date())


def forecast_section():
    """Who will win this season's Champions League (src/forecast.py), if it was made recently."""
    path = RESULTS / "forecast.json"
    if not path.exists():
        return None
    forecast = json.loads(path.read_text(encoding="utf-8"))
    age = (today() - pd.Timestamp(forecast["as_of"])).days
    if age > FORECAST_FRESH_DAYS:
        print(f"Leaving out the season forecast: it is {age} days old (run src/forecast.py)")
        return None
    history_path = RESULTS / "forecast_history.csv"
    if history_path.exists():  # each club's chance of the title on every day it was forecast, this season's only
        history = pd.read_csv(history_path, dtype={"season": str, "as_of": str})
        history = history[(history.season == forecast["season"]) & (history.as_of <= forecast["as_of"])]
        table = history.pivot(index="as_of", columns="club", values="win")
        forecast = {**forecast, "history": {"dates": list(table.index), "win": {club: [round(float(v), 6) for v in table[club]] for club in table.columns}}}
    return forecast


def live_section():
    ratings_path, ledger_path = RESULTS / "live" / "ratings.csv", RESULTS / "live" / "prediction_ledger.csv"
    if not ratings_path.exists():
        return None
    ratings = pd.read_csv(ratings_path).head(20)
    ledger = pd.read_csv(ledger_path) if ledger_path.exists() else pd.DataFrame()
    scored = ledger.dropna(subset=["brier"]) if "brier" in ledger else ledger
    both = scored.dropna(subset=["book_brier"]) if "book_brier" in scored else scored
    upcoming = ledger[ledger["brier"].isna()] if "brier" in ledger else ledger
    # When and on what the ratings were fitted, as written by update.py. A file's modification
    # time is no substitute: a fresh git clone resets it to the day of the clone.
    meta_path = RESULTS / "live" / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    day = lambda text: datetime.strptime(text[:10], "%Y-%m-%d").strftime("%d %b %Y")
    return {
        "updated": day(meta["refitted_at"]) if "refitted_at" in meta else None,
        "fitted_through": day(meta["fitted_through"]) if "fitted_through" in meta else None,
        "window_years": round(meta["window_days"] / 365) if "window_days" in meta else None,
        "big_five_average": meta.get("big_five_average"),
        "ratings": ratings.round(3).to_dict("records"),
        "predictions": int(len(ledger)),
        "scored": int(len(scored)),
        "model_brier": float(both.brier.mean()) if len(both) else None,
        "book_brier": float(both.book_brier.mean()) if len(both) else None,
        "upcoming": [{k: v for k, v in row.items() if pd.notna(v)}  # JSON has no NaN; leave missing values out
                     for row in upcoming.reindex(columns=UPCOMING).head(30).round(3).astype({"date": str}).to_dict("records")]
                    if len(upcoming) else [],
    }


def main():
    SITE.mkdir(exist_ok=True)
    matches = load_matches()
    ties = pd.read_csv(RESULTS / "knockout_ties.csv")
    champions = pd.read_csv(RESULTS / "champions_path.csv")
    scores = pd.read_csv(RESULTS / "week2_scores.csv")
    base = pd.read_csv(RESULTS / "week1_scores.csv")
    scores = pd.concat([base[base.model == "Base rates"], scores], ignore_index=True)

    champion_runs = []
    for row in champions.itertuples():
        path = ties[(ties.season == row.season) & (ties.winner == row.champion)]
        path = path.set_index("round").reindex([r for r in ROUNDS if r in set(path["round"])]).reset_index()
        champion_runs.append({
            "season": row.season, "champion": row.champion, "probability": row.path_probability,
            "ties": [{"round": t["round"], "opponent": t.team_b if t.team_a == row.champion else t.team_a,
                      "probability": t.p_winner} for _, t in path.iterrows()]})

    leg_scores = tie_scores(matches)
    tie_rows = ties[["season", "round", "team_a", "team_b", "p_a", "winner"]].round(4).to_dict("records")
    for row in tie_rows:  # a KeyError here means a tie has no recorded match: better loud than blank
        row.update(leg_scores[(row["season"], row["round"], row["team_a"], row["team_b"])])

    brackets = build_brackets(matches, pd.read_csv(RESULTS / "dixon_coles_settings.csv").iloc[0])
    favourite = np.maximum(ties.p_a, 1 - ties.p_a)
    clubs = clubs_table(ties)
    real = next(c for c in clubs if c["club"] == "Real Madrid")
    data = {
        "built": datetime.now(timezone.utc).strftime("%d %b %Y"),
        "headline": {
            "ties": len(ties),
            "first_season": ties.season.min(), "last_season": ties.season.max(),
            "underdog": float(1 - favourite.mean()),
            "favourite_expected": float(favourite.mean()),
            "favourite_won": float((ties.p_winner >= 0.5).mean()),
            "median_champion_run": float(champions.path_probability.median()),
            "real_won": real["won"], "real_ties": real["ties"], "real_expected": real["expected"],
        },
        "champions": champion_runs,
        "ties": tie_rows,
        "rounds": rounds_table(ties),
        "clubs": clubs,
        "real_madrid": None,  # filled in below, once the headline numbers exist
        "scores": scores.round(4).to_dict("records"),
        "calibration": calibration(matches),
        "matches": int(len(matches)),
        "live": live_section(),
        "forecast": forecast_section(),
        "comebacks": first_legs(matches),
        "brackets": brackets,
        "replays": season_replays(brackets),
    }
    data["real_madrid"] = real_madrid_section(data["headline"])
    # allow_nan=False: a NaN would be written as a bare NaN, which browsers refuse to parse,
    # and the whole dashboard would fail to load. Better to fail here, loudly.
    (SITE / "data.json").write_text(json.dumps(data, ensure_ascii=False, indent=1, allow_nan=False), encoding="utf-8")
    print(f"Wrote {SITE / 'data.json'} ({(SITE / 'data.json').stat().st_size // 1024} KB)")
    write_preview(data, SITE / "preview.png")  # the picture a shared link shows


if __name__ == "__main__":
    main()
