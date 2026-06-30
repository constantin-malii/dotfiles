#!/usr/bin/env python3
"""Inc 2A NewsCapability unit tests (fetch seam mocked). Run: python tests/test_news.py"""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import news, newsfeed, capability

CFG = {"defaults": {"headline_count": 3, "feed_timeout": 4.0, "max_items_per_feed": 10},
       "feeds": {"world": [{"name": "BBC World", "url": "http://bbc/world"}]},
       "stations": {}}


class FakeCtx(object):
    def __init__(self, news_cfg):
        self.news_cfg = news_cfg


def run(cfg, params, results=None):
    """results: dict url -> list[item]; absent urls -> []. Patches newsfeed.fetch_feed."""
    results = results or {}
    orig = newsfeed.fetch_feed
    newsfeed.fetch_feed = lambda feed, timeout, max_items: list(results.get(feed.get("url"), []))
    try:
        return capability.run(news.NewsCapability(), FakeCtx(cfg), params, "rid1")
    finally:
        newsfeed.fetch_feed = orig


class ResolveValidateTest(unittest.TestCase):
    def test_no_param_defaults_world(self):
        cap = news.NewsCapability()
        r = cap.resolve(FakeCtx(CFG), {})
        self.assertEqual(r["bucket_key"], "world")
        self.assertIsNone(r["requested_label"])
        self.assertEqual(len(r["feeds"]), 1)
        self.assertEqual(r["headline_count"], 3)

    def test_explicit_known_topic_selects_bucket(self):
        cap = news.NewsCapability()
        r = cap.resolve(FakeCtx(CFG), {"topic": "World"})
        self.assertEqual(r["bucket_key"], "world")

    def test_explicit_unknown_country_no_bucket(self):
        cap = news.NewsCapability()
        r = cap.resolve(FakeCtx(CFG), {"country": "Romania"})
        self.assertIsNone(r["bucket_key"])
        self.assertEqual(r["requested_label"], "Romania")

    def test_validate_unknown_bucket_not_found(self):
        r = run(CFG, {"country": "Romania"})
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"]["code"], "not_found")
        self.assertEqual(r["chat_text"], "I don't have Romania news set up yet.")
        self.assertIsNone(r["spoken_text"])

    def test_validate_empty_bucket_not_found(self):
        cfg = {"defaults": CFG["defaults"], "feeds": {"world": []}, "stations": {}}
        r = run(cfg, {})
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"]["code"], "not_found")
        self.assertIsNone(r["spoken_text"])

    def test_defaults_fallback_when_missing(self):
        d = news._defaults({})
        self.assertEqual(d["headline_count"], 3)
        self.assertEqual(d["feed_timeout"], 4.0)
        self.assertEqual(d["max_items_per_feed"], 10)


class MergeTest(unittest.TestCase):
    def _items(self, *titles):
        return [{"title": t, "link": "", "source": "s"} for t in titles]

    def test_roundrobin_interleaves_feeds(self):
        a = self._items("A1", "A2")
        b = self._items("B1", "B2")
        merged = news._merge([a, b], 4)
        self.assertEqual([m["title"] for m in merged], ["A1", "B1", "A2", "B2"])

    def test_dedupes_by_title_case_insensitive(self):
        a = self._items("Same", "A2")
        b = self._items("same", "B2")
        merged = news._merge([a, b], 4)
        self.assertEqual([m["title"] for m in merged], ["Same", "A2", "B2"])

    def test_caps_at_count(self):
        a = self._items("A1", "A2", "A3", "A4")
        merged = news._merge([a], 2)
        self.assertEqual(len(merged), 2)

    def test_empty_returns_empty(self):
        self.assertEqual(news._merge([], 3), [])
        self.assertEqual(news._merge([[]], 3), [])


def _mk(*titles):
    return [{"title": t, "link": "http://l/" + t, "source": "BBC World"} for t in titles]

TWO_FEED_CFG = {"defaults": {"headline_count": 4, "feed_timeout": 4.0, "max_items_per_feed": 10},
                "feeds": {"world": [{"name": "F1", "url": "http://f1"},
                                    {"name": "F2", "url": "http://f2"}]},
                "stations": {}}


class ExecuteTest(unittest.TestCase):
    def test_single_feed_success_shape(self):
        r = run(CFG, {}, {"http://bbc/world": _mk("Alpha", "Bravo", "Charlie", "Delta")})
        self.assertTrue(r["ok"])
        self.assertEqual(r["intent"], "news")
        self.assertEqual(r["spoken_text"], "Here are the top world headlines. Alpha. Bravo. Charlie.")
        self.assertEqual(r["chat_text"], "Top world headlines: 1) Alpha 2) Bravo 3) Charlie")
        self.assertEqual(r["metadata"]["bucket"], "world")
        self.assertEqual(r["metadata"]["count"], 3)              # capped at headline_count=3
        self.assertEqual(r["metadata"]["feeds_ok"], 1)
        self.assertEqual(r["metadata"]["feeds_failed"], 0)
        self.assertEqual(r["metadata"]["items"][0]["source"], "BBC World")

    def test_multi_feed_merge_roundrobin(self):
        r = run(TWO_FEED_CFG, {}, {"http://f1": _mk("A1", "A2"), "http://f2": _mk("B1", "B2")})
        self.assertTrue(r["ok"])
        self.assertEqual([it["title"] for it in r["metadata"]["items"]], ["A1", "B1", "A2", "B2"])
        self.assertEqual(r["metadata"]["feeds_ok"], 2)

    def test_graceful_degrade_one_feed_fails(self):
        # F1 returns nothing (failed/empty); F2 yields -> still success.
        r = run(TWO_FEED_CFG, {}, {"http://f2": _mk("B1", "B2")})
        self.assertTrue(r["ok"])
        self.assertEqual([it["title"] for it in r["metadata"]["items"]], ["B1", "B2"])
        self.assertEqual(r["metadata"]["feeds_ok"], 1)
        self.assertEqual(r["metadata"]["feeds_failed"], 1)

    def test_all_empty_unavailable_silent(self):
        r = run(CFG, {}, {})                                    # fetch returns [] for every url
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"]["code"], "unavailable")
        self.assertEqual(r["chat_text"], "Sorry, I couldn't get the news right now.")
        self.assertIsNone(r["spoken_text"])
        self.assertEqual(r["metadata"]["count"], 0)
        self.assertEqual(r["metadata"]["feeds_ok"], 0)
        self.assertEqual(r["metadata"]["feeds_failed"], 1)

    def test_headline_count_one(self):
        cfg = {"defaults": {"headline_count": 1, "feed_timeout": 4.0, "max_items_per_feed": 10},
               "feeds": {"world": [{"name": "BBC", "url": "http://bbc/world"}]}, "stations": {}}
        r = run(cfg, {}, {"http://bbc/world": _mk("Only", "Two", "Three")})
        self.assertEqual(r["spoken_text"], "Here are the top world headlines. Only.")
        self.assertEqual(r["chat_text"], "Top world headlines: 1) Only")
        self.assertEqual(r["metadata"]["count"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
