#!/usr/bin/env python3
# AU-02/AU-03: interaction duck/restore for a media zone. Silent. Python 3.5 safe.
import logging, time, threading
import capability
import command_result as cr

LOG = logging.getLogger("resolver")
_MODES = ("duck", "restore", "say")


class InteractionCapability(capability.Capability):
    name = "interaction"

    def __init__(self, timer_factory=None, clock=None):
        self._timer_factory = timer_factory or threading.Timer
        self._clock = clock or time.time
        self._snaps = {}                             # zone -> {"volume": baseline, "target": last-written, "ts": float, "timer": obj|None}
        self._lock = threading.Lock()                # guards _snaps check-then-act (HTTP threads + timer thread)

    def resolve(self, ctx, params):
        mode = (params.get("mode") or "").strip().lower()
        zone = params.get("zone") or getattr(ctx.settings, "ceiling_entity", "")
        uri = params.get("uri") or params.get("media_content_id") or ""
        hold_ms = params.get("hold_ms")
        return {"mode": mode, "zone": zone, "uri": uri, "hold_ms": hold_ms}

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
                self._snaps[zone] = {"volume": vol, "target": target, "ts": self._clock(), "timer": None}
            else:                                                      # coalesce: keep baseline, track last-written target
                self._snaps[zone]["target"] = target
            self._arm_timer(ctx, zone)                                 # snapshot + timer BEFORE the write, so a
            ctx.ha.call_service_rest("media_player", "volume_set",     #   lost-ack write is reconciled by the dead-man
                                     {"entity_id": zone, "volume_level": target})
            LOG.info("DUCK req=%s zone=%s %s -> %s", rid, zone, vol, target)
            return cr.ok(self.name, rid, "Ducked.", spoken_text=None,
                         metadata={"ducked": True, "from": vol, "to": target, "zone": zone})

    def _arm_timer(self, ctx, zone, secs=None):
        snap = self._snaps.get(zone)
        if snap is None:
            return
        self._cancel_timer(snap)
        if secs is None:
            secs = int(getattr(ctx.settings, "max_duck_timeout", 120000)) / 1000.0
        t = self._timer_factory(secs, self._auto_restore, [ctx, zone])
        snap["timer"] = t
        t.start()

    def _arm_reply_timer(self, ctx, zone, secs):
        snap = self._snaps.get(zone)
        if snap is None:
            return
        self._cancel_timer(snap)                               # replace the dead-man with the reply timer
        t = self._timer_factory(secs, self._reply_complete, [ctx, zone])
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
            self._restore(ctx, zone, "deadman", force=True)
        except Exception as e:
            LOG.error("auto-restore failed zone=%s: %r; re-arming", zone, e)
            try:
                with self._lock:
                    if zone in self._snaps:
                        self._arm_timer(ctx, zone)
            except Exception as e2:
                LOG.error("auto-restore re-arm failed zone=%s: %r", zone, e2)

    def _restore(self, ctx, zone, rid, force=False):
        with self._lock:                                               # read + write stay under _lock together
                                                                        # (intentional: serializes HTTP threads
                                                                        # against the timer thread)
            snap = self._snaps.get(zone)                              # peek; discard only after write
            if snap is None:
                return cr.ok(self.name, rid, "Nothing to restore.", spoken_text=None,
                             metadata={"restored": False, "reason": "no_snapshot", "zone": zone})
            if snap.get("reply_active") and not force:          # a ceiling reply is playing; the reply timer owns restore
                LOG.info("RESTORE req=%s zone=%s deferred (reply active)", rid, zone)
                return cr.ok(self.name, rid, "Deferred.", spoken_text=None,
                             metadata={"restored": False, "reason": "reply_active", "zone": zone})
            try:
                state = ctx.ha.get_entity_state(zone) or {}
                cur = (state.get("attributes") or {}).get("volume_level")
            except Exception as e:
                LOG.warning("RESTORE req=%s zone=%s read failed (%r); restoring baseline", rid, zone, e)
                cur = None
            applied = snap.get("target")
            # last-writer-wins vs the value WE set (not the config floor); never treats our own duck as a user change
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
            ctx.ha.call_service_rest("media_player", "volume_set",    # write first (raises on failure)
                                     {"entity_id": zone, "volume_level": target})
            self._cancel_timer(snap); self._snaps.pop(zone, None)     # confirmed -> safe to discard
            LOG.info("RESTORE req=%s zone=%s -> %s", rid, zone, target)
            return cr.ok(self.name, rid, "Restored.", spoken_text=None,
                         metadata={"restored": True, "to": target, "zone": zone})

    def _say(self, ctx, resolved, rid):
        zone = resolved["zone"]; uri = resolved["uri"]
        margin = int(getattr(ctx.settings, "say_margin_ms", 1500))
        default_hold = int(getattr(ctx.settings, "say_hold_default_ms", 8000))
        deadman_ms = int(getattr(ctx.settings, "max_duck_timeout", 120000))
        hold_ms = resolved.get("hold_ms")
        try:
            hold = default_hold if hold_ms is None else int(hold_ms)
        except (TypeError, ValueError):
            LOG.warning("SAY req=%s zone=%s bad hold_ms=%r; using default %sms",
                        rid, zone, hold_ms, default_hold)
            hold = default_hold
        if hold < 0:                                           # negative would fire the reply timer immediately
            LOG.warning("SAY req=%s zone=%s negative hold_ms=%r; using default %sms",
                        rid, zone, hold_ms, default_hold)
            hold = default_hold
        hold += margin
        if hold > deadman_ms:                                  # never arm a reply timer past the dead-man ceiling
            LOG.warning("SAY req=%s zone=%s hold+margin=%sms exceeds max_duck_timeout=%sms; clamping",
                        rid, zone, hold, deadman_ms)
            hold = deadman_ms
        with self._lock:
            ctx.ha.call_service_rest("media_player", "play_media",
                                     {"entity_id": zone, "media_content_id": uri,
                                      "media_content_type": "music", "announce": True})
            snap = self._snaps.get(zone)
            if snap is None:                                   # music wasn't ducked -> just play the reply
                LOG.info("SAY req=%s zone=%s uri=%s (no active duck)", rid, zone, uri)
                return cr.ok(self.name, rid, "Said.", spoken_text=None,
                             metadata={"said": True, "held": False, "zone": zone})
            self._arm_reply_timer(ctx, zone, hold / 1000.0)     # arm-then-flag: no window where reply_active is
            snap["reply_active"] = True                         #   set without a timer backing it
            LOG.info("SAY req=%s zone=%s uri=%s hold=%sms", rid, zone, uri, hold)
            return cr.ok(self.name, rid, "Said.", spoken_text=None,
                         metadata={"said": True, "held": True, "zone": zone})

    def _reply_complete(self, ctx, zone):
        LOG.info("SAY reply complete: restoring zone=%s", zone)
        with self._lock:
            snap = self._snaps.get(zone)
            if snap is not None:
                snap["reply_active"] = False                   # clear so _restore proceeds
        try:
            self._restore(ctx, zone, "reply")
        except Exception as e:
            LOG.error("reply-complete restore failed zone=%s: %r; re-arming", zone, e)
            try:
                with self._lock:
                    if zone in self._snaps:
                        self._arm_timer(ctx, zone)             # fall back to the dead-man backstop
            except Exception as e2:
                LOG.error("reply re-arm failed zone=%s: %r", zone, e2)
