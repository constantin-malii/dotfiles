#!/usr/bin/env python3
"""Run: python tests/test_speaker.py"""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import speaker


class FakeHA(object):
    def __init__(self): self.said = []; self.connected = False; self.fail_connect = False
    def connect(self):
        if self.fail_connect: raise IOError("no ha")
        self.connected = True
    def announce(self, text, settings): self.said.append(text)
    def close(self): pass


class FakeSettings(object):
    announce_failures = True


class AnnounceStampTest(unittest.TestCase):
    """interaction._say reads these to detect a second voice on the same turn."""

    def test_successful_announce_stamps_ts_and_text(self):
        ha = FakeHA(); sp = speaker.Speaker(FakeSettings(), lambda: ha, clock=lambda: 4242.0)
        self.assertIsNone(sp.last_announce_ts)
        sp.speak("hello")
        self.assertAlmostEqual(sp.last_announce_ts, 4242.0)
        self.assertEqual(sp.last_announce_text, "hello")

    def test_empty_text_does_not_stamp(self):
        ha = FakeHA(); sp = speaker.Speaker(FakeSettings(), lambda: ha, clock=lambda: 4242.0)
        sp.speak("")
        self.assertIsNone(sp.last_announce_ts)

    def test_stamp_survives_the_retry_path(self):
        bad = FakeHA(); bad.fail_connect = True
        good = FakeHA(); box = {"first": True}

        def factory():
            if box["first"]:
                box["first"] = False
                return bad
            return good
        sp = speaker.Speaker(FakeSettings(), factory, clock=lambda: 7.0)
        sp.speak("retried")
        self.assertEqual(good.said, ["retried"])
        self.assertAlmostEqual(sp.last_announce_ts, 7.0)

    def test_failed_announce_does_not_stamp(self):
        class DeadHA(FakeHA):
            def announce(self, text, settings): raise IOError("nope")
        sp = speaker.Speaker(FakeSettings(), lambda: DeadHA(), clock=lambda: 9.0)
        sp.speak("never heard")
        self.assertIsNone(sp.last_announce_ts)


class SpeakerTest(unittest.TestCase):
    def test_speak_connects_and_announces(self):
        ha = FakeHA(); sp = speaker.Speaker(FakeSettings(), lambda: ha)
        sp.speak("hello")
        self.assertEqual(ha.said, ["hello"]); self.assertTrue(ha.connected)

    def test_empty_text_is_noop(self):
        ha = FakeHA(); sp = speaker.Speaker(FakeSettings(), lambda: ha)
        sp.speak(None); sp.speak("")
        self.assertEqual(ha.said, [])

    def test_reuses_connection(self):
        ha = FakeHA(); sp = speaker.Speaker(FakeSettings(), lambda: ha)
        sp.speak("a"); sp.speak("b")
        self.assertEqual(ha.said, ["a", "b"])

    def test_reconnects_after_failure(self):
        bad = FakeHA(); good = FakeHA(); box = {"first": True}
        def factory():
            if box["first"]:
                box["first"] = False; bad.announce = _raiser; return bad
            return good
        sp = speaker.Speaker(FakeSettings(), factory)
        sp.speak("x")  # first announce raises -> reconnect -> good
        self.assertEqual(good.said, ["x"])

    def test_real_announce_failure_triggers_reconnect(self):
        import haconn
        made = []
        def factory():
            h = haconn.HA("host", 1, "tok"); h.sent = []
            if not made:                       # first HA: send dies (dead socket)
                def boom(domain, service, data):
                    raise BrokenPipeError(32, "Broken pipe")
                h.call_service = boom
            else:                              # reconnect HA: send works
                h.call_service = lambda d, s, dd: h.sent.append((d, s, dd))
            h.connect = lambda: None
            made.append(h)
            return h
        sp = speaker.Speaker(_RealishSettings(), factory)
        sp.speak("hello")
        self.assertEqual(len(made), 2)                 # exactly one reconnect
        self.assertEqual(len(made[1].sent), 1)         # second HA actually announced

    def test_both_attempts_fail_no_infinite_loop(self):
        import haconn
        made = []
        def factory():
            h = haconn.HA("host", 1, "tok")
            def boom(domain, service, data):
                raise BrokenPipeError(32, "Broken pipe")
            h.call_service = boom; h.connect = lambda: None
            made.append(h); return h
        sp = speaker.Speaker(_RealishSettings(), factory)
        sp.speak("hello")                              # must not raise, must not loop
        self.assertEqual(len(made), 2)                 # tried twice, then gave up
        self.assertIsNone(sp.ha)                       # cleared for a fresh attempt next time


class _RealishSettings(object):
    announce_failures = True
    tts_service = "tts.speak"
    tts_data = {"media_player_entity_id": "{entity}", "message": "{msg}"}
    ceiling_entity = "media_player.ceiling_speakers"


def _raiser(*a, **k):
    raise IOError("ws gone")


if __name__ == "__main__":
    unittest.main(verbosity=2)
