#!/usr/bin/env python3
# AU-02/AU-03: interaction duck/restore for a media zone. Silent. Python 3.5 safe.
import logging, time, threading
import capability
import command_result as cr

LOG = logging.getLogger("resolver")
_MODES = ("duck", "restore")


class InteractionCapability(capability.Capability):
    name = "interaction"

    def __init__(self, timer_factory=None, clock=None):
        self._timer_factory = timer_factory or threading.Timer
        self._clock = clock or time.time
        self._snaps = {}                             # zone -> {"volume": float, "ts": float, "timer": obj|None}
        self._lock = threading.Lock()                # guards _snaps check-then-act (HTTP threads + timer thread)

    def resolve(self, ctx, params):
        mode = (params.get("mode") or "").strip().lower()
        zone = params.get("zone") or getattr(ctx.settings, "ceiling_entity", "")
        return {"mode": mode, "zone": zone}

    def validate(self, ctx, resolved):
        if resolved["mode"] not in _MODES:
            return {"code": "invalid_input", "reason": "bad mode",
                    "chat_text": "Unknown interaction mode."}
        if not resolved["zone"]:
            return {"code": "invalid_input", "reason": "no zone", "chat_text": "No zone."}
        return None

    def execute(self, ctx, resolved, rid):
        if resolved["mode"] == "duck":
            return self._duck(ctx, resolved["zone"], rid)
        return self._restore(ctx, resolved["zone"], rid)

    def _duck(self, ctx, zone, rid):
        state = ctx.ha.get_entity_state(zone) or {}
        player_state = state.get("state")
        vol = (state.get("attributes") or {}).get("volume_level")
        if player_state != "playing" and getattr(ctx.settings, "interaction_ignore_when_idle", True):
            return cr.ok(self.name, rid, "Nothing to duck.", spoken_text=None,
                         metadata={"ducked": False, "reason": "not_playing", "zone": zone})
        if vol is None:                                             # can't guarantee restore -> don't duck
            return cr.ok(self.name, rid, "Nothing to duck.", spoken_text=None,
                         metadata={"ducked": False, "reason": "no_volume", "zone": zone})
        floor = int(getattr(ctx.settings, "interaction_floor", 15)) / 100.0
        with self._lock:                                            # atomic snapshot + timer arm
            if zone not in self._snaps:                             # coalesce: keep original baseline
                self._snaps[zone] = {"volume": vol, "ts": self._clock(), "timer": None}
            self._arm_timer(ctx, zone)
        ctx.ha.call_service("media_player", "volume_set",
                            {"entity_id": zone, "volume_level": floor})
        LOG.info("DUCK req=%s zone=%s %s -> %s", rid, zone, vol, floor)
        return cr.ok(self.name, rid, "Ducked.", spoken_text=None,
                     metadata={"ducked": True, "from": vol, "to": floor, "zone": zone})

    def _arm_timer(self, ctx, zone):
        snap = self._snaps.get(zone)
        if snap is None:
            return
        if snap.get("timer") is not None:
            try:
                snap["timer"].cancel()
            except Exception:
                pass
        secs = int(getattr(ctx.settings, "max_duck_timeout", 45000)) / 1000.0
        t = self._timer_factory(secs, self._auto_restore, [ctx, zone])
        snap["timer"] = t
        t.start()

    def _auto_restore(self, ctx, zone):
        LOG.warning("DUCK dead-man timeout: auto-restoring zone=%s", zone)
        try:
            self._restore(ctx, zone, "deadman")
        except Exception as e:
            LOG.error("auto-restore failed zone=%s: %r", zone, e)

    # implemented in a later task
    def _restore(self, ctx, zone, rid):
        raise NotImplementedError
