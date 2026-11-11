#!/usr/bin/env python3
"""Pull prices from structured sources before the web search part of a deal scan.

Each watchlist item can name its sources under "sources" in watchlist.json:

  "shopify":    {"store": "rothys.com", "handle": "womens-casual-clog-chestnut",
                 "variant": ["Chestnut", "10"], "size_from_variant": false}
                Exact price, compare-at price and stock for the matching variant, read
                from the store's own product feed. Each entry in "variant" must equal one
                of the variant's option values; "A|B" accepts either, "Front: 4K*" is a
                prefix match. With size_from_variant, the first number in the variant
                title is the pack size (e.g. "24 Pack").
  "flipp":      {"query": "kerrygold", "match": ["kerrygold"]}
                (Every source's "match" may be joined by "any": [...] (at least one, e.g.
                flavors) and "exclude": [...] (none of these words).)
                This week's printed store ads near settings.postal_code (Kroger, Publix,
                Target, Walmart and more). "match" words must all appear in the ad title.
  "slickdeals": "kerrygold butter"
                Slickdeals posts from the last settings.slickdeals_days days.
  "kroger":     {"term": "kerrygold butter", "match": ["kerrygold", "salted"], "size": 8}
                Shelf and sale price at the Kroger nearest settings.postal_code, from
                Kroger's API (needs KROGER_CLIENT_ID and KROGER_CLIENT_SECRET). "match"
                words must all appear in the brand and description; "size" keeps only
                that package size.

  "wholefoods": {"query": "kerrygold butter", "match": ["kerrygold", "salted"], "size": 8}
                Regular, sale and Prime member prices at settings.wholefoods_store, from the
                Whole Foods website's product search. The sale price is used, or the Prime
                price when settings.prime_member is true.

Shopify, Kroger and Whole Foods results are exact and become ready-made observations. Flipp and Slickdeals
results are leads: the scan still confirms the product, size and price.

Writes out/sources.json ({"observations", "leads", "errors"}) and prints a short report.
Usage: python3 scripts/fetch_sources.py [item-id ...]
"""
import base64
import json
import os
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "out"
UA = {"User-Agent": "Mozilla/5.0 (deal scan; personal use)"}


def get(url, timeout=25):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


# ---------------------------------------------------------------- shopify


def option_matches(wanted, value):
    value = value.strip().lower()
    for alt in wanted.split("|"):
        alt = alt.strip().lower()
        if alt.endswith("*") and value.startswith(alt[:-1]) or alt == value:
            return True
    return False


def variant_matches(wanted, values):
    return all(any(option_matches(w, v) for v in values) for w in wanted)


def shopify_variants(store, handle):
    """Return [(title, option_values, price, compare_at, available)] for a product."""
    base = f"https://{store}/products/{handle}"
    try:  # .js has stock; prices in cents
        p = json.loads(get(base + ".js"))
        return p["title"], [
            (v["title"], [v.get(f"option{i}") or "" for i in (1, 2, 3)], v["price"] / 100,
             (v.get("compare_at_price") or 0) / 100 or None, v.get("available"))
            for v in p["variants"]]
    except (ValueError, KeyError, OSError):
        p = json.loads(get(base + ".json"))["product"]  # no stock; prices as text
        return p["title"], [
            (v["title"], [v.get(f"option{i}") or "" for i in (1, 2, 3)], float(v["price"]),
             float(v["compare_at_price"]) if v.get("compare_at_price") else None, None)
            for v in p["variants"]]


def from_shopify(item, cfg, today):
    title, variants = shopify_variants(cfg["store"], cfg["handle"])
    url = f"https://{cfg['store']}/products/{cfg['handle']}"
    found = [v for v in variants if variant_matches(cfg.get("variant", []), v[1])]
    if not found:
        raise LookupError(f"no variant of '{title}' matches {cfg.get('variant')}")
    observations = []
    for vtitle, _, price, compare, available in found:
        o = {
            "item": item["id"],
            "store": cfg["store"],
            "price": price,
            # The watchlist's regular price wins: some stores show a permanent "compare-at".
            "regular_price": item.get("regular_price") or (compare if compare and compare > price else price),
            "url": url,
            "in_stock": available,
            "note": f"{title}: {vtitle} (store product feed, {today}).",
        }
        if compare and compare > price:
            o["note"] += f" Store shows compare-at ${compare:g}."
        if cfg.get("size_from_variant"):
            m = re.search(r"\d+", vtitle)
            o["size"] = int(m.group()) if m else 1
        if available is None:
            del o["in_stock"]
        observations.append(o)
    return observations


# ---------------------------------------------------------------- flipp


def from_flipp(item, cfg, postal_code, today):
    q = urllib.parse.urlencode({"locale": "en-us", "postal_code": postal_code, "q": cfg["query"]})
    data = json.loads(get(f"https://backflipp.wishabi.com/flipp/items/search?{q}"))
    leads = []
    for ad in data.get("items", []):
        name = ad.get("name") or ""
        if not matches(name, cfg):
            continue
        if (ad.get("valid_to") or "9999")[:10] < today:
            continue
        deal = " ".join(x for x in (ad.get("pre_price_text"), ad.get("current_price") and f"${ad['current_price']}",
                                    ad.get("post_price_text"), ad.get("sale_story")) if x)
        leads.append({
            "item": item["id"],
            "source": "Flipp weekly ad",
            "store": ad.get("merchant_name"),
            "title": name,
            "deal": deal or "in ad (price not listed)",
            "valid": f"{(ad.get('valid_from') or '')[:10]} to {(ad.get('valid_to') or '')[:10]}",
            "url": f"https://flipp.com/en-us/item/{ad.get('id')}",
        })
    return leads


# ---------------------------------------------------------------- slickdeals


def from_slickdeals(item, query, days, today):
    q = urllib.parse.urlencode({"mode": "frontpage", "searcharea": "deals", "searchin": "first", "rss": 1, "q": query})
    root = ET.fromstring(get(f"https://slickdeals.net/newsearch.php?{q}"))
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    leads = []
    for post in root.iter("item"):
        try:
            posted = parsedate_to_datetime(post.findtext("pubDate"))
        except (TypeError, ValueError):
            continue
        if posted < cutoff:
            continue
        leads.append({
            "item": item["id"],
            "source": "Slickdeals",
            "store": "",
            "title": post.findtext("title") or "",
            "deal": "",
            "valid": f"posted {posted.date()}",
            "url": post.findtext("link") or "",
        })
    return leads


# ---------------------------------------------------------------- kroger


class Kroger:
    """Kroger's public product API: shelf and sale price at the nearest Kroger store.

    Needs KROGER_CLIENT_ID and KROGER_CLIENT_SECRET (a free app at developer.kroger.com).
    """
    API = "https://api.kroger.com/v1"

    def __init__(self, postal_code):
        cid, secret = os.environ.get("KROGER_CLIENT_ID"), os.environ.get("KROGER_CLIENT_SECRET")
        if not (cid and secret):
            raise RuntimeError("KROGER_CLIENT_ID / KROGER_CLIENT_SECRET not set")
        basic = base64.b64encode(f"{cid}:{secret}".encode()).decode()
        req = urllib.request.Request(
            f"{self.API}/connect/oauth2/token", method="POST",
            data=b"grant_type=client_credentials&scope=product.compact",
            headers={**UA, "Authorization": f"Basic {basic}",
                     "Content-Type": "application/x-www-form-urlencoded"})
        with urllib.request.urlopen(req, timeout=25) as r:
            self.token = json.loads(r.read())["access_token"]
        stores = self.call("locations", {"filter.zipCode.near": postal_code, "filter.chain": "Kroger",
                                         "filter.limit": 1})["data"]
        if not stores:
            raise LookupError(f"no Kroger store near {postal_code}")
        s = stores[0]
        self.location_id = s["locationId"]
        self.store_name = f"Kroger ({s['address']['addressLine1']}, {s['address']['city']})"

    def call(self, path, params):
        req = urllib.request.Request(f"{self.API}/{path}?{urllib.parse.urlencode(params)}",
                                     headers={**UA, "Authorization": f"Bearer {self.token}"})
        with urllib.request.urlopen(req, timeout=25) as r:
            return json.loads(r.read())

    def search(self, term):
        return self.call("products", {"filter.term": term, "filter.locationId": self.location_id,
                                      "filter.limit": 20})["data"]


def has_words(text, words):
    """True when every word or phrase appears in text as a whole word ("salted" is not in "unsalted")."""
    return all(re.search(rf"(?<![\w']){re.escape(w.lower())}(?![\w'])", text.lower()) for w in words)


def matches(text, cfg):
    """A product title fits an item's source config: every "match" word, at least one of
    "any" (e.g. flavors) when given, and none of "exclude"."""
    return (has_words(text, cfg.get("match", []))
            and (not cfg.get("any") or any(has_words(text, [w]) for w in cfg["any"]))
            and not any(has_words(text, [w]) for w in cfg.get("exclude", [])))


def size_number(text):
    m = re.search(r"\d+(?:\.\d+)?", text or "")
    return float(m.group()) if m else None


def from_kroger(item, cfg, kroger, today):
    """Products whose description has every "match" word and a price at the store."""
    observations = []
    for p in kroger.search(cfg["term"]):
        text = f"{p.get('brand', '')} {p.get('description', '')}"
        if not matches(text, cfg):
            continue
        for it in p.get("items", []):
            price = it.get("price") or {}
            regular, promo = price.get("regular"), price.get("promo")
            if not regular:
                continue
            size = cfg.get("size") or size_number(it.get("size"))
            if cfg.get("size") and size_number(it.get("size")) not in (None, cfg["size"]):
                continue  # a different package size
            o = {
                "item": item["id"],
                "store": kroger.store_name,
                "price": promo if promo and 0 < promo < regular else regular,
                "regular_price": regular,
                "url": f"https://www.kroger.com/p/-/{p.get('productId')}",
                "note": f"{text.strip()} {it.get('size', '')} (Kroger API, {today}).".replace("  ", " "),
            }
            if item["kind"] == "grocery":
                o["size"] = size or 1
            observations.append(o)
    return observations


# ---------------------------------------------------------------- whole foods


def package_size(name, unit):
    """Size in the watchlist unit from a product name like "Salted Butter, 8 OZ" or "8 Count"."""
    if unit == "oz":
        m = re.search(r"(\d+(?:\.\d+)?)\s*(?:fl\.?\s*)?oz\b", name, re.I)
    elif unit == "lb":
        m = re.search(r"(\d+(?:\.\d+)?)\s*(?:lbs?|pounds?)\b", name, re.I)
    else:  # stick, bar: a pack count, else a single
        m = re.search(r"(\d+)\s*(?:count|ct|pk|pack|-pack|bars?|sticks?)\b", name, re.I)
        if not m:
            return 1
    return float(m.group(1)) if m else None


def from_wholefoods(item, cfg, settings, today):
    """Regular, sale and Prime member prices at the Whole Foods in settings.wholefoods_store."""
    store = settings["wholefoods_store"]
    q = urllib.parse.urlencode({"text": cfg["query"], "store": store["id"], "limit": 60})
    results = json.loads(get(f"https://www.wholefoodsmarket.com/api/search?{q}")).get("results", [])
    observations = []
    for p in results:
        text = f"{p.get('brand', '')} {p.get('name', '')}"
        if not matches(text, cfg) or not p.get("regularPrice"):
            continue
        size = package_size(p["name"], item["unit"]) if item["kind"] == "grocery" else None
        if cfg.get("size") and size != cfg["size"]:
            continue
        regular, sale, prime = p["regularPrice"], p.get("salePrice"), p.get("incrementalSalePrice")
        on_sale = sale and sale < regular and (p.get("saleEndDate") or "9999")[:10] >= today
        price = (prime if settings.get("prime_member") and prime else sale) if on_sale else regular
        o = {
            "item": item["id"],
            "store": f"Whole Foods {store['name']}",
            "price": price,
            "regular_price": regular,
            "url": f"https://www.wholefoodsmarket.com/product/{p.get('slug')}",
            "note": f"{text.strip()} (Whole Foods site, {today}).",
        }
        if on_sale:
            o["ends"] = p["saleEndDate"][:10]
            if prime and not settings.get("prime_member"):
                o["note"] += f" Prime members ${prime:g}."
        if size:
            o["size"] = size
        observations.append(o)
    return observations


# ---------------------------------------------------------------- main


def run_item(item, settings, today, kroger=None):
    src = item.get("sources") or {}
    observations, leads, errors = [], [], []
    jobs = []
    if "kroger" in src and kroger:
        jobs.append(("kroger", lambda: observations.extend(from_kroger(item, src["kroger"], kroger, today))))
    if "wholefoods" in src and settings.get("wholefoods_store"):
        jobs.append(("wholefoods", lambda: observations.extend(
            from_wholefoods(item, src["wholefoods"], settings, today))))
    if "shopify" in src:
        jobs.append(("shopify", lambda: observations.extend(from_shopify(item, src["shopify"], today))))
    if "flipp" in src and settings.get("postal_code"):
        jobs.append(("flipp", lambda: leads.extend(from_flipp(item, src["flipp"], settings["postal_code"], today))))
    if "slickdeals" in src:
        jobs.append(("slickdeals", lambda: leads.extend(
            from_slickdeals(item, src["slickdeals"], settings.get("slickdeals_days", 14), today))))
    for name, job in jobs:
        try:
            job()
        except Exception as e:  # one failing source must not stop the others
            errors.append(f"{item['id']} {name}: {type(e).__name__}: {e}")
    return observations, leads, errors


def main(argv):
    wl = json.loads((ROOT / "watchlist.json").read_text())
    settings = wl["settings"]
    items = [i for i in wl["items"] if not argv or i["id"] in argv]
    today = date.today().isoformat()
    kroger, setup_errors = None, []
    if any("kroger" in (i.get("sources") or {}) for i in items):
        try:
            kroger = Kroger(settings.get("postal_code"))
        except Exception as e:
            setup_errors.append(f"Kroger skipped: {type(e).__name__}: {e}")
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda i: run_item(i, settings, today, kroger), items))
    observations = [o for r in results for o in r[0]]
    leads = [lead for r in results for lead in r[1]]
    errors = setup_errors + [e for r in results for e in r[2]]
    if not settings.get("postal_code"):
        errors.append("Flipp skipped: set settings.postal_code in watchlist.json")

    OUT.mkdir(exist_ok=True)
    (OUT / "sources.json").write_text(json.dumps(
        {"date": today, "observations": observations, "leads": leads, "errors": errors},
        indent=1, ensure_ascii=False) + "\n")

    print(f"{len(observations)} exact prices, {len(leads)} leads, {len(errors)} errors -> out/sources.json")
    for o in observations:
        stock = {True: "in stock", False: "SOLD OUT", None: "stock unknown"}[o.get("in_stock")]
        size = f" (size {o['size']:g})" if "size" in o else ""
        print(f"  = {o['item']}: ${o['price']:g}{size} at {o['store']}, {stock}")
    for lead in leads:
        print(f"  ? {lead['item']}: {lead['source']} {lead['store']} | {lead['title'][:70]} | {lead['deal']} | {lead['valid']}")
    for e in errors:
        print(f"  ! {e}")


if __name__ == "__main__":
    main(sys.argv[1:])
