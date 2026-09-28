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
        self.assertTrue(interaction.is_reply_clip_uri("http://x/y.wav?authSig=PLACEHOLDER"))
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
    `fail[name]` = list consumed per call: None (normal), "error", "none" (MA sent no reply: the call
    returns None), or an Exception to raise."""
    NO_REPLY = object()
    def __init__(self, items, current=0, state="playing", elapsed=47.0, last_upd=None):
        self.items = list(items); self.current = current; self.state = state
        self.elapsed = elapsed; self.last_upd = last_upd
        self.calls = []; self.fail = {}; self.lag = 0; self._pending = None
        self.clip_reads = 0; self.clip_play_reads = 1; self.clip_never_idle = False; self.n = 0
        self.enqueue_raises_after_landing = False
        self.enqueue_raises_without_landing = False
        self.clip_lands_after_play_index = None      # a clip URL that lands only after play_index
        self.first_wrapper = None                    # store the next clip under this wrapper (identity miss)
        # Live 2026-09-28: after a clip starts in queue mode, HA's media_content_id briefly names the PREVIOUS
        # queue item (the station) while MA still plays the clip. QueueHA reports that for the first
        # `ha_flicker_reads` reads after the clip was first seen playing. The clip keeps playing underneath.
        self.ha_flicker_reads = 0; self.clip_seen = False; self.in_flicker = False
        self.ma_fails_in_flicker = False             # queue_state raises when read during a flicker read
        self.events = []                             # ("ha", state, cid) / ("ma",) in read order
        self.clip_reads_at_play_index = []           # (clip_reads left, state) at each play_index

    def _f(self, name):
        seq = self.fail.get(name)
        if not seq:
            return None
        f = seq.pop(0)
        if isinstance(f, Exception):
            raise f
        if f == "error":
            return {"error_code": 999, "details": "boom"}
        if f == "none":
            return self.NO_REPLY
        return None

    def _insert_clip(self, uri):
        self.n += 1
        wrapper, self.first_wrapper = (self.first_wrapper or "builtin://radio/"), None
        self.items.insert(self.current + 1, clip_item("c%d" % self.n, uri, wrapper))
        self.current += 1; self.state = "playing"; self.clip_reads = self.clip_play_reads
        self.clip_seen = False

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
        self.events.append(("ma",))
        if self.ma_fails_in_flicker and self.in_flicker:
            self.in_flicker = False                  # only the read made for THIS flicker poll fails
            raise OSError("MA read failed during the flicker")
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
        self.clip_reads_at_play_index.append((self.clip_reads, self.state))
        r = self._f("play_index")
        if r is self.NO_REPLY:
            return None
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
        self.q = q; self.s = None; self.connect_args = None
    def connect(self, connect_timeout=None, call_timeout=None):
        self.connect_args = (connect_timeout, call_timeout); self.s = object()
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
        self.play_boom = False                       # media_play (un-pause) raises
        self.first_state = None                      # one-shot (state, media_content_id) for the first read
    def get_entity_state(self, entity_id, timeout=None):
        self.state_timeouts.append(timeout)
        if self.first_state is not None:
            (st, mid), self.first_state = self.first_state, None
            return {"state": st, "attributes": {"volume_level": self.volume, "media_content_id": mid}}
        st, mid = self.q.ha_state()
        q = self.q
        q.in_flicker = False
        if st == "playing" and interaction.is_reply_clip_uri(mid):
            if q.clip_seen and q.ha_flicker_reads > 0 and q.current > 0:
                q.ha_flicker_reads -= 1; q.in_flicker = True
                mid = q.items[q.current - 1]["media_item"]["uri"]      # the station, not the clip
            q.clip_seen = True
        q.events.append(("ha", st, mid))
        return {"state": st, "attributes": {"volume_level": self.volume, "media_content_id": mid}}
    def call_service_rest(self, domain, service, data, timeout=5):
        self.calls.append((domain, service, data)); self.timeouts.append((service, timeout))
        if (domain, service) == ("music_assistant", "play_media"):
            self.q.ha_play_media(data)
        elif service == "media_pause":
            self.q.state = "paused"
        elif service == "media_play":
            if self.play_boom:
                raise OSError("media_play failed")
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
        cap = new_cap()
        r = say(cap, ctx_for(q))
        self.assertEqual(r["metadata"]["resume"], "fallback_uri")
        self.assertEqual(self.replaces(q), [("replace", "library://track/3")])
        # design 4.6: fallback_uri already replaced the queue -- the captured item is gone, so no
        # pending record should be left behind for it (only no-resume/unconfirmed/unknown do that).
        self.assertNotIn(ZONE, cap._queue_targets)

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
        # pins the §4.3-5 wait itself, not just its side effects: only the wait branch
        # (_play_clip_and_wait with issue=False) observes the clip actually starting, and there
        # must be no SECOND play_media call trying to enqueue it again.
        self.assertTrue(r["metadata"]["clips"][0]["started"])
        self.assertEqual(len([c for c in q.calls if c[0] == "enqueue"]), 1)

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

    def test_settle_yields_to_a_newer_turn(self):
        # fix round 1, item 1: a successor B enqueuing its own reply during A's confirm poll (up to
        # CONFIRM_BUDGET_S) must not have its clip displaced by A's settle check -- A is superseded
        # and no longer owns the zone (spec §4.3-7 / §4.4: a superseded turn does not resume).
        q = self.q8(); q.clip_lands_after_play_index = CLIP2
        box = {}

        def hook(n):
            if any(c[0] == "play_index" for c in q.calls):
                with box["cap"]._lock:
                    gens = box["cap"]._say_gen
                    gens[ZONE] = gens.get(ZONE, 0) + 1

        cap = new_cap(hook)
        box["cap"] = cap
        say(cap, ctx_for(q))
        self.assertEqual(len(self.play_indexes(q)), 1)


class QueueContinuityTest(unittest.TestCase):
    def test_barge_in_before_first_turn_recorded_its_clip(self):
        q = FakeQueue([track(i) for i in range(1, 6)], current=2, elapsed=47.0)
        q.clip_play_reads = 3                         # A's clip is still PLAYING at A's first poll sleep
        ctx = ctx_for(q)
        state = {"fired": False}
        def hook(n):
            # A's clip is playing and A has recorded nothing yet: B arrives (barge-in).
            if (not state["fired"] and q.state == "playing" and q.cur()
                    and q.cur()["queue_item_id"].startswith("c")):
                state["fired"] = True
                capability.run(cap, ctx, {"mode": "say", "uri": CLIP2}, "ridB")
        cap = new_cap(hook)
        with self.assertLogs("resolver", "INFO") as lg:
            say(cap, ctx)
        self.assertTrue(state["fired"])
        self.assertEqual(q.ids(), ["t1", "t2", "t3", "t4", "t5"])           # both clips gone
        self.assertEqual([c for c in q.calls if c[0] == "play_index"], [("play_index", "t3", 47)])
        self.assertEqual([c for c in q.calls if c[0] == "replace"], [])
        self.assertFalse(any("UNIDENTIFIED" in m for m in lg.output))     # superseded A does not probe

    def test_superseded_without_successor_capture_leaves_a_pending_resume(self):
        q = FakeQueue([track(1), track(2), track(3)], current=1, elapsed=47.0)
        q.clip_play_reads = 3
        ctx = ctx_for(q)
        state = {"fired": False}
        def hook(n):
            # An announcement claims the generation and aborts before _say: nobody else captures.
            if not state["fired"] and q.state == "playing" and q.cur()["queue_item_id"].startswith("c"):
                state["fired"] = True
                with cap._lock:
                    cap._say_gen[ZONE] = cap._say_gen.get(ZONE, 0) + 1
        cap = new_cap(hook)
        say(cap, ctx)
        self.assertFalse(cap._queue_targets[ZONE]["live"])
        r = capability.run(cap, ctx, {"mode": "resume"}, "rid2")
        self.assertEqual(r["metadata"]["how"], "queue_pending")
        self.assertEqual(q.ids(), ["t1", "t2", "t3"])
        self.assertEqual(q.cur()["queue_item_id"], "t2")

    def test_pause_question_resume(self):
        q = FakeQueue([track(1), track(2), track(3)], current=1, state="paused", elapsed=47.0)
        ctx = ctx_for(q)
        cap = new_cap()
        r = say(cap, ctx)
        self.assertEqual(r["metadata"]["resume"], "none")
        self.assertEqual(q.cur()["media_item"]["uri"], "builtin://radio/" + CLIP)
        r2 = capability.run(cap, ctx, {"mode": "resume"}, "rid2")
        self.assertTrue(r2["metadata"]["resumed"])
        self.assertEqual(r2["metadata"]["how"], "queue_pending")
        self.assertEqual(q.ids(), ["t1", "t2", "t3"])
        self.assertEqual(q.cur()["queue_item_id"], "t2")
        self.assertEqual([c for c in q.calls if c[0] == "play_index"], [("play_index", "t2", 47)])

    def test_pending_resume_confirms_before_deleting_the_lagging_clip(self):
        # fix round 1: play_index lags 3 reads before landing. Deleting BEFORE confirming would hit
        # the clip while it is still "current" -- MA treats that delete as a no-op, so the clip would
        # survive while the log claims it was deleted. The confirm must wait the lag out first.
        q = FakeQueue([track(1), track(2), track(3)], current=1, state="paused", elapsed=47.0)
        ctx = ctx_for(q)
        cap = new_cap()
        say(cap, ctx)
        q.lag = 3
        r = capability.run(cap, ctx, {"mode": "resume"}, "rid2")
        self.assertEqual(r["metadata"]["how"], "queue_pending")
        self.assertEqual(q.ids(), ["t1", "t2", "t3"])         # c1 actually gone, not left behind

    def test_pending_resume_keeps_a_clip_still_current_when_unconfirmed(self):
        # fix round 1: play_index never confirms within budget. The clip that was current when this
        # resume started must be KEPT (not deleted-as-no-op-and-forgotten), and the record must stay
        # pending with it, so a later resume can still find it.
        q = FakeQueue([track(1), track(2), track(3)], current=1, state="paused", elapsed=47.0)
        ctx = ctx_for(q)
        cap = new_cap()
        say(cap, ctx)
        q.lag = 50
        r = capability.run(cap, ctx, {"mode": "resume"}, "rid2")
        self.assertEqual(r["metadata"]["how"], "queue_pending")
        self.assertIn("c1", cap._queue_targets[ZONE]["clips"])
        self.assertIn("c1", q.ids())

    def test_pause_two_questions_resume(self):
        q = FakeQueue([track(1), track(2), track(3)], current=1, state="paused", elapsed=47.0)
        ctx = ctx_for(q)
        cap = new_cap()
        say(cap, ctx)
        say(cap, ctx, uri=CLIP2, rid="rid2")
        r3 = capability.run(cap, ctx, {"mode": "resume"}, "rid3")
        self.assertEqual(r3["metadata"]["how"], "queue_pending")
        self.assertEqual(q.ids(), ["t1", "t2", "t3"])
        self.assertEqual(q.cur()["queue_item_id"], "t2")

    def test_same_fixed_reply_twice_identifies_the_new_clip_not_the_anchor(self):
        # HA's TTS cache gives the same URL for the same text: after Q1 the current item is c1(CLIP), and Q2's
        # anchor IS that identical clip. Q2's clip must be found at anchor + 1.
        q = FakeQueue([track(1), track(2), track(3)], current=1, state="paused", elapsed=47.0)
        ctx = ctx_for(q)
        cap = new_cap()
        say(cap, ctx)
        say(cap, ctx, rid="rid2")
        capability.run(cap, ctx, {"mode": "resume"}, "rid3")
        self.assertEqual(q.ids(), ["t1", "t2", "t3"])
        self.assertEqual(sorted(c[1] for c in q.calls if c[0] == "delete"), ["c1", "c2"])

    def test_plain_pause_resume_unpauses_in_place(self):
        q = FakeQueue([track(1), track(2)], current=1, state="paused")
        ctx = ctx_for(q)
        r = capability.run(new_cap(), ctx, {"mode": "resume"}, "rid1")
        self.assertEqual(r["metadata"]["how"], "unpause_queue")
        self.assertIn(("media_player", "media_play", {"entity_id": ZONE}), ctx.ha.calls)
        self.assertEqual([c for c in q.calls if c[0] in ("replace", "play_index")], [])

    def test_resume_while_already_playing_is_a_no_op(self):
        q = FakeQueue([track(1), track(2)], current=1, state="playing")
        ctx = ctx_for(q)
        r = capability.run(new_cap(), ctx, {"mode": "resume"}, "rid1")
        self.assertEqual(r["metadata"]["how"], "already_playing")
        self.assertEqual([c for c in q.calls if c[0] in ("replace", "play_index")], [])

    def test_paused_reply_clip_is_never_unpaused(self):
        q = FakeQueue([track(1), clip_item("c9", CLIP)], current=1, state="paused")
        ctx = ctx_for(q)
        capability.run(new_cap(), ctx, {"mode": "resume"}, "rid1")
        self.assertNotIn(("media_player", "media_play", {"entity_id": ZONE}), ctx.ha.calls)

    def test_unconfirmed_resume_leaves_pending_that_resume_uses(self):
        q = FakeQueue([track(1), track(2), track(3)], current=1, elapsed=47.0)
        q.lag = 50
        ctx = ctx_for(q)
        cap = new_cap()
        r = say(cap, ctx)
        self.assertEqual(r["metadata"]["resume"], "unconfirmed")
        q.lag = 0; q._pending = None                  # the late play_index never landed
        r2 = capability.run(cap, ctx, {"mode": "resume"}, "rid2")
        self.assertEqual(r2["metadata"]["how"], "queue_pending")
        self.assertEqual(q.cur()["queue_item_id"], "t2")

    def test_note_playback_clears_the_pending_record(self):
        q = FakeQueue([track(1), track(2)], current=0, state="paused")
        ctx = ctx_for(q)
        cap = new_cap()
        say(cap, ctx)
        self.assertIn(ZONE, cap._queue_targets)
        cap.note_playback(ctx, ZONE, "library://track/99")
        self.assertNotIn(ZONE, cap._queue_targets)


def qm_for(clips, target=None):
    return {"queue_id": "q1", "cap": None, "target": target, "clips": list(clips), "played": [],
            "unrecorded": [], "anchor": 0, "unidentified": 0, "resume": "none", "seeked": False,
            "deleted": 0, "inherited_from": None}


class FinalReviewFixTest(unittest.TestCase):
    """MR-08c final-review fix wave (I1-I3, D1-D2, M1, M2, M5, M6, M8, M9)."""

    def play_indexes(self, q):
        return [c for c in q.calls if c[0] == "play_index"]

    # I1 -----------------------------------------------------------------------------------------
    def test_superseded_after_play_index_leaves_no_orphan_clip(self):
        # B supersedes A after A recorded its clip and issued play_index; B captures the SONG (a real
        # item), which pops A's record. A's clip must not be left in the queue to play after the song.
        q = FakeQueue([track(i) for i in range(1, 9)], current=2, elapsed=47.0)
        ctx = ctx_for(q)
        state = {"fired": False}
        def hook(n):
            if not state["fired"] and any(c[0] == "play_index" and c[1] == "t3" for c in q.calls):
                state["fired"] = True
                capability.run(cap, ctx, {"mode": "say", "uri": CLIP2}, "ridB")
        cap = new_cap(hook)
        with self.assertLogs("resolver", "INFO") as lg:
            say(cap, ctx)
        self.assertTrue(state["fired"])
        self.assertEqual(q.ids(), ["t%d" % i for i in range(1, 9)])      # original 8, no clip left
        self.assertEqual(q.cur()["queue_item_id"], "t3")
        self.assertTrue(any("carried 1 clip(s) from req=rid1" in m for m in lg.output))

    def test_capturing_a_real_item_carries_the_popped_records_clips(self):
        # The carry on its own (the test above also passes through the superseded exit): a record left
        # by a superseded turn is popped when this turn captures a real item, and its spent clips become
        # this turn's to delete -- even if the superseded turn never gets to clean up.
        q = FakeQueue([track(1), track(2), track(3), clip_item("cA", CLIP), track(4)], current=2, elapsed=47.0)
        ctx = ctx_for(q)
        cap = new_cap()
        cap._queue_targets[ZONE] = {"gen": 1, "rid": "ridA", "target": {"item": "t3"}, "clips": ["cA"],
                                    "live": True}
        with cap._lock:
            cap._say_gen[ZONE] = 1
        r = say(cap, ctx, uri=CLIP2, rid="ridB")
        self.assertEqual(q.ids(), ["t1", "t2", "t3", "t4"])
        self.assertEqual(q.cur()["queue_item_id"], "t3")
        self.assertEqual(r["metadata"]["clips_deleted"], 2)

    def test_superseded_exit_deletes_own_recorded_clips_when_record_not_its_own(self):
        q = FakeQueue([track(1), track(2), clip_item("c1", CLIP), clip_item("c2", CLIP2), track(3)], current=3)
        ctx = ctx_for(q)
        cap = new_cap()
        succ = {"gen": 9, "rid": "ridB", "target": None, "clips": [], "live": True}
        cap._queue_targets[ZONE] = succ
        cap._queue_superseded_exit(ctx, "ridA", ZONE, qm_for(["c1", "c2"]), 3)
        self.assertEqual(q.ids(), ["t1", "t2", "c2", "t3"])       # c1 deleted; c2 is current: kept
        self.assertEqual([c for c in q.calls if c[0] == "delete"], [("delete", "c1")])
        self.assertIs(cap._queue_targets[ZONE], succ)             # the successor's record is untouched
        self.assertTrue(ctx.mas and all(m.s is None for m in ctx.mas))

    def test_superseded_exit_before_successor_records_leaves_inherited_clip(self):
        # Race: A records c1 while c1 is still playing; B barges in, captures c1 and INHERITS it
        # (anchor = c1's index). B's c2 lands after c1 and is current. A's superseded exit then runs
        # BEFORE B records c2. A must not delete c1 -- B owns it now -- or c2 shifts left under B's
        # anchored record step, which then misses it and orphans c2 after the resumed song.
        q = FakeQueue([track(i) for i in range(1, 6)], current=2, elapsed=47.0)
        q.clip_never_idle = True                      # c1 is still PLAYING when A records it
        ctx = ctx_for(q)
        cap = new_cap()
        real_record = cap._queue_record_clip
        real_exit = cap._queue_superseded_exit
        st = {"a": None, "b_fired": False, "a_exit_early": False, "b_record_saw": None}

        def record(ctx_, rid, zone, qm, played_uri, clip, my_gen):
            if rid == "ridB" and not st["a_exit_early"]:
                # B's c2 has landed and is current; A's pending superseded exit runs first.
                st["a_exit_early"] = True
                st["b_record_saw"] = (q.ids(), q.cur()["queue_item_id"])
                a_ctx, a_qm, a_gen = st["a"]
                real_exit(a_ctx, "rid1", zone, a_qm, a_gen)
            real_record(ctx_, rid, zone, qm, played_uri, clip, my_gen)
            if rid == "rid1" and not st["b_fired"]:
                # A has recorded c1 (current, playing): B barges in now.
                st["b_fired"] = True
                st["a"] = (ctx_, qm, my_gen)
                capability.run(cap, ctx, {"mode": "say", "uri": CLIP2}, "ridB")

        def superseded_exit(ctx_, rid, zone, qm, my_gen):
            if rid == "rid1" and st["a_exit_early"]:
                return                                # A's exit already ran, at the forced point
            real_exit(ctx_, rid, zone, qm, my_gen)

        cap._queue_record_clip = record
        cap._queue_superseded_exit = superseded_exit
        with self.assertLogs("resolver", "INFO") as lg:
            say(cap, ctx)
        self.assertTrue(st["b_fired"])
        self.assertTrue(st["a_exit_early"])
        self.assertEqual(st["b_record_saw"], (["t1", "t2", "t3", "c1", "c2", "t4", "t5"], "c2"))
        self.assertEqual(q.ids(), ["t1", "t2", "t3", "t4", "t5"])            # original playlist, no clips
        self.assertEqual(q.cur()["queue_item_id"], "t3")                    # the interrupted song
        self.assertEqual(self.play_indexes(q), [("play_index", "t3", 47)])  # exactly one resume
        self.assertEqual([c for c in q.calls if c[0] == "replace"], [])     # no URI replay
        self.assertFalse(any("UNIDENTIFIED" in m for m in lg.output))
        self.assertTrue(any("clip c1 owned by successor req=ridB; not deleting" in m for m in lg.output))

    # I2 -----------------------------------------------------------------------------------------
    def test_ha_idle_but_ma_playing_still_resumes(self):
        q = FakeQueue([track(i) for i in range(1, 9)], current=2, elapsed=47.0)
        ctx = ctx_for(q)
        ctx.ha.first_state = ("idle", "builtin://radio/" + CLIP)   # HA lags: still shows the spent clip
        r = say(new_cap(), ctx)
        self.assertEqual(self.play_indexes(q), [("play_index", "t3", 47)])
        self.assertEqual(q.ids(), ["t%d" % i for i in range(1, 9)])
        self.assertEqual(r["metadata"]["resume"], "queue")

    # I3 -----------------------------------------------------------------------------------------
    def test_ma_open_passes_default_timeouts(self):
        q = FakeQueue([track(1)], current=0)
        ctx = ctx_for(q)
        m = new_cap()._ma_open(ctx)
        self.assertEqual(m.connect_args, (3.0, 5.0))

    def test_ma_open_passes_configured_timeouts(self):
        q = FakeQueue([track(1)], current=0)
        ctx = ctx_for(q)
        ctx.settings.say_ma_connect_timeout_ms = 1500
        ctx.settings.say_ma_call_timeout_ms = 2500
        m = new_cap()._ma_open(ctx)
        self.assertEqual(m.connect_args, (1.5, 2.5))

    # M6 -----------------------------------------------------------------------------------------
    def test_ma_open_closes_a_half_open_socket_when_connect_fails(self):
        q = FakeQueue([track(1)], current=0)
        ctx = ctx_for(q)
        class HalfOpen(FakeQueueMA):
            def connect(self, connect_timeout=None, call_timeout=None):
                self.s = object()
                raise OSError("auth handshake failed")
        m = HalfOpen(q)
        ctx.ma_factory = lambda: m
        with self.assertRaises(OSError):
            new_cap()._ma_open(ctx)
        self.assertIsNone(m.s)

    # D1 -----------------------------------------------------------------------------------------
    def test_recovery_unpause_failure_still_finishes(self):
        q = FakeQueue([track(i) for i in range(1, 9)], current=2, elapsed=47.0)
        ctx = ctx_for(q)
        ctx.ha.volume_boom = True                    # the reply-volume write fails after the pause
        ctx.ha.play_boom = True                      # and the recovery's un-pause raises too
        cap = new_cap()
        try:
            say(cap, ctx)
        except Exception:
            pass
        rec = cap._queue_targets.get(ZONE)
        self.assertFalse(rec is not None and rec.get("live"))

    # D2 -----------------------------------------------------------------------------------------
    def test_raised_enqueue_not_landed_when_current_item_has_no_id(self):
        q = FakeQueue([track(1), {"name": "x", "media_item": {"uri": "library://track/9"}}], current=1)
        ctx = ctx_for(q)
        cap = new_cap()
        waited = []
        cap._play_clip_and_wait = lambda *a, **k: waited.append(a)
        out = cap._queue_after_raised_enqueue(ctx, "r1", ZONE, qm_for([]), CLIP, CLIP, "clip", {},
                                              lambda: False)
        self.assertEqual(waited, [])
        self.assertFalse(out["started"])

    # M1 -----------------------------------------------------------------------------------------
    def test_play_index_no_reply_is_ambiguous_not_refused(self):
        q = FakeQueue([track(i) for i in range(1, 9)], current=2, elapsed=47.0)
        q.fail["play_index"] = ["none"]
        q.fail["queue_state"] = [None, None] + [OSError("read")] * 30   # capture + record ok, then all fail
        r = say(new_cap(), ctx_for(q))
        self.assertEqual(r["metadata"]["resume"], "unknown")
        self.assertEqual([c for c in q.calls if c[0] == "replace"], [])

    def test_pending_resume_no_reply_does_not_fall_back_or_delete(self):
        q = FakeQueue([track(1), track(2), track(3)], current=1, state="paused", elapsed=47.0)
        ctx = ctx_for(q)
        cap = new_cap()
        say(cap, ctx)
        q.items.insert(0, clip_item("c9", CLIP2))    # an older recorded clip that is NOT current
        q.current += 1
        cap._queue_targets[ZONE]["clips"].insert(0, "c9")
        q.fail["play_index"] = ["none"]              # no reply, and it never lands
        r = capability.run(cap, ctx, {"mode": "resume"}, "rid2")
        self.assertEqual(r["metadata"]["how"], "queue_pending")
        self.assertEqual([c for c in q.calls if c[0] in ("replace", "delete")], [])
        self.assertEqual(q.ids(), ["c9", "t1", "t2", "c1", "t3"])
        self.assertEqual(cap._queue_targets[ZONE]["clips"], ["c9", "c1"])

    # M2 -----------------------------------------------------------------------------------------
    def test_settle_second_play_index_refused_leaves_pending_with_late_clip(self):
        q = FakeQueue([track(i) for i in range(1, 9)], current=2, elapsed=47.0)
        q.clip_lands_after_play_index = CLIP
        q.fail["play_index"] = [None, "error"]      # the resume lands; settle's re-resume is refused
        cap = new_cap()
        with self.assertLogs("resolver", "INFO") as lg:
            r = say(cap, ctx_for(q))
        self.assertEqual(len(self.play_indexes(q)), 2)
        self.assertEqual(r["metadata"]["resume"], "unconfirmed")
        rec = cap._queue_targets[ZONE]
        self.assertFalse(rec["live"])
        self.assertIn(q.cur()["queue_item_id"], rec["clips"])      # the late clip, still current
        self.assertFalse(any("resumed again" in m for m in lg.output))

    # M5 -----------------------------------------------------------------------------------------
    def test_non_ceiling_zone_uses_legacy(self):
        q = FakeQueue([track(1), track(2)], current=0)
        ctx = ctx_for(q)
        r = capability.run(new_cap(), ctx, {"mode": "say", "uri": CLIP, "zone": "media_player.kitchen"}, "rid1")
        self.assertEqual(q.calls, [("replace", CLIP), ("replace", "library://track/1")])
        self.assertEqual(ctx.mas, [])
        self.assertEqual(r["metadata"]["resume"], "legacy")

    def test_non_ceiling_zone_resume_uses_legacy(self):
        q = FakeQueue([track(1), track(2)], current=1, state="playing")
        ctx = ctx_for(q)
        capability.run(new_cap(), ctx, {"mode": "resume", "zone": "media_player.kitchen"}, "rid1")
        self.assertEqual(ctx.mas, [])

    # M8 -----------------------------------------------------------------------------------------
    def test_capture_unavailable_is_a_warning(self):
        q = FakeQueue([track(1), track(2)], current=0)
        q.fail["queue_state"] = [OSError("ws down")]
        with self.assertLogs("resolver", "WARNING") as lg:
            say(new_cap(), ctx_for(q))
        self.assertTrue(any("queue capture unavailable" in m for m in lg.output))

    def test_final_line_counts_clips_and_still_current_wording(self):
        q = FakeQueue([track(1), track(2)], current=0, state="idle")
        with self.assertLogs("resolver", "INFO") as lg:
            say(new_cap(), ctx_for(q))
        self.assertTrue(any("(still current)" in m for m in lg.output))
        self.assertTrue(any("resume=none clips_deleted=0 clips_unidentified=0" in m for m in lg.output))

    # M9 -----------------------------------------------------------------------------------------
    def test_stopped_turn_in_queue_mode_leaves_clip_current_and_pending_record(self):
        q = FakeQueue([track(i) for i in range(1, 9)], current=2, elapsed=47.0)
        ctx = ctx_for(q)
        cap = new_cap()
        capability.run(cap, ctx, {"mode": "duck"}, "rid0")          # the turn opens
        cap.note_stopped(ZONE)                                     # HA-side pause not yet visible
        r = say(cap, ctx)
        self.assertEqual(self.play_indexes(q), [])
        self.assertEqual(r["metadata"]["resume"], "none")
        self.assertEqual(q.cur()["media_item"]["uri"], "builtin://radio/" + CLIP)
        rec = cap._queue_targets[ZONE]
        self.assertFalse(rec["live"])
        self.assertEqual(rec["target"]["item"], "t3")


class QueueFlickerTest(unittest.TestCase):
    """Live 2026-09-28: `finish-poll exit after 1.0s: state=playing cid=library://radio/2`. In queue mode the
    station stays in MA's queue, so HA's media_content_id can briefly name it while the reply clip still plays;
    two such reads used to end the wait and resume the station over the tail of the answer."""

    def radio(self, flicker=3, play_reads=6):
        q = FakeQueue([station()], current=0, elapsed=1799.0)
        q.clip_play_reads = play_reads                # the clip plays for several reads, then goes idle
        q.ha_flicker_reads = flicker
        return q

    def test_station_cid_flicker_waits_for_the_clip_to_really_end(self):
        q = self.radio()
        with self.assertLogs("resolver", "INFO") as lg:
            r = say(new_cap(), ctx_for(q))
        self.assertEqual(q.ha_flicker_reads, 0)                          # the flicker was actually served
        # The resume happened only once the clip had played out and HA saw it idle -- not mid-answer.
        self.assertEqual(q.clip_reads_at_play_index, [(0, "idle")])
        self.assertEqual([c for c in q.calls if c[0] == "play_index"], [("play_index", "st1", 0)])
        self.assertEqual(q.ids(), ["st1"])
        self.assertEqual(r["metadata"]["resume"], "queue")
        self.assertTrue(r["metadata"]["clips"][0]["ended"])
        overrides = [m for m in lg.output if "but MA still plays the clip; waiting" in m]
        self.assertEqual(len(overrides), 3)                              # one per flicker read
        self.assertFalse(any("finish-poll exit" in m and "radio/4" in m for m in lg.output))

    def test_override_uses_short_lived_connections(self):
        q = self.radio()
        ctx = ctx_for(q)
        say(new_cap(), ctx)
        self.assertTrue(ctx.mas and all(m.s is None for m in ctx.mas))  # no socket held across the wait

    def test_ma_read_failure_during_flicker_falls_back_to_the_ha_rule(self):
        q = self.radio()
        q.ma_fails_in_flicker = True
        with self.assertLogs("resolver", "INFO") as lg:
            r = say(new_cap(), ctx_for(q))
        # Today's rule: two consecutive "ended" reads end the wait, clip still playing underneath.
        self.assertEqual(len(q.clip_reads_at_play_index), 1)
        left, st = q.clip_reads_at_play_index[0]
        self.assertGreater(left, 0)
        self.assertEqual(st, "playing")
        self.assertFalse(any("but MA still plays the clip" in m for m in lg.output))
        self.assertTrue(any("finish-poll exit" in m for m in lg.output))
        self.assertEqual(r["metadata"]["resume"], "queue")
        self.assertEqual(q.ids(), ["st1"])

    def test_ma_reporting_another_item_counts_the_observation(self):
        # MA itself no longer has the clip current: the HA reading is believed, as today.
        q = self.radio()
        orig = q.queue_state
        def moved_on():
            r = orig()
            if q.in_flicker:
                r = {"result": dict(r["result"], current_item=station(), current_index=0)}
            return r
        q.queue_state = moved_on
        with self.assertLogs("resolver", "INFO") as lg:
            say(new_cap(), ctx_for(q))
        self.assertFalse(any("but MA still plays the clip" in m for m in lg.output))
        self.assertGreater(q.clip_reads_at_play_index[0][0], 0)          # ended on the HA rule

    def test_ha_idle_ends_the_wait_without_an_ma_check(self):
        q = self.radio(flicker=0, play_reads=2)
        with self.assertLogs("resolver", "INFO") as lg:
            r = say(new_cap(), ctx_for(q))
        ev = q.events
        idle = [i for i, e in enumerate(ev) if e[0] == "ha" and e[1] == "idle"]
        self.assertGreaterEqual(len(idle), 2)
        # The two idle reads that end the wait are consecutive HA reads: no MA read between them.
        self.assertEqual(idle[1], idle[0] + 1)
        self.assertFalse(any("but MA still plays the clip" in m for m in lg.output))
        self.assertEqual(q.clip_reads_at_play_index, [(0, "idle")])
        self.assertEqual(r["metadata"]["resume"], "queue")


if __name__ == "__main__":
    unittest.main()
