"""How good would the season forecast have been?

Re-runs src/forecast.py on the two seasons played in the new format (2024-25 and 2025-26) as it
would have looked at five moments: before the first matchday, and after matchdays 2, 4, 6 and 8 (the
end of the league phase). At each moment it only uses what was known then: the ratings are fitted
on earlier matches, and the matches after it are played out by the simulation, not read. Each
club's chance of each stage is then set against what happened.

Two seasons is not much, and the stages are not independent (one upset moves a dozen clubs). So this
is a check for gross mistakes (favourites far too sure, long shots never arriving), not a precise
measure of how good the forecast is. Both seasons are scored with the bracket of 2025-26.

Output: results/forecast_backtest.json and results/forecast_backtest_log.txt (with --noise, files with
_noise_<amount> in their names, so an experiment never replaces them).
"""

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

import forecast as fc
from knockouts import actual_winner
from matches import load_matches

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"
SEASONS = ("2024-25", "2025-26")
AFTER = (0, 2, 4, 6, 8)  # league-phase matchdays played at each moment
STAGES = fc.STAGES
SIZE = {"top8": 8, "top24": 24, "last16": 16, "quarter": 8, "semi": 4, "final": 2, "win": 1}
BINS = [0, 0.02, 0.1, 0.25, 0.5, 0.75, 0.9, 0.98, 1.0000001]


def league_phase(matches, season):
    """The season's league phase, in the form src/parse_league_phase.py gives."""
    league = matches[(matches.competition == "CL") & (matches.season == season)
                     & matches["round"].fillna("").str.startswith("League")].copy()
    table = pd.DataFrame({
        "matchday": league["round"].str.extract(r"(\d+)$")[0].astype(int),
        "date": league.date, "home_page": league.home, "home": league.home, "home_country": "XXX",
        "away_page": league.away, "away": league.away, "away_country": "XXX",
        "home_goals": league.home_goals.astype(float), "away_goals": league.away_goals.astype(float)})
    return table.sort_values(["matchday", "date"], kind="stable").reset_index(drop=True)


def what_happened(matches, season):
    """{club: the set of stages it reached} for the season."""
    cl = matches[(matches.competition == "CL") & (matches.season == season)]
    in_round = lambda name: set(cl[cl["round"] == name].home) | set(cl[cl["round"] == name].away)
    playoffs, last16, quarter, semi, final = (in_round(r) for r in ("Playoffs", "Round of 16", "Quarterfinals", "Semifinals", "Final"))
    top8 = last16 - playoffs  # the eight that skipped the play-offs
    champion = actual_winner(cl[cl["round"] == "Final"], False)
    reached = {"top8": top8, "top24": top8 | playoffs, "last16": last16, "quarter": quarter, "semi": semi, "final": final, "win": {champion}}
    assert [len(reached[stage]) for stage in STAGES] == [SIZE[stage] for stage in STAGES], season
    return reached, champion


def run(n, history, noise=0.0, worlds=1):
    """One row per season, moment, club and stage: the chance given, and whether it happened."""
    rows, titles = [], []
    for season in SEASONS:
        full = league_phase(history, season)
        reached, champion = what_happened(history, season)
        for after in AFTER:
            league = full.copy()
            later = league.matchday > after
            league.loc[later, ["home_goals", "away_goals"]] = np.nan
            as_of = (full[full.matchday == after].date.max() if after else full.date.min() - pd.Timedelta(days=1))
            result = fc.forecast(as_of, n=n, season=season, history=history, league=league, noise=noise, worlds=worlds)
            for club in result["clubs"]:
                for stage in STAGES:
                    rows.append({"season": season, "after": after, "club": club["club"], "stage": stage, "p": club[stage],
                                 "happened": club["club"] in reached[stage],
                                 # at the end of the league phase the table is final: top 8 and top 24 are no longer forecasts
                                 "decided": after == 8 and stage in ("top8", "top24")})
            ranked = sorted(result["clubs"], key=lambda c: -c["win"])
            mine = next(c for c in ranked if c["club"] == champion)
            titles.append({"season": season, "after": after, "champion": champion, "p": mine["win"],
                           "rank": 1 + ranked.index(mine), "favourite": ranked[0]["club"], "favourite_p": ranked[0]["win"]})
            print(f"{season} after matchday {after}: favourite {ranked[0]['club']} {ranked[0]['win']:.1%}; "
                  f"{champion} (champion) {mine['win']:.1%}, ranked {1 + ranked.index(mine)}", flush=True)
    return pd.DataFrame(rows), pd.DataFrame(titles)


def brier(frame):
    return float(((frame.p - frame.happened.astype(float)) ** 2).mean())


def summarise(rows, titles):
    """Brier scores against knowing nothing (every club given the same chance of each stage), a
    calibration table over every forecast still open, and what the champion was given."""
    rows = rows.assign(base=rows.stage.map(lambda s: SIZE[s] / 36))
    rows["base_brier"] = (rows.base - rows.happened.astype(float)) ** 2
    rows["brier"] = (rows.p - rows.happened.astype(float)) ** 2
    open_ = rows[~rows.decided]
    by_stage = []
    for stage in STAGES:
        part = open_[open_.stage == stage]
        by_stage.append({"stage": stage, "clubs": len(part), "brier": float(part.brier.mean()) if len(part) else None,
                         "knowing_nothing": float(part.base_brier.mean()) if len(part) else None,
                         "skill": float(1 - part.brier.sum() / part.base_brier.sum()) if len(part) else None})
    by_moment = []
    for after in AFTER:
        part = open_[open_.after == after]
        by_moment.append({"after": after, "brier": float(part.brier.mean()) if len(part) else None,
                          "knowing_nothing": float(part.base_brier.mean()) if len(part) else None,
                          "skill": float(1 - part.brier.sum() / part.base_brier.sum()) if len(part) else None})
    calibration = []
    for low, high in zip(BINS[:-1], BINS[1:]):
        part = open_[(open_.p >= low) & (open_.p < high)]
        if len(part):
            calibration.append({"low": low, "high": min(high, 1.0), "forecasts": len(part), "given": float(part.p.mean()),
                                "happened": float(part.happened.mean()), "expected_count": float(part.p.sum()), "count": int(part.happened.sum())})
    overall = {"brier": float(open_.brier.mean()), "knowing_nothing": float(open_.base_brier.mean()),
               "skill": float(1 - open_.brier.sum() / open_.base_brier.sum())}
    # How much weight the favourite carries: each moment's top title chance against how often that club won.
    favourites = titles.assign(won=titles.favourite.eq(titles.champion))
    return {"overall": overall, "by_stage": by_stage, "by_moment": by_moment, "calibration": calibration,
            "champion": titles.round(4).to_dict("records"),
            "favourite_won": int(favourites.won.sum()), "favourite_expected": float(favourites.favourite_p.sum()), "moments": len(favourites)}


def report(summary):
    lines = ["Forecast backtest: 2024-25 and 2025-26, as of five moments in each", ""]
    if summary.get("noise"):
        lines += [f"Every club's strength nudged by a random {summary['noise']} (log-goals), over {summary['worlds']} versions of the ratings", ""]
    o = summary["overall"]
    lines += [f"All open forecasts together: model {o['brier']:.4f}, knowing nothing {o['knowing_nothing']:.4f}, skill {o['skill']:+.1%}", ""]
    lines.append("Brier score by stage (lower is better; 'knowing nothing' gives every club the same chance of each stage)")
    for row in summary["by_stage"]:
        lines.append(f"  {row['stage']:<8} {row['clubs']:>4} forecasts  model {row['brier']:.4f}  knowing nothing {row['knowing_nothing']:.4f}  skill {row['skill']:+.0%}")
    lines += ["", "By moment"]
    for row in summary["by_moment"]:
        lines.append(f"  after matchday {row['after']}: model {row['brier']:.4f}  knowing nothing {row['knowing_nothing']:.4f}  skill {row['skill']:+.0%}")
    lines += ["", "Calibration of every open forecast (a chance given, against how often it happened)"]
    for row in summary["calibration"]:
        lines.append(f"  {row['low']:>4.0%} to {row['high']:>4.0%}: {row['forecasts']:>4} forecasts, given {row['given']:.1%}, happened {row['happened']:.1%} "
                     f"({row['count']} against {row['expected_count']:.1f} expected)")
    lines += ["", "The champion's chance of winning, as the season went on"]
    for row in summary["champion"]:
        lines.append(f"  {row['season']} after matchday {row['after']}: {row['champion']} {row['p']:.1%} (rank {row['rank']}); favourite {row['favourite']} {row['favourite_p']:.1%}")
    lines.append(f"The favourite won the title at {summary['favourite_won']} of {summary['moments']} moments; the model expected {summary['favourite_expected']:.1f}.")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--simulations", type=int, default=20_000)
    parser.add_argument("--noise", type=float, default=0.0, help="nudge every club's strength by this much (log-goals) in each world")
    parser.add_argument("--worlds", type=int, default=20, help="how many nudged versions of the ratings to split the simulations over")
    parser.add_argument("--no-save", action="store_true", help="print only, leave the saved results alone")
    args = parser.parse_args(argv)
    history = load_matches()
    rows, titles = run(args.simulations, history, args.noise, args.worlds)
    summary = summarise(rows, titles)
    summary["simulations"], summary["noise"], summary["worlds"] = args.simulations, args.noise, args.worlds if args.noise else 1
    text = report(summary)
    print("\n" + text)
    if args.no_save:
        return
    suffix = f"_noise_{args.noise:g}" if args.noise else ""  # an experiment never overwrites the real thing
    (RESULTS / f"forecast_backtest{suffix}.json").write_text(json.dumps(summary, indent=1, allow_nan=False) + "\n", encoding="utf-8")
    (RESULTS / f"forecast_backtest{suffix}_log.txt").write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
