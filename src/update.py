"""Self-updating predictions with an honest ledger.

Each run:
1. refits Dixon–Coles on the matches of the last three years (recent ones count more),
2. predicts big-five league fixtures that have not kicked off and adds them to a ledger,
   stamped with the time of prediction (a prediction already in the ledger is never changed,
   even if the match is moved to another date),
3. scores ledger predictions whose matches have now been played, against the bookmakers,
4. writes current ratings (also in football terms: goals and win chance against an average
   big-five club) and a scorecard.

Run after scripts/download_data.py --refresh-current, by hand or on a schedule.
"""

import inspect
import json
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
# One prediction per league meeting: two clubs meet at a given ground once a season, so this
# key survives a match being moved to another date (keying on the date would predict it twice).
KEY = ["competition", "season", "home", "away"]
UK = "Europe/London"  # fixtures.csv gives kick-off times in UK time


def season_of(dates):
    """'2026-27' for any date from July 2026 to June 2027."""
    years = dates.dt.year - (dates.dt.month < 7).astype(int)
    return years.astype(str) + "-" + ((years + 1) % 100).map("{:02d}".format)


def settings():
    row = pd.read_csv(ROOT / "results" / "dixon_coles_settings.csv").iloc[0]
    return dict(xi=row.xi, prior_weight=row.prior_weight, newcomer=row.newcomer), row.rho


def upcoming_fixtures(now):
    """Big-five fixtures that have not kicked off yet."""
    with urllib.request.urlopen(FIXTURES_URL, timeout=30) as response:
        path = ROOT / "data" / "raw" / "fixtures.csv"
        path.write_bytes(response.read())
    frame = pd.read_csv(path, encoding="utf-8-sig")
    frame = frame[frame["Div"].isin(LEAGUES)].reset_index(drop=True)
    dates = pd.to_datetime(parse_dates(frame["Date"]))
    times = frame["Time"].fillna("").astype(str).str.strip() if "Time" in frame else pd.Series("", index=frame.index)
    kickoff = pd.to_datetime(dates.dt.strftime("%Y-%m-%d") + " " + times, format="%Y-%m-%d %H:%M", errors="coerce")
    kickoff = kickoff.dt.tz_localize(UK, ambiguous="NaT", nonexistent="NaT").dt.tz_convert("UTC")
    fixtures = pd.DataFrame({
        "competition": frame["Div"],
        "season": season_of(dates),
        "date": dates,
        "kickoff": kickoff,
        "home": frame["HomeTeam"].str.strip(),
        "away": frame["AwayTeam"].str.strip(),
    })
    # Only matches still to start. Without a usable kick-off time we can't tell whether a
    # match today has started, so those count only from the day after.
    today = pd.Timestamp(now.date())
    ahead = (fixtures.kickoff > now) | (fixtures.kickoff.isna() & (fixtures.date > today))
    fixtures = fixtures[ahead].drop_duplicates(KEY)
    fixtures["kickoff"] = fixtures.kickoff.dt.strftime("%Y-%m-%d %H:%M UTC")
    return fixtures.reset_index(drop=True)


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
    if ledger.empty:  # also: an empty file's date column isn't read as dates
        return predictions, len(predictions)
    if "season" not in ledger:  # ledgers written before predictions were keyed by season
        ledger.insert(1, "season", season_of(pd.to_datetime(ledger.date)))
    known = set(map(tuple, ledger[KEY].to_numpy()))
    new = predictions[[key not in known for key in map(tuple, predictions[KEY].to_numpy())]]
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


def rate_clubs(model, rho, big_five_clubs):
    """Each club's strengths, and the same thing in football terms: the goals it would score and
    concede, and its chances of winning, drawing and losing, against an average big-five club
    this season on a neutral pitch."""
    ratings = pd.DataFrame({"club": list(model.index), "attack": model.attack, "defence": model.defence})
    ratings["overall"] = ratings.attack + ratings.defence
    average = ratings[ratings.club.isin(big_five_clubs)]
    scores = np.exp(model.mu + ratings.attack - average.defence.mean()).to_numpy()
    concedes = np.exp(model.mu + average.attack.mean() - ratings.defence).to_numpy()
    probs = outcome_probs(scores, concedes, rho)
    ratings["scores"], ratings["concedes"] = scores, concedes
    ratings["win"], ratings["draw"], ratings["lose"] = probs.T
    return ratings.sort_values("win", ascending=False).reset_index(drop=True)


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
    lines += ["", "## Strongest clubs now", "",
              "Against an average big-five club this season, on a neutral pitch.", "",
              "| Rank | Club | Would score | Would concede | Chance of winning |", "|---|---|---|---|---|"]
    for rank, row in enumerate(ratings.head(20).itertuples(), start=1):
        lines.append(f"| {rank} | {row.club} | {row.scores:.1f} | {row.concedes:.1f} | {row.win:.0%} |")
    (LIVE / "scorecard.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    LIVE.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y-%m-%d %H:%M UTC")
    today = pd.Timestamp(now.date())

    fit_settings, rho = settings()
    matches = load_matches()
    model = fit(matches, today + pd.Timedelta(days=1), **fit_settings)

    this_season = matches[matches.competition.isin(LEAGUES) & (matches.season == matches.season.max())]
    ratings = rate_clubs(model, rho, set(this_season.home) | set(this_season.away))
    ratings.to_csv(LIVE / "ratings.csv", index=False, float_format="%.4f")

    fixtures = upcoming_fixtures(now)
    predictions = predict(model, rho, fit_settings["newcomer"], fixtures)
    ledger, added = add_to_ledger(predictions, stamp)
    ledger = score_ledger(ledger, matches)
    ledger.sort_values(["date", "competition", "home"]).to_csv(LEDGER, index=False, float_format="%.4f")
    write_scorecard(ledger, ratings, stamp)

    # What the dashboard needs to describe the ratings honestly.
    big_five = ratings[ratings.club.isin(set(this_season.home) | set(this_season.away))]
    meta = {
        "refitted_at": stamp,
        "fitted_through": f"{matches.date.max():%Y-%m-%d}",
        "window_days": inspect.signature(fit).parameters["window_days"].default,
        "big_five_average": round(float(big_five.overall.mean()), 3),
    }
    (LIVE / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")

    print(f"{stamp}: fitted on {len(matches)} matches up to {matches.date.max():%d %b %Y}; "
          f"{len(fixtures)} upcoming fixtures, {added} new predictions; "
          f"{ledger.brier.notna().sum()} ledger predictions scored so far")


if __name__ == "__main__":
    main()
