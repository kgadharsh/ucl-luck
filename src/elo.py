"""Elo ratings for every club, updated match by match.

Elo only ever uses matches played before the one it is predicting, so its
ratings are walk-forward by construction. A rating difference becomes
home/draw/away probabilities through an ordered logistic model (see outcomes.py).
"""

import math

import numpy as np

START = 1500.0


def margin_multiplier(goal_difference):
    """Bigger wins move ratings more, with diminishing returns (World Football Elo style)."""
    gd = abs(goal_difference)
    if gd <= 1:
        return 1.0
    if gd == 2:
        return 1.5
    return (11 + gd) / 8


def run_elo(matches, k=20.0, home_advantage=60.0, newcomer_gap=100.0, season_regress=0.0, use_margin=True):
    """Return the pre-match rating difference (home minus away, including home advantage)
    for every match, in the order given. Matches must be sorted by date."""
    ratings = {}
    league_of = {}
    season_seen = None
    diffs = np.empty(len(matches))

    competitions = matches["competition"].to_numpy()
    seasons = matches["season"].to_numpy()
    homes = matches["home"].to_numpy()
    aways = matches["away"].to_numpy()
    home_goals = matches["home_goals"].to_numpy()
    away_goals = matches["away_goals"].to_numpy()
    neutral = matches["neutral"].to_numpy()
    is_league = ~np.isin(competitions, ["CL", "EL"])

    for i in range(len(matches)):
        if seasons[i] != season_seen and is_league[i]:
            season_seen = seasons[i]
            if season_regress and ratings:
                mean = sum(ratings.values()) / len(ratings)
                for team in ratings:
                    ratings[team] += season_regress * (mean - ratings[team])

        home, away = homes[i], aways[i]
        for team in (home, away):
            if team not in ratings:
                ratings[team] = new_rating(team, competitions[i], is_league[i], ratings, league_of, newcomer_gap)
            if is_league[i]:
                league_of[team] = competitions[i]

        diff = ratings[home] - ratings[away] + (0.0 if neutral[i] else home_advantage)
        diffs[i] = diff
        expected = 1 / (1 + 10 ** (-diff / 400))
        goal_difference = home_goals[i] - away_goals[i]
        actual = 1.0 if goal_difference > 0 else 0.5 if goal_difference == 0 else 0.0
        change = k * (margin_multiplier(goal_difference) if use_margin else 1.0) * (actual - expected)
        ratings[home] += change
        ratings[away] -= change
    return diffs, ratings


def new_rating(team, competition, is_league, ratings, league_of, newcomer_gap):
    """A team new to a league starts below that league's average (promoted sides are weaker).
    A club seen only in Europe starts below the overall average."""
    if is_league:
        rivals = [r for t, r in ratings.items() if league_of.get(t) == competition]
        if rivals:
            return float(np.mean(rivals)) - newcomer_gap
        return START
    if ratings:
        return float(np.mean(list(ratings.values()))) - newcomer_gap
    return START


def expected_score(diff):
    return 1 / (1 + 10 ** (-np.asarray(diff) / 400))


if __name__ == "__main__":
    from matches import load_matches

    matches = load_matches()
    diffs, ratings = run_elo(matches)
    top = sorted(ratings.items(), key=lambda item: -item[1])[:15]
    print("Top 15 clubs now:")
    for team, rating in top:
        print(f"  {rating:7.1f}  {team}")
    print(f"\nMean pre-match difference: {diffs.mean():.1f}  (home advantage shows up here)")
    print(f"Elapsed rating spread: {math.floor(min(ratings.values()))} to {math.ceil(max(ratings.values()))}")
