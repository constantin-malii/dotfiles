#!/usr/bin/env python3
"""Run: python tests/test_radio.py"""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import radio

RC = {
    "favorites": [
        {"name": "101 SMOOTH JAZZ", "uri": "library://radio/2", "country": "us", "language": "en", "genres": ["jazz"]},
        {"name": "Radio Romania Actualitati", "uri": "library://radio/10", "country": "ro", "language": "ro", "genres": ["news"]},
    ],
    "aliases": {}, "country_codes": {"romania": "ro"}, "languages": {"romanian": "ro"},
    "genre_synonyms": {"jazz": ["jazz"], "news": ["news"]},
    "defaults": {"find_internal": 5, "find_speak": 3},
}


def rb_item(uuid, name):
    return {"item_id": uuid, "provider": "radiobrowser", "name": name,
            "uri": "radiobrowser://radio/" + uuid, "media_type": "radio",
            "provider_mappings": [{"provider_domain": "radiobrowser", "available": True}]}


class FakeMA(object):
    def __init__(self, browse=None, search=None, play_reply="__ok__"):
        self._browse = browse or []; self._search = search or []; self.played = []; self._play_reply = play_reply
    def connect(self): pass
    def cmd(self, command, **a):
        if command == "music/browse":
            return {"result": {"items": self._browse}}
        if command == "music/search":
            return {"result": {"radio": self._search}}
        return None
    def play(self, q, uri, option="replace"):
        self.played.append((q, uri, option))
        return {"result": {}} if self._play_reply == "__ok__" else self._play_reply
    def close(self): pass


class FakeSettings(object):
    queue_id = "q1"


class FakeCtx(object):
    def __init__(self, ma):
        self._ma = ma; self.radio_cfg = RC; self.settings = FakeSettings()
    def ma_factory(self):
        return self._ma


class RadioTest(unittest.TestCase):
    def test_play_favorite_by_name(self):
        ma = FakeMA(search=[rb_item("u1", "Other Jazz")])
        r = radio.resolve_radio(FakeCtx(ma), {"mode": "play", "station": "smooth jazz"}, "rid")
        self.assertTrue(r["ok"] and r["played"])
        self.assertEqual(r["uri"], "library://radio/2")
        self.assertEqual(r["source"], "favorite")
        self.assertEqual(ma.played[0][1], "library://radio/2")

    def test_play_country_favorite_first(self):
        ma = FakeMA(browse=[rb_item("u2", "Some RO Station")])
        r = radio.resolve_radio(FakeCtx(ma), {"mode": "play", "country": "Romania"}, "rid")
        self.assertEqual(r["uri"], "library://radio/10")  # favorite beats browse

    def test_play_genre_fallback_to_radiobrowser(self):
        ma = FakeMA(browse=[rb_item("u3", "Pop Station")])
        r = radio.resolve_radio(FakeCtx(ma), {"mode": "play", "genre": "pop"}, "rid")  # no pop favorite
        self.assertTrue(r["ok"])
        self.assertEqual(r["source"], "radiobrowser")
        self.assertEqual(r["uri"], "radiobrowser://radio/u3")

    def test_dry_run_does_not_play(self):
        ma = FakeMA()
        r = radio.resolve_radio(FakeCtx(ma), {"mode": "play", "station": "smooth jazz", "dry_run": True}, "rid")
        self.assertTrue(r["ok"])
        self.assertFalse(r["played"])
        self.assertEqual(ma.played, [])

    def test_play_no_match_is_honest(self):
        ma = FakeMA(search=[])
        r = radio.resolve_radio(FakeCtx(ma), {"mode": "play", "station": "zzz nothing"}, "rid")
        self.assertFalse(r["ok"])
        self.assertIn("couldn't find", r["spoken"].lower())
        self.assertEqual(ma.played, [])

    def test_find_speaks_top_three(self):
        ma = FakeMA(search=[rb_item("u%d" % i, "Jazz %d" % i) for i in range(6)])
        r = radio.resolve_radio(FakeCtx(ma), {"mode": "find", "genre": "jazz"}, "rid")
        self.assertTrue(r["ok"] and r["speak_success"])
        # favorite "101 SMOOTH JAZZ" (jazz) first, then radiobrowser jazz items; 3 spoken
        self.assertEqual(r["spoken"].lower().count("jazz") >= 1, True)
        self.assertLessEqual(r["spoken"].count(","), 2)  # at most 3 items => <=2 commas

    def test_find_none_is_honest(self):
        ma = FakeMA(browse=[])
        r = radio.resolve_radio(FakeCtx(ma), {"mode": "find", "country": "Romania"}, "rid")
        # Romania has a favorite -> actually found; use a country with no fav/browse:
        r2 = radio.resolve_radio(FakeCtx(FakeMA(browse=[])), {"mode": "find", "genre": "polka"}, "rid")
        self.assertFalse(r2["ok"])
        self.assertIn("couldn't find", r2["spoken"].lower())

    def test_play_error_is_honest(self):
        ma = FakeMA(play_reply={"error_code": "x"})
        r = radio.resolve_radio(FakeCtx(ma), {"mode": "play", "station": "jazz"}, "rid")
        self.assertFalse(r["ok"])
        self.assertIn("couldn't start", r["spoken"].lower())

    def test_play_none_return_is_honest(self):
        ma = FakeMA(play_reply=None)
        r = radio.resolve_radio(FakeCtx(ma), {"mode": "play", "station": "jazz"}, "rid")
        self.assertFalse(r["ok"])
        self.assertIn("couldn't start", r["spoken"].lower())

    def test_find_single_result(self):
        ma = FakeMA(search=[])
        r = radio.resolve_radio(FakeCtx(ma), {"mode": "find", "genre": "jazz"}, "rid")
        self.assertTrue(r["ok"])
        self.assertEqual(r["spoken"], "I found 101 SMOOTH JAZZ.")

    def test_find_dedupes_duplicate_names_favorite_wins(self):
        # RadioBrowser (browse) returns a station with the SAME name as the jazz favorite
        ma = FakeMA(browse=[rb_item("dup", "101 SMOOTH JAZZ"), rb_item("u9", "Other Jazz")])
        r = radio.resolve_radio(FakeCtx(ma), {"mode": "find", "genre": "jazz"}, "rid")
        names = [s["name"] for s in r["stations"]]
        self.assertEqual(len(names), len(set(n.lower() for n in names)))  # no duplicate names
        smooth = [s for s in r["stations"] if s["name"] == "101 SMOOTH JAZZ"]
        self.assertEqual(len(smooth), 1)
        self.assertEqual(smooth[0]["uri"], "library://radio/2")   # favorite kept, not RB dup
        self.assertEqual(smooth[0]["source"], "favorite")


if __name__ == "__main__":
    unittest.main(verbosity=2)
