#!/usr/bin/env python3
"""Unit tests for the HA-event -> dispatch mapping. Run: python tests/test_resolver.py"""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import resolver, core, speaker


class FakeSettings(object):
    event_type = "mass_play_request"
    sync_event_type = "mass_sync_request"
    radio_event_type = "mass_radio_request"
    ma_host = "127.0.0.1"
    ma_port = 8095
    ha_host = "127.0.0.1"
    ha_port = 8123
    queue_id = "testqueue"
    announce_failures = True
    provider_preference = ["filesystem_smb"]
    type_order = ["artist", "album", "track", "playlist"]
    dry_run = False
    http_host = "192.168.122.1"
    http_port = 8770


class EventMapTest(unittest.TestCase):
    def test_play_event_maps_to_music_intent(self):
        ev = {"event_type": "mass_play_request", "data": {"query": "Engel", "media_type": "track"}}
        call = resolver.event_to_call(FakeSettings(), ev)
        self.assertEqual(call, ("music", {"query": "Engel", "media_type": "track"}))

    def test_play_event_without_media_type_defaults_empty(self):
        ev = {"event_type": "mass_play_request", "data": {"query": "Engel"}}
        intent, params = resolver.event_to_call(FakeSettings(), ev)
        self.assertEqual(intent, "music")
        self.assertEqual(params["media_type"], "")

    def test_play_event_without_query_is_ignored(self):
        ev = {"event_type": "mass_play_request", "data": {}}
        self.assertIsNone(resolver.event_to_call(FakeSettings(), ev))

    def test_sync_event_maps_to_sync_intent(self):
        ev = {"event_type": "mass_sync_request", "data": {"source": "lidarr"}}
        self.assertEqual(resolver.event_to_call(FakeSettings(), ev), ("sync", {"source": "lidarr"}))

    def test_unknown_event_returns_none(self):
        ev = {"event_type": "something_else", "data": {}}
        self.assertIsNone(resolver.event_to_call(FakeSettings(), ev))

    def test_radio_play_event_maps(self):
        ev = {"event_type": "mass_radio_request", "data": {"mode": "play", "country": "Romania"}}
        intent, params = resolver.event_to_call(FakeSettings(), ev)
        self.assertEqual(intent, "radio")
        self.assertEqual(params["mode"], "play")
        self.assertEqual(params["country"], "Romania")
        self.assertEqual(set(params.keys()), {"mode", "country"})

    def test_radio_event_defaults_mode_play(self):
        ev = {"event_type": "mass_radio_request", "data": {"genre": "jazz"}}
        _, params = resolver.event_to_call(FakeSettings(), ev)
        self.assertEqual(params["mode"], "play")
        self.assertEqual(params["genre"], "jazz")

    def test_radio_find_event_maps(self):
        ev = {"event_type": "mass_radio_request", "data": {"mode": "find", "genre": "jazz", "dry_run": True}}
        _, params = resolver.event_to_call(FakeSettings(), ev)
        self.assertEqual(params["mode"], "find")
        self.assertTrue(params["dry_run"])


class MakeCtxTest(unittest.TestCase):
    def test_make_ctx_wires_speaker(self):
        ctx = resolver.make_ctx(FakeSettings(), "matok", "hatok", {}, {})
        self.assertIsNotNone(ctx.speaker)
        self.assertIsInstance(ctx.speaker, speaker.Speaker)
        self.assertTrue(callable(ctx.ma_factory))

    def test_make_ctx_dispatch_unknown_is_safe(self):
        ctx = resolver.make_ctx(FakeSettings(), "matok", "hatok", {}, {})
        result = core.dispatch(ctx, "teleport", {})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "invalid_input")


class HttpConfigDefaultsTest(unittest.TestCase):
    def test_http_defaults_in_fake_settings(self):
        s = FakeSettings()
        self.assertEqual(s.http_port, 8770)
        self.assertEqual(s.http_host, "192.168.122.1")

    def test_load_settings_http_defaults(self):
        import tempfile, shutil
        d = tempfile.mkdtemp(prefix="cfg_")
        try:
            import config
            s = config.load_settings(d)
            self.assertEqual(s.http_port, 8770)
            self.assertEqual(s.http_host, "192.168.122.1")
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
