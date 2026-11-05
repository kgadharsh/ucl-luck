"""Week 3: how much of a Champions League knockout is luck?

For every knockout tie since 2012-13, the chance that each team goes through is
computed **before the first leg**, from a Dixon–Coles fit on earlier matches only.
The calculation is exact rather than simulated (the same as replaying each tie
infinitely many times). It covers both legs, the away-goals rule (used until
2020-21), extra time and penalties (treated as a coin flip).
"""

from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd
from scipy.stats import poisson

from dixon_coles import MAX_GOALS, fit, score_matrix
from matches import load_matches

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"
ROUNDS = ["Playoffs", "Round of 16", "Quarterfinals", "Semifinals", "Final"]
FIRST_SEASON = "2012-13"  # 2011-12 is the warm-up season
LAST_AWAY_GOALS_SEASON = "2020-21"
EXTRA_TIME_SHARE = 1 / 3  # 30 minutes is a third of 90


def extra_time_split(lam, nu):
    """Chances that extra time is won by the home side, won by the away side, or level."""
    goals = np.arange(MAX_GOALS + 1)
    home = poisson.pmf(goals, lam * EXTRA_TIME_SHARE)
    away = poisson.pmf(goals, nu * EXTRA_TIME_SHARE)
    grid = np.outer(home, away)
    return np.tril(grid, -1).sum(), np.triu(grid, 1).sum(), grid


def single_match_outcomes(lam, nu, rho):
    """A one-off match, in pieces: the chance the first-named team wins in normal time, the other
    team wins in normal time, it is level after 90 minutes, and (if level) that the first-named
    team goes through after extra time and penalties."""
    grid = score_matrix(np.array([lam]), np.array([nu]), rho)[0]
    win, lose, draw = np.tril(grid, -1).sum(), np.triu(grid, 1).sum(), np.trace(grid)
    et_win, et_loss, _ = extra_time_split(lam, nu)
    return win, lose, draw, et_win + 0.5 * (1 - et_win - et_loss)


def single_match(lam, nu, rho):
    """Chance the first-named team goes through a one-off match (extra time, then penalties)."""
    win, _, draw, from_level = single_match_outcomes(lam, nu, rho)
    return win + draw * from_level


def two_leg_outcomes(lam1, nu1, lam2, nu2, rho, away_goals_rule):
    """Two legs, in pieces: the chance team A is through without needing extra time, the chance
    team B is, the chance it is still level (so extra time is played), and, if level, the chance
    A goes through. Leg 1: A at home (lam1 = A's goals, nu1 = B's). Leg 2: B at home (lam2 = B's
    goals, nu2 = A's)."""
    g1 = score_matrix(np.array([lam1]), np.array([nu1]), rho)[0]  # [A goals, B goals]
    g2 = score_matrix(np.array([lam2]), np.array([nu2]), rho)[0]  # [B goals, A goals]
    i, j, k, l = np.meshgrid(*[np.arange(MAX_GOALS + 1)] * 4, indexing="ij")
    p = g1[:, :, None, None] * g2[None, None, :, :]
    agg_a, agg_b = i + l, j + k
    a_wins = agg_a > agg_b
    b_wins = agg_b > agg_a
    level = agg_a == agg_b
    if away_goals_rule:
        a_wins = a_wins | (level & (l > j))
        b_wins = b_wins | (level & (l < j))
        level = level & (l == j)
    p_a, p_b, p_level = p[a_wins].sum(), p[b_wins].sum(), p[level].sum()

    # Extra time in leg 2: B at home. With the away-goals rule, a level extra time
    # with goals (1-1, 2-2...) goes to A, who scored them away.
    et_b, et_a, et_grid = extra_time_split(lam2, nu2)
    et_level_scoring = np.trace(et_grid) - et_grid[0, 0]
    if away_goals_rule:
        a_after_et = et_a + et_level_scoring + 0.5 * et_grid[0, 0]
    else:
        a_after_et = et_a + 0.5 * np.trace(et_grid)
    return p_a, p_b, p_level, a_after_et


def two_legs(lam1, nu1, lam2, nu2, rho, away_goals_rule):
    """Chance team A goes through (see two_leg_outcomes for the legs)."""
    p_a, _, p_level, a_after_et = two_leg_outcomes(lam1, nu1, lam2, nu2, rho, away_goals_rule)
    return p_a + p_level * a_after_et


def ties_table(matches):
    cl = matches[(matches.competition == "CL") & matches["round"].isin(ROUNDS)
                 & (matches.season >= FIRST_SEASON)].copy()
    cl["pair"] = [frozenset((h, a)) for h, a in zip(cl.home, cl.away)]
    ties = []
    for (season, rnd, _), legs in cl.groupby(["season", "round", "pair"], sort=False):
        legs = legs.sort_values("date")
        ties.append((season, rnd, legs))
    return ties


def goals_after(row, side):
    """A team's goals in a match including extra time."""
    if row.extra_time:
        return int(row.home_goals_aet if side == "home" else row.away_goals_aet)
    return int(row.home_goals if side == "home" else row.away_goals)


def actual_winner(legs, away_goals_rule):
    last = legs.iloc[-1]
    if len(legs) == 1:
        h, a = goals_after(last, "home"), goals_after(last, "away")
        if h != a:
            return last.home if h > a else last.away
        return last.home if last.home_pens > last.away_pens else last.away
    first = legs.iloc[0]
    team_a, team_b = first.home, first.away
    agg_a = goals_after(first, "home") + goals_after(last, "away")
    agg_b = goals_after(first, "away") + goals_after(last, "home")
    if agg_a != agg_b:
        return team_a if agg_a > agg_b else team_b
    if away_goals_rule:
        away_a, away_b = goals_after(last, "away"), goals_after(first, "away")
        if away_a != away_b:
            return team_a if away_a > away_b else team_b
    return last.home if last.home_pens > last.away_pens else last.away


def tie_scores(matches):
    """What happened in every knockout tie, keyed like knockout_ties.csv by (season, round,
    team_a, team_b). `legs` has the score of each match with team_a's goals first, counting extra
    time. `aet`: the last match went to extra time. `pens`: the shoot-out, team_a first. `away`:
    the two legs finished level on goals and the away-goals rule decided it."""
    scores = {}
    for season, rnd, legs in ties_table(matches):
        first, last = legs.iloc[0], legs.iloc[-1]
        team_a = first.home

        def goals(row):
            home, away = goals_after(row, "home"), goals_after(row, "away")
            return [home, away] if row.home == team_a else [away, home]

        record = {"legs": [goals(row) for _, row in legs.iterrows()]}
        if last.extra_time:
            record["aet"] = True
        if pd.notna(last.home_pens):
            pens = [int(last.home_pens), int(last.away_pens)]
            record["pens"] = pens if last.home == team_a else pens[::-1]
        elif len(legs) == 2 and season <= LAST_AWAY_GOALS_SEASON:
            (a1, b1), (a2, b2) = record["legs"]
            if a1 + a2 == b1 + b2:  # level on goals: the team that scored more away goals went through
                record["away"] = True
        scores[(season, rnd, team_a, first.away)] = record
    return scores


def main():
    RESULTS.mkdir(exist_ok=True)
    settings = pd.read_csv(RESULTS / "dixon_coles_settings.csv").iloc[0]
    fit_settings = dict(xi=settings.xi, prior_weight=settings.prior_weight, newcomer=settings.newcomer)
    rho, newcomer = settings.rho, settings.newcomer
    matches = load_matches()

    fits = {}
    rows = []
    for season, rnd, legs in ties_table(matches):
        first = legs.iloc[0]
        if len(legs) == 1 and not first.neutral:
            continue  # a two-legged tie whose second leg hasn't been played yet
        when = first.date
        if when not in fits:
            fits[when] = fit(matches[matches.date < when], when, **fit_settings)
        model = fits[when]
        team_a, team_b = first.home, first.away
        away_rule = season <= LAST_AWAY_GOALS_SEASON
        if len(legs) == 1:
            lam, nu = model.expected_goals(team_a, team_b, bool(first.neutral), newcomer)
            p_a = single_match(lam, nu, rho)
        else:
            lam1, nu1 = model.expected_goals(team_a, team_b, False, newcomer)
            lam2, nu2 = model.expected_goals(team_b, team_a, False, newcomer)
            p_a = two_legs(lam1, nu1, lam2, nu2, rho, away_rule)
        winner = actual_winner(legs, away_rule)
        rows.append({"season": season, "round": rnd, "team_a": team_a, "team_b": team_b,
                     "p_a": p_a, "winner": winner,
                     "p_winner": p_a if winner == team_a else 1 - p_a})
    ties = pd.DataFrame(rows)

    # Check: every tie winner should appear in the next round of the same season.
    problems = []
    for season, group in ties.groupby("season"):
        for here, nxt in zip(ROUNDS[:-1], ROUNDS[1:]):
            winners = set(group.winner[group["round"] == here])
            later = set(group.team_a[group["round"] == nxt]) | set(group.team_b[group["round"] == nxt])
            if winners and later and winners != (winners & later):
                problems.append(f"{season} {here}: {sorted(winners - later)}")
    print("Winner check:", "all tie winners appear in the next round" if not problems else problems)

    favourite_p = np.maximum(ties.p_a, 1 - ties.p_a)
    favourite_won = ties.p_winner >= 0.5
    outcome_a = (ties.winner == ties.team_a).astype(float)
    tie_brier = np.mean((ties.p_a - outcome_a) ** 2)
    print(f"\n{len(ties)} knockout ties, {FIRST_SEASON} to {ties.season.max()}")
    print(f"The model's favourite went through in {favourite_won.mean():.1%} of ties; "
          f"the model expected {favourite_p.mean():.1%} (calibration check)")
    print(f"Average chance the model gave the underdog: {1 - favourite_p.mean():.1%}")
    print(f"Average chance the model gave the team that actually went through: {ties.p_winner.mean():.1%}")
    print(f"Tie Brier score: {tie_brier:.4f} (a coin flip scores 0.25)")

    by_round = ties.groupby("round").agg(ties=("p_a", "size"),
                                         favourite_expected=("p_a", lambda p: np.maximum(p, 1 - p).mean()),
                                         favourite_won=("p_winner", lambda p: (p >= 0.5).mean()))
    print("\nBy round:")
    print(by_round.reindex([r for r in ROUNDS if r in by_round.index]).to_string(float_format=lambda v: f"{v:.1%}"))

    finals = ties[ties["round"] == "Final"]
    champions = []
    for final in finals.itertuples():
        path = ties[(ties.season == final.season) & (ties.winner == final.winner)]
        champions.append({"season": final.season, "champion": final.winner, "ties": len(path),
                          "path_probability": path.p_winner.prod(),
                          "weakest_tie": path.loc[path.p_winner.idxmin(), "round"],
                          "weakest_tie_p": path.p_winner.min()})
    champions = pd.DataFrame(champions)
    print("\nChampions: the chance of winning every tie they actually played, judged before each tie")
    print(champions.to_string(index=False, float_format=lambda v: f"{v:.1%}"))

    longshots = ties.nsmallest(8, "p_winner")
    print("\nBiggest upsets (lowest chance for the team that went through):")
    print(longshots[["season", "round", "winner", "team_a", "team_b", "p_winner"]].to_string(
        index=False, float_format=lambda v: f"{v:.1%}"))

    ties.to_csv(RESULTS / "knockout_ties.csv", index=False, float_format="%.4f")
    champions.to_csv(RESULTS / "champions_path.csv", index=False, float_format="%.6f")  # more than 4: some runs sit on a rounding boundary
    champions_chart(champions, RESULTS / "champions_path.png")
    print(f"\nSaved knockout_ties.csv, champions_path.csv and champions_path.png in {RESULTS}")


def champions_chart(champions, path):
    fig, ax = plt.subplots(figsize=(8, 4.5))
    labels = [f"{s}\n{c}" for s, c in zip(champions.season, champions.champion)]
    ax.bar(range(len(champions)), champions.path_probability * 100, color="#2a6fdb")
    for x, p in enumerate(champions.path_probability):
        ax.text(x, p * 100 + 0.8, f"{p:.0%}", ha="center", fontsize=8)
    ax.set_xticks(range(len(champions)))
    ax.set_xticklabels(labels, rotation=60, ha="right", fontsize=7)
    ax.set_ylabel("Chance of winning every tie (%)")
    ax.set_title("How likely was each champion's run, judged before each tie?")
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


if __name__ == "__main__":
    main()
