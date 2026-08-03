#!/usr/bin/env python3
# AU-02/AU-03: interaction duck/restore for a media zone. Silent. Python 3.5 safe.
import hashlib, logging, time, threading
from urllib.parse import urlparse, urlunparse
import capability
import command_result as cr

LOG = logging.getLogger("resolver")
_MODES = ("duck", "restore", "say", "resume", "volume_up", "volume_down", "set_volume")


class InteractionCapability(capability.Capability):
    name = "interaction"

    def __init__(self, timer_factory=None, clock=None, sleeper=None):
        self._timer_factory = timer_factory or threading.Timer
        self._clock = clock or time.time
        self._sleeper = sleeper or time.sleep
        self._snaps = {}                             # zone -> {"volume": baseline, "target": last-written, "ts": float, "timer": obj|None}
        self._lock = threading.Lock()                # guards _snaps check-then-act (HTTP threads + timer thread)
        self._say_gen = {}                            # zone -> generation counter (barge-in supersede), guarded by _lock
        self._turns = {}                              # zone -> {"ts": float, "playback": uri|None}
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

    def resolve(self, ctx, params):
        mode = (params.get("mode") or "").strip().lower()
        zone = params.get("zone") or getattr(ctx.settings, "ceiling_entity", "")
        uri = params.get("uri") or params.get("media_content_id") or ""
        return {"mode": mode, "zone": zone, "uri": uri,
                "step": params.get("step"), "volume": params.get("volume")}

    def validate(self, ctx, resolved):
        if resolved["mode"] not in _MODES:
            return {"code": "invalid_input", "reason": "bad mode",
                    "chat_text": "Unknown interaction mode."}
        if not resolved["zone"]:
            return {"code": "invalid_input", "reason": "no zone", "chat_text": "No zone."}
        if resolved["mode"] == "say" and not resolved.get("uri"):
            return {"code": "invalid_input", "reason": "no uri", "chat_text": "No reply audio."}
        return None

    def execute(self, ctx, resolved, rid):
        if resolved["mode"] == "duck":
            return self._duck(ctx, resolved["zone"], rid)
        if resolved["mode"] == "say":
            return self._say(ctx, resolved, rid)
        if resolved["mode"] == "resume":
            return self._resume(ctx, resolved["zone"], rid)
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
            state = ctx.ha.get_entity_state(zone) or {}
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
                                     {"entity_id": zone, "volume_level": target})
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
        # Reply clips are Piper renders served from HA's tts_proxy, which MA wraps as
        # "builtin://radio/<url>". They must never be treated as a resumable source.
        u = (uri or "").lower()
        return ("tts_proxy" in u) or u.startswith("builtin://radio/http")

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

    def _resume(self, ctx, zone, rid):
        with self._lock:
            uri = self._last_source.get(zone)
        if uri:
            ctx.ha.call_service_rest("music_assistant", "play_media",
                                     {"entity_id": zone, "media_id": uri},
                                     timeout=int(getattr(ctx.settings, "say_call_timeout_ms", 20000)) / 1000.0)
            self.note_playback(ctx, zone, uri)     # this turn started media: do not let the reply
                                                   #   clip replace what we just resumed
            LOG.info("RESUME req=%s zone=%s replaying %s", rid, zone, uri)
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
        if state == "paused":
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
            LOG.info("RESUME req=%s zone=%s replaying the loaded source %s", rid, zone, cid)
            return cr.ok(self.name, rid, "Resuming.", spoken_text=None,
                         metadata={"resumed": True, "uri": cid, "how": "loaded", "zone": zone})
        LOG.info("RESUME req=%s zone=%s nothing to resume (state=%s had_reply_clip=%s)",
                 rid, zone, state, bool(cid))
        return cr.ok(self.name, rid, "There is nothing to resume.", spoken_text=None,
                     metadata={"resumed": False, "reason": "nothing_to_resume", "zone": zone})

    def note_playback(self, ctx, zone, uri):
        """Record that the resolver just started media on this zone as part of the current turn.

        `_say` delivers a reply with play_media, which REPLACES the stream -- so the spoken
        confirmation of a media command ("Playing Radio Noroc Moldova") overwrites the very station
        it is confirming, and _say's capture runs while that station is still starting, so it
        captures no source to replay and the zone ends up idle holding the TTS clip. Keyed to the
        TURN, not a timer: a question asked seconds later is a new turn and still gets its reply."""
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
                state = ctx.ha.get_entity_state(zone) or {}
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
                                     {"entity_id": zone, "volume_level": target})
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

    def _say(self, ctx, resolved, rid):
        zone = resolved["zone"]; uri = resolved["uri"]
        clip = self._clip_id(uri)

        # Plan decision (e): a pure media command is confirmed by the ACTION, not by speech. Playing
        # the confirmation clip here would replace the stream the same turn just started (and the
        # capture below would find it still starting, so nothing would replay it) -- the command
        # would report success and leave silence.
        if bool(getattr(ctx.settings, "say_skip_on_fresh_playback", True)):
            with self._lock:
                turn = self._turns.get(zone) or {}
                started = turn.get("playback")
            if started:
                LOG.info("SAY req=%s zone=%s clip=%s SKIPPED: this turn started %s -- the reply would "
                         "replace it (media command is confirmed by the action)", rid, zone, clip, started)
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

        # 2. barge-in gen-id: bump this zone's generation; a later say() will bump it again and
        #    supersede us -- we then abort remaining steps rather than fight over the finish.
        #    Same critical section resolves and publishes the restore baseline: capturing it HERE
        #    (not at the restore step) means a mid-reply snapshot discard cannot strip it, and
        #    publishing it in _replies makes this zone reply-owned for _restore/_duck.
        with self._lock:
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
            self._replies[zone] = {"gen": my_gen, "baseline": baseline,
                                   "ts": self._clock(), "rid": rid}

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
        play_issued = [False]                   # the reply play_media actually went out
        try:
            # 3. normalise the reply URI to the MA-reachable internal base
            norm_uri = self._normalise_uri(uri, getattr(ctx.settings, "say_internal_base", ""))

            poll_secs = max(int(getattr(ctx.settings, "say_poll_ms", 500)) / 1000.0, 0.05)
            start_timeout = int(getattr(ctx.settings, "say_start_timeout_ms", 5000)) / 1000.0
            reply_timeout = int(getattr(ctx.settings, "say_reply_timeout_ms", 30000)) / 1000.0
            reply_volume = float(getattr(ctx.settings, "reply_volume", 0.40))
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
            self._say_call(ctx, rid, zone, "media_player", "volume_set",
                           {"entity_id": zone, "volume_level": reply_volume})
            pending_restore[0] = True
            if owns_restore:
                with self._lock:
                    snap = self._snaps.get(zone)
                    if snap is not None and snap.get("ts") == my_snap_ts:
                        # Keep the duck's "last value we wrote" in step with reality. If this reply
                        # turn dies before its restore, a later _restore/dead-man must find the
                        # device in agreement and restore the baseline -- not read our reply volume
                        # as a human override, keep it, and discard the baseline (the ratchet).
                        snap["target"] = reply_volume
            # MA's play_media regularly outruns the 5s REST default; a client-side timeout here
            # aborts the turn while the clip still starts server-side (audible, unsequenced).
            self._say_call(ctx, rid, zone, "music_assistant", "play_media",
                           {"entity_id": zone, "media_id": norm_uri}, timeout=call_timeout)
            play_issued[0] = True

            # 6. confirm start: poll until the clip is actually playing, or the start budget runs out
            reply_started = False
            elapsed = 0.0
            while elapsed < start_timeout:
                if superseded():
                    return superseded_result()
                try:
                    state = ctx.ha.get_entity_state(zone) or {}
                except Exception as e:
                    LOG.warning("SAY req=%s zone=%s start-poll read failed (%r)", rid, zone, e)
                    state = {}
                attrs = state.get("attributes") or {}
                # MA does not echo the raw URL back as media_content_id -- it wraps it, e.g.
                # "builtin://radio/<url>". Match by containment, not equality.
                if state.get("state") == "playing" and norm_uri in (attrs.get("media_content_id") or ""):
                    reply_started = True
                    break
                self._sleeper(poll_secs)
                elapsed += poll_secs

            likely_silent = not reply_started
            if likely_silent:
                LOG.warning("SAY req=%s reply did not start (likely silent)", rid)
            else:
                # 7. wait for finish: poll until the clip stops playing (or gets superseded)
                elapsed = 0.0
                ended_seen = 0
                blank_for = 0.0
                blank_grace = max(int(getattr(ctx.settings, "say_blank_cid_grace_ms", 4000)) / 1000.0,
                                  poll_secs)
                while elapsed < reply_timeout:
                    if superseded():
                        return superseded_result()
                    try:
                        state = ctx.ha.get_entity_state(zone) or {}
                    except Exception as e:
                        LOG.warning("SAY req=%s zone=%s finish-poll read failed (%r)", rid, zone, e)
                        state = {}
                    attrs = state.get("attributes") or {}
                    cid = attrs.get("media_content_id") or ""
                    # MA transiently reports an EMPTY media_content_id while the clip is still
                    # playing. Treating that as "the clip ended" cut the reply off after 0.5-1.0s
                    # and replayed the source over it -- so an empty cid is NOT an ending while the
                    # player still says `playing`. Only a cid that names something ELSE counts.
                    ended = (state.get("state") != "playing") or (cid != "" and norm_uri not in cid)
                    if not ended and cid == "":
                        # Unknown, not "still playing": tolerate the flicker, but only for a bounded
                        # grace. Beyond that we cannot tell, and holding the zone at reply volume for
                        # the full reply timeout is worse than finishing.
                        blank_for += poll_secs
                        if blank_for >= blank_grace:
                            LOG.info("SAY req=%s zone=%s clip=%s finish-poll: cid stayed empty for %.1fs "
                                     "(state=playing); treating the clip as finished",
                                     rid, zone, clip, blank_for)
                            break
                    elif cid != "":
                        blank_for = 0.0
                    if ended:
                        # Require two consecutive observations: a single flicker of state or cid
                        # must not trigger the restore+replay that is heard as a cut-off.
                        ended_seen += 1
                        if ended_seen >= 2:
                            LOG.info("SAY req=%s zone=%s clip=%s finish-poll exit after %.1fs: state=%s cid=%s",
                                     rid, zone, clip, elapsed, state.get("state"), cid[:60])
                            break
                    else:
                        ended_seen = 0
                    self._sleeper(poll_secs)
                    elapsed += poll_secs

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
                if restore_to is not None:
                    ctx.ha.call_service_rest("media_player", "volume_set",
                                             {"entity_id": zone, "volume_level": restore_to})
                    pending_restore[0] = False
                    if owns_restore:
                        # As the reply-turn restore owner, retire the snapshot ourselves: leaving it
                        # armed carries a now-stale baseline into the next turn.
                        retire_snapshot(my_snap_ts)
                    LOG.info("SAY req=%s zone=%s restored -> %s (owns_restore=%s)",
                             rid, zone, restore_to, owns_restore)
            except Exception as e:
                LOG.warning("SAY req=%s zone=%s restore failed (%r)", rid, zone, e)

            # 9. replay source: the reply replaced the queue, so replay for BOTH radio and local content
            replayed = False
            if was_playing and source_id and not superseded():
                try:
                    self._say_call(ctx, rid, zone, "music_assistant", "play_media",
                                   {"entity_id": zone, "media_id": source_id}, timeout=call_timeout)
                    replayed = True
                except Exception as e:
                    LOG.warning("SAY req=%s zone=%s replay failed (%r); source NOT resumed", rid, zone, e)

            LOG.info("SAY req=%s zone=%s clip=%s reply_started=%s likely_silent=%s replayed=%s",
                     rid, zone, clip, reply_started, likely_silent, replayed)
            return cr.ok(self.name, rid, "Said.", spoken_text=None,
                         metadata={"said": True, "reply_started": reply_started, "likely_silent": likely_silent,
                                    "replayed": replayed, "superseded": False, "zone": zone})
        finally:
            # The zone must never be handed back sitting at reply_volume. If we raised after
            # raising the volume (e.g. play_media 500s, or a read blip in the poll), restore the
            # baseline on the way out -- a superseding say excepted, since it owns the zone now.
            if pending_restore[0] and owns_restore and baseline is not None and not superseded():
                try:
                    ctx.ha.call_service_rest("media_player", "volume_set",
                                             {"entity_id": zone, "volume_level": baseline})
                    retire_snapshot(my_snap_ts)     # fulfilled: the zone is back on its baseline
                    LOG.warning("SAY req=%s zone=%s aborted at reply volume; restored -> %s",
                                rid, zone, baseline)
                except Exception as e:
                    LOG.error("SAY req=%s zone=%s abort-restore failed (%r); dead-man must reconcile",
                              rid, zone, e)
            # If we silenced the music and the clip never went out, un-pause it: the queue still holds
            # the music, so this restores the zone rather than leaving it silent.
            if paused_by_us[0] and not play_issued[0] and not superseded():
                try:
                    ctx.ha.call_service_rest("media_player", "media_play", {"entity_id": zone})
                    LOG.warning("SAY req=%s zone=%s reply never issued; un-paused the source", rid, zone)
                except Exception as e:
                    LOG.error("SAY req=%s zone=%s un-pause failed (%r)", rid, zone, e)
            release_reply()
