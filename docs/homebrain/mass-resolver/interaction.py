#!/usr/bin/env python3
# AU-02/AU-03: interaction duck/restore for a media zone. Silent. Python 3.5 safe.
import hashlib, logging, re, time, threading
from urllib.parse import urlparse, urlunparse
import capability
import command_result as cr

LOG = logging.getLogger("resolver")
_MODES = ("duck", "restore", "say", "say_text", "resume", "pause", "volume_up", "volume_down",
          "set_volume", "announce")

# Consecutive unreadable zone states before a finish poll stops guessing (F1, 2026-09-27).
UNREADABLE_LIMIT = 3

# Timeout for an HA call made while `_lock` is HELD. Short on purpose: that lock also gates
# _claim_gen, interaction_in_flight (called on every dispatch result) and the volume-recovery
# timer, so a hung HA here stalls far more than the caller. This bounds the hold; it does not
# narrow the critical section, which is a real check-then-act and a larger change.
LOCK_HELD_CALL_TIMEOUT = 5.0

# --- MR-08c queue mode (design docs/homebrain/2026-09-28-mr-08c-queue-resume-design.md) -------------------
_CLIP_WRAPPERS = ("builtin://radio/", "builtin://track/")   # MA's two measured wrappings of a played URL
CONFIRM_BUDGET_S = 4.0         # how long to poll for play_index to show (MA updates queue state async)
SEEK_MIN_S = 2.0               # below this, resume from the start
SEEK_END_MARGIN_S = 5.0        # seeking this close to the end would skip the song
MAX_EXTRAPOLATE_S = 60.0       # elapsed_time_last_updated is MA's clock, `now` is ours: bound the delta
# Amendment A1 (design 4.8)
CLEANUP_READ_CAP = 500         # a cleanup read covers the WHOLE queue; larger than this -> nothing is deleted
RETRY_OFFSETS_S = (1.0, 2.0)   # A1.4-4: delete retries this long after play_index
PERMISSION_WINDOW_EXTRA = 5    # A2.1: the permission read's item window = recorded clips + this, from T's index
REPAUSE_WATCH_S = 3.0          # A2.2: how long a paused-at-start turn watches for MA restarting T by itself
OTHER_ITEM_EPSILON_S = 1e-6    # accumulated float poll sleeps must not miss the threshold by a rounding error


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
            "extrapolated": extrapolated,
            "buffer": q.get("index_in_buffer"), "items": q.get("items")}, None


def capture_anchor(cap):
    """Design 4.8 A3.1: where the first reply clip lands. MA's enqueue=play inserts after the BUFFERED item, not
    after the current one (live check 4: a pending clip buffered at 1 pushed the next clip to 2), so the anchor
    is index_in_buffer when it is an integer consistent with the capture (current_index <= it < items), else
    current_index as before. Identity stays exact (URL, or TTS name) at anchor + 1, so a wrong anchor can leave
    a clip unidentified and can never record a non-reply item; the only possible mis-record is a leftover reply
    clip with the same cached TTS URL sitting at anchor + 1. -> (anchor, "buffer" | "current")."""
    cur = cap.get("index") if _is_int(cap.get("index")) else 0
    ib, total = cap.get("buffer"), cap.get("items")
    if _is_int(ib) and _is_int(total) and cur <= ib < total:
        return ib, "buffer"
    return cur, "current"


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


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def buffer_problem(state_result):
    """Why a player_queues/get result's `index_in_buffer` cannot be relied on (design 4.8 A1.2), or None when it
    is an integer consistent with the snapshot: 0 <= index_in_buffer < items, and >= current_index when known."""
    q = state_result or {}
    ib = q.get("index_in_buffer")
    if ib is None:
        return "index_in_buffer missing"
    if not _is_int(ib):
        return "index_in_buffer not an integer (%r)" % (ib,)
    total = q.get("items")
    if not _is_int(total):
        return "queue item count unknown"
    if ib < 0 or ib >= total:
        return "index_in_buffer %d outside the queue (items=%d)" % (ib, total)
    cur = q.get("current_index")
    if _is_int(cur) and ib < cur:
        return "index_in_buffer %d below current_index %d" % (ib, cur)
    return None


def delete_permission(state_result, index_of, qiid):
    """Design 4.8 A1.2: may reply clip `qiid` be deleted, judged from ONE read? MA 2.9 silently ignores a delete
    of the current item or of anything at or below index_in_buffer (spike 4, 3.3-4/5), so a delete is permitted
    only when the clip is in the snapshot, is not current, and lies AFTER a trustworthy buffer index. Fail
    closed: anything missing or inconsistent -> not permitted. `index_of` maps queue_item_id -> absolute index
    in the same snapshot. -> (permitted, reason)."""
    why = buffer_problem(state_result)
    if why is not None:
        return False, why
    q = state_result
    ib = q["index_in_buffer"]
    if qiid not in index_of:
        return False, "not in the queue"
    idx = index_of[qiid]
    cur = q.get("current_index")
    if qiid == (q.get("current_item") or {}).get("queue_item_id") or (_is_int(cur) and idx == cur):
        return False, "current item (still current)"
    if idx <= ib:
        return False, "index %d within the buffer (index_in_buffer=%d)" % (idx, ib)
    return True, "index %d after the buffer (index_in_buffer=%d)" % (idx, ib)


class InteractionCapability(capability.Capability):
    name = "interaction"

    def __init__(self, timer_factory=None, clock=None, sleeper=None):
        self._timer_factory = timer_factory or threading.Timer
        self._clock = clock or time.time
        self._sleeper = sleeper or time.sleep
        self._snaps = {}                             # zone -> {"volume": baseline, "target": last-written, "ts": float, "timer": obj|None}
        self._lock = threading.Lock()                # guards _snaps check-then-act (HTTP threads + timer thread)
        self._mic_lock = threading.Lock()            # serialises the microphone HANDOVER: claim's
                                                     #   mute+publish against release's
                                                     #   validate+unmute. _lock protected the dict
                                                     #   entry but not the WRITE, so an older turn
                                                     #   could unmute a microphone a newer
                                                     #   announcement had just muted -- broadcasting
                                                     #   through a live satellite mic, the one
                                                     #   failure requirement 7 exists to prevent.
                                                     #   LOCK ORDER: _mic_lock BEFORE _lock, never
                                                     #   the reverse. Nothing holds _lock across a
                                                     #   _mic_* call, which is what makes that safe.
        self._say_gen = {}                            # zone -> generation counter (barge-in supersede), guarded by _lock
        self._turns = {}                              # zone -> {"ts": float, "playback": uri|None,
                                                      #          "stopped": bool}
                                                      #   ts of the last duck REQUEST. A duck request is
                                                      #   the satellite announcing a turn, whether or not there
                                                      #   was anything to attenuate -- so this marks "a turn is
                                                      #   live" even when the zone was idle. Guarded by _lock.
        self._last_source = {}                        # zone -> last REAL (non-reply) media uri played there,
                                                      #   so "resume" can restart it: media_play cannot resume
                                                      #   a radio stream whose queue was cleared, and would
                                                      #   otherwise replay a spent reply clip.
        self._replies = {}                            # zone -> {"gen": int, "baseline": float|None} while a reply
                                                      #   turn is in flight; _say owns the zone's volume for its
                                                      #   lifetime (S1b-2 decision (b)). Guarded by _lock.
        self._queue_targets = {}                      # MR-08c: zone -> {"gen", "rid", "target", "clips",
                                                      #   "live"}. The interrupted item and the reply clips a
                                                      #   turn put in the queue: a superseding turn or a later
                                                      #   "resume" continues from it (design 4.5-4.6).
                                                      #   Guarded by _lock.
        self._vol_recovery = {}                       # zone -> {"gen", "baseline", "target",
                                                      #          "rid", "ts", "timer"}
                                                      #   design 9.7: an UNDUCKED turn has no duck
                                                      #   snapshot, so _arm_timer never ran and
                                                      #   max_duck_timeout is not its net. Written
                                                      #   only by _say. Guarded by _lock.
        self._mic = {}                                # zone -> {"gen", "prev", "confirmed",
                                                      #          "rid", "ts", "timer"}
                                                      #   WRITTEN ONLY BY THE ANNOUNCEMENT PATH.
                                                      #   Nothing else in this class touches it --
                                                      #   that invariant is why a NON-announcement
                                                      #   supersession unmutes immediately instead
                                                      #   of stranding the mute, since such a turn
                                                      #   bumps _say_gen but leaves the lease ours
                                                      #   (design 9.1/9.4/9.6). Guarded by _lock.

    def resolve(self, ctx, params):
        mode = (params.get("mode") or "").strip().lower()
        zone = params.get("zone") or getattr(ctx.settings, "ceiling_entity", "")
        uri = params.get("uri") or params.get("media_content_id") or ""
        return {"mode": mode, "zone": zone, "uri": uri,
                "text": (params.get("text") or "").strip(),
                "step": params.get("step"), "volume": params.get("volume"),
                # AN-01 design 6.4: an ordered clip sequence for one reply-owned turn. All optional
                # -- absent, _say behaves exactly as it did with a single `uri`. `.get` rather than
                # `or` for volume_override, because 0.0 is a legitimate override.
                "uris": params.get("uris"), "match_keys": params.get("match_keys"),
                "finish_timeouts": params.get("finish_timeouts"),
                "volume_override": params.get("volume_override"),
                "deadline_from_now": params.get("deadline_from_now"),
                # A generation claimed by the caller BEFORE the slow work (design 9.2). `.get`, so
                # an absent key stays None and _say claims its own exactly as it always has.
                "gen": params.get("gen")}

    def validate(self, ctx, resolved):
        if resolved["mode"] not in _MODES:
            return {"code": "invalid_input", "reason": "bad mode",
                    "chat_text": "Unknown interaction mode."}
        if not resolved["zone"]:
            return {"code": "invalid_input", "reason": "no zone", "chat_text": "No zone."}
        if resolved["mode"] == "say" and not resolved.get("uri"):
            return {"code": "invalid_input", "reason": "no uri", "chat_text": "No reply audio."}
        if resolved["mode"] == "say_text" and not resolved.get("text"):
            return {"code": "invalid_input", "reason": "no text", "chat_text": "Nothing to say."}
        if resolved["mode"] == "announce" and not resolved.get("text"):
            # resolve() has already stripped, so a whitespace-only message lands here and is
            # refused before any HA call -- AN-01 design 7 step B.
            return {"code": "invalid_input", "reason": "no text",
                    "chat_text": "Nothing to announce."}
        return None

    def _render_announcement_text(self, ctx, text):
        """AN-01 design 6.3: build the text the announcement clip will speak.

        Returns (rendered, err, prefix_dropped):
          * rendered -- the bounded "prefix message", or None when err is set.
          * err      -- a validate()-shaped dict, or None.
          * prefix_dropped -- True when a misconfigured prefix was discarded. The caller logs it
            alongside the request id; it is deliberately NOT an error (see below).

        Two rules this encodes, both deliberate:

        1. The bound is on the RENDERED text, prefix included. The prefix is configurable and is
           synthesised into the same clip, so bounding only the message would let config.json
           inflate the real clip length past what design 6.5's timing model assumes.

        2. Over-length is REJECTED, never truncated. A household announcement clipped at a word
           boundary can read as fluent and mean the opposite -- "do not let the dog out the back
           gate" becomes "do not let the dog out" -- and nobody in the room can tell it was cut.
           Refusing audibly is recoverable; a silently inverted instruction is not.
        """
        msg = (text or "").strip()
        if not msg:
            return None, {"code": "invalid_input", "reason": "no text",
                          "chat_text": "Nothing to announce."}, False

        prefix = (getattr(ctx.settings, "announce_prefix", "") or "").strip()
        max_prefix = int(getattr(ctx.settings, "announce_max_prefix_chars", 40))
        dropped = False
        if prefix and len(prefix) > max_prefix:
            # A mistyped prefix in config.json must not disable every announcement in the house,
            # so the prefix is dropped and the message still goes out. It also must not eat the
            # message's budget on its way out -- hence the drop happens before the limit maths.
            LOG.error("ANNOUNCE prefix is %d chars, over the %d limit -- dropping the prefix",
                      len(prefix), max_prefix)
            prefix = ""
            dropped = True

        max_chars = int(getattr(ctx.settings, "announce_max_chars", 300))
        limit = max_chars - (len(prefix) + 1 if prefix else 0)
        if len(msg) > limit:
            # The EFFECTIVE limit is quoted, not the configured one: with a prefix set they differ,
            # and a caller told "300" while the real ceiling is 289 cannot fix their message.
            return None, {"code": "invalid_input", "reason": "text too long",
                          "chat_text": ("That announcement is too long - keep it to %d "
                                        "characters or fewer." % limit)}, dropped

        return (prefix + " " + msg if prefix else msg), None, dropped

    def execute(self, ctx, resolved, rid):
        if resolved["mode"] == "duck":
            return self._duck(ctx, resolved["zone"], rid)
        if resolved["mode"] == "say":
            return self._say(ctx, resolved, rid)
        if resolved["mode"] == "say_text":
            return self._say_text(ctx, resolved, rid)
        if resolved["mode"] == "announce":
            return self._announce(ctx, resolved, rid)
        if resolved["mode"] == "resume":
            return self._resume(ctx, resolved["zone"], rid)
        if resolved["mode"] == "pause":
            return self._pause(ctx, resolved["zone"], rid)
        if resolved["mode"] in ("volume_up", "volume_down", "set_volume"):
            return self._volume(ctx, resolved, rid)
        return self._restore(ctx, resolved["zone"], rid)

    def _duck(self, ctx, zone, rid):
        floor = int(getattr(ctx.settings, "interaction_floor", 15)) / 100.0
        with self._lock:                                               # read + write stay under _lock together
                                                                        # (intentional: serializes HTTP threads
                                                                        # against the timer thread)
            # A turn is live from here (see _turns). Log the first duck of a turn: a no-op duck used
            # to log nothing at all, so a turn over an idle zone was invisible and the operator's
            # wake could not be located in the log.
            window = int(getattr(ctx.settings, "interaction_turn_window_ms", 30000)) / 1000.0
            prev_turn = self._turns.get(zone)
            if prev_turn is None or (self._clock() - prev_turn.get("ts", 0)) > window:
                LOG.info("TURN start req=%s zone=%s (duck requested)", rid, zone)
                self._turns[zone] = {"ts": self._clock(), "playback": None}   # fresh turn
            else:
                prev_turn["ts"] = self._clock()                               # same turn, keep playback
            if self._reply_active(ctx, zone) is not None:
                # Decision (a)+(b): during a reply turn the clip has REPLACED the music, so there is
                # nothing left to duck under, and _say owns this zone's volume. Ducking here would
                # only quiet the reply itself, and the snapshot it left behind would be torn down by
                # _say's restore -- stranding the zone with neither baseline nor dead-man.
                LOG.info("DUCK req=%s zone=%s skipped: reply active (say owns volume)", rid, zone)
                return cr.ok(self.name, rid, "Reply in progress.", spoken_text=None,
                             metadata={"ducked": False, "reason": "reply_active", "zone": zone})
            # Decision (e), duck half. If this turn already STARTED playback, the reply this duck is
            # making room for will be skipped by _say for that exact reason -- so the duck attenuates
            # the station the same turn just started, and nothing un-ducks it until the restore lands
            # seconds later. Live evidence 2026-09-06: "play russian songs" started library://radio/17
            # at 10:37:32.3, was ducked to 0.15 at 10:37:33.6, and only came back at 10:37:38.6 --
            # heard as the station starting, stopping, then starting again.
            # NOTE: read _turns directly; _lock is already held here and is not reentrant.
            if bool(getattr(ctx.settings, "duck_skip_on_fresh_playback", True)):
                started = (self._turns.get(zone) or {}).get("playback")
                if started:
                    LOG.info("DUCK req=%s zone=%s skipped: this turn started %s (the reply is skipped "
                             "too, so there is nothing to duck under)", rid, zone, started)
                    return cr.ok(self.name, rid, "Nothing to duck.", spoken_text=None,
                                 metadata={"ducked": False, "reason": "fresh_playback", "zone": zone})
            state = ctx.ha.get_entity_state(zone, timeout=LOCK_HELD_CALL_TIMEOUT) or {}
            player_state = state.get("state")
            vol = (state.get("attributes") or {}).get("volume_level")
            if player_state != "playing" and getattr(ctx.settings, "interaction_ignore_when_idle", True):
                LOG.info("DUCK req=%s zone=%s no-op (not_playing)", rid, zone)
                return cr.ok(self.name, rid, "Nothing to duck.", spoken_text=None,
                             metadata={"ducked": False, "reason": "not_playing", "zone": zone})
            if vol is None:
                LOG.info("DUCK req=%s zone=%s no-op (no_volume)", rid, zone)
                return cr.ok(self.name, rid, "Nothing to duck.", spoken_text=None,
                             metadata={"ducked": False, "reason": "no_volume", "zone": zone})
            target = min(vol, floor)                                   # never raise volume
            if zone not in self._snaps:                                # first duck: capture baseline
                # Reachable mid-reply only if a reply marker went stale above (crashed/hung _say).
                # `vol` is then _say's reply volume, not a user level -- snapshotting it is the
                # ratchet -- so prefer the orphaned marker's baseline.
                baseline = self._reply_baseline(zone, vol)
                self._snaps[zone] = {"volume": baseline, "target": target,
                                     "ts": self._clock(), "timer": None}
            else:                                                      # coalesce: keep baseline, track last-written target
                self._snaps[zone]["target"] = target
            self._arm_timer(ctx, zone)                                 # snapshot + timer BEFORE the write, so a
            ctx.ha.call_service_rest("media_player", "volume_set",     #   lost-ack write is reconciled by the dead-man
                                     {"entity_id": zone, "volume_level": target},
                                     timeout=LOCK_HELD_CALL_TIMEOUT)
            LOG.info("DUCK req=%s zone=%s %s -> %s", rid, zone, vol, target)
            return cr.ok(self.name, rid, "Ducked.", spoken_text=None,
                         metadata={"ducked": True, "from": vol, "to": target, "zone": zone})

    def _arm_timer(self, ctx, zone):
        snap = self._snaps.get(zone)
        if snap is None:
            return
        self._cancel_timer(snap)
        secs = int(getattr(ctx.settings, "max_duck_timeout", 120000)) / 1000.0
        t = self._timer_factory(secs, self._auto_restore, [ctx, zone])
        snap["timer"] = t
        t.start()

    def _cancel_timer(self, snap):
        t = snap.get("timer")
        if t is not None:
            try:
                t.cancel()
            except Exception:
                pass

    def _auto_restore(self, ctx, zone):
        LOG.warning("DUCK dead-man timeout: auto-restoring zone=%s", zone)
        try:
            self._restore(ctx, zone, "deadman")
        except Exception as e:
            LOG.error("auto-restore failed zone=%s: %r; re-arming", zone, e)
            try:
                with self._lock:                       # KEEP: F3 guarded re-arm
                    if zone in self._snaps:
                        self._arm_timer(ctx, zone)
            except Exception as e2:
                LOG.error("auto-restore re-arm failed zone=%s: %r", zone, e2)

    def _reply_active(self, ctx, zone):
        # The reply marker that owns this zone's volume, or None. Caller holds _lock.
        # Two deliberate escapes from ownership:
        #  * say_owns_restore=False turns decision (b) off wholesale -- duck/restore then behave
        #    exactly as they did before Slice 4, so the flag stays a real rollback lever.
        #  * a marker older than the whole say budget is treated as orphaned (crashed/hung _say).
        #    Without this, one stuck reply would deafen duck AND restore for this zone forever --
        #    and since a deferred restore re-arms the dead-man, even the backstop could never fire.
        if not bool(getattr(ctx.settings, "say_owns_restore", True)):
            return None
        reply = self._replies.get(zone)
        if reply is None:
            return None
        # The marker's legitimate lifetime is step 2 -> finally: the pause and volume writes,
        # every play_media at its call timeout, all the poll budgets, the restore write and the
        # replay. A turn that knows its own span publishes it; older callers keep today's formula.
        #
        # Without this, a two-clip announcement outlives the legacy threshold and declares its OWN
        # marker orphaned, so duck and restore reclaim the zone while it is still speaking.
        #
        # `is None`, not truthiness: say and say_text publish the key as None rather than omitting
        # it, and a published 0.0 is an answer rather than an absence.
        budget = reply.get("marker_budget_s")
        if budget is None:
            budget = (int(getattr(ctx.settings, "say_start_timeout_ms", 5000)) +
                      int(getattr(ctx.settings, "say_reply_timeout_ms", 30000))) / 1000.0
        ts = reply.get("ts")
        if ts is not None and (self._clock() - ts) > (budget + 60.0):
            LOG.warning("reply marker zone=%s from req=%s is stale (%ds); reclaiming the zone",
                        zone, reply.get("rid"), int(self._clock() - ts))
            return None
        return reply

    def interaction_in_flight(self, ctx, zone):
        """Is a satellite turn live on this zone? Read by core.dispatch to hold back the resolver's
        own tts.speak: during a satellite turn the assistant pipeline speaks the reply itself, and
        announcing here too puts TWO voices on the zone for one utterance (the operator hears the
        answer twice, the clips overlap, and they fight over the player).

        True while a reply clip is in flight, while a duck snapshot is held, or within
        interaction_turn_window_ms of the last duck request (covers wake -> reply-URI, including the
        case where the zone was idle so nothing was ducked)."""
        window = int(getattr(ctx.settings, "interaction_turn_window_ms", 30000)) / 1000.0
        with self._lock:
            if zone in self._replies or zone in self._snaps:
                return True
            turn = self._turns.get(zone)
            return turn is not None and (self._clock() - turn.get("ts", 0)) <= window

    def _is_reply_uri(self, uri):
        """True for an EPHEMERAL clip -- something that must never be remembered or replayed as a
        durable source.

        Three forms, each measured rather than assumed:

          * Piper renders served from HA's tts_proxy, which MA wraps as "builtin://radio/<url>".
          * The announcement chime, which MA wraps as "builtin://track/<url>" -- MA wraps by MEDIA
            TYPE, and nothing in this file anticipated `track` before AN-1. Narrowed to
            "/media/local/" so a real library track stays resumable.
          * Anything still carrying a signature. That is the unwrapped shape resolve_media_source
            returns and _say hands to play_media, so it is what a capture read can see before MA has
            wrapped it -- and a signature expires, so replaying such a URL later fails silently.

        Left unguarded, `resume` would replay a spent chime instead of the operator's music, by a
        URL whose signature has expired: a silent failure two layers from its symptom. Same class of
        defect as the 2026-09-05 stop/replay bug in CHANGELOG.md, where a reply clip was resurrected
        as though it were music.
        """
        u = (uri or "").lower()
        return ("tts_proxy" in u
                or u.startswith("builtin://radio/http")
                or (u.startswith("builtin://track/") and "/media/local/" in u)
                or "authsig=" in u)

    def remember_source(self, zone, uri):
        """Record the last REAL media played on this zone, for `resume`. Ignores reply clips."""
        if not uri or self._is_reply_uri(uri):
            return
        with self._lock:
            self._last_source[zone] = uri

    def _num(self, value, default):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _volume(self, ctx, resolved, rid):
        """Volume commands must move the BASELINE while a turn is ducked.

        The ceiling volume scripts wrote the player directly, which during a turn meant a relative
        step computed from the DUCK FLOOR (0.15 + 0.10 = 0.25 instead of 0.34 + 0.10) -- and the next
        re-duck pulled it straight back down, so "volume up" ended up LOWER than where it started.
        While ducked we therefore retarget the snapshot the turn will restore to and leave the floor
        alone; the change lands audibly when the turn ends. Unducked, we write the player as before.
        """
        zone = resolved["zone"]
        mode = resolved["mode"]
        step = self._num(resolved.get("step"), 10.0) / 100.0
        with self._lock:
            snap = self._snaps.get(zone)
            ducked = snap is not None and snap.get("volume") is not None
            base = snap["volume"] if ducked else None
        if not ducked:
            try:
                attrs = (ctx.ha.get_entity_state(zone) or {}).get("attributes") or {}
                base = attrs.get("volume_level")
            except Exception as e:
                LOG.warning("VOLUME req=%s zone=%s read failed (%r)", rid, zone, e)
                base = None
        if mode == "set_volume":
            pct = self._num(resolved.get("volume"), None)
            if pct is None:
                return cr.ok(self.name, rid, "No volume given.", spoken_text=None,
                             metadata={"changed": False, "reason": "no_volume", "zone": zone})
            new = pct / 100.0
        else:
            if base is None:
                return cr.ok(self.name, rid, "I could not read the current volume.", spoken_text=None,
                             metadata={"changed": False, "reason": "no_current", "zone": zone})
            new = base + (step if mode == "volume_up" else -step)
        # Round: 0.44 - 0.10 lands on 0.33999999999999997, which is what then gets written to HA and
        # printed in the log. Harmless arithmetically, but the value is user-visible.
        new = round(max(0.0, min(1.0, new)), 3)
        if ducked:
            with self._lock:
                snap = self._snaps.get(zone)
                if snap is not None:
                    snap["volume"] = new
            LOG.info("VOLUME req=%s zone=%s %s: baseline %s -> %s (ducked; applies when the turn ends)",
                     rid, zone, mode, base, new)
            return cr.ok(self.name, rid, "Volume set.", spoken_text=None,
                         metadata={"changed": True, "to": new, "applied": "baseline", "zone": zone})
        ctx.ha.call_service_rest("media_player", "volume_set",
                                 {"entity_id": zone, "volume_level": new})
        LOG.info("VOLUME req=%s zone=%s %s: -> %s (live)", rid, zone, mode, new)
        return cr.ok(self.name, rid, "Volume set.", spoken_text=None,
                     metadata={"changed": True, "to": new, "applied": "live", "zone": zone})

    def _resume_from_queue(self, ctx, zone, rid):
        """Design 4.6 as amended by 4.8 A1.6: continue a pending queue resume, un-pause a paused real item in
        place, or do nothing when a real item is already playing (a legacy replay would replace the queue).
        None -> the existing resume logic runs.

        A pending record whose clips are still in the queue resumes with play_index(T, seek) and deletes the
        clips right after it (A1.4 steps 2-5) -- also when the current item is T itself, paused (A1.5 re-paused
        a station MA restarted): un-pausing in place would leave the clips inside MA's buffer, where a delete is
        a silent no-op, so they would play after T."""
        if not self._queue_on(ctx, zone):
            return None
        queue_id = ctx.settings.queue_id
        with self._lock:
            rec = self._queue_targets.get(zone)
            rec = dict(rec, clips=list(rec["clips"])) if rec is not None else None
        ma = None
        try:
            ma = self._ma_open(ctx)
            pending = rec is not None and not rec.get("live") and rec.get("target") is not None
            snap = self._queue_permission_read(ma, queue_id, len(rec["clips"]) if pending else 0,
                                               rec["target"] if pending else None)
            if snap is None:
                return None
            q = snap["q"]
            ci = q.get("current_item") or {}
            cur_id = ci.get("queue_item_id")
            cur_uri = (ci.get("media_item") or {}).get("uri") or ci.get("uri") or ""
            cur_is_clip = is_reply_clip_uri(cur_uri)
            present = []
            if (rec is not None and not rec.get("live") and rec.get("target") is not None
                    and (cur_id in rec["clips"]
                         or (cur_id == rec["target"]["item"] and q.get("state") != "playing"))):
                # Sitting on one of our clips, or on T itself not playing. T already playing (re-seeking would
                # jump it back) and a newer item (A1.5: never jump away from it) keep the logic below.
                present = [c for c in rec["clips"] if c in snap["index_of"] or c == cur_id]
            if present:
                t = rec["target"]
                self._log_cleanup_read("RESUME", rid, zone, "pending resume", snap, rec["clips"])
                if cur_id == t["item"]:
                    # A2.3: T is current -- the user may have played and re-paused it since the record was
                    # made, so seek from THIS read, never from the stored position.
                    live, _ = parse_queue_capture({"result": q}, self._clock())
                    if live is not None:
                        t = dict(t, pos=live["pos"])
                r = ma.play_index(queue_id, t["item"], seek_position=seek_target(t))
                t0 = self._clock()
                if r is None:
                    # Not a refusal: the command was sent and may have landed. Falling back to the
                    # legacy replay would replace the queue under a resume that may be playing.
                    LOG.warning("RESUME req=%s zone=%s pending queue resume got no reply; checking the queue",
                                rid, zone)
                elif not _ma_ok(r):
                    LOG.warning("RESUME req=%s zone=%s pending queue resume refused (%s); current logic",
                                rid, zone, r.get("error_code") if isinstance(r, dict) else "bad reply")
                    return None

                def superseded():
                    # A reply turn that captured since has replaced this record: its cleanup owns the clips.
                    with self._lock:
                        now = self._queue_targets.get(zone)
                        return now is None or now.get("gen") != rec.get("gen")

                kept = list(rec["clips"])
                deleted = 0
                # A1.4-3: delete immediately -- MA honours it only while the clip lies after the buffer that
                # play_index just reset to T. Presence decides, so a lagging play_index cannot make a no-op
                # delete of a still-current clip count as done.
                n, snap = self._queue_cleanup(ma, "RESUME", rid, zone, queue_id, kept, "after play_index",
                                              target=t, stop=superseded)
                deleted += n
                poll_secs = max(int(getattr(ctx.settings, "say_poll_ms", 500)) / 1000.0, 0.05)
                seen, _ = self._queue_confirm(ma, queue_id, t["item"], poll_secs)
                if kept and not superseded():
                    deleted += self._queue_jump_tail(ma, "RESUME", rid, zone, queue_id, t, kept, t0, snap,
                                                     superseded)
                if not kept:
                    LOG.info("RESUME req=%s zone=%s resumed pending queue item %s (clips deleted: %d, confirmed=%s)",
                             rid, zone, t["item"], deleted, seen)
                    self.note_playback(ctx, zone, t.get("uri") or "queue")
                else:
                    with self._lock:
                        cur_rec = self._queue_targets.get(zone)
                        if cur_rec is not None and cur_rec.get("gen") == rec.get("gen"):
                            cur_rec["clips"] = kept
                    LOG.info("RESUME req=%s zone=%s resume pending: clips kept %s (confirmed=%s)", rid, zone,
                             kept, seen)
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

    def _resume(self, ctx, zone, rid):
        res = self._resume_from_queue(ctx, zone, rid)
        if res is not None:
            return res
        with self._lock:
            uri = self._last_source.get(zone)
        if uri:
            ctx.ha.call_service_rest("music_assistant", "play_media",
                                     {"entity_id": zone, "media_id": uri},
                                     timeout=int(getattr(ctx.settings, "say_call_timeout_ms", 20000)) / 1000.0)
            self.note_playback(ctx, zone, uri)     # this turn started media: do not let the reply
                                                   #   clip replace what we just resumed
            LOG.info("RESUME req=%s zone=%s replaying %s", rid, zone, self._redact_uri(uri))
            return cr.ok(self.name, rid, "Resuming.", spoken_text=None,
                         metadata={"resumed": True, "uri": uri, "how": "replay", "zone": zone})
        # Nothing remembered (e.g. the resolver restarted). Do NOT blind-call media_play: on an idle
        # player HA answers HTTP 500 and the whole turn dies with a bare OSError. Inspect first.
        try:
            st = ctx.ha.get_entity_state(zone) or {}
        except Exception as e:
            LOG.warning("RESUME req=%s zone=%s read failed (%r)", rid, zone, e)
            st = {}
        state = st.get("state")
        cid = ((st.get("attributes") or {}).get("media_content_id")) or ""
        if state == "paused" and not self._is_reply_uri(cid):
            ctx.ha.call_service_rest("media_player", "media_play", {"entity_id": zone})
            self.note_playback(ctx, zone, cid or "unpaused")
            LOG.info("RESUME req=%s zone=%s un-paused", rid, zone)
            return cr.ok(self.name, rid, "Resuming.", spoken_text=None,
                         metadata={"resumed": True, "uri": None, "how": "unpause", "zone": zone})
        if cid and not self._is_reply_uri(cid):
            ctx.ha.call_service_rest("music_assistant", "play_media",
                                     {"entity_id": zone, "media_id": cid},
                                     timeout=int(getattr(ctx.settings, "say_call_timeout_ms", 20000)) / 1000.0)
            self.note_playback(ctx, zone, cid)
            LOG.info("RESUME req=%s zone=%s replaying the loaded source %s",
                     rid, zone, self._redact_uri(cid))
            return cr.ok(self.name, rid, "Resuming.", spoken_text=None,
                         metadata={"resumed": True, "uri": cid, "how": "loaded", "zone": zone})
        LOG.info("RESUME req=%s zone=%s nothing to resume (state=%s had_reply_clip=%s)",
                 rid, zone, state, bool(cid))
        return cr.ok(self.name, rid, "There is nothing to resume.", spoken_text=None,
                     metadata={"resumed": False, "reason": "nothing_to_resume", "zone": zone})

    def _pause(self, ctx, zone, rid):
        """Pause this zone and mark the turn, so the spoken confirmation cannot undo the pause.

        A pause issued straight from HA (`media_player.media_pause` in the voice automation) is
        invisible to the reply route: `_say` captures the zone's state milliseconds later, before HA
        has propagated `paused`, so it sees "playing" and replays the source at step 9 -- restarting
        the very stream this command stopped, while the user hears "Stopped." That race is not
        winnable on timing, so the turn records the intent instead and `_say` trusts the turn over
        its own capture. Mirror of note_playback for the opposite direction."""
        try:
            st = ctx.ha.get_entity_state(zone) or {}
        except Exception as e:
            LOG.warning("PAUSE req=%s zone=%s read failed (%r)", rid, zone, e)
            st = {}
        cid = ((st.get("attributes") or {}).get("media_content_id")) or ""
        self.remember_source(zone, cid)         # keep `resume` able to bring this station back
        self.note_stopped(zone)                 # BEFORE the call: the reply must never race the mark
        ctx.ha.call_service_rest("media_player", "media_pause", {"entity_id": zone})
        LOG.info("PAUSE req=%s zone=%s was=%s source=%s",
                 rid, zone, st.get("state"), self._redact_uri(cid) or None)
        return cr.ok(self.name, rid, "Paused.", spoken_text=None,
                     metadata={"paused": True, "was": st.get("state"), "zone": zone})

    def note_stopped(self, zone):
        """Record that the current turn stopped media on this zone (see _pause)."""
        with self._lock:
            turn = self._turns.get(zone)
            if turn is None:
                # No turn open: this pause came from a non-satellite caller, so no reply clip is
                # coming and there is nothing to suppress. Same reasoning as note_playback --
                # inventing a turn here would suppress a later, unrelated reply.
                return
            turn["stopped"] = True

    def _turn_stopped(self, zone):
        with self._lock:
            turn = self._turns.get(zone) or {}
            return bool(turn.get("stopped"))

    def note_playback(self, ctx, zone, uri):
        """Record that the resolver just started media on this zone as part of the current turn.

        `_say` delivers a reply with play_media, which REPLACES the stream -- so the spoken
        confirmation of a media command ("Playing Radio Noroc Moldova") overwrites the very station
        it is confirming, and _say's capture runs while that station is still starting, so it
        captures no source to replay and the zone ends up idle holding the TTS clip. Keyed to the
        TURN, not a timer: a question asked seconds later is a new turn and still gets its reply."""
        with self._lock:
            self._queue_targets.pop(zone, None)      # MR-08c: new media started; nothing pending to resume
        self.remember_source(zone, uri)          # resumable regardless of who started it
        with self._lock:
            turn = self._turns.get(zone)
            if turn is None:
                # No turn open: this play came from a non-satellite caller (phone, ChatGPT text).
                # Creating a turn here would invent a phantom one -- suppressing that caller's
                # announce for the whole turn window and skipping a later satellite reply.
                return
            turn["playback"] = uri

    def _reply_baseline(self, zone, fallback):
        # The pre-duck baseline to hand back at the end of a reply turn. Caller holds _lock.
        # Order matters: the duck snapshot is the truest pre-duck value; an in-flight reply's
        # baseline is next (it was resolved the same way, so it survives a chain of barge-ins);
        # `fallback` (the live/captured volume) is last resort.
        snap = self._snaps.get(zone)
        if snap is not None and snap.get("volume") is not None:
            return snap["volume"]
        reply = self._replies.get(zone)
        if reply is not None and reply.get("baseline") is not None:
            return reply["baseline"]
        return fallback

    def _volume_recovery_secs(self, ctx):
        explicit = int(getattr(ctx.settings, "announce_volume_deadman_ms", 0))
        if explicit > 0:
            return explicit / 1000.0
        call = int(getattr(ctx.settings, "say_call_timeout_ms", 20000)) / 1000.0
        start = int(getattr(ctx.settings, "say_start_timeout_ms", 5000)) / 1000.0
        chime_fin = int(getattr(ctx.settings, "announce_chime_finish_timeout_ms", 15000)) / 1000.0
        msg_fin = int(getattr(ctx.settings, "announce_message_finish_timeout_ms", 45000)) / 1000.0
        # the same span as marker_budget_s (design 8.4a), plus 30s of margin
        return (5.0 + 5.0 + call + start + chime_fin + call + start + msg_fin
                + 5.0 + call) + 30.0

    def _cancel_volume_recovery(self, zone, gen):
        """Stand the net down -- but only ours. A newer turn's record must survive us."""
        with self._lock:
            rec = self._vol_recovery.get(zone)
            if rec is None or rec.get("gen") != gen:
                return
            del self._vol_recovery[zone]
        self._cancel_timer(rec)

    def _volume_recovery(self, ctx, zone, gen, attempt):
        """Last-resort restore for an UNDUCKED turn whose step-8 and finalizer writes both failed.

        POLICY CUTOFF, not a wall-clock bound (design 9.7): a pathologically slow-but-live turn
        could cross it. Two guards make an early fire cheap -- a newer turn owning the zone is left
        alone, and a volume we did not write is left alone -- so the worst case is restoring the
        baseline under a clip that is still playing, which beats an indefinitely stuck 0.80.
        """
        with self._lock:
            rec = self._vol_recovery.get(zone)
            if rec is None or rec.get("gen") != gen:
                return
        if self._say_gen.get(zone) != gen:
            LOG.info("VOLUME-RECOVERY zone=%s gen=%s superseded; a newer turn owns the restore",
                     zone, gen)
            with self._lock:
                if self._vol_recovery.get(zone) is rec:
                    del self._vol_recovery[zone]
            return
        try:
            live = ((ctx.ha.get_entity_state(zone) or {}).get("attributes") or {}).get("volume_level")
        except Exception as e:
            # Unreadable: we cannot confirm the level, and leaving the ceiling possibly loud is the
            # worse error, so fall through and restore.
            LOG.warning("VOLUME-RECOVERY zone=%s read failed (%r)", zone, e)
            live = None
        target = rec.get("target")
        if live is not None and target is not None and abs(live - target) > 0.01:
            LOG.info("VOLUME-RECOVERY zone=%s volume is %s, not the %s we wrote; leaving it",
                     zone, live, target)
            with self._lock:
                if self._vol_recovery.get(zone) is rec:
                    del self._vol_recovery[zone]
            return
        try:
            ctx.ha.call_service_rest("media_player", "volume_set",
                                     {"entity_id": zone, "volume_level": rec["baseline"]})
            LOG.warning("VOLUME-RECOVERY zone=%s restored -> %s (attempt %d)",
                        zone, rec["baseline"], attempt + 1)
            with self._lock:
                if self._vol_recovery.get(zone) is rec:
                    del self._vol_recovery[zone]
            return
        except Exception as e:
            retries = int(getattr(ctx.settings, "announce_volume_deadman_retries", 3))
            if attempt + 1 >= retries:
                # Terminal exhaustion is LOG-ONLY: /command has already answered, so this cannot
                # reach the phone. The resolver log is the sole witness -- hence error, not warning.
                LOG.error("VOLUME-RECOVERY zone=%s GAVE UP after %d attempts (%r); the ceiling may "
                          "be left at %s", zone, attempt + 1, e, rec.get("target"))
                with self._lock:
                    if self._vol_recovery.get(zone) is rec:
                        del self._vol_recovery[zone]
                return
            LOG.warning("VOLUME-RECOVERY zone=%s attempt %d failed (%r); re-arming",
                        zone, attempt + 1, e)
            secs = self._volume_recovery_secs(ctx)
            t = self._timer_factory(secs, self._volume_recovery, [ctx, zone, gen, attempt + 1])
            rec["timer"] = t
            t.start()

    def _claim_gen(self, zone):
        """Claim this zone's next turn generation up front, and return it.

        _announce needs turn ownership BEFORE it touches the microphone (requirement 1), which is
        earlier than _say's step 2 -- an announcement that muted the mic and only then discovered it
        had been superseded would have to unmute again, and the mic would have been dead for the
        newer turn's own wake word. One counter, one meaning; _say revalidates on adoption.

        Read and write stay under _lock together: HTTP threads and the timer thread claim against
        the same counter, and a read-then-write without the lock hands two turns the same generation
        -- neither would ever see itself superseded.
        """
        with self._lock:
            my_gen = self._say_gen.get(zone, 0) + 1
            self._say_gen[zone] = my_gen
            return my_gen

    def _mic_budget_s(self, ctx, clips):
        """Policy cutoff for the mic dead-man, derived from the engineered phase budget (design
        6.5).

        NOT a wall-clock bound: the phase timeouts it sums are per-operation inactivity allowances,
        so a pathologically slow-but-live turn can cross this. Firing early costs a few seconds of
        self-wake exposure; never firing leaves the satellite deaf with nothing scheduled to fix it,
        so the trade-off deliberately favours liveness.
        """
        explicit = int(getattr(ctx.settings, "announce_mic_deadman_ms", 0))
        if explicit > 0:
            return explicit / 1000.0
        start = int(getattr(ctx.settings, "say_start_timeout_ms", 5000)) / 1000.0
        call = int(getattr(ctx.settings, "say_call_timeout_ms", 20000)) / 1000.0
        confirm = int(getattr(ctx.settings, "announce_mic_confirm_timeout_ms", 2000)) / 1000.0
        chime_fin = int(getattr(ctx.settings, "announce_chime_finish_timeout_ms", 15000)) / 1000.0
        msg_fin = int(getattr(ctx.settings, "announce_message_finish_timeout_ms", 45000)) / 1000.0
        floor = int(getattr(ctx.settings, "announce_min_call_timeout_ms", 500)) / 1000.0
        # rows 5-16 of the design 6.5 table, then 30s of margin
        total = (confirm + 5.0 + 5.0                       # confirm, pause, raise
                 + call + start + chime_fin                # chime
                 + call + start + msg_fin                  # message
                 + 5.0 + call + 5.0                        # restore, replay, unmute
                 + 5 * floor)
        if clips < 2:
            total -= (call + start + chime_fin)
        return total + 30.0

    def _mic_refusal(self):
        return {"code": "unavailable", "reason": "mic mute unavailable",
                "chat_text": "I can't announce without muting the microphone."}

    def _mic_entity(self, ctx):
        return (getattr(ctx.settings, "announce_mic_mute_entity", "") or "").strip()

    def _mic_claim(self, ctx, zone, my_gen, rid, clips=2):
        """Lease the microphone and mute it. Returns (lease, err); err is a dict for cr.err.

        Muting is requirement 7's fail-safe: an unmuted satellite hears the announcement come out of
        the ceiling and wakes on it. announce_require_mic_mute means what it says -- with it set, a
        microphone we cannot mute is a refusal, not a warning.

        Held under _mic_lock for the whole claim, so a concurrent release cannot land its unmute
        between this mute and the lease that says the microphone is ours.
        """
        with self._mic_lock:
            return self._mic_claim_locked(ctx, zone, my_gen, rid, clips)

    def _mic_claim_locked(self, ctx, zone, my_gen, rid, clips=2):
        entity = self._mic_entity(ctx)
        require = bool(getattr(ctx.settings, "announce_require_mic_mute", True))
        if not entity:
            # config.py ships this EMPTY on purpose, so a machine with no config refuses rather
            # than broadcasting with a live microphone.
            LOG.warning("ANNOUNCE req=%s no announce_mic_mute_entity configured", rid)
            return (None, self._mic_refusal() if require else None)
        with self._lock:
            existing = self._mic.get(zone)
            inherited = existing["prev"] if existing is not None else None
        if inherited is None:
            # First claim: read the live state. A later announcement INHERITS this instead of
            # re-reading, or it would see the `on` we just wrote and treat muted as the operator's
            # standing preference -- leaving the satellite deaf forever (design 9.2). `is None`
            # rather than a truthiness test, because an inherited False is a real value.
            try:
                st = ctx.ha.get_entity_state(entity) or {}
            except Exception as e:
                LOG.warning("ANNOUNCE req=%s could not read %s (%r)", rid, entity, e)
                return (None, self._mic_refusal() if require else None)
            inherited = (st.get("state") == "on")
        lease = {"gen": my_gen, "prev": bool(inherited), "confirmed": False,
                 "rid": rid, "ts": self._clock(), "timer": None}
        with self._lock:
            self._mic[zone] = lease            # published BEFORE the write, so a crash between the
                                               #   write and the confirmation still leaves something
                                               #   for the dead-man and the finally to reconcile
        try:
            ctx.ha.call_service_rest("switch", "turn_on", {"entity_id": entity})
        except Exception as e:
            LOG.warning("ANNOUNCE req=%s switch.turn_on %s failed (%r)", rid, entity, e)
            with self._lock:
                if self._mic.get(zone) is lease:
                    del self._mic[zone]        # nothing was muted, so leaving a lease would make
                                               #   the NEXT announcement inherit a prev nobody
                                               #   observed, and hand the dead-man a phantom
            return (None, self._mic_refusal() if require else None)
        secs = self._mic_budget_s(ctx, clips)
        t = self._timer_factory(secs, self._mic_deadman, [ctx, zone, my_gen])
        lease["timer"] = t
        t.start()
        LOG.info("ANNOUNCE req=%s zone=%s mic leased gen=%s prev=%s deadman=%.0fs",
                 rid, zone, my_gen, lease["prev"], secs)
        return (lease, None)

    def _mic_confirm(self, ctx, zone, my_gen, rid):
        """Poll the switch until it reports `on`. Returns (confirmed, err).

        A 200 from switch.turn_on means HA ACCEPTED the request, not that the microphone is muted:
        this satellite drops its ESPHome API (Errno 113), and AN-2 measured HA answering the write
        in about 1ms while the state took ~255ms to report back. Without the read-back,
        requirement 7's fail-safe would be satisfied by an accepted request rather than an observed
        state (design 9.3). AN-2 also confirmed HA does NOT fake `on` for an unreachable device,
        which is what makes this read meaningful rather than decorative.
        """
        entity = self._mic_entity(ctx)
        require = bool(getattr(ctx.settings, "announce_require_mic_mute", True))
        if not entity:
            return (False, self._mic_refusal() if require else None)
        budget = int(getattr(ctx.settings, "announce_mic_confirm_timeout_ms", 2000)) / 1000.0
        step = max(int(getattr(ctx.settings, "announce_mic_confirm_poll_ms", 250)) / 1000.0, 0.05)
        floor = int(getattr(ctx.settings, "announce_min_call_timeout_ms", 500)) / 1000.0
        deadline = self._clock() + budget
        # Bounded by the wall-clock deadline AND by a poll count. The count is not redundant:
        # time.time is not monotonic, so an NTP step backwards mid-confirm keeps `deadline - now`
        # large and a purely clock-driven loop would keep polling past its budget.
        max_polls = int(budget / step) + 1
        polls = 0
        while polls < max_polls:
            left = deadline - self._clock()
            if left < floor:
                break
            try:
                st = ctx.ha.get_entity_state(entity, timeout=min(10, max(left, floor))) or {}
            except Exception as e:
                # A read blip must produce the documented refusal, not a bare traceback out of a
                # capability -- core would report it as an unattributed 500.
                LOG.warning("ANNOUNCE req=%s confirm read of %s failed (%r)", rid, entity, e)
                st = {}
            polls += 1
            if st.get("state") == "on":
                with self._lock:
                    lease = self._mic.get(zone)
                    if lease is not None and lease.get("gen") == my_gen:
                        lease["confirmed"] = True   # only OUR lease; a newer one is not ours to mark
                LOG.info("ANNOUNCE req=%s zone=%s mic mute CONFIRMED after %d poll(s)",
                         rid, zone, polls)
                return (True, None)
            self._sleeper(step)
        LOG.warning("ANNOUNCE req=%s zone=%s mic mute NOT confirmed within %.1fs (require=%s)",
                    rid, zone, budget, require)
        if require:
            return (False, {"code": "unavailable", "reason": "mic mute not confirmed",
                            "chat_text": "I couldn't mute the microphone, so I didn't announce."})
        return (False, None)

    def _mic_release(self, ctx, zone, my_gen, rid):
        """Restore the microphone -- only if the LEASE is still ours. Returns whether it restored.

        The check is on _mic, NOT on _say_gen. Zone supersession by a satellite reply or a say_text
        turn bumps _say_gen but never writes _mic, so the lease is still ours and we unmute
        IMMEDIATELY -- which is exactly what is wanted: the superseding turn is a person talking to
        the satellite, and they need the microphone back now (design 9.4/9.6). Only a newer
        ANNOUNCEMENT takes the lease, and then it owns the restore.

        Held under _mic_lock for the whole release. Validating the lease and then unmuting without
        it left a full REST round trip in which a newer announcement could claim and mute, only to
        be unmuted by this turn.
        """
        with self._mic_lock:
            return self._mic_release_locked(ctx, zone, my_gen, rid)

    def _mic_release_locked(self, ctx, zone, my_gen, rid):
        entity = self._mic_entity(ctx)
        with self._lock:
            lease = self._mic.get(zone)
            if lease is None or lease.get("gen") != my_gen:
                LOG.info("ANNOUNCE req=%s zone=%s mic release skipped: lease is not ours", rid, zone)
                return False
        if lease.get("prev"):
            # The operator already had it muted; leave it muted.
            self._cancel_timer(lease)
            with self._lock:
                if self._mic.get(zone) is lease:
                    del self._mic[zone]
            LOG.info("ANNOUNCE req=%s zone=%s mic left muted (prev=on)", rid, zone)
            return True
        try:
            ctx.ha.call_service_rest("switch", "turn_off", {"entity_id": entity})
        except Exception as e:
            # Deliberately BEFORE any cancel: the dead-man is the only thing left that can fix a
            # microphone we failed to unmute, so cancelling it here would make this log line a lie
            # and leave the satellite deaf with nothing scheduled.
            LOG.error("ANNOUNCE req=%s zone=%s mic unmute FAILED (%r); dead-man must reconcile",
                      rid, zone, e)
            return False
        self._cancel_timer(lease)
        with self._lock:
            if self._mic.get(zone) is lease:
                del self._mic[zone]
        LOG.info("ANNOUNCE req=%s zone=%s mic restored", rid, zone)
        return True

    def _mic_deadman(self, ctx, zone, my_gen):
        LOG.warning("ANNOUNCE mic dead-man fired zone=%s gen=%s; restoring the microphone",
                    zone, my_gen)
        try:
            self._mic_release(ctx, zone, my_gen, "mic-deadman")
        except Exception as e:
            # This runs on the timer thread, where an escaping exception is unhandled and fixes
            # nothing while the microphone stays muted.
            LOG.error("ANNOUNCE mic dead-man failed zone=%s (%r)", zone, e)

    def _restore(self, ctx, zone, rid):
        with self._lock:
            if self._reply_active(ctx, zone) is not None:
                # S1b-2 decision (b): a reply turn owns this zone's volume until its clip ends.
                # Restoring here would read _say's reply volume, misread it as a human change
                # (user_override below), and DISCARD the baseline _say still needs -- the reply-turn
                # volume ratchet/crater. Defer instead, and keep a dead-man armed in case the reply
                # never finishes, since we are declining to clear the snapshot.
                snap = self._snaps.get(zone)
                if snap is not None:
                    self._arm_timer(ctx, zone)
                LOG.info("RESTORE req=%s zone=%s deferred: reply active (say owns restore)", rid, zone)
                return cr.ok(self.name, rid, "Reply in progress.", spoken_text=None,
                             metadata={"restored": False, "reason": "reply_active", "zone": zone})
            self._turns.pop(zone, None)          # restore with no reply in flight == the turn is over
            snap = self._snaps.get(zone)                              # peek; discard only after write
            if snap is None:
                return cr.ok(self.name, rid, "Nothing to restore.", spoken_text=None,
                             metadata={"restored": False, "reason": "no_snapshot", "zone": zone})
            try:
                state = ctx.ha.get_entity_state(zone, timeout=LOCK_HELD_CALL_TIMEOUT) or {}
                cur = (state.get("attributes") or {}).get("volume_level")
            except Exception as e:
                LOG.warning("RESTORE req=%s zone=%s read failed (%r); restoring baseline", rid, zone, e)  # KEEP: F5
                cur = None
            applied = snap.get("target")
            if cur is not None and applied is not None and abs(cur - applied) > 0.01:
                self._cancel_timer(snap); self._snaps.pop(zone, None)
                LOG.info("RESTORE req=%s zone=%s user_override cur=%s (kept)", rid, zone, cur)
                return cr.ok(self.name, rid, "Kept.", spoken_text=None,
                             metadata={"restored": False, "reason": "user_override", "zone": zone})
            target = snap.get("volume")
            if target is None:
                self._cancel_timer(snap); self._snaps.pop(zone, None)
                return cr.ok(self.name, rid, "Nothing to restore.", spoken_text=None,
                             metadata={"restored": False, "reason": "no_baseline", "zone": zone})
            ctx.ha.call_service_rest("media_player", "volume_set",
                                     {"entity_id": zone, "volume_level": target},
                                     timeout=LOCK_HELD_CALL_TIMEOUT)
            self._cancel_timer(snap); self._snaps.pop(zone, None)
            LOG.info("RESTORE req=%s zone=%s -> %s", rid, zone, target)
            return cr.ok(self.name, rid, "Restored.", spoken_text=None,
                         metadata={"restored": True, "to": target, "zone": zone})

    def _normalise_uri(self, uri, internal_base):
        # Rewrite the reply URI's netloc (host:port) to an MA-reachable base; preserve scheme/path/query.
        if not internal_base:
            return uri
        try:
            parts = urlparse(uri)
            return urlunparse((parts.scheme, internal_base, parts.path, parts.params,
                               parts.query, parts.fragment))
        except Exception:
            return uri

    # authSig is HA's signed-media parameter; the rest are the shapes a credential arrives in
    # elsewhere. Anchored with \b so it cannot fire inside an unrelated word -- "design=ok" is not
    # a signature -- and the longer names come first so `token` cannot shadow `access_token`.
    _SECRET_PARAM_RE = re.compile(r"\b(authSig|signature|access_token|token|sig)=[^&\s]*",
                                  re.IGNORECASE)

    def _redact_uri(self, value):
        """Strip credential parameters out of a URI before it can reach a log.

        A signed media URL is a BEARER CREDENTIAL, and it travels inside the media_content_id that
        HA reports back on every poll -- a path design 6.1 did not consider. The finish-poll used to
        log `cid[:60]`, which for the URL measured at AN-1 stops just short of `authSig`. That is
        luck, not a guarantee: a shorter host or path writes a live credential into resolver.log,
        which is world-readable on the host and quoted freely in CHANGELOG.md.

        A truncation is not a redaction, so this is applied to every log line that emits a
        media_content_id or a resolved URL. Truncation may still follow it, for brevity.
        """
        try:
            return self._SECRET_PARAM_RE.sub(r"\1=REDACTED", value or "")
        except Exception:
            return "<unredactable>"

    def _clip_id(self, uri):
        # Short fingerprint of the reply clip, for correlating log lines WITHOUT logging the URI
        # (reply URLs are unauthenticated-but-obscure tts_proxy links -- never log them verbatim).
        try:
            return hashlib.sha1((uri or "").encode("utf-8")).hexdigest()[:8]
        except Exception:
            return "????????"

    def _warn_if_double_speak(self, ctx, zone, rid, clip):
        # Two voices on one turn: the resolver announces a capability's spoken_text via tts.speak
        # (core.dispatch, the sole-TTS-owner rule) AND the satellite pipeline relays the same text
        # through Piper, which lands here as a reply clip. The operator hears the answer twice.
        # Diagnostic only -- this does not suppress either voice.
        sp = getattr(ctx, "speaker", None)
        last = getattr(sp, "last_announce_ts", None) if sp is not None else None
        if last is None:
            return
        window = int(getattr(ctx.settings, "say_double_speak_window_ms", 8000)) / 1000.0
        age = self._clock() - last
        if 0 <= age <= window:
            LOG.warning("SAY req=%s zone=%s clip=%s DOUBLE-SPEAK: resolver announced %.1fs ago "
                        "(%r) and this reply is a second voice on the same zone",
                        rid, zone, clip, age, (getattr(sp, "last_announce_text", "") or "")[:60])

    def _say_call(self, ctx, rid, zone, domain, service, data, timeout=None):
        # One place to time + attribute _say's service calls: a bare timeout used to surface only as
        # "capability=interaction error: timeout" with no hint of WHICH call died.
        t0 = self._clock()
        try:
            if timeout is None:
                ctx.ha.call_service_rest(domain, service, data)
            else:
                ctx.ha.call_service_rest(domain, service, data, timeout=timeout)
        except Exception as e:
            LOG.error("SAY req=%s zone=%s %s.%s failed after %.1fs (%r)",
                      rid, zone, domain, service, self._clock() - t0, e)
            raise

    def _say_text(self, ctx, resolved, rid):
        """Speak a SENTENCE on the zone: resolve it to a clip URL, then hand it to _say so the whole
        proven reply route applies (internal-base normalisation, reply volume, poll-to-completion,
        restore, source replay, barge-in). Deliberately never touches the announce/overlay path."""
        text = resolved.get("text") or ""
        engine = getattr(ctx.settings, "tts_engine", "") or "tts.piper"   # config default is tts.piper
        try:
            uri = ctx.ha.tts_get_url(engine, text)
        except Exception as e:
            LOG.warning("SAY_TEXT req=%s zone=%s could not resolve text to a clip (%r)",
                        rid, resolved.get("zone"), e)
            return cr.err(self.name, rid, "upstream_error", "tts_get_url failed",
                          "I couldn't say that.", spoken_text=None,
                          metadata={"said": False, "zone": resolved.get("zone")})
        # Defence in depth: `say` with an empty uri is a silent no-op that still reports success.
        # validate() catches that for mode=say; the same rule has to hold AFTER resolution here.
        if not uri:
            LOG.warning("SAY_TEXT req=%s zone=%s resolved to an empty clip uri",
                        rid, resolved.get("zone"))
            return cr.err(self.name, rid, "upstream_error", "no clip uri",
                          "I couldn't say that.", spoken_text=None,
                          metadata={"said": False, "zone": resolved.get("zone")})
        # The URL goes in WHOLE, redacted but NOT truncated. On 2026-09-27 an announcement made no
        # sound because this URL ended `.flac` and returned 404 -- MA skipped it as unplayable 91ms
        # in -- and the resolver's log could not show it: resolve time recorded only engine/chars,
        # and the finish poll truncates the cid at 80 characters, landing just short of the
        # extension. Redaction is what makes emitting the whole thing safe; brevity is what hid the
        # fault, so it is not a trade worth making here.
        LOG.info("SAY_TEXT req=%s zone=%s engine=%s chars=%d url=%s", rid, resolved.get("zone"),
                 engine, len(text), self._redact_uri(uri))
        resolved["uri"] = uri
        # A pushed sentence (timer chime, alert) is NOT confirmed by unrelated playback starting in
        # the same turn, so it must not inherit _say's media-confirmation skip -- that would drop it
        # silently while still reporting "Said.".
        resolved["skip_on_fresh_playback"] = False
        return self._say(ctx, resolved, rid)

    def _announce(self, ctx, resolved, rid):
        """Broadcast a sentence on the zone: chime + speech, as ONE reply-owned turn.

        Ordering (design 7) puts every cheap failure before anything is touched:

            A validate       (done by validate(), before we get here)
            B render + bound
            C resolve the TTS clip
            D resolve the chime
            E claim the generation
            F lease + mute the microphone
            G CONFIRM the mute by reading it back
            H one reply-owned turn through _say
            I map the outcome
            finally: release the lease

        C before F is deliberate. A TTS failure is the likeliest failure in this sequence, and
        paying for it with a muted microphone and a raised volume would be gratuitous.
        """
        zone = resolved["zone"]

        # B. Render and bound. Rejection, never truncation -- see _render_announcement_text.
        rendered, err, prefix_dropped = self._render_announcement_text(ctx, resolved.get("text"))
        if err is not None:
            return cr.err(self.name, rid, err["code"], err["reason"], err["chat_text"],
                          spoken_text=None,
                          metadata={"announced": False, "zone": zone,
                                    "prefix_dropped": prefix_dropped})

        # C. TTS clip. Nothing has been touched yet, so a failure here is free.
        engine = getattr(ctx.settings, "tts_engine", "") or "tts.piper"
        try:
            tts_uri = ctx.ha.tts_get_url(engine, rendered)
        except Exception as e:
            LOG.warning("ANNOUNCE req=%s zone=%s could not resolve text to a clip (%r)",
                        rid, zone, e)
            return cr.err(self.name, rid, "upstream_error", "tts_get_url failed",
                          "I couldn't say that.", spoken_text=None,
                          metadata={"announced": False, "zone": zone})
        if not tts_uri:
            # Defence in depth: an empty uri would make _say a silent no-op that still reports
            # success -- the exact "claimed success, did nothing" class design 8.5 rules out.
            LOG.warning("ANNOUNCE req=%s zone=%s resolved to an empty clip uri", rid, zone)
            return cr.err(self.name, rid, "upstream_error", "no clip uri",
                          "I couldn't say that.", spoken_text=None,
                          metadata={"announced": False, "zone": zone})
        # Whole and redacted -- see the matching line in _say_text for why the extension matters.
        LOG.info("ANNOUNCE req=%s zone=%s engine=%s chars=%d url=%s",
                 rid, zone, engine, len(rendered), self._redact_uri(tts_uri))

        # D. Chime. A failure DEGRADES: an announcement without its chime is still an
        #    announcement. Resolved every turn and never cached -- the signature expires, and a
        #    cached URL would fail silently two layers from its symptom.
        chime_uri = (getattr(ctx.settings, "announce_chime_uri", "") or "").strip()
        chime = {"played": False, "end_observed": False, "reason": None}
        chime_resolved = None
        if not chime_uri:
            chime["reason"] = "disabled"
        else:
            try:
                chime_resolved = ctx.ha.resolve_media_source(chime_uri)
            except Exception as e:
                # Never log the resolved URL: it carries a signature, which is a bearer credential.
                LOG.warning("ANNOUNCE req=%s zone=%s chime resolve failed (%r); continuing "
                            "without a chime", rid, zone, e)
                chime["reason"] = "resolve_failed"
            if chime_resolved is None and chime["reason"] is None:
                LOG.warning("ANNOUNCE req=%s zone=%s chime resolved to nothing; continuing "
                            "without a chime", rid, zone)
                chime["reason"] = "resolve_failed"

        uris = ([chime_resolved] if chime_resolved else []) + [tts_uri]
        # Every clip's match key is its FULL URI, query included. Design 8.2 specified a path-only
        # key for the chime on the assumption that MA strips the query; AN-1 measured the query as
        # PRESERVED, so that special case is withdrawn (post-G1 correction 1). The list is still
        # passed explicitly: it keeps per-clip matching visible and leaves a seam if MA's wrapping
        # changes.
        match_keys = list(uris)
        finish_timeouts = (
            ([int(getattr(ctx.settings, "announce_chime_finish_timeout_ms", 15000)) / 1000.0]
             if chime_resolved else [])
            + [int(getattr(ctx.settings, "announce_message_finish_timeout_ms", 45000)) / 1000.0])

        # E. Claim the generation BEFORE touching the microphone (requirement 1). Muting first and
        #    only then discovering we were superseded would leave the mic dead through the newer
        #    turn's own wake word.
        my_gen = self._claim_gen(zone)

        # F. Lease + mute.
        lease, mic_err = self._mic_claim(ctx, zone, my_gen, rid, clips=len(uris))
        if mic_err is not None:
            return cr.err(self.name, rid, mic_err["code"], mic_err["reason"],
                          mic_err["chat_text"], spoken_text=None,
                          metadata={"announced": False, "zone": zone,
                                    "mic": {"muted": False, "confirmed": False}})
        muted = lease is not None
        try:
            # G. CONFIRM by reading. A 200 from switch.turn_on is an accepted request, not a muted
            #    microphone.
            confirmed = False
            if muted:
                confirmed, conf_err = self._mic_confirm(ctx, zone, my_gen, rid)
                if conf_err is not None:
                    return cr.err(self.name, rid, conf_err["code"], conf_err["reason"],
                                  conf_err["chat_text"], spoken_text=None,
                                  metadata={"announced": False, "zone": zone,
                                            "mic": {"muted": True, "confirmed": False}})

            # H. One reply-owned turn: one baseline, one raise, N clips, one restore, one replay.
            seq = dict(resolved)
            seq["uri"] = tts_uri
            seq["uris"] = uris
            seq["match_keys"] = match_keys
            seq["finish_timeouts"] = finish_timeouts
            seq["volume_override"] = float(getattr(ctx.settings, "announce_volume", 0.80))
            seq["gen"] = my_gen
            # The play_media call is spent INSIDE this window, and this file notes a few hundred
            # lines down that "MA's play_media regularly outruns the 5s REST default". Omitting it
            # made the deadline 70s for work that can need 100s, so the message clip could exit via
            # `turn_deadline` WHILE AUDIBLY PLAYING -- reported as a failure for an announcement the
            # room heard. marker_budget already includes the call cost per clip; these now agree.
            # Widening a bound only: no clip that completes today can start failing because of it.
            seq["deadline_from_now"] = sum(finish_timeouts) + (
                len(uris) * int(getattr(ctx.settings, "say_start_timeout_ms", 5000)) / 1000.0) + (
                len(uris) * int(getattr(ctx.settings, "say_call_timeout_ms", 20000)) / 1000.0)
            # A pushed sentence is NOT confirmed by unrelated playback starting in the same turn,
            # so it must not inherit _say's media-confirmation skip.
            seq["skip_on_fresh_playback"] = False
            LOG.info("ANNOUNCE req=%s zone=%s clips=%d chars=%d volume=%s",
                     rid, zone, len(uris), len(rendered), seq["volume_override"])
            res = self._say(ctx, seq, rid)

            # I. Map the outcome. A silent announcement is a FAILURE, not a success: the caller is
            #    broadcasting to a room they may not be in, so "Announced." when nothing came out
            #    is the one answer they cannot check (design 8.5).
            meta = dict(res.get("metadata") or {})
            clips = meta.get("clips") or []
            if chime_resolved and clips:
                # The chime was the last clip judged by `started` alone. It stays decorative --
                # design 8.3 is explicit that a bad chime is a DEGRADED announcement, not a silent
                # one, and it must never fail the turn -- but reporting {played: True, reason: None}
                # for a chime whose end was never observed is the same overclaim the message path
                # was fixed for, and this metadata is what gets read when an announcement sounded
                # wrong. `played` still means "it started": that part was accurate.
                chime["played"] = bool(clips[0].get("started"))
                chime["end_observed"] = bool(clips[0].get("ended"))
                if not chime["played"] and chime["reason"] is None:
                    chime["reason"] = "never_started"
                elif chime["played"] and not chime["end_observed"] and chime["reason"] is None:
                    chime["reason"] = "end_unobserved"
            meta["chime"] = chime
            meta["mic"] = {"muted": muted, "confirmed": confirmed}
            meta["prefix_dropped"] = prefix_dropped
            meta["announced"] = bool(meta.get("said")) and not meta.get("likely_silent")
            if meta.get("superseded"):
                # Being superseded is a person talking to the satellite. That is not a fault to
                # surface to the operator as a failed announcement.
                return cr.ok(self.name, rid, "Announced.", spoken_text=None, metadata=meta)
            if not meta["announced"]:
                return cr.err(self.name, rid, "upstream_error", "announcement did not start",
                              "I couldn't play the announcement.", spoken_text=None, metadata=meta)
            # Three outcomes, because there are three states of knowledge. The clip started, so we
            # cannot claim it was silent -- but its end was never observed, so we cannot claim it
            # finished either. Saying so is the whole point of this increment: the operator is
            # broadcasting to a room they may not be in, and "Announced." is the one answer they
            # cannot check. An unqualified success here would be a guess wearing a fact's clothes.
            if not meta.get("end_observed"):
                return cr.ok(self.name, rid, "Announced, but I couldn't confirm it finished.",
                             spoken_text=None, metadata=meta)
            return cr.ok(self.name, rid, "Announced.", spoken_text=None, metadata=meta)
        finally:
            # Every exit path, including an exception: a stuck-muted microphone is a deaf satellite,
            # which is a silent open-ended failure nobody finds until they try to talk to it.
            if muted:
                self._mic_release(ctx, zone, my_gen, rid)

    def _play_clip_and_wait(self, ctx, rid, zone, norm_uri, match_key, clip, opts, superseded,
                            enqueue=None, issue=True, other_item_s=None):
        """Play ONE clip on the zone and wait for it: play_media -> start-poll -> finish-poll.

        Everything a TURN owns stays with the caller -- generation ownership, baseline capture, the
        single volume raise, the single restore, the single replay, the release. This method owns
        exactly one clip, which is what lets a caller sequence several of them over one turn.

        `match_key` is separate from `norm_uri` because MA does not echo back what it plays: it
        wraps it, and wraps it differently per media type. The caller therefore has to be able to
        say what a "this clip is playing" observation looks like.

        `opts` carries `start_timeout`, `finish_timeout`, `call_timeout`, `poll_secs`,
        `blank_grace`, `floor` and `deadline` (float, or None). Each poll is bounded by its own
        accumulated sleep AND, when a deadline is given, by the earlier of that deadline and this
        clip's own timeout -- so a generous turn budget never lets one clip overrun its allowance,
        and a clock that stalls or steps backwards cannot leave the poll unbounded.

        `other_item_s` (queue mode only; legacy callers pass nothing, which keeps the two-reading
        rule for every ending) changes what an HA `playing` reading naming ANOTHER, non-empty media id
        means: it ends the clip only once it has persisted for `other_item_s` continuously, measured
        in accumulated poll sleeps like every other bound here. Any other reading -- back on the clip,
        an empty cid, a failed read -- resets it. In queue mode the interrupted item stays in MA's
        queue, and ~1.3 s into a clip BOTH HA and MA report it as current for ~0.75 s before the
        clip resumes (design 4.8 A1.1, spike 4 / 3.3-1): two readings, and an MA cross-check, both
        read that flip as the end. HA not `playing` still ends the clip on two readings.

        Returns {"started", "issued", "clip", "ended", "gave_up"}. `ended` is True only when the
        clip's end was actually OBSERVED; `gave_up` names why the wait stopped otherwise. Both
        matter because the caller cannot otherwise tell a finished clip from an abandoned one --
        which is exactly how an announcement nobody heard reported "Announced." on 2026-09-27.

        Propagates whatever play_media raises -- the caller's finally is the recovery path, and it
        owns the volume restore, so it has to see the failure.
        """
        out = {"started": False, "issued": False, "clip": clip, "ended": False, "gave_up": None}
        deadline = opts.get("deadline")
        poll_secs = opts["poll_secs"]
        floor = opts["floor"]

        def read_timeout(default_timeout):
            # Clip a blocking read to what is left of this phase (design 6.5). A socket timeout is a
            # per-operation inactivity timeout, not a request deadline, so this reduces overshoot
            # rather than proving a limit. None means: do not start another blocking call at all --
            # a read begun with less than `floor` left buys nothing and only overshoots the phase.
            if deadline is None:
                return default_timeout
            left = deadline - self._clock()
            if left < floor:
                return None
            return min(default_timeout, left)

        # MA's play_media regularly outruns the 5s REST default; a client-side timeout here aborts
        # the turn while the clip still starts server-side (audible, unsequenced).
        if issue:
            data = {"entity_id": zone, "media_id": norm_uri}
            if enqueue:
                # MR-08c: insert the clip instead of replacing the queue (design 4.3-3).
                data["enqueue"] = enqueue
            self._say_call(ctx, rid, zone, "music_assistant", "play_media", data, timeout=opts["call_timeout"])
        out["issued"] = True

        # Confirm start: poll until the clip is actually playing, or the start budget runs out.
        start_timeout = opts["start_timeout"]
        start_deadline = self._clock() + start_timeout
        elapsed = 0.0
        start_unreadable = 0
        started_unreadable = False
        while True:
            if superseded():
                return out
            # Bounded by BOTH the accumulated sleep and, when there is one, the wall clock.
            #
            # The wall-clock test is what enforces this clip's own budget alongside the turn
            # deadline -- min(start_deadline, deadline) means a long turn budget cannot let one clip
            # poll past its own allowance, and a short turn budget still wins.
            #
            # The accumulated-sleep test is the belt. time.time is not monotonic, so a clock that
            # stalls or steps backwards keeps `deadline - now` large and would leave a purely
            # wall-clock loop unbounded. Under a sane clock the wall clock always reaches the budget
            # first -- reads take real time while the sleep count does not -- so this costs nothing.
            if elapsed >= start_timeout:
                break
            if deadline is not None and self._clock() >= min(start_deadline, deadline):
                break
            rt = read_timeout(10)
            if rt is None:
                break
            try:
                state = ctx.ha.get_entity_state(zone, timeout=rt) or {}
            except Exception as e:
                LOG.warning("SAY req=%s zone=%s start-poll read failed (%r)", rid, zone, e)
                # Same rule as the finish poll: a read that did not happen is not an observation.
                # `{}` never matches, so a run of failures used to exhaust the start budget and
                # report `never_started` -- which the announce path states as "the room certainly
                # heard nothing" and turns into a flat denial. play_media was already accepted, so
                # the clip may be audible; claiming otherwise is a guess, and acting on it replays
                # the source straight over live speech.
                start_unreadable += 1
                if start_unreadable >= UNREADABLE_LIMIT:
                    started_unreadable = True
                    break
                self._sleeper(poll_secs)
                elapsed += poll_secs
                continue
            start_unreadable = 0
            attrs = state.get("attributes") or {}
            # MA does not echo the raw URL back as media_content_id -- it wraps it, e.g.
            # "builtin://radio/<url>". Match by containment, not equality.
            if state.get("state") == "playing" and match_key in (attrs.get("media_content_id") or ""):
                out["started"] = True
                break
            self._sleeper(poll_secs)
            elapsed += poll_secs

        if not out["started"]:
            # Two different facts. "never_started" means we WATCHED the zone and it never began
            # playing -- the room heard nothing. "unreadable" means we could not see the zone at
            # all, which says nothing about what came out of the speakers.
            if started_unreadable:
                LOG.warning("SAY req=%s zone=%s clip=%s start-poll could not read the zone; "
                            "whether it is playing is UNKNOWN", rid, zone, clip)
                out["gave_up"] = "unreadable"
            else:
                LOG.warning("SAY req=%s zone=%s clip=%s did not start (likely silent)",
                            rid, zone, clip)
                out["gave_up"] = "never_started"
            return out

        # Wait for finish: poll until the clip stops playing (or the caller is superseded).
        finish_timeout = opts["finish_timeout"]
        finish_deadline = self._clock() + finish_timeout
        blank_grace = max(opts["blank_grace"], poll_secs)
        elapsed = 0.0
        ended_seen = 0
        blank_for = 0.0
        # Consecutive failed reads before the poll admits it cannot tell. One bad read is a blip on
        # a busy HA; a run of them means we have no view of the zone at all.
        unreadable = 0
        # Queue mode (A1.1): accumulated-sleep time at which HA first named another item while playing,
        # in the current unbroken run of such readings. None = no run in progress.
        other_since = None
        # NO EARLY EXIT ON A STALLED POSITION. A clip the player accepts but never plays --
        # `playing`, cid matching, media_position pinned, no sound -- is real and cost 52s of muted
        # microphone on 2026-09-27. Detecting it from media_position/media_position_updated_at was
        # implemented and then REMOVED, because measuring a HEALTHY stream falsified the premise:
        # an audibly playing radio stream reported pos=1799 and a frozen media_position_updated_at
        # unchanged across a 20s sample. MA throttles elapsed_time reporting, so "position has not
        # moved" does not distinguish a stalled clip from a playing one, and the detector would
        # have cut off audible speech. Do not reintroduce this without a signal that a healthy
        # player demonstrably moves.
        # Why the clip's wait ended. None once the end was actually OBSERVED; a string means we gave
        # up without seeing it. Three exits used to be silent, which is why the G3 failure showed up
        # as a 45s hole between two ordinary lines and was diagnosable only by subtracting
        # timestamps.
        gave_up = "finish_timeout"
        while True:
            if superseded():
                return out
            # Both bounds again -- see the start poll above for why the accumulated-sleep test is
            # kept even when a deadline is set.
            if elapsed >= finish_timeout:
                gave_up = "finish_timeout"
                break
            if deadline is not None and self._clock() >= min(finish_deadline, deadline):
                gave_up = "turn_deadline"
                break
            rt = read_timeout(10)
            if rt is None:
                gave_up = "below_floor"
                break
            try:
                state = ctx.ha.get_entity_state(zone, timeout=rt) or {}
            except Exception as e:
                LOG.warning("SAY req=%s zone=%s finish-poll read failed (%r)", rid, zone, e)
                # A read that did not happen is NOT an observation. `state = {}` used to make
                # state.get("state") != "playing" true, so two consecutive timeouts reached
                # ended_seen >= 2 and the turn reported an observed ending -- "Announced." built
                # out of two failed reads, in exactly the conditions where announcements fail.
                # Past a bound, say we could not tell rather than inventing an answer.
                unreadable += 1
                if unreadable >= UNREADABLE_LIMIT:
                    gave_up = "unreadable"
                    break
                # A poll that observed nothing must not COUNT towards the two consecutive
                # observations the ending rule requires, or `flicker -> failed read -> flicker`
                # satisfies a rule whose whole point is that flickers must be consecutive.
                ended_seen = 0
                other_since = None              # same rule for the queue-mode persistence run
                self._sleeper(poll_secs)
                elapsed += poll_secs
                continue
            unreadable = 0
            attrs = state.get("attributes") or {}
            cid = attrs.get("media_content_id") or ""
            # MA transiently reports an EMPTY media_content_id while the clip is still playing.
            # Treating that as "the clip ended" cut the reply off after 0.5-1.0s and replayed the
            # source over it -- so an empty cid is NOT an ending while the player still says
            # `playing`. Only a cid that names something ELSE counts.
            ended = (state.get("state") != "playing") or (cid != "" and match_key not in cid)
            if not ended and cid == "":
                # Unknown, not "still playing": tolerate the flicker, but only for a bounded grace.
                # Beyond that we cannot tell, and holding the zone at reply volume for the full
                # finish timeout is worse than finishing.
                blank_for += poll_secs
                if blank_for >= blank_grace:
                    LOG.info("SAY req=%s zone=%s clip=%s finish-poll: cid stayed empty for %.1fs "
                             "(state=playing); treating the clip as finished",
                             rid, zone, clip, blank_for)
                    gave_up = None
                    break
            elif cid != "":
                blank_for = 0.0
            if other_item_s is not None:
                # Queue mode (design 4.8 A1.1). Only `playing` + another non-empty id is subject to the
                # persistence rule; not-`playing` falls through to the two-reading rule below.
                if state.get("state") == "playing" and ended:
                    if other_since is None:
                        other_since = elapsed
                        LOG.info("SAY req=%s zone=%s clip=%s finish-poll: HA playing another item cid=%s; "
                                 "it ends the clip only after %.1fs", rid, zone, clip,
                                 self._redact_uri(cid)[:80], other_item_s)
                    persisted = elapsed - other_since
                    if persisted + OTHER_ITEM_EPSILON_S >= other_item_s:
                        LOG.info("SAY req=%s zone=%s clip=%s finish-poll exit after %.1fs: state=%s cid=%s "
                                 "(another item persisted %.1fs)", rid, zone, clip, elapsed,
                                 state.get("state"), self._redact_uri(cid)[:80], persisted)
                        gave_up = None
                        break
                    ended = False
                else:
                    other_since = None
            if ended:
                # Require two consecutive observations: a single flicker of state or cid must not
                # trigger the restore+replay that is heard as a cut-off.
                ended_seen += 1
                if ended_seen >= 2:
                    # Redact BEFORE truncating: the truncation is for brevity and guarantees
                    # nothing on its own.
                    LOG.info("SAY req=%s zone=%s clip=%s finish-poll exit after %.1fs: state=%s cid=%s",
                             rid, zone, clip, elapsed, state.get("state"),
                             self._redact_uri(cid)[:80])
                    gave_up = None
                    break
            else:
                ended_seen = 0
            self._sleeper(poll_secs)
            elapsed += poll_secs
        if gave_up is not None:
            # The clip's end was never observed. Say so: this is the difference between a turn that
            # finished and one that merely ran out of time, and the two are indistinguishable in the
            # log otherwise.
            LOG.warning("SAY req=%s zone=%s clip=%s finish-poll gave up after %.1fs without "
                        "observing the clip end (budget %.1fs, reason=%s)",
                        rid, zone, clip, elapsed, finish_timeout, gave_up)
        out["gave_up"] = gave_up
        out["ended"] = gave_up is None
        return out

    # --- MR-08c queue mode -------------------------------------------------------------------------------
    def _queue_on(self, ctx, zone=None):
        # queue_id names the CEILING player's queue: any other zone keeps the legacy replay.
        return (bool(getattr(ctx.settings, "say_queue_resume", True))
                and getattr(ctx, "ma_factory", None) is not None
                and bool(getattr(ctx.settings, "queue_id", None))
                and (zone is None or zone == getattr(ctx.settings, "ceiling_entity", zone)))

    def _ma_open(self, ctx):
        """A fresh MA connection for ONE phase (design 4.2): a reply can idle the socket for minutes.
        Short timeouts: an unresponsive MA must cost the reply seconds, not a 60 s call timeout."""
        ma = ctx.ma_factory()
        if getattr(ma, "s", None) is None:
            try:
                ma.connect(connect_timeout=int(getattr(ctx.settings, "say_ma_connect_timeout_ms", 3000)) / 1000.0,
                           call_timeout=int(getattr(ctx.settings, "say_ma_call_timeout_ms", 5000)) / 1000.0)
            except Exception:
                self._ma_close(ma)          # a failed auth leaves the socket open
                raise
        return ma

    def _ma_close(self, ma):
        if ma is not None:
            try:
                ma.close()
            except Exception:
                pass

    def _other_item_s(self, ctx):
        """A1.1: how long HA must name another item (while playing) before a queue-mode clip counts as ended."""
        return max(int(getattr(ctx.settings, "say_queue_other_item_ms", 1500)), 0) / 1000.0

    # --- A1.2/A1.3 cleanup reads and verified deletes ---------------------------------------------------------
    def _queue_read(self, ma, queue_id):
        """One cleanup read (design 4.8 A1.3): queue_state plus the WHOLE item list, sized by the state's own
        `items` count. -> None when the state read fails, else {"q": state result, "index_of": {qiid: index},
        "complete": bool, "why": reason when not complete}. Presence can only be judged on a complete read, so a
        queue over CLEANUP_READ_CAP, an unknown count or a failed/short item read is incomplete (fail closed)."""
        try:
            s = ma.queue_state(queue_id)
        except Exception:
            return None
        if not _ma_ok(s):
            return None
        q = s.get("result") or {}
        total = q.get("items")
        snap = {"q": q, "index_of": {}, "complete": False, "why": None}
        if not _is_int(total) or total < 0:
            snap["why"] = "queue item count unknown"
            return snap
        if total > CLEANUP_READ_CAP:
            snap["why"] = "queue too large to verify (%d items > %d)" % (total, CLEANUP_READ_CAP)
            return snap
        if total == 0:
            snap["complete"] = True
            return snap
        try:
            r = ma.queue_items(queue_id, offset=0, limit=total)
        except Exception as e:
            snap["why"] = "item list read failed (%r)" % (e,)
            return snap
        if not _ma_ok(r):
            snap["why"] = "item list read failed"
            return snap
        items = r.get("result") or []
        for i, it in enumerate(items):
            qiid = (it or {}).get("queue_item_id")
            if qiid:
                snap["index_of"][qiid] = i
        if len(items) != total:
            snap["why"] = "item list read returned %d of %d items" % (len(items), total)
        else:
            snap["complete"] = True
        return snap

    def _log_cleanup_read(self, tag, rid, zone, label, snap, clips):
        """A1.8: every cleanup read logs current_index, index_in_buffer and each recorded clip's index."""
        if snap is None:
            LOG.warning("%s req=%s zone=%s cleanup read (%s) failed; clips kept %s", tag, rid, zone, label,
                        list(clips))
            return
        q = snap["q"]
        absent = "absent" if snap["complete"] else "?"
        if snap.get("window") is not None:
            extra = " window=%d+%d" % snap["window"]
        else:
            extra = ""
        if not snap["complete"] and snap.get("window") is None:
            extra += " (incomplete: %s)" % snap["why"]
        elif snap.get("why"):
            extra += " (%s)" % snap["why"]
        LOG.info("%s req=%s zone=%s cleanup read (%s): state=%s current=%s current_index=%s index_in_buffer=%s "
                 "clips=%s items=%s%s", tag, rid, zone, label, q.get("state"),
                 (q.get("current_item") or {}).get("queue_item_id"), q.get("current_index"),
                 q.get("index_in_buffer"),
                 ",".join("%s@%s" % (c, snap["index_of"].get(c, absent)) for c in clips) or "-",
                 q.get("items"), extra)

    def _queue_permission_read(self, ma, queue_id, n_clips, target=None):
        """Design 4.8 A2.1: the PERMISSION read -- queue_state plus a small item window starting at T's index
        (limit = recorded clips + PERMISSION_WINDOW_EXTRA). Light enough to send the first delete inside the
        short window after play_index; presence is never concluded from it unless the window happens to cover
        the whole queue. T's index is the live current_index when T is current, else the captured one; with no
        target, the current index. -> None when the state read fails, else a snapshot like _queue_read's with
        `window` = (offset, limit)."""
        try:
            s = ma.queue_state(queue_id)
        except Exception:
            return None
        if not _ma_ok(s):
            return None
        q = s.get("result") or {}
        cur = (q.get("current_item") or {}).get("queue_item_id")
        cur_idx = q.get("current_index")
        t_idx = None
        if target is not None:
            if cur == target.get("item") and _is_int(cur_idx):
                t_idx = cur_idx
            elif _is_int(target.get("index")):
                t_idx = target["index"]
        offset = t_idx if t_idx is not None else (cur_idx if _is_int(cur_idx) else 0)
        offset = max(0, offset)
        limit = n_clips + PERMISSION_WINDOW_EXTRA
        snap = {"q": q, "index_of": {}, "complete": False, "why": None, "window": (offset, limit)}
        try:
            r = ma.queue_items(queue_id, offset=offset, limit=limit)
        except Exception as e:
            snap["why"] = "item window read failed (%r)" % (e,)
            return snap
        if not _ma_ok(r):
            snap["why"] = "item window read failed"
            return snap
        items = r.get("result") or []
        for i, it in enumerate(items):
            qiid = (it or {}).get("queue_item_id")
            if qiid:
                snap["index_of"][qiid] = offset + i
        total = q.get("items")
        snap["complete"] = offset == 0 and _is_int(total) and len(items) == total
        return snap

    def _queue_cleanup(self, ma, tag, rid, zone, queue_id, clips, label, target=None, snap=None, skip=None,
                       stop=None):
        """Design 4.8 A1.2 + A1.3 + A2.1. One PERMISSION read (queue_state + a window at T's index); every clip
        delete_permission allows is deleted straight from it -- so the first delete after a play_index goes out
        before any whole-queue read. Then, if anything was sent, ONE whole-queue VERIFICATION read decides by
        presence alone: MA's reply is logged, never trusted (it says success for a no-op, spike 4). Sending the
        permitted deletes back to back from one read is safe: each lies after the buffer, and removing one
        only shifts later items down onto indices still after it.

        `clips` is mutated: ids verified deleted, or absent from a read that covers the whole queue, are
        removed; every other id stays recorded. `skip(cid)` -> True leaves a clip alone (checked immediately
        before its delete); `stop()` -> True ends the pass (superseded). -> (verified deletes, latest read);
        the latest read is the verification read when one was made (None if it failed)."""
        if snap is None:
            snap = self._queue_permission_read(ma, queue_id, len(clips), target)
        self._log_cleanup_read(tag, rid, zone, label, snap, clips)
        if snap is None:
            return 0, None
        sent = []
        for cid in list(clips):
            if stop is not None and stop():
                LOG.info("%s req=%s zone=%s cleanup (%s) stopped: superseded; clips kept %s", tag, rid, zone,
                         label, list(clips))
                break
            if cid not in snap["index_of"]:
                if snap["complete"]:
                    clips.remove(cid)
                    LOG.info("%s req=%s zone=%s clip %s already gone from the queue", tag, rid, zone, cid)
                else:
                    LOG.info("%s req=%s zone=%s clip %s kept: not in the read window%s", tag, rid, zone, cid,
                             (" (%s)" % snap["why"]) if snap.get("why") else "")
                continue
            if skip is not None and skip(cid):
                continue
            ok, why = delete_permission(snap["q"], snap["index_of"], cid)
            if not ok:
                LOG.info("%s req=%s zone=%s clip %s kept: %s", tag, rid, zone, cid, why)
                continue
            try:
                r = ma.delete_item(queue_id, cid)
                reply = ("ok" if _ma_ok(r) else
                         "error %s" % (r.get("error_code") if isinstance(r, dict) else "no reply"))
            except Exception as e:
                reply = "raised %r" % (e,)
            sent.append((cid, reply))
        if not sent:
            return 0, snap
        ver = self._queue_read(ma, queue_id)
        self._log_cleanup_read(tag, rid, zone, label + " verify", ver, clips)
        deleted = 0
        for cid, reply in sent:
            if ver is not None and ver["complete"] and cid not in ver["index_of"]:
                deleted += 1
                clips.remove(cid)
                LOG.info("%s req=%s zone=%s clip %s deleted (%s; verified absent; reply %s)", tag, rid, zone,
                         cid, label, reply)
            else:
                LOG.warning("%s req=%s zone=%s clip %s not verified deleted (reply %s; %s); kept recorded",
                            tag, rid, zone, cid, reply,
                            "still in the queue after delete" if ver is not None and ver["complete"]
                            else "verification read %s" % ("failed" if ver is None else ver["why"]))
        return deleted, ver

    def _queue_jump_tail(self, ma, tag, rid, zone, queue_id, target, clips, t0, snap, superseded):
        """Design 4.8 A1.4 steps 4-5, after play_index(T) at clock `t0` and its immediate cleanup (`snap` = the
        latest read). Retry at +1 s and +2 s while a clip is still present and MA has not yet shown the jump
        (current = T with index_in_buffer at T); then, if a clip still lies after T inside the buffer, ONE more
        play_index(T, T's current position) and an immediate delete. A clip surviving that is logged as going
        to play after T and stays recorded. Stops as soon as `superseded()`. -> verified deletes."""
        deleted = 0

        def jump_shown(s):
            if s is None:
                return False
            cur = (s["q"].get("current_item") or {}).get("queue_item_id")
            t_idx = s["index_of"].get(target["item"])
            return cur == target["item"] and t_idx is not None and s["q"].get("index_in_buffer") == t_idx

        for off in RETRY_OFFSETS_S:
            if not clips or superseded() or jump_shown(snap):
                break
            wait = t0 + off - self._clock()
            if wait > 0:
                self._sleeper(wait)
            if superseded():
                break
            n, snap = self._queue_cleanup(ma, tag, rid, zone, queue_id, clips, "retry +%ds" % int(off),
                                          target=target, stop=superseded)
            deleted += n
        if not clips or superseded() or snap is None:
            return deleted
        q = snap["q"]
        if buffer_problem(q) is not None:
            return deleted                          # an untrustworthy buffer never justifies a second jump
        ib = q["index_in_buffer"]
        t_idx = snap["index_of"].get(target["item"])
        cur = (q.get("current_item") or {}).get("queue_item_id")
        if cur != target["item"] or t_idx is None:
            return deleted                          # MA has not applied the jump: nothing is "loaded next"
        loaded = [c for c in clips if c in snap["index_of"] and t_idx < snap["index_of"][c] <= ib]
        if not loaded:
            return deleted
        cap, _ = parse_queue_capture({"result": q}, self._clock())
        pos = cap["pos"] if cap is not None else 0.0
        seek = seek_target({"pos": pos, "duration": target.get("duration") or 0.0,
                            "seekable": target.get("seekable")})
        LOG.info("%s req=%s zone=%s clip(s) %s loaded after item %s inside the buffer; buffer-reset play_index "
                 "(seek=%s)", tag, rid, zone, loaded, target["item"], seek if seek else "skipped")
        if superseded():                            # directly before the jump: a successor owns the zone now
            LOG.info("%s req=%s zone=%s buffer reset skipped: superseded", tag, rid, zone)
            return deleted
        try:
            r = ma.play_index(queue_id, target["item"], seek_position=seek)
            if r is not None and not _ma_ok(r):
                LOG.warning("%s req=%s zone=%s buffer-reset play_index refused (%s)", tag, rid, zone,
                            r.get("error_code") if isinstance(r, dict) else "bad reply")
        except Exception as e:
            LOG.warning("%s req=%s zone=%s buffer-reset play_index raised (%r)", tag, rid, zone, e)
        if superseded():
            return deleted
        n, snap = self._queue_cleanup(ma, tag, rid, zone, queue_id, clips, "buffer reset", target=target,
                                      stop=superseded)
        deleted += n
        for c in loaded:
            if c in clips:
                LOG.warning("%s req=%s zone=%s clip %s will play after the current item", tag, rid, zone, c)
        return deleted

    def _queue_capture(self, ctx, rid, zone, my_gen):
        """Design 4.3-1: capture the interrupted item BEFORE the pause. None -> legacy mode for the turn."""
        if not self._queue_on(ctx, zone):
            return None
        queue_id = ctx.settings.queue_id
        ma = None
        stale = 0
        try:
            try:
                ma = self._ma_open(ctx)
                cap, why = parse_queue_capture(ma.queue_state(queue_id), self._clock())
                if cap is None:
                    LOG.warning("SAY req=%s zone=%s queue capture unavailable (%s); legacy replay", rid, zone, why)
                    return None
                try:
                    r = ma.queue_items(queue_id, offset=max(0, (cap["index"] or 0) - 10), limit=25)
                    window = (r.get("result") or []) if _ma_ok(r) else []
                    stale = sum(1 for x in window if is_reply_clip_uri(
                        (x.get("media_item") or {}).get("uri") or x.get("uri") or ""))
                except Exception:
                    pass
            except Exception as e:
                LOG.warning("SAY req=%s zone=%s queue capture unavailable (%r); legacy replay", rid, zone, e)
                return None
            anchor, anchor_src = capture_anchor(cap)
            qm = {"queue_id": queue_id, "cap": cap, "target": None, "clips": [], "played": [], "unrecorded": [],
                  "anchor": anchor, "unidentified": 0, "resume": "none", "seeked": False,
                  "deleted": 0, "inherited_from": None, "cleaned": False}
            # Adopt and publish in ONE _lock hold, before any enqueue: a superseded turn's cleanup re-reads
            # this record's clips before each delete, so an inherited clip must be visible as ours the moment
            # the predecessor's record stops being its own (design 4.5). Pure bookkeeping: no MA call inside.
            self._queue_adopt_target(qm, rid, zone, my_gen)
            LOG.info("SAY req=%s zone=%s queue capture: item=%s idx=%s pos=%.1f (extrapolated %.1fs) seekable=%s "
                     "stale_reply_clips=%d anchor=%d (%s) index_in_buffer=%s", rid, zone, cap["item"], cap["index"],
                     cap["pos"], cap["extrapolated"], cap["seekable"], stale, anchor, anchor_src,
                     cap.get("buffer"))
            if qm["clips"]:
                # A1.7 sweep: recorded clips A1.2 permits in this read are deleted (verified); the rest stay.
                # Permitted clips lie after the buffer, which is at or after the current index, so the capture's
                # current_index -- this turn's anchor -- is unaffected.
                try:
                    n, _ = self._queue_cleanup(ma, "SAY", rid, zone, queue_id, qm["clips"], "capture sweep",
                                               target=qm["target"])
                    qm["deleted"] += n
                except Exception as e:
                    LOG.warning("SAY req=%s zone=%s capture sweep failed (%r)", rid, zone, e)
                self._queue_publish_clips(zone, my_gen, qm)
            return qm
        finally:
            self._ma_close(ma)

    def _queue_adopt_target(self, qm, rid, zone, my_gen=None):
        """Which item this turn resumes (design 4.5-4.6). A record left by a superseded turn (live) or by a
        turn that did not resume (pending) is INHERITED when this turn's current item is one of its clips --
        or, for a live record whose turn recorded none yet, when the current item is a reply clip: that item
        is then recorded as the earlier turn's clip (it sits at that turn's anchor + 1). Capturing a real
        item clears any record.

        With `my_gen`, this turn's own record (target + every inherited or carried clip id) replaces the old
        one in the SAME _lock hold that read it. No gap exists in which the predecessor could see its
        record as still its own after we took it, nor in which our inherited clips are unpublished while
        the predecessor's superseded cleanup decides what to delete (_queue_delete_own_clips)."""
        cap = qm["cap"]
        is_clip = is_reply_clip_uri(cap["uri"])
        how = None
        with self._lock:                             # pure bookkeeping only: no MA/HA call in here
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
                how = "inherited"
            elif is_clip:
                how = "clip"
                if rec is not None and rec["clips"]:
                    # A1.7: recorded clips stay recorded for the sweep even when there is nothing to resume.
                    for cid in rec["clips"]:
                        if cid not in qm["clips"]:
                            qm["clips"].append(cid)
            else:
                if rec is not None and rec["clips"]:
                    # The popped record's clips are spent reply clips still sitting in the queue (e.g. a
                    # turn superseded after its play_index, whose own finish never runs). This turn's
                    # finish deletes them by exact id; it never deletes the current item.
                    for cid in rec["clips"]:
                        if cid not in qm["clips"]:
                            qm["clips"].append(cid)
                    how = "carried"
                qm["target"] = cap
            if my_gen is not None:
                self._queue_targets[zone] = {"gen": my_gen, "rid": rid, "target": qm["target"],
                                             "clips": list(qm["clips"]), "live": True}
        if how == "inherited":
            LOG.info("SAY req=%s zone=%s inherited resume target item=%s from req=%s (clips=%s)",
                     rid, zone, rec["target"]["item"], rec.get("rid"), rec["clips"])
        elif how == "clip":
            LOG.info("SAY req=%s zone=%s current queue item %s is a reply clip; no resume target",
                     rid, zone, cap["item"])
        elif how == "carried":
            LOG.info("SAY req=%s zone=%s carried %d clip(s) from req=%s", rid, zone, len(rec["clips"]),
                     rec.get("rid"))

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
        cur_idx, cur_is_clip, cur_buf = None, False, None
        try:
            ma = self._ma_open(ctx)
            s = ma.queue_state(qm["queue_id"])
            if _ma_ok(s):
                q = s.get("result") or {}
                ci = q.get("current_item") or {}
                cur_idx = q.get("current_index")
                cur_buf = q.get("index_in_buffer")
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
            searched = qm["anchor"]                  # log the anchor that was searched, not the updated one
            if cur_is_clip and cur_idx is not None:
                qm["anchor"] = cur_idx              # the next clip is inserted after this one
            LOG.warning("SAY req=%s zone=%s clip=%s queue_item UNIDENTIFIED (%s; anchor=%s current_index=%s "
                        "index_in_buffer=%s)", rid, zone, clip, why, searched, cur_idx, cur_buf)
            return
        if qid not in qm["clips"]:
            qm["clips"].append(qid)
        qm["anchor"] = idx
        self._queue_publish_clips(zone, my_gen, qm)
        LOG.info("SAY req=%s zone=%s clip=%s queue_item=%s", rid, zone, clip, qid)

    def _queue_confirm(self, ma, queue_id, item, poll_secs, tries=None):
        """Poll (bounded, design 4.4) until `item` is current. -> (seen, any_read_ok).

        `tries=None` uses the budget-derived count; a caller that already knows play_index came
        back with a KNOWN error (e.g. an error_code) passes `tries=1` -- polling the full
        CONFIRM_BUDGET_S in that case only delays the URI fallback by seconds of silence for an
        outcome that is already decided."""
        if ma is None:
            return False, False
        reads_ok = False
        if tries is None:
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

    def _queue_resume(self, ctx, rid, zone, qm, source_id, call_timeout, superseded=None):
        """Design 4.4 decision table. True when the source is (or may be) playing again."""
        t = qm["target"]
        qid = qm["queue_id"]
        seek = seek_target(t)
        poll_secs = max(int(getattr(ctx.settings, "say_poll_ms", 500)) / 1000.0, 0.05)
        known_clips = list(qm["clips"])              # clips we already knew BEFORE this resume
        qm["resume"] = "attempted"
        qm["cleaned"] = True                         # A1.4 owns this turn's deletes; _queue_finish only books
        called, why, seen, reads_ok = "ok", None, False, False
        is_superseded = superseded if superseded is not None else (lambda: False)
        t0, snap = None, None
        ma = None
        try:
            try:
                ma = self._ma_open(ctx)
            except Exception as e:
                called, why = "error", "connect failed (%r)" % (e,)   # never sent: a KNOWN failure
            if ma is not None:
                try:
                    r = ma.play_index(qid, t["item"], seek_position=seek)
                    if r is None:
                        # No reply is not a refusal: the command was sent and may have landed.
                        called, why = "raised", "play_index got no reply"
                    elif not _ma_ok(r):
                        called = "error"
                        why = "ma error %s" % (r.get("error_code") if isinstance(r, dict) else "bad reply")
                except Exception as e:
                    called, why = "raised", "play_index raised (%r)" % (e,)
                t0 = self._clock()
                if called != "error" and qm["clips"] and not is_superseded():
                    # A1.4-3: delete IMMEDIATELY, before the confirmation poll. MA honours a delete only
                    # while the clip lies after its buffer, and play_index just reset the buffer to T --
                    # once T starts playing the buffer moves on to the next item (spike 4, 3.3-4/5).
                    try:
                        n, snap = self._queue_cleanup(ma, "SAY", rid, zone, qid, qm["clips"], "after play_index",
                                                      target=t, stop=is_superseded)
                        qm["deleted"] += n
                    except Exception as e:
                        LOG.warning("SAY req=%s zone=%s cleanup after play_index failed (%r)", rid, zone, e)
                # A KNOWN error_code means the outcome is already decided -- one read is enough to
                # learn whether it landed anyway; polling the full budget only delays the URI
                # fallback (design 4.4 peer review finding).
                confirm_tries = 1 if called == "error" else None
                seen, reads_ok = self._queue_confirm(ma, qid, t["item"], poll_secs, tries=confirm_tries)
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
            # §4.3-7/§4.4: a turn superseded during the play_index + confirm poll no longer owns the
            # zone -- its successor's clip is not ours to displace. Skip the settle read/re-resume
            # entirely rather than let it race the successor's own turn.
            if superseded is None or not superseded():
                self._queue_settle(ctx, rid, zone, qm, seek, poll_secs, known_clips, superseded=superseded)
            if qm["clips"] and t0 is not None and not is_superseded():
                # A1.4-4/5 on a fresh connection: the confirm/settle phase may have held MA for seconds.
                tail = None
                try:
                    tail = self._ma_open(ctx)
                    qm["deleted"] += self._queue_jump_tail(tail, "SAY", rid, zone, qid, t, qm["clips"], t0, snap,
                                                           is_superseded)
                except Exception as e:
                    LOG.warning("SAY req=%s zone=%s clip cleanup retries failed (%r)", rid, zone, e)
                finally:
                    self._ma_close(tail)
            return True
        if outcome == "unknown":
            LOG.error("SAY req=%s zone=%s resume unknown (%s); not replaying", rid, zone, why)
            return False
        LOG.warning("SAY req=%s zone=%s resume by queue failed (%s); URI fallback", rid, zone, why)
        if source_id and not is_reply_clip_uri(source_id):
            try:
                self._say_call(ctx, rid, zone, "music_assistant", "play_media",
                               {"entity_id": zone, "media_id": source_id}, timeout=call_timeout)
                return True
            except Exception as e:
                LOG.warning("SAY req=%s zone=%s URI fallback failed (%r); source NOT resumed", rid, zone, e)
        return False

    def _queue_after_raised_enqueue(self, ctx, rid, zone, qm, one_uri, one_key, one_clip, opts, superseded):
        """Design 4.3-5: an enqueue whose REST call raised may still have landed. If the clip is current, wait
        it out (never cut the answer off); otherwise carry on -- the record step or the settle check finds it.
        gave_up is "unreadable", NOT a denial: the clip may have played, and likely_silent must not claim the
        room heard nothing (the AN-01 honesty rule: the start poll's "unreadable" outcome in
        _play_clip_and_wait, and the likely_silent computation in _say)."""
        out = {"started": False, "issued": True, "clip": one_clip, "ended": False, "gave_up": "unreadable"}
        ma = None
        cur = None
        cur_index = None
        try:
            ma = self._ma_open(ctx)
            s = ma.queue_state(qm["queue_id"])
            if _ma_ok(s):
                res = s.get("result") or {}
                cur = res.get("current_item") or {}
                cur_index = res.get("current_index")
        except Exception as e:
            LOG.warning("SAY req=%s zone=%s after raised enqueue: read failed (%r)", rid, zone, e)
        finally:
            self._ma_close(ma)
        # Identify by the same exact rule as anchored_clip (design 4.3-4): URI equality after
        # wrapper strip, or an equal name when the item carries no URI -- not a looser containment
        # check. A window of one item anchored at its own index makes anchored_clip apply that rule
        # here too, rather than duplicating it.
        landed = False
        if cur:
            if cur_index is not None:
                qid, _, _ = anchored_clip([cur], cur_index, cur_index - 1, one_uri)
                landed = qid is not None and qid == cur.get("queue_item_id")
            else:
                landed = clip_uri_of(cur) == one_uri
        if landed:
            return self._play_clip_and_wait(ctx, rid, zone, one_uri, one_key, one_clip, opts, superseded,
                                            enqueue="play", issue=False, other_item_s=self._other_item_s(ctx))
        return out

    def _queue_settle(self, ctx, rid, zone, qm, seek, poll_secs, known_clips, superseded=None):
        """Design 4.3-7: one settle re-read after a poll interval. A late-landing enqueue can put a NEW reply
        clip in front of the song; if so, record it (exact + anchored) and resume ONCE more. A clip we already
        knew before the resume just means MA is lagging -- re-resuming would restart the song (peer review
        finding 1). A turn superseded by the time settle runs no longer owns the zone -- displacing whatever
        its successor put there would cut the successor's own reply off (design 4.3-7/4.4)."""
        if superseded is not None and superseded():
            return
        self._sleeper(poll_secs)
        t = qm["target"]
        ma = None
        try:
            if superseded is not None and superseded():
                return
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
            identified = False
            if idx is not None and idx >= 0:
                off = max(0, idx - 1)
                r = ma.queue_items(qm["queue_id"], offset=off, limit=2)
                items = (r.get("result") or []) if _ma_ok(r) else []
                for played in qm["played"]:
                    got, _, _ = anchored_clip(items, off, idx - 1, played)
                    if got == cid:
                        if cid not in qm["clips"]:
                            qm["clips"].append(cid)
                        identified = True
                        break
            if not identified:
                qm["unidentified"] += 1
                LOG.warning("SAY req=%s zone=%s settle: late clip %s UNIDENTIFIED; not recorded", rid, zone, cid)
            why = None
            try:
                r = ma.play_index(qm["queue_id"], t["item"], seek_position=seek)
                if r is not None and not _ma_ok(r):
                    why = "ma error %s" % (r.get("error_code") if isinstance(r, dict) else "bad reply")
            except Exception as e:
                r, why = None, "play_index raised (%r)" % (e,)      # may still have landed: confirm
            seen, _ = self._queue_confirm(ma, qm["queue_id"], t["item"], poll_secs,
                                          tries=1 if (r is not None and why) else None)
            if seen:
                LOG.warning("SAY req=%s zone=%s settle: new reply clip %s displaced item %s; resumed again",
                            rid, zone, cid, t["item"])
            else:
                # The late clip may still be current: an unconfirmed outcome keeps a pending record
                # (with the clip) so a later "resume" can finish the job (design 4.6).
                qm["resume"] = "unconfirmed"
                LOG.warning("SAY req=%s zone=%s settle: new reply clip %s displaced item %s; re-resume "
                            "UNCONFIRMED (%s)", rid, zone, cid, t["item"], why or "not seen")
        except Exception as e:
            LOG.warning("SAY req=%s zone=%s settle check failed (%r)", rid, zone, e)
        finally:
            self._ma_close(ma)

    def _refresh_target_pos(self, qm, q):
        """Design 4.8 A2.3: a read with T current is fresher than the capture -- take the position from it
        (extrapolated per 4.3-1). qm["target"] is replaced, never mutated: it may be a record's shared dict."""
        cap, _ = parse_queue_capture({"result": q}, self._clock())
        if cap is not None and qm["target"] is not None and cap["item"] == qm["target"]["item"]:
            qm["target"] = dict(qm["target"], pos=cap["pos"])

    def _queue_not_playing_cleanup(self, ctx, rid, zone, qm, superseded, my_gen=None):
        """Design 4.8 A1.5 as amended by A2.2: the queue was NOT playing at capture (the reply to "pause", or a
        question while paused/idle). After the clip, WATCH the queue for up to REPAUSE_WATCH_S at say_poll_ms --
        MA restarts a paused station by itself ~1 s after the clip (spike 4 / 3.3-3), later than one read:
          - exact T current and `playing` -> media_pause; the clips stay in the pending record;
          - superseded -> stop at once, nothing done;
          - any item other than T or a recorded clip current -> stop at once: no pause, no play_index, only
            deletes A1.2 permits, verified.
        When the watch ends with nothing to pause, the last read decides: on a recorded clip (idle on it,
        3.3-2) or on T not playing -> pending record; anything else -> permitted deletes. Each read with T
        current refreshes the pending position (A2.3). Owns this turn's deletes (_queue_finish only books).

        A2.2a: "superseded" here means a newer turn took over -- the reply generation advanced, OR (with
        `my_gen`) the zone's queue record is no longer this turn's: a voice "resume" or new playback
        (note_playback) cleared or replaced it. A watch that paused T after that would undo the user's resume.
        A current item that is a reply clip we did not identify is still ours and does not end the watch."""
        def taken_over():
            if superseded():
                return True
            if my_gen is None:
                return False
            with self._lock:
                rec = self._queue_targets.get(zone)
                return rec is None or rec.get("gen") != my_gen

        if taken_over():
            return
        qm["cleaned"] = True
        t = qm["target"]
        qid = qm["queue_id"]
        poll_secs = max(int(getattr(ctx.settings, "say_poll_ms", 500)) / 1000.0, 0.05)
        ma = None
        try:
            ma = self._ma_open(ctx)
            last = None
            waited = 0.0
            while True:
                if taken_over():
                    LOG.info("SAY req=%s zone=%s re-pause watch stopped: a newer turn took over", rid, zone)
                    return
                q = None
                try:
                    s = ma.queue_state(qid)
                    if _ma_ok(s):
                        q = s.get("result") or {}
                except Exception:
                    q = None
                if q is not None:
                    last = q
                    ci = q.get("current_item") or {}
                    cur = ci.get("queue_item_id")
                    cur_uri = (ci.get("media_item") or {}).get("uri") or ci.get("uri") or ""
                    if t is not None and cur == t["item"]:
                        self._refresh_target_pos(qm, q)
                        if q.get("state") == "playing":
                            if taken_over():            # immediately before the pause (A2.2a)
                                LOG.info("SAY req=%s zone=%s re-pause skipped: a newer turn took over", rid, zone)
                                return
                            LOG.info("SAY req=%s zone=%s queue restarted item %s by itself after the reply "
                                     "(watch %.1fs); pausing it again (clips stay pending %s)", rid, zone, cur,
                                     waited, qm["clips"])
                            self._say_call(ctx, rid, zone, "media_player", "media_pause", {"entity_id": zone})
                            return
                    elif (cur is not None and cur not in qm["clips"]
                          and not is_reply_clip_uri(cur_uri)):   # an unidentified reply clip is still ours
                        LOG.info("SAY req=%s zone=%s re-pause watch: another item %s is current; no pause",
                                 rid, zone, cur)
                        break
                if waited + OTHER_ITEM_EPSILON_S >= REPAUSE_WATCH_S:
                    break
                self._sleeper(poll_secs)
                waited += poll_secs
            if last is None:
                self._log_cleanup_read("SAY", rid, zone, "after reply, not playing", None, qm["clips"])
                return
            cur = (last.get("current_item") or {}).get("queue_item_id")
            if t is not None and cur == t["item"]:
                # Not playing, so nothing to re-pause; A1.5 "anything else": permitted deletes only. T itself
                # stays the pending target (an un-pause in place resumes it once no clip is left).
                LOG.info("SAY req=%s zone=%s item %s current but %s after the reply; not paused", rid, zone, cur,
                         last.get("state"))
            if cur is not None and cur in qm["clips"]:
                LOG.info("SAY req=%s zone=%s clip left as current item %s (still current); pending resume keeps it",
                         rid, zone, cur)
                return
            n, _ = self._queue_cleanup(ma, "SAY", rid, zone, qid, qm["clips"], "after reply, not playing",
                                       target=t, stop=taken_over)
            qm["deleted"] += n
        except Exception as e:
            LOG.warning("SAY req=%s zone=%s clip cleanup (not playing) failed (%r)", rid, zone, e)
        finally:
            self._ma_close(ma)

    def _queue_finish(self, ctx, rid, zone, qm, my_gen):
        """Design 4.3-8 as amended by 4.8: delete (A1.2-permitted, A1.3-verified) whatever recorded clips no
        earlier step of this turn already cleaned up, then keep the zone record per outcome. A clip that could
        not be deleted stays recorded -- in the pending record, or in a target-less record after a confirmed
        resume -- so the next turn's capture sweep (A1.7) can retry it."""
        ma = None
        try:
            if qm["clips"] and not qm.get("cleaned"):
                ma = self._ma_open(ctx)
                n, _ = self._queue_cleanup(ma, "SAY", rid, zone, qm["queue_id"], qm["clips"], "finish",
                                           target=qm["target"])
                qm["deleted"] += n
        except Exception as e:
            LOG.warning("SAY req=%s zone=%s clip cleanup failed (%r)", rid, zone, e)
        finally:
            self._ma_close(ma)
        with self._lock:
            rec = self._queue_targets.get(zone)
            if rec is not None and rec.get("gen") == my_gen:
                # design 4.6: only no-resume / unconfirmed / unknown leave a pending record. A
                # "fallback_uri" outcome already REPLACED the queue (ha_play_media/play_media), so
                # the captured item is gone -- keeping a pending record for it would resume nothing.
                if qm["resume"] == "fallback_uri" or not (qm["clips"] or qm["target"] is not None):
                    del self._queue_targets[zone]
                elif qm["resume"] == "confirmed" or qm["target"] is None:
                    if qm["clips"]:
                        # Nothing to resume, but clips still sit in the queue: keep them for the sweep.
                        rec["target"] = None
                        rec["live"] = False
                        rec["clips"] = list(qm["clips"])
                    else:
                        del self._queue_targets[zone]
                else:
                    # Did not resume, or resume unconfirmed/unknown: a later "resume" continues from here.
                    # The target carries any position refreshed from a read with T current (A2.3).
                    rec["live"] = False
                    rec["target"] = qm["target"]
                    rec["clips"] = list(qm["clips"])
        if qm["target"] is not None and qm["resume"] not in ("confirmed", "fallback_uri"):
            LOG.info("SAY req=%s zone=%s pending resume recorded (item=%s clips=%s)",
                     rid, zone, qm["target"]["item"], qm["clips"])
        elif qm["clips"] and qm["resume"] != "fallback_uri":
            LOG.info("SAY req=%s zone=%s clips kept recorded for the next sweep: %s", rid, zone, qm["clips"])

    def _queue_successor_clips(self, zone, my_gen):
        """-> (rid, frozenset of clip ids) owned by the zone's CURRENT record when it is not ours, else
        (None, empty). Read under _lock and returned as a copy: the caller releases the lock before any
        MA call."""
        with self._lock:
            rec = self._queue_targets.get(zone)
            if rec is None or rec.get("gen") == my_gen:
                return None, frozenset()
            return rec.get("rid"), frozenset(rec.get("clips") or ())

    def _queue_delete_own_clips(self, ctx, rid, zone, qm, my_gen=None):
        """A superseded turn whose record a successor took (design 4.5): the resume is no longer ours,
        but the clips we RECORDED are still ours to remove -- unless the successor now owns one. A
        successor that captured our clip as its current item INHERITED it (and anchors its own clips on
        its position), and one that captured a real item CARRIED it; either way it identifies, resumes
        and deletes that clip through its own finish. Deleting it here would shift the successor's clips
        under its anchored record step and orphan them. So the successor's clip set is re-read under
        _lock immediately before EACH delete, and a clip in it is left alone. Everything else follows
        A1.2/A1.3 (design 4.8): only permitted deletes, each verified by presence; a failed read deletes
        nothing. A failed delete here is logged, never fatal."""
        if not qm["clips"]:
            return

        def successor_owns(cid):
            owner, owned = self._queue_successor_clips(zone, my_gen)   # lock released before MA
            if cid in owned:
                LOG.info("SAY req=%s zone=%s clip %s owned by successor req=%s; not deleting",
                         rid, zone, cid, owner)
                return True
            return False

        ma = None
        try:
            ma = self._ma_open(ctx)
            n, _ = self._queue_cleanup(ma, "SAY", rid, zone, qm["queue_id"], qm["clips"], "superseded",
                                       target=qm["target"], skip=successor_owns)
            qm["deleted"] += n
        except Exception as e:
            LOG.warning("SAY req=%s zone=%s superseded: own clip cleanup failed (%r)", rid, zone, e)
        finally:
            self._ma_close(ma)
        LOG.info("SAY req=%s zone=%s superseded; successor owns the resume (own clips deleted=%d left=%s)",
                 rid, zone, qm["deleted"], qm["clips"])

    def _queue_superseded_exit(self, ctx, rid, zone, qm, my_gen):
        """Design 4.5: a successor that CAPTURED owns the resume. If none did -- e.g. an announcement claimed
        the generation and aborted before reaching _say -- this turn's record would stay live forever and
        nobody would resume: record any unrecorded clips and turn it into a pending resume."""
        with self._lock:
            rec = self._queue_targets.get(zone)
            mine = rec is not None and rec.get("gen") == my_gen
        if not mine:
            self._queue_delete_own_clips(ctx, rid, zone, qm, my_gen)
            return
        for uri in list(qm["unrecorded"]):
            self._queue_record_clip(ctx, rid, zone, qm, uri, self._clip_id(uri), my_gen)
        with self._lock:
            rec = self._queue_targets.get(zone)
            if rec is not None and rec.get("gen") == my_gen:
                rec["live"] = False
                rec["clips"] = list(qm["clips"])
        LOG.info("SAY req=%s zone=%s superseded with no successor capture; pending resume recorded", rid, zone)

    def _say(self, ctx, resolved, rid):
        zone = resolved["zone"]; uri = resolved["uri"]
        # Fingerprint the NORMALISED uri, so the turn-level id matches the id the clip loop derives
        # for this same clip. HA's tts_proxy url sits on a different host than say_internal_base, so
        # hashing the raw uri here made one turn log TWO ids and defeated the correlation _clip_id
        # exists for (observed live at G3: clip=58bf0413 on the start line, clip=47dcf789 on the
        # finish-poll line, same clip).
        #
        # Normalising here rather than pushing this id down into the loop is deliberate: the loop's
        # per-clip ids must stay DISTINCT, or a chime and a message become indistinguishable.
        clip = self._clip_id(self._normalise_uri(uri, getattr(ctx.settings, "say_internal_base", "")))

        # Plan decision (e): a pure media command is confirmed by the ACTION, not by speech. Playing
        # the confirmation clip here would replace the stream the same turn just started (and the
        # capture below would find it still starting, so nothing would replay it) -- the command
        # would report success and leave silence.
        if (bool(getattr(ctx.settings, "say_skip_on_fresh_playback", True))
                and resolved.get("skip_on_fresh_playback", True)):
            with self._lock:
                turn = self._turns.get(zone) or {}
                started = turn.get("playback")
            if started:
                LOG.info("SAY req=%s zone=%s clip=%s SKIPPED: this turn started %s -- the reply would "
                         "replace it (media command is confirmed by the action)",
                         rid, zone, clip, self._redact_uri(started))
                return cr.ok(self.name, rid, "Said.", spoken_text=None,
                             metadata={"said": False, "reply_started": False, "likely_silent": False,
                                        "replayed": False, "superseded": False,
                                        "reason": "fresh_playback", "zone": zone})

        # 1. capture before-state (best-effort; a read blip must not swallow the reply)
        try:
            before = ctx.ha.get_entity_state(zone) or {}
        except Exception as e:
            LOG.warning("SAY req=%s zone=%s capture read failed (%r); proceeding with empty capture", rid, zone, e)
            before = {}
        was_playing = before.get("state") == "playing"
        battrs = before.get("attributes") or {}
        source_id = battrs.get("media_content_id")
        prev_volume = battrs.get("volume_level")
        self.remember_source(zone, source_id)       # music started outside a turn is resumable too

        # Mirror of the fresh-playback guard above, for the opposite direction: if this turn PAUSED
        # the zone, the capture ran before HA propagated `paused` and still says "playing". Replaying
        # on that stale reading restarts the stream the user just stopped -- the confirmation undoes
        # the command it is confirming. The turn's intent outranks the capture.
        if (bool(getattr(ctx.settings, "say_skip_replay_on_stop", True))
                and was_playing and self._turn_stopped(zone)):
            LOG.info("SAY req=%s zone=%s clip=%s this turn stopped playback -- the reply will not "
                     "replay the source", rid, zone, clip)
            was_playing = False

        # 2. barge-in gen-id: bump this zone's generation; a later say() will bump it again and
        #    supersede us -- we then abort remaining steps rather than fight over the finish.
        #    Same critical section resolves and publishes the restore baseline: capturing it HERE
        #    (not at the restore step) means a mid-reply snapshot discard cannot strip it, and
        #    publishing it in _replies makes this zone reply-owned for _restore/_duck.
        supplied_gen = resolved.get("gen")
        with self._lock:
            if supplied_gen is not None:
                # A pre-claimed gen is STALE by the time we see it: the caller spent up to ~17s on
                # the mic state capture, the switch write and the confirmation (design 9.2, steps
                # F-G; the two URL resolutions happen at C/D, before the claim, so they are outside
                # this window). If a turn arrived in that gap, publishing our marker would overwrite
                # ITS ownership -- the ratchet the S1b-2 ownership decision exists to prevent, where
                # a superseded turn hands back its own stale baseline over the live one.
                #
                # The check and the publish are ONE critical section on purpose. Checking outside
                # the lock is the same race one instruction later.
                #
                # `is None`, not a truthiness test: a supplied 0 is a bogus claim that must abort,
                # and `if supplied_gen:` would fall through to claiming our own and play the whole
                # announcement instead.
                if self._say_gen.get(zone) != supplied_gen:
                    LOG.info("SAY req=%s zone=%s adoption aborted: gen %s is stale (now %s)",
                             rid, zone, supplied_gen, self._say_gen.get(zone))
                    # A literal cr.ok, not superseded_result(): that closure is defined further
                    # down. The metadata shape is identical. Nothing has been published yet, so
                    # there is nothing to release -- and the caller's own finally still unmutes.
                    return cr.ok(self.name, rid, "Said.", spoken_text=None,
                                 metadata={"said": False, "reply_started": False,
                                           "likely_silent": False, "replayed": False,
                                           "superseded": True, "zone": zone})
                # Adopt the claim rather than claiming again: a second bump would leave the caller's
                # own superseded() comparing against a generation it does not hold, so every later
                # check would read as superseded and the turn would abort mid-sequence.
                my_gen = supplied_gen
            else:
                my_gen = self._say_gen.get(zone, 0) + 1
                self._say_gen[zone] = my_gen
            baseline = self._reply_baseline(zone, prev_volume)
            my_snap = self._snaps.get(zone)
            # If the zone is already sitting somewhere WE did not put it, a third party moved it
            # during the duck (the ceiling volume_up/volume_down scripts write the player directly).
            # Their level is the baseline now -- restoring our pre-duck capture would silently undo
            # the user's volume change, which is what made "volume down" look like a no-op.
            if my_snap is not None and prev_volume is not None:
                applied = my_snap.get("target")
                if applied is not None and abs(prev_volume - applied) > 0.01:
                    LOG.info("SAY req=%s zone=%s volume moved to %s during the duck (not ours, "
                             "last wrote %s); adopting it as the baseline", rid, zone, prev_volume, applied)
                    baseline = prev_volume
            # Identity of the snapshot our baseline came from. We may only ever retire THAT one:
            # a snapshot belonging to a later turn must not be torn down by us.
            my_snap_ts = my_snap.get("ts") if my_snap is not None else None
            # The duck floor as it stands NOW: step 4 overwrites snap["target"] with reply_volume,
            # so the restore check below must use this captured copy, not re-read the snapshot.
            duck_floor = my_snap.get("target") if my_snap is not None else None
            # A caller that supplied per-clip finish timeouts knows its own span, so it
            # publishes it rather than letting _reply_active guess from the single-clip formula. A
            # clip-count multiplier was the first idea and is worse: with per-clip timeouts the
            # clips are different sizes, so clips x (start + reply) over-counts an announcement by
            # roughly 3x, which would keep a crashed turn owning the zone far too long.
            marker_budget = None
            if resolved.get("finish_timeouts"):
                m_call = int(getattr(ctx.settings, "say_call_timeout_ms", 20000)) / 1000.0
                m_start = int(getattr(ctx.settings, "say_start_timeout_ms", 5000)) / 1000.0
                per_clip = sum(float(t) + m_start + m_call
                               for t in resolved["finish_timeouts"])
                # pause, raise, the clips, the restore, the replay
                marker_budget = 5.0 + 5.0 + per_clip + 5.0 + m_call
            self._replies[zone] = {"gen": my_gen, "baseline": baseline,
                                   "ts": self._clock(), "rid": rid,
                                   "marker_budget_s": marker_budget}

        def superseded():
            return self._say_gen.get(zone) != my_gen

        def retire_snapshot(my_snap_ts):
            # Retire the duck snapshot + its dead-man once we have put the zone back on the
            # baseline. ONLY ours (ts match): a duck that landed during the reply owns the next
            # turn's baseline and dead-man, and must survive us.
            with self._lock:
                snap = self._snaps.get(zone)
                if snap is not None and snap.get("ts") == my_snap_ts:
                    self._cancel_timer(snap)
                    del self._snaps[zone]

        def release_reply():
            # Release reply ownership -- but only if it is still ours: a superseding say has
            # already published its own marker and owns the zone now.
            with self._lock:
                reply = self._replies.get(zone)
                if reply is not None and reply.get("gen") == my_gen:
                    del self._replies[zone]
                    self._turns.pop(zone, None)      # our reply was the turn; it ends here

        def superseded_result():
            return cr.ok(self.name, rid, "Said.", spoken_text=None,
                         metadata={"said": False, "reply_started": False, "likely_silent": False,
                                    "replayed": False, "superseded": True, "zone": zone})

        # From here on the zone is reply-owned, so every exit path must hand it back.
        owns_restore = bool(getattr(ctx.settings, "say_owns_restore", True))
        pending_restore = [False]               # True once the zone sits at reply_volume and we still
                                               # owe it a restore (list: rebound in the finally block)
        paused_by_us = [False]                  # we silenced the outgoing music before raising volume
        volume_restore = ["deferred_to_deadman"]  # design 9.7. Answers "is a volume restore still
                                                #   outstanding?" -- flipped to "restored" the
                                                #   moment the obligation is discharged, whether by
                                                #   putting the zone back on its baseline or by
                                                #   deliberately keeping a level a third party set.
                                                #   There is deliberately no "failed" value: the
                                                #   result is serialised before the timer can run,
                                                #   so a terminal failure cannot reach it.
        queue_may_be_replaced = [False]         # design 8.3a: claimed BEFORE each play_media.
                                                #   "We may have changed the queue" is the only
                                                #   thing we can honestly know -- a landed-but-
                                                #   unacknowledged play changes it while any
                                                #   success-gated flag stays False. So a clear flag
                                                #   has to mean the turn died before REACHING a
                                                #   play_media at all.
        replay_done = [False]                   # step 9 already put the source back
        qm = None
        queue_done = [False]
        try:
            # MR-08c: capture the interrupted queue item BEFORE the pause and any enqueue (design 4.3-1).
            qm = self._queue_capture(ctx, rid, zone, my_gen)
            # HA and MA can disagree just after a play_index: HA still reports the spent (idle) clip
            # while MA already plays the song. MA's queue is the authority in queue mode -- trusting
            # HA here would skip the pause and the resume and leave the zone idle on our new clip.
            # The stopped-turn guard above still wins: a turn that paused must not be resumed.
            if (qm is not None and not was_playing and qm["cap"]["state"] == "playing"
                    and not (bool(getattr(ctx.settings, "say_skip_replay_on_stop", True))
                             and self._turn_stopped(zone))):
                LOG.info("SAY req=%s zone=%s HA reported %s but the MA queue is playing; treating as playing",
                         rid, zone, before.get("state"))
                was_playing = True

            # 3. normalise the reply URI to the MA-reachable internal base
            norm_uri = self._normalise_uri(uri, getattr(ctx.settings, "say_internal_base", ""))

            poll_secs = max(int(getattr(ctx.settings, "say_poll_ms", 500)) / 1000.0, 0.05)
            start_timeout = int(getattr(ctx.settings, "say_start_timeout_ms", 5000)) / 1000.0
            reply_timeout = int(getattr(ctx.settings, "say_reply_timeout_ms", 30000)) / 1000.0
            # `is None`, never `or`: 0.0 is a legitimate override that `or` would silently
            # discard, restoring the ordinary reply volume and making a deliberately silent clip
            # audible.
            override = resolved.get("volume_override")
            reply_volume = (float(override) if override is not None
                            else float(getattr(ctx.settings, "reply_volume", 0.40)))
            call_timeout = int(getattr(ctx.settings, "say_call_timeout_ms", 20000)) / 1000.0

            LOG.info("SAY start req=%s zone=%s clip=%s baseline=%s prev=%s reply_volume=%s",
                     rid, zone, clip, baseline, prev_volume, reply_volume)
            self._warn_if_double_speak(ctx, zone, rid, clip)

            # 4. set reply volume, then 5. play_media (reply).
            #    Raising the volume BEFORE the clip replaces the stream means the ~1s of still-playing
            #    (ducked) music gets played at reply_volume -- the audible "bump" the operator hears
            #    just before every announcement. Silence the outgoing music first so the raise cannot
            #    be heard. The queue is replaced by the clip anyway, and the source is replayed at the
            #    end either way, so this costs nothing extra.
            if was_playing and bool(getattr(ctx.settings, "say_pause_before_reply", True)):
                try:
                    self._say_call(ctx, rid, zone, "media_player", "media_pause", {"entity_id": zone})
                    paused_by_us[0] = True
                except Exception:
                    pass                        # best-effort: a failed pause only costs us the bump
            # Claim the restore obligation BEFORE issuing the write. Setting the flag first can
            # only cause a REDUNDANT restore to a value the zone already holds -- harmless and
            # idempotent. Setting it second can cause a MISSING restore, which is neither: a lost
            # acknowledgement (the write lands, the response does not) stranded the zone at the
            # reply volume, and for an announcement there is no duck snapshot and therefore no
            # volume dead-man, so this finally is the only net (design 8.4c).
            pending_restore[0] = True
            if owns_restore:
                with self._lock:
                    snap = self._snaps.get(zone)
                    if snap is not None and snap.get("ts") == my_snap_ts:
                        # Keep the duck's "last value we wrote" in step with what we are ABOUT to
                        # write, so a turn that dies mid-write leaves a device a later reconciler
                        # agrees with -- rather than reading our reply volume as a human override,
                        # keeping it, and discarding the baseline (the ratchet).
                        snap["target"] = reply_volume
            if owns_restore and my_snap_ts is None and baseline is not None:
                # No duck snapshot means _arm_timer never ran, so max_duck_timeout is not our net
                # (design 8.4c/9.7). Armed BEFORE the write for the same reason the obligation is
                # claimed before it: a write that lands without being acknowledged, whose finalizer
                # retry then also fails, is exactly the case this exists for.
                rec = {"gen": my_gen, "baseline": baseline, "target": reply_volume,
                       "rid": rid, "ts": self._clock(), "timer": None}
                with self._lock:
                    self._vol_recovery[zone] = rec
                t = self._timer_factory(self._volume_recovery_secs(ctx), self._volume_recovery,
                                        [ctx, zone, my_gen, 0])
                rec["timer"] = t
                t.start()
            self._say_call(ctx, rid, zone, "media_player", "volume_set",
                           {"entity_id": zone, "volume_level": reply_volume})
            # 5-7. play the clip SEQUENCE and wait each one out (design 8.1-8.3). One clip is
            # just the degenerate case, which is how say/say_text keep their existing behaviour.
            #
            # Every clip's match_key is its full normalised URI. Design 8.2 specified a path-only
            # key for the chime on the assumption that MA strips the query; AN-1 measured the query
            # as PRESERVED, so no clip needs a different rule. The `match_keys` list stays in the
            # interface anyway -- it costs nothing, keeps per-clip matching explicit rather than
            # implied, and leaves a seam if MA's wrapping ever changes.
            #
            # deadline_from_now is absent for say/say_text, which keeps them on accumulated-sleep
            # bounding: design 6.5 preserves that deliberately, since converting a live, proven path
            # to wall-clock deadlines would be a timing change with no defect motivating it. One
            # deadline spans the WHOLE sequence -- a two-clip announcement must not get two budgets.
            uris = resolved.get("uris") or [uri]
            match_keys = resolved.get("match_keys") or uris
            finish_timeouts = resolved.get("finish_timeouts") or ([reply_timeout] * len(uris))
            dl = resolved.get("deadline_from_now")
            deadline = (self._clock() + float(dl)) if dl is not None else None
            internal_base = getattr(ctx.settings, "say_internal_base", "")
            base_opts = {"start_timeout": start_timeout, "call_timeout": call_timeout,
                         "poll_secs": poll_secs,
                         "blank_grace": int(getattr(ctx.settings, "say_blank_cid_grace_ms", 4000)) / 1000.0,
                         "deadline": deadline,
                         "floor": int(getattr(ctx.settings, "announce_min_call_timeout_ms", 500)) / 1000.0}
            clip_results = []
            for i, one in enumerate(uris):
                one_uri = self._normalise_uri(one, internal_base)
                one_key = self._normalise_uri(match_keys[i], internal_base)
                one_clip = self._clip_id(one_uri)
                opts = dict(base_opts)
                opts["finish_timeout"] = finish_timeouts[i]
                queue_may_be_replaced[0] = True
                if qm is not None:
                    try:
                        res = self._play_clip_and_wait(
                            ctx, rid, zone, one_uri, one_key, one_clip, opts, superseded, enqueue="play",
                            other_item_s=self._other_item_s(ctx))
                    except Exception as e:
                        LOG.warning("SAY req=%s zone=%s clip=%s enqueue raised (%r); checking the queue",
                                    rid, zone, one_clip, e)
                        res = self._queue_after_raised_enqueue(ctx, rid, zone, qm, one_uri, one_key,
                                                               one_clip, opts, superseded)
                    qm["played"].append(one_uri)
                    if superseded():
                        qm["unrecorded"].append(one_uri)   # a successor may own the queue now
                    else:
                        self._queue_record_clip(ctx, rid, zone, qm, one_uri, one_clip, my_gen)
                else:
                    res = self._play_clip_and_wait(ctx, rid, zone, one_uri, one_key, one_clip,
                                                   opts, superseded)
                clip_results.append({"clip": one_clip, "started": res["started"],
                                     "issued": res["issued"], "ended": res["ended"],
                                     "gave_up": res["gave_up"]})
                if superseded():
                    return superseded_result()
            # reply_started tracks the LAST clip -- the message. Design 8.3 makes that asymmetry
            # explicit: a chime that never starts is a degraded announcement, not a silent one, and
            # reporting the whole turn as silent would send the operator looking for the wrong fault.
            reply_started = bool(clip_results) and clip_results[-1]["started"]
            # STARTING is not the same as being HEARD. `likely_silent` used to mean only "the
            # player never reached the playing state", so a clip that started and then produced
            # silence satisfied it -- and `_announce`'s correct failure mapping was handed a False.
            # A message whose end was never observed is not a message the room heard.
            # Two DIFFERENT facts, deliberately not merged. `likely_silent` means what its name
            # says and nothing more: the player never reached the playing state, so the room
            # certainly heard nothing. `end_observed` says whether we ever saw the clip finish.
            #
            # Merging them was wrong. The 2026-09-08 announcement was HEARD IN FULL and still
            # exited on its budget, because a builtin://radio/-wrapped TTS clip reports no duration
            # and never reaches idle. Treating that as silence tells the operator an announcement
            # they heard did not play -- the same dishonesty as a false success, pointed the other
            # way. An unobserved end is an absence of evidence, not a verdict.
            end_observed = bool(clip_results) and clip_results[-1]["ended"]
            # "Certainly silent" requires having WATCHED it fail to start. A clip whose start poll
            # could not read the zone establishes neither that it played nor that it did not, and
            # play_media was already accepted -- so it falls to the middle outcome, not to a denial.
            reply_gave_up = clip_results[-1]["gave_up"] if clip_results else "never_started"
            likely_silent = (not reply_started) and reply_gave_up != "unreadable"

            if superseded():
                return superseded_result()

            # 8. restore volume (best-effort; a restore failure must not swallow the reply result).
            #    `baseline` was resolved back at step 2, so a snapshot discarded mid-reply cannot
            #    strand us on the ducked prev_volume.
            try:
                restore_to = baseline if owns_restore else prev_volume
                if owns_restore and restore_to is not None:
                    # Same rule at the far end of the turn: if the zone is no longer at the volume
                    # WE last wrote, someone moved it during the reply -- keep their level.
                    # Comparing against the duck floor as well keeps a stale HA read (which returns
                    # the pre-reply value) from being mistaken for a human change.
                    live = None
                    try:
                        live = ((ctx.ha.get_entity_state(zone) or {}).get("attributes") or {}).get("volume_level")
                    except Exception as e:
                        LOG.warning("SAY req=%s zone=%s restore read failed (%r); restoring baseline", rid, zone, e)
                    if (live is not None and abs(live - reply_volume) > 0.01
                            and (duck_floor is None or abs(live - duck_floor) > 0.01)):
                        LOG.info("SAY req=%s zone=%s volume moved to %s during the reply (we wrote %s); "
                                 "keeping it instead of restoring %s", rid, zone, live, reply_volume, restore_to)
                        restore_to = None
                        pending_restore[0] = False
                        retire_snapshot(my_snap_ts)
                        # Their level is the answer now, so nothing is owed and the net stands down
                        # rather than overwriting their choice later.
                        volume_restore[0] = "restored"
                        self._cancel_volume_recovery(zone, my_gen)
                if restore_to is not None:
                    ctx.ha.call_service_rest("media_player", "volume_set",
                                             {"entity_id": zone, "volume_level": restore_to})
                    pending_restore[0] = False
                    volume_restore[0] = "restored"
                    self._cancel_volume_recovery(zone, my_gen)
                    if owns_restore:
                        # As the reply-turn restore owner, retire the snapshot ourselves: leaving it
                        # armed carries a now-stale baseline into the next turn.
                        retire_snapshot(my_snap_ts)
                    LOG.info("SAY req=%s zone=%s restored -> %s (owns_restore=%s)",
                             rid, zone, restore_to, owns_restore)
            except Exception as e:
                LOG.warning("SAY req=%s zone=%s restore failed (%r)", rid, zone, e)

            # 9. put the source back. Queue mode resumes the captured queue item (design 4.3-7);
            #    legacy mode replays the captured source by URI, exactly as before.
            replayed = False
            if qm is not None:
                if was_playing and qm["target"] is not None and not superseded():
                    replayed = self._queue_resume(ctx, rid, zone, qm, source_id, call_timeout,
                                                  superseded=superseded)
                elif not was_playing and not superseded():
                    self._queue_not_playing_cleanup(ctx, rid, zone, qm, superseded,
                                                    my_gen=my_gen)                   # design 4.8 A1.5/A2.2
                if not superseded():
                    # A turn superseded after the clip loop (e.g. during the volume restore) must
                    # NOT finish here -- its clips belong to whichever successor captured next; the
                    # `finally` already routes that case to _queue_superseded_exit (design 4.5).
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

            LOG.info("SAY req=%s zone=%s clip=%s reply_started=%s likely_silent=%s replayed=%s resume=%s "
                     "clips_deleted=%d clips_unidentified=%d",
                     rid, zone, clip, reply_started, likely_silent, replayed, resume_mode,
                     qm["deleted"] if qm else 0, qm["unidentified"] if qm else 0)
            return cr.ok(self.name, rid, "Said.", spoken_text=None,
                         metadata={"said": True, "reply_started": reply_started, "likely_silent": likely_silent,
                                    "end_observed": end_observed,
                                    "replayed": replayed, "superseded": False, "zone": zone,
                                    "clips": clip_results,
                                    "volume_restore": volume_restore[0],
                                    "resume": resume_mode, "seeked": bool(qm and qm["seeked"]),
                                    "clips_deleted": (qm["deleted"] if qm else 0),
                                    "clips_unidentified": (qm["unidentified"] if qm else 0)})
        finally:
            # The zone must never be handed back sitting at reply_volume. If we raised after
            # raising the volume (e.g. play_media 500s, or a read blip in the poll), restore the
            # baseline on the way out -- a superseding say excepted, since it owns the zone now.
            if pending_restore[0] and owns_restore and baseline is not None and not superseded():
                try:
                    ctx.ha.call_service_rest("media_player", "volume_set",
                                             {"entity_id": zone, "volume_level": baseline})
                    retire_snapshot(my_snap_ts)     # fulfilled: the zone is back on its baseline
                    volume_restore[0] = "restored"
                    self._cancel_volume_recovery(zone, my_gen)
                    LOG.warning("SAY req=%s zone=%s aborted at reply volume; restored -> %s",
                                rid, zone, baseline)
                except Exception as e:
                    LOG.error("SAY req=%s zone=%s abort-restore failed (%r); dead-man must reconcile",
                              rid, zone, e)
            if qm is None:
                # design 8.3a: an earlier clip may have replaced the queue, so un-pausing could restart
                # a spent chime instead of the music. On an AMBIGUOUS failure, replaying the captured
                # source is the safer recovery: if the play landed, replay is the only fix; if it did
                # not, replay re-plays the station that was already there.
                replayed_here = False
                if (queue_may_be_replaced[0] and not replay_done[0] and was_playing
                        and source_id and not superseded()):
                    try:
                        ctx.ha.call_service_rest(
                            "music_assistant", "play_media",
                            {"entity_id": zone, "media_id": source_id},
                            timeout=int(getattr(ctx.settings, "say_call_timeout_ms", 20000)) / 1000.0)
                        replayed_here = True
                        LOG.warning("SAY req=%s zone=%s aborted after a play; replayed the source",
                                    rid, zone)
                    except Exception as e:
                        LOG.error("SAY req=%s zone=%s abort-replay failed (%r)", rid, zone, e)
                # design 8.3a: un-pause ONLY when the queue is certainly intact -- i.e. no play_media was
                # ever attempted, or there was no source to replay. A replay that RAISED may still have
                # landed, so un-pausing after one would resume either the source or the announcement
                # clip. That ambiguity is why there is no blind last-resort un-pause here: when a play
                # and its replay both fail, the zone is left paused at its baseline and the operator
                # recovers with "resume" (interaction mode resume un-pauses a paused zone).
                if (paused_by_us[0] and not superseded()
                        and not replay_done[0] and not replayed_here
                        and (not queue_may_be_replaced[0] or not source_id)):
                    try:
                        ctx.ha.call_service_rest("media_player", "media_play", {"entity_id": zone})
                        LOG.warning("SAY req=%s zone=%s un-paused the source (queue intact, or nothing "
                                    "to replay)", rid, zone)
                    except Exception as e:
                        LOG.error("SAY req=%s zone=%s un-pause failed (%r)", rid, zone, e)
            if qm is not None:
                try:
                    if superseded():
                        self._queue_superseded_exit(ctx, rid, zone, qm, my_gen)
                    elif not queue_done[0]:
                        # Died before step 9. Only act on what WE changed (peer review finding 2):
                        #  - a clip may sit in front of the song -> resume the captured item (table 4.4);
                        #  - we only paused -> the queue is exactly as it was: un-pause in place;
                        #  - neither -> the song was never interrupted: do nothing.
                        # The finish runs even when the resume/un-pause raises: skipping it would leave
                        # this turn's record live, and a live record is only ever retired by a successor.
                        try:
                            if was_playing and qm["target"] is not None and qm["resume"] == "none":
                                if queue_may_be_replaced[0]:
                                    self._queue_resume(ctx, rid, zone, qm, source_id,
                                                       int(getattr(ctx.settings, "say_call_timeout_ms", 20000)) / 1000.0,
                                                       superseded=superseded)
                                elif paused_by_us[0]:
                                    self._say_call(ctx, rid, zone, "media_player", "media_play", {"entity_id": zone})
                        finally:
                            self._queue_finish(ctx, rid, zone, qm, my_gen)
                except Exception as e:
                    LOG.error("SAY req=%s zone=%s queue recovery failed (%r)", rid, zone, e)
            release_reply()
