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

    def test_by_name_alias_key_case_insensitive(self):
        rc = {"favorites": RC["favorites"], "aliases": {"ActualitaTI": "Radio Romania Actualitati"}}
        out = favorites.by_name(rc, "actualitati")
        self.assertTrue(out)
        self.assertEqual(out[0]["uri"], "library://radio/10")
        self.assertEqual(out[0]["source"], "favorite")

    def test_by_name_cyrillic_exact(self):
        rc = {"favorites": [{"name": "Ретро ФМ", "uri": "library://radio/8", "country": "ru", "language": "ru", "genres": ["retro"]}], "aliases": {}}
        out = favorites.by_name(rc, "Ретро ФМ")
        self.assertTrue(out)
        self.assertEqual(out[0]["uri"], "library://radio/8")

    def test_by_name_alias_to_cyrillic(self):
        rc = {"favorites": [{"name": "Ретро ФМ", "uri": "library://radio/8", "country": "ru", "language": "ru", "genres": ["retro"]}], "aliases": {"retro fm": "Ретро ФМ"}}
        out = favorites.by_name(rc, "Retro FM")
        self.assertTrue(out)
        self.assertEqual(out[0]["uri"], "library://radio/8")


class AliasResolutionTest(unittest.TestCase):
    """The assistant relays the raw transcription as the station argument, so it arrives noisy and
    over-long -- whole-string equality can never keep up. Live failures this covers:
      target='Radio Norok N O R O C'  -> candidates=0
      target='norok'                  -> candidates=0 (before aliases reached the MA search)"""

    CFG = {"aliases": {"norok": "Radio Noroc Moldova",
                       "noroc": "Radio Noroc Moldova",
                       "radio noroc moldova": "Radio Noroc Moldova",
                       "nashe": "Nashe Radio"},
           "favorites": []}

    def test_exact_alias(self):
        self.assertEqual(favorites.resolve_alias(self.CFG, "norok"), "Radio Noroc Moldova")

    def test_alias_found_inside_a_noisy_transcription(self):
        self.assertEqual(favorites.resolve_alias(self.CFG, "Radio Norok N O R O C"),
                         "Radio Noroc Moldova")

    def test_spelled_out_letters_collapse(self):
        # "N O R O C" compacts to "noroc"
        self.assertEqual(favorites.resolve_alias(self.CFG, "play N O R O C please"),
                         "Radio Noroc Moldova")

    def test_longest_alias_key_wins(self):
        self.assertEqual(favorites.resolve_alias(self.CFG, "radio noroc moldova"),
                         "Radio Noroc Moldova")

    def test_unrelated_query_is_untouched(self):
        for q in ("smooth jazz", "rock", "play some rock music", "europa plus"):
            self.assertEqual(favorites.resolve_alias(self.CFG, q), q)

    def test_rock_is_never_hijacked_by_a_noroc_alias(self):
        # "rock" is a real genre synonym; aliasing it would break every genuine rock request.
        cfg = dict(self.CFG)
        cfg["aliases"] = dict(self.CFG["aliases"]); cfg["aliases"]["no rock"] = "Radio Noroc Moldova"
        self.assertEqual(favorites.resolve_alias(cfg, "rock"), "rock")
        self.assertEqual(favorites.resolve_alias(cfg, "play rock"), "play rock")

    def test_short_keys_do_not_fire_inside_words(self):
        cfg = {"aliases": {"fm": "Some FM"}, "favorites": []}
        self.assertEqual(favorites.resolve_alias(cfg, "confirmation station"), "confirmation station")

    def test_no_aliases_or_empty_query(self):
        self.assertEqual(favorites.resolve_alias({"favorites": []}, "anything"), "anything")
        self.assertEqual(favorites.resolve_alias(self.CFG, ""), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
