"""Week 2: tune Dixon–Coles on early seasons, test it on later seasons, and compare it
with Elo and bookmakers' closing odds. Same season split as week 1.

The model is refitted every 7 days on matches played before that day only.
"""

import itertools
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

from dixon_coles import outcome_probs, walk_forward_goals
from elo import run_elo
from evaluate_elo import TUNE, WARM_UP, paired_interval, walk_forward_probs
from matches import load_matches
from outcomes import brier, log_loss, outcome_codes

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

RESULTS = Path(__file__).resolve().parent.parent / "results"
EUROPE = ["CL", "EL"]
ELO_SETTINGS = dict(k=20, home_advantage=40, newcomer_gap=50, season_regress=0.0)  # tuned in week 1


def season_span(matches, seasons):
    inside = matches.season.isin(seasons)
    return matches.date[inside].min(), matches.date[inside].max() + pd.Timedelta(days=1)


def tune(matches, outcome):
    start, end = season_span(matches, TUNE)
    tuning = (matches.season.isin(TUNE) & ~matches.competition.isin(EUROPE)).to_numpy()
    scores = []
    for xi, weight, newcomer in itertools.product([0.001, 0.002, 0.004], [1.0, 3.0, 10.0], [0.0, 0.2, 0.4]):
        lam, nu = walk_forward_goals(matches, start, end, xi=xi, prior_weight=weight, newcomer=newcomer)
        for rho in (-0.1, -0.05, 0.0):
            probs = outcome_probs(lam[tuning], nu[tuning], rho)
            scores.append(((xi, weight, newcomer, rho), log_loss(probs, outcome[tuning]).mean()))
        print(f"  tried xi={xi}, prior weight={weight}, newcomer={newcomer}", flush=True)
    scores.sort(key=lambda item: item[1])
    return scores


def calibration_chart(models, outcome, path):
    fig, ax = plt.subplots(figsize=(5.5, 5.5))
    bins = np.linspace(0, 1, 11)
    for label, p, colour in models:
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
    outcome = outcome_codes(matches.home_goals, matches.away_goals)

    print("Tuning on 2012-13 to 2016-17...")
    scores = tune(matches, outcome)
    (xi, weight, newcomer, rho), best = scores[0]
    print(f"Best: xi={xi} (half-life {np.log(2) / xi:.0f} days), prior weight={weight}, "
          f"newcomer={newcomer}, rho={rho} (log loss {best:.4f})")
    print("Runners-up:", ", ".join(f"{s} {v:.4f}" for s, v in scores[1:4]))

    test_seasons = sorted(set(matches.season) - {WARM_UP} - set(TUNE))
    start, end = season_span(matches, test_seasons)
    lam, nu = walk_forward_goals(matches, start, end, xi=xi, prior_weight=weight, newcomer=newcomer)
    test_all = matches.season.isin(test_seasons).to_numpy()
    dc = np.full((len(matches), 3), np.nan)
    dc[test_all] = outcome_probs(lam[test_all], nu[test_all], rho)

    diffs, _ = run_elo(matches, **ELO_SETTINGS)
    elo, _ = walk_forward_probs(matches, diffs)
    book = matches[["book_home", "book_draw", "book_away"]].to_numpy(dtype=float)

    league_test = test_all & ~matches.competition.isin(EUROPE).to_numpy()
    with_odds = league_test & ~np.isnan(book).any(axis=1)
    o = outcome[with_odds]

    rows = []
    for name, p in (("Elo", elo), ("Dixon–Coles", dc), ("Average of Elo and Dixon–Coles", (elo + dc) / 2),
                    ("Bookmakers (closing)", book)):
        rows.append({"model": name, "matches": int(with_odds.sum()),
                     "brier": brier(p[with_odds], o).mean(), "log_loss": log_loss(p[with_odds], o).mean()})
    table = pd.DataFrame(rows)
    print("\nTest seasons 2017-18 onwards, league matches with closing odds:")
    print(table.to_string(index=False, float_format=lambda v: f"{v:.4f}"))

    dc_brier, book_brier, elo_brier = brier(dc[with_odds], o), brier(book[with_odds], o), brier(elo[with_odds], o)
    for label, other in (("bookmakers", book_brier), ("Elo", elo_brier)):
        low, high = paired_interval(dc_brier, other)
        print(f"Dixon–Coles minus {label}, Brier: {dc_brier.mean() - other.mean():+.4f} "
              f"(95% interval {low:+.4f} to {high:+.4f}; positive means Dixon–Coles is worse)")

    europe = test_all & matches.competition.isin(EUROPE).to_numpy()
    print(f"\nEuropean matches in test seasons ({europe.sum()}): Dixon–Coles Brier "
          f"{brier(dc[europe], outcome[europe]).mean():.4f}, Elo {brier(elo[europe], outcome[europe]).mean():.4f}")
    knockout = europe & matches.knockout.to_numpy()
    print(f"European knockout matches only ({knockout.sum()}): Dixon–Coles Brier "
          f"{brier(dc[knockout], outcome[knockout]).mean():.4f}, Elo {brier(elo[knockout], outcome[knockout]).mean():.4f}")

    calibration_chart(
        [("Dixon–Coles", dc[with_odds, 0], "#2a6fdb"), ("Elo", elo[with_odds, 0], "#8a8a8a"),
         ("Bookmakers (closing)", book[with_odds, 0], "#d1495b")],
        o, RESULTS / "calibration_week2.png")
    table.to_csv(RESULTS / "week2_scores.csv", index=False)
    pd.DataFrame({"xi": [xi], "prior_weight": [weight], "newcomer": [newcomer], "rho": [rho]}).to_csv(
        RESULTS / "dixon_coles_settings.csv", index=False)
    print(f"\nSaved calibration_week2.png, week2_scores.csv and dixon_coles_settings.csv in {RESULTS}")


if __name__ == "__main__":
    main()
