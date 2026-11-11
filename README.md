# Dealfinder

Daily deal checks for a personal watchlist, with a dashboard instead of a wall of text.

- **Dashboard:** https://claude.ai/artifact/E4gmQ9GaoJxnwuKJBM5qW7 shows every item's
  status (Deal, Close, Watching, No price yet), the best price found, its target, price
  history and a log of each scan.
- `watchlist.json` lists what to watch: items, stores, target prices and units, plus
  the deal thresholds under `settings`.
- `SCAN.md` is the playbook the scheduled scans follow.
- `data/scans/` holds one JSON file per scan run; together they are the price history.
- `scripts/build.py` judges deals by fixed rules and builds the dashboard data and the
  push-notification text.

All scans live on the `claude/deal-checks-interface-rz1xgl` branch.

## Commands

```sh
python3 scripts/fetch_sources.py    # exact store prices, weekly-ad and Slickdeals leads
python3 scripts/build.py            # build out/ and print the notification text
python3 scripts/build.py --check    # validate watchlist and scans only
python3 -m unittest discover scripts
```

## Changing the watchlist

Ask Claude ("add Hoka Clifton 10, size 10.5, alert under $110") or edit `watchlist.json`
directly. Each item needs a unique `id`, a `kind` (`want` or `grocery`) and a `unit`
(`item`, `oz`, `bar` or `stick`). Wants take a `target_price`, or `null` for "any real
sale". Groceries are compared per unit.

## Where prices come from

Each item's `sources` in `watchlist.json` say where to look first:

- **Store product feeds** (`shopify`): Rothy's, Wolaco, FitcamX, Janji, ALOHA and Chomps
  publish exact prices and stock for every size and color.
- **Flipp** (`flipp`): this week's printed ads for Kroger, Publix, Target, Walmart and
  more near `settings.postal_code`.
- **Slickdeals** (`slickdeals`): posts from the last two weeks.
- **Kroger API** (`kroger`): shelf and sale prices at the nearest Kroger. Needs the
  `KROGER_CLIENT_ID` and `KROGER_CLIENT_SECRET` environment variables (a free app at
  developer.kroger.com); without them this source is skipped.

- **Whole Foods** (`wholefoods`): regular, sale and Prime member prices at the store in
  `settings.wholefoods_store` (Kennesaw), from the Whole Foods website's product search.
  Set `settings.prime_member` to `true` to count Prime prices.

Flipp also carries Costco's monthly savings book and Walmart's and Best Buy's ads. The
scan then searches the web for whatever is left (Dyson, Amazon, Walmart online prices).

## How deals are judged

| Kind | Deal | Close |
|---|---|---|
| Want | price at or under target (or below regular when there is no target) | within 10% of target |
| Grocery | at least 15% below the normal unit price | at least 5% below |

The normal grocery price comes from `typical_unit_price`, else the regular price seen on
the shelf, else the median regular price from past scans. A Deal or Close that isn't seen
again within 3 days drops back to Watching.
