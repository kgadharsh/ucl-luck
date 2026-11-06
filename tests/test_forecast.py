"""The season forecast: reading Wikipedia's league phase, the simulation, and the saved results.

The simulation is checked against things that must be true whatever the numbers (identical clubs
are interchangeable, a team that always wins always wins, probabilities add up), and the bracket
against what really happened in 2025-26, the season whose rules it copies."""

import json

import numpy as np
import pandas as pd
import pytest

import forecast as fc
from conftest import ROOT, needs_raw_data
from dixon_coles import score_matrix
from parse_league_phase import (check_league_phase, data_path, load_league_phase, parse_score, parse_team,
                                parse_wikitext, season_title)

SAVED = ROOT / "results" / "forecast.json"
KEYS = ("played", "points", "goals_for", "goals_against", "away_goals_for", "wins", "away_wins")
CLUBS = 36
SUMS = {"top8": 8, "top24": 24, "last16": 16, "quarter": 8, "semi": 4, "final": 2, "win": 1}  # clubs at each stage


@pytest.fixture(autouse=True)
def history_in_tmp(tmp_path, monkeypatch):
    """The forecast command adds each day's forecast to the history. Left alone, a test that runs it
    writes its made-up clubs into the real results/forecast_history.csv, which then gets committed."""
    monkeypatch.setattr(fc, "HISTORY", tmp_path / "forecast_history.csv")


# ---------- reading Wikipedia ----------

SAMPLE = """Intro text.

==Matches==
===Matchday 1===
{{#invoke:Football box|main
|date       = {{Start date|2026|9|8|df=y}}
|time       = 18:45&nbsp;{{small|(19:45 [[UTC+03:00|UTC+3]])}}
|team1      = [[AEK Athens F.C.|AEK Athens]] {{fbaicon|GRE}}
|score      = 1–0
|team2      = {{fbaicon|AUT}} [[LASK]]
|goals1     =
*[[Răzvan Marin|Marin]] {{goal|21}}
|goals2     =
|attendance = 30,221<ref>{{cite web |url=https://example.org |title=Summary}}</ref>
}}
----
{{#invoke:Football box|main
|date       = {{Start date|2026|9|8|df=y}}
|team1      = [[Club Brugge KV|Club Brugge]] {{fbaicon|BEL}}
|score      = 2−3 
|team2      = {{fbaicon|ENG}} [[Aston Villa F.C.|Aston Villa]]
|report     = Report
}}

===Matchday 5===
{{#invoke:Football box|main
|date       = {{Start date|2026|11|24|df=y}}
|team1      = [[FK Bodø/Glimt|Bodø/Glimt]] {{fbaicon|NOR}}
|score      =
|team2      = {{fbaicon|AUT}} [[LASK]]
|attendance = <!-- left empty until played -->
}}
"""


def test_a_wikipedia_article_is_read_match_by_match():
    league = parse_wikitext(SAMPLE)
    assert len(league) == 3
    first, second, third = (league.iloc[i] for i in range(3))
    assert (first.matchday, first.date) == (1, pd.Timestamp("2026-09-08"))
    assert (first.home_page, first.home, first.home_country) == ("AEK Athens F.C.", "AEK Athens", "GRE")
    assert (first.away_page, first.away, first.away_country) == ("LASK", "LASK", "AUT")  # the flag can come first or last
    assert (first.home_goals, first.away_goals) == (1, 0)
    assert (second.home, second.away, second.home_goals, second.away_goals) == ("Club Brugge", "Aston Villa", 2, 3)  # a minus sign, not a hyphen
    assert (third.matchday, third.date) == (5, pd.Timestamp("2026-11-24"))
    assert pd.isna(third.home_goals) and pd.isna(third.away_goals)  # not played yet


@pytest.mark.parametrize("raw, score", [("1–0", (1, 0)), ("2−3 ", (2, 3)), ("0-0", (0, 0)), ("", None), (" ", None),
                                         ("'''3–2'''", None), ("{{score|3|2}}", None), ("Match 12", None), ("1–0<ref>x</ref>", (1, 0))])
def test_scores_are_read_and_unplayed_matches_have_none(raw, score):
    assert parse_score(raw) == score


def test_a_team_field_gives_the_article_the_name_shown_and_the_country():
    assert parse_team("{{fbaicon|ENG}} [[Manchester City F.C.|Manchester City]]") == ("Manchester City F.C.", "Manchester City", "ENG")
    assert parse_team("[[LASK]] {{fbaicon|AUT}}") == ("LASK", "LASK", "AUT")


def test_the_article_title_follows_wikipedias_spelling():
    assert season_title("2026-27") == "2026–27_UEFA_Champions_League_league_phase"  # an en dash
    assert season_title("2099-00") == "2099–00_UEFA_Champions_League_league_phase"


def ring(played=0, clubs=CLUBS):
    """A made-up league phase: club i hosts the next four clubs, so every club has four home and four away matches."""
    rows = []
    for k in range(1, 5):
        for i in range(clubs):
            rows.append((k, i, (i + k) % clubs))
    league = pd.DataFrame({
        "matchday": [2 * k - 1 for k, _, _ in rows],
        "date": [pd.Timestamp("2026-09-08") + pd.Timedelta(days=7 * (k - 1)) for k, _, _ in rows],
        "home_page": [f"Club {h:02d} F.C." for _, h, _ in rows], "home": [f"Club {h:02d}" for _, h, _ in rows],
        "home_country": [("ENG", "ESP", "GER", "ITA", "FRA")[h % 5] if h < 10 else "NED" for _, h, _ in rows],
        "away_page": [f"Club {a:02d} F.C." for _, _, a in rows], "away": [f"Club {a:02d}" for _, _, a in rows],
        "away_country": [("ENG", "ESP", "GER", "ITA", "FRA")[a % 5] if a < 10 else "NED" for _, _, a in rows],
        "home_goals": np.nan, "away_goals": np.nan})
    league.loc[:played - 1, "home_goals"] = [(i * 7) % 4 for i in range(played)]
    league.loc[:played - 1, "away_goals"] = [(i * 5) % 3 for i in range(played)]
    return league


def test_a_whole_league_phase_is_recognised():
    assert check_league_phase(ring()) is None
    assert "matches listed" in check_league_phase(ring().iloc[:-1])
    crooked = ring()
    crooked.loc[0, "away_page"] = "Somebody else"  # a club that plays nine matches and another that plays seven
    assert "every one plays 8" in check_league_phase(crooked)
    undated = ring()
    undated.loc[3, "date"] = pd.NaT
    assert "no date" in check_league_phase(undated)


# ---------- naming the clubs ----------

def test_clubs_get_the_names_the_rest_of_the_model_uses():
    league = pd.DataFrame({
        "home_page": ["Manchester City F.C.", "Arsenal F.C.", "Some New Club"], "home": ["Manchester City", "Arsenal", "New Club"],
        "home_country": ["ENG", "ENG", "NED"],
        "away_page": ["Olympiacos F.C.", "Newly Promoted", "Viking FK"], "away": ["Olympiacos", "Newly Promoted", "Viking"],
        "away_country": ["GRE", "ENG", "NOR"]})
    known = {"Man City", "Arsenal", "Olympiacos (GRE)"}
    named, new = fc.resolve_names(league, known)
    assert list(named.home) == ["Man City", "Arsenal", "New Club (NED)"]  # a mapping, the name as it is, the way outside clubs are named
    assert list(named.away) == ["Olympiacos (GRE)", "Newly Promoted", "Viking (NOR)"]
    assert new == ["New Club (NED)", "Newly Promoted", "Viking (NOR)"]  # never seen playing before


def test_the_name_table_has_no_repeats():
    table = pd.read_csv(ROOT / "data" / "wikipedia_names.csv")
    assert table.wikipedia_page.is_unique and table.canonical.is_unique  # two articles for one club would merge two clubs


@pytest.mark.skipif(not data_path("2026-27").exists(), reason="needs data/raw/wikipedia: run scripts/download_data.py first")
@needs_raw_data
def test_this_seasons_league_phase_is_read_and_every_big_five_club_is_known():
    from matches import load_matches
    league = load_league_phase("2026-27")
    assert check_league_phase(league) is None
    assert league.home_goals.notna().sum() == league.away_goals.notna().sum() > 0
    history = load_matches()
    named, new = fc.resolve_names(league, set(history.home) | set(history.away))
    big_five = {"ENG", "ESP", "GER", "ITA", "FRA"}
    in_big_five = set(named.home[league.home_country.isin(big_five)]) | set(named.away[league.away_country.isin(big_five)])
    # Every big-five club has league results in the data, so one with no history has been given the wrong name.
    assert not [club for club in new if club in in_big_five], f"fix these in data/wikipedia_names.csv: {new}"


# ---------- the table ----------

def test_standings_count_what_uefa_counts():
    league = pd.DataFrame({
        "home": ["A", "A", "B"], "away": ["B", "C", "C"],
        "home_goals": [2.0, 1.0, np.nan], "away_goals": [0.0, 1.0, np.nan]})  # B v C not played
    table = fc.standings(league, ["A", "B", "C"])
    assert list(table["played"]) == [2, 1, 1]
    assert list(table["points"]) == [4, 0, 1]
    assert list(table["goals_for"]) == [3, 0, 1] and list(table["goals_against"]) == [1, 2, 1]
    assert list(table["away_goals_for"]) == [0, 0, 1]
    assert list(table["wins"]) == [1, 0, 0] and list(table["away_wins"]) == [0, 0, 0]


def blank_table():
    return {key: np.zeros(CLUBS, dtype=np.int64) for key in KEYS}


# Clubs 5 and 9 are level with everyone on everything, except as set here: club 5 is ahead on one thing and
# behind on every tie-breaker that comes after it, so it can only finish above club 9 if that one thing counts first.
TIE_BREAKERS = [
    ("points", {"points": 11, "goals_for": 0, "goals_against": 30, "away_goals_for": 0, "wins": 0, "away_wins": 0}),
    ("goal difference", {"goals_for": 9, "goals_against": 5, "away_goals_for": 0, "wins": 0, "away_wins": 0}),
    ("goals scored", {"goals_for": 11, "goals_against": 11, "away_goals_for": 0, "wins": 0, "away_wins": 0}),
    ("away goals scored", {"away_goals_for": 4, "wins": 0, "away_wins": 0}),
    ("wins", {"wins": 4, "away_wins": 0}),
    ("away wins", {"away_wins": 2}),
]


@pytest.mark.parametrize("name, club_5", TIE_BREAKERS, ids=[name for name, _ in TIE_BREAKERS])
def test_the_table_is_sorted_by_points_then_each_tie_breaker_in_turn(name, club_5):
    table = blank_table()
    for key, value in {"points": 10, "goals_for": 10, "goals_against": 10, "away_goals_for": 3, "wins": 3, "away_wins": 1}.items():
        table[key][:] = value
    for key, value in club_5.items():
        table[key][5] = value
    order = fc.league_phase(table, np.empty((0, 2), dtype=int), np.empty((0, 121)), 60, np.random.default_rng(0))
    position = lambda team: np.argmax(order == team, axis=0)
    assert (position(5) < position(9)).all(), name
    if name == "points":
        assert (position(5) == 0).all()  # a point more than everyone else is first place


def test_clubs_level_on_every_tie_breaker_are_ordered_by_chance():
    first_place = {fc.league_phase(blank_table(), np.empty((0, 2), dtype=int), np.empty((0, 121)), 1, np.random.default_rng(s))[0, 0]
                   for s in range(40)}
    assert len(first_place) > 10  # all 36 are level, so nearly any of them can finish first


def test_a_match_to_play_moves_the_clubs_in_the_table():
    table = blank_table()
    table["points"][:] = 4
    cdf = np.zeros(121)
    cdf[1 * 11 + 0:] = 1.0  # a certain 1-0 to the home side
    order = fc.league_phase(table, np.array([[7, 3]]), cdf[None, :], 50, np.random.default_rng(0))
    position = lambda team: np.argmax(order == team, axis=0)
    assert (position(7) == 0).all() and (position(3) == 35).all()  # +3 points, +1 goal difference; and the other way round
    cdf[:] = 0
    cdf[0 * 11 + 2:] = 1.0  # a certain 0-2 away win: the away side leads on points, goals and away goals
    order = fc.league_phase(table, np.array([[7, 3]]), cdf[None, :], 50, np.random.default_rng(0))
    assert (position(3) == 0).all() and (position(7) == 35).all()


# ---------- the simulation ----------

def equal_cdfs(count, lam=1.4, nu=1.1, rho=-0.05):
    return np.cumsum(score_matrix(np.full(count, lam), np.full(count, nu), rho).reshape(count, -1), axis=1)


def ring_fixtures():
    return np.array([(i, (i + k) % CLUBS) for k in range(1, 5) for i in range(CLUBS)])


def test_clubs_of_equal_strength_have_equal_chances_whatever_their_place_in_the_bracket():
    fixtures = ring_fixtures()
    even = np.full((CLUBS, CLUBS), 0.5)
    reach = fc.simulate(blank_table(), fixtures, equal_cdfs(len(fixtures)), even, even, n=40_000, seed=3)
    for stage, expected in {"top8": 8, "top24": 24, "last16": 16, "quarter": 8, "semi": 4, "final": 2, "win": 1}.items():
        assert reach[stage].sum() == pytest.approx(expected)
        assert reach[stage] == pytest.approx(np.full(CLUBS, expected / CLUBS), abs=0.012 if expected > 2 else 0.005), stage
    # A bye to the round of 16 is worth as much as the play-off round it skips, so nobody is favoured by finishing high.
    assert reach["win"].max() < 1 / CLUBS * 1.2 and reach["win"].min() > 1 / CLUBS * 0.8


def test_a_club_that_wins_everything_wins_the_trophy():
    fixtures = ring_fixtures()
    cdfs = equal_cdfs(len(fixtures))
    for k, (home, away) in enumerate(fixtures):
        if 0 in (home, away):
            cdfs[k] = 0.0
            cdfs[k, (5 * 11 + 0) if home == 0 else (0 * 11 + 5):] = 1.0  # 5-0 to club 0, at home or away
    through = np.full((CLUBS, CLUBS), 0.5)
    final = np.full((CLUBS, CLUBS), 0.5)
    through[0, :], through[:, 0] = 1.0, 0.0
    final[0, :], final[:, 0] = 1.0, 0.0
    reach = fc.simulate(blank_table(), fixtures, cdfs, through, final, n=2000, seed=1)
    assert reach["top8"][0] == 1 and reach["win"][0] == 1
    assert reach["win"][1:].sum() == 0


def positions(n=50):
    """A league phase with a known end: club i finishes in position i + 1, in every simulated season."""
    return np.tile(np.arange(CLUBS)[:, None], (1, n))


def seasons_where(stage_teams):
    return [set(stage_teams[:, s]) for s in range(stage_teams.shape[1])]


def lower_number_wins():
    final = np.zeros((CLUBS, CLUBS))
    final[np.triu_indices(CLUBS, 1)] = 1.0  # club 3 beats club 8, never the other way round
    return final


def test_when_the_team_hosting_the_second_leg_always_wins_the_best_seeds_go_all_the_way():
    through = np.zeros((CLUBS, CLUBS))  # whoever hosts the first leg loses
    reach = fc.knockouts(positions(), through, lower_number_wins(), np.random.default_rng(0))
    assert all(s == set(range(16)) for s in seasons_where(reach["last16"]))  # the seeded team won every play-off
    assert all(s == set(range(8)) for s in seasons_where(reach["quarter"]))
    assert all(s == {0, 1, 2, 3} for s in seasons_where(reach["semi"]))
    assert all(s == {0, 1} for s in seasons_where(reach["final"]))
    assert (reach["win"] == 0).all()  # club 0 is champion in every season


def test_when_the_team_hosting_the_first_leg_always_wins_the_unseeded_teams_take_over_the_seeds_places():
    through = np.ones((CLUBS, CLUBS))  # whoever hosts the first leg wins
    reach = fc.knockouts(positions(), through, lower_number_wins(), np.random.default_rng(0))
    assert all(s == set(range(8)) | set(range(16, 24)) for s in seasons_where(reach["last16"]))
    assert all(s == set(range(16, 24)) for s in seasons_where(reach["quarter"]))  # the round-of-16 winners hosted the first leg
    # In the quarter-finals the team in the worse place hosts the first leg. Those are the seeds the 22nd and
    # 23rd place sides took over (7th and 8th), and the 20th and 21st sides (5th and 6th), and so on.
    assert all(s == {20, 21, 22, 23} for s in seasons_where(reach["semi"]))
    assert all(s == {20, 21} for s in seasons_where(reach["final"]))


def test_every_stage_has_the_right_number_of_clubs_in_every_season():
    rng = np.random.default_rng(5)
    through = rng.random((CLUBS, CLUBS))
    final = rng.random((CLUBS, CLUBS))
    order = np.argsort(rng.random((CLUBS, 300)), axis=0)
    reach = fc.knockouts(order, through, final, rng)
    for stage, size in {"top8": 8, "top24": 24, "last16": 16, "quarter": 8, "semi": 4, "final": 2, "win": 1}.items():
        assert reach[stage].shape == (size, 300)
        assert all(len(set(reach[stage][:, s])) == size for s in range(300)), stage  # nobody twice
    for later, earlier in (("last16", "top24"), ("quarter", "last16"), ("semi", "quarter"), ("final", "semi"), ("win", "final")):
        assert all(set(reach[later][:, s]) <= set(reach[earlier][:, s]) for s in range(300)), (later, earlier)


def test_a_simulation_gives_the_same_answer_for_the_same_seed():
    fixtures = ring_fixtures()[:60]
    args = (blank_table(), fixtures, equal_cdfs(60), np.full((CLUBS, CLUBS), 0.5), np.full((CLUBS, CLUBS), 0.5))
    a, b, c = (fc.simulate(*args, n=500, seed=s) for s in (1, 1, 2))
    assert all((a[stage] == b[stage]).all() for stage in a)
    assert any((a[stage] != c[stage]).any() for stage in a)


# ---------- the bracket, against what happened ----------

@needs_raw_data
def test_the_bracket_is_the_one_used_in_2025_26():
    """Replay last season's knockout phase against the bracket in forecast.py: who was drawn against
    whom, who met in the quarter-finals and semi-finals, and who hosted the second leg."""
    from matches import load_matches
    cl = load_matches().query("competition == 'CL' and season == '2025-26'")
    league = cl[cl["round"].fillna("").str.startswith("League")]
    teams = sorted(set(league.home) | set(league.away))
    table = fc.standings(league, teams)
    goal_difference = table["goals_for"] - table["goals_against"]
    order = sorted(range(len(teams)), key=lambda i: (-table["points"][i], -goal_difference[i], -table["goals_for"][i],
                                                     -table["away_goals_for"][i], -table["wins"][i], -table["away_wins"][i]))
    position = {teams[i]: p for p, i in enumerate(order)}  # 0 is first place

    def ties(name):
        part = cl[cl["round"] == name].sort_values("date")
        found = {}
        for row in part.itertuples():
            found.setdefault(frozenset((row.home, row.away)), []).append(row)
        return [(legs[0], legs[-1]) for legs in found.values()]  # (first leg, second leg)

    # Play-offs: positions 9 to 16 against 17 to 24, the seeded side hosting the second leg.
    section_of, seed_of = {}, {}  # the round-of-16 seeds a play-off winner can meet
    for first, second in ties("Playoffs"):
        seeded, unseeded = second.home, second.away
        assert first.home == unseeded and 8 <= position[seeded] <= 15 and 16 <= position[unseeded] <= 23
        section = next(i for i, (high, low) in enumerate(fc.PLAYOFFS)
                       if position[seeded] in high and position[unseeded] in low)
        section_of[seeded] = section_of[unseeded] = section

    # Round of 16: a top-eight side against the winner of its section; the seeded side hosts the second leg.
    slot = {}  # the seed a team holds from here on
    for first, second in ties("Round of 16"):
        seeded, visitor = second.home, second.away
        assert first.home == visitor and position[seeded] < 8
        assert position[seeded] in fc.ROUND_OF_16_SEEDS[section_of[visitor]], (seeded, visitor)
        winner = actual_winner(first, second)
        slot[winner] = position[seeded]

    quarter_slot = {}
    for first, second in ties("Quarterfinals"):
        a, b = slot[second.home], slot[second.away]
        assert a < b, "the better seed hosts the second leg, even if the club in it finished lower"
        assert (a, b) in fc.QUARTER_FINALS
        quarter_slot[actual_winner(first, second)] = a
    for first, second in ties("Semifinals"):
        a, b = quarter_slot[second.home], quarter_slot[second.away]
        assert a < b and (a, b) in fc.SEMI_FINALS


def actual_winner(first, second):
    """Who went through a two-legged tie (no away goals rule since 2021-22)."""
    from knockouts import goals_after
    home = goals_after(first, "home") + goals_after(second, "away")
    away = goals_after(first, "away") + goals_after(second, "home")
    if home != away:
        return first.home if home > away else first.away
    return second.home if second.home_pens > second.away_pens else second.away


# ---------- the whole forecast ----------

def made_up_history(seed=0):
    """Two years of results among the 36 made-up clubs, so there is something to fit."""
    rng = np.random.default_rng(seed)
    pairs = [(i, j) for i in range(CLUBS) for j in range(CLUBS) if i != j]
    strength = np.linspace(1.0, -1.0, CLUBS)
    rows = []
    for k, (i, j) in enumerate(pairs):
        rows.append({"competition": "CL", "season": "2025-26", "date": pd.Timestamp("2025-01-01") + pd.Timedelta(days=k % 600),
                     "home": f"Club {i:02d}", "away": f"Club {j:02d}", "neutral": False,
                     "home_goals": rng.poisson(np.exp(0.2 + 0.25 + strength[i] - strength[j])),
                     "away_goals": rng.poisson(np.exp(0.2 + strength[j] - strength[i]))})
    return pd.DataFrame(rows)


@pytest.fixture
def made_up_season(monkeypatch):
    state = {"league": ring(played=72)}
    monkeypatch.setattr(fc, "load_league_phase", lambda season: state["league"])
    return state


def test_two_clubs_given_one_name_are_refused_rather_than_merged(made_up_season, monkeypatch):
    real = fc.resolve_names

    def merging(league, known):
        league, new = real(league, known)
        return league.assign(home=league.home.replace("Club 05", "Club 04"), away=league.away.replace("Club 05", "Club 04")), new

    monkeypatch.setattr(fc, "resolve_names", merging)
    with pytest.raises(fc.NoForecast, match="same name"):
        fc.forecast("2026-11-05", n=100, history=made_up_history())


def test_a_forecast_has_every_club_and_every_stage_adds_up(made_up_season):
    result = fc.forecast("2026-11-05", n=3000, history=made_up_history())
    assert (result["season"], result["as_of"], result["played"], result["left"], result["matches"]) == ("2026-27", "2026-11-05", 72, 72, 144)
    assert len(result["clubs"]) == CLUBS and result["new_clubs"] == []
    for stage, size in SUMS.items():
        assert sum(c[stage] for c in result["clubs"]) == pytest.approx(size, abs=1e-4), stage
    for club in result["clubs"]:
        assert 0 <= club["win"] <= club["final"] <= club["semi"] <= club["quarter"] <= club["last16"] <= club["top24"] <= 1
        assert club["top8"] <= club["last16"]
        assert club["played"] == 4  # two matchdays of the made-up fixtures, two matches each
    assert [c["win"] for c in result["clubs"]] == sorted((c["win"] for c in result["clubs"]), reverse=True)
    assert sum(c["played"] for c in result["clubs"]) == 2 * 72
    json.dumps(result, allow_nan=False)  # plain data


def test_a_forecast_can_be_made_before_a_single_match_is_played(made_up_season):
    made_up_season["league"] = ring(played=0)  # the draw has been made and the article lists the fixtures
    result = fc.forecast("2026-09-01", n=500, history=made_up_history())
    assert (result["played"], result["left"]) == (0, 144) and all(c["played"] == 0 and c["points"] == 0 for c in result["clubs"])
    assert sum(c["win"] for c in result["clubs"]) == pytest.approx(1, abs=1e-4)


# ---------- which matches matter ----------

def test_recording_the_results_does_not_change_the_forecast():
    """Keeping every simulated match result must not use a random number, so nothing else moves."""
    fixtures = ring_fixtures()
    args = (blank_table(), fixtures, equal_cdfs(len(fixtures)), np.full((CLUBS, CLUBS), 0.5), np.full((CLUBS, CLUBS), 0.5))
    plain = fc.simulate(*args, n=800, seed=4)
    record = {}
    kept = fc.simulate(*args, n=800, seed=4, record=record)
    for stage in plain:
        assert np.array_equal(plain[stage], kept[stage]), stage
    assert record["outcomes"].shape == (len(fixtures), 800) and set(np.unique(record["outcomes"])) <= {0, 1, 2}
    assert record["top8"].shape == (CLUBS, 800) and (record["top8"].sum(axis=0) == 8).all()  # eight clubs a season


def test_a_matchs_leverage_is_read_off_the_seasons_where_it_ended_that_way():
    """Three clubs, one match (club 0 at home to club 1), ten simulated seasons worked out by hand."""
    outcomes = np.array([[0, 0, 0, 0, 1, 1, 1, 2, 2, 2]], dtype=np.int8)  # four home wins, three draws, three away wins
    top8 = np.zeros((3, 10), dtype=bool)
    top8[0, [0, 1, 2, 3, 4]] = True       # club 0 is in the top eight after all four wins and one draw
    top8[1, [4, 5, 7, 8, 9]] = True       # club 1: in the top eight after all three of its wins and two of its three draws
    top8[2, :] = True                     # club 2 is not in the match and always makes it
    record = {"outcomes": outcomes, "top8": top8}
    lv = fc.match_leverage(record, np.array([[0, 1]]), ["A", "B", "C"], ["2026-11-24"])
    assert lv["matches"] == [{"date": "2026-11-24", "home": "A", "away": "B", "shares": [0.4, 0.3, 0.3]}]
    (home,), (away,) = lv["clubs"]["A"], lv["clubs"]["B"]
    assert home == {"match": 0, "top8": [1.0, 0.3333, 0.0], "swing": 1.0}     # if they win, draw, lose
    # Club 1 wins in seasons 7, 8, 9 (in the top eight in 7, 8, 9: all three), draws in 4, 5, 6 (4 and 5), loses in 0..3 (none).
    assert away == {"match": 0, "top8": [1.0, 0.6667, 0.0], "swing": 1.0}
    assert lv["clubs"]["C"] == []
    assert [e["club"] for e in lv["soon"]] == ["A"]  # one club per match: the first of two equal swings


def test_an_unlikely_result_is_left_out_of_the_swing():
    outcomes = np.array([[0] * 49 + [2] * 1 + [1] * 50], dtype=np.int8)  # the away win is 1 in 100: noise, not a swing
    top8 = np.zeros((2, 100), dtype=bool)
    top8[0, 49] = True          # the one season behind the away win has club 0 in the top eight
    top8[0, :49] = True
    lv = fc.match_leverage({"outcomes": outcomes, "top8": top8}, np.array([[0, 1]]), ["A", "B"], ["2026-11-24"])
    entry = lv["clubs"]["A"][0]
    assert entry["top8"] == [1.0, 0.0, 1.0] and entry["swing"] == 1.0  # win against draw: the lone loss is ignored


def test_every_match_still_to_play_has_a_swing_for_both_clubs(made_up_season):
    result = fc.forecast("2026-11-05", n=3000, history=made_up_history())
    lv = result["leverage"]
    assert len(lv["matches"]) == result["left"] == 72
    assert set(lv["clubs"]) == {c["club"] for c in result["clubs"]}
    for club, entries in lv["clubs"].items():
        assert len(entries) == 4  # four matches left for every club in the made-up season
        assert [e["swing"] for e in entries] == sorted((e["swing"] for e in entries), reverse=True)
        for e in entries:
            assert len(e["top8"]) == 3 and all(0 <= x <= 1 for x in e["top8"]) and 0 <= e["swing"] <= 1
            assert club in (lv["matches"][e["match"]]["home"], lv["matches"][e["match"]]["away"])
    # Winning helps: across all clubs and matches a win leaves a club better placed than a loss.
    gaps = [e["top8"][0] - e["top8"][2] for entries in lv["clubs"].values() for e in entries]
    assert np.mean(gaps) > 0.1
    soon = lv["soon"]
    assert 0 < len(soon) <= fc.LEVERAGE_SHOWN and len({e["match"] for e in soon}) == len(soon)
    first = min(m["date"] for m in lv["matches"])
    assert all(lv["matches"][e["match"]]["date"] <= f"{pd.Timestamp(first) + pd.Timedelta(days=fc.LEVERAGE_SOON_DAYS):%Y-%m-%d}" for e in soon)
    assert [e["swing"] for e in soon] == sorted((e["swing"] for e in soon), reverse=True)
    json.dumps(lv, allow_nan=False)


def test_leverage_is_left_out_when_the_ratings_are_nudged_or_nothing_is_left_to_play(made_up_season):
    nudged = fc.forecast("2026-11-05", n=400, history=made_up_history(), noise=0.1, worlds=2)
    assert "leverage" not in nudged
    made_up_season["league"] = ring(played=144)
    assert "leverage" not in fc.forecast("2026-10-01", n=200, history=made_up_history(), knockouts=None)


def test_uncertain_ratings_split_the_simulations_over_nudged_worlds_and_flatten_the_favourites(made_up_season):
    history = made_up_history()
    plain = fc.forecast("2026-11-05", n=4000, history=history)
    same = fc.forecast("2026-11-05", n=4000, history=history, noise=0.0, worlds=7)
    assert same == plain  # no noise: the worlds make no difference
    nudged = fc.forecast("2026-11-05", n=4003, history=history, noise=0.4, worlds=7)  # 4003 doesn't divide by 7
    for stage, size in SUMS.items():
        assert sum(c[stage] for c in nudged["clubs"]) == pytest.approx(size, abs=1e-4), stage  # still every simulation counted once
    best = lambda result: max(c["win"] for c in result["clubs"])
    assert best(nudged) < best(plain)  # a favourite whose strength is uncertain is less of a favourite


def test_a_nudged_copy_of_the_ratings_leaves_the_original_alone():
    from dixon_coles import fit
    history = made_up_history()
    model = fit(history, pd.Timestamp("2026-11-05"), xi=0.002, prior_weight=3.0, newcomer=0.2)
    before = model.attack.copy()
    other = fc.nudged(model, 0.3, np.random.default_rng(0))
    assert (model.attack == before).all() and not np.allclose(other.attack, before) and other.index == model.index
    assert np.std(other.attack - before) == pytest.approx(0.3, abs=0.08)


def test_the_favourite_is_one_of_the_strongest_made_up_clubs(made_up_season):
    result = fc.forecast("2026-11-05", n=3000, history=made_up_history())
    assert int(result["clubs"][0]["club"][-2:]) < 8 and int(result["clubs"][-1]["club"][-2:]) > 27  # strongest first, weakest last


def test_the_forecast_stays_until_the_knockout_phase_begins(made_up_season):
    made_up_season["league"] = ring(played=144)
    last = made_up_season["league"].date.max()
    during = fc.forecast(last + pd.Timedelta(days=3), n=500, history=made_up_history())
    assert during["left"] == 0 and during["played"] == 144  # the table is final, the knockouts are still to come
    assert sum(c["win"] for c in during["clubs"]) == pytest.approx(1, abs=1e-4)
    with pytest.raises(fc.NoForecast) as stopped:
        fc.forecast(last + pd.Timedelta(days=fc.KNOCKOUTS_START_DAYS + 1), n=500, history=made_up_history())
    assert stopped.value.over


def test_without_the_data_there_is_no_forecast_but_the_stage_is_not_over(monkeypatch):
    monkeypatch.setattr(fc, "load_league_phase", lambda season: None)
    with pytest.raises(fc.NoForecast) as missing:
        fc.forecast("2026-11-05", n=100, history=made_up_history())
    assert not missing.value.over
    monkeypatch.setattr(fc, "load_league_phase", lambda season: ring(played=10).iloc[:100])
    with pytest.raises(fc.NoForecast, match="matches listed") as broken:
        fc.forecast("2026-11-05", n=100, history=made_up_history())
    assert not broken.value.over


def test_matches_already_in_the_main_data_are_not_counted_twice(made_up_season, monkeypatch):
    history = made_up_history()
    have = made_up_season["league"].iloc[:20]  # the main data already has the first 20 played matches
    copies = pd.DataFrame({"competition": "CL", "season": "2026-27", "date": have.date, "home": have.home, "away": have.away,
                           "home_goals": have.home_goals.astype(int), "away_goals": have.away_goals.astype(int), "neutral": False})
    seen = {}
    real_fit = fc.fit

    def spy(combined, ref_date, **kwargs):
        seen["rows"] = len(combined)
        return real_fit(combined, ref_date, **kwargs)

    monkeypatch.setattr(fc, "fit", spy)
    fc.forecast("2026-11-05", n=100, history=pd.concat([history, copies], ignore_index=True))
    assert seen["rows"] == len(history) + 72  # each of the 72 played matches once


def test_the_command_writes_the_forecast_and_removes_it_only_when_the_stage_is_over(made_up_season, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(fc, "OUTPUT", tmp_path / "forecast.json")
    monkeypatch.setattr(fc, "load_matches", lambda: made_up_history())
    assert fc.main(["--as-of", "2026-11-05", "--simulations", "300"]) == 0
    written = json.loads((tmp_path / "forecast.json").read_text(encoding="utf-8"))
    assert written["simulations"] == 300 and "Favourites:" in capsys.readouterr().out
    assert pd.read_csv(fc.HISTORY).as_of.unique().tolist() == ["2026-11-05"]  # the day went into the history, in the temporary one
    monkeypatch.setattr(fc, "load_league_phase", lambda season: None)  # no data: the last forecast stays, and it is reported
    assert fc.main(["--as-of", "2026-11-06"]) == 1
    assert (tmp_path / "forecast.json").exists()
    made_up_season["league"] = ring(played=144)
    monkeypatch.setattr(fc, "load_league_phase", lambda season: made_up_season["league"])
    assert fc.main(["--as-of", "2027-03-01"]) == 0  # long after the league phase: out of season, so it goes
    assert not (tmp_path / "forecast.json").exists()
    assert "No forecast" in capsys.readouterr().out


# ---------- the saved forecast and the page ----------

@pytest.fixture
def saved():
    if not SAVED.exists():
        pytest.skip("no forecast is saved outside the league phase")
    return json.loads(SAVED.read_text(encoding="utf-8"))


def test_the_saved_forecast_adds_up(saved):
    assert len(saved["clubs"]) == CLUBS and len({c["club"] for c in saved["clubs"]}) == CLUBS
    assert saved["played"] + saved["left"] == saved["matches"] == 144
    for stage, size in SUMS.items():
        assert sum(c[stage] for c in saved["clubs"]) == pytest.approx(size, abs=1e-3), stage
    assert sum(c["played"] for c in saved["clubs"]) == 2 * saved["played"]
    for club in saved["clubs"]:
        assert 0 <= club["win"] <= club["final"] <= club["semi"] <= club["quarter"] <= club["last16"] <= club["top24"] <= 1, club["club"]
        assert club["top8"] <= club["last16"] and club["points"] <= 3 * club["played"] <= 24, club["club"]
    wins = [c["win"] for c in saved["clubs"]]
    assert wins == sorted(wins, reverse=True)
    assert set(saved["new_clubs"]) <= {c["club"] for c in saved["clubs"]}


def test_the_saved_forecasts_match_swings_are_consistent(saved):
    lv = saved.get("leverage")
    if lv is None:
        pytest.skip("this saved forecast was made before matches that matter were added, or is past the league phase")
    assert len(lv["matches"]) == saved["left"]
    for entries in lv["clubs"].values():
        assert all(0 <= x <= 1 for e in entries for x in e["top8"])
        assert [e["swing"] for e in entries] == sorted((e["swing"] for e in entries), reverse=True)


def test_the_page_carries_the_saved_forecast_unless_it_is_stale(data, saved, tmp_path, monkeypatch):
    import export_site
    monkeypatch.setattr(export_site, "RESULTS", tmp_path)
    assert export_site.forecast_section() is None  # nothing saved
    (tmp_path / "forecast.json").write_text(json.dumps(saved), encoding="utf-8")
    day = pd.Timestamp(saved["as_of"])
    monkeypatch.setattr(export_site, "today", lambda: day + pd.Timedelta(days=export_site.FORECAST_FRESH_DAYS))
    assert export_site.forecast_section() == saved
    monkeypatch.setattr(export_site, "today", lambda: day + pd.Timedelta(days=export_site.FORECAST_FRESH_DAYS + 1))
    assert export_site.forecast_section() is None  # a forecast nobody has refreshed lately is not shown as current


def test_the_page_data_is_the_saved_forecast(data, saved):
    # Not always there: the exporter leaves out a forecast that has gone stale.
    assert data["forecast"] is None or {k: v for k, v in data["forecast"].items() if k != "history"} == saved


# ---------- the history of forecasts ----------

def test_a_days_forecast_replaces_that_days_earlier_one_and_keeps_the_rest(made_up_season, tmp_path):
    history = made_up_history()
    path = tmp_path / "history.csv"
    first = fc.forecast("2026-11-05", n=300, history=history)
    fc.add_to_history(first, path)
    fc.add_to_history(fc.forecast("2026-11-06", n=300, history=history), path)
    fc.add_to_history(fc.forecast("2026-11-05", n=300, seed=9, history=history), path)  # run again the same day
    table = pd.read_csv(path)
    assert sorted(table.as_of.unique()) == ["2026-11-05", "2026-11-06"] and (table.groupby("as_of").size() == CLUBS).all()
    same_day = table[table.as_of == "2026-11-05"].set_index("club").win
    assert same_day.sum() == pytest.approx(1, abs=1e-4) and not same_day.equals(pd.Series({c["club"]: c["win"] for c in first["clubs"]}).sort_index())


def test_a_backfill_starts_before_the_first_matchday_and_uses_only_matches_played_by_then(made_up_season, tmp_path, monkeypatch):
    made_up_season["league"] = ring(played=72)  # two of the four made-up matchdays are done
    monkeypatch.setattr(fc, "load_matches", lambda: made_up_history())
    path = tmp_path / "history.csv"
    fc.backfill("2026-27", n=300, path=path)
    table = pd.read_csv(path)
    assert table.as_of.nunique() == 1 + 4 or table.as_of.nunique() >= 3
    played = table.groupby("as_of").played.sum().tolist()
    assert played[0] == 0 and played == sorted(played) and played[-1] == 2 * 72  # more is known each day
    assert (table.groupby("as_of").win.sum().round(3) == 1).all()


def test_the_page_gets_each_clubs_title_odds_day_by_day(saved, tmp_path, monkeypatch):
    import export_site
    monkeypatch.setattr(export_site, "RESULTS", tmp_path)
    (tmp_path / "forecast.json").write_text(json.dumps(saved), encoding="utf-8")
    monkeypatch.setattr(export_site, "today", lambda: pd.Timestamp(saved["as_of"]))
    rows = [{"season": saved["season"], "as_of": d, "club": c["club"], "win": c["win"] * k}
            for d, k in (("2026-09-01", 0.5), (saved["as_of"], 1), ("2099-01-01", 3)) for c in saved["clubs"]]  # the last is in the future
    pd.DataFrame(rows + [{"season": "2025-26", "as_of": "2026-01-01", "club": "Arsenal", "win": 0.9}]).to_csv(tmp_path / "forecast_history.csv", index=False)
    history = export_site.forecast_section()["history"]
    assert history["dates"] == ["2026-09-01", saved["as_of"]]  # this season, up to today
    assert set(history["win"]) == {c["club"] for c in saved["clubs"]} and all(len(v) == 2 for v in history["win"].values())
    assert history["win"][saved["clubs"][0]["club"]][1] == pytest.approx(saved["clubs"][0]["win"])
