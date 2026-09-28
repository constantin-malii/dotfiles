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


class PlaylistTracksTest(unittest.TestCase):
    def _ma(self, reply):
        m = MA("h", 1, "t")                 # test_maconn imports `from maconn import MA, WS_CMD`
        m.calls = []
        def cmd(command, **a):
            m.calls.append((command, a)); return reply
        m.cmd = cmd
        return m

    def test_list_result(self):
        m = self._ma({"result": [{"name": "a"}, {"name": "b"}]})
        self.assertEqual([t["name"] for t in m.playlist_tracks(28)], ["a", "b"])
        self.assertEqual(m.calls[0], ("music/playlists/playlist_tracks",
                                      {"item_id": "28", "provider_instance_id_or_domain": "library"}))

    def test_items_dict_result_and_cap(self):
        m = self._ma({"result": {"items": [{"name": str(i)} for i in range(10)]}})
        self.assertEqual(len(m.playlist_tracks("28", limit=3)), 3)

    def test_no_reply_is_empty(self):
        self.assertEqual(self._ma(None).playlist_tracks(28), [])


class QueueHelpersTest(unittest.TestCase):
    def _ma(self, reply=None):
        m = MA("h", 1, "t")
        m.calls = []
        def cmd(command, **a):
            m.calls.append((command, a)); return reply
        m.cmd = cmd
        return m

    def test_queue_state(self):
        m = self._ma({"result": {"state": "playing"}})
        self.assertEqual(m.queue_state("q1"), {"result": {"state": "playing"}})
        self.assertEqual(m.calls, [("player_queues/get", {"queue_id": "q1"})])

    def test_queue_items_window(self):
        m = self._ma({"result": []})
        m.queue_items("q1", offset=55, limit=5)
        self.assertEqual(m.calls, [("player_queues/items", {"queue_id": "q1", "offset": 55, "limit": 5})])

    def test_play_index_with_seek_position(self):
        m = self._ma({"result": None})
        m.play_index("q1", "abc", seek_position=47)
        self.assertEqual(m.calls, [("player_queues/play_index",
                                    {"queue_id": "q1", "index": "abc", "seek_position": 47})])

    def test_play_index_default_from_start(self):
        m = self._ma({"result": None})
        m.play_index("q1", "abc")
        self.assertEqual(m.calls[0][1]["seek_position"], 0)

    def test_delete_item(self):
        m = self._ma({"result": None})
        m.delete_item("q1", "c9")
        self.assertEqual(m.calls, [("player_queues/delete_item", {"queue_id": "q1", "item_id_or_index": "c9"})])


if __name__ == "__main__":
    unittest.main(verbosity=2)
