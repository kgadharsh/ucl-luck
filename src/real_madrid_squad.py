"""Does who played explain Real Madrid's Champions League record?

real_madrid.py found that Real Madrid beat the model in Europe in a way that lasted, and that the
model, which sees only results, can't say why. This uses Transfermarkt's open dataset (starting
elevens and player market values) to test the explanations that line-ups can speak to:

1. Rotation: do Real field weaker elevens in La Liga than in Europe, more than other big clubs?
2. Strength: does the eleven fielded (against the club's usual one), or the gap in squad quality,
   predict who beats the model, and how much of Real's surplus does that account for?
3. The manager: does the surplus follow Ancelotti or Zidane, or the club?

Needs the Transfermarkt files: python scripts/download_data.py --transfermarkt (about 135 MB).
Writes results/real_madrid_squad.json (the dashboard reads it) and results/real_madrid_squad_log.txt.
"""

import json
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from matches import load_matches
from real_madrid import CLUB, STAGES, match_table

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"
TRANSFERMARKT = ROOT / "data" / "raw" / "transfermarkt"
REAL_ID = 418  # Real Madrid's club id on Transfermarkt
FIRST_SEASON = 2013  # 2013-14: there are no starting elevens for 2012-13
STALE_DAYS = 400  # a market value older than this isn't trusted
FLOOR = 250_000  # a value for players with none on record, and the least Transfermarkt records
MIN_LINEUPS = 20  # elevens a club needs in a season before "its best eleven" means anything
LEAGUES = {"GB1", "ES1", "L1", "IT1", "FR1", "NL1", "PO1", "TR1", "BE1", "RU1", "GR1", "SC1", "UKR1", "DK1", "A1", "C1"}
KNOCKOUT_WORDS = ("last 16", "quarter", "semi", "final", "intermediate")  # Transfermarkt's round names


# ---------- the data ----------

def xi_values(lineups, valuations):
    """The market value of every complete starting eleven: each starter's latest valuation on or
    before the match (ignoring one older than STALE_DAYS, and never below FLOOR), added up."""
    starters = lineups[lineups["type"] == "starting_lineup"].copy()
    starters["date"] = pd.to_datetime(starters["date"])
    values = valuations.assign(vdate=pd.to_datetime(valuations["date"]))[["player_id", "vdate", "market_value_in_eur"]]
    merged = pd.merge_asof(starters.sort_values("date"), values.sort_values("vdate"), left_on="date", right_on="vdate",
                           by="player_id", direction="backward")
    merged.loc[(merged.date - merged.vdate).dt.days > STALE_DAYS, "market_value_in_eur"] = np.nan
    merged["value"] = merged.market_value_in_eur.fillna(FLOOR).clip(lower=FLOOR)
    xi = merged.groupby(["game_id", "club_id"]).agg(xi_value=("value", "sum"), starters=("player_id", "size")).reset_index()
    return xi[xi.starters == 11].drop(columns="starters")


def load_transfermarkt():
    games = pd.read_csv(TRANSFERMARKT / "games.csv.gz", usecols=[
        "game_id", "competition_id", "season", "date", "round", "home_club_id", "away_club_id", "home_club_name", "away_club_name",
        "home_club_goals", "away_club_goals", "home_club_manager_name", "away_club_manager_name"])
    games["date"] = pd.to_datetime(games["date"])
    lineups = pd.read_csv(TRANSFERMARKT / "game_lineups.csv.gz", usecols=["game_id", "date", "player_id", "club_id", "type"])
    valuations = pd.read_csv(TRANSFERMARKT / "player_valuations.csv.gz", usecols=["player_id", "date", "market_value_in_eur"])
    xi = xi_values(lineups, valuations).merge(games[["game_id", "competition_id", "season", "date", "round"]], on="game_id")
    return games, xi


def link_matches(ours, theirs):
    """Match our records to Transfermarkt's game ids by date and score. Where several games share
    both, the club names learned from the unambiguous ones settle it. Returns {our index: game_id}."""
    key = lambda date, home_goals, away_goals: (date.strftime("%Y-%m-%d"), int(home_goals), int(away_goals))
    candidates = defaultdict(list)
    by_day = defaultdict(list)
    for t in theirs.itertuples():
        candidates[key(t.date, t.home_club_goals, t.away_club_goals)].append(t)
        by_day[t.date.strftime("%Y-%m-%d")].append(t)
    votes = defaultdict(Counter)
    for o in ours.itertuples():
        found = candidates.get(key(o.date, o.home_goals, o.away_goals), [])
        if len(found) == 1:
            votes[o.home][found[0].home_club_id] += 1
            votes[o.away][found[0].away_club_id] += 1
    club_id = {name: counts.most_common(1)[0][0] for name, counts in votes.items()}
    linked, used = {}, set()
    for o in ours.itertuples():
        home, away = club_id.get(o.home), club_id.get(o.away)
        found = [t for t in by_day.get(o.date.strftime("%Y-%m-%d"), []) if (home is not None and t.home_club_id == home and (away is None or t.away_club_id == away))]
        if len(found) == 1 and found[0].game_id not in used:
            linked[o.Index] = found[0].game_id
            used.add(found[0].game_id)
    return linked


# ---------- 1. rotation ----------

def is_knockout(round_name):
    name = str(round_name).lower()
    return any(word in name for word in KNOCKOUT_WORDS) and not name.startswith("group")


def rotation(xi):
    """How strong an eleven each club fields, as a share of its own best (the 90th percentile of
    every eleven it fielded that season), in the league and in Champions League knockouts."""
    x = xi[xi.season >= FIRST_SEASON].copy()
    x["stage"] = [("knockouts" if is_knockout(r) else "groups") if c == "CL" else ("league" if c in LEAGUES else "other")
                  for c, r in zip(x.competition_id, x["round"])]
    x["best"] = x.groupby(["club_id", "season"]).xi_value.transform(lambda s: s.quantile(0.9))
    x = x[x.groupby(["club_id", "season"]).xi_value.transform("size") >= MIN_LINEUPS]
    x["share"] = x.xi_value / x.best
    seasons = x.groupby(["club_id", "season", "stage"]).share.mean().unstack("stage").dropna(subset=["league", "knockouts"])
    seasons["gap"] = seasons.knockouts - seasons.league
    clubs = seasons.groupby("club_id").agg(seasons=("gap", "size"), league=("league", "mean"), knockouts=("knockouts", "mean"),
                                           gap=("gap", "mean"), sd=("gap", "std"))
    clubs["se"] = clubs.sd / np.sqrt(clubs.seasons)
    return clubs[clubs.seasons >= 5].sort_values("gap", ascending=False)


# ---------- 2. strength ----------

def ols_robust(columns, y):
    """Least squares with an intercept, and standard errors that don't assume equal spread."""
    X = np.column_stack([np.ones(len(y)), *columns])
    beta = np.linalg.solve(X.T @ X, X.T @ y)
    resid = y - X @ beta
    bread = np.linalg.inv(X.T @ X)
    meat = (X * resid[:, None]).T @ (X * resid[:, None])
    cov = bread @ meat @ bread * len(y) / (len(y) - X.shape[1])
    return beta, np.sqrt(np.diag(cov))


def strength_table(cl, xi):
    """Every Champions League match with both elevens' values, from 2013-14. `dev`: the home eleven
    stronger than its usual, relative to the same for the away side. `level`: the gap in usual strength."""
    typical = xi.groupby(["club_id", "season"]).xi_value.median()
    value = xi.set_index(["game_id", "club_id"]).xi_value
    t = cl.copy()
    t["season_year"] = t.season.str[:4].astype(int)
    for side in ("home", "away"):
        t[f"xi_{side}"] = [value.get((g, c), np.nan) for g, c in zip(t.game_id, t[f"tm_{side}_id"])]
        t[f"typical_{side}"] = [typical.get((c, s), np.nan) for c, s in zip(t[f"tm_{side}_id"], t.season_year)]
    t = t.dropna(subset=["xi_home", "xi_away", "typical_home", "typical_away"])
    t = t[t.season_year >= FIRST_SEASON].copy()
    t["resid"] = (t.home_goals - t.away_goals) - (t.lam - t.nu)  # goals better than the model expected, home side
    t["dev"] = np.log(t.xi_home / t.typical_home) - np.log(t.xi_away / t.typical_away)
    t["level"] = np.log(t.typical_home) - np.log(t.typical_away)
    return t


def explain(t):
    beta, se = ols_robust([t.dev.to_numpy(), t.level.to_numpy()], t.resid.to_numpy())
    real = t[(t.tm_home_id == REAL_ID) | (t.tm_away_id == REAL_ID)]
    sign = np.where(real.tm_home_id == REAL_ID, 1, -1)  # Real's point of view
    out = {"matches": int(len(t)), "fielded_vs_usual": {"coefficient": float(beta[1]), "se": float(se[1])},
           "quality_gap": {"coefficient": float(beta[2]), "se": float(se[2])}, "real": {}}
    for label, part in (("groups", real.stage != STAGES[2]), ("knockouts", real.stage == STAGES[2])):
        mine = real[part.to_numpy()]
        s = sign[part.to_numpy()]
        actual, dev, level = mine.resid.to_numpy() * s, mine.dev.to_numpy() * s, mine.level.to_numpy() * s
        out["real"][label] = {"matches": int(len(mine)), "actual": float(actual.mean()), "se": float(actual.std(ddof=1) / np.sqrt(len(mine))),
                              "explained_by_fielded": float(beta[1] * dev.mean()), "explained_by_quality": float(beta[2] * level.mean())}
    return out


# ---------- 3. the manager ----------

def manager_rows(t, games):
    managers = games.set_index("game_id")
    frames = []
    for side, flip in (("home", 1), ("away", -1)):
        won = t.home_goals > t.away_goals if side == "home" else t.away_goals > t.home_goals
        points = np.where(won, 3, np.where(t.home_goals == t.away_goals, 1, 0))
        expected = 3 * t[f"p_{side}"] + t.p_draw
        frames.append(pd.DataFrame({"manager": t.game_id.map(managers[f"{side}_club_manager_name"]), "club_id": t[f"tm_{side}_id"],
                                    "knockout": t.stage == STAGES[2], "points": points - expected}))
    return pd.concat(frames, ignore_index=True)


def manager_summary(rows):
    n = len(rows)
    return {"matches": int(n), "knockout_matches": int(rows.knockout.sum()), "points": float(rows.points.mean()),
            "se": float(rows.points.std(ddof=1) / np.sqrt(n))}


def managers(t, games):
    rows = manager_rows(t, games)
    real = rows[rows.club_id == REAL_ID]
    named = lambda pattern: real.manager.fillna("").str.contains(pattern)
    ancelotti_elsewhere = rows[rows.manager.fillna("").str.contains("Ancelotti") & (rows.club_id != REAL_ID)]
    return {"ancelotti_at_real": manager_summary(real[named("Ancelotti")]), "zidane_at_real": manager_summary(real[named("Zidane")]),
            "others_at_real": manager_summary(real[~named("Ancelotti|Zidane")]),
            "ancelotti_elsewhere": manager_summary(ancelotti_elsewhere)}


# ---------- everything together ----------

def analyse():
    settings = pd.read_csv(RESULTS / "dixon_coles_settings.csv").iloc[0]
    ties = pd.read_csv(RESULTS / "knockout_ties.csv")
    matches = load_matches()
    matches = matches[matches.season <= ties.season.max()]
    table = match_table(matches, settings)
    table = table[table.competition == "CL"]
    games, xi = load_transfermarkt()
    names = pd.concat([games[["home_club_id", "home_club_name"]].set_axis(["id", "name"], axis=1),
                       games[["away_club_id", "away_club_name"]].set_axis(["id", "name"], axis=1)]).drop_duplicates("id").set_index("id").name
    assert names[REAL_ID] == CLUB, "Transfermarkt's club id for Real Madrid has changed"

    cl = games[games.competition_id == "CL"]
    linked = link_matches(table, cl)
    cl_matches = table.assign(game_id=pd.Series(linked))
    cl_matches = cl_matches[cl_matches.game_id.notna()].copy()
    by_id = cl.set_index("game_id")
    cl_matches["tm_home_id"] = cl_matches.game_id.map(by_id.home_club_id)
    cl_matches["tm_away_id"] = cl_matches.game_id.map(by_id.away_club_id)
    wrong_score = (cl_matches.home_goals != cl_matches.game_id.map(by_id.home_club_goals)) & (cl_matches.extra_time != True)  # noqa: E712
    assert not wrong_score.any(), "a linked match has a different 90-minute score"

    shares = rotation(xi)
    real_share = shares.loc[REAL_ID]
    others = shares.drop(REAL_ID)
    t = strength_table(cl_matches, xi)
    return {
        "club": CLUB,
        "through_season": str(ties.season.max()),
        "matches_linked": int(len(cl_matches)), "matches_in_data": int(len(table)),
        "first_season": f"{FIRST_SEASON}-{(FIRST_SEASON + 1) % 100:02d}",
        "rotation": {
            "real": {"seasons": int(real_share.seasons), "league": float(real_share.league), "knockouts": float(real_share.knockouts),
                     "gap": float(real_share.gap), "se": float(real_share.se)},
            "others": {"clubs": int(len(others)), "gap": float(others.gap.mean()), "sd": float(others.gap.std())},
            "real_rank": int((shares.gap > real_share.gap).sum()) + 1, "clubs": int(len(shares)),
            "table": [{"club": names[cid], "seasons": int(r.seasons), "league": float(r.league), "knockouts": float(r.knockouts),
                       "gap": float(r.gap), "se": float(r.se)} for cid, r in shares.iterrows()],
        },
        "strength": explain(t),
        "managers": managers(t, games),
    }


def report(r):
    rot, s, m = r["rotation"], r["strength"], r["managers"]
    lines = [f"{r['club']}: do the elevens explain it? ({r['matches_linked']} of {r['matches_in_data']} Champions League matches linked, from {r['first_season']})", "",
             "1. Rotation: share of the club's own best eleven (by market value) fielded; knockouts minus league",
             f"   Real Madrid  league {rot['real']['league']:.3f}  knockouts {rot['real']['knockouts']:.3f}  gap {rot['real']['gap']:+.3f} (se {rot['real']['se']:.3f}, {rot['real']['seasons']} seasons)",
             f"   the other {rot['others']['clubs']} clubs: mean gap {rot['others']['gap']:+.3f}, spread between clubs {rot['others']['sd']:.3f}; Real ranks {rot['real_rank']} of {rot['clubs']}", "",
             f"2. Strength: goals a match better than the model expected, on the eleven fielded ({s['matches']} matches)",
             f"   eleven stronger than usual: {s['fielded_vs_usual']['coefficient']:+.3f} (se {s['fielded_vs_usual']['se']:.3f})   gap in squad quality: {s['quality_gap']['coefficient']:+.3f} (se {s['quality_gap']['se']:.3f})"]
    for label, v in s["real"].items():
        lines.append(f"   Real, {label:<9} {v['matches']:>3} matches: {v['actual']:+.3f} goals a match (se {v['se']:.3f}); explained by the eleven fielded {v['explained_by_fielded']:+.3f}, by squad quality {v['explained_by_quality']:+.3f}")
    lines += ["", "3. The manager: points a match better than the model expected"]
    for label, v in m.items():
        lines.append(f"   {label.replace('_', ' '):<20} {v['matches']:>3} matches ({v['knockout_matches']} knockout): {v['points']:+.3f} (se {v['se']:.3f})")
    return "\n".join(lines)


def main():
    result = analyse()
    text = report(result)
    print(text)
    (RESULTS / "real_madrid_squad_log.txt").write_text(text + "\n", encoding="utf-8")
    (RESULTS / "real_madrid_squad.json").write_text(json.dumps(result, ensure_ascii=False, indent=1, allow_nan=False) + "\n", encoding="utf-8")
    print(f"\nSaved real_madrid_squad.json and real_madrid_squad_log.txt in {RESULTS}")


if __name__ == "__main__":
    main()
