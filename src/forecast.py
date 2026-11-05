"""Who will win this season's Champions League?

The goals model that rates every club (Dixon–Coles) plays out the rest of the season, 100,000 times:

1. Ratings are fitted on everything played up to now, including the league-phase matches already
   played this season (read from Wikipedia: openfootball has not published the season yet).
2. Each league-phase match still to play gets a random scoreline from the model's chances. The
   table is sorted the way UEFA sorts it: points, goal difference, goals scored, away goals scored,
   wins, away wins. What UEFA looks at after that (opponents' results, discipline, coefficients) is
   left to chance.
3. The top eight go straight to the round of 16, positions 9 to 24 play off for the other eight
   places, and everyone is then drawn into a fixed bracket. Every tie is decided by the exact
   chance of going through that src/knockouts.py uses for two legs (extra time, then penalties),
   or for the one-off final. Clubs do not change strength during the season in these simulations.

The rules are the ones of 2025-26, and the draws are random with no country protection, as they
were then. The bracket below was checked against that season's results.

Run after scripts/download_data.py, by hand or on a schedule; the output is results/forecast.json.
"""

import argparse
import copy
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from dixon_coles import MAX_GOALS, fit, score_matrix
from knockouts import single_match, two_legs
from matches import load_matches
from parse_league_phase import check_league_phase, data_path, load_league_phase, season_title
from update import season_of, settings

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "results" / "forecast.json"
HISTORY = ROOT / "results" / "forecast_history.csv"  # every day's forecast, one row per club, kept so the odds can be charted
NAMES = ROOT / "data" / "wikipedia_names.csv"

SIMULATIONS = 100_000
SEED = 2026
# The play-offs start about three weeks after the league phase ends. From then on the forecast
# would need the play-off results, which it does not read, so it stops.
KNOCKOUTS_START_DAYS = 20

# The knockout phase. Positions are counted from 0, so 0 is first place in the league phase.
# A play-off section is (seeded positions, unseeded positions); its two winners meet two of the top
# eight in the round of 16, in the order of ROUND_OF_16_SEEDS.
PLAYOFFS = (((8, 9), (22, 23)), ((10, 11), (20, 21)), ((12, 13), (18, 19)), ((14, 15), (16, 17)))
ROUND_OF_16_SEEDS = ((6, 7), (4, 5), (2, 3), (0, 1))
# Who meets whom after that is fixed. A team that beats a better seed takes that seed's place, and
# the better place hosts the second leg, so a tie is always listed with the better place first.
QUARTER_FINALS = ((0, 6), (1, 7), (2, 5), (3, 4))
SEMI_FINALS = ((1, 2), (0, 3))  # which quarter-final winners meet

STAGES = ("top8", "top24", "last16", "quarter", "semi", "final", "win")


class NoForecast(Exception):
    """The season is not at a stage this forecast covers, or its data cannot be used."""

    def __init__(self, reason, over=False):
        super().__init__(reason)
        self.over = over  # True: the stage this forecast covers has ended; False: no data, or data that is broken


# ---------- reading the season ----------

def resolve_names(league, known):
    """One model name per club, learnt from the Wikipedia article's titles. Returns the table of
    matches with the names changed, and the clubs the model has never seen play."""
    table = pd.read_csv(NAMES)
    by_page = dict(zip(table.wikipedia_page, table.canonical))
    big_five = {"ENG", "ESP", "GER", "ITA", "FRA"}
    names = {}
    for side in ("home", "away"):
        for page, shown, country in zip(league[f"{side}_page"], league[side], league[f"{side}_country"]):
            if page in by_page:
                names[page] = by_page[page]
            elif shown in known:
                names[page] = shown
            elif country not in big_five:
                names[page] = f"{shown} ({country})"  # how matches.py names clubs outside the big five
            else:
                names[page] = shown
    league = league.assign(home=league.home_page.map(names), away=league.away_page.map(names))
    clubs = sorted(set(league.home) | set(league.away))
    return league, [club for club in clubs if club not in known]


def standings(league, teams):
    """Everything UEFA's table order looks at, from the matches played so far."""
    index = {team: i for i, team in enumerate(teams)}
    table = {key: np.zeros(len(teams), dtype=np.int64)
             for key in ("played", "points", "goals_for", "goals_against", "away_goals_for", "wins", "away_wins")}
    for row in league[league.home_goals.notna()].itertuples():
        for team, scored, conceded, away in ((row.home, row.home_goals, row.away_goals, False),
                                             (row.away, row.away_goals, row.home_goals, True)):
            i = index[team]
            table["played"][i] += 1
            table["goals_for"][i] += int(scored)
            table["goals_against"][i] += int(conceded)
            table["away_goals_for"][i] += int(scored) if away else 0
            if scored > conceded:
                table["points"][i] += 3
                table["wins"][i] += 1
                table["away_wins"][i] += int(away)
            elif scored == conceded:
                table["points"][i] += 1
    return table


# ---------- the model's chances ----------

def scoreline_cdfs(model, teams, fixtures, rho, newcomer):
    """For each match still to play, the cumulative chance of every scoreline (home goals 0 to 10,
    then away goals 0 to 10, row by row)."""
    lam, nu = zip(*(model.expected_goals(teams[h], teams[a], False, newcomer) for h, a in fixtures))
    grid = score_matrix(np.array(lam), np.array(nu), rho)
    return np.cumsum(grid.reshape(len(fixtures), -1), axis=1)


def tie_chances(model, teams, rho, newcomer):
    """through[a, b]: the chance a goes through a two-legged tie with b, when a hosts the first leg.
    final[a, b]: the chance a beats b in a one-off match on neutral ground."""
    count = len(teams)
    through, final = np.zeros((count, count)), np.full((count, count), 0.5)
    for a in range(count):
        for b in range(count):
            if a == b:
                continue
            lam1, nu1 = model.expected_goals(teams[a], teams[b], False, newcomer)
            lam2, nu2 = model.expected_goals(teams[b], teams[a], False, newcomer)
            through[a, b] = two_legs(lam1, nu1, lam2, nu2, rho, False)
            lam, nu = model.expected_goals(teams[a], teams[b], True, newcomer)
            final[a, b] = single_match(lam, nu, rho)
    return through, final


# ---------- playing the season ----------

def league_phase(table, fixtures, cdfs, n, rng):
    """Play the rest of the league phase n times. Returns order[r, s]: the team in position r + 1
    in simulated season s."""
    teams = len(table["points"])
    points, goals_for, goals_against, away_for, wins, away_wins = (
        np.tile(table[key].astype(np.int32)[:, None], (1, n))
        for key in ("points", "goals_for", "goals_against", "away_goals_for", "wins", "away_wins"))
    width = MAX_GOALS + 1
    for (home, away), cdf in zip(fixtures, cdfs):
        scoreline = np.minimum(np.searchsorted(cdf, rng.random(n)), width * width - 1)
        home_goals, away_goals = scoreline // width, scoreline % width
        home_won, away_won, level = home_goals > away_goals, away_goals > home_goals, home_goals == away_goals
        points[home] += 3 * home_won + level
        points[away] += 3 * away_won + level
        goals_for[home] += home_goals
        goals_against[home] += away_goals
        goals_for[away] += away_goals
        goals_against[away] += home_goals
        away_for[away] += away_goals
        wins[home] += home_won
        wins[away] += away_won
        away_wins[away] += away_won
    # One number that sorts like UEFA's table: each tie-breaker only counts when the ones before it are level.
    key = ((((points * 200.0 + (goals_for - goals_against) + 100) * 100 + goals_for) * 100 + away_for) * 10 + wins) * 10 + away_wins
    key += rng.random((teams, n)) * 0.5
    return np.argsort(-key, axis=0)


def knockouts(order, through, final, rng):
    """Play the knockout phase for every simulated season at once. Returns, for each stage, the
    teams that reached it (an array with one column per simulated season)."""
    n = order.shape[1]

    def tie(first_leg_host, second_leg_host):
        return np.where(rng.random(n) < through[first_leg_host, second_leg_host], first_leg_host, second_leg_host)

    # Play-offs. A draw settles which of the two seeded teams in a section meets which unseeded one.
    winners = []
    for seeded, unseeded in PLAYOFFS:
        swap = rng.random(n) < 0.5
        first = np.where(swap, order[unseeded[1]], order[unseeded[0]])
        second = np.where(swap, order[unseeded[0]], order[unseeded[1]])
        winners.append((tie(first, order[seeded[0]]), tie(second, order[seeded[1]])))

    # Round of 16: the seeded team hosts the second leg. Whoever wins takes the seed's place.
    place = {}
    for (low, high), (first, second) in zip(ROUND_OF_16_SEEDS, winners):
        swap = rng.random(n) < 0.5
        place[low] = tie(np.where(swap, second, first), order[low])
        place[high] = tie(np.where(swap, first, second), order[high])

    quarter = {}
    for better, worse in QUARTER_FINALS:
        quarter[better] = tie(place[worse], place[better])
    semi = {}
    for better, worse in SEMI_FINALS:
        semi[better] = tie(quarter[worse], quarter[better])
    finalists = [semi[better] for better, _ in SEMI_FINALS]
    champion = np.where(rng.random(n) < final[finalists[0], finalists[1]], finalists[0], finalists[1])

    return {
        "top8": order[:8], "top24": order[:24],
        "last16": np.concatenate([order[:8]] + [np.stack(pair) for pair in winners]),
        "quarter": np.stack(list(place.values())), "semi": np.stack(list(quarter.values())),
        "final": np.stack(list(semi.values())), "win": champion[None, :]}


def nudged(model, noise, rng):
    """A copy of the model with every club's attack and defence strength moved by a random amount (a normal
    with this standard deviation, in log-goals). The ratings are estimates, not facts: playing the season out
    with them as exact makes the favourites too sure."""
    other = copy.copy(model)
    other.attack = model.attack + rng.normal(0, noise, len(model.attack))
    other.defence = model.defence + rng.normal(0, noise, len(model.defence))
    return other


def simulate(table, fixtures, cdfs, through, final, n=SIMULATIONS, seed=SEED):
    """How often each team reaches each stage: {stage: array with one share per team}."""
    rng = np.random.default_rng(seed)
    order = league_phase(table, fixtures, cdfs, n, rng)
    reached = knockouts(order, through, final, rng)
    teams = len(table["points"])
    return {stage: np.bincount(teams_at.ravel(), minlength=teams) / n for stage, teams_at in reached.items()}


# ---------- putting it together ----------

def forecast(as_of=None, n=SIMULATIONS, seed=SEED, season=None, history=None, league=None, noise=0.0, worlds=1):
    """The forecast as plain data, ready for results/forecast.json. Raises NoForecast when the season
    is not at a stage this covers. `league` is the season's league phase as parse_league_phase reads it
    (read from the downloaded article if not given); `history` is the matches to fit on. With `noise`, the
    simulations are split over `worlds` versions of the ratings, each nudged at random by that much."""
    as_of = pd.Timestamp(as_of or datetime.now(timezone.utc).date())
    season = season or season_of(pd.Series([as_of])).iloc[0]
    league = load_league_phase(season) if league is None else league
    if league is None:
        raise NoForecast(f"{data_path(season).name} has not been downloaded")
    problem = check_league_phase(league)
    if problem:
        raise NoForecast(f"{season_title(season)}: {problem}")

    history = load_matches() if history is None else history
    known = set(history.home) | set(history.away)
    league, new_clubs = resolve_names(league, known)
    if len(set(league.home) | set(league.away)) != len(set(league.home_page) | set(league.away_page)):
        raise NoForecast("two clubs were given the same name: check data/wikipedia_names.csv")

    played = league[league.home_goals.notna()]
    left = league[league.home_goals.isna()]
    if left.empty and as_of > league.date.max() + pd.Timedelta(days=KNOCKOUTS_START_DAYS):
        raise NoForecast("the league phase is over and the knockout phase has begun", over=True)

    # Learn from this season's matches too, unless the main data already has them.
    have = set(zip(history.date, history.home, history.away))
    new = played[np.array([key not in have for key in zip(played.date, played.home, played.away)], dtype=bool)]  # (a bare empty list would pick columns)
    this_season = pd.DataFrame({
        "competition": "CL", "season": season, "date": new.date, "home": new.home, "away": new.away,
        "home_goals": new.home_goals.astype(int), "away_goals": new.away_goals.astype(int), "neutral": False})
    combined = pd.concat([history, this_season], ignore_index=True).sort_values("date", kind="stable").reset_index(drop=True)

    fit_settings, rho = settings()
    model = fit(combined, as_of + pd.Timedelta(days=1), **fit_settings)
    newcomer = fit_settings["newcomer"]

    teams = sorted(set(league.home) | set(league.away))
    index = {team: i for i, team in enumerate(teams)}
    table = standings(league, teams)
    fixtures = np.array([(index[h], index[a]) for h, a in zip(left.home, left.away)], dtype=int).reshape(-1, 2)
    reach = {stage: np.zeros(len(teams)) for stage in STAGES}
    for world in range(worlds if noise else 1):
        version = nudged(model, noise, np.random.default_rng([seed, world])) if noise else model
        share = n // (worlds if noise else 1) + (n % worlds if noise and world == worlds - 1 else 0)
        cdfs = scoreline_cdfs(version, teams, fixtures, rho, newcomer) if len(fixtures) else np.empty((0, (MAX_GOALS + 1) ** 2))
        through, final = tie_chances(version, teams, rho, newcomer)
        found = simulate(table, fixtures, cdfs, through, final, share, seed + world)
        for stage in STAGES:
            reach[stage] += found[stage] * share / n

    country = {}
    for side in ("home", "away"):
        country.update(zip(league[side], league[f"{side}_country"]))
    clubs = []
    for i, team in enumerate(teams):
        clubs.append({
            "club": team, "country": country[team], "played": int(table["played"][i]), "points": int(table["points"][i]),
            "goal_difference": int(table["goals_for"][i] - table["goals_against"][i]),
            **{stage: round(float(reach[stage][i]), 6) for stage in STAGES}})
    clubs.sort(key=lambda c: (-c["win"], -c["final"], -c["semi"], c["club"]))
    return {
        "season": season, "as_of": f"{as_of:%Y-%m-%d}", "simulations": n, "seed": seed,
        "matches": int(len(league)), "played": int(len(played)), "left": int(len(left)),
        "last_match": f"{league.date.max():%Y-%m-%d}",
        "new_clubs": new_clubs,
        "source": f"https://en.wikipedia.org/wiki/{season_title(season)}",
        "clubs": clubs}


def add_to_history(result, path=None):
    """Put a forecast in the history, replacing any earlier one for the same season and day."""
    path = path or HISTORY
    rows = pd.DataFrame([{"season": result["season"], "as_of": result["as_of"], **{k: c[k] for k in ("club", "played", "points", *STAGES)}}
                         for c in result["clubs"]])
    if path.exists():
        old = pd.read_csv(path, dtype={"season": str, "as_of": str})
        old = old[~((old.season == result["season"]) & (old.as_of == result["as_of"]))]
        rows = pd.concat([old, rows], ignore_index=True)
    rows.sort_values(["season", "as_of", "club"]).to_csv(path, index=False, float_format="%.6f")


def backfill(season, n=SIMULATIONS, path=None):
    """Forecasts as they would have stood before the first matchday and after each one played so far,
    so the history starts at the beginning of the season. Uses only what was known at each point."""
    league = load_league_phase(season)
    if league is None:
        raise NoForecast(f"{data_path(season).name} has not been downloaded")
    done = [d for d in sorted(league.matchday.unique()) if league[league.matchday == d].home_goals.notna().all()]
    history = load_matches()
    for after in [0] + done:
        masked = league.copy()
        masked.loc[masked.matchday > after, ["home_goals", "away_goals"]] = np.nan
        as_of = league[league.matchday == after].date.max() if after else league.date.min() - pd.Timedelta(days=1)
        add_to_history(forecast(as_of, n=n, season=season, history=history, league=masked), path)
        print(f"{season}: forecast after matchday {after} ({as_of:%Y-%m-%d}) added to the history")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--as-of", help="forecast as of this date (YYYY-MM-DD); today by default")
    parser.add_argument("--simulations", type=int, default=SIMULATIONS)
    parser.add_argument("--backfill", action="store_true", help="add the forecasts for every matchday played so far to the history")
    args = parser.parse_args(argv)
    try:
        if args.backfill:
            backfill(season_of(pd.Series([pd.Timestamp(args.as_of or datetime.now(timezone.utc).date())])).iloc[0], args.simulations)
        result = forecast(args.as_of, args.simulations)
    except NoForecast as problem:
        # Once the stage it covers is over, an old forecast must not stay on the page. Missing or broken
        # data is another matter: the last forecast stays, with its date, until fresh data arrives.
        if problem.over and OUTPUT.exists():
            OUTPUT.unlink()
        print(f"No forecast: {problem}")
        return 0 if problem.over else 1
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=1, allow_nan=False) + "\n", encoding="utf-8")
    add_to_history(result)
    top = result["clubs"][:3]
    print(f"{result['season']} forecast as of {result['as_of']}: {result['played']} of {result['matches']} league-phase "
          f"matches played, {result['simulations']:,} simulations. Favourites: "
          + ", ".join(f"{c['club']} {c['win']:.1%}" for c in top))
    if result["new_clubs"]:
        print(f"Rated from this season's matches alone (no earlier history): {', '.join(result['new_clubs'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
