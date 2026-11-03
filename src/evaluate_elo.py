"""Week 1: tune Elo on early seasons, then test it on later seasons it never saw,
against simple baselines and bookmakers' closing odds.

Seasons
- 2011-12: warm-up only (ratings start equal, so its predictions are not scored)
- 2012-13 to 2016-17: tuning (choose Elo settings by log loss)
- 2017-18 onwards: test (reported, never used for choices)

For every season, the probability model is refitted on earlier seasons only.
"""

import itertools
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

from elo import run_elo
from matches import load_matches
from outcomes import brier, fit_ordered, log_loss, ordered_probs, outcome_codes

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

RESULTS = Path(__file__).resolve().parent.parent / "results"
WARM_UP = "2011-12"
TUNE = ["2012-13", "2013-14", "2014-15", "2015-16", "2016-17"]
EUROPE = ["CL", "EL"]
RNG = np.random.default_rng(7)


def walk_forward_probs(matches, diffs):
    """Probabilities for every match, with the ordered model fitted only on earlier seasons."""
    outcome = outcome_codes(matches.home_goals, matches.away_goals)
    probs = np.full((len(matches), 3), np.nan)
    seasons = sorted(matches.season.unique())
    league = ~matches.competition.isin(EUROPE).to_numpy()
    for season in seasons:
        if season == WARM_UP:
            continue
        earlier = (matches.season < season).to_numpy() & (matches.season != WARM_UP).to_numpy() & league
        if not earlier.any():
            earlier = (matches.season == WARM_UP).to_numpy() & league
        params = fit_ordered(diffs[earlier], outcome[earlier])
        now = (matches.season == season).to_numpy()
        probs[now] = ordered_probs(diffs[now], params)
    return probs, outcome


def tune(matches):
    league = ~matches.competition.isin(EUROPE)
    tuning = (matches.season.isin(TUNE) & league).to_numpy()
    grid = itertools.product([15, 20, 25, 30, 40], [40, 60, 80, 100], [50, 100, 150], [0.0, 0.2])
    scores = []
    for k, home, gap, regress in grid:
        diffs, _ = run_elo(matches, k=k, home_advantage=home, newcomer_gap=gap, season_regress=regress)
        probs, outcome = walk_forward_probs(matches, diffs)
        scores.append(((k, home, gap, regress), log_loss(probs[tuning], outcome[tuning]).mean()))
    scores.sort(key=lambda item: item[1])
    return scores


def base_rate_probs(matches, outcome):
    """Baseline: every match gets the home/draw/away frequencies of earlier seasons."""
    probs = np.full((len(matches), 3), np.nan)
    league = ~matches.competition.isin(EUROPE).to_numpy()
    for season in sorted(matches.season.unique())[1:]:
        earlier = (matches.season < season).to_numpy() & league
        rates = np.bincount(outcome[earlier], minlength=3) / earlier.sum()
        probs[(matches.season == season).to_numpy()] = rates
    return probs


def paired_interval(a, b, draws=2000):
    """95% bootstrap interval for mean(a) - mean(b), resampling matches."""
    n = len(a)
    picks = RNG.integers(0, n, size=(draws, n))
    differences = a[picks].mean(axis=1) - b[picks].mean(axis=1)
    return np.percentile(differences, [2.5, 97.5])


def calibration_chart(probs, book, outcome, path):
    """Home-win probability against how often the home team actually won, with 95% intervals."""
    fig, ax = plt.subplots(figsize=(5.5, 5.5))
    bins = np.linspace(0, 1, 11)
    for label, p, colour in (("Elo", probs[:, 0], "#2a6fdb"), ("Bookmakers (closing)", book[:, 0], "#d1495b")):
        centres, rates, errors = [], [], []
        for low, high in zip(bins[:-1], bins[1:]):
            inside = (p >= low) & (p < high)
            if inside.sum() < 30:
                continue
            won = (outcome[inside] == 0).mean()
            centres.append(p[inside].mean())
            rates.append(won)
            errors.append(1.96 * np.sqrt(won * (1 - won) / inside.sum()))
        ax.errorbar(centres, rates, yerr=errors, fmt="o-", color=colour, label=label, capsize=3, ms=4)
    ax.plot([0, 1], [0, 1], color="#999", lw=1, ls="--", label="Perfectly honest")
    ax.set_xlabel("Predicted chance of a home win")
    ax.set_ylabel("How often the home team actually won")
    ax.set_title("Calibration on unseen seasons, big-five leagues")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.legend(loc="upper left", frameon=False)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def main():
    RESULTS.mkdir(exist_ok=True)
    matches = load_matches()

    scores = tune(matches)
    (k, home, gap, regress), best = scores[0]
    print(f"Best settings on tuning seasons: K={k}, home advantage={home}, newcomer gap={gap}, "
          f"season regression={regress} (log loss {best:.4f})")
    print("Runners-up:", ", ".join(f"{s} {v:.4f}" for s, v in scores[1:4]))

    diffs, _ = run_elo(matches, k=k, home_advantage=home, newcomer_gap=gap, season_regress=regress)
    probs, outcome = walk_forward_probs(matches, diffs)
    base = base_rate_probs(matches, outcome)

    league = ~matches.competition.isin(EUROPE)
    test = (~matches.season.isin([WARM_UP] + TUNE) & league).to_numpy()
    book = matches[["book_home", "book_draw", "book_away"]].to_numpy(dtype=float)
    with_odds = test & ~np.isnan(book).any(axis=1)

    rows = []
    for name, p in (("Elo", probs), ("Base rates", base), ("Bookmakers (closing)", book)):
        rows.append({
            "model": name,
            "matches": int(with_odds.sum()),
            "brier": brier(p[with_odds], outcome[with_odds]).mean(),
            "log_loss": log_loss(p[with_odds], outcome[with_odds]).mean(),
        })
    table = pd.DataFrame(rows)
    print("\nTest seasons 2017-18 onwards, league matches with closing odds:")
    print(table.to_string(index=False, float_format=lambda v: f"{v:.4f}"))

    elo_brier = brier(probs[with_odds], outcome[with_odds])
    book_brier = brier(book[with_odds], outcome[with_odds])
    low, high = paired_interval(elo_brier, book_brier)
    print(f"\nElo minus bookmakers, Brier: {elo_brier.mean() - book_brier.mean():+.4f} "
          f"(95% interval {low:+.4f} to {high:+.4f}; positive means Elo is worse)")

    by_season = pd.DataFrame({
        "season": matches.season[with_odds].to_numpy(),
        "elo": elo_brier,
        "book": book_brier,
    }).groupby("season").mean()
    by_season["gap"] = by_season.elo - by_season.book
    print("\nBy season (Brier):")
    print(by_season.to_string(float_format=lambda v: f"{v:.4f}"))

    europe_test = (~matches.season.isin([WARM_UP] + TUNE) & matches.competition.isin(EUROPE)).to_numpy()
    print(f"\nEuropean matches in test seasons ({europe_test.sum()}, no odds available): "
          f"Elo Brier {brier(probs[europe_test], outcome[europe_test]).mean():.4f}, "
          f"base rates {brier(base[europe_test], outcome[europe_test]).mean():.4f}")

    calibration_chart(probs[with_odds], book[with_odds], outcome[with_odds], RESULTS / "calibration_week1.png")
    table.to_csv(RESULTS / "week1_scores.csv", index=False)
    print(f"\nSaved {RESULTS / 'calibration_week1.png'} and week1_scores.csv")


if __name__ == "__main__":
    main()
