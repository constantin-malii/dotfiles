#!/usr/bin/env python3
# AU-02/AU-03: interaction duck/restore for a media zone. Silent. Python 3.5 safe.
import logging, time, threading
from urllib.parse import urlparse, urlunparse
import capability
import command_result as cr

LOG = logging.getLogger("resolver")
_MODES = ("duck", "restore", "say")


class InteractionCapability(capability.Capability):
    name = "interaction"

    def __init__(self, timer_factory=None, clock=None, sleeper=None):
        self._timer_factory = timer_factory or threading.Timer
        self._clock = clock or time.time
        self._sleeper = sleeper or time.sleep
        self._snaps = {}                             # zone -> {"volume": baseline, "target": last-written, "ts": float, "timer": obj|None}
        self._lock = threading.Lock()                # guards _snaps check-then-act (HTTP threads + timer thread)
        self._say_gen = {}                            # zone -> generation counter (barge-in supersede), guarded by _lock
        self._replies = {}                            # zone -> {"gen": int, "baseline": float|None} while a reply
                                                      #   turn is in flight; _say owns the zone's volume for its
                                                      #   lifetime (S1b-2 decision (b)). Guarded by _lock.

    def resolve(self, ctx, params):
        mode = (params.get("mode") or "").strip().lower()
        zone = params.get("zone") or getattr(ctx.settings, "ceiling_entity", "")
        uri = params.get("uri") or params.get("media_content_id") or ""
        return {"mode": mode, "zone": zone, "uri": uri}

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
        return self._restore(ctx, resolved["zone"], rid)

    def _duck(self, ctx, zone, rid):
        floor = int(getattr(ctx.settings, "interaction_floor", 15)) / 100.0
        with self._lock:                                               # read + write stay under _lock together
                                                                        # (intentional: serializes HTTP threads
                                                                        # against the timer thread)
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
                return cr.ok(self.name, rid, "Nothing to duck.", spoken_text=None,
                             metadata={"ducked": False, "reason": "not_playing", "zone": zone})
            if vol is None:
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

    def _say(self, ctx, resolved, rid):
        zone = resolved["zone"]; uri = resolved["uri"]

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
            # Identity of the snapshot our baseline came from. We may only ever retire THAT one:
            # a snapshot belonging to a later turn must not be torn down by us.
            my_snap_ts = my_snap.get("ts") if my_snap is not None else None
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

        def superseded_result():
            return cr.ok(self.name, rid, "Said.", spoken_text=None,
                         metadata={"said": False, "reply_started": False, "likely_silent": False,
                                    "replayed": False, "superseded": True, "zone": zone})

        # From here on the zone is reply-owned, so every exit path must hand it back.
        owns_restore = bool(getattr(ctx.settings, "say_owns_restore", True))
        pending_restore = [False]               # True once the zone sits at reply_volume and we still
                                               # owe it a restore (list: rebound in the finally block)
        try:
            # 3. normalise the reply URI to the MA-reachable internal base
            norm_uri = self._normalise_uri(uri, getattr(ctx.settings, "say_internal_base", ""))

            poll_secs = max(int(getattr(ctx.settings, "say_poll_ms", 500)) / 1000.0, 0.05)
            start_timeout = int(getattr(ctx.settings, "say_start_timeout_ms", 5000)) / 1000.0
            reply_timeout = int(getattr(ctx.settings, "say_reply_timeout_ms", 30000)) / 1000.0
            reply_volume = float(getattr(ctx.settings, "reply_volume", 0.40))

            # 4. set reply volume, then 5. play_media (reply)
            ctx.ha.call_service_rest("media_player", "volume_set",
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
            ctx.ha.call_service_rest("music_assistant", "play_media",
                                     {"entity_id": zone, "media_id": norm_uri})

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
                while elapsed < reply_timeout:
                    if superseded():
                        return superseded_result()
                    try:
                        state = ctx.ha.get_entity_state(zone) or {}
                    except Exception as e:
                        LOG.warning("SAY req=%s zone=%s finish-poll read failed (%r)", rid, zone, e)
                        state = {}
                    attrs = state.get("attributes") or {}
                    if state.get("state") != "playing" or norm_uri not in (attrs.get("media_content_id") or ""):
                        break
                    self._sleeper(poll_secs)
                    elapsed += poll_secs

            if superseded():
                return superseded_result()

            # 8. restore volume (best-effort; a restore failure must not swallow the reply result).
            #    `baseline` was resolved back at step 2, so a snapshot discarded mid-reply cannot
            #    strand us on the ducked prev_volume.
            try:
                restore_to = baseline if owns_restore else prev_volume
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
                    ctx.ha.call_service_rest("music_assistant", "play_media",
                                             {"entity_id": zone, "media_id": source_id})
                    replayed = True
                except Exception as e:
                    LOG.warning("SAY req=%s zone=%s replay failed (%r)", rid, zone, e)

            LOG.info("SAY req=%s zone=%s reply_started=%s likely_silent=%s replayed=%s",
                     rid, zone, reply_started, likely_silent, replayed)
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
            release_reply()
