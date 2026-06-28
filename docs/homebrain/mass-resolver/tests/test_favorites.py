#!/usr/bin/env python3
"""Run: python tests/test_favorites.py"""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import favorites

RC = {
    "favorites": [
        {"name": "101 SMOOTH JAZZ", "uri": "library://radio/2", "country": "us", "language": "en", "genres": ["jazz", "smooth jazz"]},
        {"name": "Radio Romania Actualitati", "uri": "library://radio/10", "country": "ro", "language": "ro", "genres": ["news", "talk"]},
        {"name": "Europa Plus", "uri": "library://radio/3", "country": "ru", "language": "ru", "genres": ["pop"]},
    ],
    "aliases": {"actualitati": "Radio Romania Actualitati"},
}


class FavoritesTest(unittest.TestCase):
    def test_by_name_fuzzy(self):
        out = favorites.by_name(RC, "smooth jazz")
        self.assertTrue(out and out[0]["uri"] == "library://radio/2")
        self.assertEqual(out[0]["source"], "favorite")

    def test_by_name_alias(self):
        out = favorites.by_name(RC, "actualitati")
        self.assertEqual(out[0]["uri"], "library://radio/10")

    def test_by_name_no_match(self):
        self.assertEqual(favorites.by_name(RC, "nonexistent station xyz"), [])

    def test_by_country(self):
        out = favorites.by_country(RC, "ru")
        self.assertEqual([s["uri"] for s in out], ["library://radio/3"])

    def test_by_genre_synonyms(self):
        out = favorites.by_genre(RC, ["news", "talk"])
        self.assertEqual([s["uri"] for s in out], ["library://radio/10"])

    def test_by_language(self):
        out = favorites.by_language(RC, "en")
        self.assertEqual([s["uri"] for s in out], ["library://radio/2"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
