"""The daily pipeline: downloads, the prediction ledger and knockout ties.

Everything runs on temporary files; nothing here touches data/ or results/.
"""

import importlib.util
import io
import json
import urllib.error
import warnings
from datetime import date, datetime, timezone

import pandas as pd
import pytest

from conftest import ROOT, needs_raw_data


class _Reply(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


def _replying(body):
    return lambda url, timeout=30: _Reply(body)


def _failing(error):
    def opener(url, timeout=30):
        raise error
    return opener


@pytest.fixture
def download():
    spec = importlib.util.spec_from_file_location("download_data", ROOT / "scripts" / "download_data.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.PAUSE_SECONDS = 0
    return module


# ---------- downloads ----------

@pytest.mark.parametrize("error", [
    urllib.error.HTTPError("http://x", 404, "Not Found", None, None),
    urllib.error.URLError("no network"),
    TimeoutError("timed out"),
], ids=["http-404", "no-network", "timeout"])
def test_failed_refresh_keeps_the_old_file(download, tmp_path, monkeypatch, error):
    dest = tmp_path / "E0.csv"
    dest.write_bytes(b"old season data")
    monkeypatch.setattr(download.urllib.request, "urlopen", _failing(error))
    result = download.fetch("http://x", dest, refresh=True)
    assert dest.read_bytes() == b"old season data"
    assert result.startswith("kept old copy")


def test_failed_download_of_a_new_file_reports_missing(download, tmp_path, monkeypatch):
    monkeypatch.setattr(download.urllib.request, "urlopen", _failing(urllib.error.URLError("no network")))
    dest = tmp_path / "new.csv"
    assert download.fetch("http://x", dest).startswith("missing")
    assert not dest.exists()


def test_successful_refresh_replaces_the_file_completely(download, tmp_path, monkeypatch):
    dest = tmp_path / "E0.csv"
    dest.write_bytes(b"old")
    monkeypatch.setattr(download.urllib.request, "urlopen", _replying(b"new season data"))
    assert download.fetch("http://x", dest, refresh=True) == "refreshed"
    assert dest.read_bytes() == b"new season data"
    assert not list(tmp_path.glob("*.part"))


def test_files_on_disk_are_kept_without_refresh(download, tmp_path, monkeypatch):
    dest = tmp_path / "E0.csv"
    dest.write_bytes(b"old")
    monkeypatch.setattr(download.urllib.request, "urlopen", _failing(AssertionError("should not download")))
    assert download.fetch("http://x", dest) == "kept"


def test_a_reply_that_is_not_what_was_asked_for_is_never_saved(download, tmp_path, monkeypatch):
    monkeypatch.setattr(download.urllib.request, "urlopen", _replying(b'{"error": {"code": "missingtitle"}}'))
    has_text = lambda data: "parse" in json.loads(data)
    dest = tmp_path / "page.json"
    assert download.fetch("http://x", dest, valid=has_text).startswith("missing")
    assert not dest.exists()
    dest.write_bytes(b"old copy")
    assert download.fetch("http://x", dest, refresh=True, valid=has_text).startswith("kept old copy")
    assert dest.read_bytes() == b"old copy"


def test_the_league_phase_is_fetched_from_wikipedia_by_name(download, tmp_path, monkeypatch):
    seen = {}

    def opener(request, timeout=30):
        seen["url"], seen["agent"] = request.full_url, request.get_header("User-agent")
        return _Reply(json.dumps({"parse": {"wikitext": "some text"}}).encode())

    monkeypatch.setattr(download.urllib.request, "urlopen", opener)
    monkeypatch.setattr(download, "RAW", tmp_path)
    assert download.league_phase(2026) == "downloaded"
    assert "page=2026%E2%80%9327_UEFA_Champions_League_league_phase" in seen["url"]  # with an en dash
    assert "ucl-luck" in seen["agent"]  # Wikipedia asks who is calling
    saved = json.loads((tmp_path / "wikipedia" / "2026-27-league-phase.json").read_text(encoding="utf-8"))
    assert saved["parse"]["wikitext"] == "some text"
    # A season whose article doesn't exist yet comes back as an error message, with a success status.
    monkeypatch.setattr(download.urllib.request, "urlopen", _replying(b'{"error": {"code": "missingtitle"}}'))
    assert download.league_phase(2027).startswith("missing")
    assert not (tmp_path / "wikipedia" / "2027-28-league-phase.json").exists()


@pytest.mark.parametrize("day, season", [
    (date(2026, 6, 30), 2025), (date(2026, 7, 1), 2026), (date(2027, 1, 15), 2026), (date(2027, 7, 1), 2027)])
def test_current_season_rolls_over_on_1_july(download, day, season):
    assert download.current_season(day) == season


# ---------- fixtures: only matches still to kick off ----------

FIXTURES = """Div,Date,Time,HomeTeam,AwayTeam
E0,07/11/2026,12:30,Arsenal,Chelsea
E0,07/11/2026,17:30,Liverpool,Everton
E0,07/11/2026,17:30,Liverpool,Everton
E0,07/11/2026,,Fulham,Brentford
E0,08/11/2026,,Newcastle,Burnley
SP1,07/11/2026,20:00,Barcelona,Getafe
B1,08/11/2026,15:00,Genk,Gent
"""


@pytest.fixture
def update(tmp_path, monkeypatch):
    import update as module
    (tmp_path / "data" / "raw").mkdir(parents=True)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "LEDGER", tmp_path / "prediction_ledger.csv")
    return module


def test_only_fixtures_still_to_kick_off_are_predicted(update, monkeypatch):
    monkeypatch.setattr(update.urllib.request, "urlopen", _replying(FIXTURES.encode()))
    now = datetime(2026, 11, 7, 14, 0, tzinfo=timezone.utc)  # in November UK time is UTC
    fixtures = update.upcoming_fixtures(now)
    assert sorted(zip(fixtures.home, fixtures.away)) == [
        ("Barcelona", "Getafe"),  # kicks off later today
        ("Liverpool", "Everton"),  # later today, listed twice: kept once
        ("Newcastle", "Burnley"),  # tomorrow, no time given
    ]  # not Arsenal v Chelsea (already kicked off), Fulham v Brentford (today, time unknown), Genk v Gent (not big five)
    assert set(fixtures.season) == {"2026-27"}


def test_kick_off_times_are_read_as_uk_time(update, monkeypatch):
    summer = "Div,Date,Time,HomeTeam,AwayTeam\nE0,15/08/2026,15:00,Leeds,Wolves\n"
    monkeypatch.setattr(update.urllib.request, "urlopen", _replying(summer.encode()))
    # 15:00 in August is 14:00 UTC (British Summer Time), so at 14:30 UTC it has started.
    assert update.upcoming_fixtures(datetime(2026, 8, 15, 13, 30, tzinfo=timezone.utc)).shape[0] == 1
    assert update.upcoming_fixtures(datetime(2026, 8, 15, 14, 30, tzinfo=timezone.utc)).shape[0] == 0


def test_season_boundary_is_1_july(update):
    seasons = update.season_of(pd.Series(pd.to_datetime(["2027-06-30", "2027-07-01"])))
    assert seasons.tolist() == ["2026-27", "2027-28"]


# ---------- the ledger: predictions are never changed or duplicated ----------

def _prediction(day, p_home=0.6):
    return pd.DataFrame({"competition": ["E0"], "season": ["2026-27"], "date": [pd.Timestamp(day)],
                         "kickoff": [f"{day} 15:00 UTC"], "home": ["Liverpool"], "away": ["Everton"],
                         "p_home": [p_home], "p_draw": [0.25], "p_away": [1 - p_home - 0.25]})


def test_an_empty_old_format_ledger_takes_its_first_prediction(update):
    pd.DataFrame(columns=["date", "home", "away", "competition", "p_home", "p_draw", "p_away",
                          "predicted_at", "brier"]).to_csv(update.LEDGER, index=False)
    with warnings.catch_warnings():
        warnings.simplefilter("error", FutureWarning)
        ledger, added = update.add_to_ledger(_prediction("2026-11-08"), "2026-11-05 05:30 UTC")
    assert added == 1 and len(ledger) == 1


def test_a_moved_match_keeps_its_original_prediction_and_is_scored(update):
    first, _ = update.add_to_ledger(_prediction("2026-11-08", 0.6), "2026-11-05 05:30 UTC")
    first.to_csv(update.LEDGER, index=False)
    ledger, added = update.add_to_ledger(_prediction("2026-11-09", 0.5), "2026-11-07 05:30 UTC")
    assert added == 0 and len(ledger) == 1
    assert ledger.predicted_at.iloc[0] == "2026-11-05 05:30 UTC" and ledger.p_home.iloc[0] == 0.6
    played = pd.DataFrame({"competition": ["E0"], "season": ["2026-27"], "date": [pd.Timestamp("2026-11-09")],
                           "home": ["Liverpool"], "away": ["Everton"], "home_goals": [2], "away_goals": [0],
                           "book_home": [0.62], "book_draw": [0.23], "book_away": [0.15]})
    scored = update.score_ledger(ledger, played)
    assert scored.brier.notna().sum() == 1


def test_a_new_fixture_is_added_alongside_existing_ones(update):
    first, _ = update.add_to_ledger(_prediction("2026-11-08"), "2026-11-05 05:30 UTC")
    first.to_csv(update.LEDGER, index=False)
    other = _prediction("2026-11-08").assign(home="Arsenal", away="Chelsea")
    ledger, added = update.add_to_ledger(other, "2026-11-06 05:30 UTC")
    assert added == 1 and len(ledger) == 2


# ---------- knockout ties ----------

@needs_raw_data
def test_an_unfinished_two_legged_tie_is_skipped_not_decided(tmp_path, monkeypatch):
    import knockouts
    from matches import load_matches

    matches = load_matches()
    last16 = matches[(matches.competition == "CL") & (matches.season == "2025-26") & (matches["round"] == "Round of 16")]
    pairs = last16.apply(lambda row: frozenset((row.home, row.away)), axis=1)
    second_legs = last16.sort_values("date").groupby(pairs).tail(1).index
    monkeypatch.setattr(knockouts, "load_matches", lambda: matches.drop(second_legs))
    monkeypatch.setattr(knockouts, "RESULTS", tmp_path)
    (tmp_path / "dixon_coles_settings.csv").write_bytes((ROOT / "results" / "dixon_coles_settings.csv").read_bytes())
    knockouts.main()
    ties = pd.read_csv(tmp_path / "knockout_ties.csv")
    full = pd.read_csv(ROOT / "results" / "knockout_ties.csv")
    assert len(ties) == len(full) - len(second_legs) == len(full) - 8
    assert not ((ties.season == "2025-26") & (ties["round"] == "Round of 16")).any()


# ---------- what the dashboard gets about upcoming predictions ----------

def test_bookmaker_odds_are_saved_as_chances(update, monkeypatch):
    fixtures = ("Div,Date,Time,HomeTeam,AwayTeam,AvgH,AvgD,AvgA\n"
                "E0,08/11/2026,16:30,Arsenal,Chelsea,2.0,3.5,4.0\n"
                "E0,08/11/2026,14:00,Leeds,Wolves,,,\n")
    monkeypatch.setattr(update.urllib.request, "urlopen", _replying(fixtures.encode()))
    rows = update.upcoming_fixtures(datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc)).set_index("home")
    arsenal = rows.loc["Arsenal", ["odds_home", "odds_draw", "odds_away"]].to_numpy(float)
    assert arsenal.sum() == pytest.approx(1)  # the bookmakers' margin is taken out
    assert arsenal[0] > arsenal[1] > arsenal[2]
    assert rows.loc["Leeds", ["odds_home", "odds_draw", "odds_away"]].isna().all()  # no odds listed: left empty


def test_upcoming_predictions_never_put_nan_in_data_json(tmp_path, monkeypatch):
    # Upcoming rows have no result or score yet. A NaN in data.json would stop the page loading.
    import json
    import export_site
    live = tmp_path / "live"
    live.mkdir()
    pd.DataFrame({"club": ["Arsenal"], "attack": [0.3], "defence": [0.8], "overall": [1.1], "scores": [1.8],
                  "concedes": [0.6], "win": [0.66], "draw": [0.23], "lose": [0.11]}).to_csv(live / "ratings.csv", index=False)
    pd.DataFrame({"competition": ["E0", "E0"], "season": ["2026-27"] * 2, "date": ["2026-11-08"] * 2,
                  "kickoff": ["2026-11-08 16:30 UTC", None], "home": ["Arsenal", "Leeds"], "away": ["Chelsea", "Wolves"],
                  "p_home": [0.5, 0.4], "p_draw": [0.25, 0.3], "p_away": [0.25, 0.3],
                  "odds_home": [0.48, None], "odds_draw": [0.27, None], "odds_away": [0.25, None],
                  "predicted_at": ["2026-11-05 05:30 UTC"] * 2, "home_goals": [None, None], "brier": [None, None],
                  "book_brier": [None, None]}).to_csv(live / "prediction_ledger.csv", index=False)
    monkeypatch.setattr(export_site, "RESULTS", tmp_path)
    section = export_site.live_section()
    json.dumps(section, allow_nan=False)  # raises on any NaN
    assert len(section["upcoming"]) == 2
    assert "odds_home" not in section["upcoming"][1] and "kickoff" not in section["upcoming"][1]


def _cl_match(date, home, away, home_goals, away_goals, season, round_="Round of 16", **extra):
    row = dict(competition="CL", season=season, round=round_, date=pd.Timestamp(date), home=home, away=away,
               home_goals=home_goals, away_goals=away_goals, extra_time=False, home_goals_aet=None,
               away_goals_aet=None, home_pens=None, away_pens=None, neutral=False)
    return {**row, **extra}


def test_tie_scores_always_put_team_a_first_whoever_was_at_home():
    # The second leg is played at team_b's ground, so its score is stored the other way round.
    from knockouts import tie_scores
    matches = pd.DataFrame([
        # away goals: 2-1 then 0-1 at B's ground leaves them level on goals, and B scored the away goal
        _cl_match("2019-02-13", "A", "B", 2, 1, "2018-19"),
        _cl_match("2019-03-06", "B", "A", 1, 0, "2018-19"),
        # extra time then penalties (no away goals any more): A wins the shoot-out 4-3, B was at home
        _cl_match("2023-02-14", "C", "D", 1, 0, "2022-23"),
        _cl_match("2023-03-07", "D", "C", 1, 0, "2022-23", extra_time=True, home_goals_aet=1, away_goals_aet=0,
                  home_pens=3, away_pens=4),
        # a one-off final, decided in extra time
        _cl_match("2023-06-10", "E", "F", 0, 0, "2022-23", round_="Final", neutral=True, extra_time=True,
                  home_goals_aet=0, away_goals_aet=1),
    ])
    scores = tie_scores(matches)
    assert scores[("2018-19", "Round of 16", "A", "B")] == {"legs": [[2, 1], [0, 1]], "away": True}
    assert scores[("2022-23", "Round of 16", "C", "D")] == {"legs": [[1, 0], [0, 1]], "aet": True, "pens": [4, 3]}
    assert scores[("2022-23", "Final", "E", "F")] == {"legs": [[0, 1]], "aet": True}


# ---------- dates ----------

@pytest.mark.parametrize("season, month, year", [
    ("2012-13", 9, 2012), ("2012-13", 3, 2013), ("2012-13", 5, 2013),
    ("2019-20", 9, 2019), ("2019-20", 2, 2020),
    ("2019-20", 8, 2020),  # the season was suspended in March 2020 and finished in August
    ("2020-21", 10, 2020), ("2020-21", 5, 2021),
])
def test_matches_are_dated_in_the_right_year(season, month, year):
    from parse_europe import season_year
    assert season_year(season, month) == year


@needs_raw_data
def test_no_european_match_is_dated_before_its_season_could_start():
    # Qualifying rounds aren't in the files, so nothing can be played before September of the first year.
    # This is how an August 2020 match dated 2019 (the COVID finish) showed up: it was caught only by
    # comparing every match against another source.
    from parse_europe import load_europe
    europe, _ = load_europe()
    first_possible = pd.to_datetime(europe.season.str[:4] + "-09-01")
    early = europe[pd.to_datetime(europe.date) < first_possible]
    assert early.empty, early[["competition", "season", "date", "home", "away"]].head(12).to_string()


@needs_raw_data
def test_the_covid_finish_comes_after_the_first_legs_in_the_same_ties():
    from knockouts import ties_table
    from matches import load_matches
    matches = load_matches()
    finish = matches[(matches.competition == "CL") & (matches.season == "2019-20") & (matches.date >= "2020-08-01")]
    assert len(finish) == 11 and finish.date.min() == pd.Timestamp("2020-08-07") and finish.date.max() == pd.Timestamp("2020-08-23")
    # Real Madrid v Man City: the first leg was at the Bernabeu in February, the second at the Etihad in August.
    (legs,) = [legs for season, rnd, legs in ties_table(matches)
               if season == "2019-20" and rnd == "Round of 16" and set(legs.home) == {"Real Madrid", "Man City"}]
    assert list(legs.home) == ["Real Madrid", "Man City"] and list(legs.date.dt.strftime("%Y-%m-%d")) == ["2020-02-26", "2020-08-07"]
