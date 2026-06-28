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


def _raiser(*a, **k):
    raise IOError("ws gone")


if __name__ == "__main__":
    unittest.main(verbosity=2)
