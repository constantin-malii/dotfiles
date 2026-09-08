#!/usr/bin/env python3
# AU-02/AU-03: interaction duck/restore for a media zone. Silent. Python 3.5 safe.
import hashlib, logging, re, time, threading
from urllib.parse import urlparse, urlunparse
import capability
import command_result as cr

LOG = logging.getLogger("resolver")
_MODES = ("duck", "restore", "say", "say_text", "resume", "pause", "volume_up", "volume_down",
          "set_volume", "announce")


class InteractionCapability(capability.Capability):
    name = "interaction"

    def __init__(self, timer_factory=None, clock=None, sleeper=None):
        self._timer_factory = timer_factory or threading.Timer
        self._clock = clock or time.time
        self._sleeper = sleeper or time.sleep
        self._snaps = {}                             # zone -> {"volume": baseline, "target": last-written, "ts": float, "timer": obj|None}
        self._lock = threading.Lock()                # guards _snaps check-then-act (HTTP threads + timer thread)
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

    def _resume(self, ctx, zone, rid):
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
        """
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
        """
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
        LOG.info("SAY_TEXT req=%s zone=%s engine=%s chars=%d", rid, resolved.get("zone"),
                 engine, len(text))
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

        # D. Chime. A failure DEGRADES: an announcement without its chime is still an
        #    announcement. Resolved every turn and never cached -- the signature expires, and a
        #    cached URL would fail silently two layers from its symptom.
        chime_uri = (getattr(ctx.settings, "announce_chime_uri", "") or "").strip()
        chime = {"played": False, "reason": None}
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
            seq["deadline_from_now"] = sum(finish_timeouts) + (
                len(uris) * int(getattr(ctx.settings, "say_start_timeout_ms", 5000)) / 1000.0)
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
                chime["played"] = bool(clips[0].get("started"))
                if not chime["played"] and chime["reason"] is None:
                    chime["reason"] = "never_started"
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
            return cr.ok(self.name, rid, "Announced.", spoken_text=None, metadata=meta)
        finally:
            # Every exit path, including an exception: a stuck-muted microphone is a deaf satellite,
            # which is a silent open-ended failure nobody finds until they try to talk to it.
            if muted:
                self._mic_release(ctx, zone, my_gen, rid)

    def _play_clip_and_wait(self, ctx, rid, zone, norm_uri, match_key, clip, opts, superseded):
        """Play ONE clip on the zone and wait for it: play_media -> start-poll -> finish-poll.

        Everything a TURN owns stays with the caller -- generation ownership, baseline capture, the
        single volume raise, the single restore, the single replay, the release. This method owns
        exactly one clip, which is what lets a caller sequence several of them over one turn.

        `match_key` is separate from `norm_uri` because MA does not echo back what it plays: it
        wraps it, and wraps it differently per media type. The caller therefore has to be able to
        say what a "this clip is playing" observation looks like.

        `opts` carries `start_timeout`, `finish_timeout`, `call_timeout`, `poll_secs`,
        `blank_grace`, `floor` and `deadline` (float, or None for accumulated-sleep bounding).

        Returns {"started", "issued", "clip"}. Propagates whatever play_media raises -- the caller's
        finally is the recovery path, and it owns the volume restore, so it has to see the failure.
        """
        out = {"started": False, "issued": False, "clip": clip}
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
        self._say_call(ctx, rid, zone, "music_assistant", "play_media",
                       {"entity_id": zone, "media_id": norm_uri}, timeout=opts["call_timeout"])
        out["issued"] = True

        # Confirm start: poll until the clip is actually playing, or the start budget runs out.
        start_timeout = opts["start_timeout"]
        start_deadline = self._clock() + start_timeout
        elapsed = 0.0
        while True:
            if superseded():
                return out
            if deadline is None:
                if elapsed >= start_timeout:
                    break
            elif self._clock() >= min(start_deadline, deadline):
                break
            rt = read_timeout(10)
            if rt is None:
                break
            try:
                state = ctx.ha.get_entity_state(zone, timeout=rt) or {}
            except Exception as e:
                LOG.warning("SAY req=%s zone=%s start-poll read failed (%r)", rid, zone, e)
                state = {}
            attrs = state.get("attributes") or {}
            # MA does not echo the raw URL back as media_content_id -- it wraps it, e.g.
            # "builtin://radio/<url>". Match by containment, not equality.
            if state.get("state") == "playing" and match_key in (attrs.get("media_content_id") or ""):
                out["started"] = True
                break
            self._sleeper(poll_secs)
            elapsed += poll_secs

        if not out["started"]:
            LOG.warning("SAY req=%s zone=%s clip=%s did not start (likely silent)", rid, zone, clip)
            return out

        # Wait for finish: poll until the clip stops playing (or the caller is superseded).
        finish_timeout = opts["finish_timeout"]
        finish_deadline = self._clock() + finish_timeout
        blank_grace = max(opts["blank_grace"], poll_secs)
        elapsed = 0.0
        ended_seen = 0
        blank_for = 0.0
        while True:
            if superseded():
                return out
            if deadline is None:
                if elapsed >= finish_timeout:
                    break
            elif self._clock() >= min(finish_deadline, deadline):
                break
            rt = read_timeout(10)
            if rt is None:
                break
            try:
                state = ctx.ha.get_entity_state(zone, timeout=rt) or {}
            except Exception as e:
                LOG.warning("SAY req=%s zone=%s finish-poll read failed (%r)", rid, zone, e)
                state = {}
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
                    break
            elif cid != "":
                blank_for = 0.0
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
                    break
            else:
                ended_seen = 0
            self._sleeper(poll_secs)
            elapsed += poll_secs
        return out

    def _say(self, ctx, resolved, rid):
        zone = resolved["zone"]; uri = resolved["uri"]
        clip = self._clip_id(uri)

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
                res = self._play_clip_and_wait(ctx, rid, zone, one_uri, one_key, one_clip,
                                               opts, superseded)
                play_issued[0] = play_issued[0] or res["issued"]
                clip_results.append({"clip": one_clip, "started": res["started"],
                                     "issued": res["issued"]})
                if superseded():
                    return superseded_result()
            # reply_started tracks the LAST clip -- the message. Design 8.3 makes that asymmetry
            # explicit: a chime that never starts is a degraded announcement, not a silent one, and
            # reporting the whole turn as silent would send the operator looking for the wrong fault.
            reply_started = bool(clip_results) and clip_results[-1]["started"]
            likely_silent = not reply_started

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
                                    "replayed": replayed, "superseded": False, "zone": zone,
                                    "clips": clip_results})
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
