#!/usr/bin/env python3
"""Turn watchlist.json and data/scans/*.json into dashboard data and a phone summary.

Writes to out/:
  items.json    one row per watched item, with its current verdict
  history.json  one row per price sighting, across all scans
  runs.json     one row per scan run, newest first
  summary.txt   the push-notification text for the latest run

Every run judges deals by the same fixed rules (thresholds live in watchlist.json):
  want     Deal  : price <= target_price, or below regular price when there is no target
           Close : within want_close_margin of the target
  grocery  Deal  : unit price at least grocery_deal_pct below the normal unit price
           Close : at least grocery_close_pct below it
           normal = typical_unit_price, else this sighting's regular price, else the
           median regular unit price seen in past scans.
When no target or normal price is known, the scan's own "assessment" decides.
Sightings that are sold out (in_stock false) or expired (ends before the scan date) are
skipped. A Deal or Close not seen again within deal_stale_days drops to Watching.

Usage: python3 scripts/build.py [--check]    --check validates the data and writes nothing
"""
import json
import statistics
import sys
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "out"

STATUSES = ("Deal", "Close", "Watching", "No price yet")
RANK = {status: i for i, status in enumerate(STATUSES)}
ASSESSMENT_STATUS = {"deal": "Deal", "close": "Close", "none": "Watching"}
KINDS = ("want", "grocery")


class DataError(Exception):
    """A watchlist or scan file that breaks the format described in SCAN.md."""


# ---------------------------------------------------------------- loading


def is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def parse_day(value, where):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise DataError(f"{where}: {value!r} is not a YYYY-MM-DD date") from None


def load_watchlist(path):
    data = json.loads(path.read_text())
    settings, items = data["settings"], {}
    for item in data["items"]:
        where = f"watchlist.json: {item.get('id')!r}"
        if item.get("id") in items:
            raise DataError(f"{where}: duplicate item id")
        if item.get("kind") not in KINDS:
            raise DataError(f"{where}: kind must be one of {', '.join(KINDS)}")
        if not item.get("unit"):
            raise DataError(f"{where}: needs a unit (item, oz, bar, stick)")
        items[item["id"]] = item
    return settings, items


def check_observation(o, items, where):
    item = items.get(o.get("item"))
    if item is None:
        raise DataError(f"{where}: unknown item id {o.get('item')!r}")
    where = f"{where}: {o['item']}"
    if not o.get("store"):
        raise DataError(f"{where}: needs a store")
    if not is_number(o.get("price")) or o["price"] <= 0:
        raise DataError(f"{where}: price must be a positive number")
    if item["kind"] == "grocery" and not (is_number(o.get("size")) and o["size"] > 0):
        raise DataError(f"{where}: grocery sightings need a positive size in {item['unit']}")
    if o.get("regular_price") is not None and not (is_number(o["regular_price"]) and o["regular_price"] > 0):
        raise DataError(f"{where}: regular_price must be a positive number or null")
    if o.get("assessment") not in (None, *ASSESSMENT_STATUS):
        raise DataError(f"{where}: assessment must be deal, close or none")
    if o.get("ends"):
        parse_day(o["ends"], f"{where} ends")


def load_scans(folder, items):
    scans = []
    for path in sorted(folder.glob("*.json")):
        scan = json.loads(path.read_text())
        parse_day(scan.get("date"), path.name)
        scan.setdefault("run", "daily")
        for o in scan.get("observations", []):
            check_observation(o, items, path.name)
        scans.append(scan)
    scans.sort(key=lambda s: (s["date"], s.get("time", ""), s["run"]))

    # Label each run so (date, run) is unique even with several runs a day.
    same_day = Counter((s["date"], s["run"]) for s in scans)
    labels = set()
    for s in scans:
        label = s["run"]
        if same_day[(s["date"], label)] > 1:
            if not s.get("time"):
                raise DataError(f"{s['date']}: several '{label}' runs; give each a time")
            label = f"{label} {s['time']}"
        if (s["date"], label) in labels:
            raise DataError(f"{s['date']}: two scans are both labelled '{label}'")
        labels.add((s["date"], label))
        s["label"] = label
    return scans


# ---------------------------------------------------------------- judging


def unit_price(o):
    return round(o["price"] / (o.get("size") or 1), 4)


def regular_unit_price(o):
    return o["regular_price"] / (o.get("size") or 1) if o.get("regular_price") else None


def from_assessment(o):
    return ASSESSMENT_STATUS.get(o.get("assessment"), "Watching")


def judge_want(item, o, settings):
    """Return (status, pct_off, compared_to) for a one-time purchase."""
    regular = o.get("regular_price") or item.get("regular_price")
    pct = round(1 - o["price"] / regular, 3) if regular else None
    target = item.get("target_price")
    if target:
        if o["price"] <= target:
            return "Deal", pct, target
        if o["price"] <= target * (1 + settings["want_close_margin"]):
            return "Close", pct, target
        return "Watching", pct, target
    if regular:
        # No target: any real sale below the regular price counts (2% guards rounding).
        return ("Deal" if o["price"] < regular * 0.98 else "Watching"), pct, regular
    return from_assessment(o), None, None


def judge_grocery(item, o, settings, past_regulars):
    """Return (status, pct_off, compared_to) for a regular grocery purchase."""
    normal = item.get("typical_unit_price") or regular_unit_price(o)
    if not normal and past_regulars:
        normal = statistics.median(past_regulars)
    if not normal:
        return from_assessment(o), None, None
    pct = round(1 - unit_price(o) / normal, 3)
    if pct >= settings["grocery_deal_pct"]:
        status = "Deal"
    elif pct >= settings["grocery_close_pct"]:
        status = "Close"
    else:
        # The scan may still have spotted a deal the numbers can't show (e.g. a BOGO).
        status = from_assessment(o) if o.get("assessment") in ("deal", "close") else "Watching"
    return status, pct, round(normal, 4)


def judge(item, o, settings, past_regulars):
    if item["kind"] == "want":
        return judge_want(item, o, settings)
    return judge_grocery(item, o, settings, past_regulars)


# ---------------------------------------------------------------- building


def blank_row(item):
    return {
        "id": item["id"],
        "name": item["name"],
        "variant": item.get("variant", ""),
        "kind": "Want" if item["kind"] == "want" else "Grocery",
        "unit": item["unit"],
        "stores": ", ".join(item.get("stores", [])),
        "target": item.get("target_price"),
        "target_reason": item.get("target_reason", ""),
        "status": "No price yet",
        "status_rank": RANK["No price yet"],
        "price": None,
        "unit_price": None,
        "store": "",
        "url": "",
        "pct_off": None,
        "compare_to": None,
        "ends": "",
        "code": "",
        "final_sale": False,
        "note": "",
        "last_seen": "",
        "lowest_unit_price": None,
        "observations": 0,
    }


def usable(o, scan):
    return o.get("in_stock") is not False and not (o.get("ends") and o["ends"] < scan["date"])


def build(settings, items, scans):
    regulars = {}
    for s in scans:
        for o in s.get("observations", []):
            rup = regular_unit_price(o)
            if rup and items[o["item"]]["kind"] == "grocery":
                regulars.setdefault(o["item"], []).append(rup)

    history, latest = [], {}
    for s in scans:
        this_run = {}
        for o in s.get("observations", []):
            if not usable(o, s):
                continue
            item = items[o["item"]]
            status, pct, compare = judge(item, o, settings, regulars.get(o["item"], []))
            history.append({
                "date": s["date"],
                "run": s["label"],
                "item": o["item"],
                "name": item["name"],
                "store": o["store"],
                "price": o["price"],
                "unit_price": unit_price(o),
                "unit": item["unit"],
                "status": status,
            })
            this_run.setdefault(o["item"], []).append((o, status, pct, compare))
        for item_id, sightings in this_run.items():
            latest[item_id] = (s["date"], sightings)

    last_scan = date.fromisoformat(scans[-1]["date"]) if scans else None
    stale_days = settings.get("deal_stale_days", 3)
    rows = []
    for item in items.values():
        row = blank_row(item)
        past = [h["unit_price"] for h in history if h["item"] == item["id"]]
        if past:
            row["lowest_unit_price"] = min(past)
            row["observations"] = len(past)
        if item["id"] in latest:
            day, sightings = latest[item["id"]]
            # Best sighting: best status first, then cheapest per unit.
            o, status, pct, compare = min(sightings, key=lambda t: (RANK[t[1]], unit_price(t[0])))
            row.update({
                "status": status,
                "status_rank": RANK[status],
                "price": o["price"],
                "unit_price": unit_price(o),
                "store": o["store"],
                "url": o.get("url") or "",
                "pct_off": pct,
                "compare_to": compare,
                "ends": o.get("ends") or "",
                "code": o.get("code") or "",
                "final_sale": bool(o.get("final_sale")),
                "note": o.get("note") or "",
                "last_seen": day,
            })
            age = (last_scan - date.fromisoformat(day)).days
            if status in ("Deal", "Close") and age > stale_days:
                row["status"], row["status_rank"] = "Watching", RANK["Watching"]
                row["note"] = f"Not seen in the last {age} days. {row['note']}".strip()
        rows.append(row)
    rows.sort(key=lambda r: (r["status_rank"], -(r["pct_off"] or 0), r["name"]))

    runs = []
    for s in scans:
        statuses = [h["status"] for h in history if h["date"] == s["date"] and h["run"] == s["label"]]
        sources = s.get("sources", [])
        runs.append({
            "date": s["date"],
            "run": s["label"],
            "time": s.get("time", ""),
            "headline": s.get("headline", ""),
            "deals": statuses.count("Deal"),
            "close": statuses.count("Close"),
            "prices_checked": len(statuses),
            "sources_ok": sum(1 for x in sources if x.get("ok")),
            "sources_failed": ", ".join(x.get("name", "?") for x in sources if not x.get("ok")),
            "notes": " • ".join(s.get("notes", [])),
            "gaps": " • ".join(s.get("gaps", [])),
        })
    runs.reverse()  # newest first
    return rows, history, runs


# ---------------------------------------------------------------- summary


def money(v):
    return f"${v:,.0f}" if float(v).is_integer() else f"${v:,.2f}"


def unit_money(v):
    return f"${v:.3f}".rstrip("0").rstrip(".") if v < 1 else f"${v:.2f}"


def describe_deal(r):
    bits = [f"{r['name']} {money(r['price'])} at {r['store']}"]
    if r["pct_off"] and r["pct_off"] > 0:
        bits.append(f"{round(r['pct_off'] * 100)}% off")
    if r["unit"] != "item" and r["unit_price"]:
        bits.append(f"{unit_money(r['unit_price'])}/{r['unit']}")
    if r["code"]:
        bits.append(f"code {r['code']}")
    if r["ends"]:
        bits.append("ends " + date.fromisoformat(r["ends"]).strftime("%-m/%-d"))
    return "• " + ", ".join(bits)


def summary(settings, rows, scans):
    latest = scans[-1]["date"] if scans else None
    fresh = [r for r in rows if latest and r["last_seen"] == latest]
    deals = [r for r in fresh if r["status"] == "Deal"]
    close = [r for r in fresh if r["status"] == "Close"]
    if deals:
        lines = [f"{len(deals)} deal{'s' if len(deals) > 1 else ''} today:"]
        lines += [describe_deal(r) for r in deals[:5]]
    else:
        lines = ["No notable deals today."]
        if close:
            lines.append("Closest: " + "; ".join(
                f"{r['name']} {money(r['price'])} at {r['store']}" for r in close[:2]))
    lines.append(settings["dashboard_url"])
    return "\n".join(lines)


# ---------------------------------------------------------------- main


def main(argv):
    try:
        settings, items = load_watchlist(ROOT / "watchlist.json")
        scans = load_scans(ROOT / "data" / "scans", items)
    except (DataError, json.JSONDecodeError, KeyError) as e:
        sys.exit(f"build.py: {e}")
    rows, history, runs = build(settings, items, scans)
    if "--check" in argv:
        print(f"OK: {len(items)} items, {len(scans)} scans, {len(history)} sightings")
        return
    OUT.mkdir(exist_ok=True)
    for name, data in (("items", rows), ("history", history), ("runs", runs)):
        (OUT / f"{name}.json").write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
    text = summary(settings, rows, scans)
    (OUT / "summary.txt").write_text(text + "\n")
    print(text)


if __name__ == "__main__":
    main(sys.argv[1:])
