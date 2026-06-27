#!/usr/bin/env python3
"""Unit tests for the dispatcher + failure feedback. Run: python tests/test_core.py"""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import core


class FakeSettings(object):
    provider_preference = ["filesystem_smb"]
    type_order = ["artist", "album", "track", "playlist"]
    queue_id = "q1"
    dry_run = False
    announce_failures = True
    ceiling_entity = "media_player.ceiling_speakers"
    tts_service = "tts.speak"
    tts_data = {}


class FakeHA(object):
    def __init__(self):
        self.announced = []
    def announce(self, message, settings):
        self.announced.append(message)


class FakeMA(object):
    def __init__(self, data=None, sync_ok=True):
        self._data = data or {}
        self.synced = False
    def connect(self):
        pass
    def library(self, mt):
        return self._data.get(mt, [])
    def play(self, q, uri, option="replace"):
        return {"result": {}}
    def sync(self):
        self.synced = True
    def close(self):
        pass


def smb_item(name, item_id):
    return {"name": name, "provider_mappings": [
        {"provider_domain": "filesystem_smb", "provider_instance": "fs--x",
         "available": True, "item_id": item_id}]}


class CoreTest(unittest.TestCase):
    def _ctx(self, ma):
        ha = FakeHA()
        ctx = core.Ctx(ma_factory=lambda: ma, ha=ha, settings=FakeSettings(),
                       radio_cfg={}, news_cfg={})
        return ctx, ha

    def test_music_success_does_not_announce(self):
        ctx, ha = self._ctx(FakeMA({"artist": [smb_item("Rammstein", "1")]}))
        r = core.dispatch(ctx, "music", {"query": "Rammstein", "media_type": "artist"})
        self.assertTrue(r["ok"])
        self.assertEqual(ha.announced, [])

    def test_music_failure_announces_honest_line(self):
        ctx, ha = self._ctx(FakeMA({"artist": [], "album": [], "track": [], "playlist": []}))
        r = core.dispatch(ctx, "music", {"query": "Nonexistent"})
        self.assertFalse(r["ok"])
        self.assertEqual(len(ha.announced), 1)
        self.assertIn("couldn't find", ha.announced[0].lower())

    def test_stub_intent_announces_not_available(self):
        ctx, ha = self._ctx(FakeMA())
        r = core.dispatch(ctx, "radio", {"country": "Romania"})
        self.assertFalse(r["ok"])
        self.assertEqual(len(ha.announced), 1)
        self.assertIn("yet", ha.announced[0].lower())

    def test_sync_runs_and_never_announces(self):
        ma = FakeMA()
        ctx, ha = self._ctx(ma)
        r = core.dispatch(ctx, "sync", {"source": "lidarr"})
        self.assertTrue(r["ok"])
        self.assertTrue(ma.synced)
        self.assertEqual(ha.announced, [])

    def test_unknown_intent_is_safe(self):
        ctx, ha = self._ctx(FakeMA())
        r = core.dispatch(ctx, "teleport", {})
        self.assertFalse(r["ok"])
        self.assertEqual(r["reason"], "unknown intent")

    def test_announce_suppressed_when_flag_off(self):
        ma = FakeMA({"artist": [], "album": [], "track": [], "playlist": []})
        ctx, ha = self._ctx(ma)
        ctx.settings.announce_failures = False
        core.dispatch(ctx, "music", {"query": "Nope"})
        self.assertEqual(ha.announced, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
