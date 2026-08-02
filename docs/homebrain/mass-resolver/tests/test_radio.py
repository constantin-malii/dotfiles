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
    ceiling_entity = "media_player.ceiling_speakers"
    radio_confirm_after_ms = 0            # no real timers in tests; the confirm tests opt in


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


class RadioCapabilityTest(unittest.TestCase):
    """Capability-driven tests: drive RadioCapability via capability.run()."""

    def _ctx(self, ma):
        return FakeCtx(ma)

    def test_capability_play_favorite_returns_commandresult(self):
        import capability, radio
        ma = FakeMA(search=[rb_item("u1", "Other Jazz")])
        r = capability.run(radio.RadioCapability(), self._ctx(ma), {"mode": "play", "station": "smooth jazz"}, "r1")
        self.assertTrue(r["ok"])
        self.assertEqual(r["intent"], "radio")
        self.assertEqual(r["metadata"]["uri"], "library://radio/2")
        self.assertEqual(r["metadata"]["source"], "favorite")
        self.assertTrue(r["metadata"]["played"])
        self.assertIsNone(r["spoken_text"])
        self.assertIsNone(r["error"])

    def test_capability_genre_radiobrowser_fallback(self):
        import capability, radio
        ma = FakeMA(browse=[rb_item("u3", "Pop Station")])
        r = capability.run(radio.RadioCapability(), self._ctx(ma), {"mode": "play", "genre": "pop"}, "r2")
        self.assertTrue(r["ok"])
        self.assertEqual(r["metadata"]["source"], "radiobrowser")
        self.assertEqual(r["metadata"]["uri"], "radiobrowser://radio/u3")
        self.assertTrue(r["metadata"]["played"])

    def test_capability_dry_run_does_not_play(self):
        import capability, radio
        ma = FakeMA()
        r = capability.run(radio.RadioCapability(), self._ctx(ma), {"mode": "play", "station": "smooth jazz", "dry_run": True}, "r3")
        self.assertTrue(r["ok"])
        self.assertFalse(r["metadata"]["played"])
        self.assertEqual(ma.played, [])
        self.assertIn("Would play", r["chat_text"])

    def test_capability_find_spoken_text_lists_top_three(self):
        import capability, radio
        ma = FakeMA(search=[rb_item("u%d" % i, "Jazz %d" % i) for i in range(6)])
        r = capability.run(radio.RadioCapability(), self._ctx(ma), {"mode": "find", "genre": "jazz"}, "r4")
        self.assertTrue(r["ok"])
        self.assertIsNotNone(r["spoken_text"])
        self.assertIn("stations", r["metadata"])
        # spoken_text should mention at most 3 stations (find_speak=3)
        self.assertLessEqual(r["spoken_text"].count(","), 2)

    def test_capability_not_found_error(self):
        import capability, radio
        ma = FakeMA(search=[])
        r = capability.run(radio.RadioCapability(), self._ctx(ma), {"mode": "play", "station": "zzz nothing"}, "r5")
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"]["code"], "not_found")
        self.assertIn("couldn't find", r["chat_text"].lower())

    def test_capability_play_failed_returns_err(self):
        import capability, radio
        ma = FakeMA(play_reply={"error_code": "x"})
        r = capability.run(radio.RadioCapability(), self._ctx(ma), {"mode": "play", "station": "jazz"}, "r6")
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"]["code"], "play_failed")
        self.assertIn("couldn't start", r["chat_text"].lower())
        self.assertFalse(r["metadata"]["played"])


class RecordingMA(FakeMA):
    """Records the query MA actually received, so alias resolution can be asserted."""
    def __init__(self, **kw):
        FakeMA.__init__(self, **kw)
        self.search_queries = []
    def cmd(self, command, **a):
        if command == "music/search":
            self.search_queries.append(a.get("search_query"))
        return FakeMA.cmd(self, command, **a)


class FakeTimer(object):
    created = []
    def __init__(self, interval, fn, args=None):
        self.interval = interval; self.fn = fn; self.args = args or []
        self.started = False; self.daemon = False
        FakeTimer.created.append(self)
    def start(self): self.started = True
    def fire(self): self.fn(*self.args)


class FakeHA(object):
    def __init__(self, state=None): self._state = state
    def get_entity_state(self, entity_id): return self._state


class AliasSearchTest(unittest.TestCase):
    """STT mangles station names ("norok" for "Radio Noroc Moldova"). MA's search returns 0 hits for
    the variant and 2 for the real name, so the alias must reach the MA search -- not only the local
    favorites list, which need not contain the station at all."""

    def _cfg(self):
        rc = dict(RC)
        rc["aliases"] = {"norok": "Radio Noroc Moldova"}
        return rc

    def test_alias_is_used_for_the_ma_search_query(self):
        ma = RecordingMA(search=[rb_item("u9", "Radio Noroc Moldova")])
        ctx = FakeCtx(ma); ctx.radio_cfg = self._cfg()
        r = radio.resolve_radio(ctx, {"mode": "play", "station": "norok"}, "rid")
        self.assertEqual(ma.search_queries, ["Radio Noroc Moldova"])   # not "norok"
        self.assertTrue(r["ok"] and r["played"])

    def test_unaliased_query_is_passed_through_unchanged(self):
        ma = RecordingMA(search=[rb_item("u1", "Some Station")])
        ctx = FakeCtx(ma); ctx.radio_cfg = self._cfg()
        radio.resolve_radio(ctx, {"mode": "play", "station": "some station"}, "rid")
        self.assertEqual(ma.search_queries, ["some station"])

    def test_station_absent_from_local_favorites_still_resolves_via_alias(self):
        # Radio Noroc Moldova lives in MA's library, NOT in radio.json favorites.
        self.assertFalse(any("noroc" in f["name"].lower() for f in RC["favorites"]))
        ma = RecordingMA(search=[rb_item("u9", "Radio Noroc Moldova")])
        ctx = FakeCtx(ma); ctx.radio_cfg = self._cfg()
        r = radio.resolve_radio(ctx, {"mode": "play", "station": "norok"}, "rid")
        self.assertEqual(r["uri"], "radiobrowser://radio/u9")


class PlayConfirmationTest(unittest.TestCase):
    """MA returning without an error_code says nothing about audio: the old RADIO PLAYING line
    claimed success it never checked, so a station that resolved and played NOTHING logged clean."""

    def setUp(self):
        FakeTimer.created = []

    class Settings(FakeSettings):
        radio_confirm_after_ms = 8000

    def _run(self, player_state):
        cap = radio.RadioCapability(timer_factory=FakeTimer)
        ma = FakeMA(search=[rb_item("u1", "Some Station")])
        ctx = FakeCtx(ma)
        ctx.settings = self.Settings()
        ctx.ha = FakeHA(player_state)
        import capability
        res = capability.run(cap, ctx, {"mode": "play", "station": "smooth jazz"}, "rid")
        self.assertTrue(res["ok"])
        self.assertEqual(len(FakeTimer.created), 1)
        self.assertTrue(FakeTimer.created[0].started)
        self.assertTrue(FakeTimer.created[0].daemon)
        self.assertAlmostEqual(FakeTimer.created[0].interval, 8.0)
        return FakeTimer.created[0]

    def test_confirmed_when_the_zone_really_plays_the_requested_uri(self):
        t = self._run({"state": "playing",
                       "attributes": {"media_content_id": "library://radio/2"}})
        with self.assertLogs("resolver", level="INFO") as cm:
            t.fire()
        self.assertTrue(any("RADIO CONFIRM" in m and "is playing" in m for m in cm.output), cm.output)

    def test_warns_when_ma_accepted_but_the_zone_is_not_playing(self):
        t = self._run({"state": "idle", "attributes": {}})
        with self.assertLogs("resolver", level="WARNING") as cm:
            t.fire()
        self.assertTrue(any("NOT confirmed" in m for m in cm.output), cm.output)

    def test_warns_when_a_different_station_is_playing(self):
        t = self._run({"state": "playing",
                       "attributes": {"media_content_id": "library://radio/99"}})
        with self.assertLogs("resolver", level="WARNING") as cm:
            t.fire()
        self.assertTrue(any("NOT confirmed" in m for m in cm.output), cm.output)

    def test_confirm_read_failure_is_logged_not_raised(self):
        class BoomHA(object):
            def get_entity_state(self, e): raise IOError("ha down")
        cap = radio.RadioCapability(timer_factory=FakeTimer)
        ma = FakeMA(search=[rb_item("u1", "S")])
        ctx = FakeCtx(ma); ctx.settings = self.Settings(); ctx.ha = BoomHA()
        import capability
        capability.run(cap, ctx, {"mode": "play", "station": "smooth jazz"}, "rid")
        with self.assertLogs("resolver", level="WARNING") as cm:
            FakeTimer.created[0].fire()
        self.assertTrue(any("RADIO CONFIRM" in m and "read failed" in m for m in cm.output))

    def test_zero_disables_the_check(self):
        cap = radio.RadioCapability(timer_factory=FakeTimer)
        ma = FakeMA(search=[rb_item("u1", "S")])
        ctx = FakeCtx(ma); ctx.ha = FakeHA(None)      # FakeSettings default: 0 -> disabled
        import capability
        capability.run(cap, ctx, {"mode": "play", "station": "smooth jazz"}, "rid")
        self.assertEqual(FakeTimer.created, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
