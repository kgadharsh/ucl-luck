"""The Real Madrid analysis: its probability arithmetic, its saved results, and that the saved
results agree with the ties that the rest of the page is built from."""

import itertools
import json
import math

import numpy as np
import pytest

from conftest import ROOT, needs_raw_data
from knockouts import single_match, single_match_outcomes, two_leg_outcomes, two_legs
from real_madrid import at_least, at_most, poisson_binomial, z_score

CLUB = "Real Madrid"


@pytest.fixture(scope="module")
def saved():
    return json.loads((ROOT / "results" / "real_madrid.json").read_text(encoding="utf-8"))


def real_ties(data):
    ties = [t for t in data["ties"] if CLUB in (t["team_a"], t["team_b"])]
    return [(t, t["p_a"] if t["team_a"] == CLUB else 1 - t["p_a"]) for t in ties]


# ---------- the arithmetic ----------

def test_poisson_binomial_matches_counting_every_outcome():
    ps = [0.2, 0.5, 0.9, 0.35]
    brute = np.zeros(len(ps) + 1)
    for outcome in itertools.product([0, 1], repeat=len(ps)):
        brute[sum(outcome)] += math.prod(p if won else 1 - p for p, won in zip(ps, outcome))
    assert poisson_binomial(ps) == pytest.approx(brute)
    assert at_least(ps, 3) == pytest.approx(brute[3:].sum())
    assert at_most(ps, 1) == pytest.approx(brute[:2].sum())
    assert at_least(ps, 0) == pytest.approx(1) and at_most(ps, len(ps)) == pytest.approx(1)


def test_a_z_score_is_zero_when_the_wins_match_the_chances():
    assert z_score(2, [0.5] * 4) == pytest.approx(0)
    assert z_score(4, [0.5] * 4) > 0 > z_score(0, [0.5] * 4)


@pytest.mark.parametrize("away_goals", [False, True])
def test_two_leg_pieces_add_up_to_one_and_to_the_tie_chance(away_goals):
    for goals in [(1.6, 0.9, 1.1, 1.4), (1.0, 1.0, 1.0, 1.0), (2.2, 0.6, 0.8, 1.9)]:
        won, lost, level, from_level = two_leg_outcomes(*goals, -0.05, away_goals)
        assert won + lost + level == pytest.approx(1, abs=1e-6)
        assert 0 <= from_level <= 1
        assert won + level * from_level == pytest.approx(two_legs(*goals, -0.05, away_goals))


def test_one_off_match_pieces_add_up_to_one_and_to_the_match_chance():
    for lam, nu in [(1.5, 0.8), (1.0, 1.0), (0.7, 1.9)]:
        won, lost, level, from_level = single_match_outcomes(lam, nu, -0.05)
        assert won + lost + level == pytest.approx(1, abs=1e-6)
        assert won + level * from_level == pytest.approx(single_match(lam, nu, -0.05))


# ---------- the saved results against the ties on the page ----------

def test_saved_analysis_agrees_with_the_ties(saved, data):
    mine = real_ties(data)
    assert (saved["ties"], saved["won"]) == (len(mine), sum(t["winner"] == CLUB for t, _ in mine))
    assert saved["expected"] == pytest.approx(sum(p for _, p in mine), abs=1e-3)
    assert saved["p_at_least"] == pytest.approx(at_least([p for _, p in mine], saved["won"]))


def test_the_two_halves_are_recomputed_from_the_ties(saved, data):
    mine = real_ties(data)
    seasons = sorted({t["season"] for t in data["ties"]})
    for half, in_half in zip(saved["halves"], (seasons[:7], seasons[7:])):
        part = [(t, p) for t, p in mine if t["season"] in in_half]
        assert (half["ties"], half["won"]) == (len(part), sum(t["winner"] == CLUB for t, _ in part))
        assert half["expected"] == pytest.approx(sum(p for _, p in part), abs=1e-3)
    assert sum(h["ties"] for h in saved["halves"]) == saved["ties"]
    ahead = sum(sum((t["winner"] == CLUB) - p for t, p in mine if t["season"] == s) > 0 for s in seasons)
    assert (saved["seasons_above"], saved["seasons"]) == (ahead, len(seasons))


def test_normal_time_split_agrees_with_the_scores_and_adds_up(saved, data):
    mine = real_ties(data)
    n = saved["normal_time"]
    extra = [t for t, _ in mine if t.get("aet")]
    assert n["extra_time"]["actual"] == len(extra)
    assert n["won_extra"]["actual"] == sum(t["winner"] == CLUB for t in extra)
    assert n["won_normal"]["actual"] == sum(t["winner"] == CLUB for t, _ in mine if not t.get("aet"))
    assert n["lost_normal"]["actual"] == sum(t["winner"] != CLUB for t, _ in mine if not t.get("aet"))
    assert n["won_normal"]["actual"] + n["lost_normal"]["actual"] + n["extra_time"]["actual"] == saved["ties"]
    assert n["won_normal"]["actual"] + n["won_extra"]["actual"] == saved["won"]
    # What the model expected, in the same three pieces, has to add back up to its tie chances.
    assert n["won_normal"]["expected"] + n["lost_normal"]["expected"] + n["extra_time"]["expected"] == pytest.approx(saved["ties"], abs=1e-3)
    assert n["won_normal"]["expected"] + n["won_extra"]["expected"] == pytest.approx(saved["expected"], abs=1e-3)


def test_the_stages_have_the_right_number_of_matches(saved):
    stages = {s["label"]: s for s in saved["stages"]}
    assert stages["Champions League knockouts"]["matches"] == 82  # 44 ties: 38 two-legged and 6 single matches
    assert 500 < stages["La Liga"]["matches"] <= 14 * 38
    for s in saved["stages"] + saved["other_clubs_stages"]:
        assert s["error"] > 0 and s["gap"] == pytest.approx(s["points"] - s["expected"], abs=1e-9)


def test_the_page_gets_the_analysis_only_when_it_matches_the_ties(saved, data, tmp_path, monkeypatch, capsys):
    import export_site
    assert data["real_madrid"] == saved
    monkeypatch.setattr(export_site, "RESULTS", tmp_path)
    assert export_site.real_madrid_section(data["headline"]) is None  # no file at all
    (tmp_path / "real_madrid.json").write_text(json.dumps(saved), encoding="utf-8")
    assert export_site.real_madrid_section(data["headline"]) == saved
    stale = {**data["headline"], "real_won": saved["won"] + 4, "real_ties": saved["ties"] + 6}  # new ties since it was run
    assert export_site.real_madrid_section(stale) is None
    assert "out of date" in capsys.readouterr().out


@needs_raw_data
def test_saved_analysis_is_what_the_script_produces_today(saved):
    from real_madrid import analyse

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

    same(json.loads(json.dumps(analyse())), saved)  # also fails on anything that isn't plain JSON
