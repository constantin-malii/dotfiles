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

    def _restore(self, ctx, zone, rid):
        with self._lock:
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

    def _say(self, ctx, resolved, rid):
        zone = resolved["zone"]; uri = resolved["uri"]
        timeout = int(getattr(ctx.settings, "say_announce_timeout_ms", 30000)) / 1000.0
        # capture what's playing so we can re-play it if the announcement doesn't auto-resume (radio/live)
        try:                                                  # best-effort capture; a read blip must not swallow the reply
            before = ctx.ha.get_entity_state(zone) or {}
        except Exception as e:
            LOG.warning("SAY req=%s zone=%s capture read failed (%r); replay skipped", rid, zone, e)
            before = {}
        was_playing = before.get("state") == "playing"
        media_id = (before.get("attributes") or {}).get("media_content_id")
        # blocking: MA pauses the music, plays the reply, resumes resumable content
        ctx.ha.call_service_rest("music_assistant", "play_announcement",
                                 {"entity_id": zone, "url": uri}, timeout=timeout)
        replayed = False
        if was_playing and media_id:
            try:
                after = ctx.ha.get_entity_state(zone) or {}
            except Exception:
                after = {}
            if after.get("state") != "playing":               # radio/live didn't auto-resume -> re-play the station
                ctx.ha.call_service_rest("music_assistant", "play_media",
                                         {"entity_id": zone, "media_id": media_id})
                replayed = True
        LOG.info("SAY req=%s zone=%s uri=%s replayed=%s", rid, zone, uri, replayed)
        return cr.ok(self.name, rid, "Said.", spoken_text=None,
                     metadata={"said": True, "replayed": replayed, "zone": zone})
