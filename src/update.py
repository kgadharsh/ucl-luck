"""Self-updating predictions with an honest ledger.

Each run:
1. refits Dixon–Coles on every match played so far,
2. predicts upcoming big-five league fixtures and adds them to a ledger,
   stamped with the time of prediction (a prediction already in the ledger is never changed),
3. scores ledger predictions whose matches have now been played, against the bookmakers,
4. writes current ratings and a scorecard.

Run after scripts/download_data.py --refresh-current, by hand or on a schedule.
"""

import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from dixon_coles import fit, outcome_probs
from matches import load_matches
from outcomes import brier, outcome_codes
from parse_leagues import parse_dates

ROOT = Path(__file__).resolve().parent.parent
LIVE = ROOT / "results" / "live"
LEDGER = LIVE / "prediction_ledger.csv"
FIXTURES_URL = "https://www.football-data.co.uk/fixtures.csv"
LEAGUES = {"E0", "SP1", "D1", "I1", "F1"}
KEY = ["date", "home", "away"]


def settings():
    row = pd.read_csv(ROOT / "results" / "dixon_coles_settings.csv").iloc[0]
    return dict(xi=row.xi, prior_weight=row.prior_weight, newcomer=row.newcomer), row.rho


def upcoming_fixtures(today):
    with urllib.request.urlopen(FIXTURES_URL, timeout=30) as response:
        path = ROOT / "data" / "raw" / "fixtures.csv"
        path.write_bytes(response.read())
    frame = pd.read_csv(path, encoding="utf-8-sig")
    frame = frame[frame["Div"].isin(LEAGUES)]
    fixtures = pd.DataFrame({
        "competition": frame["Div"],
        "date": pd.to_datetime(parse_dates(frame["Date"])),
        "home": frame["HomeTeam"].str.strip(),
        "away": frame["AwayTeam"].str.strip(),
    })
    return fixtures[fixtures.date >= today].reset_index(drop=True)


def predict(model, rho, newcomer, fixtures):
    expected = [model.expected_goals(row.home, row.away, False, newcomer) for row in fixtures.itertuples()]
    lam = np.array([e[0] for e in expected])
    nu = np.array([e[1] for e in expected])
    probs = outcome_probs(lam, nu, rho) if len(fixtures) else np.empty((0, 3))
    out = fixtures.copy()
    out["p_home"], out["p_draw"], out["p_away"] = probs.T if len(fixtures) else ([], [], [])
    out["exp_home_goals"], out["exp_away_goals"] = lam, nu
    return out


def add_to_ledger(predictions, stamp):
    predictions = predictions.assign(predicted_at=stamp)
    if not LEDGER.exists():
        return predictions, len(predictions)
    ledger = pd.read_csv(LEDGER, parse_dates=["date"])
    known = set(zip(ledger.date, ledger.home, ledger.away))
    new = predictions[[(d, h, a) not in known for d, h, a in
                       zip(predictions.date, predictions.home, predictions.away)]]
    if len(new):
        ledger = pd.concat([ledger, new], ignore_index=True)
    return ledger, len(new)


def score_ledger(ledger, matches):
    played = matches[~matches.competition.isin(["CL", "EL"])][
        KEY + ["home_goals", "away_goals", "book_home", "book_draw", "book_away"]]
    ledger = ledger.drop(columns=[c for c in played.columns if c not in KEY and c in ledger.columns])
    ledger = ledger.merge(played, on=KEY, how="left")
    done = ledger.home_goals.notna().to_numpy()
    ledger["brier"] = np.nan
    ledger["book_brier"] = np.nan
    if done.any():
        outcome = outcome_codes(ledger.home_goals[done].astype(int), ledger.away_goals[done].astype(int))
        ledger.loc[done, "brier"] = brier(ledger.loc[done, ["p_home", "p_draw", "p_away"]].to_numpy(float), outcome)
        book = ledger.loc[done, ["book_home", "book_draw", "book_away"]].to_numpy(float)
        has_book = ~np.isnan(book).any(axis=1)
        book_scores = np.full(done.sum(), np.nan)
        book_scores[has_book] = brier(book[has_book], outcome[has_book])
        ledger.loc[done, "book_brier"] = book_scores
    return ledger


def write_scorecard(ledger, ratings, stamp):
    scored = ledger.dropna(subset=["brier"])
    both = scored.dropna(subset=["book_brier"])
    lines = [
        "# Live scorecard",
        "",
        f"Last updated {stamp}. Predictions are made before kick-off and never changed afterwards.",
        "",
        f"- Predictions in the ledger: {len(ledger)}",
        f"- Matches played and scored: {len(scored)}",
    ]
    if len(both):
        lines.append(f"- Brier on {len(both)} matches with closing odds: model {both.brier.mean():.4f}, "
                     f"bookmakers {both.book_brier.mean():.4f} (lower is better)")
    lines += ["", "## Strongest clubs now (attack + defence, in log-goals)", "",
              "| Rank | Club | Attack | Defence | Overall |", "|---|---|---|---|---|"]
    for rank, row in enumerate(ratings.head(20).itertuples(), start=1):
        lines.append(f"| {rank} | {row.club} | {row.attack:+.2f} | {row.defence:+.2f} | {row.overall:+.2f} |")
    (LIVE / "scorecard.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    LIVE.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y-%m-%d %H:%M UTC")
    today = pd.Timestamp(now.date())

    fit_settings, rho = settings()
    matches = load_matches()
    model = fit(matches, today + pd.Timedelta(days=1), **fit_settings)

    clubs = list(model.index)
    ratings = pd.DataFrame({"club": clubs, "attack": model.attack, "defence": model.defence})
    ratings["overall"] = ratings.attack + ratings.defence
    ratings = ratings.sort_values("overall", ascending=False).reset_index(drop=True)
    ratings.to_csv(LIVE / "ratings.csv", index=False, float_format="%.4f")

    fixtures = upcoming_fixtures(today)
    predictions = predict(model, rho, fit_settings["newcomer"], fixtures)
    ledger, added = add_to_ledger(predictions, stamp)
    ledger = score_ledger(ledger, matches)
    ledger.sort_values(KEY).to_csv(LEDGER, index=False, float_format="%.4f")
    write_scorecard(ledger, ratings, stamp)

    print(f"{stamp}: fitted on {len(matches)} matches up to {matches.date.max():%d %b %Y}; "
          f"{len(fixtures)} upcoming fixtures, {added} new predictions; "
          f"{ledger.brier.notna().sum()} ledger predictions scored so far")


if __name__ == "__main__":
    main()
