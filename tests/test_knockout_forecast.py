"""The forecast once the knockout phase is under way: reading the articles, and playing out what is left
from the draws made and the legs already played."""

import numpy as np
import pandas as pd
import pytest

import forecast as fc
import parse_knockouts as pk
from conftest import ROOT, needs_raw_data
from dixon_coles import score_matrix
from knockouts import two_legs

FIXTURES = ROOT / "tests" / "fixtures"
CLUBS = 36


def read(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


# ---------- reading the articles ----------

def test_a_row_is_split_where_it_should_be_even_with_pipes_inside_links():
    row = "|[[AS Monaco FC|Monaco]]|FRA|4–5|[[Paris Saint-Germain FC|Paris Saint-Germain]]|FRA|2–3|2–2"
    assert pk.split_row(row) == ["[[AS Monaco FC|Monaco]]", "FRA", "4–5", "[[Paris Saint-Germain FC|Paris Saint-Germain]]", "FRA", "2–3", "2–2"]
    assert pk.split_row("not a row") == []


@pytest.mark.parametrize("raw, expected", [
    ("2–3", {"goals": (2, 3), "aet": False, "pens": None}), ("5-1", {"goals": (5, 1), "aet": False, "pens": None}),
    ("2–3 (aet)", {"goals": (2, 3), "aet": True, "pens": None}), ("1–1 (a.e.t.) (4–3 p)", {"goals": (1, 1), "aet": True, "pens": (4, 3)}),
    ("0–0 (5–4 pen.)", {"goals": (0, 0), "aet": False, "pens": (5, 4)}), ("", None), ("TBD", None)])
def test_a_leg_is_read_with_its_extra_time_and_shoot_out(raw, expected):
    assert pk.parse_leg(raw) == expected


def test_every_round_of_2025_26_is_read():
    ties = pk.parse_ties(read("knockouts_2025-26.txt"))
    assert {name: len(found) for name, found in ties.items()} == {"Playoffs": 8, "Round of 16": 8, "Quarterfinals": 4, "Semifinals": 2}
    monaco = ties["Playoffs"][0]
    assert (monaco["team1"], monaco["team2"]) == (("AS Monaco FC", "Monaco"), ("Paris Saint-Germain FC", "Paris Saint-Germain"))
    assert (monaco["leg1"], monaco["leg2"], monaco["aet"]) == ((2, 3), (2, 2), False)  # the first leg's host first, in both legs
    assert ties["Playoffs"][1]["aet"] and ties["Round of 16"][2]["leg2"] == (2, 1)  # "2-1" with a hyphen
    assert [pk.tie_winner(t) for t in ties["Semifinals"]] == [1, 2]  # Paris SG, then Arsenal (who beat Atlético 2-1 on aggregate)


def test_the_winner_of_a_tie_is_its_aggregate_then_its_shoot_out():
    tie = {"leg1": (1, 0), "leg2": (1, 2), "pens": None}
    assert pk.tie_winner({**tie, "leg2": (0, 0)}) == 1 and pk.tie_winner({**tie, "leg2": (0, 2)}) == 2
    assert pk.tie_winner(tie) is None  # level, and no shoot-out recorded
    assert pk.tie_winner({**tie, "pens": (3, 4)}) == 2 and pk.tie_winner({**tie, "pens": (4, 3)}) == 1
    assert pk.tie_winner({**tie, "leg2": None}) is None  # not over


def test_unplayed_legs_and_missing_rounds_are_left_empty():
    text = "\n==Round of 16==\n{{#invoke:Sports series|main|generate_links=y\n|[[A FC|A]]|ENG||[[B FC|B]]|ESP|2–0|\n|[[C FC|C]]|ITA||[[D FC|D]]|GER||\n}}\n"
    ties = pk.parse_ties(text)
    assert list(ties) == ["Round of 16"]
    assert [(t["leg1"], t["leg2"]) for t in ties["Round of 16"]] == [((2, 0), None), (None, None)]


def test_the_final_is_read_before_and_after_it_is_played():
    final = pk.parse_final(read("final_2025-26.txt"))
    assert (final["team1"][0], final["goals"], final["pens"], final["date"]) == ("Paris Saint-Germain FC", (1, 1), (4, 3), pd.Timestamp("2026-05-30"))
    assert pk.final_winner(final) == 1
    assert pk.final_winner({**final, "pens": None}) is None and pk.final_winner({**final, "goals": (0, 1)}) == 2
    infobox = "{{Infobox football match\n| team1 = [[Real Madrid CF|Real Madrid]]\n| team2 = [[FC Barcelona|Barcelona]]\n| team1score = %s\n| team2score = %s\n| date = {{Start date|2027|6|5|df=y}}\n}}"
    assert pk.parse_final(infobox % ("", ""))["goals"] is None  # the article before the match
    assert pk.final_winner(pk.parse_final(infobox % ("2", "1"))) == 1
    assert pk.parse_final("{{Infobox football match\n| team1 = \n| team2 = \n}}") is None  # finalists not known yet


def test_the_knockout_articles_are_loaded_from_their_files(tmp_path, monkeypatch):
    import json
    monkeypatch.setattr(pk, "RAW", tmp_path)
    assert pk.load_knockouts("2025-26") is None
    (tmp_path / "2025-26-knockout-phase.json").write_text(json.dumps({"parse": {"wikitext": read("knockouts_2025-26.txt")}}), encoding="utf-8")
    loaded = pk.load_knockouts("2025-26")
    assert len(loaded["ties"]["Playoffs"]) == 8 and loaded["final"] is None  # no final article yet
    (tmp_path / "2025-26-final.json").write_text(json.dumps({"parse": {"wikitext": read("final_2025-26.txt")}}), encoding="utf-8")
    assert pk.final_winner(pk.load_knockouts("2025-26")["final"]) == 1


# ---------- what a tie in progress is worth ----------

def test_a_second_leg_played_out_from_every_first_leg_score_adds_up_to_the_whole_tie():
    lam1, nu1, lam2, nu2, rho = 1.6, 0.9, 1.2, 1.3, -0.05
    first = score_matrix(np.array([lam1]), np.array([nu1]), rho)[0]
    total = sum(first[x, y] * fc.after_first_leg(lam2, nu2, x - y, rho) for x in range(11) for y in range(11))
    assert total == pytest.approx(two_legs(lam1, nu1, lam2, nu2, rho, False), abs=1e-9)


def test_a_bigger_first_leg_lead_is_worth_more_and_a_huge_one_is_a_certainty():
    chances = [fc.after_first_leg(1.3, 1.3, lead, -0.05) for lead in range(-3, 4)]
    assert chances == sorted(chances) and fc.after_first_leg(1.3, 1.3, 0, -0.05) == pytest.approx(0.5, abs=0.06)
    assert fc.after_first_leg(1.3, 1.3, 10, -0.05) == pytest.approx(1, abs=1e-3) and fc.after_first_leg(1.3, 1.3, -10, -0.05) == pytest.approx(0, abs=1e-3)


class Even:
    def expected_goals(self, home, away, neutral, newcomer):
        return 1.4, 1.1


@pytest.mark.parametrize("tie, expected", [
    ({"leg1": (2, 0), "leg2": (0, 1), "pens": None}, 1.0), ({"leg1": (0, 2), "leg2": (1, 0), "pens": None}, 0.0),
    ({"leg1": (1, 0), "leg2": (1, 2), "pens": (4, 3)}, 1.0), ({"leg1": (1, 0), "leg2": (1, 2), "pens": (3, 4)}, 0.0),
    ({"leg1": (1, 0), "leg2": (1, 2), "pens": None}, 0.5)])
def test_a_tie_that_is_over_is_worth_one_zero_or_a_toss_up(tie, expected):
    assert fc.real_tie_chance(Even(), {**tie, "host": "A", "other": "B"}, -0.05, 0.2) == expected


def test_a_tie_not_yet_started_is_worth_what_the_model_says():
    tie = {"leg1": None, "leg2": None, "pens": None, "host": "A", "other": "B"}
    assert fc.real_tie_chance(Even(), tie, -0.05, 0.2) == pytest.approx(two_legs(1.4, 1.1, 1.4, 1.1, -0.05, False))
    ahead = fc.real_tie_chance(Even(), {**tie, "leg1": (2, 0)}, -0.05, 0.2)
    assert ahead > 0.8 > two_legs(1.4, 1.1, 1.4, 1.1, -0.05, False)  # two goals up at home after the first leg


# ---------- playing out what is left ----------

def ladder():
    """A finished league phase in which club i finishes in position i + 1."""
    table = {key: np.zeros(CLUBS, dtype=np.int64) for key in ("played", "points", "goals_for", "goals_against", "away_goals_for", "wins", "away_wins")}
    table["points"] = np.arange(CLUBS, 0, -1)
    return table


def play(through, plan, final=None, n=400):
    final = np.full((CLUBS, CLUBS), 0.5) if final is None else final
    return fc.simulate(ladder(), np.empty((0, 2), dtype=int), np.empty((0, 121)), through, final, n=n, seed=1, plan=plan)


def real_draw():
    return {"playoffs": {8: 23, 9: 22, 10: 21, 11: 20, 12: 19, 13: 18, 14: 17, 15: 16},
            "last16": {0: 15, 1: 14, 2: 13, 3: 12, 4: 11, 5: 10, 6: 9, 7: 8}}


def test_a_draw_that_has_been_made_is_the_draw_that_is_played():
    through = np.full((CLUBS, CLUBS), 0.5)
    through[23, 8], through[8, 23] = 1.0, 0.0  # club 23 beats club 8 for certain; club 22 would not beat club 8
    through[22, 8], through[8, 22] = 0.0, 1.0
    drawn = play(through, {"playoffs": real_draw()["playoffs"]})  # the real tie was club 8 v club 23
    assert drawn["last16"][23] == 1 and drawn["last16"][8] == 0
    open_draw = fc.simulate(ladder(), np.empty((0, 2), dtype=int), np.empty((0, 121)), through, np.full((CLUBS, CLUBS), 0.5), n=400, seed=1)
    assert 0 < open_draw["last16"][23] < 1  # with the draw still to come, 23 might have drawn club 9 instead


def test_a_known_table_makes_the_top_places_certain():
    reach = play(np.full((CLUBS, CLUBS), 0.5), real_draw())
    assert (reach["top8"][:8] == 1).all() and reach["top8"][8:].sum() == 0 and (reach["top24"][:24] == 1).all()
    for stage, size in {"last16": 16, "quarter": 8, "semi": 4, "final": 2, "win": 1}.items():
        assert reach[stage].sum() == pytest.approx(size)


def test_a_draw_that_does_not_fit_the_table_is_refused():
    wrong = real_draw()
    wrong["playoffs"] = {k + 1: v for k, v in wrong["playoffs"].items()}  # the table was worked out differently
    with pytest.raises(fc.NoForecast, match="draw doesn't match"):
        play(np.full((CLUBS, CLUBS), 0.5), wrong)


def test_a_final_already_played_has_a_champion():
    final = np.full((CLUBS, CLUBS), 0.5)
    through = np.full((CLUBS, CLUBS), 0.5)
    through[:, :] = np.where(np.add.outer(np.arange(CLUBS), np.arange(CLUBS)) >= 0, 0.5, 0)
    state = fc.knockouts(np.tile(np.arange(CLUBS)[:, None], (1, 50)), np.zeros((CLUBS, CLUBS)), final, np.random.default_rng(0), real_draw())
    champion = state["win"][0, 0]
    final[champion, :], final[:, champion] = 1.0, 0.0
    finalists = set(state["final"][:, 0])
    assert champion in finalists
    reach = play(np.zeros((CLUBS, CLUBS)), real_draw(), final)
    assert reach["win"][champion] == 1 and reach["win"].sum() == pytest.approx(1)


def test_the_season_is_in_the_phase_its_ties_say():
    ties = lambda legs: [{"leg1": (1, 0) if legs else None, "leg2": (0, 0) if legs == 2 else None, "pens": None}]
    full = lambda n: {"Playoffs": ties(n), "Round of 16": ties(n), "Quarterfinals": ties(n), "Semifinals": ties(n)}
    final = {"goals": None, "pens": None}
    assert fc.phase_of(5, None) == "league" and fc.phase_of(0, None) == "playoffs"
    assert fc.phase_of(0, {"ties": {"Playoffs": ties(1)}, "final": None}) == "playoffs"
    assert fc.phase_of(0, {"ties": {"Playoffs": ties(2)}, "final": None}) == "last16"
    assert fc.phase_of(0, {"ties": {**full(2), "Quarterfinals": ties(1), "Semifinals": []}, "final": None}) == "quarter"
    assert fc.phase_of(0, {"ties": full(2), "final": final}) == "final"
    assert fc.phase_of(0, {"ties": full(2), "final": {"goals": (1, 0), "pens": None}}) == "done"


# ---------- a whole forecast, against last season ----------

PAGES = {"Leverkusen": "Bayer 04 Leverkusen", "Newcastle": "Newcastle United F.C.", "Olympiakos": "Olympiacos F.C.", "Tottenham": "Tottenham Hotspur F.C."}


@pytest.fixture(scope="module")
def last_season():
    from backtest_forecast import league_phase
    from matches import load_matches
    history = load_matches()
    league = league_phase(history, "2025-26")
    for side in ("home", "away"):
        league[f"{side}_page"] = league[side].map(lambda club: PAGES.get(club, club))
    ties = pk.parse_ties(read("knockouts_2025-26.txt"))
    return history, league, ties, pk.parse_final(read("final_2025-26.txt"))


def first_legs(found):
    return [{**t, "leg2": None, "aet": False, "pens": None} for t in found]


@needs_raw_data
@pytest.mark.parametrize("label, phase, build, favourite", [
    ("play-offs drawn", "playoffs", lambda t, f: ({"Playoffs": [{**x, "leg1": None, "leg2": None, "pens": None} for x in t["Playoffs"]]}, None), "Arsenal"),
    ("play-offs, first legs played", "playoffs", lambda t, f: ({"Playoffs": first_legs(t["Playoffs"])}, None), "Arsenal"),
    ("quarter-final first legs", "quarter", lambda t, f: ({"Playoffs": t["Playoffs"], "Round of 16": t["Round of 16"], "Quarterfinals": first_legs(t["Quarterfinals"])}, None), "Arsenal"),
    ("final to play", "final", lambda t, f: (t, {**f, "goals": None, "pens": None}), "Arsenal"),
    ("final played", "done", lambda t, f: (t, f), "Paris SG")])
def test_last_seasons_knockouts_are_played_out_from_where_each_stage_stood(last_season, label, phase, build, favourite):
    history, league, ties, final = last_season
    found, last = build(ties, final)
    result = fc.forecast("2026-05-31" if phase == "done" else "2026-05-10" if phase == "final" else "2026-03-01", n=4000, season="2025-26",
                         history=history, league=league, knockouts={"ties": found, "final": last})
    assert result["phase"] == phase and result["clubs"][0]["club"] == favourite, label
    for stage, size in {"top8": 8, "top24": 24, "last16": 16, "quarter": 8, "semi": 4, "final": 2, "win": 1}.items():
        assert sum(c[stage] for c in result["clubs"]) == pytest.approx(size, abs=1e-3), stage
    won = {c["club"]: c["win"] for c in result["clubs"]}
    if phase == "final":
        assert {c for c, p in won.items() if p > 0} == {"Paris SG", "Arsenal"}  # only the two finalists can win it
    if phase == "done":
        assert won["Paris SG"] == 1  # decided on penalties, 4-3
    if phase == "quarter":
        semi = {c["club"]: c["semi"] for c in result["clubs"]}
        assert semi["Liverpool"] < 0.2 < semi["Paris SG"]  # Liverpool lost the first leg 0-2 away to Paris SG


@needs_raw_data
def test_the_forecast_stops_a_few_days_after_the_final(last_season):
    history, league, ties, final = last_season
    forecast = lambda day: fc.forecast(day, n=300, season="2025-26", history=history, league=league, knockouts={"ties": ties, "final": final})
    assert forecast("2026-06-02")["phase"] == "done"
    with pytest.raises(fc.NoForecast, match="final has been played") as stopped:
        forecast("2026-06-05")
    assert stopped.value.over


@needs_raw_data
def test_a_club_the_article_lists_but_the_league_phase_never_had_is_refused(last_season):
    history, league, ties, _ = last_season
    odd = {"Playoffs": [{**ties["Playoffs"][0], "team1": ("Nobody FC", "Nobody")}]}
    with pytest.raises(fc.NoForecast, match="Nobody"):
        fc.forecast("2026-02-01", n=100, season="2025-26", history=history, league=league, knockouts={"ties": odd, "final": None})
