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



class SayAsHandleTest(unittest.TestCase):
    """Cyrillic-named stations are unsayable to STT (the Noroc lesson). A favorite may carry a
    short ASCII `say_as` handle: it is what the listing reads out AND what the user can say back,
    so one field serves discovery and addressability without a second list to keep in sync."""

    RC = {
        "favorites": [
            {"name": "Mega Hits", "uri": "library://radio/16", "country": "pt", "say_as": "mega hits"},
            {"name": "Русское Радио", "uri": "library://radio/7", "country": "ru", "say_as": "russian radio"},
            {"name": "Kiss FM 106.5", "uri": "library://radio/11", "country": "ua"},
        ],
        "aliases": {},
    }

    def test_say_as_resolves_like_an_alias(self):
        self.assertEqual(favorites.resolve_alias(self.RC, "russian radio"),
                         u"Русское Радио")

    def test_say_as_reaches_the_station_by_name(self):
        out = favorites.by_name(self.RC, "russian radio")
        self.assertTrue(out)
        self.assertEqual(out[0]["uri"], "library://radio/7")

    def test_explicit_alias_still_wins_when_both_exist(self):
        rc = dict(self.RC)
        rc["aliases"] = {"russian radio": "Mega Hits"}
        self.assertEqual(favorites.resolve_alias(rc, "russian radio"), "Mega Hits")


class FavoritesListingTest(unittest.TestCase):
    RC = SayAsHandleTest.RC

    def test_all_returns_every_favorite_in_file_order(self):
        out = favorites.all_favorites(self.RC)
        self.assertEqual([s["uri"] for s in out],
                         ["library://radio/16", "library://radio/7", "library://radio/11"])

    def test_all_carries_the_spoken_handle(self):
        out = favorites.all_favorites(self.RC)
        self.assertEqual(out[0]["say_as"], "mega hits")
        self.assertEqual(out[1]["say_as"], "russian radio")

    def test_station_without_a_handle_falls_back_to_its_name(self):
        out = favorites.all_favorites(self.RC)
        self.assertEqual(favorites.spoken_name(out[2]), "Kiss FM 106.5")
        self.assertEqual(favorites.spoken_name(out[1]), "russian radio")


if __name__ == "__main__":
    unittest.main(verbosity=2)
