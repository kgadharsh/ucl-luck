"""Turn a rating difference into home/draw/away probabilities, and score probabilities.

Ordered logistic model: one latent "how much better is home" score, a * diff,
cut at two points. Below the first cut the away team wins, between the cuts it is
a draw, above the second cut the home team wins.
"""

import numpy as np
from scipy.optimize import minimize
from scipy.special import expit


def ordered_probs(diff, params):
    slope, cut_low, cut_gap = params
    cut_high = cut_low + abs(cut_gap)
    score = slope * np.asarray(diff) / 400
    away = expit(cut_low - score)
    away_or_draw = expit(cut_high - score)
    return np.column_stack([1 - away_or_draw, away_or_draw - away, away])  # home, draw, away


def fit_ordered(diff, outcome):
    """outcome: 0 = home win, 1 = draw, 2 = away win."""
    def loss(params):
        probs = ordered_probs(diff, params)
        return -np.mean(np.log(np.clip(probs[np.arange(len(outcome)), outcome], 1e-12, 1)))
    return minimize(loss, x0=[2.0, -1.0, 1.0], method="Nelder-Mead").x


def outcome_codes(home_goals, away_goals):
    home_goals, away_goals = np.asarray(home_goals), np.asarray(away_goals)
    return np.where(home_goals > away_goals, 0, np.where(home_goals == away_goals, 1, 2))


def brier(probs, outcome):
    """Mean of the summed squared error over home/draw/away. 0 is perfect; lower is better."""
    actual = np.eye(3)[outcome]
    return np.sum((probs - actual) ** 2, axis=1)


def log_loss(probs, outcome):
    """Mean surprise at what actually happened. Lower is better."""
    return -np.log(np.clip(probs[np.arange(len(outcome)), outcome], 1e-12, 1))
