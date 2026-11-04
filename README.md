# How much of a Champions League knockout is luck?

My model against the bookmakers, using Champions League knockouts from 2011-12 onwards.

The project is a **study first** and an app second. The question decides what gets built.

## The question

When a Champions League knockout ends, how much of the result came from the better team being better, and how much from luck? To answer it, I need a model whose probabilities can be trusted, so the first job is proving the model is honest.

## Plan

| Week | Work | Done when |
|---|---|---|
| 1 | Elo ratings in Python, on the big five leagues plus Champions League and Europa League results | A Brier score on a season the model never saw is written below |
| 2 | Dixon–Coles goals model; walk-forward testing (train on past seasons, predict the next) | A calibration chart against bookmakers' closing odds, with error bars |
| 3 | Work out each knockout's exact chances before the first leg | One chart: how likely each champion's run was |
| 4 | Small bracket demo, **only if the analysis holds up** | A page someone can try in 10 seconds |

If I stop after week 2, I still have a model tested against bookmakers.

### Cut on purpose
- StatsBomb event data: not needed for a goals model.
- "Did the 2024-25 format help the big clubs?": two seasons is too little data.
- Live leaderboards, accounts and a WhatsApp version.

### Things to keep in mind
- **Few matches.** Each season has only about 15 knockout ties. Pool all seasons, test calibration on every league match, and show error bars.
- **I will probably lose to the bookmakers.** That's expected. Report how close I got and why.
- **Team names differ between sources.** For example, "Man City" in one source and "Manchester City FC (ENG)" in the other, so I need a name mapping.

## Data

| Source | What | Licence |
|---|---|---|
| [football-data.co.uk](https://www.football-data.co.uk/) | League results with bookmaker odds, including closing odds (for example `PSCH`, Pinnacle closing home odds) | Free to use; check their terms before publishing anything built on it |
| [openfootball/champions-league](https://github.com/openfootball/champions-league) | Champions League results from 2011-12 and Europa League results from 2020-21 to 2024-25 (the only Europa League seasons it has), including extra time and penalties | CC0 (public domain) |

Raw data is downloaded by `scripts/download_data.py` into `data/raw/` and isn't committed.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python scripts/download_data.py
```

## Dashboard

`site/` is a static dashboard: plain HTML, CSS and JavaScript with hand-drawn SVG and canvas charts, no libraries and no build step (`app.js` draws the charts, `motion.js` handles the animation). It shows:
- **the luck machine**: every tie since 2012-13 drops through a Galton board and lands on the chance the team that went through had before the first leg, so the pile is the shape of the luck. Hover a ball for its tie; click it to find it in the explorer;
- a ticker of the biggest upsets (the team that went through had under 35%) and the headline numbers;
- each champion's run, with a funnel showing its chance shrinking tie by tie (pick any champion);
- **"What if?"**, a butterfly-effect bracket for every season since 2012-13 (`src/brackets.py`). Pick the winner of any tie, and every club's chance of winning the trophy is recalculated exactly, with gains and losses shown against the chances before your picks. Strengths are frozen just before the round of 16. For seasons before 2024-25, when later rounds were drawn round by round, the bracket uses the draws as they happened;
- **a comeback meter**: pick a first-leg score, venue, team strength and rule set.
  - The model works out the exact chance of going through, covering the second leg, extra time, penalties and, optionally, away goals.
  - It sits next to the record of real two-legged ties that started the same way under the same rules, with a 95% range: 337 ties in all, from Champions League knockouts since 2011-12 and Europa League knockouts from 2020-21 to 2024-25.
  - A heatmap shows every first-leg score at once. Under today's rules only the goal difference matters, so each diagonal is the same; with away goals it isn't.
  - Real teams that lost the first leg away usually hosted the second leg because they were seeded, which is why the record beats the "evenly matched" model there.
- favourites by round, with uncertainty;
- an explorer for all 226 ties, with a season-by-season strip and filters for season, round, club and upsets;
- the Real Madrid blind spot;
- calibration against the bookmakers, shown as each model's gap from honest (or on the full scale), plus how much of the way from knowing nothing to the bookmakers each model gets (the exact Brier and log-loss scores are in a fold-out);
- the live ratings, in football terms (goals scored and conceded, and the chance of winning, against an average big-five club on a neutral pitch), and the prediction ledger.

The page is written for football fans, not statisticians: the one idea it relies on, each team's chance of going through before the first leg, is introduced once as the **pre-match chance**.

It works on phones, in light and dark mode, with a keyboard, and printed or saved as PDF (every section prints, in the light palette). Readers who ask their system for reduced motion get the finished page without animation.

The dashboard's UI design was done with help from Claude, an AI assistant.

```bash
.venv/bin/python src/export_site.py              # writes site/data.json from results/
python3 -m http.server 8123 --directory site     # then open http://localhost:8123
```

**Live at [kgadharsh.github.io/ucl-luck](https://kgadharsh.github.io/ucl-luck/).** The daily workflow refreshes `site/data.json`, and `.github/workflows/pages.yml` republishes `site/` to GitHub Pages after every daily update and every push to `main` that changes it.

## Tests

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m playwright install chromium firefox webkit   # the three browser engines, once
.venv/bin/python -m pytest                                       # everything, about 3 minutes
.venv/bin/python -m pytest -o addopts="" tests/test_pipeline.py tests/test_data.py   # just the fast checks
```

- `tests/test_pipeline.py`: failed downloads keep the old data, only fixtures still to kick off are predicted (in UK time), a moved match is never predicted twice, the season rolls over on 1 July, and unfinished two-legged ties are skipped.
- `tests/test_data.py`: `site/data.json` agrees with itself (every champion's run is the product of its ties, the calibration chart uses the same matches as the scores table), and the README quotes the same numbers as the data.
- `tests/test_site.py`: the dashboard in Chromium, Firefox and WebKit (Safari's engine). It checks that charts use the right colours in every theme combination, that nothing runs off-screen from 320px to 1920px wide, an accessibility scan, reduced motion, tooltips (they hide however the pointer leaves; a tap shows one on touch screens), hover zones, keyboard focus, links to a section, the nav highlight, the season strip's zoom and filters, and that a printout shows every section in final form.

GitHub Actions runs them on every push and pull request and after each daily update (`.github/workflows/tests.yml`). The daily job also runs the pipeline and data checks before it commits, so it never commits a `data.json` that disagrees with itself.

## Live predictions (self-updating)

`src/update.py` refits Dixon–Coles on the last three years of matches, with recent ones counting more. It then predicts big-five league fixtures that haven't kicked off yet (using the kick-off times in football-data's fixture list) and writes them to a **prediction ledger** (`results/live/prediction_ledger.csv`), stamped with the time of prediction.
- A prediction already in the ledger is never changed, so the record can't be quietly improved afterwards. Each league meeting is predicted once per season, even if the match is moved to another date.
- Once a match is played, its prediction is scored against the result and the bookmakers' closing odds.
- If a download fails, the previous copy of that season's data is kept rather than lost.
- `results/live/scorecard.md` shows the running score and the current strongest clubs.

```bash
.venv/bin/python scripts/download_data.py --refresh-current
.venv/bin/python src/update.py
```

`.github/workflows/update.yml` runs this every morning on GitHub Actions and commits the results.

**Not covered yet:** the 2026-27 Champions League. openfootball has no 2026-27 Champions League data (it stopped updating in September 2026), and I found no free source that works without a key. The football-data.org API has a free plan that needs a personal key; check that its free plan covers the Champions League before relying on it.

## Results

### Week 1: Elo against the bookmakers

**Setup.** One Elo rating per club, updated after every big-five league and Champions League match from August 2011 and every Europa League match from 2020-21 (30,331 matches, up to 2 November 2026). A rating difference becomes home/draw/away chances through an ordered logistic model, refitted each season on earlier seasons only.
- 2011-12: warm-up, not scored.
- 2012-13 to 2016-17: tuning only (K = 20, home advantage = 40 points, promoted sides start 50 below their league's average, no regression between seasons).
- 2017-18 onwards: test seasons, never used for any choice.

**Scores on the test seasons** (16,561 league matches with closing odds; lower is better):

| Model | Brier | Log loss |
|---|---|---|
| Base rates (same home/draw/away chances for every match) | 0.6497 | 1.0735 |
| **Elo** | **0.5879** | **0.9866** |
| Bookmakers' closing odds | 0.5737 | 0.9659 |

- Elo closes **about 81% of the gap** between knowing nothing and the bookmakers.
- The bookmakers are still better, by 0.0142 Brier (95% interval 0.0123 to 0.0160, from resampling matches). They lead in every single season, as expected: closing odds include team news, injuries and the betting market's money.
- The gap was widest in **2020-21 (0.0204)**, the season played without fans. Home advantage shrank, and the bookmakers adjusted faster than Elo, which learns slowly from results.
- **Calibration** ([chart](results/calibration_week1.png)): both are honest across the range. Elo is slightly overconfident between 55% and 65%: home sides it gave about 65% won about 61% of the time.
- **European matches** (2,062 in test seasons, with no odds available): Elo Brier 0.5615, against 0.6353 for base rates.

**Caveats.**
- Two tuned settings ended at the edge of the grid searched (home advantage 40, newcomer gap 50). The differences between nearby settings were tiny (log loss 0.9792 against 0.9793), so this barely matters, but it's worth widening the grid in week 2.
- Pinnacle closing odds are used where available (2012-13 to 2025-26); otherwise the market average is used.

Run it with `.venv/bin/python src/evaluate_elo.py` (about 1.5 minutes, mostly the tuning grid).

### Week 2: Dixon–Coles goals model

**Setup.** Each club gets an attack and a defence strength, and goals follow a Poisson distribution with the Dixon–Coles correction for low scores (`src/dixon_coles.py`).
- Recent matches count more, with a half-life of about 350 days.
- Clubs with little data are pulled towards a prior. Promoted sides and clubs seen only in Europe start weaker than an average big-five club.
- The model is **refitted every 7 days on earlier matches only**. That makes about 500 refits for the test seasons, and each takes about 0.03 seconds thanks to closed-form updates.
- Settings were tuned on 2012-13 to 2016-17 (none ended at the edge of the grid). The test seasons are the same as week 1.

**Scores on the test seasons** (same 16,561 league matches; lower is better):

| Model | Brier | Log loss |
|---|---|---|
| Elo | 0.5879 | 0.9866 |
| Dixon–Coles | 0.5872 | 0.9858 |
| Average of the two | 0.5861 | 0.9840 |
| Bookmakers' closing odds | **0.5737** | **0.9659** |

- **Dixon–Coles ties with Elo in the leagues.** The difference is −0.0008 Brier, with a 95% interval of −0.0020 to +0.0006, which includes zero. Averaging the two models is a little better than either alone.
- **It is better calibrated.** It fixes Elo's overconfidence between 55% and 65% and tracks the bookmakers closely ([chart](results/calibration_week2.png)).
- **The bookmakers still lead**, by 0.0135 Brier (95% interval 0.0116 to 0.0151).
- **In European matches** (2,062 test matches), Dixon–Coles beats Elo: Brier 0.5567 against 0.5615.
- **Knockout matches are much harder to predict**: Brier 0.6107 across 526 knockout matches, against 0.5567 for all European matches. Knockouts mostly pair strong teams, so results are closer to a coin flip. This is the first hint for the luck question.

Dixon–Coles is the model for week 3, because it predicts **scorelines**. That's needed to simulate two-legged ties, extra time and penalties.

Run it with `.venv/bin/python src/evaluate_dc.py` (about 3 minutes).

### Week 3: how much of a knockout is luck?

**Setup.** For every Champions League knockout tie from 2012-13 to 2025-26 (226 ties), the chance of each team going through is worked out **before the first leg**, from a Dixon–Coles fit on earlier matches only (`src/knockouts.py`).
- It covers both legs, the away-goals rule (used until 2020-21), extra time and penalties (treated as a coin flip).
- The calculation is exact rather than simulated, which is the same as replaying each tie infinitely many times.
- Check: every tie winner the code finds appears in the next round, and all 14 champions match the real ones.

**The answer: a knockout tie is roughly a 70/30 bet.**
- On average the model gave the underdog a **32%** chance of going through.
- The model's favourite went through in **69.9%** of ties, against **68.0%** expected (95% interval about ±6 points), so the tie probabilities are honest.
- Tie Brier score 0.194, where a coin flip scores 0.25.
- The later the round, the closer the contest. The favourite's expected chance falls from 70% in the round of 16 to 62% in the semi-finals and 59% in the final.

**Even champions mostly got lucky** ([chart](results/champions_path.png)).
- Judged before each tie, the chance of winning every tie they actually played was **10% for the median champion**.
- The most expected runs were Man City 2022-23 (26%) and Real Madrid 2015-16 (25%). The least expected were Real Madrid 2021-22 (2.9%) and Chelsea 2020-21 (3.3%).

**Biggest upsets** (chance of the team that went through):
- Club Brugge over Atalanta, 2024-25 play-offs: 13%
- Bodø/Glimt over Inter, 2025-26 play-offs: 14%
- Roma over Barcelona, 2017-18 quarter-final: 17%
- Villarreal over Bayern, 2021-22 quarter-final: 19%

### Luck, or a blind spot? Real Madrid

The tie probabilities are honest overall, but one club breaks them.
- **Real Madrid went through 36 of 44 ties when the model expected 24.3.** If the model were right, that would happen about **once in 11,500 tries**, which is still far too rare after allowing for 15 clubs being checked. Every other club with 8 or more ties is within the normal range.
- The model rates Real accurately in La Liga: they took 2.24 points a match against 2.18 expected. In **Champions League knockout matches** they took **1.85 against 1.50 expected**, a third of a point a match over 82 matches. Bayern, City, Barcelona and PSG show no comparable gap.
- **Conclusion:** part of what looks like Real Madrid's luck is not luck. Either Real lifts its level for Champions League knockouts, or something that matters there (squad depth, experience) isn't visible in league results. A model built mostly on league results can't tell these apart. That limit is worth stating plainly, and testing it further is a natural next step.

Run it with `.venv/bin/python src/knockouts.py` (a few seconds).
