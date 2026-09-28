#!/usr/bin/env python3
"""MR-08c: the queue survives a spoken reply. Run: python -m unittest tests.test_queue_resume -v"""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import interaction

CLIP = "http://192.168.122.10:8123/api/tts_proxy/abc123.mp3"     # on say_internal_base: normalises to itself
CLIP2 = "http://192.168.122.10:8123/api/tts_proxy/def456.mp3"
STREAM = "builtin://radio/http://stream.example.net/live"         # a radio station added to MA by URL


def track(n, dur=240):
    return {"queue_item_id": "t%d" % n, "name": "Song %d" % n, "duration": dur,
            "media_item": {"uri": "library://track/%d" % n, "media_type": "track", "duration": dur}}


def station(uri="library://radio/4"):
    return {"queue_item_id": "st1", "name": "Radio", "duration": 0,
            "media_item": {"uri": uri, "media_type": "radio"}}


def clip_item(qid, uri, wrapper="builtin://radio/"):
    return {"queue_item_id": qid, "name": interaction.tts_id(uri), "media_item": {"uri": wrapper + uri}}


class ReplyClipUriTest(unittest.TestCase):
    def test_narrow_predicate(self):
        self.assertTrue(interaction.is_reply_clip_uri("builtin://radio/" + CLIP))
        self.assertTrue(interaction.is_reply_clip_uri("http://x/y.wav?authSig=abc"))
        self.assertTrue(interaction.is_reply_clip_uri("builtin://track/http://h/media/local/timer_chime.wav"))
        self.assertFalse(interaction.is_reply_clip_uri(STREAM))          # a station, not a clip
        self.assertFalse(interaction.is_reply_clip_uri("library://track/3"))


class ParseCaptureTest(unittest.TestCase):
    def reply(self, **q):
        base = {"state": "playing", "current_index": 2, "elapsed_time": 40.0,
                "elapsed_time_last_updated": None, "current_item": track(3)}
        base.update(q)
        return {"result": base}

    def test_track_capture(self):
        cap, why = interaction.parse_queue_capture(self.reply(), 1000.0)
        self.assertIsNone(why)
        self.assertEqual((cap["item"], cap["index"], cap["pos"], cap["duration"], cap["seekable"]),
                         ("t3", 2, 40.0, 240.0, True))

    def test_extrapolates_while_playing(self):
        cap, _ = interaction.parse_queue_capture(self.reply(elapsed_time_last_updated=993.0), 1000.0)
        self.assertAlmostEqual(cap["pos"], 47.0)
        self.assertAlmostEqual(cap["extrapolated"], 7.0)

    def test_no_extrapolation_when_paused(self):
        cap, _ = interaction.parse_queue_capture(
            self.reply(state="paused", elapsed_time_last_updated=990.0), 1000.0)
        self.assertAlmostEqual(cap["pos"], 40.0)

    def test_skewed_clock_is_not_trusted(self):
        for upd in (0.0, 1100.0):                     # delta 1000 s, or negative: two clocks disagree
            cap, _ = interaction.parse_queue_capture(self.reply(elapsed_time_last_updated=upd), 1000.0)
            self.assertAlmostEqual(cap["pos"], 40.0)

    def test_position_capped_at_duration(self):
        cap, _ = interaction.parse_queue_capture(
            self.reply(elapsed_time=239.0, elapsed_time_last_updated=990.0), 1000.0)
        self.assertEqual(cap["pos"], 240.0)

    def test_radio_not_seekable(self):
        cap, _ = interaction.parse_queue_capture(self.reply(current_item=station(), current_index=0), 1000.0)
        self.assertFalse(cap["seekable"])

    def test_failures(self):
        self.assertIsNone(interaction.parse_queue_capture({"error_code": 5}, 1.0)[0])
        self.assertIsNone(interaction.parse_queue_capture(None, 1.0)[0])
        self.assertIsNone(interaction.parse_queue_capture({"result": {"current_item": None}}, 1.0)[0])


class ClipIdentityTest(unittest.TestCase):
    def test_wrappers_stripped_exactly(self):
        self.assertEqual(interaction.clip_uri_of(clip_item("c", CLIP)), CLIP)
        self.assertEqual(interaction.clip_uri_of(clip_item("c", CLIP, "builtin://track/")), CLIP)
        self.assertEqual(interaction.clip_uri_of({"uri": CLIP}), CLIP)

    def test_tts_id(self):
        self.assertEqual(interaction.tts_id(CLIP), "abc123")
        self.assertEqual(interaction.tts_id(CLIP + "?authSig=x"), "abc123")

    def test_anchored_exact_match(self):
        items = [track(3), clip_item("c1", CLIP), track(4)]           # window read at offset 2
        self.assertEqual(interaction.anchored_clip(items, 2, 2, CLIP), ("c1", 3, None))

    def test_containment_is_not_identity(self):
        items = [track(3), clip_item("c1", CLIP + "?x=1")]
        qid, idx, why = interaction.anchored_clip(items, 2, 2, CLIP)
        self.assertIsNone(qid)
        self.assertIn("differs", why)

    def test_nothing_at_anchor(self):
        self.assertIsNone(interaction.anchored_clip([track(3)], 2, 2, CLIP)[0])

    def test_real_track_at_anchor_is_not_the_clip(self):
        self.assertIsNone(interaction.anchored_clip([track(3), track(4)], 2, 2, CLIP)[0])

    def test_name_fallback_only_without_uri(self):
        items = [track(3), {"queue_item_id": "c1", "name": "abc123", "media_item": {}}]
        self.assertEqual(interaction.anchored_clip(items, 2, 2, CLIP)[0], "c1")
        items[1]["name"] = "abc1234"
        self.assertIsNone(interaction.anchored_clip(items, 2, 2, CLIP)[0])

    def test_identical_leftover_elsewhere_is_ignored(self):
        items = [clip_item("old", CLIP), track(2), track(3), clip_item("new", CLIP)]  # offset 0, anchor 2
        self.assertEqual(interaction.anchored_clip(items, 0, 2, CLIP)[0], "new")


class SeekTargetTest(unittest.TestCase):
    def t(self, pos, dur=240, seekable=True):
        return {"pos": pos, "duration": dur, "seekable": seekable}

    def test_gates(self):
        self.assertEqual(interaction.seek_target(self.t(47.9)), 47)
        self.assertEqual(interaction.seek_target(self.t(1.5)), 0)           # < SEEK_MIN_S
        self.assertEqual(interaction.seek_target(self.t(236.0)), 0)         # within SEEK_END_MARGIN_S of the end
        self.assertEqual(interaction.seek_target(self.t(100, seekable=False)), 0)


if __name__ == "__main__":
    unittest.main()
