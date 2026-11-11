"""Tests for fetch_sources.py that need no network. Run: python3 -m unittest discover scripts"""
import unittest
from unittest import mock

import fetch_sources as fs

ROTHYS = ("The Casual Clog - Chestnut", [
    ("Chestnut / 9", ["Chestnut", "9", ""], 160.0, None, False),
    ("Chestnut / 10", ["Chestnut", "10", ""], 160.0, None, True),
])
CHOMPS = ("Original Beef", [
    ("10 Pack", ["10 Pack", "", ""], 25.6, None, True),
    ("24 Pack", ["24 Pack", "", ""], 54.99, 60.0, True),
])


class VariantMatchTests(unittest.TestCase):
    def test_exact_alternatives_and_prefix(self):
        self.assertTrue(fs.variant_matches(["Chestnut", "10"], ["Chestnut", "10", ""]))
        self.assertFalse(fs.variant_matches(["Chestnut", "10"], ["Chestnut", "11", ""]))
        self.assertTrue(fs.variant_matches(["Carbon|Midnight", "L"], ["Midnight", "L", ""]))
        self.assertTrue(fs.variant_matches(["Front: 4K*"], ["Front: 4K（2160P）64GB", "", ""]))
        self.assertFalse(fs.variant_matches(["Front: 4K*"], ["Front 4K+ Rear 1080P+ 128G", "", ""]))

    def test_size_is_not_a_prefix_match(self):
        self.assertFalse(fs.variant_matches(["1"], ["10", "", ""]))


class ShopifyTests(unittest.TestCase):
    def test_matching_variant_becomes_observation(self):
        item = {"id": "clog", "regular_price": 160}
        cfg = {"store": "rothys.com", "handle": "h", "variant": ["Chestnut", "10"]}
        with mock.patch.object(fs, "shopify_variants", return_value=ROTHYS):
            (o,) = fs.from_shopify(item, cfg, "2026-11-11")
        self.assertEqual((o["price"], o["regular_price"], o["in_stock"]), (160.0, 160, True))

    def test_pack_size_and_compare_at(self):
        item = {"id": "chomps", "regular_price": None}
        cfg = {"store": "chomps.com", "handle": "h", "variant": ["24 Pack"], "size_from_variant": True}
        with mock.patch.object(fs, "shopify_variants", return_value=CHOMPS):
            (o,) = fs.from_shopify(item, cfg, "2026-11-11")
        self.assertEqual((o["size"], o["regular_price"]), (24, 60.0))

    def test_no_matching_variant_is_an_error(self):
        cfg = {"store": "rothys.com", "handle": "h", "variant": ["Chestnut", "14"]}
        with mock.patch.object(fs, "shopify_variants", return_value=ROTHYS):
            with self.assertRaises(LookupError):
                fs.from_shopify({"id": "clog"}, cfg, "2026-11-11")


class FlippTests(unittest.TestCase):
    def test_filters_by_words_and_date(self):
        ads = {"items": [
            {"id": 1, "merchant_name": "Publix", "name": "Kerrygold Pure Irish Butter BOGO",
             "pre_price_text": "Buy 1 Get 1 FREE", "valid_from": "2026-11-11", "valid_to": "2026-11-18"},
            {"id": 2, "merchant_name": "Kroger", "name": "Land O Lakes Butter", "valid_to": "2026-11-18"},
            {"id": 3, "merchant_name": "Target", "name": "Kerrygold butter", "valid_to": "2026-11-01"},
        ]}
        with mock.patch.object(fs, "get", return_value=__import__("json").dumps(ads)):
            leads = fs.from_flipp({"id": "kg"}, {"query": "kerrygold", "match": ["kerrygold"]}, "30303", "2026-11-11")
        self.assertEqual([(l["store"], l["deal"]) for l in leads], [("Publix", "Buy 1 Get 1 FREE")])


class RunItemTests(unittest.TestCase):
    def test_one_failing_source_does_not_stop_the_others(self):
        item = {"id": "x", "sources": {"shopify": {"store": "s", "handle": "h"}, "slickdeals": "x"}}
        with mock.patch.object(fs, "from_shopify", side_effect=OSError("blocked")), \
             mock.patch.object(fs, "from_slickdeals", return_value=[{"item": "x"}]):
            obs, leads, errors = fs.run_item(item, {}, "2026-11-11")
        self.assertEqual((obs, len(leads), len(errors)), ([], 1, 1))


class KrogerTests(unittest.TestCase):
    PRODUCTS = [
        {"productId": "1", "brand": "Kerrygold", "description": "Kerrygold Pure Irish Salted Butter",
         "items": [{"size": "8 oz", "price": {"regular": 4.99, "promo": 3.99}}]},
        {"productId": "2", "brand": "Kerrygold", "description": "Kerrygold Unsalted Butter",
         "items": [{"size": "8 oz", "price": {"regular": 4.99, "promo": 0}}]},
        {"productId": "3", "brand": "Kerrygold", "description": "Kerrygold Salted Butter Sticks",
         "items": [{"size": "4 oz", "price": {"regular": 3.29, "promo": 0}}]},
    ]

    def kroger(self):
        k = mock.Mock(store_name="Kroger (Main St, Kennesaw)")
        k.search.return_value = self.PRODUCTS
        return k

    def test_match_words_size_and_promo(self):
        item = {"id": "kg", "kind": "grocery"}
        cfg = {"term": "kerrygold", "match": ["kerrygold", "salted"], "size": 8}
        obs = fs.from_kroger(item, cfg, self.kroger(), "2026-11-11")
        self.assertEqual([(o["price"], o["regular_price"], o["size"]) for o in obs], [(3.99, 4.99, 8)])

    def test_size_read_from_package_when_not_given(self):
        item = {"id": "kg", "kind": "grocery"}
        obs = fs.from_kroger(item, {"term": "k", "match": ["salted"]}, self.kroger(), "2026-11-11")
        self.assertEqual(sorted(o["size"] for o in obs), [4.0, 8.0])

    def test_missing_keys_skip_kroger(self):
        with mock.patch.dict(fs.os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError):
                fs.Kroger("30152")


if __name__ == "__main__":
    unittest.main()
