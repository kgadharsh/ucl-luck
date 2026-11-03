"""Dixon–Coles goals model.

Each club has an attack strength a and a defence strength d. In a match,
    home goals ~ Poisson(exp(mu + home + a_home - d_away))
    away goals ~ Poisson(exp(mu + a_away - d_home))
with a small correction (rho) for how often 0-0, 1-0, 0-1 and 1-1 happen.
Recent matches count more: a match t days ago has weight exp(-xi * t).

Fitting uses alternating closed-form updates for a weighted Poisson model, with
a gamma prior that pulls clubs with little data towards a prior strength. That is
fast enough to refit every week on a laptop.
"""

import numpy as np
from scipy.stats import poisson

MAX_GOALS = 10
EUROPE = ("CL", "EL")


class Fit:
    def __init__(self, teams, attack, defence, mu, home, prior_attack, prior_defence):
        self.index = {team: i for i, team in enumerate(teams)}
        self.attack, self.defence = attack, defence
        self.mu, self.home = mu, home
        self.prior_attack, self.prior_defence = prior_attack, prior_defence

    def strengths(self, team, newcomer):
        i = self.index.get(team)
        if i is None:
            return (-newcomer, -newcomer)
        return self.attack[i], self.defence[i]

    def expected_goals(self, home, away, neutral, newcomer):
        a_h, d_h = self.strengths(home, newcomer)
        a_a, d_a = self.strengths(away, newcomer)
        lam = np.exp(self.mu + (0 if neutral else self.home) + a_h - d_a)
        nu = np.exp(self.mu + a_a - d_h)
        return lam, nu


def fit(history, ref_date, xi=0.002, prior_weight=3.0, newcomer=0.2, window_days=1100, iterations=40):
    """Fit on matches played before ref_date.

    newcomer: prior shift (in log-goals) for clubs new to a league or seen only in
    Europe, which are usually weaker than an average big-five club."""
    days = (ref_date - history["date"]).dt.days.to_numpy()
    keep = (days > 0) & (days <= window_days)
    data = history[keep]
    weight = np.exp(-xi * days[keep])

    teams = np.array(sorted(set(data.home) | set(data.away)))
    index = {team: i for i, team in enumerate(teams)}
    hi = np.array([index[t] for t in data.home])
    ai = np.array([index[t] for t in data.away])
    x = data.home_goals.to_numpy(float)
    y = data.away_goals.to_numpy(float)
    at_home = (~data.neutral.to_numpy()).astype(float)

    prior = prior_strength(data, teams, newcomer)
    a, d = prior.copy(), prior.copy()
    n = len(teams)
    mu, home = np.log(max((x + y).mean() / 2, 0.1)), 0.25

    scored = np.bincount(hi, weight * x, n) + np.bincount(ai, weight * y, n)
    conceded = np.bincount(ai, weight * x, n) + np.bincount(hi, weight * y, n)
    for _ in range(iterations):
        lam = np.exp(mu + home * at_home + a[hi] - d[ai])
        nu = np.exp(mu + a[ai] - d[hi])
        base_a = np.bincount(hi, weight * lam / np.exp(a[hi]), n) + np.bincount(ai, weight * nu / np.exp(a[ai]), n)
        a = np.log((scored + prior_weight * np.exp(prior)) / (base_a + prior_weight))

        lam = np.exp(mu + home * at_home + a[hi] - d[ai])
        nu = np.exp(mu + a[ai] - d[hi])
        base_d = np.bincount(ai, weight * lam * np.exp(d[ai]), n) + np.bincount(hi, weight * nu * np.exp(d[hi]), n)
        d = -np.log((conceded + prior_weight * np.exp(-prior)) / (base_d + prior_weight))

        lam = np.exp(mu + home * at_home + a[hi] - d[ai])
        nu = np.exp(mu + a[ai] - d[hi])
        mu += np.log(np.sum(weight * (x + y)) / np.sum(weight * (lam + nu)))
        lam = np.exp(mu + home * at_home + a[hi] - d[ai])
        home += np.log(np.sum(weight * at_home * x) / np.sum(weight * at_home * lam))

    return Fit(teams, a, d, mu, home, prior, prior)


def prior_strength(data, teams, newcomer):
    """Clubs that have played in a big-five league in the window start at 0 (average);
    everyone else (promoted sides with little history, clubs seen only in Europe) starts lower."""
    league = ~data.competition.isin(EUROPE)
    regulars = set(data.home[league]) | set(data.away[league])
    counts = data[league].home.value_counts().add(data[league].away.value_counts(), fill_value=0)
    prior = np.zeros(len(teams))
    for i, team in enumerate(teams):
        if team not in regulars or counts.get(team, 0) < 10:
            prior[i] = -newcomer
    return prior


def score_matrix(lam, nu, rho):
    """Probability of every scoreline up to MAX_GOALS each, for arrays of matches. Shape (n, 11, 11)."""
    goals = np.arange(MAX_GOALS + 1)
    home = poisson.pmf(goals[None, :], np.asarray(lam)[:, None])
    away = poisson.pmf(goals[None, :], np.asarray(nu)[:, None])
    grid = home[:, :, None] * away[:, None, :]
    grid[:, 0, 0] *= 1 - lam * nu * rho
    grid[:, 0, 1] *= 1 + lam * rho
    grid[:, 1, 0] *= 1 + nu * rho
    grid[:, 1, 1] *= 1 - rho
    return grid / grid.sum(axis=(1, 2), keepdims=True)


def outcome_probs(lam, nu, rho):
    grid = score_matrix(lam, nu, rho)
    home = np.tril(np.ones((MAX_GOALS + 1, MAX_GOALS + 1)), -1)  # home goals > away goals
    p_home = (grid * home).sum(axis=(1, 2))
    p_draw = np.trace(grid, axis1=1, axis2=2)
    return np.column_stack([p_home, p_draw, 1 - p_home - p_draw])


def walk_forward_goals(matches, start, end, refit_days=7, **settings):
    """Expected goals for every match between start and end, refitting every refit_days
    on matches played before each refit date only."""
    lam = np.full(len(matches), np.nan)
    nu = np.full(len(matches), np.nan)
    newcomer = settings.get("newcomer", 0.2)
    dates = matches["date"]
    current = start
    while current < end:
        upcoming = ((dates >= current) & (dates < current + np.timedelta64(refit_days, "D"))).to_numpy()
        if upcoming.any():
            model = fit(matches[dates < current], current, **settings)
            for i in np.flatnonzero(upcoming):
                row = matches.iloc[i]
                lam[i], nu[i] = model.expected_goals(row.home, row.away, row.neutral, newcomer)
        current = current + np.timedelta64(refit_days, "D")
    return lam, nu
