# Deal scan procedure

This file is the playbook for every scheduled deal scan (daily 8:44am ET, plus the
Black Friday extra scans). The scheduled task's prompt only says *which* scan to run;
everything about *how* lives here, so improving the scan means editing this file.

What to watch lives in `watchlist.json`. Each run's findings go in
`data/scans/YYYY-MM-DD.json`. `scripts/build.py` turns them into verdicts, the
dashboard data and the notification text, so deals are judged by fixed rules
instead of by feel.

## 1. Gather prices

Search the web (including slickdeals.net) for current sales, price drops, coupons,
digital coupons and promo codes on every item in `watchlist.json`, at the stores
listed for it. Also check Walmart for every item Walmart carries (except store brands
sold elsewhere).

Read pages with WebFetch and WebSearch, not curl: direct downloads from Bash are
blocked for most retail sites. Use subagents in parallel where available (e.g. one for Kroger/Publix ads, one for
Costco, one for the "want" items, one for Amazon/Target/Slickdeals groceries).

### Weekly ad sources (Kroger & Publix)
- kroger.com and publix.com weekly ads load prices with JavaScript and can't be read.
  Read Southern Savers' item-by-item weekly ad posts instead (ad prices, digital
  coupons, Ibotta).
- Start at https://www.southernsavers.com/ and find the CURRENT "Kroger Weekly Ad" and
  "Publix Weekly Ad" posts (Kroger Wed–Tue; Publix Wed–Tue or Thu–Wed). URL patterns:
  `southernsavers.com/kroger-weekly-ad-M-D-M-D/` and
  `southernsavers.com/publix-weekly-ad-M-D-M-D-or-M-D-M-D/`. Confirm the date range
  covers today and the year is right — old posts share similar URLs.
- Also check Southern Savers' Kroger/Publix unadvertised-deals posts if current.
- walmart.com blocks automated fetching — don't work around it. For Walmart, use only
  what shows in search results or real Slickdeals posts.

### Rules
- Match the exact product, variant and size (Califia Cold Brew is not Toasted Coconut;
  Chomplings minis are not Original 1.15 oz sticks).
- Only record prices you can see on a retailer page, a store weekly ad (including the
  Southern Savers posts), the Costco savings book, or a real Slickdeals post. Ignore
  coupon-aggregator sites with unverified codes.
- Student discount: for non-grocery items the target prices in `watchlist.json` already
  account for it. Wolaco and Dyson have no verified student rate (see their notes).
- Check that a Slickdeals post is recent and not marked expired before using it.

## 2. Record the run

Write `data/scans/<today>.json` (America/New_York date). For an extra run on a day that
already has a file, use `data/scans/<today>-<run>.json` (e.g. `2026-11-27-noon.json`)
and set `"run"` and `"time"`.

Record an observation for **every item you found a current price for, deal or not** —
full-price sightings are what the dashboard uses to learn normal prices and show how
close each item is to its target.

```json
{
  "date": "2026-11-09",
  "run": "daily",                 // or "black-friday-noon", etc.
  "time": "08:50",                // optional, local time
  "headline": "One short sentence on the run.",
  "sources": [
    {"name": "Southern Savers: Kroger weekly ad", "covers": "11/11–11/17", "url": "…", "ok": true}
  ],
  "observations": [
    {
      "item": "kerrygold-butter",   // id from watchlist.json (build fails on unknown ids)
      "store": "Kroger",
      "price": 3.99,                // what you pay for the package, after required coupons
      "size": 8,                    // REQUIRED for groceries, in the item's unit (oz / bar / stick)
      "regular_price": 4.99,        // package regular price if shown; null if unknown
      "url": "https://…",
      "ends": "2026-11-17",         // if known
      "code": "",                   // coupon/promo code or "digital coupon" / "Ibotta $1"
      "final_sale": false,
      "in_stock": true,             // false = sold out in the wanted variant/size (skipped)
      "assessment": "close",        // optional: deal | close | none — used only when no
                                    // baseline price is known (no regular_price yet)
      "note": "Short context, e.g. 'Costco is cheaper per oz'."
    }
  ],
  "notes": ["Near-misses or mismatches worth knowing (wrong variant on sale, expired post)."],
  "gaps": ["Sources that failed or couldn't be fully read."]
}
```

When you learn an item's normal price with confidence, you may set
`typical_unit_price` (per oz/bar/stick) or `regular_price` in `watchlist.json`.

## 3. Build, publish, save, notify

1. `python3 scripts/build.py` — validates the scan and writes `out/items.json`,
   `out/history.json`, `out/runs.json` and `out/summary.txt`. Fix any error it reports.
2. Update the dashboard (`settings.dashboard_url` in `watchlist.json`):
   - Upload each of the three JSON files with the Artifact tool, one call each:
     `action: publish, url: <dashboard_url>, asset: true, file_path: out/<name>.json`.
     Keep each returned `url` (`/_blob/…`).
   - With ArtifactData, `get` `datasets/items`, `datasets/history`, `datasets/runs` to
     read their versions, then one `batch` of three `update` writes (each with its
     `if_version`) setting:
     `source: {kind: "file", url: <returned url>, name: "<name>.json", format: "json"}`,
     `updated: {at: <UTC ISO now>, by: "Daily deal scan"}`,
     `edit: {via: "claude", at: <UTC ISO now>}`.
   - Do not change the dashboard page or anything else in it.
3. Save the scan file (and any `watchlist.json` change) to GitHub with the GitHub
   connector's `create_or_update_file`: owner `npep56`, repo `Dealfinder`, branch
   `claude/deal-checks-interface-rz1xgl`, message `Deal scan <date>`. For a file that
   already exists, first read its `sha` with `get_file_contents` and pass it. Don't use
   `git push`: scheduled sessions can't push to this branch.
4. Send one PushNotification with the text of `out/summary.txt` (it already ends with the
   dashboard link). Final reply: the same summary plus any gaps.

If the dashboard or git step fails, still send the notification and say in one line
what failed.
