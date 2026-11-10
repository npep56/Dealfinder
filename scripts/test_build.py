"""Tests for build.py. Run: python3 -m unittest discover scripts"""
import json
import tempfile
import unittest
from pathlib import Path

import build

SETTINGS = {
    "want_close_margin": 0.1,
    "grocery_deal_pct": 0.15,
    "grocery_close_pct": 0.05,
    "deal_stale_days": 3,
    "dashboard_url": "https://example.test/dash",
}
CLOG = {"id": "clog", "name": "Clog", "kind": "want", "unit": "item", "regular_price": 160, "target_price": 127}
TIGHT = {"id": "tight", "name": "Tight", "kind": "want", "unit": "item", "regular_price": None, "target_price": None}
BUTTER = {"id": "butter", "name": "Butter", "kind": "grocery", "unit": "oz", "typical_unit_price": None}
ITEMS = {i["id"]: i for i in (CLOG, TIGHT, BUTTER)}


def scan(day, *obs, run="daily", time=None):
    s = {"date": day, "run": run, "observations": list(obs)}
    if time:
        s["time"] = time
    return s


class JudgeTests(unittest.TestCase):
    def test_want_at_target_is_deal(self):
        self.assertEqual(build.judge_want(CLOG, {"price": 127}, SETTINGS), ("Deal", 0.206, 127))

    def test_want_within_margin_is_close(self):
        self.assertEqual(build.judge_want(CLOG, {"price": 139}, SETTINGS)[0], "Close")

    def test_want_full_price_is_watching(self):
        self.assertEqual(build.judge_want(CLOG, {"price": 160}, SETTINGS)[0], "Watching")

    def test_want_without_target_uses_regular_price(self):
        self.assertEqual(build.judge_want(TIGHT, {"price": 100, "regular_price": 128}, SETTINGS)[0], "Deal")
        self.assertEqual(build.judge_want(TIGHT, {"price": 128, "regular_price": 128}, SETTINGS)[0], "Watching")

    def test_want_without_any_reference_uses_assessment(self):
        self.assertEqual(build.judge_want(TIGHT, {"price": 90, "assessment": "close"}, SETTINGS)[0], "Close")

    def test_grocery_against_regular_price(self):
        o = {"price": 3.0, "size": 8, "regular_price": 4.0}
        self.assertEqual(build.judge_grocery(BUTTER, o, SETTINGS, []), ("Deal", 0.25, 0.5))

    def test_grocery_uses_median_of_past_regulars(self):
        o = {"price": 3.8, "size": 8}
        self.assertEqual(build.judge_grocery(BUTTER, o, SETTINGS, [0.5, 0.5, 0.6])[0], "Close")

    def test_grocery_without_baseline_uses_assessment(self):
        self.assertEqual(build.judge_grocery(BUTTER, {"price": 3.99, "size": 8, "assessment": "close"}, SETTINGS, [])[0], "Close")


class BuildTests(unittest.TestCase):
    def test_best_sighting_wins_and_history_kept(self):
        scans = [scan("2026-11-08", {"item": "clog", "store": "A", "price": 160}),
                 scan("2026-11-09", {"item": "clog", "store": "A", "price": 160},
                      {"item": "clog", "store": "B", "price": 120})]
        for s in scans:
            s["label"] = s["run"]
        rows, history, runs = build.build(SETTINGS, ITEMS, scans)
        clog = next(r for r in rows if r["id"] == "clog")
        self.assertEqual((clog["status"], clog["store"], clog["lowest_unit_price"]), ("Deal", "B", 120))
        self.assertEqual(len(history), 3)
        self.assertEqual([r["date"] for r in runs], ["2026-11-09", "2026-11-08"])

    def test_stale_deal_drops_to_watching(self):
        scans = [scan("2026-11-01", {"item": "clog", "store": "A", "price": 120}), scan("2026-11-09")]
        for s in scans:
            s["label"] = s["run"]
        rows, _, _ = build.build(SETTINGS, ITEMS, scans)
        self.assertEqual(next(r for r in rows if r["id"] == "clog")["status"], "Watching")

    def test_sold_out_and_expired_are_skipped(self):
        scans = [scan("2026-11-09",
                      {"item": "clog", "store": "A", "price": 100, "in_stock": False},
                      {"item": "clog", "store": "B", "price": 100, "ends": "2026-11-08"})]
        scans[0]["label"] = "daily"
        rows, history, _ = build.build(SETTINGS, ITEMS, scans)
        self.assertEqual(history, [])
        self.assertEqual(next(r for r in rows if r["id"] == "clog")["status"], "No price yet")


class LoadTests(unittest.TestCase):
    def write_scans(self, *scans):
        folder = Path(tempfile.mkdtemp())
        for i, s in enumerate(scans):
            (folder / f"{i}.json").write_text(json.dumps(s))
        return folder

    def test_same_day_runs_get_unique_labels_and_counts(self):
        folder = self.write_scans(
            scan("2026-11-27", {"item": "clog", "store": "A", "price": 120}, run="black-friday", time="12:44"),
            scan("2026-11-27", {"item": "clog", "store": "A", "price": 160}, run="black-friday", time="17:44"))
        scans = build.load_scans(folder, ITEMS)
        self.assertEqual([s["label"] for s in scans], ["black-friday 12:44", "black-friday 17:44"])
        _, _, runs = build.build(SETTINGS, ITEMS, scans)
        self.assertEqual([(r["run"], r["deals"]) for r in runs], [("black-friday 17:44", 0), ("black-friday 12:44", 1)])

    def test_bad_data_is_rejected(self):
        bad = [
            {"item": "nope", "store": "A", "price": 1},
            {"item": "clog", "store": "A", "price": "120"},
            {"item": "butter", "store": "A", "price": 3.99},
            {"item": "clog", "store": "A", "price": 120, "assessment": "great"},
            {"item": "clog", "store": "A", "price": 120, "ends": "11/20"},
        ]
        for o in bad:
            with self.subTest(o=o), self.assertRaises(build.DataError):
                build.load_scans(self.write_scans(scan("2026-11-09", o)), ITEMS)


class SummaryTests(unittest.TestCase):
    def test_money(self):
        self.assertEqual([build.money(v) for v in (120, 3.99, 1500)], ["$120", "$3.99", "$1,500"])
        self.assertEqual([build.unit_money(v) for v in (0.499, 0.5, 2.31)], ["$0.499", "$0.5", "$2.31"])

    def test_deal_line(self):
        rows = [dict(build.blank_row(CLOG), status="Deal", price=120, store="rothys.com", pct_off=0.25,
                     code="FORYOU26", last_seen="2026-11-09")]
        text = build.summary(SETTINGS, rows, [{"date": "2026-11-09"}])
        self.assertEqual(text.splitlines()[:2], ["1 deal today:", "• Clog $120 at rothys.com, 25% off, code FORYOU26"])


if __name__ == "__main__":
    unittest.main()
