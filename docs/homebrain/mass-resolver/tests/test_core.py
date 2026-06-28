#!/usr/bin/env python3
"""Unit tests for core.dispatch (returns CommandResult, speaks via Speaker). Run: python tests/test_core.py"""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import core


class FakeSpeaker(object):
    def __init__(self):
        self.said = []
    def speak(self, text):
        if text:
            self.said.append(text)


class FakeSettings(object):
    provider_preference = ["filesystem_smb"]
    type_order = ["artist", "album", "track", "playlist"]
    queue_id = "q1"
    dry_run = False
    announce_failures = True
    ceiling_entity = "media_player.ceiling_speakers"
    tts_service = "tts.speak"
    tts_data = {}


class FakeMA(object):
    def __init__(self, data=None, play_reply=None, browse=None, search=None):
        self._data = data or {}
        self.play_reply = play_reply or {"result": {}}
        self._browse = browse or []
        self._search = search or []
        self.synced = False
        self.s = None
    def connect(self):
        self.s = object()
    def close(self):
        self.s = None
    def library(self, mt):
        return self._data.get(mt, [])
    def play(self, q, uri, option="replace"):
        return self.play_reply
    def sync(self):
        self.synced = True
    def cmd(self, command, **a):
        if command == "music/browse":
            return {"result": {"items": self._browse}}
        if command == "music/search":
            return {"result": {"radio": self._search}}
        return None


def smb_item(name, item_id):
    return {"name": name, "provider_mappings": [
        {"provider_domain": "filesystem_smb", "provider_instance": "filesystem_smb--kd66vco4",
         "available": True, "item_id": item_id}]}


def rb_item(uuid, name):
    return {"item_id": uuid, "provider": "radiobrowser", "name": name,
            "uri": "radiobrowser://radio/" + uuid, "media_type": "radio",
            "provider_mappings": [{"provider_domain": "radiobrowser", "available": True}]}


RC = {
    "favorites": [
        {"name": "101 SMOOTH JAZZ", "uri": "library://radio/2", "country": "us",
         "language": "en", "genres": ["jazz"]},
    ],
    "aliases": {}, "country_codes": {}, "languages": {},
    "genre_synonyms": {"jazz": ["jazz"]},
    "defaults": {"find_internal": 5, "find_speak": 3},
}


class FakeCtx(object):
    def __init__(self, ma, speaker=None, settings=None, radio_cfg=None, announce_failures=True):
        self._ma = ma
        s = settings or FakeSettings()
        s.announce_failures = announce_failures
        self.settings = s
        self.radio_cfg = radio_cfg or RC
        self.news_cfg = {}
        self.speaker = speaker or FakeSpeaker()
    def ma_factory(self):
        return self._ma


class CoreDispatchTest(unittest.TestCase):

    # --- music success ---
    def test_music_success_ok_no_speak(self):
        ma = FakeMA(data={"artist": [smb_item("Rammstein", "1")]})
        spk = FakeSpeaker()
        ctx = FakeCtx(ma, speaker=spk)
        r = core.dispatch(ctx, "music", {"query": "Rammstein", "media_type": "artist"})
        self.assertTrue(r["ok"])
        self.assertIsNone(r["error"])
        self.assertEqual(spk.said, [])

    # --- music not_found ---
    def test_music_not_found_speaks_honest_line(self):
        ma = FakeMA(data={"artist": [], "album": [], "track": [], "playlist": []})
        spk = FakeSpeaker()
        ctx = FakeCtx(ma, speaker=spk)
        r = core.dispatch(ctx, "music", {"query": "Nonexistent"})
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"]["code"], "not_found")
        self.assertEqual(len(spk.said), 1)
        self.assertIn("couldn't find", spk.said[0].lower())

    # --- radio find speaks the list ---
    def test_radio_find_speaks_list(self):
        ma = FakeMA(search=[rb_item("u%d" % i, "Jazz %d" % i) for i in range(4)])
        spk = FakeSpeaker()
        ctx = FakeCtx(ma, speaker=spk)
        r = core.dispatch(ctx, "radio", {"mode": "find", "genre": "jazz"})
        self.assertTrue(r["ok"])
        self.assertEqual(len(spk.said), 1)
        self.assertIn("found", spk.said[0].lower())

    # --- radio play success silent ---
    def test_radio_play_success_no_speak(self):
        ma = FakeMA(search=[rb_item("u1", "Jazz FM")])
        spk = FakeSpeaker()
        ctx = FakeCtx(ma, speaker=spk)
        r = core.dispatch(ctx, "radio", {"mode": "play", "station": "smooth jazz"})
        self.assertTrue(r["ok"])
        self.assertEqual(spk.said, [])

    # --- sync ---
    def test_sync_ok_no_speak(self):
        ma = FakeMA()
        spk = FakeSpeaker()
        ctx = FakeCtx(ma, speaker=spk)
        r = core.dispatch(ctx, "sync", {})
        self.assertTrue(r["ok"])
        self.assertEqual(r["intent"], "sync")
        self.assertTrue(ma.synced)
        self.assertEqual(spk.said, [])

    # --- unknown intent ---
    def test_unknown_intent_err_invalid_input_no_speak(self):
        ma = FakeMA()
        spk = FakeSpeaker()
        ctx = FakeCtx(ma, speaker=spk)
        r = core.dispatch(ctx, "teleport", {})
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"]["code"], "invalid_input")
        self.assertEqual(spk.said, [])

    # --- stub intent (news) ---
    def test_stub_intent_not_implemented_speaks(self):
        ma = FakeMA()
        spk = FakeSpeaker()
        ctx = FakeCtx(ma, speaker=spk)
        r = core.dispatch(ctx, "news", {"country": "Romania"})
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"]["code"], "not_implemented")
        self.assertEqual(len(spk.said), 1)
        self.assertIn("yet", spk.said[0].lower())

    # --- announce_failures=False suppresses failure speech ---
    def test_announce_failures_false_suppresses_speech(self):
        ma = FakeMA(data={"artist": [], "album": [], "track": [], "playlist": []})
        spk = FakeSpeaker()
        ctx = FakeCtx(ma, speaker=spk, announce_failures=False)
        core.dispatch(ctx, "music", {"query": "Nope"})
        self.assertEqual(spk.said, [])

    # --- Ctx has speaker attribute ---
    def test_ctx_has_speaker_attribute(self):
        ma = FakeMA()
        spk = FakeSpeaker()
        ctx = core.Ctx(ma_factory=lambda: ma, ha=None, settings=FakeSettings(),
                       radio_cfg=RC, news_cfg={}, speaker=spk)
        self.assertIs(ctx.speaker, spk)

    # --- Ctx speaker defaults to None (backwards compat) ---
    def test_ctx_speaker_defaults_none(self):
        ma = FakeMA()
        ctx = core.Ctx(ma_factory=lambda: ma, ha=None, settings=FakeSettings(),
                       radio_cfg=RC, news_cfg={})
        self.assertIsNone(ctx.speaker)


if __name__ == "__main__":
    unittest.main(verbosity=2)
