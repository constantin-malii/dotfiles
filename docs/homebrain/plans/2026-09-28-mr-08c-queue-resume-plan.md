# MR-08c The Queue Survives a Spoken Reply — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A question (or pause/resume) during a playlist, album, `.m3u` or radio keeps the Music Assistant queue:
the reply clip is inserted, not replacing, and the interrupted item resumes at its position afterwards.

**Architecture:** `interaction._say` gains a *queue mode* (default on, kill switch `say_queue_resume`): capture the
current queue item before the pause, play each clip with HA `music_assistant.play_media enqueue="play"`, identify
each clip by exact + position-anchored identity, resume with one `player_queues/play_index(seek_position=…)`
decided by a bounded confirmation table, delete only recorded clips, and keep a per-zone record for barge-in and
pending resume. Anything that fails before the capture completes runs today's legacy path unchanged.

**Tech Stack:** Python 3.5-compatible stdlib, `unittest`, raw-socket MA WebSocket client (`maconn.py`), HA REST.

**Spec:** `docs/homebrain/2026-09-28-mr-08c-queue-resume-design.md` (v2; operator-approved as the design basis;
peer review `dotfiles-61` aligned; spike 3 results in §3.2). Read §3 (measured MA behaviour), §4.3–§4.6 (the
algorithm) and §4.4 (decision table) before starting — they are binding. This plan revision folds in the peer
review of the first plan draft (settle vs lag, eager recovery, superseded-without-successor, the AN-01 honesty
rule, live-anchor identity, clock skew, radio-by-URL, and four smaller points).

## Global Constraints

- Python **3.5** syntax only in resolver modules — no f-strings, no `_` numeric separators, no annotations
  (`tests/test_py35_compat.py` parses every module).
- Worktree `D:\repos\dotfiles\.claude\worktrees\mr-08c-queue-resume`, branch `homebrain/mr-08c-queue-resume`;
  resolver code in `docs/homebrain/mass-resolver/`. Run tests from there: full suite
  `python -m unittest discover -s tests -t .` (baseline **895 OK, 2 skipped**); one module
  `python -m unittest tests.test_queue_resume -v`.
- **The legacy path must stay byte-for-byte in behaviour**: every existing test in `tests/test_interaction.py`
  passes **unmodified** (their `FakeCtx` has no `ma_factory`, which selects legacy mode). If an existing test
  would have to change, STOP and report it — the only permitted legacy change is the one named in Task 5 Step 3d.
- Queue mode is on only when `settings.say_queue_resume` (default True), `ctx.ma_factory` and
  `settings.queue_id` all exist. Every new setting is read with `getattr(..., default)`.
- **One MA connection per phase** (`_ma_open` / `_ma_close`), never held across a clip wait.
- In queue mode, "is this a spent reply clip?" uses the new **`is_reply_clip_uri`** (TTS / signed URL / announce
  chime) — never `_is_reply_uri`, which also matches a radio station stored as `builtin://radio/http…`.
- URI replay (`music_assistant.play_media` without `enqueue`) in queue mode only per the §4.4 table
  (outcome `fallback_uri`), never after `play_index` was confirmed or may have landed.
- Delete only recorded queue item ids; never delete by URI match or guess.
- Implementation only: no SSH, no live host, never run `resolver.py`. Commits: human-style, **no AI
  attribution, no Co-Authored-By**; code and docs in separate commits.
- Existing files may be CRLF: preserve line endings; `git diff --numstat` must show only intended lines.

## Review Focus

1. **Double play / double restart** — URI replay after `play_index` succeeded or may have; settle re-resuming on a
   merely lagging MA: pinned by the lag, raised-unknown and exception-after-resume tests (Task 4).
2. **Deleting the wrong item** — identical earlier leftovers, the same fixed reply twice (the anchor itself an
   identical clip), a containment-only URI, long queues: Tasks 2–3, 5.
3. **Silence** — late-landing enqueue, a clip that never goes idle, pause→question→resume, a turn superseded by
   one that never captures: Tasks 4–5.
4. **Barge-in** resuming the first answer's clip instead of the song: Task 5.
5. **Legacy regressions** — kill switch, no-`ma_factory` contexts, radio stations added by URL: Task 3 + the
   untouched existing suite.

---

### Task 1: MA queue helpers in `maconn.py`

**Files:**
- Modify: `docs/homebrain/mass-resolver/maconn.py` (add methods after `playlist_tracks`)
- Test: `docs/homebrain/mass-resolver/tests/test_maconn.py` (append a class)

**Interfaces:**
- Produces: `MA.queue_state(queue_id)`, `MA.queue_items(queue_id, offset=0, limit=50)`,
  `MA.play_index(queue_id, queue_item_id, seek_position=0)`, `MA.delete_item(queue_id, queue_item_id)` — each
  returns MA's raw reply message (dict or None); callers check `error_code`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_maconn.py` (it imports `from maconn import MA, WS_CMD`):

```python
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
```

- [ ] **Step 2: Run to verify they fail** — `python -m unittest tests.test_maconn.QueueHelpersTest -v`
  → FAIL (`AttributeError: 'MA' object has no attribute 'queue_state'` etc.).

- [ ] **Step 3: Implement** — in `maconn.py`, after `playlist_tracks`:

```python
    # MR-08c queue helpers (design 4.2). Raw replies: callers check "error_code".
    def queue_state(self, queue_id):
        return self.cmd("player_queues/get", queue_id=queue_id)

    def queue_items(self, queue_id, offset=0, limit=50):
        return self.cmd("player_queues/items", queue_id=queue_id, offset=offset, limit=limit)

    def play_index(self, queue_id, queue_item_id, seek_position=0):
        # One call resumes at a position (spike 3, design 3.2-3): no play-from-0-then-seek blip.
        return self.cmd("player_queues/play_index", queue_id=queue_id, index=queue_item_id,
                        seek_position=int(seek_position))

    def delete_item(self, queue_id, queue_item_id):
        return self.cmd("player_queues/delete_item", queue_id=queue_id, item_id_or_index=queue_item_id)
```

- [ ] **Step 4: Run** — `python -m unittest tests.test_maconn -v` → all PASS.

- [ ] **Step 5: Commit**

```bash
git add docs/homebrain/mass-resolver/maconn.py docs/homebrain/mass-resolver/tests/test_maconn.py
git commit -m "feat(resolver): MA queue helpers - state, items window, play_index at a position, delete"
```

---

### Task 2: Pure queue-mode helpers + `say_queue_resume` setting

**Files:**
- Modify: `docs/homebrain/mass-resolver/interaction.py` (module level, after the imports/constants, before `class InteractionCapability`)
- Modify: `docs/homebrain/mass-resolver/config.py` (one line next to `say_pause_before_reply`)
- Create: `docs/homebrain/mass-resolver/tests/test_queue_resume.py`
- Test: `docs/homebrain/mass-resolver/tests/test_config.py`

**Interfaces:**
- Produces (module level in `interaction`): `_ma_ok(reply) -> bool`; `is_reply_clip_uri(uri) -> bool`;
  `parse_queue_capture(reply, now) -> (cap|None, why|None)` where
  `cap = {"item","index","pos","duration","seekable","uri","state","extrapolated"}`; `clip_uri_of(item) -> str`;
  `tts_id(uri) -> str`; `anchored_clip(items, offset, anchor_index, played_uri) -> (queue_item_id|None,
  index|None, why|None)`; `seek_target(target) -> int`; constants `CONFIRM_BUDGET_S = 4.0`, `SEEK_MIN_S = 2.0`,
  `SEEK_END_MARGIN_S = 5.0`, `MAX_EXTRAPOLATE_S = 60.0`; `Settings.say_queue_resume` (default True).

- [ ] **Step 1: Write the failing tests** — create `tests/test_queue_resume.py`:

```python
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
```

Append to `tests/test_config.py` (inside the class holding the `playlist_aliases` tests):

```python
    def test_say_queue_resume_default_on_and_switchable(self):
        self.assertTrue(config.Settings({}).say_queue_resume)
        self.assertFalse(config.Settings({"say_queue_resume": False}).say_queue_resume)
```

- [ ] **Step 2: Run to verify they fail** — `python -m unittest tests.test_queue_resume tests.test_config -v`
  → FAIL (`AttributeError: module 'interaction' has no attribute 'tts_id'` …, `say_queue_resume`).

- [ ] **Step 3: Implement** — in `config.py`, after the `say_pause_before_reply` line:

```python
        # MR-08c kill switch: false = the legacy replace-and-replay reply path, exactly as before.
        self.say_queue_resume = bool(cfg.get("say_queue_resume", True))
```

In `interaction.py`, module level before `class InteractionCapability`:

```python
# --- MR-08c queue mode (design docs/homebrain/2026-09-28-mr-08c-queue-resume-design.md) -------------------
_CLIP_WRAPPERS = ("builtin://radio/", "builtin://track/")   # MA's two measured wrappings of a played URL
CONFIRM_BUDGET_S = 4.0         # how long to poll for play_index to show (MA updates queue state async)
SEEK_MIN_S = 2.0               # below this, resume from the start
SEEK_END_MARGIN_S = 5.0        # seeking this close to the end would skip the song
MAX_EXTRAPOLATE_S = 60.0       # elapsed_time_last_updated is MA's clock, `now` is ours: bound the delta


def _ma_ok(reply):
    return isinstance(reply, dict) and "error_code" not in reply


def _float(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def is_reply_clip_uri(uri):
    """A spent reply clip sitting in an MA queue: a TTS render, a signed URL, or the announce chime.
    Deliberately NARROWER than _is_reply_uri: a radio station added to MA by URL is also stored as
    builtin://radio/http..., and must stay a resumable queue item (peer review of the plan, finding 8)."""
    u = (uri or "").lower()
    return ("tts_proxy" in u or "authsig=" in u
            or (u.startswith("builtin://track/") and "/media/local/" in u))


def parse_queue_capture(reply, now):
    """player_queues/get reply -> (capture, None) or (None, why). Position per design 4.3-1: captured
    before the pause; extrapolated from elapsed_time_last_updated only while playing (MA does not refresh
    elapsed_time on pause -- spike 3), and only for a sane delta between the two clocks."""
    if not _ma_ok(reply):
        return None, "ma error %s" % ((reply or {}).get("error_code") if isinstance(reply, dict) else "no reply")
    q = reply.get("result") or {}
    ci = q.get("current_item") or {}
    qid = ci.get("queue_item_id")
    if not qid:
        return None, "no current item"
    mi = ci.get("media_item") or {}
    dur = _float(ci.get("duration") or mi.get("duration"))
    pos = _float(q.get("elapsed_time"))
    extrapolated = 0.0
    upd = q.get("elapsed_time_last_updated")
    if q.get("state") == "playing" and upd is not None:
        delta = now - _float(upd)
        if 0.0 <= delta <= MAX_EXTRAPOLATE_S:
            pos += delta
            extrapolated = delta
    if dur > 0:
        pos = min(pos, dur)
    return {"item": qid, "index": q.get("current_index"), "pos": pos, "duration": dur,
            "seekable": mi.get("media_type") == "track" and dur > 0,
            "uri": mi.get("uri") or ci.get("uri") or "", "state": q.get("state"),
            "extrapolated": extrapolated}, None


def clip_uri_of(item):
    """The URL a queue item was played from, with exactly one known MA wrapper removed."""
    mi = item.get("media_item") or {}
    u = mi.get("uri") or item.get("uri") or ""
    for w in _CLIP_WRAPPERS:
        if u.startswith(w):
            return u[len(w):]
    return u


def tts_id(uri):
    """The name MA gives a TTS clip: the URL's last path segment without query or extension."""
    seg = (uri or "").split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1]
    return seg.rsplit(".", 1)[0] if "." in seg else seg


def anchored_clip(items, offset, anchor_index, played_uri):
    """Exact + position-anchored identity (design 4.3-4). `items` is a window read starting at queue index
    `offset`; the clip must sit at anchor_index + 1 and match the played URL exactly (name only when the
    item carries no URI). -> (queue_item_id, index, None) or (None, None, why)."""
    want = anchor_index + 1
    rel = want - offset
    if rel < 0 or rel >= len(items):
        return None, None, "nothing at index %d" % want
    it = items[rel]
    u = clip_uri_of(it)
    if u:
        if u == played_uri:
            return it.get("queue_item_id"), want, None
        return None, None, "item at index %d differs from the played url" % want
    if it.get("name") and it.get("name") == tts_id(played_uri):
        return it.get("queue_item_id"), want, None
    return None, None, "item at index %d is not the clip" % want


def seek_target(target):
    """seek_position for play_index (design 4.3-7 gates); 0 means from the start."""
    p, d = target["pos"], target["duration"]
    if target["seekable"] and p >= SEEK_MIN_S and p <= d - SEEK_END_MARGIN_S:
        return int(p)
    return 0
```

- [ ] **Step 4: Run** — `python -m unittest tests.test_queue_resume tests.test_config tests.test_interaction -v`
  → all PASS (test_interaction untouched and green).

- [ ] **Step 5: Commit**

```bash
git add docs/homebrain/mass-resolver/interaction.py docs/homebrain/mass-resolver/config.py docs/homebrain/mass-resolver/tests/test_queue_resume.py docs/homebrain/mass-resolver/tests/test_config.py
git commit -m "feat(resolver): queue-mode helpers - capture parsing, exact anchored clip identity, seek gates"
```

---

### Task 3: Queue mode happy path in `_say` (capture → enqueue → identify → resume → delete)

**Files:**
- Modify: `docs/homebrain/mass-resolver/interaction.py` — `__init__` (one dict), `_play_clip_and_wait`
  (signature + play call), `_say` (capture at the top of its `try`, clip loop, step 9, `finally`), new methods.
- Test: `docs/homebrain/mass-resolver/tests/test_queue_resume.py` (append the harness + class)

**Interfaces:**
- Consumes: Task 1 helpers on the MA object; Task 2 module functions.
- Produces (methods on `InteractionCapability`): `_ma_open(ctx)`, `_ma_close(ma)`, `_queue_on(ctx)`,
  `_queue_capture(ctx, rid, zone, my_gen) -> qm|None`, `_queue_adopt_target(qm, rid, zone)`,
  `_queue_record_clip(ctx, rid, zone, qm, played_uri, clip, my_gen)`, `_queue_confirm(ma, queue_id, item,
  poll_secs) -> (seen, any_read_ok)`, `_queue_resume(ctx, rid, zone, qm, source_id, call_timeout) -> bool`,
  `_queue_settle(ctx, rid, zone, qm, seek, poll_secs, known_clips)`, `_queue_finish(ctx, rid, zone, qm,
  my_gen)`; `_play_clip_and_wait(..., enqueue=None, issue=True)`; `self._queue_targets` (zone → record, guarded
  by `_lock`). `qm` keys: `queue_id, cap, target, clips, played, unrecorded, anchor, unidentified, resume,
  seeked, deleted, inherited_from`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_queue_resume.py` (above `if __name__`):

```python
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
```

`test_paused_queue_at_enqueue`: `FakeSettings` leaves `say_pause_before_reply` at its default True, so `QueueHA`
sets the queue `paused` before the enqueue — the production order measured in spike 3.

- [ ] **Step 2: Run to verify they fail** — `python -m unittest tests.test_queue_resume.QueueModeTest -v`
  → FAIL (queue replaced: `("replace", CLIP)` calls; `KeyError: 'resume'`).

- [ ] **Step 3: Implement.**

3a. In `__init__`, after the `self._replies = {}` block:

```python
        self._queue_targets = {}                      # MR-08c: zone -> {"gen", "rid", "target", "clips",
                                                      #   "live"}. The interrupted item and the reply clips a
                                                      #   turn put in the queue: a superseding turn or a later
                                                      #   "resume" continues from it (design 4.5-4.6).
                                                      #   Guarded by _lock.
```

3b. `_play_clip_and_wait` — signature and the play call:

```python
    def _play_clip_and_wait(self, ctx, rid, zone, norm_uri, match_key, clip, opts, superseded,
                            enqueue=None, issue=True):
```
replace the play call block (the `self._say_call(... "play_media" ...)` + `out["issued"] = True`) with:

```python
        if issue:
            data = {"entity_id": zone, "media_id": norm_uri}
            if enqueue:
                # MR-08c: insert the clip instead of replacing the queue (design 4.3-3).
                data["enqueue"] = enqueue
            self._say_call(ctx, rid, zone, "music_assistant", "play_media", data, timeout=opts["call_timeout"])
        out["issued"] = True
```

3c. New methods on `InteractionCapability` (place after `_play_clip_and_wait`, before `_say`):

```python
    # --- MR-08c queue mode -------------------------------------------------------------------------------
    def _queue_on(self, ctx):
        return (bool(getattr(ctx.settings, "say_queue_resume", True))
                and getattr(ctx, "ma_factory", None) is not None
                and bool(getattr(ctx.settings, "queue_id", None)))

    def _ma_open(self, ctx):
        """A fresh MA connection for ONE phase (design 4.2): a reply can idle the socket for minutes."""
        ma = ctx.ma_factory()
        if getattr(ma, "s", None) is None:
            ma.connect()
        return ma

    def _ma_close(self, ma):
        if ma is not None:
            try:
                ma.close()
            except Exception:
                pass

    def _queue_capture(self, ctx, rid, zone, my_gen):
        """Design 4.3-1: capture the interrupted item BEFORE the pause. None -> legacy mode for the turn."""
        if not self._queue_on(ctx):
            return None
        queue_id = ctx.settings.queue_id
        ma = None
        stale = 0
        try:
            ma = self._ma_open(ctx)
            cap, why = parse_queue_capture(ma.queue_state(queue_id), self._clock())
            if cap is None:
                LOG.info("SAY req=%s zone=%s queue capture unavailable (%s); legacy replay", rid, zone, why)
                return None
            try:
                r = ma.queue_items(queue_id, offset=max(0, (cap["index"] or 0) - 10), limit=25)
                window = (r.get("result") or []) if _ma_ok(r) else []
                stale = sum(1 for x in window if is_reply_clip_uri(
                    (x.get("media_item") or {}).get("uri") or x.get("uri") or ""))
            except Exception:
                pass
        except Exception as e:
            LOG.info("SAY req=%s zone=%s queue capture unavailable (%r); legacy replay", rid, zone, e)
            return None
        finally:
            self._ma_close(ma)
        qm = {"queue_id": queue_id, "cap": cap, "target": None, "clips": [], "played": [], "unrecorded": [],
              "anchor": cap["index"] or 0, "unidentified": 0, "resume": "none", "seeked": False,
              "deleted": 0, "inherited_from": None}
        self._queue_adopt_target(qm, rid, zone)
        with self._lock:
            self._queue_targets[zone] = {"gen": my_gen, "rid": rid, "target": qm["target"],
                                         "clips": list(qm["clips"]), "live": True}
        LOG.info("SAY req=%s zone=%s queue capture: item=%s idx=%s pos=%.1f (extrapolated %.1fs) seekable=%s "
                 "stale_reply_clips=%d", rid, zone, cap["item"], cap["index"], cap["pos"], cap["extrapolated"],
                 cap["seekable"], stale)
        return qm

    def _queue_adopt_target(self, qm, rid, zone):
        """Which item this turn resumes. Task 3: the captured item, unless it is itself a reply clip.
        (Task 5 replaces this with barge-in / pending-resume inheritance, design 4.5-4.6.)"""
        cap = qm["cap"]
        if is_reply_clip_uri(cap["uri"]):
            LOG.info("SAY req=%s zone=%s current queue item %s is a reply clip; no resume target",
                     rid, zone, cap["item"])
            return
        qm["target"] = cap

    def _queue_publish_clips(self, zone, my_gen, qm):
        with self._lock:
            rec = self._queue_targets.get(zone)
            if rec is not None and rec.get("gen") == my_gen:
                rec["clips"] = list(qm["clips"])

    def _queue_record_clip(self, ctx, rid, zone, qm, played_uri, clip, my_gen):
        """Design 4.3-4: record this clip's queue id by exact identity at the anchored position. enqueue=play
        makes the clip CURRENT, so the live current item at anchor+1 is checked first and a window read at the
        anchor is the fallback. The anchor follows the live current index, so one miss cannot cascade onto
        the next clip of the same turn."""
        ma = None
        qid, idx, why = None, None, None
        cur_idx, cur_is_clip = None, False
        try:
            ma = self._ma_open(ctx)
            s = ma.queue_state(qm["queue_id"])
            if _ma_ok(s):
                q = s.get("result") or {}
                ci = q.get("current_item") or {}
                cur_idx = q.get("current_index")
                cur_is_clip = is_reply_clip_uri((ci.get("media_item") or {}).get("uri") or ci.get("uri") or "")
                if cur_idx == qm["anchor"] + 1 and ci.get("queue_item_id"):
                    qid, idx, why = anchored_clip([ci], cur_idx, qm["anchor"], played_uri)
            if qid is None:
                r = ma.queue_items(qm["queue_id"], offset=qm["anchor"], limit=5)
                items = (r.get("result") or []) if _ma_ok(r) else []
                qid, idx, why = anchored_clip(items, qm["anchor"], qm["anchor"], played_uri)
        except Exception as e:
            qid, idx, why = None, None, "read failed (%r)" % (e,)
        finally:
            self._ma_close(ma)
        if qid is None:
            qm["unidentified"] += 1
            if cur_is_clip and cur_idx is not None:
                qm["anchor"] = cur_idx              # the next clip is inserted after this one
            LOG.warning("SAY req=%s zone=%s clip=%s queue_item UNIDENTIFIED (%s)", rid, zone, clip, why)
            return
        if qid not in qm["clips"]:
            qm["clips"].append(qid)
        qm["anchor"] = idx
        self._queue_publish_clips(zone, my_gen, qm)
        LOG.info("SAY req=%s zone=%s clip=%s queue_item=%s", rid, zone, clip, qid)

    def _queue_confirm(self, ma, queue_id, item, poll_secs):
        """Poll (bounded, design 4.4) until `item` is current. -> (seen, any_read_ok)."""
        if ma is None:
            return False, False
        reads_ok = False
        tries = max(1, int(CONFIRM_BUDGET_S / max(poll_secs, 0.05)))
        for i in range(tries):
            try:
                s = ma.queue_state(queue_id)
                if _ma_ok(s):
                    reads_ok = True
                    cur = ((s.get("result") or {}).get("current_item") or {}).get("queue_item_id")
                    if cur == item:
                        return True, True
            except Exception:
                pass
            if i < tries - 1:
                self._sleeper(poll_secs)
        return False, reads_ok

    def _queue_resume(self, ctx, rid, zone, qm, source_id, call_timeout):
        """Design 4.4 decision table. True when the source is (or may be) playing again."""
        t = qm["target"]
        qid = qm["queue_id"]
        seek = seek_target(t)
        poll_secs = max(int(getattr(ctx.settings, "say_poll_ms", 500)) / 1000.0, 0.05)
        known_clips = list(qm["clips"])              # clips we already knew BEFORE this resume
        qm["resume"] = "attempted"
        called, why, seen, reads_ok = "ok", None, False, False
        ma = None
        try:
            try:
                ma = self._ma_open(ctx)
            except Exception as e:
                called, why = "error", "connect failed (%r)" % (e,)   # never sent: a KNOWN failure
            if ma is not None:
                try:
                    r = ma.play_index(qid, t["item"], seek_position=seek)
                    if not _ma_ok(r):
                        called = "error"
                        why = "ma error %s" % ((r or {}).get("error_code") if isinstance(r, dict) else "no reply")
                except Exception as e:
                    called, why = "raised", "play_index raised (%r)" % (e,)
                seen, reads_ok = self._queue_confirm(ma, qid, t["item"], poll_secs)
        finally:
            self._ma_close(ma)
        if seen:
            outcome = "confirmed"
        elif called == "ok":
            outcome = "unconfirmed"
        elif called == "error" or reads_ok:
            outcome = "fallback_uri"
        else:
            outcome = "unknown"
        qm["resume"] = outcome
        if outcome in ("confirmed", "unconfirmed"):
            qm["seeked"] = seek > 0
            LOG.info("SAY req=%s zone=%s resumed by queue item=%s outcome=%s seek=%s",
                     rid, zone, t["item"], outcome, seek if seek else "skipped")
            self._queue_settle(ctx, rid, zone, qm, seek, poll_secs, known_clips)
            return True
        if outcome == "unknown":
            LOG.error("SAY req=%s zone=%s resume unknown (%s); not replaying", rid, zone, why)
            return False
        LOG.warning("SAY req=%s zone=%s resume by queue failed (%s); URI fallback", rid, zone, why)
        if source_id and not self._is_reply_uri(source_id):
            try:
                self._say_call(ctx, rid, zone, "music_assistant", "play_media",
                               {"entity_id": zone, "media_id": source_id}, timeout=call_timeout)
                return True
            except Exception as e:
                LOG.warning("SAY req=%s zone=%s URI fallback failed (%r); source NOT resumed", rid, zone, e)
        return False

    def _queue_settle(self, ctx, rid, zone, qm, seek, poll_secs, known_clips):
        """Task 3: no-op placeholder with the final signature; Task 4 fills it (design 4.3-7)."""
        return None

    def _queue_finish(self, ctx, rid, zone, qm, my_gen):
        """Design 4.3-8: delete recorded clips that are not current; keep the zone record per outcome."""
        ma = None
        cur = None
        try:
            if qm["clips"]:
                ma = self._ma_open(ctx)
                try:
                    s = ma.queue_state(qm["queue_id"])
                    if _ma_ok(s):
                        cur = ((s.get("result") or {}).get("current_item") or {}).get("queue_item_id")
                except Exception:
                    pass
                for cid in list(qm["clips"]):
                    if cid == cur:
                        LOG.info("SAY req=%s zone=%s clip left as current item %s (no resume)", rid, zone, cid)
                        continue
                    try:
                        r = ma.delete_item(qm["queue_id"], cid)
                        if _ma_ok(r):
                            qm["deleted"] += 1
                            qm["clips"].remove(cid)
                        else:
                            LOG.warning("SAY req=%s zone=%s delete failed for %s (%s)", rid, zone, cid,
                                        r.get("error_code") if isinstance(r, dict) else "no reply")
                    except Exception as e:
                        LOG.warning("SAY req=%s zone=%s delete failed for %s (%r)", rid, zone, cid, e)
        except Exception as e:
            LOG.warning("SAY req=%s zone=%s clip cleanup failed (%r)", rid, zone, e)
        finally:
            self._ma_close(ma)
        with self._lock:
            rec = self._queue_targets.get(zone)
            if rec is not None and rec.get("gen") == my_gen:
                if qm["resume"] == "confirmed" or qm["target"] is None:
                    del self._queue_targets[zone]
                else:
                    # Did not resume, or resume unconfirmed/unknown: a later "resume" continues from here.
                    rec["live"] = False
                    rec["clips"] = list(qm["clips"])
        if qm["target"] is not None and qm["resume"] != "confirmed":
            LOG.info("SAY req=%s zone=%s pending resume recorded (item=%s clips=%s)",
                     rid, zone, qm["target"]["item"], qm["clips"])

    def _queue_superseded_exit(self, ctx, rid, zone, qm, my_gen):
        """Design 4.5: a successor that CAPTURED owns the resume. If none did -- e.g. an announcement claimed
        the generation and aborted before reaching _say -- this turn's record would stay live forever and
        nobody would resume: record any unrecorded clips and turn it into a pending resume."""
        with self._lock:
            rec = self._queue_targets.get(zone)
            mine = rec is not None and rec.get("gen") == my_gen
        if not mine:
            return
        for uri in list(qm["unrecorded"]):
            self._queue_record_clip(ctx, rid, zone, qm, uri, self._clip_id(uri), my_gen)
        with self._lock:
            rec = self._queue_targets.get(zone)
            if rec is not None and rec.get("gen") == my_gen:
                rec["live"] = False
                rec["clips"] = list(qm["clips"])
        LOG.info("SAY req=%s zone=%s superseded with no successor capture; pending resume recorded", rid, zone)
```

3d. `_say` edits:
- Before `try:` (next to `replay_done = [False]`), add: `qm = None` and `queue_done = [False]`.
- First statement inside the `try:` (before `# 3. normalise`):

```python
            # MR-08c: capture the interrupted queue item BEFORE the pause and any enqueue (design 4.3-1).
            qm = self._queue_capture(ctx, rid, zone, my_gen)
```
- In the clip loop, keep the existing `queue_may_be_replaced[0] = True` line, and replace the
  `res = self._play_clip_and_wait(...)` call with:

```python
                res = self._play_clip_and_wait(ctx, rid, zone, one_uri, one_key, one_clip,
                                               opts, superseded,
                                               enqueue=("play" if qm is not None else None))
                if qm is not None:
                    qm["played"].append(one_uri)
                    if superseded():
                        qm["unrecorded"].append(one_uri)   # a successor may own the queue now
                    else:
                        self._queue_record_clip(ctx, rid, zone, qm, one_uri, one_clip, my_gen)
```
- Replace the whole step 9 block (`# 9. replay source ...` through its `except` line) with:

```python
            # 9. put the source back. Queue mode resumes the captured queue item (design 4.3-7);
            #    legacy mode replays the captured source by URI, exactly as before.
            replayed = False
            if qm is not None:
                if was_playing and qm["target"] is not None and not superseded():
                    replayed = self._queue_resume(ctx, rid, zone, qm, source_id, call_timeout)
                self._queue_finish(ctx, rid, zone, qm, my_gen)
                queue_done[0] = True
            elif was_playing and source_id and not superseded():
                try:
                    queue_may_be_replaced[0] = True
                    self._say_call(ctx, rid, zone, "music_assistant", "play_media",
                                   {"entity_id": zone, "media_id": source_id}, timeout=call_timeout)
                    replayed = True
                    replay_done[0] = True       # the finally must not replay a second time
                except Exception as e:
                    LOG.warning("SAY req=%s zone=%s replay failed (%r); source NOT resumed", rid, zone, e)
            resume_mode = ({"confirmed": "queue"}.get(qm["resume"], qm["resume"]) if qm is not None
                           else "legacy")
```
- Final log + return metadata: append `resume=%s` (with `resume_mode`) to the
  `LOG.info("SAY req=%s zone=%s clip=%s reply_started=%s ...` line, and add to the metadata dict:
  `"resume": resume_mode, "seeked": bool(qm and qm["seeked"]), "clips_deleted": (qm["deleted"] if qm else 0),
  "clips_unidentified": (qm["unidentified"] if qm else 0),`
- `finally:` — wrap the two legacy recovery blocks (the `replayed_here = False ... abort-replay` block and the
  un-pause block, which reads `replayed_here`) together in `if qm is None:` (indent one level; content
  byte-identical), and add before `release_reply()`:

```python
            if qm is not None:
                try:
                    if superseded():
                        self._queue_superseded_exit(ctx, rid, zone, qm, my_gen)
                    elif not queue_done[0]:
                        # Died before step 9. Only act on what WE changed (peer review finding 2):
                        #  - a clip may sit in front of the song -> resume the captured item (table 4.4);
                        #  - we only paused -> the queue is exactly as it was: un-pause in place;
                        #  - neither -> the song was never interrupted: do nothing.
                        if was_playing and qm["target"] is not None and qm["resume"] == "none":
                            if queue_may_be_replaced[0]:
                                self._queue_resume(ctx, rid, zone, qm, source_id,
                                                   int(getattr(ctx.settings, "say_call_timeout_ms", 20000)) / 1000.0)
                            elif paused_by_us[0]:
                                self._say_call(ctx, rid, zone, "media_player", "media_play", {"entity_id": zone})
                        self._queue_finish(ctx, rid, zone, qm, my_gen)
                except Exception as e:
                    LOG.error("SAY req=%s zone=%s queue recovery failed (%r)", rid, zone, e)
```

- [ ] **Step 4: Run** — `python -m unittest tests.test_queue_resume tests.test_interaction -v` → all PASS,
  `test_interaction` unmodified.

- [ ] **Step 5: Commit**

```bash
git add docs/homebrain/mass-resolver/interaction.py docs/homebrain/mass-resolver/tests/test_queue_resume.py
git commit -m "feat(resolver): replies keep the queue - enqueue the clip, resume the captured item, delete the clip"
```

---

### Task 4: Failure handling — decision table, late landing, settle check, recovery

**Files:**
- Modify: `docs/homebrain/mass-resolver/interaction.py` (`_queue_settle` body; clip loop try/except; new
  `_queue_after_raised_enqueue`)
- Test: `docs/homebrain/mass-resolver/tests/test_queue_resume.py` (append class)

**Interfaces:**
- Consumes: Task 3 methods. Produces: `_queue_after_raised_enqueue(ctx, rid, zone, qm, one_uri, one_key,
  one_clip, opts, superseded) -> res dict` (same shape as `_play_clip_and_wait`'s).

- [ ] **Step 1: Write the failing tests** — append:

```python
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
```

`test_clip_landing_after_resume_is_caught_by_settle`: the first clip lands normally (c1, recorded); the late one
(c2) is inserted by `play_index` right after `t3`, so the confirm poll never sees `t3` (unconfirmed); settle sees
c2 current, **not** in the clips known before the resume, identifies it at `t3`'s index + 1 (exact match against a
played URL), records it, resumes once more, and `_queue_finish` deletes c1 and c2. In the lag test the current
item stays c1, which *was* known before the resume, so settle does nothing.

`test_exception_before_pause_leaves_the_song_alone`: `_warn_if_double_speak` runs after the capture and before
the pause (`SAY start` step), so neither `paused_by_us` nor `queue_may_be_replaced` is set.

- [ ] **Step 2: Run to verify they fail** — `python -m unittest tests.test_queue_resume.QueueFailureTest -v`
  → the enqueue-raised, not-landed and settle tests FAIL (the exception propagates; one `play_index`). Others may
  pass already from Task 3 — expected; they pin the table.

- [ ] **Step 3: Implement.**

3a. Clip loop in `_say` — replace the Task 3 queue-mode block (`res = self._play_clip_and_wait(... enqueue=...)`
and the `if qm is not None:` record block) with:

```python
                if qm is not None:
                    try:
                        res = self._play_clip_and_wait(ctx, rid, zone, one_uri, one_key, one_clip,
                                                       opts, superseded, enqueue="play")
                    except Exception as e:
                        LOG.warning("SAY req=%s zone=%s clip=%s enqueue raised (%r); checking the queue",
                                    rid, zone, one_clip, e)
                        res = self._queue_after_raised_enqueue(ctx, rid, zone, qm, one_uri, one_key,
                                                               one_clip, opts, superseded)
                    qm["played"].append(one_uri)
                    if superseded():
                        qm["unrecorded"].append(one_uri)
                    else:
                        self._queue_record_clip(ctx, rid, zone, qm, one_uri, one_clip, my_gen)
                else:
                    res = self._play_clip_and_wait(ctx, rid, zone, one_uri, one_key, one_clip,
                                                   opts, superseded)
```

3b. New method:

```python
    def _queue_after_raised_enqueue(self, ctx, rid, zone, qm, one_uri, one_key, one_clip, opts, superseded):
        """Design 4.3-5: an enqueue whose REST call raised may still have landed. If the clip is current, wait
        it out (never cut the answer off); otherwise carry on -- the record step or the settle check finds it.
        gave_up is "unreadable", NOT a denial: the clip may have played, and likely_silent must not claim the
        room heard nothing (the AN-01 honesty rule at the start poll, ~1227)."""
        out = {"started": False, "issued": True, "clip": one_clip, "ended": False, "gave_up": "unreadable"}
        ma = None
        cur = None
        try:
            ma = self._ma_open(ctx)
            s = ma.queue_state(qm["queue_id"])
            if _ma_ok(s):
                cur = (s.get("result") or {}).get("current_item") or {}
        except Exception as e:
            LOG.warning("SAY req=%s zone=%s after raised enqueue: read failed (%r)", rid, zone, e)
        finally:
            self._ma_close(ma)
        if cur and clip_uri_of(cur) == one_uri:
            return self._play_clip_and_wait(ctx, rid, zone, one_uri, one_key, one_clip, opts, superseded,
                                            enqueue="play", issue=False)
        return out
```

3c. `_queue_settle` body (replace the placeholder):

```python
    def _queue_settle(self, ctx, rid, zone, qm, seek, poll_secs, known_clips):
        """Design 4.3-7: one settle re-read after a poll interval. A late-landing enqueue can put a NEW reply
        clip in front of the song; if so, record it (exact + anchored) and resume ONCE more. A clip we already
        knew before the resume just means MA is lagging -- re-resuming would restart the song (peer review
        finding 1)."""
        self._sleeper(poll_secs)
        t = qm["target"]
        ma = None
        try:
            ma = self._ma_open(ctx)
            s = ma.queue_state(qm["queue_id"])
            if not _ma_ok(s):
                return
            q = s.get("result") or {}
            ci = q.get("current_item") or {}
            cid = ci.get("queue_item_id")
            if not ci or cid == t["item"] or cid in known_clips:
                return
            if not is_reply_clip_uri((ci.get("media_item") or {}).get("uri") or ci.get("uri") or ""):
                return
            idx = q.get("current_index")
            if idx is not None and idx >= 1:
                r = ma.queue_items(qm["queue_id"], offset=idx - 1, limit=2)
                items = (r.get("result") or []) if _ma_ok(r) else []
                for played in qm["played"]:
                    got, _, _ = anchored_clip(items, idx - 1, idx - 1, played)
                    if got == cid:
                        if cid not in qm["clips"]:
                            qm["clips"].append(cid)
                        break
            ma.play_index(qm["queue_id"], t["item"], seek_position=seek)
            LOG.warning("SAY req=%s zone=%s settle: new reply clip %s displaced item %s; resumed again",
                        rid, zone, cid, t["item"])
        except Exception as e:
            LOG.warning("SAY req=%s zone=%s settle check failed (%r)", rid, zone, e)
        finally:
            self._ma_close(ma)
```

- [ ] **Step 4: Run** — `python -m unittest tests.test_queue_resume tests.test_interaction -v` → all PASS.

- [ ] **Step 5: Commit**

```bash
git add docs/homebrain/mass-resolver/interaction.py docs/homebrain/mass-resolver/tests/test_queue_resume.py
git commit -m "feat(resolver): queue resume decision table, late-landing clips, settle check, scoped recovery"
```

---

### Task 5: Barge-in inheritance, pending resume, voice "resume"

**Files:**
- Modify: `docs/homebrain/mass-resolver/interaction.py` (`_queue_adopt_target`, `note_playback`, `_resume`,
  new `_resume_from_queue`)
- Test: `docs/homebrain/mass-resolver/tests/test_queue_resume.py` (append class)

**Interfaces:**
- Consumes: `self._queue_targets` records (Task 3). Produces: `_resume_from_queue(ctx, zone, rid) -> CommandResult|None`.

- [ ] **Step 1: Write the failing tests** — append:

```python
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

    def test_pause_two_questions_resume(self):
        q = FakeQueue([track(1), track(2), track(3)], current=1, state="paused", elapsed=47.0)
        ctx = ctx_for(q)
        cap = new_cap()
        say(cap, ctx)
        say(cap, ctx, uri=CLIP2, rid="rid2")
        capability.run(cap, ctx, {"mode": "resume"}, "rid3")
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
```

- [ ] **Step 2: Run to verify they fail** — `python -m unittest tests.test_queue_resume.QueueContinuityTest -v`
  → FAIL (barge-in resumes a clip / two `play_index`; `resume` metadata lacks `queue_pending`; `media_play` on a
  paused clip; no `already_playing`).

- [ ] **Step 3: Implement.**

3a. Replace `_queue_adopt_target` with:

```python
    def _queue_adopt_target(self, qm, rid, zone):
        """Which item this turn resumes (design 4.5-4.6). A record left by a superseded turn (live) or by a
        turn that did not resume (pending) is INHERITED when this turn's current item is one of its clips --
        or, for a live record whose turn recorded none yet, when the current item is a reply clip: that item
        is then recorded as the earlier turn's clip (it sits at that turn's anchor + 1). Capturing a real
        item clears any record."""
        cap = qm["cap"]
        is_clip = is_reply_clip_uri(cap["uri"])
        with self._lock:
            rec = self._queue_targets.get(zone)
            rec = dict(rec, clips=list(rec["clips"])) if rec is not None else None
            if not is_clip:
                self._queue_targets.pop(zone, None)
        if rec is not None and is_clip and rec.get("target") is not None and (
                cap["item"] in rec["clips"] or rec.get("live")):
            if cap["item"] not in rec["clips"]:
                rec["clips"].append(cap["item"])
            qm["target"] = rec["target"]
            qm["clips"] = rec["clips"]
            qm["inherited_from"] = rec.get("rid")
            LOG.info("SAY req=%s zone=%s inherited resume target item=%s from req=%s (clips=%s)",
                     rid, zone, rec["target"]["item"], rec.get("rid"), rec["clips"])
            return
        if is_clip:
            LOG.info("SAY req=%s zone=%s current queue item %s is a reply clip; no resume target",
                     rid, zone, cap["item"])
            return
        qm["target"] = cap
```

3b. `note_playback` — first statement of the method body, before `self.remember_source(zone, uri)`:

```python
        with self._lock:
            self._queue_targets.pop(zone, None)      # MR-08c: new media started; nothing pending to resume
```

3c. New method, and call it first in `_resume`:

```python
    def _resume_from_queue(self, ctx, zone, rid):
        """Design 4.6: continue a pending queue resume, un-pause a paused real item in place, or do nothing
        when a real item is already playing (a legacy replay would replace the queue). None -> the existing
        resume logic runs."""
        if not self._queue_on(ctx):
            return None
        queue_id = ctx.settings.queue_id
        with self._lock:
            rec = self._queue_targets.get(zone)
            rec = dict(rec, clips=list(rec["clips"])) if rec is not None else None
        ma = None
        try:
            ma = self._ma_open(ctx)
            s = ma.queue_state(queue_id)
            if not _ma_ok(s):
                return None
            q = s.get("result") or {}
            ci = q.get("current_item") or {}
            cur_id = ci.get("queue_item_id")
            cur_uri = (ci.get("media_item") or {}).get("uri") or ci.get("uri") or ""
            cur_is_clip = is_reply_clip_uri(cur_uri)
            if (rec is not None and not rec.get("live") and rec.get("target") is not None
                    and cur_id in rec["clips"]):
                t = rec["target"]
                r = ma.play_index(queue_id, t["item"], seek_position=seek_target(t))
                if not _ma_ok(r):
                    LOG.warning("RESUME req=%s zone=%s pending queue resume refused (%s); current logic",
                                rid, zone, r.get("error_code") if isinstance(r, dict) else "no reply")
                    return None
                for cid in rec["clips"]:
                    try:
                        ma.delete_item(queue_id, cid)
                    except Exception as e:
                        LOG.warning("RESUME req=%s zone=%s delete failed for %s (%r)", rid, zone, cid, e)
                LOG.info("RESUME req=%s zone=%s resumed pending queue item %s (clips deleted: %s)",
                         rid, zone, t["item"], rec["clips"])
                self.note_playback(ctx, zone, t.get("uri") or "queue")
                return cr.ok(self.name, rid, "Resuming.", spoken_text=None,
                             metadata={"resumed": True, "uri": t.get("uri"), "how": "queue_pending",
                                       "zone": zone})
            if cur_id and not cur_is_clip and q.get("state") == "playing":
                LOG.info("RESUME req=%s zone=%s already playing queue item %s; nothing to do", rid, zone, cur_id)
                return cr.ok(self.name, rid, "Already playing.", spoken_text=None,
                             metadata={"resumed": False, "uri": cur_uri or None, "how": "already_playing",
                                       "zone": zone})
            if cur_id and not cur_is_clip and q.get("state") == "paused":
                ctx.ha.call_service_rest("media_player", "media_play", {"entity_id": zone})
                self.note_playback(ctx, zone, cur_uri or "unpaused")
                LOG.info("RESUME req=%s zone=%s un-paused the queue in place", rid, zone)
                return cr.ok(self.name, rid, "Resuming.", spoken_text=None,
                             metadata={"resumed": True, "uri": cur_uri or None, "how": "unpause_queue",
                                       "zone": zone})
            return None
        except Exception as e:
            LOG.warning("RESUME req=%s zone=%s queue check failed (%r); current logic", rid, zone, e)
            return None
        finally:
            self._ma_close(ma)
```

In `_resume`, first lines of the body:

```python
        res = self._resume_from_queue(ctx, zone, rid)
        if res is not None:
            return res
```

3d. **The one allowed legacy change:** in `_resume`'s existing logic, the un-pause branch must not un-pause a
spent reply clip (spec §7). Change `if state == "paused":` to `if state == "paused" and not self._is_reply_uri(cid):`.
Run `tests.test_interaction` — if any existing test asserts un-pausing a paused *reply clip*, STOP and report it by
name (it would encode the bug).

- [ ] **Step 4: Run** — `python -m unittest tests.test_queue_resume tests.test_interaction -v` → all PASS.

- [ ] **Step 5: Commit**

```bash
git add docs/homebrain/mass-resolver/interaction.py docs/homebrain/mass-resolver/tests/test_queue_resume.py
git commit -m "feat(resolver): barge-in and pending resume keep the queue; voice resume continues it"
```

---

### Task 6: MR-08e — log the query on a music miss

**Files:**
- Modify: `docs/homebrain/mass-resolver/music.py` (`resolve` return dict; `validate` no-match branch)
- Test: `docs/homebrain/mass-resolver/tests/test_playlist.py` (append class)

- [ ] **Step 1: Write the failing test** — append to `tests/test_playlist.py` (before `if __name__`):

```python
class MissLoggingTest(unittest.TestCase):
    def test_miss_logs_the_query(self):
        ma = FakeMA({"playlist": [curated("my music - costea (local)", "28")]}, {"28": EIGHT})
        with self.assertLogs("resolver", "INFO") as lg:
            r = run(ma, "Costa Rica")
        self.assertFalse(r["ok"])
        self.assertTrue(any("MISS" in m and "'Costa Rica'" in m for m in lg.output))

    def test_hit_logs_no_miss(self):
        ma = FakeMA({"playlist": [curated("my music - costea (local)", "28")]}, {"28": EIGHT})
        with self.assertLogs("resolver", "INFO") as lg:
            run(ma, "my music - costea (local)")
        self.assertFalse(any("MISS" in m for m in lg.output))
```

- [ ] **Step 2: Run to verify they fail** — `python -m unittest tests.test_playlist.MissLoggingTest -v` →
  `test_miss_logs_the_query` FAILS (no `MISS` line).

- [ ] **Step 3: Implement** — in `MusicCapability.resolve`, add `"rid": rid, "media_type": mt,` to the returned
  dict (both names already exist there). In `validate`, first line of the no-match branch (just before
  `q = resolved.get("alias") or resolved.get("query") or "that"`):

```python
        LOG.info("req=%s MISS query=%r media_type=%r alias=%r", resolved.get("rid", ""),
                 resolved.get("query"), resolved.get("media_type") or "", resolved.get("alias"))
```

- [ ] **Step 4: Run** — `python -m unittest tests.test_playlist tests.test_music tests.test_core -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add docs/homebrain/mass-resolver/music.py docs/homebrain/mass-resolver/tests/test_playlist.py
git commit -m "feat(resolver): log the query on a music miss"
```

---

### Task 7: Full suite, Python 3.5 check, mutation check

- [ ] **Step 1: Full suite** — `python -m unittest discover -s tests -t .` → OK (895 + new tests, 2 skipped),
  `test_py35_compat` included; `git diff 035cfc7 -- docs/homebrain/mass-resolver/tests/test_interaction.py`
  must be **empty**.

- [ ] **Step 2: Mutation check** — one at a time: make the change, run the named test, confirm it FAILS, revert
  by editing back (a repo hook blocks `git checkout -- <file>`), confirm `git status --short` is clean.

| # | Mutation (`interaction.py`) | Run | Must fail |
|---|---|---|---|
| 1 | clip loop passes `enqueue=None` in queue mode | `tests.test_queue_resume.QueueModeTest` | `test_multi_item_queue_survives_and_resumes_at_position` |
| 2 | `_queue_resume`: map `unconfirmed` to `fallback_uri` | `…QueueFailureTest` | `test_lag_beyond_budget_is_unconfirmed_and_never_replays_or_restarts` |
| 3 | `anchored_clip`: return the first exact URL match anywhere in the window instead of `anchor+1` | `tests.test_queue_resume.ClipIdentityTest` | `test_identical_leftover_elsewhere_is_ignored` |
| 4 | `_queue_finish`: also delete every reply-clip item in a window read | `…QueueModeTest` | `test_identical_leftover_clip_untouched_and_counted` |
| 5 | `_queue_settle`: `return` immediately | `…QueueFailureTest` | `test_clip_landing_after_resume_is_caught_by_settle` |
| 6 | `_queue_settle`: drop the `cid in known_clips` check | `…QueueFailureTest` | `test_lag_beyond_budget_is_unconfirmed_and_never_replays_or_restarts` |
| 7 | `_queue_adopt_target`: ignore the record (always `qm["target"] = cap` unless a clip) | `…QueueContinuityTest` | `test_barge_in_before_first_turn_recorded_its_clip` |
| 8 | `_resume`: skip `_resume_from_queue` | `…QueueContinuityTest` | `test_pause_question_resume` |
| 9 | `seek_target`: drop the end-margin check | `…SeekTargetTest` | `test_gates` |
| 10 | `parse_queue_capture`: ignore `elapsed_time_last_updated` | `…QueueModeTest` | `test_position_extrapolated_from_last_update` |
| 11 | `finally`: drop the `qm["resume"] == "none"` condition (re-decide after play_index) | `…QueueFailureTest` | `test_exception_after_play_index_is_not_redecided` |
| 12 | `finally`: resume by `play_index` whenever `resume == "none"` (drop the `queue_may_be_replaced` / `paused_by_us` split) | `…QueueFailureTest` | `test_exception_after_pause_before_enqueue_unpauses_in_place` |
| 13 | `finally`: skip `_queue_superseded_exit` | `…QueueContinuityTest` | `test_superseded_without_successor_capture_leaves_a_pending_resume` |
| 14 | `_queue_resume`: treat `raised` + all reads failed as `fallback_uri` | `…QueueFailureTest` | `test_play_index_raised_and_reads_fail_is_unknown_no_replay` |
| 15 | `_queue_adopt_target` / capture: use `self._is_reply_uri` instead of `is_reply_clip_uri` | `…QueueModeTest` | `test_radio_station_added_by_url_is_resumed_not_mistaken_for_a_clip` |
| 16 | `_queue_after_raised_enqueue`: `gave_up="enqueue_raised"` | `…QueueFailureTest` | `test_enqueue_raised_not_landed_is_not_reported_certainly_silent` |
| 17 | `_queue_record_clip`: do not move the anchor on a miss | `…QueueModeTest` | `test_unidentified_clip_does_not_cascade` |

- [ ] **Step 3: Commit** (tests only if any were tightened; otherwise an empty evidence commit):

```bash
git commit --allow-empty -m "test(resolver): MR-08c full suite green; mutation check 17/17 caught"
```

- [ ] **Step 4: Whole-branch review** by the controller (not the implementer).

---

### Task 8: Deploy and docs (operator-gated — stop and ask before Step 1)

Same staged, checksum-verified procedure as MR-08 (see `docs/homebrain/CHANGELOG.md` 2026-09-28 and the MR-08
plan's Task 7), with these specifics:

- **Gate:** claim the §10 row on its own small branch off `origin/main`; PR via the browser URL (`gh` cannot
  create PRs here); wait for the merge.
- **Backup** with sha256 (`.bak/<ts>/SHA256SUMS`, written via `/tmp`), including `tests/`.
- **Read-only probe before staging:** list the radio favourites' queue-item URIs (play nothing — read
  `music/radios/library_items`); if any favourite's URI would match `is_reply_clip_uri`, STOP (finding 8).
- **Stage** in `~/mr08c-staging/mass-resolver` (the directory must be named `mass-resolver`); copy
  `maconn.py interaction.py music.py config.py` and the changed/new tests `tests/test_maconn.py
  tests/test_queue_resume.py tests/test_config.py tests/test_playlist.py`. `test_queue_resume` imports
  `tests.test_interaction`, which the host already carries — verify with `ls` first.
- **Verify** every copy by sha256 (normalise Windows `*name` vs Linux `  name`).
- **Host tests:** every module present in the staged `tests/`, by name, on Python 3.5.2 — any failure STOPs
  before promote.
- **Promote** with a sha256 match; **operator restarts**.
- **Dry-run:** `/command` music dry-run for an unknown query → `MISS` line in the log, `ANNOUNCE via` count
  unchanged.
- **Live, operator present** (design §8): (1) playlist + question → same song near its position, queue = 8,
  no clip, next song follows; (2) radio + question → station back, queue `[station]` — **stop point**: the
  capture log line must name the station item, not "is a reply clip"; (3) pause → resume; (4) pause → question →
  resume. Check each with a read-only queue listing and the log lines of design §6. **Stop and roll back** on any
  failure: restore `.bak/<ts>`, or add `"say_queue_resume": false` to the host `config.json` + restart (kill
  switch).
- **Docs** in the merge PR: CHANGELOG entry, ONBOARDING note, BACKLOG (`MR-08c`, `MR-08e` done; §10 released).
