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

    def test_quoted_keys_are_cleaned(self):
        env = {"KROGER_CLIENT_ID": '<app-123>', "KROGER_CLIENT_SECRET": " 'sec' "}
        seen = {}

        def fake_urlopen(req, timeout):
            seen["auth"] = req.get_header("Authorization")
            raise fs.urllib.error.HTTPError(req.full_url, 401, "no", {}, None)

        with mock.patch.dict(fs.os.environ, env, clear=True), \
             mock.patch.object(fs.urllib.request, "urlopen", fake_urlopen):
            with self.assertRaises(RuntimeError):
                fs.Kroger("30152")
        self.assertEqual(seen["auth"], "Basic " + fs.base64.b64encode(b"app-123:sec").decode())

    def test_missing_keys_skip_kroger(self):
        with mock.patch.dict(fs.os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError):
                fs.Kroger("30152")


class MatchAndSizeTests(unittest.TestCase):
    def test_any_and_exclude(self):
        cfg = {"match": ["cedars"], "any": ["hot honey", "original"], "exclude": ["reserve"]}
        self.assertTrue(fs.matches("Cedars Organic Hot Honey Hommus, 10 OZ", cfg))
        self.assertFalse(fs.matches("Cedars Organic Cedar's Reserve Olive Hommus, 10 OZ", cfg))
        self.assertFalse(fs.matches("Cedars Reserve Original Hommus", cfg))

    def test_package_size(self):
        self.assertEqual(fs.package_size("Salted Irish Butter, 8 OZ", "oz"), 8)
        self.assertEqual(fs.package_size("Protein Bar 12pk, 1.98 OZ", "bar"), 12)
        self.assertEqual(fs.package_size("Original Beef Stick 8 Count, 1.15 OZ", "stick"), 8)
        self.assertEqual(fs.package_size("Original Beef Stick Sgl, 1.15 OZ", "stick"), 1)
        self.assertEqual(fs.package_size("Scoop Away Cat Litter, 14 lbs.", "lb"), 14)


class WholeFoodsTests(unittest.TestCase):
    SETTINGS = {"wholefoods_store": {"id": "10590", "name": "Kennesaw"}, "prime_member": False}
    RESULTS = {"results": [
        {"brand": "Kerrygold", "name": "Salted Butter Sticks, 8 OZ", "slug": "a", "regularPrice": 5.49,
         "salePrice": 4.88, "incrementalSalePrice": 4.39, "saleEndDate": "2026-11-17T23:59:59Z"},
        {"brand": "Kerrygold", "name": "Unsalted Butter Sticks, 8 OZ", "slug": "b", "regularPrice": 5.49},
        {"brand": "Kerrygold", "name": "Salted Butter, 16 OZ", "slug": "c", "regularPrice": 9.99,
         "salePrice": 8.99, "saleEndDate": "2026-11-01T23:59:59Z"},
    ]}

    def run_wf(self, settings, cfg):
        item = {"id": "kg", "kind": "grocery", "unit": "oz"}
        with mock.patch.object(fs, "get", return_value=__import__("json").dumps(self.RESULTS)):
            return fs.from_wholefoods(item, cfg, settings, "2026-11-11")

    def test_sale_price_and_expired_sale(self):
        obs = self.run_wf(self.SETTINGS, {"query": "k", "match": ["kerrygold", "salted"]})
        self.assertEqual([(o["price"], o["regular_price"], o["size"], o.get("ends")) for o in obs],
                         [(4.88, 5.49, 8, "2026-11-17"), (9.99, 9.99, 16, None)])
        self.assertIn("Prime members $4.39", obs[0]["note"])

    def test_prime_price_for_members(self):
        obs = self.run_wf(dict(self.SETTINGS, prime_member=True), {"query": "k", "match": ["salted"], "size": 8})
        self.assertEqual([o["price"] for o in obs], [4.39])


if __name__ == "__main__":
    unittest.main()
