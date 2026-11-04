# How much of a Champions League knockout is luck?

Every year someone goes out of the Champions League and everyone argues about whether they were unlucky or just not good enough. I wanted an actual number for that. So I built a model, tested it against the bookmakers, and used it to work out how likely every knockout tie since 2012-13 really was before a ball was kicked.

**The dashboard is live at [kgadharsh.github.io/ucl-luck](https://kgadharsh.github.io/ucl-luck/).**

The short version: a knockout tie is roughly a 70/30 bet, and even most champions needed a fair bit of luck to get through four or five of them in a row. Real Madrid are the exception, and I don't think it's luck (more on that at the bottom).

## How I went about it

I treated this as a study first and an app second. A luck number is only as good as the probabilities behind it, so the first job was proving the model was honest. I split it into weeks so I'd have something useful even if I stopped early:

| Week | Work | Done when |
|---|---|---|
| 1 | Elo ratings on the big five leagues plus Champions League and Europa League results | A Brier score on a season the model never saw |
| 2 | Dixon–Coles goals model, tested walk-forward (train on the past, predict the next season) | A calibration chart against bookmakers' closing odds, with error bars |
| 3 | Each knockout tie's exact chances before the first leg | One chart showing how likely each champion's run was |
| 4 | A small interactive page, only if the analysis held up | Something you can play with in 10 seconds |

Things I left out on purpose: StatsBomb event data (a goals model doesn't need it), the "did the new 2024-25 format help the big clubs?" question (two seasons isn't enough), and anything like accounts or leaderboards.

A few things I knew going in. There are only about 15 knockout ties a season, so I pooled every season and tested calibration on league matches too, where there's far more data. I expected to lose to the bookmakers, and I did, so the interesting part is how close I got. And the two data sources spell team names differently ("Man City" vs "Manchester City FC (ENG)"), so there's a name mapping in `data/team_names.csv`.

## Data

| Source | What | Licence |
|---|---|---|
| [football-data.co.uk](https://www.football-data.co.uk/) | League results with bookmaker odds, including closing odds (e.g. `PSCH`, Pinnacle's closing home odds) | Free to use; check their terms before building anything public on it |
| [openfootball/champions-league](https://github.com/openfootball/champions-league) | Champions League results from 2011-12, and Europa League results from 2020-21 to 2024-25 (the only Europa League seasons it has), including extra time and penalties | CC0 (public domain) |

`scripts/download_data.py` downloads everything into `data/raw/`, which isn't committed.

## Running it

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python scripts/download_data.py
```

To build and view the dashboard locally:

```bash
.venv/bin/python src/export_site.py              # writes site/data.json from results/
python3 -m http.server 8123 --directory site     # then open http://localhost:8123
```

## The dashboard

`site/` is plain HTML, CSS and JavaScript. The charts are hand-drawn SVG and canvas, with no libraries and no build step (`app.js` draws the charts, `motion.js` does the animation). The dashboard's UI design was done with help from Claude, an AI assistant.

What's on it:

- **The luck machine.** Every tie drops through a Galton board and lands on the winner's chance before the first leg, so the pile you end up with is the shape of the luck. Hover a ball to see its tie, or click it to jump to it in the explorer.
- An upsets ticker (ties won by a side given under 35%) and the headline numbers.
- Each champion's run, with a funnel showing its chances shrinking tie by tie.
- **What if?** Pick the winner of any tie in any season since 2012-13 and every club's chance of winning the trophy is recalculated exactly (`src/brackets.py`). Strengths are frozen just before the round of 16. Before 2024-25 the later rounds were drawn one at a time, so for those seasons it uses the draws as they actually happened. Your picks are saved in the page's address, so "Share these picks" gives you a link that opens with exactly the same bracket.
- **A comeback meter.** Pick a first-leg score, where it was played, how strong your team is and which rules apply, and it gives you the exact chance of still going through (second leg, extra time, penalties, and away goals if you want them). Next to that is what actually happened in real ties that started the same way: 337 ties in all, from Champions League knockouts since 2011-12 and the Europa League seasons above. One thing it shows nicely: real teams that lost the first leg away usually went through more often than the "evenly matched" model says, because they were usually the seeded side and had the second leg at home.
- How often the favourite went through in each round.
- An explorer for all 226 ties, with a season-by-season strip and filters.
- The Real Madrid section.
- How honest the model is against the bookmakers, and the live ratings and prediction ledger.
- An upsets watch: the upcoming league games where the model rates a result well above the bookmakers do, so you can see each weekend whether the model or the market was right.

I tried to write the page for football fans rather than statisticians. The one idea it leans on, a team's chance of going through before the first leg, gets one name (the "pre-match chance") and is used everywhere. It works on phones, in light and dark mode, with a keyboard, and printed to PDF. If your system asks for reduced motion, you get the finished page without the animation.

Shared links show a preview card (`site/preview.png`), which `src/preview.py` draws from the same numbers as the page. The daily workflow refreshes `site/data.json` and the preview, and `.github/workflows/pages.yml` republishes the site after each daily update and every push to `main` that touches `site/`.

## Live predictions

To keep myself honest going forward, `src/update.py` refits Dixon–Coles every morning on the last three years of matches (recent ones count more) and predicts the big-five league fixtures that haven't kicked off yet. The predictions go into `results/live/prediction_ledger.csv` with a timestamp.

Once a prediction is in the ledger it never changes, so I can't quietly improve the record afterwards. Each league meeting is predicted once a season, even if the match gets moved. I also save the bookmakers' odds at the moment of each prediction. When a match is played, the prediction is scored against the result and against the bookmakers' closing odds. If a download fails, the old copy of that season's data is kept. `results/live/scorecard.md` has the running score and the current strongest clubs.

```bash
.venv/bin/python scripts/download_data.py --refresh-current
.venv/bin/python src/update.py
```

`.github/workflows/update.yml` runs this on GitHub Actions every morning and commits the results.

Not covered yet: the 2026-27 Champions League itself. openfootball stopped updating in September 2026 and I haven't found a free source that works without a key. football-data.org has a free plan with a personal key, but I still need to check whether it includes the Champions League.

## Tests

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m playwright install chromium firefox webkit   # once
.venv/bin/python -m pytest                                       # everything, about 3 minutes
.venv/bin/python -m pytest -o addopts="" tests/test_pipeline.py tests/test_data.py   # just the quick ones
```

`tests/test_pipeline.py` covers the daily job: failed downloads keep the old data, only fixtures that haven't kicked off get predicted (in UK time), a moved match is never predicted twice, the season rolls over on 1 July, and unfinished two-legged ties are skipped.

`tests/test_data.py` checks that `site/data.json` agrees with itself (each champion's run is the product of its ties, the calibration chart uses the same matches as the scores) and that the numbers in this README match the data.

`tests/test_site.py` loads the dashboard in Chromium, Firefox and WebKit and checks the things I kept breaking: chart colours in every theme, nothing running off the screen from 320px to 1920px, an accessibility scan, reduced motion, tooltips, hover zones, keyboard focus, links to a section, the nav highlight, the season strip, and that a printout shows every section finished.

GitHub Actions runs all of this on every push and after each daily update. The daily job also runs the quick checks before committing, so it never commits a `data.json` that disagrees with itself.

## Results

### Week 1: Elo against the bookmakers

One Elo rating per club, updated after every big-five league and Champions League match since August 2011, plus every Europa League match since 2020-21. That's 30,331 matches up to 2 November 2026. The rating difference is turned into home/draw/away chances with an ordered logistic model, refitted each season using earlier seasons only.

I used 2011-12 as a warm-up, tuned on 2012-13 to 2016-17 (K = 20, home advantage = 40 points, promoted sides start 50 below their league's average, no regression between seasons), and kept 2017-18 onwards purely for testing.

Scores on the test seasons (16,561 league matches with closing odds; lower is better):

| Model | Brier | Log loss |
|---|---|---|
| Base rates (same home/draw/away chances for every match) | 0.6497 | 1.0735 |
| Elo | 0.5879 | 0.9866 |
| Bookmakers' closing odds | 0.5737 | 0.9659 |

Elo gets about 81% of the way from knowing nothing to the bookmakers. They're still better, by 0.0142 Brier (95% interval 0.0123 to 0.0160, from resampling matches), and they win every single season. That's not surprising: closing odds know about team news, injuries and where the money's going.

The gap was biggest in 2020-21 (0.0204), the season without fans. Home advantage shrank and the bookmakers picked up on it much faster than Elo, which only learns from results.

Calibration is fine across the range ([chart](results/calibration_week1.png)). Elo is a little overconfident between 55% and 65%: home sides it gave about 65% won about 61% of the time. In European matches (2,062 in the test seasons, no odds available), Elo scores 0.5615 against 0.6353 for base rates.

Two caveats. Two of the tuned settings ended up at the edge of the grid I searched (home advantage 40, newcomer gap 50), though the difference between neighbouring settings was tiny (log loss 0.9792 vs 0.9793). And I used Pinnacle closing odds where they exist (2012-13 to 2025-26) and the market average otherwise.

`.venv/bin/python src/evaluate_elo.py` reproduces this (about 1.5 minutes, mostly the tuning grid).

### Week 2: Dixon–Coles goals model

Each club gets an attack and a defence strength, and goals follow a Poisson distribution with the Dixon–Coles correction for low scores (`src/dixon_coles.py`). Recent matches count more (a half-life of about 350 days), and clubs with little data get pulled towards a prior, with promoted sides and clubs only seen in Europe starting weaker than an average big-five side. The model is refitted every 7 days on earlier matches only. That's about 500 refits over the test seasons, but each takes about 0.03 seconds thanks to closed-form updates. Settings were tuned on the same seasons as week 1, and none ended at the edge of the grid this time.

Same 16,561 test matches:

| Model | Brier | Log loss |
|---|---|---|
| Elo | 0.5879 | 0.9866 |
| Dixon–Coles | 0.5872 | 0.9858 |
| Average of the two | 0.5861 | 0.9840 |
| Bookmakers' closing odds | 0.5737 | 0.9659 |

In the leagues it's basically a tie with Elo: the difference is −0.0008 Brier, with a 95% interval of −0.0020 to +0.0006, so it could go either way. Averaging the two is slightly better than either alone. Dixon–Coles is better calibrated though. It fixes Elo's overconfidence around 60% and tracks the bookmakers closely ([chart](results/calibration_week2.png)). The bookmakers still lead, by 0.0135 Brier (95% interval 0.0116 to 0.0151).

In European matches Dixon–Coles does beat Elo (0.5567 vs 0.5615 over 2,062 matches). Knockout matches are much harder: 0.6107 across 526 of them. Knockouts mostly pair strong teams, so results are closer to a coin flip, which was the first hint of what week 3 would find.

I went with Dixon–Coles for week 3 because it predicts scorelines, and you need scorelines to play out two legs, extra time and penalties.

`.venv/bin/python src/evaluate_dc.py` reproduces this (about 3 minutes).

### Week 3: so how much is luck?

For every Champions League knockout tie from 2012-13 to 2025-26 (226 ties), `src/knockouts.py` works out each team's chance of going through before the first leg, using a Dixon–Coles fit on earlier matches only. It handles both legs, away goals (until 2020-21), extra time and penalties (treated as a coin flip). It's an exact calculation rather than a simulation, which is the same as replaying each tie infinitely many times. As a sanity check, every winner the code finds turns up in the next round, and all 14 champions match the real ones.

The answer: a knockout tie is roughly a 70/30 bet. On average the model gave the underdog a **32%** chance of going through. The favourite went through in 69.9% of ties, against 68.0% expected (give or take about 6 points), so the tie probabilities hold up. The Brier score on ties is 0.194, where a coin flip would get 0.25. Ties get closer as the tournament goes on: the favourite's expected chance drops from 70% in the round of 16 to 62% in the semis and 59% in the final.

Even champions mostly got lucky ([chart](results/champions_path.png)). Multiply together a champion's chances in each tie it actually played and you get the odds of its whole run. That came out at **10% for the median champion**. The most expected runs were Man City in 2022-23 (26%) and Real Madrid in 2015-16 (25%). The least expected were Real Madrid in 2021-22 (2.9%) and Chelsea in 2020-21 (3.3%).

The biggest upsets, by the winner's pre-match chance:

- Club Brugge over Atalanta, 2024-25 play-offs: 13%
- Bodø/Glimt over Inter, 2025-26 play-offs: 14%
- Roma over Barcelona, 2017-18 quarter-final: 17%
- Villarreal over Bayern, 2021-22 quarter-final: 19%

### Luck, or a blind spot? Real Madrid

Overall the tie probabilities are honest, but one club breaks them. Real Madrid went through 36 of 44 ties when the model expected 24.3. If the model were right, that would happen about once in 11,500 tries, which is still far too rare even after allowing for the fact that I checked 15 clubs. Every other club with 8 or more ties is within the normal range.

The model isn't just underrating Real in general. In La Liga they took 2.24 points a match against 2.18 expected, which is spot on. In Champions League knockout matches they took 1.85 against 1.50 expected, a third of a point a match over 82 matches. Bayern, City, Barcelona and PSG show nothing like it.

So part of what looks like Real Madrid's luck isn't luck. Either they genuinely raise their level for these games, or something that matters in them (squad depth, experience, whatever you want to call it) doesn't show up in league results. A model built mostly on league results can't tell those two apart, and that's the obvious next thing to dig into.

`.venv/bin/python src/knockouts.py` reproduces this (a few seconds).
