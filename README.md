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

Once the study was done I checked every Champions League match against Transfermarkt's match list as a one-off. They agree on date and score everywhere except the 20 extra-time games, where Transfermarkt records the score after extra time and mine is the 90-minute score. That caught one real bug: eleven matches from the COVID-delayed finish in August 2020 were dated August 2019, so a few 2019-20 ties had stale or leaked information in their chances. It's fixed (`season_year` in `src/parse_europe.py`) and covered by tests, and every number below comes from after the fix. The effect was small (no tie result changed, and Real Madrid's record is the same), but the median champion's run went from 10% to 11% and Bayern's 2019-20 run from 11% to 18%.

## Data

| Source | What | Licence |
|---|---|---|
| [football-data.co.uk](https://www.football-data.co.uk/) | League results with bookmaker odds, including closing odds (e.g. `PSCH`, Pinnacle's closing home odds) | Free to use; check their terms before building anything public on it |
| [openfootball/champions-league](https://github.com/openfootball/champions-league) | Champions League results from 2011-12, and Europa League results from 2020-21 to 2024-25 (the only Europa League seasons it has), including extra time and penalties | CC0 (public domain) |

| [Wikipedia](https://en.wikipedia.org/wiki/UEFA_Champions_League) | The league phase of the season in progress: fixtures and results, read through the MediaWiki API. Only the season forecast uses it, because openfootball hasn't published the season | CC BY-SA 4.0 (credited on the page) |

`scripts/download_data.py` downloads everything into `data/raw/`, which isn't committed.

## Running it

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python scripts/download_data.py
```

To build and view the dashboard locally:

```bash
.venv/bin/python src/forecast.py                 # this season's forecast, results/forecast.json (while the season is on)
.venv/bin/python src/export_site.py              # writes site/data.json from results/
python3 -m http.server 8123 --directory site     # then open http://localhost:8123
```

## The dashboard

`site/` is plain HTML, CSS and JavaScript. The charts are hand-drawn SVG and canvas, with no libraries and no build step (`app.js` draws the charts, `motion.js` does the animation). The dashboard's UI design was done with help from Claude, an AI assistant.

What's on it:

- **The luck machine.** Every tie drops through a Galton board and lands on the winner's chance before the first leg, so the pile you end up with is the shape of the luck. Hover a ball to see its tie, or click it to jump to it in the explorer.
- An upsets ticker (ties won by a side given under 35%) and the headline numbers.
- Each champion's run, with a funnel showing its chances shrinking tie by tie.
- **Who'll win this season?** Every club's chance of finishing in the top eight, reaching each knockout round and winning the trophy, from 100,000 simulated seasons (more below). Click a heading to sort by it. The section runs from the start of the league phase to the final and is refreshed every morning. Below the table, the six likeliest winners are set beside the forecast made before the first matchday, with a sentence saying whether anything much has changed. It reads the forecasts kept in `results/forecast_history.csv`.
- **Replay every season.** Each past season's real draw is played out every possible way (all 32,768 results of its 15 ties, exactly, with no random simulation: `src/replays.py`). The page shows how often the club that really won would win in a replay, next to the season's favourite, and how unusual the real run of results was: the share of replays that were more likely than what happened. Seasons are ranked from most to least surprising, and clicking one opens it in the What-if bracket.
- **The matches that matter most.** For every league-phase match still to play, how much the result moves a club's chance of finishing in the top eight (straight into the round of 16). The forecast keeps each simulated match result and who finished in the top eight, then reads off a club's chance in the simulated seasons where it won, drew or lost that match (`match_leverage` in `src/forecast.py`; a result under 1 season in 20 is left out of the swing). The page shows the biggest swings among the next matches, or every match left for the club you pick. It appears whenever the forecast has the league phase still to play.
- **One tie is a lottery, a season isn't.** A typical favourite wins a tie about 68% of the time, so it still goes out about 1 time in 3. Three numbers show how fast that luck fades as it plays more ties (the chance it ends up with more losses than wins after 1, 10 and 30), and a sentence says what a trophy asks for: winning every tie, four or five in a row, which stays unlikely however good you are.
- **What if?** Pick the winner of any tie in any season since 2012-13 and every club's chance of winning the trophy is recalculated exactly (`src/brackets.py`). Strengths are frozen just before the round of 16. Before 2024-25 the later rounds were drawn one at a time, so for those seasons it uses the draws as they actually happened. Your picks are saved in the page's address, so "Share these picks" gives you a link that opens with exactly the same bracket.
- **A comeback meter.** Pick a first-leg score, where it was played, how strong your team is and which rules apply, and it gives you the exact chance of still going through (second leg, extra time, penalties, and away goals if you want them). Next to that is what actually happened in real ties that started the same way: 337 ties in all, from Champions League knockouts since 2011-12 and the Europa League seasons above. One thing it shows nicely: real teams that lost the first leg away usually went through more often than the "evenly matched" model says, because they were usually the seeded side and had the second leg at home.
- How often the favourite went through in each round, as a strip of five numbers under the wildest-season chart.
- **Which season was the wildest?** For each season, how many underdogs went through against how many the model expected. Hover a season to see who they were; click it to open its ties in the explorer.
- An explorer for all 226 ties, with a season-by-season strip and filters. Every tie shows how it actually ended: both legs, extra time, penalties, or the away-goals rule where it was used. Type two clubs to get their full history against each other, with how often the model expected each to go through; the page suggests the pairings that have met most often.
- The Real Madrid section, with two checks on whether its record is luck: where in a tie the extra wins came from, and whether the first seven seasons predict the last seven.
- How honest the model is against the bookmakers, and the live prediction ledger.
- An upsets watch: the upcoming league games where the model rates a result well above the bookmakers do, so you can see each weekend whether the model or the market was right.

I tried to write the page for football fans rather than statisticians. The one idea it leans on, a team's chance of going through before the first leg, gets one name (the "pre-match chance") and is used everywhere. The few technical words that are left, like Elo, are underlined with dots: hover, tap or tab to one for a one-line explanation. It works on phones, in light and dark mode, with a keyboard, and printed to PDF. If your system asks for reduced motion, you get the finished page without the animation.

Shared links show a preview card (`site/preview.png`), which `src/preview.py` draws from the same numbers as the page. The daily workflow refreshes `site/data.json` and the preview, and `.github/workflows/pages.yml` republishes the site after each daily update and every push to `main` that touches `site/`.

## Live predictions

To keep myself honest going forward, `src/update.py` refits Dixon–Coles every morning on the last three years of matches (recent ones count more) and predicts the big-five league fixtures that haven't kicked off yet. The predictions go into `results/live/prediction_ledger.csv` with a timestamp.

Once a prediction is in the ledger it never changes, so I can't quietly improve the record afterwards. Each league meeting is predicted once a season, even if the match gets moved. I also save the bookmakers' odds at the moment of each prediction. When a match is played, the prediction is scored against the result and against the bookmakers' closing odds. If a download fails, the old copy of that season's data is kept. `results/live/scorecard.md` has the running score and the current strongest clubs.

```bash
.venv/bin/python scripts/download_data.py --refresh-current
.venv/bin/python src/update.py
```

`.github/workflows/update.yml` runs this on GitHub Actions every morning and commits the results.

Not covered by the ledger: the 2026-27 Champions League matches themselves. openfootball stopped updating in September 2026, and I haven't found a free source that works without a key for scoring them as predictions. (The season forecast below reads this season's results from Wikipedia instead, but only for itself: they aren't in the main data.)

## Who'll win this season?

`src/forecast.py` plays out the rest of the season 100,000 times and counts how often each club gets how far. It runs every morning after the update, writes `results/forecast.json`, and the dashboard shows it as a table you can sort.

```bash
.venv/bin/python scripts/download_data.py --refresh-current   # also fetches this season's league phase, knockout phase and final from Wikipedia
.venv/bin/python src/forecast.py
```

How it works:

1. **Strengths.** The same Dixon–Coles model and settings as everything else, fitted on all matches up to today plus the league-phase matches already played this season (those come from Wikipedia, so `data/wikipedia_names.csv` maps its club names onto the model's). A club with no earlier matches in the data is rated from this season alone, and the page marks it.
2. **League phase.** Each match still to play gets a scoreline drawn from the model's chances. The table is sorted the way UEFA sorts it down to away wins, and what comes after that (opponents' results, discipline, coefficients) is left to chance.
3. **Knockouts.** The top eight go straight to the last 16; 9th to 24th play off for the other eight places, and the rest of the bracket is fixed. The draws are random with no country protection, the better-placed side hosts the second leg, and a team that knocks out a better seed takes that seed's place. These are the 2025-26 rules, and they are checked against what happened that season: `test_the_bracket_is_the_one_used_in_2025_26` replays its knockouts through the bracket in the code, and checking against that season is what showed that "better-placed" means the seed's place and not the club's own league-phase position. Each tie uses the exact chance of going through two legs from `src/knockouts.py` (extra time, then penalties), and the final is one match on neutral ground.

What to keep in mind:

- It's the model's view, not a price. Strengths are frozen at today's, and it knows nothing about injuries, transfers, line-ups or the betting market. Treating each club's strength as known also makes the favourites look a little surer than they should. I haven't compared the numbers with bookmakers' title odds (there's no free source), so I wouldn't read the top club's figure as better than that. The backtest below shows how the favourites fared in the two earlier seasons.
- The 100,000 simulations leave each figure good to a few tenths of a point. A fixed random seed means rerunning on the same data gives the same numbers.
- **Once the knockouts start it plays them from where they stand.** The knockout phase and final articles on Wikipedia are read every morning (`src/parse_knockouts.py`). A draw that has been made is the draw that is played, a tie that is over is settled, and after a first leg the second is played out knowing its score (`after_first_leg` in `src/forecast.py`, checked against the whole tie in the tests). Before a draw, the draw is still random. `test_last_seasons_knockouts_are_played_out_from_where_each_stage_stood` runs this on 2025-26 at five points in the knockouts. The forecast comes down three days after the final, and the page leaves it out if it hasn't been refreshed for two weeks.
- Not done: using squad market values (Transfermarkt) to correct clubs the results can't tell apart yet, like a newly promoted side with a good start.

### Does it hold up?

`src/backtest_forecast.py` replays the forecast on 2024-25 and 2025-26, the two seasons in this format, as it would have looked before matchday 1 and after matchdays 2, 4, 6 and 8. It only uses what was known at each moment, and scores every club's chance of every stage against what happened (`results/forecast_backtest.json`). Two seasons is not much, and the forecasts overlap heavily (one upset moves a dozen clubs), so this catches gross mistakes and no more. Both seasons use the 2025-26 bracket, though 2024-25's quarter-finals were paired differently, so its later rounds are a little off.

- **It beats giving every club the same chance, at every stage except the title.** The improvement in Brier score over that flat forecast ("skill") is +29% for finishing in the top eight, +45% for the top 24, +37% for the last 16, +41% for the quarter-finals, +34% for the semi-finals and +24% for the final, and +36% across all of them. The title is the exception, at +1%: there is one winner a season, so two seasons can't tell a good title forecast from a flat one.
- **The favourites were too sure, and the long shots too unlikely.** Clubs given 75% to 90% did it 70 times out of 101, where 83 were expected; clubs given 2% to 10% did it 27 times against 19 expected. Most of the rest is close, for example 120 against 119 expected in the 50% to 75% band.
- **The title favourite never won.** Arsenal or Man City were the favourite at all ten moments, and Paris SG won both seasons. They were given 3% to 5% in 2024-25 (6th to 10th favourite) and 10% to 14% in 2025-26 (2nd or 3rd). The model expected the favourite to win at 2.4 of the ten moments, so that proves little by itself.
- **Letting the ratings be uncertain didn't help.** I nudged every club's attack and defence strength at random (by 0.08, 0.15 and 0.25 log-goals, over 20 versions of the ratings), which is the obvious fix for favourites being too sure. It narrowed the 75% to 90% gap, but it made the score slightly worse each time: skill +35.6%, +35.4% and +34.9% against +35.9% without it. So the page doesn't use it. `src/backtest_forecast.py --noise 0.15` reruns it, and another season or two of data would settle it.

## Tests

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m playwright install chromium firefox webkit   # once
.venv/bin/python -m pytest                                       # everything, about 3 minutes
.venv/bin/python -m pytest -o addopts="" tests/test_pipeline.py tests/test_data.py   # just the quick ones
```

`tests/test_pipeline.py` covers the daily job: failed downloads keep the old data, only fixtures that haven't kicked off get predicted (in UK time), a moved match is never predicted twice, the season rolls over on 1 July, and unfinished two-legged ties are skipped.

`tests/test_knockout_forecast.py` covers reading the knockout articles (the fixtures in `tests/fixtures/` are trimmed from Wikipedia's 2025-26 pages) and playing out ties in progress. `tests/test_forecast_backtest.py` covers the backtest's scoring and what it counts as having happened. `tests/test_forecast.py` covers the season forecast: reading Wikipedia's league phase, the table's tie-breakers one by one, the bracket against what happened in 2025-26, simulations that must come out a known way (identical clubs get identical chances, a team that wins everything wins the trophy, every stage has the right number of clubs), and what happens when the data is missing or the season moves on.

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

Elo gets about 81% of the way from knowing nothing to the bookmakers. They're still better, by 0.0142 Brier (95% interval 0.0123 to 0.0161, from resampling matches), and they win every single season. That's not surprising: closing odds know about team news, injuries and where the money's going.

The gap was biggest in 2020-21 (0.0204), the season without fans. Home advantage shrank and the bookmakers picked up on it much faster than Elo, which only learns from results.

Calibration is fine across the range ([chart](results/calibration_week1.png)). Elo is a little overconfident between 55% and 65%: home sides it gave about 65% won about 61% of the time. In European matches (2,062 in the test seasons, no odds available), Elo scores 0.5614 against 0.6353 for base rates.

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

In the leagues it's basically a tie with Elo: the difference is −0.0008 Brier, with a 95% interval of −0.0021 to +0.0006, so it could go either way. Averaging the two is slightly better than either alone. Dixon–Coles is better calibrated though. It fixes Elo's overconfidence around 60% and tracks the bookmakers closely ([chart](results/calibration_week2.png)). The bookmakers still lead, by 0.0135 Brier (95% interval 0.0117 to 0.0152).

In European matches Dixon–Coles does beat Elo (0.5567 vs 0.5614 over 2,062 matches). Knockout matches are much harder: 0.6106 across 526 of them. Knockouts mostly pair strong teams, so results are closer to a coin flip, which was the first hint of what week 3 would find.

I went with Dixon–Coles for week 3 because it predicts scorelines, and you need scorelines to play out two legs, extra time and penalties.

`.venv/bin/python src/evaluate_dc.py` reproduces this (about 3 minutes).

### Week 3: so how much is luck?

For every Champions League knockout tie from 2012-13 to 2025-26 (226 ties), `src/knockouts.py` works out each team's chance of going through before the first leg, using a Dixon–Coles fit on earlier matches only. It handles both legs, away goals (until 2020-21), extra time and penalties (treated as a coin flip). It's an exact calculation rather than a simulation, which is the same as replaying each tie infinitely many times. As a sanity check, every winner the code finds turns up in the next round, and all 14 champions match the real ones.

The answer: a knockout tie is roughly a 70/30 bet. On average the model gave the underdog a **32%** chance of going through. The favourite went through in 69.9% of ties, against 68.0% expected (give or take about 6 points), so the tie probabilities hold up. The Brier score on ties is 0.193, where a coin flip would get 0.25. Ties get closer as the tournament goes on: the favourite's expected chance drops from 70% in the round of 16 to 62% in the semis and 60% in the final.

Even champions mostly got lucky ([chart](results/champions_path.png)). Multiply together a champion's chances in each tie it actually played and you get the odds of its whole run. That came out at **11% for the median champion**. The most expected runs were Man City in 2022-23 (25%) and Real Madrid in 2015-16 (25%). The least expected were Real Madrid in 2021-22 (3.0%) and Chelsea in 2020-21 (3.2%).

The biggest upsets, by the winner's pre-match chance:

- Club Brugge over Atalanta, 2024-25 play-offs: 13%
- Bodø/Glimt over Inter, 2025-26 play-offs: 14%
- Roma over Barcelona, 2017-18 quarter-final: 17%
- Villarreal over Bayern, 2021-22 quarter-final: 19%

### Luck, or a blind spot? Real Madrid

Overall the tie probabilities are honest, but one club breaks them. Real Madrid went through 36 of 44 ties when the model expected 24.3. If the model were right, that would happen about once in 10,200 tries, That is for Real Madrid on its own. I noticed Real Madrid before testing them, so the fair question is how often the most unusual club in the whole field would look this extreme if every tie followed the model. Replaying the 226 ties 400,000 times with every club that has at least 4 ties (31 clubs), it happens about once in 530 tries (`selection_corrected` in `src/real_madrid.py`), so the effect survives the correction. Every other club with 8 or more ties is within the normal range (none is further than 1.4 standard deviations from what the model expected).

So is it luck or a blind spot? `src/real_madrid.py` runs every check below.

**It isn't the model underrating Real Madrid everywhere.** In La Liga they took 2.24 points a match against 2.17 expected, which is inside the margin of error. In Champions League group matches the gap was +0.16 a match (88 matches), and in knockout matches +0.34 (1.85 against 1.51, over 82 matches). Every other club taken together is spot on in both: the gap is -0.00 over 2,792 group matches and -0.01 over 782 knockout matches. Real's three numbers climb with the stakes, but their error bars overlap, so I wouldn't read much into that.

**It isn't just Spain.** Barcelona won 17 of 28 ties against 17.5 expected, and Atlético Madrid 15 of 26 against 13.1.

**Where in a tie it happens.** Of Real's 44 ties, 37 were settled in normal time: they won 29 when the model expected 21.7, and lost 8 when it expected 17.1. Seven went to extra time or penalties, which the model treats as close to coin flips, and Real won all seven (2.7 expected, about 1 in 170). That run is the likeliest piece of pure luck. I picked these cuts after seeing the data, so read the odds as descriptions rather than tests.

**Did it last?** This is the check that separates a lucky run from something real, because luck washes out and a real effect carries on. Split the 14 seasons into two halves of seven. In the first Real won 20 of 23 ties against 14.2 expected, and in the second 16 of 21 against 10.2: about the same both times, and ahead of the model in 11 of 14 seasons. The second half is the fair test. I'd already have noticed Real from the first half, and picking one club out of 15 after the fact is easy to fool yourself with, but then they did it again over seven more seasons, which for a club chosen in advance would happen about once in 140 tries. A boost fitted on the first seven seasons alone (it multiplies Real's odds of going through by about 4.8) cuts the forecast error on the next 21 ties from 0.642 to 0.476 (log loss per tie). Other clubs don't do that. For the 11 other clubs with at least four ties in each half, a good first half says nothing about the second (the correlation is -0.43), which is how luck should behave.

**Is it the line-ups?** The obvious explanations are rotation (Real rest players in La Liga, so league results understate them in Europe) and a better best eleven than their results show. Transfermarkt's open dataset has every starting eleven and each player's market value, so `src/real_madrid_squad.py` tests both (it needs `python scripts/download_data.py --transfermarkt`, about 135 MB, and takes about 30 seconds). Real do field a fuller eleven in Europe than in La Liga: 91% of their best eleven's value in knockout matches against 84% in the league. But every big club does. The gap is +0.070 for Real and +0.054 on average for the other 15 clubs, and Real ranks 5th of 16. Fielding a stronger eleven than usual predicts only a small, uncertain gain (+0.29 goals a match, standard error 0.19), and between the eleven Real fielded and the gap in squad quality with their opponents, only +0.03 of their +0.44 goals a match in knockouts is accounted for. Real beat the model under Ancelotti (+0.39 points a match) and under Zidane (+0.23), but Ancelotti's 24 matches elsewhere (+0.03) are too few to tell a coach from a club.

**What I think.** Mostly a real blind spot, with some luck on top, and not one that rotation or a stronger eleven explains. What's left is something neither results nor line-ups can see: how Real manage a tie, experience in these games, or something about the club itself. Bookmaker odds for these matches would be the next test, because they'd show whether the market also rated Real above the model, but I couldn't find a free source for Champions League odds.

`.venv/bin/python src/knockouts.py` reproduces the first part (a few seconds), and `.venv/bin/python src/real_madrid.py` the rest (about 25 seconds).
