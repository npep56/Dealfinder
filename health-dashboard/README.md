# Training Health dashboard

A live dashboard that puts your **Strava** training, your **Oura Ring** recovery and your **training plan** on one page, color-coded green / amber / red so you can see at a glance what's good and what needs attention.

It's built as a Claude **Data** artifact (a dashboard page on claude.ai), so it pulls fresh numbers through your own connectors every time you open it.

## What's on it

- **Today's call**: this morning's Oura readiness as a ring, with a suggestion (push / train as planned / take it easy)
- **Tiles**: sleep score, readiness, sleep hours, last night's HRV and lowest heart rate, VO₂ max, each with a status chip and a 14-day trend line
- **Race countdown**: from your Strava training focus, with progress through an 18-week build
- **This week's plan**: a card per day showing the plan, what Strava recorded (pace, effort), that morning's readiness / sleep score / HRV, and whether you did it, plus next week and last week
- **Weekly run mileage** with fast-ramp weeks flagged
- **Readiness against training load**, **how you bounce back** after hard / easy / rest days, **sleep** and **HRV / resting heart rate** charts
- **Last 14 days** table

## What you need

| | Why |
|---|---|
| A claude.ai account with Artifacts | The dashboard is a Data artifact |
| **Strava** connector (needs a Strava subscription) | Activities and your goal race |
| **Freddy - Oura** custom connector (`https://freddy.coach/mcp`) | Oura readiness, sleep, HRV, steps, VO₂ max. Freddy's free plan serves the last 7 days |
| Your training plan as a CSV (optional) | The plan section. A screenshot works too: Claude can type it up |

Add the Freddy connector on claude.ai under **Settings → Connectors → Add custom connector**, then sign in to Freddy and connect your Oura Ring there.

## Set it up

The easiest way is to let Claude do it. In a Claude Code session with this folder available, say:

> Create a Data dashboard from the files in `health-dashboard/`: use `datasets/*.json` as the datasets, `index.html` as the page, upload `samples/oura_history.empty.json` as the Oura history file and my training plan as the plan file, and point those two datasets at the uploads.

By hand, the pieces map like this:

| File | Goes to |
|---|---|
| `index.html` | the dashboard's `files/index.html` |
| `datasets/_dash_meta.json` | `dash/meta` (rename the title to make it yours) |
| `datasets/<id>.json` | `datasets/<id>` |
| `samples/oura_history.empty.json` | upload as an asset, put its `/_blob/...` url in `datasets/oura_history.json` |
| your plan CSV | upload as an asset, put its url in `datasets/training_plan.json` |

Then create the daily scheduled task in [`scheduled-task.md`](scheduled-task.md) so your Oura history keeps growing past Freddy's 7 days. Week-to-week comparisons appear once two weeks are saved.

## Training plan format

One row per day. See [`samples/training_plan.example.csv`](samples/training_plan.example.csv).

| Column | Example | Notes |
|---|---|---|
| `date` | `2027-03-03` | YYYY-MM-DD |
| `day` | `Wed` | |
| `week_of` | `2027-03-01` | the Monday of that week |
| `week_type` | `Build` | `Build`, `Cutback`, `Taper`, `Recovery`, `Simulation`, `Race week` (sets the card colors; combine with ` · `) |
| `planned_mi` | `7` | empty for a rest day |
| `workout` | `7 mi w/ 4 x 1 mi @ 10K pace` | `@`, `hard`, `pace`, `tempo` or 12+ miles marks a hard day |
| `week_total` | `35` | |

## Make it yours

Everything tunable is at the top of script 2 in `index.html`:

```js
const T = { readyGood: 85, readyWarn: 70, sleepGood: 7.5, sleepWarn: 6.5, hard: 60, ramp: 15, blockWeeks: 18 };
```

- `readyGood` / `readyWarn`: readiness and sleep-score cutoffs for green and red
- `sleepGood` / `sleepWarn`: sleep-hour cutoffs
- `hard`: Strava relative effort that counts as a hard day
- `ramp`: weekly mileage jump (%) that turns a bar amber
- `blockWeeks`: length of your build, for the countdown bar

Every place on the page that mentions a threshold reads it from here, so the words and colors stay in step.

## How the page is put together

`index.html` has three scripts:

1. **Sources and numbers**: loaders turn each connector's answer into rows (Freddy answers in plain text, which is parsed here); calcs work out every figure (`oura_all` joins saved history with live Freddy data, then `nightly`, `daily`, `kpis`, `plan_days`, `weekly`, `recovery`, `race`). Readers can see each formula in the dashboard's Sources panel.
2. **Thresholds, status rules and chart helpers** (`window.HB`).
3. **Drawings**: one `dash.draw` per `data-draw` element. Text you can read without data lives in the HTML; scripts only fill the marked elements.

## Test it offline

`test/` runs the page in a headless browser with **made-up data** and a stand-in for the dashboard runtime, at desktop and phone width:

```bash
npm install --prefix test d3@7.9.0 playwright
```

```bash
python3 test/build.py && node test/run.js
```

It prints `NO ERRORS`, or lists script errors, drawings that never filled in, and sideways scrolling. Scenarios: `python3 test/build.py race_passed` (also `no_focus`, `freddy_error`, `no_oura`). `node test/run.js shot` saves screenshots.

## Privacy

- Each person who opens the dashboard sees Strava and Oura data through **their own** connectors.
- **Attached files (your plan and Oura history) can be read by anyone who can open the dashboard.** Keep the dashboard private, or share it knowing that.
- Never commit your own plan or history to a public repo. Files named `my-*` are git-ignored here for that reason.
