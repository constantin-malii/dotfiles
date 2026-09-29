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
    """MA's queue as measured (design 3, 3.3): enqueue=play inserts after current and plays it (also when
    paused); a clip plays for `clip_play_reads` HA reads then goes idle (or never, with clip_never_idle);
    play_index by id at a position. `lag` = confirming reads before a play_index shows.
    `fail[name]` = list consumed per call: None (normal), "error", "none" (MA sent no reply: the call
    returns None), or an Exception to raise.

    MA 2.9 buffer model (design 4.8 A1.9): player_queues/get reports `index_in_buffer` and `items`. The buffer
    FOLLOWS THE CURRENT INDEX unless something moved it, so a delete of an item after the current one works as
    before. A delete of the current item or of any item at index <= the buffer replies success and does
    nothing. play_index resets the buffer to T (after `buffer_lag` reads); `start_after` (one entry per
    play_index: M reads, or None) advances it to T+1 once playback "starts"."""
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
        self.events = []                             # ("ha", state, cid) / ("ma",) in read order
        self.clip_reads_at_play_index = []           # (clip_reads left, state) at each play_index
        self.ha_flicker_after = 1                    # clip reads before the flicker begins
        self.clip_seen_count = 0
        self.ha_script = None                        # scripted HA reads after an enqueue: "clip", "other",
        self._script_armed = False                   #   "idle", "blank" (one per read), then the model again
        # A1.9 buffer knobs
        self.buffer = None                           # explicit buffer index; None = follows current
        self.buffer_mode = None                      # None | "missing" | "nonnumeric" | "bool" |
                                                     #   "out_of_range" | "below_current" (REPORTED value only)
        self.buffer_lag = 0                          # reads after play_index before the buffer resets to T
        self._buffer_hold = None
        self.start_after = []                        # per play_index: reads until the buffer advances to T+1
        self._start_countdown = None
        self.delete_mode = None                      # None | "error_but_removes" | "ok_but_keeps"
        self.restart_item = None                     # after the clip goes idle, MA restarts this item (3.3-3)
        self.restart_delay_reads = 0                 # ...this many MA reads after the clip went idle
        self.restart_plan = None                     # or a list of {"after", "item", "state", "elapsed"} steps,
        self._restart_armed = False                  #   each `after` MA reads after the previous one
        self._plan = []
        self.ma_flip = False
        self.on_ma_read = None                       # hook(result) after each successful queue_state reply

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
        at = max(self.current, self.real_buffer()) + 1   # A3: MA inserts after the BUFFERED item
        self.items.insert(at, clip_item("c%d" % self.n, uri, wrapper))
        self.current = at; self.state = "playing"; self.clip_reads = self.clip_play_reads
        self.clip_seen = False; self.clip_seen_count = 0
        self.buffer = None                           # MA is playing the clip: the buffer is at it
        self._script_armed = self.ha_script is not None

    def arm_restart(self):
        self._plan = [dict(p) for p in (self.restart_plan or
                                        [{"after": self.restart_delay_reads, "item": self.restart_item,
                                          "state": "playing"}])]
        self._restart_armed = bool(self._plan)

    def _restart_step(self):
        step = self._plan[0]
        if step["after"] > 0:
            step["after"] -= 1
            return
        self._plan.pop(0)
        self._restart_armed = bool(self._plan)
        self.current = self.ids().index(step["item"]); self.state = step.get("state", "playing")
        self.buffer = None
        if "elapsed" in step:
            self.elapsed = float(step["elapsed"])

    def real_buffer(self):
        return self.buffer if self.buffer is not None else self.current

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
                if self.restart_item is not None or self.restart_plan:
                    self.arm_restart()
        return self.state, mid

    # MA side
    def queue_state(self):
        self.events.append(("ma",))
        r = self._f("queue_state")
        if r is not None:
            return r
        if self._restart_armed:
            self._restart_step()
        if self._pending is not None:
            if self.lag > 0:
                self.lag -= 1
            else:
                self.current, self._pending = self._pending, None
        if self._pending is None and self._buffer_hold is not None:
            if self._buffer_hold <= 0:
                self.buffer = None; self._buffer_hold = None
            else:
                self._buffer_hold -= 1
        if self._pending is None and self._buffer_hold is None and self._start_countdown is not None:
            if self._start_countdown <= 0:
                self._start_countdown = None
                if self.current + 1 < len(self.items):
                    self.buffer = self.current + 1
            else:
                self._start_countdown -= 1
        res = {"state": self.state, "current_index": self.current, "elapsed_time": self.elapsed,
               "elapsed_time_last_updated": self.last_upd, "current_item": self.cur(), "items": len(self.items)}
        if self.ma_flip:
            self.ma_flip = False                     # one MA read per scripted "other" HA read
            res["current_index"] = self.current - 1; res["current_item"] = self.items[self.current - 1]
        b = self.real_buffer()
        if self.buffer_mode != "missing":
            res["index_in_buffer"] = {"nonnumeric": str(b), "bool": True, "out_of_range": len(self.items),
                                      "below_current": self.current - 1}.get(self.buffer_mode, b)
        if self.on_ma_read is not None:
            self.on_ma_read(res)
        return {"result": res}

    def queue_items(self, offset, limit):
        self.events.append(("items", offset, limit))
        r = self._f("queue_items")
        if r is not None:
            return r
        return {"result": self.items[offset:offset + limit]}

    def play_index(self, item_id, seek_position):
        self.calls.append(("play_index", item_id, seek_position))
        self.clip_reads_at_play_index.append((self.clip_reads, self.state))
        self.events.append(("play_index",))
        r = self._f("play_index")
        if r is self.NO_REPLY:
            return None
        if r is not None:
            return r
        idx = [i for i, x in enumerate(self.items) if x["queue_item_id"] == item_id][0]
        self.state = "playing"; self.elapsed = float(seek_position)
        if self.buffer_lag:
            self.buffer = self.real_buffer(); self._buffer_hold = self.buffer_lag
        else:
            self.buffer = None; self._buffer_hold = None
        self._start_countdown = self.start_after.pop(0) if self.start_after else None
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
        self.events.append(("delete", item_id))
        r = self._f("delete_item")
        if r is not None:
            return r
        if item_id not in self.ids():
            return {"error_code": 404, "details": "no such item"}
        idx = self.ids().index(item_id)
        if self.delete_mode == "ok_but_keeps":
            return {"result": None}
        if idx == self.current or idx <= self.real_buffer():
            return {"result": None}                  # MA 2.9: the current item / the buffer -- a silent no-op
        del self.items[idx]
        if idx < self.current:
            self.current -= 1
        if self.delete_mode == "error_but_removes":
            return {"error_code": 999, "details": "boom"}
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
        q = self.q
        if q._script_armed and q.ha_script:
            kind = q.ha_script.pop(0)
            clip_mid = ((q.cur() or {}).get("media_item") or {}).get("uri") or ""
            if kind == "idle":
                q.state = "idle"
                st, mid = "idle", clip_mid
            elif kind == "other":
                # Spike 4: BOTH HA and MA name the interrupted item during the flip.
                st, mid = "playing", q.items[q.current - 1]["media_item"]["uri"]
                q.ma_flip = True
            elif kind == "blank":
                st, mid = "playing", ""
            else:
                st, mid = "playing", clip_mid
            q.events.append(("ha", st, mid))
            return {"state": st, "attributes": {"volume_level": self.volume, "media_content_id": mid}}
        st, mid = self.q.ha_state()
        q.in_flicker = False
        if st == "playing" and interaction.is_reply_clip_uri(mid):
            if (q.clip_seen_count >= q.ha_flicker_after and q.ha_flicker_reads > 0 and q.current > 0):
                q.ha_flicker_reads -= 1; q.in_flicker = True
                mid = q.items[q.current - 1]["media_item"]["uri"]      # the station, not the clip
            else:
                q.clip_seen_count += 1
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
        # A1: c1 lies AFTER the current clip (MA 2.9 ignores a delete at or below index_in_buffer, so a clip
        # before the current one is not deletable -- this test used to place c1 there).
        q = FakeQueue([track(1), track(2), clip_item("c2", CLIP2), clip_item("c1", CLIP), track(3)], current=2)
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


class RecSleeper(object):
    """Records each sleep's length; an optional hook(secs) fires per call."""
    def __init__(self, hook=None):
        self.secs = []
        self._hook = hook

    def __call__(self, secs):
        self.secs.append(secs)
        if self._hook is not None:
            self._hook(secs)


def rec_cap(hook=None):
    sl = RecSleeper(hook)
    return interaction.InteractionCapability(timer_factory=FakeTimer, clock=lambda: 1000.0, sleeper=sl), sl


def calls_of(q, kind):
    return [c for c in q.calls if c[0] == kind]


ORIG8 = ["t%d" % i for i in range(1, 9)]


class FinishRuleTest(unittest.TestCase):
    """Design 4.8 A1.1 (spike 4, 3.3-1). In queue mode HA `playing` with ANOTHER media id ends the clip only after
    it has persisted >= say_queue_other_item_ms (default 1500) continuously; any reading back on the clip resets
    it; not-`playing` keeps the two-reading rule. The MA cross-check is gone. Replaces QueueFlickerTest, which
    pinned that cross-check."""

    def radio(self, script, poll_ms=500):
        q = FakeQueue([station()], current=0, elapsed=1799.0)
        q.clip_never_idle = True                      # only the scripted HA reads end the clip
        q.ha_script = list(script)                    # first entry = the start-poll read
        ctx = ctx_for(q)
        ctx.settings.say_poll_ms = poll_ms
        return q, ctx

    def test_three_quarter_second_flip_ends_only_at_idle(self):
        # Spike 4: clip, clip, song for ~0.75 s (three 250 ms reads), clip, idle.
        q, ctx = self.radio(["clip", "clip", "other", "other", "other", "clip", "idle", "idle"], poll_ms=250)
        with self.assertLogs("resolver", "INFO") as lg:
            r = say(new_cap(), ctx)
        self.assertEqual(q.ha_script, [])             # the finish poll read on through BOTH idle readings
        self.assertTrue(r["metadata"]["clips"][0]["ended"])
        self.assertEqual(calls_of(q, "play_index"), [("play_index", "st1", 0)])
        self.assertTrue(any("finish-poll exit" in m and "state=idle" in m for m in lg.output))
        self.assertFalse(any("persisted" in m and "finish-poll exit" in m for m in lg.output))

    def test_other_item_persisting_ends_at_the_threshold_not_before(self):
        q, ctx = self.radio(["clip"] + ["other"] * 8)
        with self.assertLogs("resolver", "INFO") as lg:
            r = say(new_cap(), ctx)
        # other@0.0, 0.5, 1.0 do not end it; other@1.5 does. Then the restore read takes one more.
        self.assertEqual(len(q.ha_script), 8 - 4 - 1)
        self.assertTrue(any("finish-poll exit after 1.5s" in m and "persisted" in m for m in lg.output))
        self.assertTrue(r["metadata"]["clips"][0]["ended"])
        self.assertEqual(calls_of(q, "play_index"), [("play_index", "st1", 0)])

    def test_threshold_comes_from_settings(self):
        q, ctx = self.radio(["clip"] + ["other"] * 10)
        ctx.settings.say_queue_other_item_ms = 2500
        with self.assertLogs("resolver", "INFO") as lg:
            say(new_cap(), ctx)
        self.assertEqual(len(q.ha_script), 10 - 6 - 1)
        self.assertTrue(any("finish-poll exit after 2.5s" in m for m in lg.output))

    def test_a_reading_back_on_the_clip_resets_the_persistence(self):
        # 1.0 s of "other" twice (and once more around a blank reading) never adds up to 1.5 s.
        script = (["clip"] + ["other"] * 3 + ["clip"] + ["other"] * 3 + ["blank"] + ["other"] * 3
                  + ["clip", "idle", "idle"])
        q, ctx = self.radio(script)
        with self.assertLogs("resolver", "INFO") as lg:
            say(new_cap(), ctx)
        self.assertEqual(q.ha_script, [])
        self.assertTrue(any("finish-poll exit" in m and "state=idle" in m for m in lg.output))

    def test_no_ma_read_during_the_finish_wait(self):
        q, ctx = self.radio(["clip", "clip", "other", "other", "clip", "idle", "idle"])
        say(new_cap(), ctx)
        ev = q.events
        clip_mid = "builtin://radio/" + CLIP
        i0 = ev.index(("ha", "playing", clip_mid))
        idle = [i for i, e in enumerate(ev) if e == ("ha", "idle", clip_mid)]
        self.assertNotIn(("ma",), ev[i0:idle[1] + 1])

    def test_raised_enqueue_that_landed_uses_the_same_rule(self):
        q, ctx = self.radio(["clip", "clip", "other", "other", "other", "clip", "idle", "idle"])
        q.enqueue_raises_after_landing = True
        r = say(new_cap(), ctx)
        self.assertEqual(q.ha_script, [])
        self.assertEqual(len(calls_of(q, "enqueue")), 1)
        self.assertEqual(calls_of(q, "play_index"), [("play_index", "st1", 0)])
        self.assertTrue(r["metadata"]["clips"][0]["ended"])

    def test_ha_idle_ends_the_wait_on_two_readings(self):
        q = FakeQueue([station()], current=0, elapsed=1799.0)
        q.clip_play_reads = 2
        r = say(new_cap(), ctx_for(q))
        self.assertEqual(q.clip_reads_at_play_index, [(0, "idle")])
        self.assertEqual(r["metadata"]["resume"], "queue")

    def test_the_cross_check_is_gone(self):
        self.assertFalse(hasattr(interaction.InteractionCapability, "_queue_clip_checker"))


class DeletePermissionTest(unittest.TestCase):
    """Design 4.8 A1.2: delete_permission(state_result, index_of, qiid) -> (bool, reason), fail closed."""
    IDX = {"t1": 0, "t2": 1, "t3": 2, "c1": 3, "t4": 4, "t5": 5}

    def st(self, **kw):
        base = {"current_index": 2, "index_in_buffer": 2, "items": 6, "current_item": {"queue_item_id": "t3"}}
        base.update(kw)
        return base

    def test_after_the_buffer_is_permitted(self):
        ok, why = interaction.delete_permission(self.st(), self.IDX, "c1")
        self.assertTrue(ok, why)

    def test_current_index_unknown_still_permits_after_the_buffer(self):
        self.assertTrue(interaction.delete_permission(self.st(current_index=None), self.IDX, "c1")[0])

    def test_fail_closed(self):
        no_key = self.st()
        del no_key["index_in_buffer"]
        cases = [
            (no_key, "c1", "index_in_buffer missing"),
            (self.st(index_in_buffer=None), "c1", "index_in_buffer missing"),
            (self.st(index_in_buffer="2"), "c1", "not an integer"),
            (self.st(index_in_buffer=True), "c1", "not an integer"),
            (self.st(index_in_buffer=2.5), "c1", "not an integer"),
            (self.st(index_in_buffer=-1), "c1", "outside the queue"),
            (self.st(index_in_buffer=6), "c1", "outside the queue"),
            (self.st(index_in_buffer=1), "c1", "below current_index"),
            (self.st(items=None), "c1", "item count unknown"),
            (self.st(), "c9", "not in the queue"),
            (self.st(current_index=3, index_in_buffer=3, current_item={"queue_item_id": "c1"}), "c1",
             "still current"),
            (self.st(index_in_buffer=3), "c1", "within the buffer"),
            (self.st(), "t1", "within the buffer"),
        ]
        for st, cid, frag in cases:
            with self.subTest(st=st, cid=cid):
                ok, why = interaction.delete_permission(st, self.IDX, cid)
                self.assertFalse(ok)
                self.assertIn(frag, why)


class BufferAwareCleanupTest(unittest.TestCase):
    """Design 4.8 A1.3/A1.4/A1.8: verified deletes, retries at +1/+2 s, one buffer-reset retry."""

    def q8(self):
        return FakeQueue([track(i) for i in range(1, 9)], current=2, elapsed=47.0)

    def test_delete_waits_for_the_lagging_buffer_reset_and_retries(self):
        # A1.9 case 3: play_index lands but MA keeps the buffer at the clip for a few reads.
        q = self.q8(); q.buffer_lag = 4
        cap, sl = rec_cap()
        with self.assertLogs("resolver", "INFO") as lg:
            r = say(cap, ctx_for(q))
        self.assertEqual(calls_of(q, "delete"), [("delete", "c1")])    # never sent while the buffer covered it
        self.assertEqual(r["metadata"]["clips_deleted"], 1)
        self.assertEqual(q.ids(), ORIG8)
        self.assertEqual(len(calls_of(q, "play_index")), 1)             # the retries sufficed: no buffer reset
        self.assertIn(1.0, sl.secs)                                     # the +1 s retry
        self.assertIn(2.0, sl.secs)                                     # the +2 s retry
        self.assertTrue(any("clip c1 kept" in m and "within the buffer" in m for m in lg.output))
        self.assertTrue(any("retry +2s" in m and "clip c1 deleted" in m for m in lg.output))
        # A1.8: every cleanup read logs current_index, index_in_buffer and the clip's index
        self.assertTrue(any("current_index=2 index_in_buffer=3 clips=c1@3" in m for m in lg.output))

    def test_clip_loaded_as_next_gets_exactly_one_buffer_reset(self):
        # A1.9 case 4: playback starts at once, so the buffer is already at the clip (T+1) through +2 s.
        q = self.q8(); q.start_after = [0, None]
        cap, sl = rec_cap()
        with self.assertLogs("resolver", "INFO") as lg:
            r = say(cap, ctx_for(q))
        pis = [i for i, c in enumerate(q.calls) if c[0] == "play_index"]
        self.assertEqual([q.calls[i] for i in pis], [("play_index", "t3", 47), ("play_index", "t3", 47)])
        self.assertEqual(calls_of(q, "delete"), [("delete", "c1")])
        self.assertGreater(q.calls.index(("delete", "c1")), pis[1])     # deleted right after the reset
        self.assertEqual(r["metadata"]["clips_deleted"], 1)
        self.assertEqual(q.ids(), ORIG8)
        self.assertIn(2.0, sl.secs)                                     # the reset came after the +2 s retry
        self.assertFalse(any("will play after" in m for m in lg.output))

    def test_clip_surviving_the_buffer_reset_is_warned_and_kept_recorded(self):
        q = self.q8(); q.start_after = [0, 0]
        cap = new_cap()
        with self.assertLogs("resolver", "INFO") as lg:
            r = say(cap, ctx_for(q))
        self.assertEqual(len(calls_of(q, "play_index")), 2)             # one reset, never a second
        self.assertEqual(calls_of(q, "delete"), [])
        self.assertIn("c1", q.ids())
        self.assertEqual(r["metadata"]["clips_deleted"], 0)
        self.assertEqual(cap._queue_targets[ZONE]["clips"], ["c1"])     # kept for the next sweep
        self.assertIsNone(cap._queue_targets[ZONE]["target"])           # ...but nothing to resume
        warn = [m for m in lg.output
                if m.startswith("WARNING") and "clip c1 will play after the current item" in m]
        self.assertEqual(len(warn), 1)

    def test_delete_reply_error_but_item_gone_counts_as_deleted(self):
        # A1.9 case 8, one way: presence decides, not the reply.
        q = self.q8(); q.delete_mode = "error_but_removes"
        r = say(new_cap(), ctx_for(q))
        self.assertEqual(r["metadata"]["clips_deleted"], 1)
        self.assertEqual(q.ids(), ORIG8)

    def test_delete_reply_ok_but_item_kept_is_not_counted(self):
        # A1.9 case 8, the other way.
        q = self.q8(); q.delete_mode = "ok_but_keeps"
        cap = new_cap()
        with self.assertLogs("resolver", "INFO") as lg:
            r = say(cap, ctx_for(q))
        self.assertEqual(len(calls_of(q, "delete")), 1)
        self.assertEqual(r["metadata"]["clips_deleted"], 0)
        self.assertIn("c1", q.ids())
        self.assertEqual(cap._queue_targets[ZONE]["clips"], ["c1"])
        self.assertTrue(any("clip c1" in m and "still in the queue after delete" in m for m in lg.output))

    def test_unusable_index_in_buffer_withholds_every_delete(self):
        # A1.9 case 9.
        for mode, frag in (("missing", "index_in_buffer missing"), ("nonnumeric", "not an integer"),
                           ("bool", "not an integer"), ("out_of_range", "outside the queue"),
                           ("below_current", "below current_index")):
            with self.subTest(mode=mode):
                q = self.q8(); q.buffer_mode = mode
                cap = new_cap()
                with self.assertLogs("resolver", "INFO") as lg:
                    say(cap, ctx_for(q))
                self.assertEqual(calls_of(q, "delete"), [])
                self.assertEqual(len(calls_of(q, "play_index")), 1)     # no buffer reset on it either
                self.assertIn("c1", q.ids())
                self.assertEqual(cap._queue_targets[ZONE]["clips"], ["c1"])
                self.assertTrue(any("clip c1 kept" in m and frag in m for m in lg.output))

    def test_queue_larger_than_the_read_cap_is_never_counted_deleted(self):
        # A2.1: permission comes from the small window, so the delete IS sent; but presence cannot be verified
        # over CLEANUP_READ_CAP items, so nothing is counted (fail closed).
        q = FakeQueue([track(i) for i in range(1, 502)], current=2, elapsed=47.0)
        cap = new_cap()
        with self.assertLogs("resolver", "INFO") as lg:
            r = say(cap, ctx_for(q))
        self.assertEqual(calls_of(q, "delete"), [("delete", "c1")])
        self.assertEqual(r["metadata"]["clips_deleted"], 0)
        self.assertTrue(any("clip c1 not verified deleted" in m and "too large" in m for m in lg.output))

    def test_superseded_during_the_retries_stops_the_old_turn(self):
        # A1.9 case 11. Without the supersede this run would end in a buffer-reset play_index.
        q = self.q8(); q.buffer_lag = 50
        box = {}

        def hook(secs):
            if secs >= 1.0 and "at" not in box:           # the +1 s retry wait (polls sleep 0.5 s)
                box["at"] = len(q.calls)
                with box["cap"]._lock:
                    box["cap"]._say_gen[ZONE] += 1
        cap, sl = rec_cap(hook)
        box["cap"] = cap
        say(cap, ctx_for(q))
        self.assertIn("at", box)
        self.assertEqual([c for c in q.calls[box["at"]:] if c[0] in ("delete", "play_index")], [])
        self.assertEqual(len(calls_of(q, "play_index")), 1)
        self.assertIn("c1", q.ids())


class PausedAtStartTest(unittest.TestCase):
    """Design 4.8 A1.5 / A1.6: the queue was not playing at capture."""

    def test_station_restarted_by_ma_is_paused_then_resume_deletes_the_clip(self):
        # A1.9 case 5 (spike 4, 3.3-3).
        q = FakeQueue([station()], current=0, state="paused", elapsed=0.0)
        q.restart_item = "st1"
        ctx = ctx_for(q)
        cap = new_cap()
        with self.assertLogs("resolver", "INFO") as lg:
            r = say(cap, ctx)
        self.assertEqual([c for c in ctx.ha.calls if c[1] == "media_pause"],
                         [("media_player", "media_pause", {"entity_id": ZONE})])
        self.assertEqual(q.state, "paused")
        self.assertEqual(calls_of(q, "play_index"), [])
        self.assertEqual(r["metadata"]["resume"], "none")
        self.assertTrue(any("restarted item st1" in m for m in lg.output))
        rec = cap._queue_targets[ZONE]
        self.assertFalse(rec["live"])
        self.assertEqual(rec["target"]["item"], "st1")
        self.assertEqual(rec["clips"], ["c1"])
        self.assertIn("c1", q.ids())
        r2 = capability.run(cap, ctx, {"mode": "resume"}, "rid2")
        self.assertEqual(r2["metadata"]["how"], "queue_pending")
        self.assertLess(q.calls.index(("play_index", "st1", 0)), q.calls.index(("delete", "c1")))
        self.assertEqual(q.ids(), ["st1"])
        self.assertEqual(q.cur()["queue_item_id"], "st1")
        self.assertNotIn(ZONE, cap._queue_targets)

    def test_pending_record_with_the_target_already_playing_is_not_jumped_back(self):
        # A1.6 is for resuming FROM a pause/clip: re-seeking a T that already plays would jump it back.
        q = FakeQueue([track(1), track(2), track(3)], current=1, state="paused", elapsed=47.0)
        q.restart_item = "t2"
        ctx = ctx_for(q)
        cap = new_cap()
        say(cap, ctx)                                 # T restarted by MA, then re-paused (A1.5)
        q.state = "playing"                           # un-paused from elsewhere
        r2 = capability.run(cap, ctx, {"mode": "resume"}, "rid2")
        self.assertEqual(r2["metadata"]["how"], "already_playing")
        self.assertEqual(calls_of(q, "play_index"), [])

    def test_newer_playback_is_neither_paused_nor_jumped(self):
        # A1.9 case 6: the current item is some other item; the clip sits inside its buffer.
        q = FakeQueue([track(1), track(2), track(3)], current=1, state="paused", elapsed=47.0)
        q.restart_item = "t3"
        ctx = ctx_for(q)
        with self.assertLogs("resolver", "INFO") as lg:
            say(new_cap(), ctx)
        self.assertEqual([c for c in ctx.ha.calls if c[1] == "media_pause"], [])
        self.assertEqual(calls_of(q, "play_index"), [])
        self.assertEqual(calls_of(q, "delete"), [])
        self.assertTrue(any("clip c1 kept" in m for m in lg.output))

    def test_newer_playback_deletes_only_what_is_permitted(self):
        q = FakeQueue([track(1), track(2), track(3)], current=1, state="paused", elapsed=47.0)
        q.restart_item = "t1"                          # the clip now lies after the buffer
        ctx = ctx_for(q)
        r = say(new_cap(), ctx)
        self.assertEqual([c for c in ctx.ha.calls if c[1] == "media_pause"], [])
        self.assertEqual(calls_of(q, "play_index"), [])
        self.assertEqual(calls_of(q, "delete"), [("delete", "c1")])
        self.assertEqual(r["metadata"]["clips_deleted"], 1)
        self.assertEqual(q.ids(), ["t1", "t2", "t3"])

    def test_idle_on_the_clip_no_pause_pending_then_resume_deletes(self):
        # A1.9 case 7 (spike 4, 3.3-2).
        q = FakeQueue([track(1), track(2), track(3)], current=1, state="paused", elapsed=47.0)
        ctx = ctx_for(q)
        cap = new_cap()
        say(cap, ctx)
        self.assertEqual([c for c in ctx.ha.calls if c[1] == "media_pause"], [])
        self.assertEqual(cap._queue_targets[ZONE]["clips"], ["c1"])
        self.assertEqual(q.cur()["queue_item_id"], "c1")
        r2 = capability.run(cap, ctx, {"mode": "resume"}, "rid2")
        self.assertEqual(r2["metadata"]["how"], "queue_pending")
        self.assertLess(q.calls.index(("play_index", "t2", 47)), q.calls.index(("delete", "c1")))
        self.assertEqual(q.ids(), ["t1", "t2", "t3"])


class CaptureSweepTest(unittest.TestCase):
    """Design 4.8 A1.7: at capture, recorded clips A1.2 permits are deleted and verified; the rest stay."""

    def test_sweep_deletes_a_permitted_recorded_clip_and_keeps_the_rest(self):
        items = [track(1), clip_item("cB", CLIP2), track(2), track(3), clip_item("cA", CLIP2), track(4)]
        q = FakeQueue(items, current=2, elapsed=47.0)
        cap = new_cap()
        cap._queue_targets[ZONE] = {"gen": 1, "rid": "ridA", "target": {"item": "t2"}, "clips": ["cA", "cB"],
                                    "live": False}
        with self.assertLogs("resolver", "INFO") as lg:
            r = say(cap, ctx_for(q), rid="ridB")
        self.assertLess(q.calls.index(("delete", "cA")), q.calls.index(("enqueue", CLIP)))
        self.assertNotIn(("delete", "cB"), q.calls)
        self.assertNotIn("cA", q.ids())
        self.assertIn("cB", q.ids())
        self.assertTrue(any("clip cB kept" in m for m in lg.output))
        self.assertEqual(cap._queue_targets[ZONE]["clips"], ["cB"])
        self.assertEqual(r["metadata"]["clips_deleted"], 2)          # cA + this turn's own clip


class ReviewAmendmentA2Test(unittest.TestCase):
    """Design 4.8 A2 (review amendment) and the review findings of the A1 commit."""

    def after(self, q, marker):
        return q.events.index(marker)

    def assert_first_delete_is_fast(self, q, clip="c1", n_clips=1):
        ev = q.events
        pi = ev.index(("play_index",))
        dl = ev.index(("delete", clip))
        ma_after = [i for i in range(pi + 1, len(ev)) if ev[i] == ("ma",)]
        self.assertLess(dl, ma_after[1])               # before the SECOND MA read after play_index
        for e in ev[pi:dl]:                            # A2.1: only the small permission window before it
            if e[0] == "items":
                self.assertEqual(e[2], n_clips + interaction.PERMISSION_WINDOW_EXTRA)

    # I1 / I3 ----------------------------------------------------------------------------------------------------
    def test_say_first_delete_precedes_the_buffer_advance(self):
        q = FakeQueue([track(i) for i in range(1, 9)], current=2, elapsed=47.0)
        q.start_after = [1]                            # the buffer moves to T+1 right after the first read
        r = say(new_cap(), ctx_for(q))
        self.assert_first_delete_is_fast(q)
        self.assertEqual(len(calls_of(q, "play_index")), 1)
        self.assertEqual(r["metadata"]["clips_deleted"], 1)
        self.assertEqual(q.ids(), ORIG8)

    def test_pending_resume_first_delete_precedes_the_buffer_advance(self):
        q = FakeQueue([track(1), track(2), track(3)], current=1, state="paused", elapsed=47.0)
        ctx = ctx_for(q)
        cap = new_cap()
        say(cap, ctx)                                  # idle on c1, pending
        q.events[:] = []
        q.start_after = [1]
        r = capability.run(cap, ctx, {"mode": "resume"}, "rid2")
        self.assertEqual(r["metadata"]["how"], "queue_pending")
        self.assert_first_delete_is_fast(q)
        self.assertEqual(len(calls_of(q, "play_index")), 1)
        self.assertEqual(q.ids(), ["t1", "t2", "t3"])

    # I2 / A2.2 --------------------------------------------------------------------------------------------------
    def paused_tracks(self):
        return FakeQueue([track(1), track(2), track(3)], current=1, state="paused", elapsed=47.0)

    def test_watch_pauses_when_the_restart_arrives_reads_late(self):
        q = self.paused_tracks()
        q.restart_item = "t2"; q.restart_delay_reads = 3
        ctx = ctx_for(q)
        cap = new_cap()
        say(cap, ctx)
        self.assertEqual([c for c in ctx.ha.calls if c[1] == "media_pause"],
                         [("media_player", "media_pause", {"entity_id": ZONE})])
        self.assertEqual(calls_of(q, "play_index"), [])
        self.assertEqual(cap._queue_targets[ZONE]["clips"], ["c1"])

    def test_watch_stops_when_another_item_becomes_current(self):
        q = self.paused_tracks()
        # t3 becomes current first; had the watch carried on, it would then see T playing and pause it.
        q.restart_plan = [{"after": 1, "item": "t3", "state": "playing"},
                          {"after": 0, "item": "t2", "state": "playing"}]
        ctx = ctx_for(q)
        with self.assertLogs("resolver", "INFO") as lg:
            say(new_cap(), ctx)
        self.assertEqual([c for c in ctx.ha.calls if c[1] == "media_pause"], [])
        self.assertEqual(calls_of(q, "play_index"), [])
        self.assertTrue(any("another item t3 is current; no pause" in m for m in lg.output))

    def test_watch_stops_on_supersede(self):
        q = FakeQueue([track(1), track(2), clip_item("c1", CLIP), track(3)], current=2, state="idle")
        q.restart_plan = [{"after": 1, "item": "t2", "state": "playing"}]
        q.arm_restart()
        ctx = ctx_for(q)
        calls = {"n": 0}

        def superseded():
            calls["n"] += 1
            return calls["n"] > 2                      # owner for the entry check and the first watch read only
        qm = qm_for(["c1"], target={"item": "t2", "index": 1, "pos": 47.0, "duration": 240.0, "seekable": True})
        new_cap()._queue_not_playing_cleanup(ctx, "rid1", ZONE, qm, superseded)
        self.assertEqual([c for c in ctx.ha.calls if c[1] == "media_pause"], [])
        self.assertEqual(calls_of(q, "delete"), [])

    def test_repause_requires_playing(self):
        q = self.paused_tracks()
        q.restart_plan = [{"after": 0, "item": "t2", "state": "paused"}]     # exact T current, but paused
        ctx = ctx_for(q)
        cap = new_cap()
        say(cap, ctx)
        self.assertEqual([c for c in ctx.ha.calls if c[1] == "media_pause"], [])
        # A1.5 "anything else": the clip after T's buffer is deleted; T stays the pending target.
        self.assertEqual(calls_of(q, "delete"), [("delete", "c1")])
        rec = cap._queue_targets[ZONE]
        self.assertEqual((rec["target"]["item"], rec["clips"], rec["live"]), ("t2", [], False))
        r2 = capability.run(cap, ctx, {"mode": "resume"}, "rid2")
        self.assertEqual(r2["metadata"]["how"], "unpause_queue")          # no clip left: un-pause in place

    # I4 / A2.3 --------------------------------------------------------------------------------------------------
    def test_repause_refreshes_the_pending_position_from_that_read(self):
        q = self.paused_tracks()
        q.restart_plan = [{"after": 1, "item": "t2", "state": "playing", "elapsed": 49.0}]
        ctx = ctx_for(q)
        cap = new_cap()
        say(cap, ctx)
        self.assertEqual(cap._queue_targets[ZONE]["target"]["pos"], 49.0)

    def test_resume_after_the_user_replayed_and_repaused_seeks_from_the_live_position(self):
        q = self.paused_tracks()
        ctx = ctx_for(q)
        cap = new_cap()
        say(cap, ctx)                                  # pending at 47 s, idle on c1
        q.current = q.ids().index("t2"); q.state = "paused"; q.elapsed = 120.0   # app: play, listen, pause
        r = capability.run(cap, ctx, {"mode": "resume"}, "rid2")
        self.assertEqual(r["metadata"]["how"], "queue_pending")
        self.assertEqual(calls_of(q, "play_index"), [("play_index", "t2", 120)])
        self.assertEqual(q.ids(), ["t1", "t2", "t3"])

    # minor --------------------------------------------------------------------------------------------------------
    def test_superseded_check_directly_before_the_buffer_reset_play_index(self):
        q = FakeQueue([track(i) for i in range(1, 9)], current=2, elapsed=47.0)
        q.start_after = [0, None]                      # would need the buffer reset (case 4)
        cap = new_cap()
        real = interaction.parse_queue_capture

        def parse(reply, now):
            if calls_of(q, "play_index"):              # the buffer reset's position read
                with cap._lock:
                    cap._say_gen[ZONE] += 1
            return real(reply, now)
        interaction.parse_queue_capture = parse
        try:
            say(cap, ctx_for(q))
        finally:
            interaction.parse_queue_capture = real
        self.assertEqual(len(calls_of(q, "play_index")), 1)

    def test_superseded_exit_leaves_a_clip_before_the_successors_current_item(self):
        # The realistic barge-in layout: our clip c1 sits BEFORE the successor's current clip c2, inside MA's
        # buffer. No delete is sent (it would be a silent no-op) and c1 stays recorded.
        q = FakeQueue([track(1), track(2), clip_item("c1", CLIP), clip_item("c2", CLIP2), track(3)], current=3)
        ctx = ctx_for(q)
        cap = new_cap()
        cap._queue_targets[ZONE] = {"gen": 9, "rid": "ridB", "target": None, "clips": ["c2"], "live": True}
        # A target at t2 puts the permission window over c1 (index 2), so it is index_in_buffer (3) that
        # refuses the delete -- not the window missing it.
        qm = qm_for(["c1"], target={"item": "t2", "index": 1, "pos": 47.0, "duration": 240.0, "seekable": True})
        with self.assertLogs("resolver", "INFO") as lg:
            cap._queue_superseded_exit(ctx, "ridA", ZONE, qm, 3)
        self.assertTrue(any("clip c1 kept" in m and "within the buffer" in m for m in lg.output))
        self.assertEqual(calls_of(q, "delete"), [])
        self.assertEqual(qm["clips"], ["c1"])
        self.assertIn("c1", q.ids())


class RepauseWatchTakeoverTest(unittest.TestCase):
    """Design 4.8 A2.2a: a newer turn takes over the zone when the reply generation advances OR the zone's queue
    record is no longer this turn's (voice "resume", note_playback). The watch must then never pause."""

    def paused_tracks(self):
        return FakeQueue([track(1), track(2), track(3)], current=1, state="paused", elapsed=47.0)

    def run_with_midwatch(self, q, action):
        ctx = ctx_for(q)
        box = {"watching": False, "fired": False}

        def hook(secs):
            if box["watching"] and not box["fired"]:
                box["fired"] = True
                box["calls_at"] = len(ctx.ha.calls)
                action(cap, ctx)
        cap, sl = rec_cap(hook)
        real = cap._queue_not_playing_cleanup

        def watch(*a, **k):
            box["watching"] = True
            return real(*a, **k)
        cap._queue_not_playing_cleanup = watch
        say(cap, ctx)
        self.assertTrue(box["fired"])
        return ctx, cap, box

    def test_note_playback_mid_watch_stops_the_watch(self):
        q = self.paused_tracks()
        # T appears paused, then playing: without the takeover rule the watch would pause it.
        q.restart_plan = [{"after": 0, "item": "t2", "state": "paused"},
                          {"after": 1, "item": "t2", "state": "playing"}]
        def act(c, x):
            box_ev["at"] = len(q.events)
            c.note_playback(x, ZONE, "library://track/2")
        box_ev = {}
        ctx, cap, box = self.run_with_midwatch(q, act)
        self.assertEqual([c for c in ctx.ha.calls if c[1] == "media_pause"], [])
        # A2.2a "stop at once": no further MA read once the record is no longer this turn's.
        self.assertEqual([e for e in q.events[box_ev["at"]:] if e == ("ma",)], [])

    def test_takeover_during_the_read_that_shows_t_playing_skips_the_pause(self):
        # The record changes while the very read reporting T `playing` is in flight: only the check made
        # immediately before the pause can see it.
        q = self.paused_tracks()
        q.restart_plan = [{"after": 1, "item": "t2", "state": "playing"}]
        ctx = ctx_for(q)
        cap = new_cap()
        box = {"watching": False, "fired": False}
        real = cap._queue_not_playing_cleanup

        def watch(*a, **k):
            box["watching"] = True
            return real(*a, **k)
        cap._queue_not_playing_cleanup = watch

        def on_read(res):
            cur = (res.get("current_item") or {}).get("queue_item_id")
            if box["watching"] and not box["fired"] and cur == "t2" and res.get("state") == "playing":
                box["fired"] = True
                cap.note_playback(ctx, ZONE, "library://track/2")
        q.on_ma_read = on_read
        say(cap, ctx)
        self.assertTrue(box["fired"])
        self.assertEqual([c for c in ctx.ha.calls if c[1] == "media_pause"], [])

    def test_voice_resume_mid_watch_is_not_undone(self):
        q = self.paused_tracks()
        q.restart_plan = [{"after": 0, "item": "t2", "state": "paused"}]
        ctx, cap, box = self.run_with_midwatch(
            q, lambda c, x: capability.run(c, x, {"mode": "resume"}, "ridR"))
        later = ctx.ha.calls[box["calls_at"]:]
        self.assertIn(("media_player", "media_play", {"entity_id": ZONE}), later)   # the user's resume
        self.assertEqual([c for c in ctx.ha.calls if c[1] == "media_pause"], [])     # ...never undone
        self.assertEqual(q.state, "playing")

    def test_unidentified_reply_clip_does_not_end_the_watch(self):
        q = self.paused_tracks()
        q.first_wrapper = "odd://"                     # the clip is current but not identified / recorded
        q.restart_item = "t2"; q.restart_delay_reads = 3
        ctx = ctx_for(q)
        cap = new_cap()
        r = say(cap, ctx)
        self.assertEqual(r["metadata"]["clips_unidentified"], 1)
        self.assertEqual([c for c in ctx.ha.calls if c[1] == "media_pause"],
                         [("media_player", "media_pause", {"entity_id": ZONE})])


class BufferAnchorTest(unittest.TestCase):
    """Design 4.8 A3 (live check 4, 20:09): enqueue=play inserts after index_in_buffer, so the first clip's anchor
    is the buffered index when it is consistent with the capture, else current_index."""

    def replaces(self, q):
        return calls_of(q, "replace")

    def test_buffered_prior_clip_station_question_then_resume_takes_the_queue_path(self):
        # A3.3 case 1: [T, C1], T current and paused, the pending "Paused." clip C1 buffered at index 1.
        q = FakeQueue([station(), clip_item("c1", CLIP)], current=0, state="paused", elapsed=0.0)
        q.buffer = 1
        q.n = 1                                        # the next inserted clip is c2
        ctx = ctx_for(q)
        cap = new_cap()
        cap._queue_targets[ZONE] = {"gen": 1, "rid": "ridP", "live": False, "clips": ["c1"],
                                    "target": {"item": "st1", "index": 0, "pos": 0.0, "duration": 0.0,
                                               "seekable": False, "uri": "library://radio/4"}}
        with cap._lock:
            cap._say_gen[ZONE] = 1
        with self.assertLogs("resolver", "INFO") as lg:
            r = say(cap, ctx, uri=CLIP2, rid="ridQ")
        self.assertEqual(q.ids(), ["st1", "c1", "c2"])                   # inserted after the buffered clip
        self.assertEqual(r["metadata"]["clips_unidentified"], 0)
        self.assertTrue(any("anchor=1 (buffer)" in m for m in lg.output))
        self.assertEqual(sorted(cap._queue_targets[ZONE]["clips"]), ["c1", "c2"])
        r2 = capability.run(cap, ctx, {"mode": "resume"}, "ridR")
        self.assertEqual(r2["metadata"]["how"], "queue_pending")
        self.assertEqual(calls_of(q, "play_index"), [("play_index", "st1", 0)])
        self.assertEqual(sorted(c[1] for c in calls_of(q, "delete")), ["c1", "c2"])
        self.assertEqual(q.ids(), ["st1"])                               # verified: both gone
        self.assertEqual(self.replaces(q), [])                           # no URI replay
        self.assertNotIn(ZONE, cap._queue_targets)

    def test_playlist_pause_question_resume_end_to_end(self):
        # A3.3 case 2: a playing playlist has the next track buffered (index_in_buffer = current + 1).
        q = FakeQueue([track(1, 240), track(2), track(3)], current=0, state="playing", elapsed=60.0)
        q.buffer = 1
        ctx = ctx_for(q)
        cap = new_cap()
        capability.run(cap, ctx, {"mode": "duck"}, "ridP")
        capability.run(cap, ctx, {"mode": "pause"}, "ridP")
        rp = say(cap, ctx, rid="ridP")                 # "Paused." -> c1 after the buffered s2; MA idles on it
        self.assertEqual(q.ids(), ["t1", "t2", "c1", "t3"])
        self.assertEqual(rp["metadata"]["clips_unidentified"], 0)
        self.assertEqual(calls_of(q, "play_index"), [])
        rq = say(cap, ctx, uri=CLIP2, rid="ridQ")      # the question: inherits, c2 after c1
        self.assertEqual(q.ids(), ["t1", "t2", "c1", "c2", "t3"])
        self.assertEqual(rq["metadata"]["clips_unidentified"], 0)
        self.assertEqual(sorted(cap._queue_targets[ZONE]["clips"]), ["c1", "c2"])
        rr = capability.run(cap, ctx, {"mode": "resume"}, "ridR")
        self.assertEqual(rr["metadata"]["how"], "queue_pending")
        self.assertEqual(calls_of(q, "play_index"), [("play_index", "t1", 60)])      # the captured position
        self.assertEqual(sorted(c[1] for c in calls_of(q, "delete")), ["c1", "c2"])
        self.assertEqual(q.ids(), ["t1", "t2", "t3"])
        self.assertEqual(q.cur()["queue_item_id"], "t1")
        self.assertEqual(self.replaces(q), [])

    def test_invalid_buffer_anchors_on_the_current_index(self):
        # A3.3 case 3: the REPORTED index_in_buffer is unusable; MA really inserts after the current item.
        for mode in ("missing", "nonnumeric", "bool", "below_current", "out_of_range"):
            with self.subTest(mode=mode):
                q = FakeQueue([track(i) for i in range(1, 9)], current=2, elapsed=47.0)
                q.buffer_mode = mode
                with self.assertLogs("resolver", "INFO") as lg:
                    r = say(new_cap(), ctx_for(q))
                self.assertTrue(any("anchor=2 (current)" in m for m in lg.output))
                self.assertEqual(r["metadata"]["clips_unidentified"], 0)

    def test_buffer_equal_to_current_is_unchanged(self):
        # A3.3 case 4 (regression): the common playing case, buffer == current.
        q = FakeQueue([track(i) for i in range(1, 9)], current=2, elapsed=47.0)
        with self.assertLogs("resolver", "INFO") as lg:
            r = say(new_cap(), ctx_for(q))
        self.assertTrue(any("anchor=2 (buffer)" in m for m in lg.output))
        self.assertEqual(r["metadata"]["clips_unidentified"], 0)
        self.assertEqual(calls_of(q, "play_index"), [("play_index", "t3", 47)])
        self.assertEqual(q.ids(), ORIG8)


if __name__ == "__main__":
    unittest.main()
