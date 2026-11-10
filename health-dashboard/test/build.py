"""Build test/test.html: the dashboard page plus a stand-in runtime (mock.js) and made-up data.

Usage (from the health-dashboard folder):
    npm install --prefix test d3@7.9.0 playwright
    python3 test/build.py [scenario]     # scenario: race_passed | no_focus | freddy_error | no_oura
    node test/run.js [screenshot-prefix]

All data here is synthetic, generated relative to today. Nothing personal is stored.
"""
import csv, datetime as dt, json, os, random, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
random.seed(7)
today = dt.date.today()
monday = today - dt.timedelta(days=today.weekday())

# Strava list_activities answer (shape of use_preferred_units=true)
acts = []
for i in range(70):
    d = today - dt.timedelta(days=i)
    if d.weekday() == 6:
        continue
    long = d.weekday() == 5
    hard = d.weekday() == 2
    miles = round(random.uniform(12, 16) if long else random.uniform(6, 9) if hard else random.uniform(3, 7), 2)
    pace = random.randint(500, 540) if hard else random.randint(560, 610)
    acts.append({"id": str(9000 + i), "name": "Long run" if long else "Speed work" if hard else "Easy run",
                 "sport_type": "Run", "start_local": f"{d}T07:00:00",
                 "summary": {"distance": miles, "moving_time": int(miles * pace), "elevation_gain": 200,
                             "avg_pace": pace, "avg_pace_display": f"{pace // 60}:{pace % 60:02d} /mi",
                             "relative_effort": random.randint(70, 110) if hard or long else random.randint(8, 30),
                             "total_calories": int(miles * 110)}})
strava = {"activities": acts, "has_next_page": False}
profile = {"measurement_preference": "Imperial",
           "current_focus": {"focus_type": "TrainForEvent", "open_text": "Spring marathon",
                             "expires_at_local": f"{today + dt.timedelta(days=60)}T23:59:59"}}

# Freddy query_metrics text answer for the last 7 days
lines = ["Health data (last 7 days):", ""]
for i in range(8):
    d = today - dt.timedelta(days=i)
    lines.append(f"{d}:")
    if i > 0:
        lines += [f"  sleep_average_hrv: {random.randint(60, 90)} ms_rmssd (Oura)",
                  f"  sleep_lowest_heart_rate: {random.randint(40, 47)} bpm (Oura)",
                  f"  sleep_total_sleep_duration: {random.randint(21000, 28000)} seconds (Oura)",
                  f"  sleep_total_sleep_duration: {random.randint(300, 1200)} seconds (Oura)",
                  f"  daily_activity_steps: {random.randint(4000, 20000)} count (Oura)"]
        if i % 2:
            lines.append("  vo2_max_vo2_max: 52 ml_kg_min (Oura)")
    lines += [f"  daily_readiness_score: {random.randint(62, 92)} score (Oura)",
              f"  daily_sleep_score: {random.randint(62, 90)} score (Oura)"]
freddy = "\n".join(lines)

# Saved history: 14 older days
history = [{"date": str(today - dt.timedelta(days=i)), "readiness": random.randint(65, 90),
            "sleep_score": random.randint(62, 88), "sleep_min": random.randint(350, 470),
            "hrv": random.randint(60, 90), "lowest_hr": random.randint(40, 47),
            "steps": random.randint(4000, 18000), "vo2max": 51 if i % 3 == 0 else None} for i in range(21, 7, -1)]

# Plan: three weeks around today
plan = []
for w in (-1, 0, 1):
    start = monday + dt.timedelta(weeks=w)
    mi = [5, 3, 8, 3, 5, 14, None]
    for i in range(7):
        d = start + dt.timedelta(days=i)
        plan.append({"date": str(d), "day": d.strftime("%a"), "week_of": str(start), "week_type": ["Build", "Simulation", "Cutback"][w + 1],
                     "planned_mi": None if mi[i] is None else str(mi[i]),
                     "workout": "Rest" if mi[i] is None else ("8 mi w/ 5 mi @ tempo" if i == 2 else f"{mi[i]} mi easy"),
                     "week_total": "38"})

fx = {"strava_acts": strava, "strava_profile": profile, "freddy_oura": freddy, "oura_history": history, "training_plan": plan}
sc = sys.argv[1] if len(sys.argv) > 1 else ""
if sc == "race_passed": profile["current_focus"]["expires_at_local"] = f"{today - dt.timedelta(days=3)}T23:59:59"
if sc == "no_focus": profile.pop("current_focus")
if sc == "freddy_error": fx["freddy_oura"] = "Error: freddy needs you to sign in again."
if sc == "no_oura": fx["freddy_oura"] = "No health data found for the last 7 days."; fx["oura_history"] = []

page = open(os.path.join(ROOT, "index.html")).read()
tokens = ("--color-fg:#1b1d22;--color-fg-muted:#62666f;--color-bg:#fff;--color-panel:#f7f7f8;--color-border-line:#e3e4e8;"
          "--color-ok:#1d9a6c;--color-warn:#d99a0b;--color-bad:#d43f3f;--cds-chart-grid:#e9eaee;--cds-chart-muted:#b9bcc4;"
          "--cds-chart-reference:#8b8f99;--cds-text-secondary:#62666f;--cds-surface-popover:#fff;--cds-border:#ddd;"
          "--font-anthropic-sans:system-ui;--font-anthropic-serif:Georgia")
html = f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<style>:root{{{tokens}}} body{{margin:0;padding:24px;background:#fff;font:14px system-ui}}</style>
<script src="node_modules/d3/dist/d3.min.js"></script><script src="mock.js"></script></head><body><div id="dash-root">
{page}
</div><script>window.__fixtures = {json.dumps(fx)};</script></body></html>"""
open(os.path.join(HERE, "test.html"), "w").write(html)
print("wrote test/test.html", f"({sc or 'normal'})")
