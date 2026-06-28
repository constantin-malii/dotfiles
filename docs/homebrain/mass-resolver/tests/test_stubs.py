#!/usr/bin/env python3
"""Contract tests for not-yet-implemented capabilities. Run: python tests/test_stubs.py"""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import news, acquire, status


class StubTest(unittest.TestCase):
    def _check(self, fn, intent):
        r = fn(None, {}, "rid")
        self.assertFalse(r["ok"])
        self.assertTrue(r["not_implemented"])
        self.assertEqual(r["intent"], intent)
        self.assertIn("yet", r["spoken"].lower())
        self.assertEqual(r["request_id"], "rid")

    def test_news_stub(self):
        self._check(news.get_news, "news")

    def test_acquire_stub(self):
        self._check(acquire.acquire, "acquire")

    def test_status_stub(self):
        self._check(status.status, "status")


if __name__ == "__main__":
    unittest.main(verbosity=2)
