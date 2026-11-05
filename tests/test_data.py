"""site/data.json agrees with itself, and the README agrees with it.

Numbers on the page are shown in several places (a tooltip and a funnel, a headline and a
chart, the page and the README); these tests fail when any two of them drift apart.
"""

import json
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


def test_scores_reproduce_every_winner(data):
    # The scores come from the match files and the winners from a separate calculation. If they
    # ever disagree, one of them is wrong, whichever tie it is.
    for t in data["ties"]:
        a, b = (sum(leg[i] for leg in t["legs"]) for i in (0, 1))
        if a != b:
            winner = t["team_a"] if a > b else t["team_b"]
        elif t.get("away"):  # team_b's away goals are its first-leg goals, team_a's are its second-leg goals
            away_a, away_b = t["legs"][1][0], t["legs"][0][1]
            assert away_a != away_b, t
            winner = t["team_a"] if away_a > away_b else t["team_b"]
        else:
            assert t["pens"][0] != t["pens"][1], t
            winner = t["team_a"] if t["pens"][0] > t["pens"][1] else t["team_b"]
        assert winner == t["winner"], (t["season"], t["round"], t["team_a"], t["team_b"])


def test_scores_have_the_right_shape(data):
    for t in data["ties"]:
        assert len(t["legs"]) in (1, 2) and all(len(leg) == 2 and min(leg) >= 0 for leg in t["legs"])
        if t.get("away"):  # the away-goals rule ended after 2020-21, and only applies to two legs
            assert t["season"] <= "2020-21" and len(t["legs"]) == 2 and "pens" not in t
    assert sum("pens" in t for t in data["ties"]) > 0 and sum(bool(t.get("aet")) for t in data["ties"]) > 0


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


def test_forecast_section_adds_up(data):
    forecast = data.get("forecast")
    if forecast is None:
        pytest.skip("no season forecast: out of season, or too old to show")
    clubs = forecast["clubs"]
    assert len(clubs) == 36 and len({c["club"] for c in clubs}) == 36
    assert forecast["played"] + forecast["left"] == forecast["matches"] == 144
    assert sum(c["played"] for c in clubs) == 2 * forecast["played"]
    # Every simulated season has exactly this many clubs at each stage, so the shares add up to it.
    for stage, size in {"top8": 8, "top24": 24, "last16": 16, "quarter": 8, "semi": 4, "final": 2, "win": 1}.items():
        assert sum(c[stage] for c in clubs) == pytest.approx(size, abs=1e-3), stage
    for c in clubs:  # a club can't reach a stage without reaching the one before
        assert 0 <= c["win"] <= c["final"] <= c["semi"] <= c["quarter"] <= c["last16"] <= c["top24"] <= 1, c["club"]
        assert c["top8"] <= c["last16"], c["club"]
    assert [c["win"] for c in clubs] == sorted((c["win"] for c in clubs), reverse=True)


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


@pytest.mark.readme
def test_readme_real_madrid_checks(readme):
    r = json.loads((ROOT / "results" / "real_madrid.json").read_text(encoding="utf-8"))
    league, groups, knockouts = r["stages"]
    other_groups, other_knockouts = r["other_clubs_stages"]
    n, (h1, h2), f = r["normal_time"], r["halves"], r["forecast"]
    others = [c for c in r["clubs"] if c["club"] != "Real Madrid"]
    correlation = np.corrcoef([c["first"] for c in others], [c["second"] for c in others])[0, 1]
    round_to = lambda x, digits: float(f"{x:.{digits}g}")
    expected = [
        f"{league['points']:.2f} points a match against {league['expected']:.2f}",
        f"the gap was {groups['gap']:+.2f} a match ({groups['matches']} matches)",
        f"{knockouts['gap']:+.2f} ({knockouts['points']:.2f} against {knockouts['expected']:.2f}, over {knockouts['matches']} matches)",
        f"the gap is {other_groups['gap']:+.2f} over {other_groups['matches']:,} group matches and {other_knockouts['gap']:+.2f} over {other_knockouts['matches']:,} knockout matches",
        f"none is further than {r['others']['largest_z']:.1f} standard deviations",
        f"Barcelona won {r['spanish']['Barcelona']['won']} of {r['spanish']['Barcelona']['ties']} ties against {r['spanish']['Barcelona']['expected']:.1f} expected",
        f"Atlético Madrid {r['spanish']['Ath Madrid']['won']} of {r['spanish']['Ath Madrid']['ties']} against {r['spanish']['Ath Madrid']['expected']:.1f}",
        f"they won {n['won_normal']['actual']} when the model expected {n['won_normal']['expected']:.1f}, and lost {n['lost_normal']['actual']} when it expected {n['lost_normal']['expected']:.1f}",
        f"({n['won_extra']['expected']:.1f} expected, about 1 in {round_to(1 / n['won_extra']['p_at_least'], 2):.0f})",
        f"In the first Real won {h1['won']} of {h1['ties']} ties against {h1['expected']:.1f} expected, and in the second {h2['won']} of {h2['ties']} against {h2['expected']:.1f}",
        f"ahead of the model in {r['seasons_above']} of {r['seasons']} seasons",
        f"about once in {round_to(1 / h2['p_at_least'], 2):.0f} tries",
        f"by about {math.exp(f['boost']):.1f})",
        f"from {f['without']:.3f} to {f['with']:.3f}",
        f"For the {len(others)} other clubs",
        f"(the correlation is {correlation:.2f})",
    ]
    missing = [text for text in expected if text not in readme]
    assert not missing, missing


@pytest.mark.readme
def test_readme_line_up_check(readme):
    r = json.loads((ROOT / "results" / "real_madrid_squad.json").read_text(encoding="utf-8"))
    rotation, strength, managers = r["rotation"], r["strength"], r["managers"]
    knockouts = strength["real"]["knockouts"]
    explained = knockouts["explained_by_fielded"] + knockouts["explained_by_quality"]
    expected = [
        f"{rotation['real']['knockouts']:.0%} of their best eleven's value in knockout matches against {rotation['real']['league']:.0%} in the league",
        f"The gap is {rotation['real']['gap']:+.3f} for Real and {rotation['others']['gap']:+.3f} on average for the other {rotation['others']['clubs']} clubs, and Real ranks {rotation['real_rank']}th of {rotation['clubs']}",
        f"({strength['fielded_vs_usual']['coefficient']:+.2f} goals a match, standard error {strength['fielded_vs_usual']['se']:.2f})",
        f"only {explained:+.2f} of their {knockouts['actual']:+.2f} goals a match in knockouts",
        f"under Ancelotti ({managers['ancelotti_at_real']['points']:+.2f} points a match) and under Zidane ({managers['zidane_at_real']['points']:+.2f})",
        f"Ancelotti's {managers['ancelotti_elsewhere']['matches']} matches elsewhere ({managers['ancelotti_elsewhere']['points']:+.2f})",
    ]
    missing = [text for text in expected if text not in readme]
    assert not missing, missing

