# Deal scan procedure

This file is the playbook for every scheduled deal scan (daily 8:44am ET, plus the
Black Friday extra scans). The scheduled task's prompt only says *which* scan to run;
everything about *how* lives here, so improving the scan means editing this file.

What to watch lives in `watchlist.json`. Each run's findings go in
`data/scans/YYYY-MM-DD.json`. `scripts/build.py` turns them into verdicts, the
dashboard data and the notification text, so deals are judged by fixed rules
instead of by feel.

## 1. Gather prices

### Start with the structured sources

Run `python3 scripts/fetch_sources.py` first (about 5 seconds). It reads the sources
listed under each item's `"sources"` in `watchlist.json` and writes `out/sources.json`:

- `observations`: exact prices and stock from the store's own product feed (Rothy's,
  Wolaco, FitcamX, Janji, ALOHA, Chomps), shelf and sale prices from the Kroger nearest
  `settings.postal_code` (Kroger API), and regular, sale and Prime prices at the Whole
  Foods in `settings.wholefoods_store`. Copy them into the scan file as they are.
- `leads`: this week's printed store ads from Flipp (Kroger, Publix, Target, Walmart,
  Walgreens and more, for `settings.postal_code`) and Slickdeals posts from the last two
  weeks. Each lead is a hint, not a price: open it and confirm the exact product, size
  and price before recording an observation (e.g. "Just Bare Chicken Breast Fillets" is
  not the Lightly Breaded Chunks). Note leads that don't match in `notes`.
- `errors`: sources that failed. Fill those in by hand below and list them in `gaps`.

Then use web search only for what the sources don't cover: Dyson, Costco (beyond its
Flipp ad), Amazon, items with no lead, and stores an item lists that the sources skipped. Kroger
digital coupons are not in the Kroger API; Southern Savers' Kroger post still lists them.

### Search the web

Search the web (including slickdeals.net) for current sales, price drops, coupons,
digital coupons and promo codes on every item in `watchlist.json`, at the stores
listed for it. Also check Walmart for every item Walmart carries (except store brands
sold elsewhere).

Read pages with WebFetch and WebSearch rather than curl: direct downloads from Bash
may be blocked. Open the actual retailer pages and Southern Savers posts; a search
snippet alone is not enough to record a price unless the page can't be read (say so in
the note). Use subagents in parallel where available (e.g. one for Kroger/Publix ads, one for
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

### Costco savings book (monthly)
Costco's monthly savings ("coupon") book runs about 4–5 weeks (e.g. Nov 16 – Dec 20,
2026) and is posted about a week before it starts. Read each book once and keep what
it says in `data/costco-books/<valid_from>.json`. Daily scans reuse that file.

1. **Each run:** if a file in `data/costco-books/` covers today, record an observation
   for each of its `matches` (store "Costco", `ends` = `valid_to`, `code` "Costco
   savings book", note "from the savings book, read <read_on>"). When the book prints only
   "$X off", set `price` to Costco's last known regular price minus X,
   `regular_price` to that regular price, and say in the note that the price is worked
   out from the discount. If no regular price is known, don't record an observation
   (the build needs a price); put the discount in `notes` instead.
2. **When to look for a new book:** if no file covers the next 10 days, look for the
   next book. Search the web (`Costco coupon book <Month> <year>`) for its dates, then
   find the Slickdeals post for it, titled like "Costco Coupon Book - Nov 16 - Dec 20, 2026".
   Costco97, CostcoInsider, Costrefund, Costcoguides, Krazy Coupon Lady and
   daily.slickdeals.net can't be reached from this environment. The Slickdeals post can.
3. **Reading the book:** the Slickdeals post holds the pages as image attachments.
   Download them with Bash (`curl -sSL -A "Mozilla/5.0"` on the post, collect every
   `attachment.php?attachmentid=…&d=…` link, download each as `https://slickdeals.net/<link>`,
   and save them in the scratchpad with a `.png` name). Read them with a subagent so the images stay
   out of the main context. Ask it for: the printed dates, how complete the pages look,
   and every watchlist item (exact name, size, $ off, printed price, limit,
   warehouse/online), plus close relatives as near-misses. Check each match against its
   page image yourself before saving it.
4. **Saving:** write `data/costco-books/<valid_from>.json` with `valid_from`, `valid_to`,
   `source`, `read_on`, `coverage`, `matches`, `not_found` and `near_misses` (see the
   2026-11-16 file). If the screenshots look incomplete, say so in `coverage`, and look
   again on later runs for a fuller set. Commit it with the scan.
5. Costco also runs separate holiday events (e.g. Holiday Savings, Oct 30 – Nov 30, in
   several windows). Check Slickdeals for posts on them during November.

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

Write `data/scans/<today>.json` (America/New_York date). An extra run on a day that
already has a file goes in `data/scans/<today>-<run>-<HHMM>.json` (e.g.
`2026-11-27-bf-1244.json`) with `"run"` and `"time"` set; when a day has several runs
with the same `run` name, each needs its own `time`.

Record an observation for **every item you found a current price for, deal or not** —
full-price sightings are what the dashboard uses to learn normal prices and show how
close each item is to its target.

The comments below explain each field; the real file is plain JSON without them.

```jsonc
{
  "date": "2026-11-09",
  "run": "daily",                 // or "black-friday"
  "time": "08:50",                // local time, HH:MM
  "headline": "One short sentence on the run.",
  "sources": [
    {"name": "Southern Savers: Kroger weekly ad", "covers": "11/11–11/17", "url": "…", "ok": true}
  ],
  "observations": [
    {
      "item": "kerrygold-butter",   // id from watchlist.json (build fails on unknown ids)
      "store": "Kroger",
      "price": 3.99,                // what you pay for the package, after required coupons
      "size": 8,                    // REQUIRED for groceries, in the item's unit (oz / lb / bar / stick)
      "regular_price": 4.99,        // package regular price if shown; null if unknown
      "url": "https://…",
      "ends": "2026-11-17",         // if known
      "code": "",                   // coupon/promo code or "digital coupon" / "Ibotta $1"
      "final_sale": false,
      "in_stock": true,             // false = sold out in the wanted variant/size (skipped)
      "assessment": "close",        // optional: deal | close | none. Decides when no target
                                    // or normal price is known; for groceries "deal" or
                                    // "close" also flags a deal the numbers can't show (BOGO)
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
   - Do not delete the old files or change the dashboard page or anything else in it.
     (Deletes need a person's approval and would stall an unattended run.)
3. Commit `data/scans/…` (and any `watchlist.json` change) with message
   `Deal scan <date>` on top of `claude/deal-checks-interface-rz1xgl` (the branch that
   holds every scan) and push it there:
   `git push origin HEAD:claude/deal-checks-interface-rz1xgl`. If that push is refused,
   push to the branch the session started on instead and say which branch in the
   notification.
4. Send one PushNotification with the text of `out/summary.txt` (it already ends with the
   dashboard link). Final reply: the same summary plus any gaps.

If the dashboard or git step fails, still send the notification and say in one line
what failed.
