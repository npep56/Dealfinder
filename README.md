# Dealfinder

Daily deal checks for a personal watchlist, with a dashboard instead of a wall of text.

- **Dashboard:** https://claude.ai/artifact/E4gmQ9GaoJxnwuKJBM5qW7 — every item's status
  (Deal / Close / Watching / No price yet), best price found, target, price history and
  the log of each scan.
- `watchlist.json` — what to watch: items, stores, target prices, units.
- `SCAN.md` — the scan playbook the scheduled tasks follow.
- `data/scans/` — one JSON file per scan run (the price history).
- `scripts/build.py` — judges deals by fixed rules and builds the dashboard data and the
  push-notification text (`python3 scripts/build.py`, or `--check` to validate only).

## Changing the watchlist

Ask Claude ("add Hoka Clifton 10, size 10.5, alert under $110") or edit `watchlist.json`
directly. Wants need `target_price` (or `null` for "any real sale"); groceries need a
`unit` (oz, bar, stick) so prices compare per unit.

## How deals are judged

| Kind | Deal | Close |
|---|---|---|
| Want | price ≤ target (or below regular when there is no target) | within 10% of target |
| Grocery | ≥ 15% below normal unit price | ≥ 5% below |

Normal grocery price comes from `typical_unit_price`, else the regular price seen in
past scans. Thresholds live in `watchlist.json` → `settings`.
