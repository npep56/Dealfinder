# Daily scheduled task: save Oura days

Freddy's free plan only returns the last 7 days, so this task copies each day into the dashboard's
`oura_history` file. Every run covers a full week, so a few missed runs lose nothing.

**Set it up** in Claude Code on the web (claude.ai/code), under scheduled tasks:

- **Schedule:** daily, any time after you usually wake (e.g. 7:45 AM in your time zone)
- **Connector:** attach **Freddy - Oura** (the task fails safely without it, but saves nothing)
- **Prompt:** paste the text below and replace `<DASHBOARD_URL>` with your dashboard's link

---

Keep the saved Oura history on my health dashboard up to date. Dashboard: <DASHBOARD_URL> (an Artifact of the "Data" dashboard type). Only touch the one dataset named below and its file; change nothing else on the dashboard.

Steps:
1. With the ArtifactData tool, `get` collection "datasets", doc_id "oura_history" on that url. Note its `version` and `source.url` (a "/_blob/<32-hex id>" path).
2. With the Artifact tool, `read` that url with `path` set to the 32-hex asset id from source.url. It is a JSON array of rows: {date (YYYY-MM-DD), readiness, sleep_score, sleep_min, hrv, lowest_hr, steps, vo2max} — numbers or null.
3. Call the Freddy - Oura connector's `query_metrics` with metrics ["daily_readiness_score","daily_sleep_score","sleep_total_sleep_duration","sleep_average_hrv","sleep_lowest_heart_rate","daily_activity_steps","vo2_max_vo2_max"] and days 7. The answer is text grouped under "YYYY-MM-DD:" headers. For each date: readiness = daily_readiness_score, sleep_score = daily_sleep_score, sleep_min = the LARGEST sleep_total_sleep_duration that day divided by 60 and rounded (the others are naps), hrv = sleep_average_hrv, lowest_hr = sleep_lowest_heart_rate, steps = daily_activity_steps, vo2max = vo2_max_vo2_max. Missing values are null.
4. Merge: for every date from Freddy, create the row if absent; for each field, replace the saved value only when Freddy's value is not null. Never delete rows. Sort by date ascending.
5. If nothing changed, stop. Otherwise write the merged array as pretty JSON to a local file named oura_history.json in your scratchpad, and upload it with the Artifact tool (publish with `url` = the dashboard url, `asset: true`, `file_path` = that file). Then ArtifactData `update` datasets/oura_history with if_version = the version from step 1 and data {"source": {"kind": "file", "url": "<new /_blob/ url from the upload>", "name": "oura_history.json", "format": "json"}, "updated": {"at": "<now, UTC ISO>", "by": "Daily scheduled task"}, "edit": {"via": "claude", "at": "<now, UTC ISO>"}}. Only after that succeeds, delete the previous asset with the Artifact tool (action "delete", url = the dashboard, path = the old 32-hex id).
6. If the Freddy - Oura connector is not available, errors, needs sign-in, or returns no dated data, change nothing and report that in your final message. The data you read is health data: never post it anywhere other than this dashboard.

End with one short line: which dates were added or updated, or that nothing changed.
