#!/usr/bin/env python3
"""Inc 2A newsfeed parse/fetch unit tests (network mocked). Run: python tests/test_newsfeed.py"""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import newsfeed

RSS = ('<?xml version="1.0" encoding="utf-8"?>'
       '<rss version="2.0"><channel><title>BBC</title>'
       '<item><title>Headline  One &amp; Two</title><link>http://x/1</link></item>'
       '<item><title>Second   Headline</title><link>http://x/2</link></item>'
       '</channel></rss>').encode("utf-8")

ATOM = ('<?xml version="1.0" encoding="utf-8"?>'
        '<feed xmlns="http://www.w3.org/2005/Atom">'
        '<entry><title>Atom Title</title><link href="http://a/1"/></entry>'
        '</feed>').encode("utf-8")

NONASCII = ('<?xml version="1.0" encoding="utf-8"?><rss version="2.0"><channel>'
            '<item><title>Café News</title><link>http://x</link></item>'
            '</channel></rss>').encode("utf-8")


class ParseTest(unittest.TestCase):
    def test_rss_titles_links(self):
        items = newsfeed.parse(RSS)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["title"], "Headline One & Two")   # whitespace collapsed, entity decoded
        self.assertEqual(items[0]["link"], "http://x/1")
        self.assertEqual(items[1]["title"], "Second Headline")

    def test_atom_title_and_href_link(self):
        items = newsfeed.parse(ATOM)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "Atom Title")
        self.assertEqual(items[0]["link"], "http://a/1")

    def test_nonascii_title_preserved(self):
        items = newsfeed.parse(NONASCII)
        self.assertEqual(items[0]["title"], "Café News")

    def test_malformed_xml_returns_empty(self):
        self.assertEqual(newsfeed.parse(b"not xml <<<"), [])

    def test_empty_bytes_returns_empty(self):
        self.assertEqual(newsfeed.parse(b""), [])

    def test_doctype_entity_rejected(self):
        # billion-laughs / XXE payload: must be rejected before reaching the parser.
        bomb = (b'<?xml version="1.0"?>'
                b'<!DOCTYPE lolz [<!ENTITY lol "lol">'
                b'<!ENTITY lol2 "&lol;&lol;&lol;">]>'
                b'<rss version="2.0"><channel><item><title>&lol2;</title>'
                b'<link>http://x</link></item></channel></rss>')
        self.assertEqual(newsfeed.parse(bomb), [])


class FetchFeedTest(unittest.TestCase):
    def setUp(self):
        self._orig = newsfeed._http_get

    def tearDown(self):
        newsfeed._http_get = self._orig

    def test_success_attaches_source(self):
        newsfeed._http_get = lambda url, timeout: RSS
        items = newsfeed.fetch_feed({"name": "BBC World", "url": "http://x"}, 4.0, 10)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["source"], "BBC World")
        self.assertEqual(items[0]["title"], "Headline One & Two")

    def test_network_error_returns_empty(self):
        def boom(url, timeout):
            raise IOError("timed out")
        newsfeed._http_get = boom
        self.assertEqual(newsfeed.fetch_feed({"name": "BBC", "url": "http://x"}, 4.0, 10), [])

    def test_max_items_truncates(self):
        newsfeed._http_get = lambda url, timeout: RSS
        items = newsfeed.fetch_feed({"name": "BBC", "url": "http://x"}, 4.0, 1)
        self.assertEqual(len(items), 1)

    def test_missing_url_returns_empty(self):
        self.assertEqual(newsfeed.fetch_feed({"name": "BBC"}, 4.0, 10), [])

    def test_unparseable_body_returns_empty(self):
        newsfeed._http_get = lambda url, timeout: b"garbage <<<"
        self.assertEqual(newsfeed.fetch_feed({"name": "BBC", "url": "http://x"}, 4.0, 10), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
