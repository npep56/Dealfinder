#!/usr/bin/env python3
"""Turn watchlist.json + data/scans/*.json into dashboard data and a phone summary.

Outputs (in out/):
  items.json    one row per watched item with its current verdict
  history.json  one row per price observation, all scans
  runs.json     one row per scan run
  summary.txt   the push-notification text for the latest run

Verdicts are computed here, by fixed rules, so every run judges deals the same way:
  want     Deal  : price <= target_price (or < regular_price when no target)
           Close : within want_close_margin (10%) of the target
  grocery  Deal  : unit price >= grocery_deal_pct (15%) below the baseline
           Close : >= grocery_close_pct (5%) below the baseline
           baseline = typical_unit_price, else the median regular unit price seen,
           else the scanner's own "assessment" field is used.
A scan observation may set "assessment" ("deal" | "close" | "none") to override when
no baseline exists. Expired observations (ends < scan date) are ignored.

Usage: python3 scripts/build.py [--check]   (--check validates only, writes nothing)
"""
import json
import statistics
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "out"
STATUS_RANK = {"Deal": 0, "Close": 1, "Watching": 2, "No price yet": 3}


def fail(msg):
    sys.exit(f"build.py: {msg}")


def load():
    wl = json.loads((ROOT / "watchlist.json").read_text())
    items = {i["id"]: i for i in wl["items"]}
    scans = []
    for p in sorted((ROOT / "data" / "scans").glob("*.json")):
        s = json.loads(p.read_text())
        try:
            date.fromisoformat(s["date"])
        except Exception:
            fail(f"{p.name}: bad or missing date")
        for o in s.get("observations", []):
            if o.get("item") not in items:
                fail(f"{p.name}: unknown item id {o.get('item')!r}")
            if not isinstance(o.get("price"), (int, float)) or o["price"] <= 0:
                fail(f"{p.name}: {o['item']} needs a positive numeric price")
            if items[o["item"]]["kind"] == "grocery" and not o.get("size"):
                fail(f"{p.name}: {o['item']} is a grocery item; give size (in {items[o['item']]['unit']})")
            if o.get("assessment") not in (None, "deal", "close", "none"):
                fail(f"{p.name}: {o['item']} assessment must be deal, close or none")
        scans.append(s)
    # Several runs on one day (e.g. Black Friday extras) sort by date then run name.
    scans.sort(key=lambda s: (s["date"], s.get("time", ""), s.get("run", "")))
    return wl["settings"], items, scans


def unit_price(o):
    return round(o["price"] / (o.get("size") or 1), 4)


def judge(item, obs, settings, regular_unit_prices):
    """Return (status, pct_off, compare_to) for one observation."""
    up = unit_price(obs)
    if item["kind"] == "want":
        regular = obs.get("regular_price") or item.get("regular_price")
        target = item.get("target_price")
        pct = round(1 - obs["price"] / regular, 3) if regular else None
        if target:
            if obs["price"] <= target:
                return "Deal", pct, target
            if obs["price"] <= target * (1 + settings["want_close_margin"]):
                return "Close", pct, target
            return "Watching", pct, target
        if regular and obs["price"] < regular * 0.98:
            return "Deal", pct, regular
        return ("Deal" if obs.get("assessment") == "deal" else "Watching"), pct, regular

    baseline = item.get("typical_unit_price")
    if not baseline and obs.get("regular_price"):
        baseline = obs["regular_price"] / (obs.get("size") or 1)
    if not baseline and regular_unit_prices:
        baseline = statistics.median(regular_unit_prices)
    if baseline:
        pct = round(1 - up / baseline, 3)
        if pct >= settings["grocery_deal_pct"]:
            return "Deal", pct, round(baseline, 4)
        if pct >= settings["grocery_close_pct"]:
            return "Close", pct, round(baseline, 4)
        if obs.get("assessment") in ("deal", "close"):
            return obs["assessment"].title(), pct, round(baseline, 4)
        return "Watching", pct, round(baseline, 4)
    a = obs.get("assessment")
    return {"deal": "Deal", "close": "Close"}.get(a, "Watching"), None, None


def build(settings, items, scans):
    history, latest_by_item, regulars = [], {}, {}
    for s in scans:
        for o in s.get("observations", []):
            if o.get("regular_price") and o.get("size"):
                regulars.setdefault(o["item"], []).append(o["regular_price"] / o["size"])
    for s in scans:
        seen_this_run = {}
        for o in s.get("observations", []):
            if o.get("ends") and o["ends"] < s["date"]:
                continue
            if o.get("in_stock") is False:
                continue
            item = items[o["item"]]
            status, pct, compare = judge(item, o, settings, regulars.get(o["item"], []))
            row = {
                "date": s["date"],
                "item": o["item"],
                "name": item["name"],
                "store": o["store"],
                "price": o["price"],
                "unit_price": unit_price(o),
                "unit": item["unit"],
                "status": status,
            }
            history.append(row)
            seen_this_run.setdefault(o["item"], []).append((o, status, pct, compare))
        for k, v in seen_this_run.items():
            latest_by_item[k] = (s["date"], v)

    rows = []
    for item in items.values():
        base = {
            "id": item["id"],
            "name": item["name"],
            "variant": item.get("variant", ""),
            "kind": "Want" if item["kind"] == "want" else "Grocery",
            "unit": item["unit"],
            "stores": ", ".join(item.get("stores", [])),
            "target": item.get("target_price"),
            "target_reason": item.get("target_reason", ""),
            "status": "No price yet",
            "status_rank": 3,
            "price": None, "unit_price": None, "store": "", "url": "",
            "pct_off": None, "compare_to": None, "ends": "", "code": "",
            "final_sale": False, "note": "", "last_seen": "",
            "lowest_unit_price": None, "observations": 0,
        }
        past = [h for h in history if h["item"] == item["id"]]
        if past:
            base["lowest_unit_price"] = min(h["unit_price"] for h in past)
            base["observations"] = len(past)
        if item["id"] in latest_by_item:
            day, obs = latest_by_item[item["id"]]
            # Best = best status first, then cheapest per unit.
            o, status, pct, compare = min(obs, key=lambda t: (STATUS_RANK[t[1]], unit_price(t[0])))
            base.update({
                "status": status, "status_rank": STATUS_RANK[status],
                "price": o["price"], "unit_price": unit_price(o), "store": o["store"],
                "url": o.get("url", ""), "pct_off": pct, "compare_to": compare,
                "ends": o.get("ends") or "", "code": o.get("code") or "",
                "final_sale": bool(o.get("final_sale")), "note": o.get("note", ""),
                "last_seen": day,
            })
        # A deal not re-seen in the last few scans days is no longer shown as a deal.
        if scans and base["status"] in ("Deal", "Close") and base["last_seen"]:
            age = (date.fromisoformat(scans[-1]["date"]) - date.fromisoformat(base["last_seen"])).days
            if age > settings.get("deal_stale_days", 3):
                base["status"], base["status_rank"] = "Watching", STATUS_RANK["Watching"]
                base["note"] = f"Not seen in the last {age} days. " + base["note"]
        rows.append(base)
    rows.sort(key=lambda r: (r["status_rank"], -(r["pct_off"] or 0), r["name"]))

    runs = []
    for s in scans:
        statuses = [h["status"] for h in history if h["date"] == s["date"]]
        srcs = s.get("sources", [])
        runs.append({
            "date": s["date"],
            "run": s.get("run", "daily"),
            "headline": s.get("headline", ""),
            "deals": statuses.count("Deal"),
            "close": statuses.count("Close"),
            "prices_checked": len(statuses),
            "sources_ok": sum(1 for x in srcs if x.get("ok")),
            "sources_failed": ", ".join(x["name"] for x in srcs if not x.get("ok")),
            "notes": " • ".join(s.get("notes", [])),
            "gaps": " • ".join(s.get("gaps", [])),
        })
    runs.sort(key=lambda r: r["date"], reverse=True)
    return rows, history, runs


def money(v):
    return f"${v:,.2f}".replace(".00", "")


def summary(settings, rows, scans):
    latest = scans[-1]["date"] if scans else "never"
    fresh = [r for r in rows if r["last_seen"] == latest]
    deals = [r for r in fresh if r["status"] == "Deal"]
    close = [r for r in fresh if r["status"] == "Close"]
    lines = []
    if deals:
        lines.append(f"{len(deals)} deal{'s' if len(deals) > 1 else ''} today:")
        for r in deals[:5]:
            bits = [f"{r['name']} {money(r['price'])} at {r['store']}"]
            if r["pct_off"]:
                bits.append(f"{round(r['pct_off'] * 100)}% off")
            if r["unit"] != "item" and r["unit_price"]:
                bits.append(f"{money(r['unit_price'])}/{r['unit']}")
            if r["code"]:
                bits.append(f"code {r['code']}")
            if r["ends"]:
                bits.append(f"ends {r['ends'][5:].replace('-', '/')}")
            lines.append("• " + ", ".join(bits))
    else:
        lines.append("No notable deals today.")
        if close:
            lines.append("Closest: " + "; ".join(f"{r['name']} {money(r['price'])} at {r['store']}" for r in close[:2]))
    lines.append(settings["dashboard_url"])
    return "\n".join(lines)


def main():
    settings, items, scans = load()
    rows, history, runs = build(settings, items, scans)
    if "--check" in sys.argv:
        print(f"OK: {len(items)} items, {len(scans)} scans, {len(history)} observations")
        return
    OUT.mkdir(exist_ok=True)
    for name, data in (("items", rows), ("history", history), ("runs", runs)):
        (OUT / f"{name}.json").write_text(json.dumps(data, indent=1, ensure_ascii=False))
    text = summary(settings, rows, scans)
    (OUT / "summary.txt").write_text(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
