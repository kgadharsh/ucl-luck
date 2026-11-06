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
    for key in ["updated", "fitted_through", "window_years", "big_five_average"]:
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
    sel = h["real_selection"]
    assert f"({sel['clubs']} clubs)" in readme and f"at least {sel['min_ties']} ties" in readme and f"once in {sel['one_in']} tries" in readme


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



@pytest.mark.readme
def test_readme_forecast_backtest(readme):
    """The numbers in the README's "Does it hold up?" are the saved backtest's."""
    result = json.loads((ROOT / "results" / "forecast_backtest.json").read_text(encoding="utf-8"))
    stage = {row["stage"]: row for row in result["by_stage"]}
    for name in ("top8", "top24", "last16", "quarter", "semi", "final", "win"):
        assert f"{stage[name]['skill']:+.0%}" in readme, name
    assert f"{result['overall']['skill']:+.0%} across all of them" in readme
    band = {round(row["low"], 2): row for row in result["calibration"]}
    for low in (0.75, 0.02, 0.5):
        assert f"{band[low]['count']} " in readme and f"{band[low]['expected_count']:.0f}" in readme
    assert f"{band[0.75]['count']} times out of {band[0.75]['forecasts']}, where {band[0.75]['expected_count']:.0f} were expected" in readme
    assert f"{band[0.02]['count']} times against {band[0.02]['expected_count']:.0f} expected" in readme
    assert f"{band[0.5]['count']} against {band[0.5]['expected_count']:.0f} expected in the 50% to 75% band" in readme
    assert f"{result['favourite_expected']:.1f} of the ten moments" in readme and result["favourite_won"] == 0 and result["moments"] == 10
    skills = [json.loads(path.read_text(encoding="utf-8"))["overall"]["skill"]
              for path in sorted((ROOT / "results").glob("forecast_backtest_noise_*.json"))]
    assert len(skills) == 3 and f"skill {skills[0]:+.1%}, {skills[1]:+.1%} and {skills[2]:+.1%} against {result['overall']['skill']:+.1%} without it" in readme
    assert all(skill < result["overall"]["skill"] for skill in skills)  # the claim: it made the score slightly worse each time


# ---------- season replays ----------

def test_season_replays_are_exact_and_agree_with_the_brackets(data):
    """Every replay is a whole bracket played out: title chances sum to one, and the real champion is in it."""
    assert sorted(r["season"] for r in data["replays"]) == sorted(b["season"] for b in data["brackets"])
    by_season = {b["season"]: b for b in data["brackets"]}
    for row in data["replays"]:
        bracket = by_season[row["season"]]
        final = next(n for n in bracket["nodes"] if n["round"] == "Final")
        assert row["champion"] == final["winner"]
        assert 0 < row["champion_chance"] < 1 and 0 <= row["less_surprising"] <= 1
        chances = [c["chance"] for c in row["contenders"]]
        assert chances == sorted(chances, reverse=True) and sum(chances) <= 1.0001
        assert row["contenders"][0]["chance"] >= row["champion_chance"] or row["contenders"][0]["club"] == row["champion"]
    ranked = [r["less_surprising"] for r in data["replays"]]
    assert ranked == sorted(ranked, reverse=True), "most surprising season first"


def test_replays_of_a_tiny_bracket_match_a_hand_calculation():
    """Four clubs, three ties: A v B and C v D, then the winners. Worked out by hand."""
    import sys
    sys.path.insert(0, str(ROOT / "src"))
    from replays import replay_season
    chance = [[0.5, 0.6, 0.7, 0.8], [0.4, 0.5, 0.6, 0.7], [0.3, 0.4, 0.5, 0.6], [0.2, 0.3, 0.4, 0.5]]
    bracket = {"season": "x", "teams": ["A", "B", "C", "D"], "two_legs": chance, "single": chance, "nodes": [
        {"id": 0, "round": "Round of 16", "winner": "A", "teams": ["A", "B"], "format": "two_legs"},
        {"id": 1, "round": "Round of 16", "winner": "C", "teams": ["C", "D"], "format": "two_legs"},
        {"id": 2, "round": "Final", "winner": "A", "from": [0, 1], "format": "single"}]}
    r = replay_season(bracket)
    # A wins: beat B (0.6), then beat C (0.7) or D (0.8), weighted by who reached the final.
    expected_a = 0.6 * (0.6 * 0.7 + 0.4 * 0.8)
    assert r["title"]["A"] == pytest.approx(expected_a) and sum(r["title"].values()) == pytest.approx(1)
    # The real run: A beat B (0.6), C beat D (0.6), A beat C (0.7) = 0.252. Replays with a higher chance are less surprising.
    actual = 0.6 * 0.6 * 0.7
    outcomes = [(0.6 * 0.6 * 0.7, "A"), (0.6 * 0.6 * 0.3, "C"), (0.6 * 0.4 * 0.8, "A"), (0.6 * 0.4 * 0.2, "D"),
                (0.4 * 0.6 * 0.6, "B"), (0.4 * 0.6 * 0.4, "C"), (0.4 * 0.4 * 0.7, "B"), (0.4 * 0.4 * 0.3, "D")]
    assert r["less_surprising"] == pytest.approx(sum(p for p, _ in outcomes if p > actual))
