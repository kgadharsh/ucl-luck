"""The forecast backtest: its scoring arithmetic, what it counts as having happened, and its saved results."""

import json

import numpy as np
import pandas as pd
import pytest

import backtest_forecast as bt
from conftest import ROOT, needs_raw_data
from parse_league_phase import check_league_phase

RESULTS = ROOT / "results"
SIZE = bt.SIZE


def frame(rows):
    return pd.DataFrame(rows, columns=["season", "after", "club", "stage", "p", "happened", "decided"])


def titles(**changes):
    row = {"season": "2024-25", "after": 4, "champion": "A", "p": 0.2, "rank": 2, "favourite": "B", "favourite_p": 0.3, **changes}
    return pd.DataFrame([row])


# ---------- the scoring ----------

def test_a_forecast_that_knew_everything_scores_zero_and_one_that_knew_nothing_scores_the_baseline():
    certain = [("s", 2, f"c{i}", "top8", 1.0 if i < 8 else 0.0, i < 8, False) for i in range(36)]
    blind = [("s", 2, f"c{i}", "top24", 24 / 36, i < 24, False) for i in range(36)]
    summary = bt.summarise(frame(certain + blind), titles())
    by_stage = {row["stage"]: row for row in summary["by_stage"] if row["clubs"]}
    assert by_stage["top8"]["brier"] == 0 and by_stage["top8"]["skill"] == pytest.approx(1)
    assert by_stage["top24"]["brier"] == pytest.approx(by_stage["top24"]["knowing_nothing"]) and by_stage["top24"]["skill"] == pytest.approx(0, abs=1e-12)
    assert by_stage["top8"]["knowing_nothing"] == pytest.approx((8 / 36) * (28 / 36))  # p(1-p), the best a flat forecast can do


def test_forecasts_whose_answer_is_already_known_are_left_out():
    rows = [("s", 8, f"c{i}", "top8", 1.0 if i < 8 else 0.0, i < 8, True) for i in range(36)]  # the table is final
    rows += [("s", 8, f"c{i}", "last16", 0.5, i < 16, False) for i in range(36)]
    summary = bt.summarise(frame(rows), titles())
    assert [row["stage"] for row in summary["by_stage"] if row["clubs"]] == ["last16"]
    assert sum(row["forecasts"] for row in summary["calibration"]) == 36  # the 36 open forecasts, not the 72


def test_calibration_compares_what_was_given_with_what_happened_in_each_band():
    rows = [("s", 0, f"a{i}", "semi", 0.8, i < 4, False) for i in range(5)]  # 80% given, 4 of 5 happened
    rows += [("s", 0, f"b{i}", "semi", 0.05, i < 2, False) for i in range(10)]  # 5% given, 2 of 10 happened
    summary = bt.summarise(frame(rows), titles())
    band = {round(row["low"], 2): row for row in summary["calibration"]}
    assert (band[0.75]["forecasts"], band[0.75]["count"], band[0.75]["happened"]) == (5, 4, pytest.approx(0.8))
    assert band[0.75]["expected_count"] == pytest.approx(4.0)
    assert (band[0.02]["forecasts"], band[0.02]["count"], band[0.02]["expected_count"]) == (10, 2, pytest.approx(0.5))


def test_the_favourite_is_checked_against_the_champion():
    both = pd.concat([titles(), titles(champion="B", favourite="B", favourite_p=0.4)])
    summary = bt.summarise(frame([("s", 0, "a", "win", 0.1, False, False)]), both)
    assert (summary["favourite_won"], summary["moments"], summary["favourite_expected"]) == (1, 2, pytest.approx(0.7))


# ---------- what counts as having happened ----------

@needs_raw_data
@pytest.mark.parametrize("season, champion", [("2024-25", "Paris SG"), ("2025-26", "Paris SG")])
def test_every_stage_has_the_right_clubs(season, champion):
    from matches import load_matches
    matches = load_matches()
    league = bt.league_phase(matches, season)
    assert check_league_phase(league) is None and league.home_goals.notna().all() and sorted(league.matchday.unique()) == list(range(1, 9))
    reached, won = bt.what_happened(matches, season)
    assert won == champion and reached["win"] == {champion}
    assert {stage: len(clubs) for stage, clubs in reached.items()} == SIZE
    for later, earlier in (("last16", "top24"), ("quarter", "last16"), ("semi", "quarter"), ("final", "semi"), ("win", "final")):
        assert reached[later] <= reached[earlier], (later, earlier)
    assert reached["top8"] <= reached["last16"] and len(reached["top24"] - reached["top8"]) == 16  # the play-off clubs
    # The top eight really are the clubs that finished there: they all scored well in the league phase.
    points = {}
    for row in league.itertuples():
        home, away = (3, 0) if row.home_goals > row.away_goals else (0, 3) if row.home_goals < row.away_goals else (1, 1)
        points[row.home_page] = points.get(row.home_page, 0) + home
        points[row.away_page] = points.get(row.away_page, 0) + away
    assert min(points[c] for c in reached["top8"]) > max(points[c] for c in set(points) - reached["top24"])


# ---------- the saved results ----------

@pytest.fixture(scope="module")
def saved():
    return json.loads((RESULTS / "forecast_backtest.json").read_text(encoding="utf-8"))


def test_saved_backtest_has_every_stage_and_moment(saved):
    assert [row["stage"] for row in saved["by_stage"]] == list(bt.STAGES)
    assert [row["after"] for row in saved["by_moment"]] == list(bt.AFTER)
    assert len(saved["champion"]) == len(bt.SEASONS) * len(bt.AFTER) == saved["moments"]
    assert saved["noise"] == 0 and saved["worlds"] == 1
    # 36 clubs, 7 stages, 10 moments (5 in each season), less top 8 and top 24 at the end of the league phase, when they are known.
    assert sum(row["clubs"] for row in saved["by_stage"]) == 36 * (7 * 10 - 2 * 2)
    assert sum(row["forecasts"] for row in saved["calibration"]) == 36 * (7 * 10 - 2 * 2)


def test_saved_backtest_totals_agree_with_the_stage_scores(saved):
    stages = saved["by_stage"]
    total = sum(row["clubs"] for row in stages)
    assert saved["overall"]["brier"] == pytest.approx(sum(row["clubs"] * row["brier"] for row in stages) / total, abs=1e-9)
    assert saved["overall"]["knowing_nothing"] == pytest.approx(sum(row["clubs"] * row["knowing_nothing"] for row in stages) / total, abs=1e-9)
    assert saved["overall"]["skill"] == pytest.approx(1 - saved["overall"]["brier"] / saved["overall"]["knowing_nothing"], abs=1e-9)
    assert all(0 <= row["happened"] <= 1 and row["low"] < row["high"] for row in saved["calibration"])
    assert sum(row["expected_count"] for row in saved["calibration"]) == pytest.approx(  # the chances given, added up
        sum(row["given"] * row["forecasts"] for row in saved["calibration"]))


def test_the_forecast_beats_knowing_nothing(saved):
    assert saved["overall"]["skill"] > 0.2
    assert all(row["skill"] > 0 for row in saved["by_stage"] if row["stage"] != "win")  # one winner a season is too few to score the title
    assert all(row["skill"] > 0 for row in saved["by_moment"])


def test_experiments_with_uncertain_ratings_are_saved_apart():
    found = sorted(RESULTS.glob("forecast_backtest_noise_*.json"))
    assert found, "run src/backtest_forecast.py --noise 0.15"
    for path in found:
        result = json.loads(path.read_text(encoding="utf-8"))
        assert result["noise"] > 0 and result["worlds"] > 1 and f"_noise_{result['noise']:g}" in path.name
