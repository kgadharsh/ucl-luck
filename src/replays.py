"""Replay every past Champions League season from the round of 16, many times over.

The bracket data already holds each season's knockout tree and the chance that any club
beats any other. Playing the tree out in every possible way (2**15 results) gives, exactly
and without simulation noise, how often each club would win the trophy in a replay, and how
unusual the season that really happened was next to all the others it could have been.

A season's draw is kept as it was: the pairings come from the real tree. "Less surprising"
is the share of replays whose whole run of results was more likely than the one that really
happened, so a season of upsets scores high and one where favourites kept winning scores low.
"""


def _every_season(node_id, nodes, chance, index):
    """Every way the tie at node_id, and everything feeding it, can go: (winner, probability)."""
    node = nodes[node_id]
    if "teams" in node:
        sides = [[(team, 1.0)] for team in node["teams"]]
    else:
        sides = [_every_season(child, nodes, chance, index) for child in node["from"]]
    matrix = chance[node["format"]]
    out = []
    for left, p_left_side in sides[0]:
        for right, p_right_side in sides[1]:
            joint = p_left_side * p_right_side
            p_left = matrix[index[left]][index[right]]
            out.append((left, joint * p_left))
            out.append((right, joint * (1 - p_left)))
    return out


def replay_season(bracket):
    nodes, teams = bracket["nodes"], bracket["teams"]
    index = {team: i for i, team in enumerate(teams)}
    chance = {"two_legs": bracket["two_legs"], "single": bracket["single"]}
    final = next(n["id"] for n in nodes if n["round"] == "Final")
    won = {n["id"]: n["winner"] for n in nodes}

    # The chance of the exact run of results that happened: every tie won by its real winner.
    actual = 1.0
    for node in nodes:
        pair = node["teams"] if "teams" in node else [won[c] for c in node["from"]]
        winner = node["winner"]
        loser = pair[1] if pair[0] == winner else pair[0]
        actual *= chance[node["format"]][index[winner]][index[loser]]

    title = {}
    less_surprising = 0.0
    for champion, probability in _every_season(final, nodes, chance, index):
        title[champion] = title.get(champion, 0.0) + probability
        if probability > actual:
            less_surprising += probability
    return {"champion": won[final], "title": title, "less_surprising": less_surprising}


def season_replays(brackets, top=4):
    """The rows the page shows, most surprising season first."""
    rows = []
    for bracket in brackets:
        r = replay_season(bracket)
        contenders = sorted(r["title"].items(), key=lambda kv: -kv[1])[:top]
        rows.append({
            "season": bracket["season"],
            "champion": r["champion"],
            "champion_chance": round(r["title"].get(r["champion"], 0.0), 4),
            "less_surprising": round(r["less_surprising"], 4),
            "contenders": [{"club": club, "chance": round(p, 4)} for club, p in contenders],
        })
    return sorted(rows, key=lambda row: -row["less_surprising"])
