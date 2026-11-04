"""site/data.json agrees with itself, and the README agrees with it.

Numbers on the page are shown in several places (a tooltip and a funnel, a headline and a
chart, the page and the README); these tests fail when any two of them drift apart.
"""

import math
import re

import numpy as np
import pytest

from conftest import ROOT


def winner_chance(t):
    return t["p_a"] if t["winner"] == t["team_a"] else 1 - t["p_a"]


@pytest.fixture(scope="module")
def readme():
    return (ROOT / "README.md").read_text(encoding="utf-8")


def odds_of_doing_as_well(ties, club):
    """Exact chance of winning at least as many ties as the club did, as '1 in N' (3 s.f.)."""
    mine = [t for t in ties if club in (t["team_a"], t["team_b"])]
    dist = np.array([1.0])
    for t in mine:
        p = t["p_a"] if t["team_a"] == club else 1 - t["p_a"]
        dist = np.append(dist * (1 - p), 0) + np.append(0, dist * p)
    won = sum(t["winner"] == club for t in mine)
    return f"{float(f'{1 / dist[won:].sum():.3g}'):,.0f}"


# ---------- data.json against itself ----------

def test_headline_matches_the_ties(data):
    h, ties = data["headline"], data["ties"]
    assert h["ties"] == len(ties)
    assert {h["first_season"], h["last_season"]} <= {t["season"] for t in ties}
    assert h["underdog"] == pytest.approx(np.mean([min(t["p_a"], 1 - t["p_a"]) for t in ties]), abs=1e-3)
    real = [t for t in ties if "Real Madrid" in (t["team_a"], t["team_b"])]
    assert (h["real_ties"], h["real_won"]) == (len(real), sum(t["winner"] == "Real Madrid" for t in real))


def test_every_tie_winner_is_one_of_its_teams(data):
    assert all(t["winner"] in (t["team_a"], t["team_b"]) for t in data["ties"])
    assert all(0 <= t["p_a"] <= 1 for t in data["ties"])


def test_each_champions_run_is_the_product_of_its_ties(data):
    # The bar's tooltip uses the stored figure and the funnel multiplies the ties: they must agree.
    for run in data["champions"]:
        product = math.prod(t["probability"] for t in run["ties"])
        assert product == pytest.approx(run["probability"], abs=6e-4), run["season"]


def test_one_final_per_season(data):
    seasons = {t["season"] for t in data["ties"]}
    finals = next(r for r in data["rounds"] if r["round"] == "Final")
    assert finals["ties"] == len(seasons) == len(data["champions"])


def test_calibration_uses_the_same_matches_as_the_scores_table(data):
    # "Tested on N matches" comes from the scores table; the chart must be drawn on the same N.
    by_model = {s["name"]: sum(p["n"] for p in s["points"]) for s in data["calibration"]}
    assert by_model["Dixon–Coles"] == by_model["Elo"] == data["scores"][0]["matches"]


def test_comeback_ties_say_which_rules_they_were_played_under(data):
    ties = data["comebacks"]["ties"]
    assert all(len(t) == 4 and t[3] in (0, 1) and t[2] in (0, 1) for t in ties)
    assert {t[3] for t in ties} == {0, 1}


def test_live_section_describes_its_fit(data):
    live = data.get("live")
    if live is None:
        pytest.skip("no live section")
    for key in ["updated", "fitted_through", "window_years", "big_five_average", "ratings"]:
        assert live.get(key) is not None, key


# ---------- the README against data.json ----------

@pytest.mark.readme
def test_readme_tie_count(data, readme):
    assert f"({len(data['ties'])} ties)" in readme


@pytest.mark.readme
def test_readme_underdog_chance(data, readme):
    assert f"underdog a **{round(data['headline']['underdog'] * 100)}%**" in readme


@pytest.mark.readme
def test_readme_median_champion(data, readme):
    assert f"**{round(data['headline']['median_champion_run'] * 100)}% for the median champion**" in readme


@pytest.mark.readme
def test_readme_real_madrid(data, readme):
    h = data["headline"]
    assert f"{h['real_won']} of {h['real_ties']} ties" in readme
    assert f"expected {h['real_expected']:.1f}" in readme
    assert f"once in {odds_of_doing_as_well(data['ties'], 'Real Madrid')} tries" in readme


@pytest.mark.readme
def test_readme_comeback_count(data, readme):
    assert f"{len(data['comebacks']['ties'])} ties in all" in readme


@pytest.mark.readme
def test_readme_test_match_count(data, readme):
    assert f"{data['scores'][0]['matches']:,} league matches" in readme


@pytest.mark.readme
def test_readme_europa_league_coverage_matches_the_data():
    seasons = sorted(p.parent.name for p in (ROOT / "data" / "raw" / "europe").glob("*/el.txt"))
    if not seasons:
        pytest.skip("needs data/raw")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert re.search(rf"Europa League results from {seasons[0]} to {seasons[-1]}", readme)
