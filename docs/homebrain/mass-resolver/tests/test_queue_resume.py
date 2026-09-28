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


import capability
from tests.test_interaction import FakeHA, FakeSettings, FakeSleeper, FakeTimer

ZONE = "media_player.ceiling_speakers"


class FakeQueue(object):
    """MA's queue as measured (design 3): enqueue=play inserts after current and plays it (also when paused);
    a clip plays for `clip_play_reads` HA reads then goes idle (or never, with clip_never_idle); deleting the
    current item is a no-op; play_index by id at a position. `lag` = confirming reads before a play_index shows.
    `fail[name]` = list consumed per call: None (normal), "error", or an Exception to raise."""
    def __init__(self, items, current=0, state="playing", elapsed=47.0, last_upd=None):
        self.items = list(items); self.current = current; self.state = state
        self.elapsed = elapsed; self.last_upd = last_upd
        self.calls = []; self.fail = {}; self.lag = 0; self._pending = None
        self.clip_reads = 0; self.clip_play_reads = 1; self.clip_never_idle = False; self.n = 0
        self.enqueue_raises_after_landing = False
        self.enqueue_raises_without_landing = False
        self.clip_lands_after_play_index = None      # a clip URL that lands only after play_index
        self.first_wrapper = None                    # store the next clip under this wrapper (identity miss)

    def _f(self, name):
        seq = self.fail.get(name)
        if not seq:
            return None
        f = seq.pop(0)
        if isinstance(f, Exception):
            raise f
        if f == "error":
            return {"error_code": 999, "details": "boom"}
        return None

    def _insert_clip(self, uri):
        self.n += 1
        wrapper, self.first_wrapper = (self.first_wrapper or "builtin://radio/"), None
        self.items.insert(self.current + 1, clip_item("c%d" % self.n, uri, wrapper))
        self.current += 1; self.state = "playing"; self.clip_reads = self.clip_play_reads

    def cur(self):
        return self.items[self.current] if 0 <= self.current < len(self.items) else None

    # HA side
    def ha_play_media(self, data):
        uri = data["media_id"]
        if data.get("enqueue") == "play":
            self.calls.append(("enqueue", uri))
            if self.enqueue_raises_without_landing:
                raise OSError("REST timeout; the enqueue never landed")
            self._insert_clip(uri)
            if self.enqueue_raises_after_landing:
                raise OSError("REST timeout after the enqueue landed")
        else:
            self.calls.append(("replace", uri))
            self.n += 1
            self.items = [clip_item("r%d" % self.n, uri) if interaction.is_reply_clip_uri(uri) else
                          {"queue_item_id": "r%d" % self.n, "name": uri, "media_item": {"uri": uri}}]
            self.current = 0; self.state = "playing"; self.clip_reads = self.clip_play_reads

    def ha_state(self):
        ci = self.cur()
        mid = ((ci or {}).get("media_item") or {}).get("uri") or ""
        if ci is not None and interaction.is_reply_clip_uri(mid) and self.state == "playing":
            if self.clip_reads > 0:
                self.clip_reads -= 1
            elif not self.clip_never_idle:
                self.state = "idle"
        return self.state, mid

    # MA side
    def queue_state(self):
        r = self._f("queue_state")
        if r is not None:
            return r
        if self._pending is not None:
            if self.lag > 0:
                self.lag -= 1
            else:
                self.current, self._pending = self._pending, None
        return {"result": {"state": self.state, "current_index": self.current, "elapsed_time": self.elapsed,
                           "elapsed_time_last_updated": self.last_upd, "current_item": self.cur()}}

    def queue_items(self, offset, limit):
        r = self._f("queue_items")
        if r is not None:
            return r
        return {"result": self.items[offset:offset + limit]}

    def play_index(self, item_id, seek_position):
        self.calls.append(("play_index", item_id, seek_position))
        r = self._f("play_index")
        if r is not None:
            return r
        idx = [i for i, x in enumerate(self.items) if x["queue_item_id"] == item_id][0]
        self.state = "playing"; self.elapsed = float(seek_position)
        if self.lag:
            self._pending = idx
        else:
            self.current = idx
        if self.clip_lands_after_play_index:
            uri, self.clip_lands_after_play_index = self.clip_lands_after_play_index, None
            self._insert_clip(uri)
        return {"result": None}

    def delete_item(self, item_id):
        self.calls.append(("delete", item_id))
        r = self._f("delete_item")
        if r is not None:
            return r
        idx = [i for i, x in enumerate(self.items) if x["queue_item_id"] == item_id][0]
        if idx == self.current:
            return {"result": None}                  # measured: deleting the current item is a no-op
        del self.items[idx]
        if idx < self.current:
            self.current -= 1
        return {"result": None}

    def ids(self):
        return [x["queue_item_id"] for x in self.items]


class FakeQueueMA(object):
    def __init__(self, q):
        self.q = q; self.s = None
    def connect(self): self.s = object()
    def close(self): self.s = None
    def queue_state(self, queue_id): return self.q.queue_state()
    def queue_items(self, queue_id, offset=0, limit=50): return self.q.queue_items(offset, limit)
    def play_index(self, queue_id, queue_item_id, seek_position=0): return self.q.play_index(queue_item_id, seek_position)
    def delete_item(self, queue_id, queue_item_id): return self.q.delete_item(queue_item_id)


class QueueHA(FakeHA):
    """HA whose ceiling entity reflects the FakeQueue, and whose services act on it."""
    def __init__(self, q, volume=0.3):
        FakeHA.__init__(self)
        self.q = q; self.volume = volume; self.volume_boom = False
    def get_entity_state(self, entity_id, timeout=None):
        self.state_timeouts.append(timeout)
        st, mid = self.q.ha_state()
        return {"state": st, "attributes": {"volume_level": self.volume, "media_content_id": mid}}
    def call_service_rest(self, domain, service, data, timeout=5):
        self.calls.append((domain, service, data)); self.timeouts.append((service, timeout))
        if (domain, service) == ("music_assistant", "play_media"):
            self.q.ha_play_media(data)
        elif service == "media_pause":
            self.q.state = "paused"
        elif service == "media_play":
            self.q.state = "playing"
        elif service == "volume_set":
            if self.volume_boom and abs(data["volume_level"] - 0.40) < 0.001:
                raise OSError("volume_set failed")
            self.volume = data["volume_level"]


class QSettings(FakeSettings):
    queue_id = "q1"
    say_queue_resume = True


class QCtx(object):
    def __init__(self, ha, q):
        self.ha = ha; self.settings = QSettings(); self.mas = []
        def factory():
            m = FakeQueueMA(q); self.mas.append(m); return m
        self.ma_factory = factory


def new_cap(hook=None):
    return interaction.InteractionCapability(timer_factory=FakeTimer, clock=lambda: 1000.0,
                                             sleeper=FakeSleeper(hook))


def say(cap, ctx, uri=CLIP, uris=None, rid="rid1"):
    p = {"mode": "say", "uri": uri}
    if uris:
        p["uris"] = uris
    return capability.run(cap, ctx, p, rid)


def ctx_for(q):
    return QCtx(QueueHA(q), q)


class QueueModeTest(unittest.TestCase):
    def test_multi_item_queue_survives_and_resumes_at_position(self):
        q = FakeQueue([track(i) for i in range(1, 9)], current=2, elapsed=47.0)
        ctx = ctx_for(q)
        r = say(new_cap(), ctx)
        self.assertTrue(r["ok"])
        self.assertEqual(q.ids(), ["t%d" % i for i in range(1, 9)])      # original 8, no clip
        self.assertEqual(q.cur()["queue_item_id"], "t3")
        self.assertEqual([c for c in q.calls if c[0] == "play_index"], [("play_index", "t3", 47)])
        self.assertEqual([c for c in q.calls if c[0] == "replace"], [])
        self.assertEqual([c for c in q.calls if c[0] == "enqueue"], [("enqueue", CLIP)])
        self.assertEqual(r["metadata"]["resume"], "queue")
        self.assertEqual(r["metadata"]["clips_deleted"], 1)
        self.assertTrue(r["metadata"]["replayed"])
        self.assertTrue(ctx.mas and all(m.s is None for m in ctx.mas))   # every phase connection closed

    def test_position_extrapolated_from_last_update(self):
        q = FakeQueue([track(i) for i in range(1, 4)], current=1, elapsed=40.0, last_upd=993.0)
        say(new_cap(), ctx_for(q))
        self.assertEqual([c for c in q.calls if c[0] == "play_index"], [("play_index", "t2", 47)])

    def test_long_queue_window(self):
        q = FakeQueue([track(i) for i in range(1, 61)], current=55)
        say(new_cap(), ctx_for(q))
        self.assertEqual(q.ids(), ["t%d" % i for i in range(1, 61)])
        self.assertEqual(q.cur()["queue_item_id"], "t56")

    def test_identical_leftover_clip_untouched_and_counted(self):
        items = [track(1), clip_item("old", CLIP), track(2), track(3), track(4)]
        q = FakeQueue(items, current=3)
        with self.assertLogs("resolver", "INFO") as lg:
            say(new_cap(), ctx_for(q))
        self.assertEqual(q.ids(), ["t1", "old", "t2", "t3", "t4"])       # new clip deleted, leftover kept
        self.assertTrue(any("stale_reply_clips=1" in m for m in lg.output))
        self.assertNotIn(("delete", "old"), q.calls)

    def test_seek_gates(self):
        for pos, want in ((1.0, 0), (236.0, 0)):
            q = FakeQueue([track(1), track(2)], current=0, elapsed=pos)
            say(new_cap(), ctx_for(q))
            self.assertEqual([c for c in q.calls if c[0] == "play_index"], [("play_index", "t1", want)])

    def test_radio_resumes_station_without_seek(self):
        q = FakeQueue([station()], current=0, elapsed=1799.0)
        r = say(new_cap(), ctx_for(q))
        self.assertEqual([c for c in q.calls if c[0] == "play_index"], [("play_index", "st1", 0)])
        self.assertEqual(q.ids(), ["st1"])
        self.assertEqual(r["metadata"]["resume"], "queue")

    def test_radio_station_added_by_url_is_resumed_not_mistaken_for_a_clip(self):
        q = FakeQueue([station(STREAM)], current=0, elapsed=10.0)
        r = say(new_cap(), ctx_for(q))
        self.assertEqual([c for c in q.calls if c[0] == "play_index"], [("play_index", "st1", 0)])
        self.assertEqual(r["metadata"]["resume"], "queue")

    def test_multi_clip_turn_chained_anchors(self):
        q = FakeQueue([track(1), track(2), track(3)], current=1)
        say(new_cap(), ctx_for(q), uris=[CLIP, CLIP2])
        self.assertEqual(q.ids(), ["t1", "t2", "t3"])
        self.assertEqual(len([c for c in q.calls if c[0] == "delete"]), 2)
        self.assertEqual(len([c for c in q.calls if c[0] == "play_index"]), 1)

    def test_unidentified_clip_does_not_cascade(self):
        q = FakeQueue([track(1), track(2), track(3)], current=1)
        q.first_wrapper = "odd://"                     # the first clip's queue uri will not match exactly
        r = say(new_cap(), ctx_for(q), uris=[CLIP, CLIP2])
        self.assertEqual(r["metadata"]["clips_unidentified"], 1)
        deletes = [c[1] for c in q.calls if c[0] == "delete"]
        self.assertEqual(deletes, ["c2"])              # the second clip is still found at the live anchor
        self.assertNotIn("c2", q.ids())

    def test_paused_queue_at_enqueue(self):
        q = FakeQueue([track(1), track(2)], current=0)
        ctx = ctx_for(q)
        say(new_cap(), ctx)                            # say_pause_before_reply pauses before the enqueue
        self.assertIn(("media_player", "media_pause", {"entity_id": ZONE}), ctx.ha.calls)
        self.assertEqual(q.ids(), ["t1", "t2"])
        self.assertEqual(q.cur()["queue_item_id"], "t1")

    def test_clip_that_never_goes_idle_still_resumes(self):
        q = FakeQueue([track(1), track(2)], current=0)
        q.clip_never_idle = True
        r = say(new_cap(), ctx_for(q))
        self.assertEqual(q.ids(), ["t1", "t2"])
        self.assertEqual(r["metadata"]["resume"], "queue")

    def test_kill_switch_gives_legacy_calls(self):
        q = FakeQueue([track(1), track(2)], current=0)
        ctx = ctx_for(q)
        ctx.settings.say_queue_resume = False
        r = say(new_cap(), ctx)
        self.assertEqual(q.calls, [("replace", CLIP), ("replace", "library://track/1")])
        self.assertEqual(ctx.mas, [])
        self.assertEqual(r["metadata"]["resume"], "legacy")

    def test_capture_failure_gives_legacy_calls(self):
        q = FakeQueue([track(1), track(2)], current=0)
        q.fail["queue_state"] = [OSError("ws down")]
        r = say(new_cap(), ctx_for(q))
        self.assertEqual([c[0] for c in q.calls], ["replace", "replace"])
        self.assertEqual(r["metadata"]["resume"], "legacy")

    def test_idle_zone_no_resume_clip_left_as_current(self):
        q = FakeQueue([track(1), track(2)], current=0, state="idle")
        r = say(new_cap(), ctx_for(q))
        self.assertEqual([c for c in q.calls if c[0] == "play_index"], [])
        self.assertEqual(r["metadata"]["resume"], "none")
        self.assertEqual(q.cur()["media_item"]["uri"], "builtin://radio/" + CLIP)   # left, logged

    def test_play_index_error_code_falls_back_to_uri_without_delay(self):
        # fix round 1, item 1: the fallback guard must be is_reply_clip_uri, not _is_reply_uri --
        # a URL-added radio station is a reply-clip URI's opposite case (a STATION, not a clip), so
        # the old `_is_reply_uri` guard (built for the legacy single-URI replay) would refuse to
        # replay it here. Also covers item 4: one queue_state read should decide the outcome --
        # polling the full CONFIRM_BUDGET_S after a KNOWN error_code only delays the fallback.
        q = FakeQueue([station(STREAM)], current=0)
        q.fail["play_index"] = ["error"]
        r = say(new_cap(), ctx_for(q))
        self.assertEqual(r["metadata"]["resume"], "fallback_uri")
        self.assertIn(("replace", STREAM), q.calls)
        self.assertEqual(len([c for c in q.calls if c[0] == "play_index"]), 1)
        self.assertEqual(len([c for c in q.calls if c[0] == "replace"]), 1)

    def test_finish_keeps_the_last_clip_when_current_is_unknown(self):
        # fix round 1, item 3: a failed queue_state read at finish must not be read as "nothing is
        # current" -- that would let the last recorded clip (the one most likely to BE current) get
        # "deleted" as MA's current-item no-op, silently dropping its id and overcounting deletes.
        q = FakeQueue([track(1), track(2)], current=0, state="idle")
        q.fail["queue_state"] = [None, None, OSError("read")]   # capture ok, record ok, finish fails
        cap = new_cap()
        r = say(cap, ctx_for(q))
        self.assertEqual(r["metadata"]["clips_deleted"], 0)
        self.assertEqual(len(cap._queue_targets[ZONE]["clips"]), 1)


class QueueFailureTest(unittest.TestCase):
    def q8(self):
        return FakeQueue([track(i) for i in range(1, 9)], current=2, elapsed=47.0)

    def replaces(self, q):
        return [c for c in q.calls if c[0] == "replace"]

    def play_indexes(self, q):
        return [c for c in q.calls if c[0] == "play_index"]

    def test_confirmation_lag_within_budget_is_confirmed(self):
        q = self.q8(); q.lag = 3
        r = say(new_cap(), ctx_for(q))
        self.assertEqual(r["metadata"]["resume"], "queue")
        self.assertEqual(self.replaces(q), [])
        self.assertEqual(len(self.play_indexes(q)), 1)

    def test_lag_beyond_budget_is_unconfirmed_and_never_replays_or_restarts(self):
        q = self.q8(); q.lag = 50
        r = say(new_cap(), ctx_for(q))
        self.assertEqual(r["metadata"]["resume"], "unconfirmed")
        self.assertEqual(self.replaces(q), [])
        self.assertEqual(len(self.play_indexes(q)), 1)     # settle must not re-resume a merely lagging MA

    def test_play_index_error_and_reads_show_other_item_falls_back_once(self):
        q = self.q8(); q.fail["play_index"] = ["error"]
        r = say(new_cap(), ctx_for(q))
        self.assertEqual(r["metadata"]["resume"], "fallback_uri")
        self.assertEqual(self.replaces(q), [("replace", "library://track/3")])

    def test_play_index_error_and_reads_fail_falls_back_once(self):
        q = self.q8(); q.fail["play_index"] = ["error"]
        q.fail["queue_state"] = [None, None] + [OSError("read")] * 30   # capture + record ok, then all fail
        r = say(new_cap(), ctx_for(q))
        self.assertEqual(r["metadata"]["resume"], "fallback_uri")
        self.assertEqual(len(self.replaces(q)), 1)

    def test_play_index_raised_and_reads_fail_is_unknown_no_replay(self):
        q = self.q8(); q.fail["play_index"] = [OSError("timeout")]
        q.fail["queue_state"] = [None, None] + [OSError("read")] * 30
        r = say(new_cap(), ctx_for(q))
        self.assertEqual(r["metadata"]["resume"], "unknown")
        self.assertEqual(self.replaces(q), [])

    def test_delete_failure_is_logged_not_fatal(self):
        q = self.q8(); q.fail["delete_item"] = ["error"]
        r = say(new_cap(), ctx_for(q))
        self.assertTrue(r["ok"])
        self.assertEqual(r["metadata"]["resume"], "queue")
        self.assertEqual(r["metadata"]["clips_deleted"], 0)

    def test_exception_after_play_index_is_not_redecided(self):
        q = self.q8()
        cap = new_cap()
        def boom(*a, **k):
            raise RuntimeError("after resume")
        cap._queue_finish = boom
        try:
            say(cap, ctx_for(q))
        except Exception:
            pass
        self.assertEqual(len(self.play_indexes(q)), 1)
        self.assertEqual(self.replaces(q), [])

    def test_exception_after_enqueue_resumes_in_recovery(self):
        q = self.q8()
        cap = new_cap()
        def boom(*a, **k):
            raise RuntimeError("record failed")
        cap._queue_record_clip = boom
        try:
            say(cap, ctx_for(q))
        except Exception:
            pass
        self.assertEqual(self.play_indexes(q), [("play_index", "t3", 47)])
        self.assertEqual(self.replaces(q), [])

    def test_exception_after_pause_before_enqueue_unpauses_in_place(self):
        q = self.q8()
        ctx = ctx_for(q); ctx.ha.volume_boom = True           # the reply-volume write fails after the pause
        try:
            say(new_cap(), ctx)
        except Exception:
            pass
        self.assertEqual(self.play_indexes(q), [])
        self.assertEqual([c for c in q.calls if c[0] == "enqueue"], [])
        self.assertIn(("media_player", "media_play", {"entity_id": ZONE}), ctx.ha.calls)

    def test_exception_before_pause_leaves_the_song_alone(self):
        q = self.q8()
        ctx = ctx_for(q)
        cap = new_cap()
        def boom(*a, **k):
            raise RuntimeError("before the pause")
        cap._warn_if_double_speak = boom
        try:
            say(cap, ctx)
        except Exception:
            pass
        self.assertEqual(self.play_indexes(q), [])
        self.assertEqual([c for c in ctx.ha.calls if c[1] in ("media_play", "media_pause")], [])

    def test_enqueue_raised_but_landed_waits_then_resumes_and_deletes(self):
        q = self.q8(); q.enqueue_raises_after_landing = True
        r = say(new_cap(), ctx_for(q))
        self.assertEqual(q.ids(), ["t%d" % i for i in range(1, 9)])
        self.assertEqual(q.cur()["queue_item_id"], "t3")
        self.assertEqual(self.replaces(q), [])
        self.assertEqual(r["metadata"]["resume"], "queue")

    def test_enqueue_raised_not_landed_is_not_reported_certainly_silent(self):
        q = self.q8(); q.enqueue_raises_without_landing = True
        r = say(new_cap(), ctx_for(q))
        self.assertFalse(r["metadata"]["likely_silent"])     # AN-01 honesty rule: unknown, not a denial
        self.assertEqual(r["metadata"]["resume"], "queue")
        self.assertEqual(q.ids(), ["t%d" % i for i in range(1, 9)])

    def test_clip_landing_after_resume_is_caught_by_settle(self):
        q = self.q8(); q.clip_lands_after_play_index = CLIP
        say(new_cap(), ctx_for(q))
        self.assertEqual(len(self.play_indexes(q)), 2)       # resumed once more
        self.assertEqual(q.cur()["queue_item_id"], "t3")
        self.assertEqual(q.ids(), ["t%d" % i for i in range(1, 9)])


if __name__ == "__main__":
    unittest.main()
