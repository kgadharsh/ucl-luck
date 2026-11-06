"""A follow-up to week 3: is Real Madrid's knockout record luck, or something the model can't see?

Real Madrid went through 36 of 44 knockout ties when the model expected 24.3. This takes that
apart in four ways, using only what the model knew before each match or tie:

1. Where: La Liga, Champions League group/league-phase matches, Champions League knockouts.
2. When in a tie: won in normal time, lost in normal time, or went to extra time and penalties
   (which the model treats as close to a coin flip).
3. Did it last? Seven seasons against seven seasons, and a boost fitted on the first seven
   used to forecast the next seven. Other clubs get the same test as a control.
4. Is it just Spain? Barcelona and Atletico, the other big Spanish clubs, as a check.

Writes results/real_madrid.json (the dashboard reads it) and results/real_madrid_log.txt.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar
from scipy.special import expit, logit

from dixon_coles import fit, outcome_probs, walk_forward_goals
from knockouts import (LAST_AWAY_GOALS_SEASON, ROUNDS, ties_table, tie_scores, two_leg_outcomes,
                       single_match_outcomes)
from matches import load_matches

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"
CLUB = "Real Madrid"
FIRST_SEASON = "2012-13"
MIN_TIES = 8  # a club needs this many ties before its record means anything
STAGES = ["La Liga", "Champions League groups", "Champions League knockouts"]


# ---------- exact probabilities for "how many ties would they win?" ----------

def poisson_binomial(ps):
    """The chance of each total number of successes, when each event has its own chance."""
    dist = np.array([1.0])
    for p in ps:
        dist = np.append(dist * (1 - p), 0) + np.append(0, dist * p)
    return dist


def at_least(ps, k):
    return float(poisson_binomial(ps)[k:].sum())


def at_most(ps, k):
    return float(poisson_binomial(ps)[: k + 1].sum())


def z_score(won, ps):
    ps = np.asarray(ps, float)
    return float((won - ps.sum()) / np.sqrt((ps * (1 - ps)).sum()))


def selection_corrected(ties, club=CLUB, min_ties=4, sims=400_000, seed=2012):
    """How often would the most over-performing club look at least as unusual as `club` does, if every
    tie were decided by the model's own chances?

    A club's z-score (wins against what the model expected, in standard deviations) is only a fair test if
    the club was picked before looking. Real Madrid stood out first and was tested after, so the fair
    question is about the whole field: replay the ties `sims` times, each time giving every club its z-score,
    and count the replays whose best z-score is at least `club`'s real one.

    Every club with at least `min_ties` ties is in the field, not just the ones with 8 or more: a club needs
    ties to be listed, and winning gets it more ties, so a stricter cut-off would flatter the result. Clubs
    with one tie are left out because one tie gives a z-score that means nothing."""
    ties = ties.reset_index(drop=True)
    count = pd.concat([ties.team_a, ties.team_b]).value_counts()
    teams = sorted(count[count >= min_ties].index)
    index = {team: i for i, team in enumerate(teams)}
    p = ties.p_a.to_numpy(np.float32)
    as_a = np.zeros((len(ties), len(teams)), np.float32)  # as_a[t, c]: club c hosted the first leg of tie t
    as_b = np.zeros_like(as_a)
    for t, (a, b) in enumerate(zip(ties.team_a, ties.team_b)):
        if a in index:
            as_a[t, index[a]] = 1
        if b in index:
            as_b[t, index[b]] = 1
    expected = as_a.T @ p + as_b.T @ (1 - p)
    spread = np.sqrt((as_a + as_b).T @ (p * (1 - p)))
    won = np.array([int((ties.winner == team).sum()) for team in teams])
    z = (won - expected) / spread
    real = float(z[index[club]])
    rng = np.random.default_rng(seed)
    hits, chunk = 0, 20_000
    for _ in range(sims // chunk):
        a_wins = (rng.random((chunk, len(ties))) < p).astype(np.float32)  # team_a goes through
        wins = a_wins @ as_a + (1 - a_wins) @ as_b
        hits += int((((wins - expected) / spread).max(axis=1) >= real - 1e-9).sum())
    chance = hits / ((sims // chunk) * chunk)
    return {"clubs": len(teams), "min_ties": min_ties, "z": real, "chance": chance,
            "one_in": int(float(f"{1 / max(chance, 1e-9):.2g}"))}  # two significant figures: it is a simulation


# ---------- 1. where: match by match ----------

def match_table(matches, settings):
    """Every La Liga and Champions League match since 2012-13 with what the model expected
    beforehand (walk-forward: refitted every week on earlier matches only)."""
    first = matches[(matches.competition == "CL") & (matches.season >= FIRST_SEASON)].date.min()
    lam, nu = walk_forward_goals(matches, first - pd.Timedelta(days=7), matches.date.max() + pd.Timedelta(days=1),
                                 xi=settings.xi, prior_weight=settings.prior_weight, newcomer=settings.newcomer)
    table = matches.assign(lam=lam, nu=nu)
    table = table[table.lam.notna() & table.competition.isin(["CL", "SP1"])].copy()
    table["p_home"], table["p_draw"], table["p_away"] = outcome_probs(table.lam.to_numpy(), table.nu.to_numpy(), settings.rho).T
    table["stage"] = np.where(table.competition == "SP1", "La Liga",
                              np.where(table["round"].isin(ROUNDS), "Champions League knockouts", "Champions League groups"))
    return table


def side_view(table, side):
    """The matches from one side's point of view: points and goals, and what was expected."""
    home = side == "home"
    scored, conceded = (table.home_goals, table.away_goals) if home else (table.away_goals, table.home_goals)
    return pd.DataFrame({
        "team": table.home if home else table.away, "stage": table.stage,
        "pts": np.where(scored > conceded, 3, np.where(scored == conceded, 1, 0)),
        "xpts": 3 * (table.p_home if home else table.p_away) + table.p_draw,
        "gf": scored, "ga": conceded,
        "xgf": table.lam if home else table.nu, "xga": table.nu if home else table.lam,
    })


def stage_rows(view, labels):
    rows = []
    for label in labels:
        part = view[view.stage == label]
        gap = part.pts - part.xpts
        rows.append({"label": label, "matches": int(len(part)), "points": float(part.pts.mean()),
                     "expected": float(part.xpts.mean()), "gap": float(gap.mean()),
                     "error": float(1.96 * gap.std(ddof=1) / np.sqrt(len(part))),
                     "scored": float(part.gf.mean()), "expected_scored": float(part.xgf.mean()),
                     "conceded": float(part.ga.mean()), "expected_conceded": float(part.xga.mean())})
    return rows


# ---------- 2. when in a tie: normal time or extra time ----------

def tie_pieces(matches, settings):
    """For every knockout tie, the model's chance that team_a wins in normal time, that team_b
    does, that it goes to extra time, and that team_a wins if it does. Fitted before the first leg."""
    fits, rows = {}, []
    for season, rnd, legs in ties_table(matches):
        first = legs.iloc[0]
        if len(legs) == 1 and not first.neutral:
            continue  # a two-legged tie whose second leg hasn't been played yet
        when = first.date
        if when not in fits:
            fits[when] = fit(matches[matches.date < when], when, xi=settings.xi, prior_weight=settings.prior_weight,
                             newcomer=settings.newcomer)
        model = fits[when]
        a, b = first.home, first.away
        if len(legs) == 1:
            lam, nu = model.expected_goals(a, b, bool(first.neutral), settings.newcomer)
            pieces = single_match_outcomes(lam, nu, settings.rho)
        else:
            lam1, nu1 = model.expected_goals(a, b, False, settings.newcomer)
            lam2, nu2 = model.expected_goals(b, a, False, settings.newcomer)
            pieces = two_leg_outcomes(lam1, nu1, lam2, nu2, settings.rho, season <= LAST_AWAY_GOALS_SEASON)
        rows.append({"season": season, "round": rnd, "team_a": a, "team_b": b,
                     "p_a_normal": pieces[0], "p_b_normal": pieces[1], "p_extra": pieces[2], "p_a_if_extra": pieces[3]})
    return pd.DataFrame(rows)


def club_ties(club, ties, pieces, scores):
    """One row per tie the club played: its chance of going through, how it was decided."""
    x = pieces.merge(ties[["season", "round", "team_a", "team_b", "p_a", "winner"]], on=["season", "round", "team_a", "team_b"])
    assert len(x) == len(ties) == len(pieces)
    assert np.allclose(x.p_a_normal + x.p_extra * x.p_a_if_extra, x.p_a, atol=2e-4), "pieces must add up to the tie chance"
    x["extra_time"] = [bool(scores[(r.season, r.round, r.team_a, r.team_b)].get("aet")) for r in x.itertuples()]
    mine = x[(x.team_a == club) | (x.team_b == club)].copy()
    a = (mine.team_a == club).to_numpy()
    mine["p"] = np.where(a, mine.p_a, 1 - mine.p_a)
    mine["p_win_normal"] = np.where(a, mine.p_a_normal, mine.p_b_normal)
    mine["p_lose_normal"] = np.where(a, mine.p_b_normal, mine.p_a_normal)
    mine["p_win_if_extra"] = np.where(a, mine.p_a_if_extra, 1 - mine.p_a_if_extra)
    mine["won"] = mine.winner == club
    return mine


def normal_time_split(mine):
    won, extra = mine.won.to_numpy(), mine.extra_time.to_numpy()
    won_normal, lost_normal = int((won & ~extra).sum()), int((~won & ~extra).sum())
    return {
        "ties": int(len(mine)),
        "won_normal": {"actual": won_normal, "expected": float(mine.p_win_normal.sum()),
                       "p_at_least": at_least(mine.p_win_normal, won_normal)},
        "lost_normal": {"actual": lost_normal, "expected": float(mine.p_lose_normal.sum()),
                        "p_at_most": at_most(mine.p_lose_normal, lost_normal)},
        "extra_time": {"actual": int(extra.sum()), "expected": float(mine.p_extra.sum())},
        "won_extra": {"actual": int((won & extra).sum()), "expected": float((mine.p_extra * mine.p_win_if_extra).sum()),
                      "p_at_least": at_least((mine.p_win_if_extra[extra]).to_numpy(), int((won & extra).sum()))},
    }


# ---------- 3. did it last? ----------

def half_summary(mine, seasons):
    part = mine[mine.season.isin(seasons)]
    return {"seasons": f"{seasons[0]} to {seasons[-1]}", "ties": int(len(part)), "won": int(part.won.sum()),
            "expected": float(part.p.sum()), "z": z_score(part.won.sum(), part.p),
            "p_at_least": at_least(part.p, int(part.won.sum()))}


def log_loss(df, boost):
    q = expit(logit(df.p.clip(1e-6, 1 - 1e-6)) + boost)
    return float(-(df.won * np.log(q) + (1 - df.won) * np.log(1 - q)).sum())


def fit_boost(df):
    return float(minimize_scalar(lambda b: log_loss(df, b), bounds=(-3, 3), method="bounded").x)


def forecast_test(mine, first, second):
    """A boost (a shift on the log-odds of going through) fitted on the first seven seasons only,
    then used on the next seven. Lower log loss is better."""
    train, test = mine[mine.season.isin(first)], mine[mine.season.isin(second)]
    boost = fit_boost(train)
    best = fit_boost(mine)
    inside = [b for b in np.linspace(-1, 3, 801) if 2 * (log_loss(mine, b) - log_loss(mine, best)) < 3.84]
    return {"boost": boost, "ties": int(len(test)), "without": log_loss(test, 0) / len(test), "with": log_loss(test, boost) / len(test),
            "all_seasons_boost": best, "all_seasons_range": [float(min(inside)), float(max(inside))]}


def all_club_ties(ties):
    rows = []
    for t in ties.itertuples():
        for club, p in ((t.team_a, t.p_a), (t.team_b, 1 - t.p_a)):
            rows.append({"club": club, "season": t.season, "p": p, "won": int(t.winner == club)})
    return pd.DataFrame(rows)


def club_halves(everyone, first, second, minimum=4):
    """For every club with enough ties in both halves: how far above or below the model it was
    in each half, in units of normal luck (z-scores)."""
    out = []
    for club, g in everyone.groupby("club"):
        a, b = g[g.season.isin(first)], g[g.season.isin(second)]
        if len(a) >= minimum and len(b) >= minimum:
            out.append({"club": club, "ties_first": int(len(a)), "ties_second": int(len(b)),
                        "first": z_score(a.won.sum(), a.p), "second": z_score(b.won.sum(), b.p)})
    return out


# ---------- everything together ----------

def analyse():
    settings = pd.read_csv(RESULTS / "dixon_coles_settings.csv").iloc[0]
    ties = pd.read_csv(RESULTS / "knockout_ties.csv")
    # Only the seasons the ties cover. Without this, the first matches of a new league season
    # would creep into the La Liga numbers, and the results would change every day.
    matches = load_matches()
    matches = matches[matches.season <= ties.season.max()]
    scores = tie_scores(matches)

    table = match_table(matches, settings)
    views = pd.concat([side_view(table, "home"), side_view(table, "away")], ignore_index=True)
    mine_matches, others_matches = views[views.team == CLUB], views[(views.team != CLUB) & (views.stage != "La Liga")]
    mine = club_ties(CLUB, ties, tie_pieces(matches, settings), scores)
    seasons = sorted(ties.season.unique())
    first, second = seasons[:7], seasons[7:]
    everyone = all_club_ties(ties)
    halves = club_halves(everyone, first, second)
    others = [z_score(g.won.sum(), g.p) for club, g in everyone.groupby("club") if club != CLUB and len(g) >= MIN_TIES]
    per_season = (mine.won.astype(float) - mine.p).groupby(mine.season).sum()  # wins above expectation, season by season
    spanish = {}
    for club in ["Barcelona", "Ath Madrid"]:
        g = everyone[everyone.club == club]
        spanish[club] = {"ties": int(len(g)), "won": int(g.won.sum()), "expected": float(g.p.sum()), "z": z_score(g.won.sum(), g.p)}
    return {
        "club": CLUB,
        "through_season": str(ties.season.max()),
        "ties": int(len(mine)), "won": int(mine.won.sum()), "expected": float(mine.p.sum()),
        "p_at_least": at_least(mine.p, int(mine.won.sum())),
        "stages": stage_rows(mine_matches, STAGES),
        "other_clubs_stages": stage_rows(others_matches, STAGES[1:]),
        "normal_time": normal_time_split(mine),
        "halves": [half_summary(mine, first), half_summary(mine, second)],
        "seasons_above": int((per_season > 0).sum()), "seasons": int(len(per_season)),
        "forecast": forecast_test(mine, first, second),
        "clubs": halves,
        "others": {"clubs": len(others), "largest_z": float(max(abs(z) for z in others))},
        "spanish": spanish,
    }


def report(r):
    lines = [f"{r['club']}: won {r['won']} of {r['ties']} ties, expected {r['expected']:.1f} "
             f"(about 1 in {1 / r['p_at_least']:,.0f} by luck alone)", ""]
    lines.append("1. Where (points a match, 90 minutes, model expectation made before each match)")
    for s in r["stages"]:
        lines.append(f"   {s['label']:<30} {s['matches']:>4} matches  {s['points']:.2f} v {s['expected']:.2f} expected  "
                     f"gap {s['gap']:+.2f} (95%: +/-{s['error']:.2f})   goals {s['scored']:.2f} v {s['expected_scored']:.2f}, "
                     f"conceded {s['conceded']:.2f} v {s['expected_conceded']:.2f}")
    n = r["normal_time"]
    lines += ["", "2. When in a tie (the model treats extra time and penalties as close to a coin flip)",
              f"   won in normal time     {n['won_normal']['actual']:>3} v {n['won_normal']['expected']:.1f} expected  (1 in {1 / n['won_normal']['p_at_least']:,.0f})",
              f"   lost in normal time    {n['lost_normal']['actual']:>3} v {n['lost_normal']['expected']:.1f} expected  (1 in {1 / n['lost_normal']['p_at_most']:,.0f})",
              f"   went to extra time     {n['extra_time']['actual']:>3} v {n['extra_time']['expected']:.1f} expected",
              f"   won after extra time   {n['won_extra']['actual']:>3} v {n['won_extra']['expected']:.1f} expected  (1 in {1 / n['won_extra']['p_at_least']:,.0f})"]
    lines += ["", "3. Did it last?"]
    for h in r["halves"]:
        lines.append(f"   {h['seasons']}: won {h['won']} of {h['ties']}, expected {h['expected']:.1f}, z = {h['z']:.2f} (1 in {1 / h['p_at_least']:,.0f})")
    f = r["forecast"]
    lines += [f"   above the model in {r['seasons_above']} of {r['seasons']} seasons",
              f"   a boost fitted on the first seven seasons (odds x{np.exp(f['boost']):.1f}) cuts the forecast error on the next "
              f"{f['ties']} ties from {f['without']:.3f} to {f['with']:.3f} (log loss per tie)",
              f"   fitted on all seasons: odds x{np.exp(f['all_seasons_boost']):.1f}, 95% range x{np.exp(f['all_seasons_range'][0]):.1f} to x{np.exp(f['all_seasons_range'][1]):.1f}"]
    for s in r["other_clubs_stages"]:
        lines.append(f"   every other club, {s['label']}: {s['matches']} matches, gap {s['gap']:+.2f}")
    others = [c for c in r["clubs"] if c["club"] != r["club"]]
    corr = np.corrcoef([c["first"] for c in others], [c["second"] for c in others])[0, 1]
    lines += [f"   control: the other {len(others)} clubs with 4+ ties in both halves: first-half and second-half z-scores correlate {corr:+.2f}",
              f"   control: no other club with {MIN_TIES}+ ties is further than z = {r['others']['largest_z']:.1f} from the model ({r['others']['clubs']} clubs)"]
    lines += ["", "4. Just Spain?"]
    for club, s in r["spanish"].items():
        lines.append(f"   {club}: won {s['won']} of {s['ties']}, expected {s['expected']:.1f} (z = {s['z']:+.2f})")
    return "\n".join(lines)


def main():
    result = analyse()
    text = report(result)
    print(text)
    (RESULTS / "real_madrid_log.txt").write_text(text + "\n", encoding="utf-8")
    (RESULTS / "real_madrid.json").write_text(json.dumps(result, ensure_ascii=False, indent=1, allow_nan=False) + "\n", encoding="utf-8")
    print(f"\nSaved real_madrid.json and real_madrid_log.txt in {RESULTS}")


if __name__ == "__main__":
    main()
