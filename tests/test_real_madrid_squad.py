"""The line-up check on Real Madrid: its arithmetic on small made-up data, its saved results against
the ties on the page, and (when Transfermarkt's files are present) that it reproduces."""

import json

import numpy as np
import pandas as pd
import pytest

from conftest import ROOT, needs_raw_data, needs_transfermarkt
from real_madrid_squad import FLOOR, is_knockout, link_matches, ols_robust, xi_values


@pytest.fixture(scope="module")
def saved():
    return json.loads((ROOT / "results" / "real_madrid_squad.json").read_text(encoding="utf-8"))


# ---------- the arithmetic ----------

def test_an_elevens_value_uses_each_players_latest_fresh_valuation():
    lineups = pd.DataFrame(
        [{"game_id": 1, "club_id": 10, "player_id": p, "date": "2020-01-01", "type": "starting_lineup"} for p in range(1, 12)]
        + [{"game_id": 1, "club_id": 10, "player_id": 99, "date": "2020-01-01", "type": "substitutes"}]  # a substitute isn't in the eleven
        + [{"game_id": 2, "club_id": 20, "player_id": p, "date": "2020-01-01", "type": "starting_lineup"} for p in range(21, 31)])  # only ten players
    valuations = pd.DataFrame([
        {"player_id": 1, "date": "2019-06-01", "market_value_in_eur": 10_000_000},
        {"player_id": 1, "date": "2019-12-01", "market_value_in_eur": 20_000_000},  # the latest before the match
        {"player_id": 1, "date": "2020-06-01", "market_value_in_eur": 99_000_000},  # after the match: must not be used
        {"player_id": 2, "date": "2017-01-01", "market_value_in_eur": 50_000_000},  # three years old: too stale to trust
        {"player_id": 99, "date": "2019-12-01", "market_value_in_eur": 80_000_000},
    ])
    xi = xi_values(lineups, valuations)
    assert list(xi.game_id) == [1]  # the ten-man "eleven" is dropped
    assert xi.xi_value.iloc[0] == 20_000_000 + 10 * FLOOR  # player 1, then ten players at the floor


def test_matches_with_the_same_date_and_score_are_told_apart_by_club():
    day = pd.Timestamp("2020-03-01")
    ours = pd.DataFrame({"date": [day, day, pd.Timestamp("2020-03-02"), pd.Timestamp("2020-03-03")],
                         "home": ["A", "C", "A", "B"], "away": ["B", "D", "C", "D"],
                         "home_goals": [1, 1, 2, 3], "away_goals": [0, 0, 1, 0]})
    theirs = pd.DataFrame({"game_id": [1, 2, 3, 4], "date": [day, day, pd.Timestamp("2020-03-02"), pd.Timestamp("2020-03-03")],
                           "home_club_id": [101, 103, 101, 102], "away_club_id": [102, 104, 103, 104],
                           "home_club_goals": [1, 1, 2, 3], "away_club_goals": [0, 0, 1, 0]})
    # the two 1-0 games on 1 March share a date and score; the other days teach us which id is which club
    assert link_matches(ours, theirs) == {0: 1, 1: 2, 2: 3, 3: 4}


def test_robust_regression_matches_least_squares_and_gives_positive_errors():
    rng = np.random.default_rng(1)
    x = rng.normal(size=200)
    y = 1.0 + 2.0 * x + rng.normal(scale=0.5, size=200)
    beta, se = ols_robust([x], y)
    assert beta == pytest.approx(np.linalg.lstsq(np.column_stack([np.ones(200), x]), y, rcond=None)[0])
    assert (se > 0).all() and beta[1] == pytest.approx(2.0, abs=0.2) and se[1] < 0.1


@pytest.mark.parametrize("name, knockout", [
    ("Last 16 1st Leg", True), ("last 16 2nd leg", True), ("Quarter-Finals 1st leg", True), ("Semi-Finals", True), ("Final", True),
    ("intermediate stage 1st leg", True), ("Group A", False), ("Group Stage", False)])
def test_transfermarkts_round_names_are_sorted_into_knockouts_and_groups(name, knockout):
    assert is_knockout(name) is knockout


# ---------- the saved results ----------

def test_saved_results_agree_with_the_ties_and_the_other_analysis(saved, data):
    assert saved["through_season"] == data["real_madrid"]["through_season"] == data["headline"]["last_season"]
    assert data["real_madrid"]["squad"] == saved
    # Real's knockout matches in the squad check are those of the other analysis, minus 2012-13 (no starting elevens exist for it).
    before = sum(len(t["legs"]) for t in data["ties"] if t["season"] == "2012-13" and "Real Madrid" in (t["team_a"], t["team_b"]))
    others = {s["label"]: s for s in data["real_madrid"]["stages"]}
    assert saved["strength"]["real"]["knockouts"]["matches"] == others["Champions League knockouts"]["matches"] - before


def test_rotation_numbers_are_consistent(saved):
    rot = saved["rotation"]
    table = rot["table"]
    gaps = [row["gap"] for row in table]
    assert gaps == sorted(gaps, reverse=True) and len(table) == rot["clubs"]
    real = next(row for row in table if row["club"] == "Real Madrid")
    assert real["gap"] == pytest.approx(real["knockouts"] - real["league"]) and real["gap"] == pytest.approx(rot["real"]["gap"])
    assert rot["real_rank"] == 1 + sum(row["gap"] > real["gap"] for row in table)
    others = [row["gap"] for row in table if row["club"] != "Real Madrid"]
    assert rot["others"]["gap"] == pytest.approx(np.mean(others)) and rot["others"]["clubs"] == len(others)
    assert 0.5 < real["league"] < real["knockouts"] <= 1.0  # a share of the best eleven, fuller in knockouts


def test_nearly_every_champions_league_match_was_linked(saved):
    assert saved["matches_linked"] >= saved["matches_in_data"] - 3  # all but a few, and the check inside the script says none disagree
    assert saved["strength"]["matches"] > 1700


@needs_raw_data
@needs_transfermarkt
def test_saved_results_are_what_the_script_produces_today(saved):
    from real_madrid_squad import analyse

    def same(fresh, old, where="result"):
        if isinstance(fresh, dict):
            assert fresh.keys() == old.keys(), where
            for key in fresh:
                same(fresh[key], old[key], f"{where}.{key}")
        elif isinstance(fresh, list):
            assert len(fresh) == len(old), where
            for i, (a, b) in enumerate(zip(fresh, old)):
                same(a, b, f"{where}[{i}]")
        elif isinstance(fresh, float):
            assert fresh == pytest.approx(old, rel=1e-6, abs=1e-9), where
        else:
            assert fresh == old, where

    same(json.loads(json.dumps(analyse())), saved)
