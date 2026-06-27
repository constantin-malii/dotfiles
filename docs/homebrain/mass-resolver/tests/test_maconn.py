#!/usr/bin/env python3
"""Unit tests for the MA client result handling. Run: python tests/test_maconn.py"""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from maconn import MA, WS_CMD


class FakeMA(MA):
    """Overrides cmd() so no socket is used; records calls, returns canned replies."""
    def __init__(self, reply):
        MA.__init__(self, "h", 1, "tok")
        self._reply = reply
        self.calls = []
    def cmd(self, command, **args):
        self.calls.append((command, args))
        return self._reply


class MaConnTest(unittest.TestCase):
    def test_ws_cmd_has_all_media_types(self):
        self.assertEqual(set(WS_CMD), {"artist", "album", "track", "playlist"})

    def test_library_extracts_items_from_dict_result(self):
        m = FakeMA({"result": {"items": [{"name": "A"}, {"name": "B"}]}})
        self.assertEqual(m.library("artist"), [{"name": "A"}, {"name": "B"}])
        self.assertEqual(m.calls[0][0], WS_CMD["artist"])

    def test_library_extracts_list_result(self):
        m = FakeMA({"result": [{"name": "X"}]})
        self.assertEqual(m.library("track"), [{"name": "X"}])

    def test_library_handles_empty(self):
        m = FakeMA({"result": None})
        self.assertEqual(m.library("album"), [])

    def test_play_calls_play_media_with_replace(self):
        m = FakeMA({"result": {}})
        m.play("q1", "filesystem_smb--x://track/7")
        cmd, args = m.calls[0]
        self.assertEqual(cmd, "player_queues/play_media")
        self.assertEqual(args["queue_id"], "q1")
        self.assertEqual(args["media"], "filesystem_smb--x://track/7")
        self.assertEqual(args["option"], "replace")


if __name__ == "__main__":
    unittest.main(verbosity=2)
