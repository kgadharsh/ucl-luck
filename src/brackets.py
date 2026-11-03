"""Bracket data for the dashboard's "butterfly effect": every season's knockout tree from
the round of 16, plus the chance that any one of the 16 clubs beats any other.

Strengths are frozen just before the round of 16 (a Dixon–Coles fit on earlier matches),
so changing one result shows how much the rest of the bracket depended on it.

Since 2024-25 the bracket is fixed in advance. Before that, the quarter- and semi-final
draws were made round by round; for those seasons the tree is the draw as it happened.
"""

import numpy as np
import pandas as pd

from dixon_coles import fit
from knockouts import FIRST_SEASON, LAST_AWAY_GOALS_SEASON, actual_winner, single_match, two_legs

ORDER = ["Round of 16", "Quarterfinals", "Semifinals", "Final"]


def season_ties(matches, season):
    cl = matches[(matches.competition == "CL") & (matches.season == season) & matches["round"].isin(ORDER)].copy()
    cl["pair"] = [frozenset((h, a)) for h, a in zip(cl.home, cl.away)]
    ties = {}
    for (rnd, pair), legs in cl.groupby(["round", "pair"], sort=False):
        legs = legs.sort_values("date")
        ties.setdefault(rnd, []).append({"teams": sorted(pair), "legs": legs,
                                         "winner": actual_winner(legs, season <= LAST_AWAY_GOALS_SEASON)})
    return ties


def build_tree(ties):
    """Nodes in round order. Each later node names the two earlier nodes that feed it."""
    nodes = []
    by_round = {}
    for rnd in ORDER:
        ids = []
        for tie in ties[rnd]:
            node = {"id": len(nodes), "round": rnd, "winner": tie["winner"]}
            if rnd == "Round of 16":
                node["teams"] = tie["teams"]
            else:
                earlier = by_round[ORDER[ORDER.index(rnd) - 1]]
                node["from"] = sorted(n["id"] for n in earlier if n["winner"] in tie["teams"])
                if len(node["from"]) != 2:
                    raise ValueError(f"Could not place {rnd} tie {tie['teams']}")
            nodes.append(node)
            ids.append(node)
        by_round[rnd] = ids
    # Put round-of-16 ties in bracket order so the halves read top to bottom.
    order = []

    def leaves(node):
        if "from" not in node:
            order.append(node["id"])
            return
        for child in node["from"]:
            leaves(nodes[child])

    leaves(by_round["Final"][0])
    position = {node_id: i for i, node_id in enumerate(order)}
    for node in nodes:
        node["slot"] = position.get(node["id"], None)
    return nodes


def pairwise(model, teams, season, rho, newcomer, actual_r16):
    """chance[i][j]: team i beats team j over two legs (averaging who hosts the second leg,
    except for the real round-of-16 ties, which use the real order); single[i][j]: one
    match at a neutral ground, then extra time and penalties."""
    away_rule = season <= LAST_AWAY_GOALS_SEASON
    n = len(teams)
    legs2 = np.full((n, n), 0.5)
    single = np.full((n, n), 0.5)
    for i in range(n):
        for j in range(i + 1, n):
            a, b = teams[i], teams[j]
            lam1, nu1 = model.expected_goals(a, b, False, newcomer)
            lam2, nu2 = model.expected_goals(b, a, False, newcomer)
            a_first = two_legs(lam1, nu1, lam2, nu2, rho, away_rule)          # a at home first
            b_first = 1 - two_legs(lam2, nu2, lam1, nu1, rho, away_rule)      # b at home first
            if (a, b) in actual_r16:
                p = a_first
            elif (b, a) in actual_r16:
                p = b_first
            else:
                p = (a_first + b_first) / 2
            legs2[i, j], legs2[j, i] = p, 1 - p
            lam, nu = model.expected_goals(a, b, True, newcomer)
            s = single_match(lam, nu, rho)
            single[i, j], single[j, i] = s, 1 - s
    return legs2, single


def build_brackets(matches, settings):
    fit_settings = dict(xi=settings.xi, prior_weight=settings.prior_weight, newcomer=settings.newcomer)
    seasons = sorted(s for s in matches.season.unique() if s >= FIRST_SEASON)
    out = []
    for season in seasons:
        ties = season_ties(matches, season)
        if any(rnd not in ties for rnd in ORDER):
            continue
        nodes = build_tree(ties)
        teams = sorted({t for node in nodes if node["round"] == "Round of 16" for t in node["teams"]})
        first_r16 = min(tie["legs"].date.min() for tie in ties["Round of 16"])
        model = fit(matches[matches.date < first_r16], first_r16, **fit_settings)
        actual_r16 = {(tie["legs"].iloc[0].home, tie["legs"].iloc[0].away) for tie in ties["Round of 16"]}
        legs2, single = pairwise(model, teams, season, settings.rho, settings.newcomer, actual_r16)
        lisbon = season == "2019-20"  # quarter- and semi-finals were one-off matches
        for node in nodes:
            node["format"] = "single" if node["round"] == "Final" or (lisbon and node["round"] != "Round of 16") else "two_legs"
        out.append({
            "season": season,
            "fixed_bracket": season >= "2024-25",
            "teams": teams,
            "two_legs": np.round(legs2, 4).tolist(),
            "single": np.round(single, 4).tolist(),
            "nodes": nodes,
        })
    return out


if __name__ == "__main__":
    from matches import load_matches
    from pathlib import Path

    settings = pd.read_csv(Path(__file__).resolve().parent.parent / "results" / "dixon_coles_settings.csv").iloc[0]
    brackets = build_brackets(load_matches(), settings)
    for b in brackets:
        champion = next(n for n in b["nodes"] if n["round"] == "Final")["winner"]
        print(b["season"], len(b["teams"]), "teams, champion", champion, "| fixed bracket" if b["fixed_bracket"] else "")
