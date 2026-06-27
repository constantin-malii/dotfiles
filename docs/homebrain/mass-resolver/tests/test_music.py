#!/usr/bin/env python3
"""Unit tests for resolve_music. Run: python tests/test_music.py"""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import music


class FakeSettings(object):
    provider_preference = ["filesystem_smb"]
    type_order = ["artist", "album", "track", "playlist"]
    queue_id = "q1"
    dry_run = False


class FakeMA(object):
    """library() returns canned items per type; play() records and returns a reply."""
    def __init__(self, play_reply=None):
        self.play_reply = play_reply or {"result": {}}
        self.played = []
        self._data = {}
    def set(self, data):
        self._data = data; return self
    def library(self, media_type):
        return self._data.get(media_type, [])
    def play(self, queue_id, uri, option="replace"):
        self.played.append((queue_id, uri, option)); return self.play_reply


def smb_item(name, item_id):
    return {"name": name, "provider_mappings": [
        {"provider_domain": "filesystem_smb", "provider_instance": "filesystem_smb--kd66vco4",
         "available": True, "item_id": item_id}]}


def ytm_item(name, item_id):
    return {"name": name, "uri": "ytmusic://x/" + item_id, "provider_mappings": [
        {"provider_domain": "ytmusic", "provider_instance": "ytmusic--7MLPoF6b",
         "available": True, "item_id": item_id}]}


class MusicTest(unittest.TestCase):
    def test_plays_local_artist_match(self):
        ma = FakeMA().set({"artist": [smb_item("Rammstein", "42")]})
        r = music.resolve_music(ma, "Rammstein", "artist", FakeSettings(), "rid1")
        self.assertTrue(r["ok"])
        self.assertTrue(r["played"])
        self.assertEqual(r["provider"], "filesystem_smb")
        self.assertEqual(r["uri"], "filesystem_smb--kd66vco4://artist/42")
        self.assertEqual(ma.played[0][1], r["uri"])

    def test_rejects_non_preferred_provider(self):
        ma = FakeMA().set({"artist": [ytm_item("Rammstein", "9")],
                               "album": [], "track": [], "playlist": []})
        r = music.resolve_music(ma, "Rammstein", "artist", FakeSettings(), "rid2")
        self.assertFalse(r["ok"])
        self.assertEqual(r["reason"], "no local match")
        self.assertIn("couldn't find", r["spoken"].lower())
        self.assertEqual(ma.played, [])

    def test_falls_back_to_other_types_when_hint_wrong(self):
        ma = FakeMA().set({"artist": [], "album": [], "track": [smb_item("Du Hast", "7")], "playlist": []})
        r = music.resolve_music(ma, "Du Hast", "artist", FakeSettings(), "rid3")
        self.assertTrue(r["ok"])
        self.assertEqual(r["media_type"], "track")

    def test_dry_run_does_not_play(self):
        s = FakeSettings(); s.dry_run = True
        ma = FakeMA().set({"artist": [smb_item("Rammstein", "42")]})
        r = music.resolve_music(ma, "Rammstein", "artist", s, "rid4")
        self.assertTrue(r["ok"])
        self.assertFalse(r["played"])
        self.assertEqual(ma.played, [])

    def test_play_error_reports_honest_failure(self):
        ma = FakeMA(play_reply={"error_code": "x", "details": "boom"}).set(
            {"artist": [smb_item("Rammstein", "42")]})
        r = music.resolve_music(ma, "Rammstein", "artist", FakeSettings(), "rid5")
        self.assertFalse(r["ok"])
        self.assertEqual(r["reason"], "play failed")
        self.assertIn("couldn't start", r["spoken"].lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
