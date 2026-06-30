#!/usr/bin/env python3
"""Run: python tests/test_radio_config.py"""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

RC = {
    "favorites": [{"name": "101 SMOOTH JAZZ", "uri": "library://radio/2", "country": "us", "language": "en", "genres": ["jazz", "smooth jazz"]}],
    "country_codes": {"romania": "ro", "romanian": "ro", "russia": "ru"},
    "languages": {"russian": "ru", "english": "en"},
    "genre_synonyms": {"jazz": ["jazz", "smooth jazz"], "news": ["news", "talk"]},
}


class RadioConfigTest(unittest.TestCase):
    def test_resolve_country_place_and_nationality(self):
        self.assertEqual(config.resolve_country(RC, "Romania"), "ro")
        self.assertEqual(config.resolve_country(RC, "romanian"), "ro")
        self.assertIsNone(config.resolve_country(RC, "Atlantis"))

    def test_resolve_language(self):
        self.assertEqual(config.resolve_language(RC, "Russian"), "ru")
        self.assertIsNone(config.resolve_language(RC, "klingon"))

    def test_resolve_genre_key(self):
        self.assertEqual(config.resolve_genre(RC, "jazz"), ("jazz", ["jazz", "smooth jazz"]))

    def test_resolve_genre_via_synonym(self):
        self.assertEqual(config.resolve_genre(RC, "talk"), ("news", ["news", "talk"]))

    def test_resolve_genre_unknown_passthrough(self):
        self.assertEqual(config.resolve_genre(RC, "Polka"), ("polka", ["polka"]))

    def test_defaults(self):
        d = config.radio_defaults(RC)
        self.assertEqual(d["find_internal"], 5)
        self.assertEqual(d["find_speak"], 3)

    def test_defaults_override(self):
        d = config.radio_defaults({"defaults": {"find_speak": 2}})
        self.assertEqual(d["find_speak"], 2)
        self.assertEqual(d["find_internal"], 5)

    def test_favorites_accessor(self):
        self.assertEqual(len(config.favorites(RC)), 1)
        self.assertEqual(config.favorites({}), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
