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

    def test_announce_noops_when_service_part_missing(self):
        h = self._ha()
        h.announce("x", FakeSettings(tts_service="tts"))    # no dot -> no service
        h.announce("y", FakeSettings(tts_service="tts."))   # trailing dot -> empty service
        self.assertEqual(h.sent, [])

    def test_announce_survives_none_ceiling_entity(self):
        h = self._ha()
        s = FakeSettings(tts_service="tts.speak",
                         tts_data={"media_player_entity_id": "{entity}", "message": "{msg}"},
                         ceiling_entity=None)
        h.announce("hello", s)   # must not raise
        self.assertEqual(len(h.sent), 1)
        _, _, data = h.sent[0]
        self.assertEqual(data["media_player_entity_id"], "")   # None entity renders to empty string
        self.assertEqual(data["message"], "hello")

    def test_announce_propagates_send_failure(self):
        h = self._ha()
        def boom(domain, service, data):
            raise BrokenPipeError(32, "Broken pipe")
        h.call_service = boom
        s = FakeSettings(tts_service="tts.speak",
                         tts_data={"media_player_entity_id": "{entity}", "message": "{msg}"})
        with self.assertRaises(BrokenPipeError):
            h.announce("hello", s)


class SendLockTest(unittest.TestCase):
    def test_call_service_holds_lock_during_send(self):
        ha = haconn.HA("h", 1, "tok")
        held = {"during_send": None}
        class FakeSock(object):
            def sendall(self, b):
                held["during_send"] = ha._send_lock.locked()
        ha.s = FakeSock()
        ha.call_service("media_player", "volume_set", {"entity_id": "x", "volume_level": 0.1})
        self.assertTrue(held["during_send"])          # lock held while sending
        self.assertFalse(ha._send_lock.locked())      # released after


if __name__ == "__main__":
    unittest.main(verbosity=2)
