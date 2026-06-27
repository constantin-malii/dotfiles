#!/usr/bin/env python3
"""Unit tests for the HA client service-call/announce composition. Run: python tests/test_haconn.py"""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import haconn


class FakeSettings(object):
    def __init__(self, tts_service="", tts_data=None, ceiling_entity="media_player.ceiling_speakers"):
        self.tts_service = tts_service
        self.tts_data = tts_data or {}
        self.ceiling_entity = ceiling_entity


class HaConnTest(unittest.TestCase):
    def _ha(self):
        h = haconn.HA("host", 1, "tok")
        h.sent = []
        h.call_service = lambda domain, service, data: h.sent.append((domain, service, data))
        return h

    def test_call_service_split_used_by_announce(self):
        h = self._ha()
        s = FakeSettings(tts_service="tts.speak",
                         tts_data={"entity_id": "tts.home", "media_player_entity_id": "{entity}", "message": "{msg}"})
        h.announce("Couldn't find Engel locally.", s)
        self.assertEqual(len(h.sent), 1)
        domain, service, data = h.sent[0]
        self.assertEqual(domain, "tts")
        self.assertEqual(service, "speak")
        self.assertEqual(data["message"], "Couldn't find Engel locally.")
        self.assertEqual(data["media_player_entity_id"], "media_player.ceiling_speakers")
        self.assertEqual(data["entity_id"], "tts.home")

    def test_announce_noops_when_no_tts_service(self):
        h = self._ha()
        h.announce("anything", FakeSettings(tts_service=""))
        self.assertEqual(h.sent, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
