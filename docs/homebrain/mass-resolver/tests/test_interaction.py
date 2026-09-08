#!/usr/bin/env python3
"""AU-02/03 InteractionCapability unit tests. Run: python tests/test_interaction.py"""
import os, sys, threading, time, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import capability, interaction, core


class FakeHA(object):
    def __init__(self, state=None, boom=None, write_boom=None):
        self._state = state
        self._boom = boom
        self._write_boom = write_boom
        self._states = None
        self.calls = []                              # (domain, service, data)
        self.timeouts = []                           # (service, timeout)
        self.tts_url = None                          # what tts_get_url() should return
        self.tts_calls = []                          # (engine_id, message)
        self.tts_boom = None
        self.state_timeouts = []                     # per-read timeout, as get_entity_state got it
        self.media_url = None                        # what resolve_media_source() should return
        self.resolve_calls = []                      # media-source URIs asked for
    def tts_get_url(self, engine_id, message, timeout=10):
        self.tts_calls.append((engine_id, message))
        if self.tts_boom is not None:
            raise self.tts_boom
        return self.tts_url
    def resolve_media_source(self, uri, timeout=10):
        self.resolve_calls.append(uri)
        return self.media_url

    def set_states(self, states):
        self._states = list(states)
    def get_entity_state(self, entity_id, timeout=None):
        # AN-01 Task 7 gave the real get_entity_state a per-call timeout so a read can be clipped
        # to what is left of a phase deadline. Mirrored here, and recorded, because Task 11's
        # _play_clip_and_wait is the caller that actually does the clipping.
        self.state_timeouts.append(timeout)
        if self._boom is not None:
            raise self._boom
        if self._states:
            return self._states.pop(0)
        return self._state
    def call_service_rest(self, domain, service, data, timeout=5):
        if self._write_boom is not None:
            raise self._write_boom
        self.calls.append((domain, service, data))
        self.timeouts.append((service, timeout))


class FakeSettings(object):
    ceiling_entity = "media_player.ceiling_speakers"
    interaction_floor = 15
    max_duck_timeout = 45000
    interaction_ignore_when_idle = True
    announce_failures = True
    reply_volume = 0.40
    say_start_timeout_ms = 5000
    say_reply_timeout_ms = 30000
    say_poll_ms = 500
    say_internal_base = "192.168.122.10:8123"
    say_owns_restore = True
    # AN-01 Task 9 tunables. Mirrored here so announce tests run against production values rather
    # than getattr() fallbacks. Note announce_mic_mute_entity is EMPTY in config.py by design and
    # populated only in config.json, so a value is set here explicitly for tests that need one.
    announce_volume = 0.80
    announce_prefix = ""
    announce_max_prefix_chars = 40
    announce_chime_uri = "media-source://media_source/local/timer_chime.wav"   # no "./" -- AN-1/D4
    announce_mic_mute_entity = "switch.respeaker_test_microphone_mute"
    announce_require_mic_mute = True
    announce_mic_confirm_timeout_ms = 2000
    announce_mic_confirm_poll_ms = 250
    announce_mic_deadman_ms = 0
    announce_volume_deadman_ms = 0
    announce_volume_deadman_retries = 3
    announce_chime_finish_timeout_ms = 15000
    announce_message_finish_timeout_ms = 45000
    announce_max_chars = 300
    announce_min_call_timeout_ms = 500


class FakeSleeper(object):
    """No-op sleeper for tests; records call count and optionally fires a hook per call
    (used to simulate a barge-in gen bump mid-poll)."""
    def __init__(self, hook=None):
        self.calls = 0
        self._hook = hook

    def __call__(self, secs):
        self.calls += 1
        if self._hook is not None:
            self._hook(self.calls)


class FakeSpeaker(object):
    def __init__(self): self.said = []
    def speak(self, text):
        if text: self.said.append(text)


class FakeCtx(object):
    def __init__(self, ha):
        self.ha = ha
        self.settings = FakeSettings()


def playing(vol):
    return {"state": "playing", "attributes": {"volume_level": vol}}


def radio_playing(mid):
    return {"state": "playing", "attributes": {"media_content_id": mid}}


def idle_state():
    return {"state": "idle", "attributes": {}}


def playing_with_id(vol, mid):
    return {"state": "playing", "attributes": {"volume_level": vol, "media_content_id": mid}}


def run(cap, ctx, params):
    return capability.run(cap, ctx, params, "rid1")


class ResolveValidateTest(unittest.TestCase):
    def test_default_zone_is_ceiling(self):
        cap = interaction.InteractionCapability()
        r = cap.resolve(FakeCtx(FakeHA()), {"mode": "duck"})
        self.assertEqual(r["zone"], "media_player.ceiling_speakers")
        self.assertEqual(r["mode"], "duck")

    def test_explicit_zone(self):
        cap = interaction.InteractionCapability()
        r = cap.resolve(FakeCtx(FakeHA()), {"mode": "restore", "zone": "media_player.x"})
        self.assertEqual(r["zone"], "media_player.x")

    def test_invalid_mode_rejected(self):
        cap = interaction.InteractionCapability()
        r = run(cap, FakeCtx(FakeHA(playing(0.3))), {"mode": "sideways"})
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"]["code"], "invalid_input")


class SayResolveValidateTest(unittest.TestCase):
    def test_resolve_uri_and_defaults(self):
        cap = interaction.InteractionCapability()
        r = cap.resolve(FakeCtx(FakeHA()), {"mode": "say", "uri": "http://x/a.flac"})
        self.assertEqual(r["mode"], "say")
        self.assertEqual(r["uri"], "http://x/a.flac")
        self.assertEqual(r["zone"], "media_player.ceiling_speakers")

    def test_resolve_media_content_id_alias(self):
        cap = interaction.InteractionCapability()
        r = cap.resolve(FakeCtx(FakeHA()), {"mode": "say", "media_content_id": "http://x/b.flac"})
        self.assertEqual(r["uri"], "http://x/b.flac")

    def test_say_without_uri_rejected(self):
        cap = interaction.InteractionCapability()
        r = run(cap, FakeCtx(FakeHA(playing(0.3))), {"mode": "say"})
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"]["code"], "invalid_input")


class FakeTimer(object):
    created = []
    def __init__(self, interval, fn, args=None):
        self.interval = interval; self.fn = fn; self.args = args or []
        self.started = False; self.cancelled = False
        FakeTimer.created.append(self)
    def start(self): self.started = True
    def cancel(self): self.cancelled = True
    def fire(self): self.fn(*self.args)


class DuckTest(unittest.TestCase):
    def setUp(self):
        FakeTimer.created = []
        self.cap = interaction.InteractionCapability(timer_factory=FakeTimer, clock=lambda: 1000.0)

    def test_duck_snapshots_and_sets_floor(self):
        ha = FakeHA(playing(0.40)); ctx = FakeCtx(ha)
        r = run(self.cap, ctx, {"mode": "duck"})
        self.assertTrue(r["ok"]); self.assertIsNone(r["spoken_text"])
        self.assertTrue(r["metadata"]["ducked"])
        self.assertEqual(len(ha.calls), 1)
        domain, service, data = ha.calls[0]
        self.assertEqual((domain, service), ("media_player", "volume_set"))
        self.assertEqual(data["entity_id"], "media_player.ceiling_speakers")
        self.assertAlmostEqual(data["volume_level"], 0.15)          # floor 15%
        self.assertAlmostEqual(r["metadata"]["from"], 0.40)

    def test_duck_ignored_when_not_playing(self):
        ha = FakeHA({"state": "idle", "attributes": {"volume_level": 0.4}}); ctx = FakeCtx(ha)
        r = run(self.cap, ctx, {"mode": "duck"})
        self.assertTrue(r["ok"])
        self.assertFalse(r["metadata"]["ducked"])
        self.assertEqual(ha.calls, [])                              # no volume change

    def test_duck_ignored_when_no_volume(self):
        ha = FakeHA({"state": "playing", "attributes": {}}); ctx = FakeCtx(ha)   # playing but no volume_level
        r = run(self.cap, ctx, {"mode": "duck"})
        self.assertTrue(r["ok"])
        self.assertFalse(r["metadata"]["ducked"])
        self.assertEqual(r["metadata"]["reason"], "no_volume")
        self.assertEqual(ha.calls, [])                              # never duck what we can't restore

    def test_re_duck_coalesces_keeps_original_baseline(self):
        ha = FakeHA(playing(0.40)); ctx = FakeCtx(ha)
        run(self.cap, ctx, {"mode": "duck"})                        # snapshot 0.40
        ha._state = playing(0.15)                                   # now at floor
        r2 = run(self.cap, ctx, {"mode": "duck"})                   # re-duck
        self.assertAlmostEqual(self.cap._snaps["media_player.ceiling_speakers"]["volume"], 0.40)
        self.assertTrue(r2["metadata"]["ducked"])

    def test_duck_schedules_dead_man_timer(self):
        ha = FakeHA(playing(0.40)); ctx = FakeCtx(ha)
        run(self.cap, ctx, {"mode": "duck"})
        self.assertEqual(len(FakeTimer.created), 1)
        self.assertTrue(FakeTimer.created[0].started)
        self.assertAlmostEqual(FakeTimer.created[0].interval, 45.0)  # FakeSettings max_duck_timeout 45000ms -> 45s


class SayPlayMediaTest(unittest.TestCase):
    def setUp(self):
        FakeTimer.created = []
        self.zone = "media_player.ceiling_speakers"
        self.norm_uri = "http://192.168.122.10:8123/api/tts_proxy/x.mp3"
        # REALITY (live-captured): Music Assistant does not echo the raw URL back as
        # media_content_id -- it wraps it, e.g. "builtin://radio/<url>". Poll matching
        # must use containment, not equality; these tests script the prefixed form.
        self.reply_mid = "builtin://radio/" + self.norm_uri

    def _cap(self, hook=None):
        cap = interaction.InteractionCapability(timer_factory=FakeTimer, clock=lambda: 1000.0,
                                                sleeper=FakeSleeper(hook))
        return cap

    def test_uri_normalised_to_internal_base(self):
        cap = self._cap()
        ha = FakeHA()
        ha.set_states([
            idle_state(),                                   # capture (before)
            playing_with_id(0.40, self.reply_mid),          # start-poll: MA-wrapped media_content_id
            idle_state(),                                   # finish-poll: reply ended
        ])
        ctx = FakeCtx(ha)
        r = run(cap, ctx, {"mode": "say", "uri": "http://192.168.1.104:8123/api/tts_proxy/x.mp3"})
        self.assertTrue(r["ok"])
        pm = [c for c in ha.calls if c[1] == "play_media"]
        self.assertEqual(len(pm), 1)
        self.assertEqual(pm[0][2]["media_id"], self.norm_uri)

    def test_happy_path_volume_before_play_then_replay_after_finish(self):
        cap = self._cap()
        ha = FakeHA()
        ha.set_states([
            playing_with_id(0.55, "library://track/9"),     # capture: was playing local track
            playing_with_id(0.40, self.reply_mid),          # start-poll: MA-wrapped media_content_id
            idle_state(),                                   # finish-poll: reply ended
        ])
        ctx = FakeCtx(ha)
        r = run(cap, ctx, {"mode": "say", "uri": self.norm_uri})
        self.assertTrue(r["ok"]); self.assertIsNone(r["spoken_text"])
        self.assertTrue(r["metadata"]["reply_started"])
        self.assertFalse(r["metadata"]["likely_silent"])
        self.assertTrue(r["metadata"]["replayed"])
        self.assertFalse(r["metadata"]["superseded"])
        # order: volume_set(reply_volume) BEFORE play_media(reply)
        service_order = [c[1] for c in ha.calls]
        vol_idx = service_order.index("volume_set")
        pm_indices = [i for i, s in enumerate(service_order) if s == "play_media"]
        self.assertTrue(vol_idx < pm_indices[0])
        vol_call = ha.calls[vol_idx]
        self.assertAlmostEqual(vol_call[2]["volume_level"], 0.40)          # FakeSettings.reply_volume
        reply_pm = ha.calls[pm_indices[0]]
        self.assertEqual(reply_pm[2]["media_id"], self.norm_uri)
        # replay of the captured source happens after the clip ends
        replay_pm = ha.calls[pm_indices[1]]
        self.assertEqual(replay_pm[2]["media_id"], "library://track/9")

    def test_ma_wrapped_media_content_id_is_not_exact_match(self):
        # Documents the prefix behaviour: exact-equality against the raw normalised URI
        # must NOT match the MA-wrapped form, but containment must. A future regression
        # to exact-match would fail this assertion (and re-break start-poll detection).
        self.assertNotEqual(self.reply_mid, self.norm_uri)
        self.assertIn(self.norm_uri, self.reply_mid)

    def test_reply_never_starts_still_restores_and_replays(self):
        cap = self._cap()
        ha = FakeHA()
        # capture + 10 start-poll reads (say_start_timeout_ms=5000 / say_poll_ms=500), never matches
        states = [playing_with_id(0.55, "library://track/9")] + [idle_state()] * 10
        ha.set_states(states)
        ctx = FakeCtx(ha)
        r = run(cap, ctx, {"mode": "say", "uri": self.norm_uri})
        self.assertTrue(r["ok"])
        self.assertFalse(r["metadata"]["reply_started"])
        self.assertTrue(r["metadata"]["likely_silent"])
        self.assertTrue(r["metadata"]["replayed"])
        vol_calls = [c for c in ha.calls if c[1] == "volume_set"]
        self.assertEqual(len(vol_calls), 2)                 # reply volume, then restore
        pm_calls = [c for c in ha.calls if c[1] == "play_media"]
        self.assertEqual(len(pm_calls), 2)                  # reply attempt, then source replay
        self.assertEqual(pm_calls[1][2]["media_id"], "library://track/9")

    def test_barge_in_supersede_aborts_restore_and_replay(self):
        zone = self.zone

        def bump_gen(n):
            if n == 1:                                       # bump mid start-poll, on the first sleep
                cap._say_gen[zone] = cap._say_gen.get(zone, 0) + 1

        cap = interaction.InteractionCapability(timer_factory=FakeTimer, clock=lambda: 1000.0)
        cap._sleeper = FakeSleeper(bump_gen)
        ha = FakeHA()
        ha.set_states([
            playing_with_id(0.55, "library://track/9"),      # capture
            idle_state(),                                     # start-poll #1: not started -> sleeps -> gen bumped
            idle_state(),                                     # start-poll #2: superseded check trips here
        ])
        ctx = FakeCtx(ha)
        r = run(cap, ctx, {"mode": "say", "uri": self.norm_uri})
        self.assertTrue(r["ok"])
        self.assertTrue(r["metadata"]["superseded"])
        vol_calls = [c for c in ha.calls if c[1] == "volume_set"]
        self.assertEqual(len(vol_calls), 1)                 # only the initial reply-volume set; no restore
        pm_calls = [c for c in ha.calls if c[1] == "play_media"]
        self.assertEqual(len(pm_calls), 1)                  # only the reply attempt; no source replay

    def test_restore_targets_duck_baseline_when_owns_restore(self):
        cap = self._cap()
        ha = FakeHA(playing(0.40)); ctx = FakeCtx(ha)
        run(cap, ctx, {"mode": "duck"})                      # seed baseline 0.40 in cap._snaps
        ha.calls = []
        ha.set_states([
            idle_state(),                                    # capture
            playing_with_id(0.40, self.reply_mid),           # start-poll: MA-wrapped media_content_id
            idle_state(),                                    # finish-poll: ended
        ])
        r = run(cap, ctx, {"mode": "say", "uri": self.norm_uri})
        self.assertTrue(r["ok"])
        vol_calls = [c for c in ha.calls if c[1] == "volume_set"]
        self.assertAlmostEqual(vol_calls[-1][2]["volume_level"], 0.40)     # restored to duck baseline

    def test_restore_falls_back_to_prev_volume_when_snapshot_popped_concurrently(self):
        # simulates a dead-man timer / S1a _restore() popping self._snaps[zone] mid-reply:
        # say_owns_restore=True but the snapshot is gone by the time the restore step runs.
        cap = self._cap()
        ha = FakeHA(playing(0.40)); ctx = FakeCtx(ha)
        run(cap, ctx, {"mode": "duck"})                      # seed baseline 0.40 in cap._snaps
        cap._snaps.pop("media_player.ceiling_speakers", None)  # concurrent pop before restore step
        ha.calls = []
        ha.set_states([
            playing(0.55),                                   # capture: prev_volume=0.55
            playing_with_id(0.40, self.reply_mid),           # start-poll: MA-wrapped media_content_id
            idle_state(),                                    # finish-poll: ended
        ])
        r = run(cap, ctx, {"mode": "say", "uri": self.norm_uri})
        self.assertTrue(r["ok"])
        vol_calls = [c for c in ha.calls if c[1] == "volume_set"]
        self.assertEqual(len(vol_calls), 2)                  # reply volume, then restore still happens
        self.assertAlmostEqual(vol_calls[-1][2]["volume_level"], 0.55)  # falls back to prev_volume, not skipped

    def test_restore_targets_prev_volume_when_not_owns_restore(self):
        class NoOwnRestoreSettings(FakeSettings):
            say_owns_restore = False
        cap = self._cap()
        ha = FakeHA(); ctx = FakeCtx(ha)
        ctx.settings = NoOwnRestoreSettings()
        ha.set_states([
            playing(0.62),                                   # capture: prev_volume=0.62, no media_content_id
            playing_with_id(0.40, self.reply_mid),            # start-poll: MA-wrapped media_content_id
            idle_state(),                                     # finish-poll: ended
        ])
        r = run(cap, ctx, {"mode": "say", "uri": self.norm_uri})
        self.assertTrue(r["ok"])
        vol_calls = [c for c in ha.calls if c[1] == "volume_set"]
        self.assertAlmostEqual(vol_calls[-1][2]["volume_level"], 0.62)     # restored to captured prev_volume


class RestoreTest(unittest.TestCase):
    def setUp(self):
        FakeTimer.created = []
        self.cap = interaction.InteractionCapability(timer_factory=FakeTimer, clock=lambda: 1000.0)

    def test_restore_returns_to_snapshot(self):
        ha = FakeHA(playing(0.40)); ctx = FakeCtx(ha)
        run(self.cap, ctx, {"mode": "duck"})                        # snapshot 0.40, now at 0.15
        ha._state = playing(0.15)                                   # unchanged since our duck
        ha.calls = []
        r = run(self.cap, ctx, {"mode": "restore"})
        self.assertTrue(r["metadata"]["restored"])
        self.assertEqual(len(ha.calls), 1)
        _, _, data = ha.calls[0]
        self.assertAlmostEqual(data["volume_level"], 0.40)
        self.assertNotIn("media_player.ceiling_speakers", self.cap._snaps)   # snapshot cleared
        self.assertTrue(FakeTimer.created[0].cancelled)             # dead-man cancelled

    def test_restore_last_writer_wins_when_user_changed(self):
        ha = FakeHA(playing(0.40)); ctx = FakeCtx(ha)
        run(self.cap, ctx, {"mode": "duck"})                        # floor 0.15
        ha._state = playing(0.55)                                   # user bumped it mid-interaction
        ha.calls = []
        r = run(self.cap, ctx, {"mode": "restore"})
        self.assertFalse(r["metadata"]["restored"])
        self.assertEqual(r["metadata"]["reason"], "user_override")
        self.assertEqual(ha.calls, [])                              # do not clobber the user's 0.55

    def test_restore_without_snapshot_is_noop(self):
        ha = FakeHA(playing(0.30)); ctx = FakeCtx(ha)
        r = run(self.cap, ctx, {"mode": "restore"})
        self.assertTrue(r["ok"]); self.assertFalse(r["metadata"]["restored"])
        self.assertEqual(ha.calls, [])


class DeadManTest(unittest.TestCase):
    def setUp(self):
        FakeTimer.created = []
        self.cap = interaction.InteractionCapability(timer_factory=FakeTimer, clock=lambda: 1000.0)

    def test_timeout_auto_restores(self):
        ha = FakeHA(playing(0.40)); ctx = FakeCtx(ha)
        run(self.cap, ctx, {"mode": "duck"})                        # snapshot 0.40
        ha._state = playing(0.15); ha.calls = []                    # still at floor
        FakeTimer.created[0].fire()                                 # dead-man fires
        self.assertNotIn("media_player.ceiling_speakers", self.cap._snaps)
        self.assertEqual(len(ha.calls), 1)
        _, _, data = ha.calls[0]
        self.assertAlmostEqual(data["volume_level"], 0.40)         # restored to baseline


class Round2FindingsTest(unittest.TestCase):
    def setUp(self):
        FakeTimer.created = []
        self.cap = interaction.InteractionCapability(timer_factory=FakeTimer, clock=lambda: 1000.0)

    def test_duck_never_goes_upward(self):                          # finding #7
        ha = FakeHA(playing(0.10)); ctx = FakeCtx(ha)                # already below floor 0.15
        r = run(self.cap, ctx, {"mode": "duck"})
        self.assertTrue(r["ok"])
        self.assertEqual(len(ha.calls), 1)
        _, _, data = ha.calls[0]
        self.assertAlmostEqual(data["volume_level"], 0.10)           # min(0.10, 0.15) == 0.10
        self.assertAlmostEqual(self.cap._snaps["media_player.ceiling_speakers"]["target"], 0.10)

    def test_restore_write_failure_keeps_snapshot_and_timer(self):  # finding #1
        ha = FakeHA(playing(0.40)); ctx = FakeCtx(ha)
        run(self.cap, ctx, {"mode": "duck"})                        # snapshot 0.40, target 0.15
        # Swap ctx.ha: reads the floor (no user-override short-circuit) but the write raises.
        ctx.ha = FakeHA(playing(0.15), write_boom=IOError("nope"))
        r = run(self.cap, ctx, {"mode": "restore"})
        self.assertFalse(r["ok"])
        self.assertIn("media_player.ceiling_speakers", self.cap._snaps)
        self.assertFalse(FakeTimer.created[0].cancelled)

    def test_missing_max_duck_timeout_falls_back_to_120s(self):     # finding #6
        class SettingsNoTimeout(object):
            ceiling_entity = "media_player.ceiling_speakers"
            interaction_floor = 15
            interaction_ignore_when_idle = True
        ha = FakeHA(playing(0.40))
        ctx = FakeCtx(ha)
        ctx.settings = SettingsNoTimeout()
        run(self.cap, ctx, {"mode": "duck"})
        self.assertEqual(len(FakeTimer.created), 1)
        self.assertAlmostEqual(FakeTimer.created[0].interval, 120.0)

    def test_write_happens_while_lock_held(self):                   # finding #5
        cap = self.cap
        held = {"locked": None}
        class LockCheckingHA(object):
            def __init__(self, cap):
                self._cap = cap
                self.calls = []
            def get_entity_state(self, entity_id):
                return playing(0.40)
            def call_service_rest(self, domain, service, data):
                held["locked"] = self._cap._lock.locked()
                self.calls.append((domain, service, data))
        ha = LockCheckingHA(cap)
        ctx = FakeCtx(ha)
        run(cap, ctx, {"mode": "duck"})
        self.assertTrue(held["locked"])


class Round3FindingsTest(unittest.TestCase):
    def setUp(self):
        FakeTimer.created = []
        self.cap = interaction.InteractionCapability(timer_factory=FakeTimer, clock=lambda: 1000.0)

    def test_c1_failed_first_duck_write_still_snapshots_and_arms(self):
        zone = "media_player.ceiling_speakers"
        ha = FakeHA(playing(0.40), write_boom=IOError("nope"))
        ctx = FakeCtx(ha)
        r = run(self.cap, ctx, {"mode": "duck"})
        self.assertFalse(r["ok"])
        self.assertIn(zone, self.cap._snaps)                        # snapshot survives the failed write
        self.assertTrue(FakeTimer.created[0].started)
        self.assertFalse(FakeTimer.created[0].cancelled)
        # dead-man later reconciles: swap in a working HA and fire the armed timer.
        ctx.ha = FakeHA(playing(0.40))
        FakeTimer.created[0].fire()
        self.assertNotIn(zone, self.cap._snaps)                     # cleaned up, no permanent strand

    def test_c2_re_duck_syncs_target_avoids_false_override(self):
        zone = "media_player.ceiling_speakers"
        ha = FakeHA(playing(0.40)); ctx = FakeCtx(ha)
        run(self.cap, ctx, {"mode": "duck"})                        # baseline 0.40, target 0.15
        ha._state = playing(0.05)                                   # user dropped further
        r2 = run(self.cap, ctx, {"mode": "duck"})                   # re-duck: writes 0.05
        self.assertTrue(r2["metadata"]["ducked"])
        self.assertAlmostEqual(self.cap._snaps[zone]["target"], 0.05)
        ha._state = playing(0.05)                                   # device now at our last-written value
        ha.calls = []
        r3 = run(self.cap, ctx, {"mode": "restore"})
        self.assertTrue(r3["metadata"]["restored"])                 # not a false user_override
        self.assertEqual(len(ha.calls), 1)
        _, _, data = ha.calls[0]
        self.assertAlmostEqual(data["volume_level"], 0.40)          # reaches the real baseline

    def test_f3_rearm_loop_survives_repeated_auto_restore_failure(self):
        zone = "media_player.ceiling_speakers"
        ha = FakeHA(playing(0.40)); ctx = FakeCtx(ha)
        run(self.cap, ctx, {"mode": "duck"})                        # snapshot 0.40, target 0.15
        ha._state = playing(0.15)                                   # still at floor, not a user override
        ha.calls = []
        first_timer = FakeTimer.created[0]
        real_write = ha.call_service_rest
        calls = {"n": 0}
        def flaky_write(domain, service, data):
            calls["n"] += 1
            if calls["n"] == 1:
                raise IOError("first restore write fails")
            return real_write(domain, service, data)
        ha.call_service_rest = flaky_write
        first_timer.fire()                                          # _auto_restore -> _restore raises -> re-arm
        self.assertEqual(len(FakeTimer.created), 2)                 # a NEW timer was armed
        self.assertIn(zone, self.cap._snaps)                        # snapshot still present
        second_timer = FakeTimer.created[1]
        self.assertFalse(second_timer.cancelled)
        second_timer.fire()                                         # second fire succeeds
        self.assertNotIn(zone, self.cap._snaps)                     # cleaned up
        self.assertEqual(len(ha.calls), 1)                          # only the successful write recorded

    def test_f5_restore_logs_and_recovers_from_read_failure(self):
        ha = FakeHA(playing(0.40)); ctx = FakeCtx(ha)
        run(self.cap, ctx, {"mode": "duck"})                        # snapshot 0.40
        ctx.ha = FakeHA(boom=IOError("read broke"))                 # get_entity_state raises; write still ok
        with self.assertLogs("resolver", level="WARNING") as cm:
            r = run(self.cap, ctx, {"mode": "restore"})
        self.assertTrue(r["metadata"]["restored"])                  # fail-safe: still restores baseline
        self.assertAlmostEqual(r["metadata"]["to"], 0.40)
        self.assertTrue(any("read failed" in m for m in cm.output))  # logged, not silent

    def test_user_override_cancels_timer_and_pops_snapshot(self):
        zone = "media_player.ceiling_speakers"
        ha = FakeHA(playing(0.40)); ctx = FakeCtx(ha)
        run(self.cap, ctx, {"mode": "duck"})                        # target 0.15
        ha._state = playing(0.55)                                   # user bumped it away from our target
        ha.calls = []
        r = run(self.cap, ctx, {"mode": "restore"})
        self.assertFalse(r["metadata"]["restored"])
        self.assertEqual(r["metadata"]["reason"], "user_override")
        self.assertEqual(ha.calls, [])                               # never clobbers the user's value
        self.assertTrue(FakeTimer.created[0].cancelled)              # dead-man cancelled
        self.assertNotIn(zone, self.cap._snaps)                      # snapshot popped, no permanent strand


class RealThreadingTest(unittest.TestCase):
    def setUp(self):
        FakeTimer.created = []
        self.cap = interaction.InteractionCapability(timer_factory=FakeTimer, clock=lambda: 1000.0)

    def test_lock_provides_true_mutual_exclusion_across_threads(self):
        started = threading.Event()
        release = threading.Event()
        b_done = threading.Event()

        class BlockingHA(object):
            def __init__(self):
                self.calls = []
                self._n = 0
            def get_entity_state(self, entity_id):
                return playing(0.40)
            def call_service_rest(self, domain, service, data):
                self._n += 1
                if self._n == 1:                                    # first writer (thread A) blocks here
                    started.set()
                    release.wait(5)
                self.calls.append((domain, service, data))

        ha = BlockingHA()
        ctx = FakeCtx(ha)

        def thread_a():
            run(self.cap, ctx, {"mode": "duck"})

        def thread_b():
            run(self.cap, ctx, {"mode": "duck"})
            b_done.set()

        ta = threading.Thread(target=thread_a)
        ta.start()
        self.assertTrue(started.wait(5), "thread A never reached the blocking write")
        tb = threading.Thread(target=thread_b)
        tb.start()
        time.sleep(0.1)                                              # give B a chance to try to acquire _lock
        self.assertFalse(b_done.is_set(), "thread B completed while A still held the lock")
        release.set()                                                # let A finish, then B can proceed
        ta.join(5)
        tb.join(5)
        self.assertFalse(ta.is_alive(), "thread A join timed out")
        self.assertFalse(tb.is_alive(), "thread B join timed out")
        self.assertTrue(b_done.is_set(), "thread B never completed after A released the lock")
        self.assertEqual(len(ha.calls), 2)


class CoreWiringTest(unittest.TestCase):
    def test_interaction_registered_in_caps_not_stubs(self):
        self.assertIn("interaction", core.CAPS)
        self.assertIsInstance(core.CAPS["interaction"], interaction.InteractionCapability)
        self.assertNotIn("interaction", core._STUBS)

    def test_dispatch_duck_is_silent(self):
        ha = FakeHA(playing(0.40))
        spk = FakeSpeaker()
        ctx = core.Ctx(ma_factory=lambda: None, ha=ha, settings=FakeSettings(),
                       radio_cfg={}, news_cfg={}, speaker=spk)
        r = core.dispatch(ctx, "interaction", {"mode": "duck"})
        self.assertTrue(r["ok"]); self.assertEqual(r["intent"], "interaction")
        self.assertTrue(r["metadata"]["ducked"])
        self.assertEqual(spk.said, [])                              # silent: no TTS


class SayDispatchTest(unittest.TestCase):
    def test_dispatch_say_is_silent(self):
        norm_uri = "http://192.168.122.10:8123/a.flac"
        reply_mid = "builtin://radio/" + norm_uri            # MA-wrapped media_content_id
        ha = FakeHA()
        ha.set_states([idle_state(), playing_with_id(0.40, reply_mid), idle_state()])
        spk = FakeSpeaker()
        ctx = core.Ctx(ma_factory=lambda: None, ha=ha, settings=FakeSettings(),
                       radio_cfg={}, news_cfg={}, speaker=spk)
        r = core.dispatch(ctx, "interaction", {"mode": "say", "uri": "http://x/a.flac"})
        self.assertTrue(r["ok"]); self.assertEqual(r["intent"], "interaction")
        self.assertTrue(r["metadata"]["said"])
        self.assertEqual(spk.said, [])                              # silent: no TTS
        # End-to-end: verify _say mechanism fired through dispatch via play_media
        pm = [c for c in ha.calls if c[1] == "play_media"]
        self.assertEqual(len(pm), 1)
        self.assertEqual(pm[0][0], "music_assistant")
        self.assertEqual(pm[0][2]["media_id"], norm_uri)
        self.assertIn("replayed", r["metadata"])                    # capture/replay metadata present
        self.assertFalse(r["metadata"]["replayed"])                 # not playing before -> no replay


class ObservabilitySettings(FakeSettings):
    reply_volume = 0.70
    say_call_timeout_ms = 20000
    say_double_speak_window_ms = 8000


class AnnouncingSpeaker(object):
    """Stands in for resolver.Speaker: records when it last put a voice on the zone."""
    def __init__(self, last_announce_ts=None, text="I couldn't find a station for norok."):
        self.last_announce_ts = last_announce_ts
        self.last_announce_text = text


class SayObservabilityTest(unittest.TestCase):
    """The visibility gaps that made the live double-speak turn hard to read:
    no SAY start line, no attribution for which service call timed out, and no signal that a
    second voice had just spoken on the same zone."""

    def setUp(self):
        FakeTimer.created = []
        self.zone = "media_player.ceiling_speakers"
        self.norm_uri = "http://192.168.122.10:8123/api/tts_proxy/x.mp3"
        self.reply_mid = "builtin://radio/" + self.norm_uri

    def _cap(self, clock=None):
        return interaction.InteractionCapability(timer_factory=FakeTimer,
                                                clock=clock or (lambda: 1000.0),
                                                sleeper=FakeSleeper())

    def _ctx(self, ha):
        ctx = FakeCtx(ha)
        ctx.settings = ObservabilitySettings()
        return ctx

    def _happy_states(self):
        return [playing_with_id(0.32, "library://radio/18"),
                playing_with_id(0.70, self.reply_mid),
                idle_state()]

    def test_say_logs_a_start_line_with_a_clip_fingerprint_not_the_uri(self):
        cap = self._cap()
        ha = FakeHA(); ctx = self._ctx(ha)
        ha.set_states(self._happy_states())
        with self.assertLogs("resolver", level="INFO") as cm:
            run(cap, ctx, {"mode": "say", "uri": self.norm_uri})
        starts = [m for m in cm.output if "SAY start" in m]
        self.assertEqual(len(starts), 1)
        self.assertIn("clip=" + cap._clip_id(self.norm_uri), starts[0])
        # the reply URL itself must never reach the log
        self.assertNotIn("tts_proxy", "\n".join(cm.output))

    def test_double_speak_is_reported_when_resolver_just_announced(self):
        cap = self._cap()
        ha = FakeHA(); ctx = self._ctx(ha)
        ctx.speaker = AnnouncingSpeaker(last_announce_ts=997.0)     # 3s before this reply
        ha.set_states(self._happy_states())
        with self.assertLogs("resolver", level="WARNING") as cm:
            run(cap, ctx, {"mode": "say", "uri": self.norm_uri})
        self.assertTrue(any("DOUBLE-SPEAK" in m for m in cm.output), cm.output)

    def test_no_double_speak_warning_for_an_old_or_absent_announce(self):
        for speaker_obj in (AnnouncingSpeaker(last_announce_ts=980.0),   # 20s ago, outside window
                            AnnouncingSpeaker(last_announce_ts=None),    # never announced
                            None):                                       # no speaker wired
            cap = self._cap()
            ha = FakeHA(); ctx = self._ctx(ha)
            if speaker_obj is not None:
                ctx.speaker = speaker_obj
            ha.set_states(self._happy_states())
            with self.assertLogs("resolver", level="INFO") as cm:
                run(cap, ctx, {"mode": "say", "uri": self.norm_uri})
            self.assertFalse(any("DOUBLE-SPEAK" in m for m in cm.output), cm.output)

    def test_play_media_gets_the_long_timeout_and_volume_set_does_not(self):
        # MA play_media outran the 5s REST default live, aborting the turn while the clip played.
        cap = self._cap()
        ha = FakeHA(); ctx = self._ctx(ha)
        ha.set_states(self._happy_states())
        run(cap, ctx, {"mode": "say", "uri": self.norm_uri})
        by_service = {}
        for service, timeout in ha.timeouts:
            by_service.setdefault(service, []).append(timeout)
        self.assertEqual(by_service["play_media"], [20.0, 20.0])    # reply + replay
        self.assertEqual(by_service["volume_set"], [5, 5])          # unchanged default

    def test_failed_call_is_attributed_with_service_and_elapsed(self):
        cap = self._cap()
        ha = FakeHA(playing(0.32)); ctx = self._ctx(ha)
        real_write = ha.call_service_rest

        def boom(domain, service, data, timeout=None):
            if service == "play_media":
                raise IOError("timed out")
            real_write(domain, service, data)
        ha.call_service_rest = boom
        ha.set_states([playing_with_id(0.32, "library://radio/18")])
        with self.assertLogs("resolver", level="ERROR") as cm:
            r = run(cap, ctx, {"mode": "say", "uri": self.norm_uri})
        self.assertFalse(r["ok"])
        self.assertTrue(any("music_assistant.play_media failed after" in m for m in cm.output), cm.output)


class OwnershipSettings(FakeSettings):
    """Production-shaped: reply_volume distinct from both the baseline and the duck floor,
    so a restore to the wrong value is unambiguous in assertions."""
    reply_volume = 0.70


class DuckOwnershipSlice4Test(unittest.TestCase):
    """S1b-2 Slice 4 -- the reply-turn volume ratchet/crater.

    Root cause: S1a's `idle->restore` fires while `_say` is still polling the reply clip. It reads
    `_say`'s reply volume, misreads it as a human change (`user_override`), and DISCARDS the duck
    snapshot. `_say`'s own restore then finds no snapshot and falls back to `prev_volume` -- which is
    the already-ducked floor -- so the ceiling craters; and with no surviving baseline the next turn
    captures the inflated reply volume instead, so it ratchets. Decision (b): `_say` is the sole
    reply-turn restore owner.
    """

    def setUp(self):
        FakeTimer.created = []
        self.zone = "media_player.ceiling_speakers"
        self.norm_uri = "http://192.168.122.10:8123/api/tts_proxy/x.mp3"
        self.reply_mid = "builtin://radio/" + self.norm_uri

    def _ctx(self, ha):
        ctx = FakeCtx(ha)
        ctx.settings = OwnershipSettings()
        return ctx

    def test_idle_restore_during_reply_does_not_crater_or_ratchet(self):
        # THE REPRO: full turn with S1a's idle->restore landing mid-reply.
        cap = interaction.InteractionCapability(timer_factory=FakeTimer, clock=lambda: 1000.0)
        ha = FakeHA(playing(0.32))
        ctx = self._ctx(ha)
        run(cap, ctx, {"mode": "duck"})                       # baseline 0.32 -> floor 0.15
        ha.calls = []
        seen = {}

        def s1a_idle_restore(n):
            if n == 1:                                        # first finish-poll sleep == satellite idle
                seen["restore"] = run(cap, ctx, {"mode": "restore"})
                seen["snap_after_restore"] = dict(cap._snaps.get(self.zone) or {})

        cap._sleeper = FakeSleeper(s1a_idle_restore)
        ha.set_states([
            playing_with_id(0.15, "library://radio/2"),       # _say capture: prev_volume IS the duck floor
            playing_with_id(0.70, self.reply_mid),             # start-poll: reply playing at reply_volume
            playing_with_id(0.70, self.reply_mid),             # finish-poll #1: still playing -> sleep -> S1a fires
            playing_with_id(0.70, self.reply_mid),             # the interleaved _restore's own read
            idle_state(),                                      # finish-poll #2: clip ended
            idle_state(),                                      # ... confirmed (2-sample debounce)
            playing(0.70),                                     # _say's restore-step read: still ours
        ])
        r = run(cap, ctx, {"mode": "say", "uri": self.norm_uri})
        self.assertTrue(r["ok"])
        self.assertTrue(r["metadata"]["reply_started"])

        # 1. the interleaved S1a restore must DEFER to the in-flight reply, not claim a user override
        self.assertFalse(seen["restore"]["metadata"]["restored"])
        self.assertEqual(seen["restore"]["metadata"]["reason"], "reply_active")
        # 2. and it must NOT strip the baseline _say needs
        self.assertAlmostEqual(seen["snap_after_restore"].get("volume"), 0.32)
        # 3. so _say's own restore lands on the pre-duck baseline: no crater to 0.15, no strand at 0.70
        vol_calls = [c for c in ha.calls if c[1] == "volume_set"]
        self.assertEqual(len(vol_calls), 2)                    # reply volume, then exactly one restore
        self.assertAlmostEqual(vol_calls[0][2]["volume_level"], 0.70)
        self.assertAlmostEqual(vol_calls[-1][2]["volume_level"], 0.32)
        # 4. the reply owner cleans up after itself: no stale snapshot, no stale reply marker
        self.assertNotIn(self.zone, cap._snaps)
        self.assertNotIn(self.zone, cap._replies)

    def test_restore_defers_while_reply_active_and_rearms_dead_man(self):
        cap = interaction.InteractionCapability(timer_factory=FakeTimer, clock=lambda: 1000.0)
        ha = FakeHA(playing(0.32))
        ctx = self._ctx(ha)
        run(cap, ctx, {"mode": "duck"})                        # baseline 0.32, dead-man #1 armed
        cap._replies[self.zone] = {"gen": 1, "baseline": 0.32}  # a reply is in flight
        ha._state = playing(0.70)                              # device sits at _say's reply volume
        ha.calls = []
        r = run(cap, ctx, {"mode": "restore"})
        self.assertTrue(r["ok"])
        self.assertFalse(r["metadata"]["restored"])
        self.assertEqual(r["metadata"]["reason"], "reply_active")
        self.assertEqual(ha.calls, [])                         # never fights _say for the volume
        self.assertAlmostEqual(cap._snaps[self.zone]["volume"], 0.32)   # baseline preserved
        self.assertEqual(len(FakeTimer.created), 2)             # dead-man re-armed, not dropped
        self.assertTrue(FakeTimer.created[1].started)

    def test_duck_during_reply_defers_to_say(self):
        # Decision (a): the reply clip REPLACED the music, so there is nothing to duck under.
        # Ducking here would quiet the reply, and the snapshot it left would be torn down by
        # _say's restore -- leaving the zone with neither baseline nor dead-man.
        cap = interaction.InteractionCapability(timer_factory=FakeTimer, clock=lambda: 1000.0)
        ha = FakeHA(playing(0.70))                             # reply clip playing loud
        ctx = self._ctx(ha)
        cap._replies[self.zone] = {"gen": 1, "baseline": 0.32, "ts": 1000.0, "rid": "r0"}
        r = run(cap, ctx, {"mode": "duck"})
        self.assertTrue(r["ok"])
        self.assertFalse(r["metadata"]["ducked"])
        self.assertEqual(r["metadata"]["reason"], "reply_active")
        self.assertEqual(ha.calls, [])                          # never quiets the reply
        self.assertNotIn(self.zone, cap._snaps)                 # no rival snapshot for _say to pop

    def test_duck_reclaims_zone_from_a_stale_reply_marker(self):
        # A crashed/hung _say must not deafen this zone forever; and once reclaimed, the baseline
        # comes from the orphaned marker, not from the live (reply) volume.
        clock = [1000.0]
        cap = interaction.InteractionCapability(timer_factory=FakeTimer, clock=lambda: clock[0])
        ha = FakeHA(playing(0.70))
        ctx = self._ctx(ha)
        cap._replies[self.zone] = {"gen": 1, "baseline": 0.32, "ts": 1000.0, "rid": "r0"}
        clock[0] = 1000.0 + 5.0 + 30.0 + 61.0                   # past start+reply budget + margin
        r = run(cap, ctx, {"mode": "duck"})
        self.assertTrue(r["metadata"]["ducked"])
        self.assertAlmostEqual(cap._snaps[self.zone]["volume"], 0.32)   # inherited, not 0.70
        self.assertAlmostEqual(cap._snaps[self.zone]["target"], 0.15)

    def test_restore_reclaims_zone_from_a_stale_reply_marker(self):
        clock = [1000.0]
        cap = interaction.InteractionCapability(timer_factory=FakeTimer, clock=lambda: clock[0])
        ha = FakeHA(playing(0.32))
        ctx = self._ctx(ha)
        run(cap, ctx, {"mode": "duck"})                         # baseline 0.32, target 0.15
        cap._replies[self.zone] = {"gen": 1, "baseline": 0.32, "ts": 1000.0, "rid": "r0"}
        ha._state = playing(0.15)
        ha.calls = []
        clock[0] = 1000.0 + 96.0
        r = run(cap, ctx, {"mode": "restore"})
        self.assertTrue(r["metadata"]["restored"])              # backstop is not deafened forever
        self.assertAlmostEqual(ha.calls[0][2]["volume_level"], 0.32)

    def test_say_does_not_retire_a_snapshot_from_the_next_turn(self):
        # C1: the restore write and the snapshot pop are separate steps. If the next turn's duck
        # lands between them, _say must not tear down THAT turn's baseline + dead-man -- doing so
        # left the zone at the floor with nothing to restore it.
        cap = interaction.InteractionCapability(timer_factory=FakeTimer, clock=lambda: 1000.0,
                                                sleeper=FakeSleeper())
        zone = self.zone
        ha = FakeHA(playing(0.32))
        ctx = self._ctx(ha)
        run(cap, ctx, {"mode": "duck"})                          # turn 1: baseline 0.32, dead-man #1
        ha.set_states([playing_with_id(0.15, "library://radio/2"),
                       playing_with_id(0.70, self.reply_mid),
                       idle_state(), idle_state(),              # end, confirmed (debounce)
                       playing(0.70)])                          # restore-step read: still ours
        real_write = ha.call_service_rest

        def write_then_next_turn_ducks(domain, service, data, timeout=None):
            real_write(domain, service, data)
            if service == "volume_set" and abs(data["volume_level"] - 0.32) < 0.001:
                # turn 2's wake-word duck slips in right after our restore write
                cap._replies.pop(zone, None)                     # its own _reply_active gate passes
                cap._snaps[zone] = {"volume": 0.32, "target": 0.15, "ts": 2000.0, "timer": None}
                cap._replies[zone] = {"gen": 1, "baseline": 0.32, "ts": 1000.0, "rid": "r0"}
        ha.call_service_rest = write_then_next_turn_ducks
        r = run(cap, ctx, {"mode": "say", "uri": self.norm_uri})
        self.assertTrue(r["ok"])
        self.assertIn(zone, cap._snaps)                          # turn 2's snapshot survives
        self.assertAlmostEqual(cap._snaps[zone]["ts"], 2000.0)   # and it is turn 2's, not turn 1's

    def test_say_crash_after_reply_volume_leaves_a_reconcilable_zone(self):
        # C2: if the reply turn dies after raising the volume, the zone must not be left loud, and
        # a later _restore must NOT read the reply volume as a human override and keep it.
        cap = interaction.InteractionCapability(timer_factory=FakeTimer, clock=lambda: 1000.0,
                                                sleeper=FakeSleeper())
        zone = self.zone
        ha = FakeHA(playing(0.32))
        ctx = self._ctx(ha)
        run(cap, ctx, {"mode": "duck"})                          # baseline 0.32, target 0.15
        ha.set_states([playing_with_id(0.15, "library://radio/2")])
        real_write = ha.call_service_rest

        def boom_on_play_media(domain, service, data, timeout=None):
            if service == "play_media":
                raise IOError("MA play_media 500")
            real_write(domain, service, data)
        ha.call_service_rest = boom_on_play_media
        r = run(cap, ctx, {"mode": "say", "uri": self.norm_uri})
        self.assertFalse(r["ok"])
        self.assertNotIn(zone, cap._replies)                     # ownership handed back
        # the abort path put the zone back on the baseline itself (a trailing un-pause may follow,
        # so look for the restore rather than assuming it is the last call)...
        vol_calls = [c for c in ha.calls if c[1] == "volume_set"]
        self.assertAlmostEqual(vol_calls[-1][2]["volume_level"], 0.32)
        # ...and the snapshot it left behind is reconcilable: target tracks what was really written,
        # so the dead-man restores the baseline instead of claiming user_override.
        ha._state = playing(0.32)
        ha.call_service_rest = real_write
        ha.calls = []
        r2 = run(cap, ctx, {"mode": "restore"})
        self.assertNotEqual(r2["metadata"].get("reason"), "user_override")

    def test_dead_man_during_reply_defers_and_stays_armed(self):
        cap = interaction.InteractionCapability(timer_factory=FakeTimer, clock=lambda: 1000.0)
        ha = FakeHA(playing(0.32))
        ctx = self._ctx(ha)
        run(cap, ctx, {"mode": "duck"})
        cap._replies[self.zone] = {"gen": 1, "baseline": 0.32, "ts": 1000.0, "rid": "r0"}
        ha._state = playing(0.70)                                # sitting at _say's reply volume
        ha.calls = []
        FakeTimer.created[0].fire()                              # dead-man fires mid-reply
        self.assertEqual(ha.calls, [])                           # does not fight _say
        self.assertAlmostEqual(cap._snaps[self.zone]["volume"], 0.32)
        self.assertEqual(len(FakeTimer.created), 2)              # re-armed, backstop not lost

    def test_two_consecutive_turns_do_not_ratchet(self):
        # The end-to-end property the operator hears: turn 2 must start and finish on the same
        # baseline as turn 1, with S1a's idle->restore firing mid-reply on both turns.
        cap = interaction.InteractionCapability(timer_factory=FakeTimer, clock=lambda: 1000.0)
        ctx = None

        def one_turn(ha):
            run(cap, ctx, {"mode": "duck"})                      # wake: 0.32 -> 0.15
            ha.set_states([playing_with_id(0.15, "library://radio/2"),
                           playing_with_id(0.70, self.reply_mid),
                           playing_with_id(0.70, self.reply_mid),
                           playing_with_id(0.70, self.reply_mid),   # the interleaved restore's read
                           idle_state(), idle_state(),              # end, confirmed (debounce)
                           playing(0.70)])                          # restore-step read: still ours
            cap._sleeper = FakeSleeper(lambda n: n == 1 and run(cap, ctx, {"mode": "restore"}))
            return run(cap, ctx, {"mode": "say", "uri": self.norm_uri})

        ha = FakeHA(playing(0.32))
        ctx = self._ctx(ha)
        one_turn(ha)
        vols = [c[2]["volume_level"] for c in ha.calls if c[1] == "volume_set"]
        self.assertAlmostEqual(vols[-1], 0.32)
        ha2 = FakeHA(playing(0.32))                              # turn 2 starts where turn 1 left off
        ctx.ha = ha2
        one_turn(ha2)
        vols2 = [c[2]["volume_level"] for c in ha2.calls if c[1] == "volume_set"]
        self.assertAlmostEqual(vols2[0], 0.15)                   # ducked from the SAME baseline
        self.assertAlmostEqual(vols2[-1], 0.32)                  # and returned to it: no ratchet
        self.assertNotIn(self.zone, cap._replies)

    def test_owns_restore_false_keeps_pre_slice4_behaviour(self):
        # The rollback lever: with the flag off, duck/restore must not defer at all.
        class NoOwnRestore(OwnershipSettings):
            say_owns_restore = False
        cap = interaction.InteractionCapability(timer_factory=FakeTimer, clock=lambda: 1000.0)
        ha = FakeHA(playing(0.32))
        ctx = self._ctx(ha)
        ctx.settings = NoOwnRestore()
        run(cap, ctx, {"mode": "duck"})
        cap._replies[self.zone] = {"gen": 1, "baseline": 0.32, "ts": 1000.0, "rid": "r0"}
        ha._state = playing(0.55)                                # a human bump
        ha.calls = []
        r = run(cap, ctx, {"mode": "restore"})
        self.assertEqual(r["metadata"]["reason"], "user_override")   # legacy heuristic, not deferral
        r2 = run(cap, ctx, {"mode": "duck"})                      # and duck still ducks
        self.assertTrue(r2["metadata"]["ducked"])

    def test_say_inherits_baseline_from_superseded_reply(self):
        # Barge-in: reply #2 captures prev_volume == reply #1's volume. It must inherit the
        # original pre-duck baseline instead, or each barge-in ratchets the zone up.
        cap = interaction.InteractionCapability(timer_factory=FakeTimer, clock=lambda: 1000.0,
                                                sleeper=FakeSleeper())
        ha = FakeHA()
        ctx = self._ctx(ha)
        cap._replies[self.zone] = {"gen": 1, "baseline": 0.32}   # reply #1 in flight, no _snaps
        ha.set_states([
            playing_with_id(0.70, "builtin://radio/old-reply"),  # capture: prev_volume is reply #1's volume
            playing_with_id(0.70, self.reply_mid),
            idle_state(),
        ])
        r = run(cap, ctx, {"mode": "say", "uri": self.norm_uri})
        self.assertTrue(r["ok"])
        vol_calls = [c for c in ha.calls if c[1] == "volume_set"]
        self.assertAlmostEqual(vol_calls[-1][2]["volume_level"], 0.32)

    def test_say_leaves_snapshot_for_s1a_when_not_owns_restore(self):
        class NoOwnRestore(OwnershipSettings):
            say_owns_restore = False
        cap = interaction.InteractionCapability(timer_factory=FakeTimer, clock=lambda: 1000.0,
                                                sleeper=FakeSleeper())
        ha = FakeHA(playing(0.32))
        ctx = self._ctx(ha)
        run(cap, ctx, {"mode": "duck"})
        ctx.settings = NoOwnRestore()
        ha.set_states([playing(0.15), playing_with_id(0.70, self.reply_mid), idle_state()])
        r = run(cap, ctx, {"mode": "say", "uri": self.norm_uri})
        self.assertTrue(r["ok"])
        self.assertIn(self.zone, cap._snaps)                    # S1a still owns the baseline restore
        self.assertNotIn(self.zone, cap._replies)               # but the reply marker is always released

    def test_reply_marker_released_when_say_raises(self):
        # A stuck marker would deafen _restore/_duck for this zone forever.
        cap = interaction.InteractionCapability(timer_factory=FakeTimer, clock=lambda: 1000.0,
                                                sleeper=FakeSleeper())
        ha = FakeHA(playing(0.32), write_boom=IOError("volume_set exploded"))
        ctx = self._ctx(ha)
        r = run(cap, ctx, {"mode": "say", "uri": self.norm_uri})
        self.assertFalse(r["ok"])
        self.assertNotIn(self.zone, cap._replies)

    def test_superseded_say_does_not_release_the_newer_reply_marker(self):
        zone = self.zone

        def bump_gen(n):
            if n == 1:
                cap._say_gen[zone] = cap._say_gen.get(zone, 0) + 1
                cap._replies[zone] = {"gen": cap._say_gen[zone], "baseline": 0.32}
        cap = interaction.InteractionCapability(timer_factory=FakeTimer, clock=lambda: 1000.0)
        cap._sleeper = FakeSleeper(bump_gen)
        ha = FakeHA()
        ctx = self._ctx(ha)
        ha.set_states([playing_with_id(0.32, "library://radio/2"), idle_state(), idle_state()])
        r = run(cap, ctx, {"mode": "say", "uri": self.norm_uri})
        self.assertTrue(r["metadata"]["superseded"])
        self.assertIn(zone, cap._replies)                       # the newer reply still owns the zone
        self.assertEqual(cap._replies[zone]["gen"], cap._say_gen[zone])


class FreshPlaybackSkipTest(unittest.TestCase):
    """The live "play radio noroc reports success but is silent" bug: _say delivers the reply with
    play_media, which REPLACES the stream -- so the spoken confirmation of a media command overwrote
    the station it was confirming, and because the station was still starting when _say captured, no
    source was captured to replay. Zone ended idle holding the TTS clip. Decision (e): a media
    command is confirmed by the action."""

    def setUp(self):
        FakeTimer.created = []
        self.zone = "media_player.ceiling_speakers"
        self.norm_uri = "http://192.168.122.10:8123/api/tts_proxy/x.mp3"
        self.reply_mid = "builtin://radio/" + self.norm_uri

    def _cap(self):
        return interaction.InteractionCapability(timer_factory=FakeTimer, clock=lambda: 1000.0,
                                                sleeper=FakeSleeper())

    def _ctx(self, ha):
        ctx = FakeCtx(ha); ctx.settings = OwnershipSettings()
        return ctx

    def test_reply_is_skipped_when_this_turn_started_playback(self):
        cap = self._cap()
        ha = FakeHA(playing(0.15)); ctx = self._ctx(ha)
        run(cap, ctx, {"mode": "duck"})                     # turn opens
        cap.note_playback(ctx, self.zone, "library://radio/18")
        ha.calls = []
        r = run(cap, ctx, {"mode": "say", "uri": self.norm_uri})
        self.assertTrue(r["ok"])
        self.assertFalse(r["metadata"]["said"])
        self.assertEqual(r["metadata"]["reason"], "fresh_playback")
        self.assertEqual(ha.calls, [])                      # never touches volume or the stream
        self.assertNotIn(self.zone, cap._replies)           # no reply ownership taken

    def test_a_later_turn_still_gets_its_reply(self):
        # A question asked after a media command is a NEW turn -- it must not lose its answer.
        cap = self._cap()
        ha = FakeHA(playing(0.15)); ctx = self._ctx(ha)
        run(cap, ctx, {"mode": "duck"})
        cap.note_playback(ctx, self.zone, "library://radio/18")
        run(cap, ctx, {"mode": "restore"})                  # turn ends
        cap._turns.clear()                                  # ... and a fresh turn begins
        run(cap, ctx, {"mode": "duck"})
        ha.calls = []
        ha.set_states([playing_with_id(0.15, "library://radio/18"),
                       playing_with_id(0.70, self.reply_mid),
                       idle_state()])
        r = run(cap, ctx, {"mode": "say", "uri": self.norm_uri})
        self.assertTrue(r["metadata"]["said"])
        self.assertTrue(r["metadata"]["reply_started"])

    def test_open_qa_with_no_playback_this_turn_replies_normally(self):
        cap = self._cap()
        ha = FakeHA(); ctx = self._ctx(ha)
        run(cap, ctx, {"mode": "duck"})                     # idle zone -> no-op duck, turn still open
        ha.set_states([playing_with_id(0.32, "library://radio/18"),
                       playing_with_id(0.70, self.reply_mid),
                       idle_state()])
        r = run(cap, ctx, {"mode": "say", "uri": self.norm_uri})
        self.assertTrue(r["metadata"]["said"])

    def test_flag_off_restores_the_clobbering_behaviour(self):
        class NoSkip(OwnershipSettings):
            say_skip_on_fresh_playback = False
        cap = self._cap()
        ha = FakeHA(playing(0.15)); ctx = self._ctx(ha)
        ctx.settings = NoSkip()
        run(cap, ctx, {"mode": "duck"})
        cap.note_playback(ctx, self.zone, "library://radio/18")
        ha.set_states([playing_with_id(0.15, "library://radio/18"),
                       playing_with_id(0.70, self.reply_mid),
                       idle_state()])
        r = run(cap, ctx, {"mode": "say", "uri": self.norm_uri})
        self.assertTrue(r["metadata"]["said"])

    def test_duck_after_playback_started_does_not_attenuate_it(self):
        # THE BLIP (2026-09-06). The reply is skipped because this turn started playback, so the duck
        # that was making room for it only quiets the station until the restore lands seconds later.
        # Shaped exactly like the live turn: the zone is IDLE when the turn opens (the log shows two
        # `no-op (not_playing)` ducks), the station starts, and only then does a duck arrive.
        cap = self._cap()
        ha = FakeHA(); ctx = self._ctx(ha)
        ha.set_states([idle_state(), playing(0.36)])
        run(cap, ctx, {"mode": "duck"})                     # turn opens over an idle zone -> no-op
        cap.note_playback(ctx, self.zone, "library://radio/17")
        ha.calls = []
        r = run(cap, ctx, {"mode": "duck"})                 # the duck that arrives AFTER the play
        self.assertFalse(r["metadata"]["ducked"])
        self.assertEqual(r["metadata"]["reason"], "fresh_playback")
        self.assertEqual(ha.calls, [])                      # the station's volume is never touched
        self.assertNotIn(self.zone, cap._snaps)             # and no snapshot/dead-man is left behind

    def test_duck_flag_off_restores_the_blip(self):
        class NoDuckSkip(OwnershipSettings):
            duck_skip_on_fresh_playback = False
        cap = self._cap()
        ha = FakeHA(); ctx = self._ctx(ha)
        ctx.settings = NoDuckSkip()
        ha.set_states([idle_state(), playing(0.36)])
        run(cap, ctx, {"mode": "duck"})
        cap.note_playback(ctx, self.zone, "library://radio/17")
        ha.calls = []
        r = run(cap, ctx, {"mode": "duck"})
        self.assertTrue(r["metadata"]["ducked"])            # the pre-fix behaviour, on demand
        self.assertEqual(r["metadata"]["to"], 0.15)         # ... attenuating the fresh station

    def test_duck_before_any_playback_still_ducks(self):
        # Guard rail: the ordinary case -- a question asked over music -- must still duck.
        cap = self._cap()
        ha = FakeHA(playing(0.36)); ctx = self._ctx(ha)
        r = run(cap, ctx, {"mode": "duck"})
        self.assertTrue(r["metadata"]["ducked"])
        self.assertEqual(r["metadata"]["to"], 0.15)

    def test_note_playback_does_not_invent_a_turn(self):
        # A play from a non-satellite caller (phone / ChatGPT text) must NOT open a phantom turn:
        # that would suppress that caller's announce for the turn window and would skip a genuine
        # satellite reply later.
        cap = self._cap()
        ctx = self._ctx(FakeHA())
        cap.note_playback(ctx, self.zone, "library://radio/2")
        self.assertNotIn(self.zone, cap._turns)
        self.assertFalse(cap.interaction_in_flight(ctx, self.zone))

    def test_note_playback_annotates_an_open_turn(self):
        cap = self._cap()
        ha = FakeHA(playing(0.32)); ctx = self._ctx(ha)
        run(cap, ctx, {"mode": "duck"})                      # a satellite turn is open
        cap.note_playback(ctx, self.zone, "library://radio/2")
        self.assertEqual(cap._turns[self.zone]["playback"], "library://radio/2")


class StopReplaySkipTest(unittest.TestCase):
    """The live "Nabu does not stop the music" bug (2026-09-05). The voice automation issued
    `media_player.media_pause` straight from HA and spoke "Stopped."; `_say` captured the zone 28 ms
    later -- before HA had propagated `paused` -- so it read "playing" and replayed the source at
    step 9. Observed three times: the radio came back every time while the user heard "Stopped."

    Mirror of FreshPlaybackSkipTest: there a turn that STARTED playback must not have the reply
    replace it; here a turn that STOPPED playback must not have the reply resurrect it. Neither race
    is winnable on timing, so both trust the turn's recorded intent over the live capture."""

    def setUp(self):
        FakeTimer.created = []
        self.zone = "media_player.ceiling_speakers"
        self.norm_uri = "http://192.168.122.10:8123/api/tts_proxy/x.mp3"
        self.reply_mid = "builtin://radio/" + self.norm_uri
        self.source = "library://radio/17"

    def _cap(self):
        return interaction.InteractionCapability(timer_factory=FakeTimer, clock=lambda: 1000.0,
                                                sleeper=FakeSleeper())

    def _ctx(self, ha, settings=None):
        ctx = FakeCtx(ha)
        ctx.settings = settings or OwnershipSettings()
        return ctx

    def _stale_capture_states(self):
        # HA has NOT yet propagated `paused`: the capture still reports the stream playing.
        return [playing_with_id(0.15, self.source),
                playing_with_id(0.70, self.reply_mid),
                idle_state()]

    def _replayed_source(self, ha):
        return ("music_assistant", "play_media",
                {"entity_id": self.zone, "media_id": self.source}) in ha.calls

    def test_pause_pauses_the_zone_and_marks_the_turn(self):
        cap = self._cap()
        ha = FakeHA(playing_with_id(0.36, self.source)); ctx = self._ctx(ha)
        run(cap, ctx, {"mode": "duck"})                      # turn opens
        ha.calls = []
        r = run(cap, ctx, {"mode": "pause"})
        self.assertTrue(r["ok"])
        self.assertTrue(r["metadata"]["paused"])
        self.assertEqual(r["metadata"]["was"], "playing")
        self.assertIn(("media_player", "media_pause", {"entity_id": self.zone}), ha.calls)
        self.assertTrue(cap._turns[self.zone]["stopped"])

    def test_reply_after_a_stop_does_not_replay_the_source(self):
        # THE BUG. The capture below says "playing" -- the stale reading that caused the replay.
        cap = self._cap()
        ha = FakeHA(playing_with_id(0.36, self.source)); ctx = self._ctx(ha)
        run(cap, ctx, {"mode": "duck"})
        run(cap, ctx, {"mode": "pause"})
        ha.calls = []
        ha.set_states(self._stale_capture_states())
        r = run(cap, ctx, {"mode": "say", "uri": self.norm_uri})
        self.assertFalse(r["metadata"]["replayed"])
        self.assertFalse(self._replayed_source(ha))

    def test_the_confirmation_is_still_spoken(self):
        # Suppressing the replay must not cost the user the confirmation -- that is the whole reason
        # this fix exists rather than simply silencing the stop branch.
        cap = self._cap()
        ha = FakeHA(playing_with_id(0.36, self.source)); ctx = self._ctx(ha)
        run(cap, ctx, {"mode": "duck"})
        run(cap, ctx, {"mode": "pause"})
        ha.set_states(self._stale_capture_states())
        r = run(cap, ctx, {"mode": "say", "uri": self.norm_uri})
        self.assertTrue(r["metadata"]["said"])
        self.assertTrue(r["metadata"]["reply_started"])

    def test_pause_remembers_the_source_so_resume_can_bring_it_back(self):
        cap = self._cap()
        ha = FakeHA(playing_with_id(0.36, self.source)); ctx = self._ctx(ha)
        run(cap, ctx, {"mode": "duck"})
        run(cap, ctx, {"mode": "pause"})
        ha.calls = []
        r = run(cap, ctx, {"mode": "resume"})
        self.assertTrue(r["metadata"]["resumed"])
        self.assertEqual(r["metadata"]["uri"], self.source)
        self.assertTrue(self._replayed_source(ha))

    def test_a_later_turn_replays_normally(self):
        # The mark is scoped to the turn that stopped playback: an ordinary question afterwards must
        # still get its music back after the reply.
        cap = self._cap()
        ha = FakeHA(playing_with_id(0.36, self.source)); ctx = self._ctx(ha)
        run(cap, ctx, {"mode": "duck"})
        run(cap, ctx, {"mode": "pause"})
        run(cap, ctx, {"mode": "restore"})                   # turn ends
        cap._turns.clear()                                   # ... and a fresh turn begins
        run(cap, ctx, {"mode": "duck"})
        ha.calls = []
        ha.set_states(self._stale_capture_states())
        r = run(cap, ctx, {"mode": "say", "uri": self.norm_uri})
        self.assertTrue(r["metadata"]["replayed"])
        self.assertTrue(self._replayed_source(ha))

    def test_flag_off_restores_the_resurrecting_behaviour(self):
        class NoSkip(OwnershipSettings):
            say_skip_replay_on_stop = False
        cap = self._cap()
        ha = FakeHA(playing_with_id(0.36, self.source)); ctx = self._ctx(ha, NoSkip())
        run(cap, ctx, {"mode": "duck"})
        run(cap, ctx, {"mode": "pause"})
        ha.calls = []
        ha.set_states(self._stale_capture_states())
        r = run(cap, ctx, {"mode": "say", "uri": self.norm_uri})
        self.assertTrue(r["metadata"]["replayed"])           # the pre-fix behaviour, on demand

    def test_note_stopped_does_not_invent_a_turn(self):
        # Same reasoning as note_playback: a pause from a non-satellite caller has no reply coming,
        # and opening a phantom turn here would suppress a genuine reply later.
        cap = self._cap()
        ctx = self._ctx(FakeHA())
        cap.note_stopped(self.zone)
        self.assertNotIn(self.zone, cap._turns)
        self.assertFalse(cap.interaction_in_flight(ctx, self.zone))

    def test_pause_is_a_valid_mode(self):
        cap = interaction.InteractionCapability()
        ctx = self._ctx(FakeHA())
        resolved = cap.resolve(ctx, {"mode": "pause"})
        self.assertIsNone(cap.validate(ctx, resolved))


class HumanVolumeChangeDuringTurnTest(unittest.TestCase):
    """REGRESSION GUARD. The old user_override check did two jobs: the false positive that caused the
    ratchet, AND honouring a genuine human volume change mid-turn. Making _say the single writer
    removed both, so "Okay Nabu, volume down" became a no-op -- the ceiling scripts write the player
    directly, then _say's baseline restore undid it. The resolver knows the only two values IT wrote
    (the duck floor and reply_volume); anything else is a third party and must be kept."""

    def setUp(self):
        FakeTimer.created = []
        self.zone = "media_player.ceiling_speakers"
        self.norm_uri = "http://192.168.122.10:8123/api/tts_proxy/x.mp3"
        self.reply_mid = "builtin://radio/" + self.norm_uri

    def _cap(self):
        return interaction.InteractionCapability(timer_factory=FakeTimer, clock=lambda: 1000.0,
                                                sleeper=FakeSleeper())

    def _ctx(self, ha):
        ctx = FakeCtx(ha); ctx.settings = OwnershipSettings()   # reply_volume 0.70
        return ctx

    def test_volume_lowered_during_the_duck_becomes_the_baseline(self):
        cap = self._cap()
        ha = FakeHA(playing(0.47)); ctx = self._ctx(ha)
        run(cap, ctx, {"mode": "duck"})                       # 0.47 -> floor 0.15
        ha.calls = []
        ha.set_states([
            playing_with_id(0.05, "library://radio/2"),        # capture: user pressed volume down
            playing_with_id(0.70, self.reply_mid),              # start-poll: reply playing
            idle_state(), idle_state(),                         # ended, confirmed (debounce)
            playing(0.70),                                      # restore-step read: still ours
        ])
        run(cap, ctx, {"mode": "say", "uri": self.norm_uri})
        vol_calls = [c[2]["volume_level"] for c in ha.calls if c[1] == "volume_set"]
        self.assertAlmostEqual(vol_calls[-1], 0.05)            # their level, NOT the 0.47 baseline

    def test_volume_changed_during_the_reply_is_kept(self):
        cap = self._cap()
        ha = FakeHA(playing(0.47)); ctx = self._ctx(ha)
        run(cap, ctx, {"mode": "duck"})
        ha.calls = []
        ha.set_states([
            playing_with_id(0.15, "library://radio/2"),        # capture: still at our floor
            playing_with_id(0.70, self.reply_mid),
            idle_state(), idle_state(),                        # ended, confirmed (debounce)
            playing(0.30),                                     # restore-step read: user moved it
        ])
        run(cap, ctx, {"mode": "say", "uri": self.norm_uri})
        vol_calls = [c[2]["volume_level"] for c in ha.calls if c[1] == "volume_set"]
        self.assertEqual(len(vol_calls), 1)                    # only the reply volume; no restore
        self.assertNotIn(self.zone, cap._snaps)                # snapshot retired, no dead-man left

    def test_our_own_reply_volume_is_not_mistaken_for_a_human(self):
        # This is the ratchet: reply_volume must never be read as a user override.
        cap = self._cap()
        ha = FakeHA(playing(0.47)); ctx = self._ctx(ha)
        run(cap, ctx, {"mode": "duck"})
        ha.calls = []
        ha.set_states([
            playing_with_id(0.15, "library://radio/2"),
            playing_with_id(0.70, self.reply_mid),
            idle_state(), idle_state(),                        # ended, confirmed (debounce)
            playing(0.70),                                     # restore-step read: OUR reply volume
        ])
        run(cap, ctx, {"mode": "say", "uri": self.norm_uri})
        vol_calls = [c[2]["volume_level"] for c in ha.calls if c[1] == "volume_set"]
        self.assertAlmostEqual(vol_calls[-1], 0.47)            # baseline restored

    def test_a_stale_read_of_the_duck_floor_is_not_a_human_change(self):
        # HA state lags; a stale read returns the pre-reply (ducked) value. That must NOT be taken
        # for a user override -- doing so would strand the zone at the floor.
        cap = self._cap()
        ha = FakeHA(playing(0.47)); ctx = self._ctx(ha)
        run(cap, ctx, {"mode": "duck"})
        ha.calls = []
        ha.set_states([
            playing_with_id(0.15, "library://radio/2"),
            playing_with_id(0.70, self.reply_mid),
            idle_state(), idle_state(),                        # ended, confirmed (debounce)
            playing(0.15),                                     # stale: still reads the floor
        ])
        run(cap, ctx, {"mode": "say", "uri": self.norm_uri})
        vol_calls = [c[2]["volume_level"] for c in ha.calls if c[1] == "volume_set"]
        self.assertAlmostEqual(vol_calls[-1], 0.47)            # baseline restored, not stranded


class ResumeModeTest(unittest.TestCase):
    """`script.ceiling_resume` used media_player.media_play, which cannot resume a radio stream whose
    queue was cleared -- and after a reply turn the zone is holding a spent TTS clip, so media_play
    would replay THAT. `resume` replays the last real source instead."""

    def setUp(self):
        FakeTimer.created = []
        self.zone = "media_player.ceiling_speakers"
        self.cap = interaction.InteractionCapability(timer_factory=FakeTimer, clock=lambda: 1000.0,
                                                    sleeper=FakeSleeper())

    def test_resume_replays_the_last_real_source(self):
        ha = FakeHA(); ctx = FakeCtx(ha)
        self.cap.remember_source(self.zone, "library://radio/18")
        r = run(self.cap, ctx, {"mode": "resume"})
        self.assertTrue(r["ok"])
        self.assertTrue(r["metadata"]["resumed"])
        self.assertEqual(r["metadata"]["how"], "replay")
        pm = [c for c in ha.calls if c[1] == "play_media"]
        self.assertEqual(pm[0][2]["media_id"], "library://radio/18")

    def test_reply_clips_are_never_remembered_as_a_source(self):
        for clip in ("http://192.168.122.10:8123/api/tts_proxy/abc.flac",
                     "builtin://radio/http://192.168.122.10:8123/api/tts_proxy/abc.flac"):
            self.cap.remember_source(self.zone, clip)
        self.assertNotIn(self.zone, self.cap._last_source)

    def test_resume_on_an_idle_empty_zone_makes_NO_service_call(self):
        # Live failure: a blind media_play on an idle player returned HTTP 500 and killed the turn
        # with a bare OSError, which the assistant surfaced as "there is nothing playing".
        ha = FakeHA(idle_state()); ctx = FakeCtx(ha)
        r = run(self.cap, ctx, {"mode": "resume"})
        self.assertTrue(r["ok"])
        self.assertFalse(r["metadata"]["resumed"])
        self.assertEqual(r["metadata"]["reason"], "nothing_to_resume")
        self.assertEqual(ha.calls, [])

    def test_resume_unpauses_a_paused_zone(self):
        ha = FakeHA({"state": "paused", "attributes": {"media_content_id": "library://radio/2"}})
        ctx = FakeCtx(ha)
        r = run(self.cap, ctx, {"mode": "resume"})
        self.assertEqual(r["metadata"]["how"], "unpause")
        self.assertEqual([c[1] for c in ha.calls], ["media_play"])

    def test_resume_replays_a_loaded_real_source_when_nothing_remembered(self):
        ha = FakeHA(playing_with_id(0.3, "library://radio/2")); ctx = FakeCtx(ha)
        r = run(self.cap, ctx, {"mode": "resume"})
        self.assertEqual(r["metadata"]["how"], "loaded")
        self.assertEqual(r["metadata"]["uri"], "library://radio/2")

    def test_resume_will_not_replay_a_spent_reply_clip(self):
        clip = "builtin://radio/http://192.168.122.10:8123/api/tts_proxy/x.flac"
        ha = FakeHA({"state": "idle", "attributes": {"media_content_id": clip}})
        ctx = FakeCtx(ha)
        r = run(self.cap, ctx, {"mode": "resume"})
        self.assertFalse(r["metadata"]["resumed"])
        self.assertEqual(ha.calls, [])

    def test_a_played_station_is_remembered_via_note_playback(self):
        ctx = FakeCtx(FakeHA())
        self.cap.note_playback(ctx, self.zone, "library://radio/2")
        self.assertEqual(self.cap._last_source[self.zone], "library://radio/2")

    def test_say_remembers_the_source_it_captured(self):
        ha = FakeHA(); ctx = FakeCtx(ha)
        ha.set_states([playing_with_id(0.32, "library://track/9"),
                       playing_with_id(0.40, "builtin://radio/" + "http://192.168.122.10:8123/api/tts_proxy/x.mp3"),
                       idle_state(), playing(0.40)])
        run(self.cap, ctx, {"mode": "say", "uri": "http://192.168.122.10:8123/api/tts_proxy/x.mp3"})
        self.assertEqual(self.cap._last_source[self.zone], "library://track/9")

    def test_resume_is_a_valid_mode(self):
        r = self.cap.resolve(FakeCtx(FakeHA()), {"mode": "resume"})
        self.assertIsNone(self.cap.validate(FakeCtx(FakeHA()), r))


class VolumeCommandTest(unittest.TestCase):
    """LIVE FAILURE this guards: "volume up" from 0.34 ended at 0.25.

        15:43:32  DUCK 0.34 -> 0.15          wake ducks to the floor
        15:43:38  DUCK 0.25 -> 0.15          volume_up made 0.15+0.10, the re-duck undid it
        15:43:39  SAY restored -> 0.25       so "up" finished LOWER than it started

    A relative step must be computed from the BASELINE, not the duck floor, and must survive the
    re-ducks that follow it."""

    def setUp(self):
        FakeTimer.created = []
        self.zone = "media_player.ceiling_speakers"
        self.cap = interaction.InteractionCapability(timer_factory=FakeTimer, clock=lambda: 1000.0,
                                                    sleeper=FakeSleeper())

    def test_volume_up_while_ducked_moves_the_baseline_not_the_floor(self):
        ha = FakeHA(playing(0.34)); ctx = FakeCtx(ha)
        run(self.cap, ctx, {"mode": "duck"})                 # 0.34 -> 0.15
        ha.calls = []
        r = run(self.cap, ctx, {"mode": "volume_up"})
        self.assertTrue(r["metadata"]["changed"])
        self.assertEqual(r["metadata"]["applied"], "baseline")
        self.assertAlmostEqual(r["metadata"]["to"], 0.44)     # 0.34 + 0.10, NOT 0.15 + 0.10
        self.assertEqual(ha.calls, [])                        # floor untouched, nothing to fight
        self.assertAlmostEqual(self.cap._snaps[self.zone]["volume"], 0.44)

    def test_the_ducked_change_survives_a_re_duck_and_lands_on_restore(self):
        ha = FakeHA(playing(0.34)); ctx = FakeCtx(ha)
        run(self.cap, ctx, {"mode": "duck"})
        run(self.cap, ctx, {"mode": "volume_up"})            # baseline -> 0.44
        ha._state = playing(0.15)
        run(self.cap, ctx, {"mode": "duck"})                 # re-duck must NOT undo it
        self.assertAlmostEqual(self.cap._snaps[self.zone]["volume"], 0.44)
        ha.calls = []
        r = run(self.cap, ctx, {"mode": "restore"})
        self.assertTrue(r["metadata"]["restored"])
        self.assertAlmostEqual(ha.calls[-1][2]["volume_level"], 0.44)   # the user's "up" lands

    def test_volume_down_while_ducked(self):
        ha = FakeHA(playing(0.34)); ctx = FakeCtx(ha)
        run(self.cap, ctx, {"mode": "duck"})
        r = run(self.cap, ctx, {"mode": "volume_down"})
        self.assertAlmostEqual(r["metadata"]["to"], 0.24)

    def test_custom_step_is_honoured(self):
        ha = FakeHA(playing(0.34)); ctx = FakeCtx(ha)
        run(self.cap, ctx, {"mode": "duck"})
        r = run(self.cap, ctx, {"mode": "volume_up", "step": 25})
        self.assertAlmostEqual(r["metadata"]["to"], 0.59)

    def test_unducked_volume_up_writes_the_player_directly(self):
        ha = FakeHA(playing(0.40)); ctx = FakeCtx(ha)
        r = run(self.cap, ctx, {"mode": "volume_up"})
        self.assertEqual(r["metadata"]["applied"], "live")
        self.assertAlmostEqual(ha.calls[-1][2]["volume_level"], 0.50)

    def test_set_volume_absolute_ducked_and_unducked(self):
        ha = FakeHA(playing(0.34)); ctx = FakeCtx(ha)
        run(self.cap, ctx, {"mode": "duck"})
        r = run(self.cap, ctx, {"mode": "set_volume", "volume": 55})
        self.assertEqual(r["metadata"]["applied"], "baseline")
        self.assertAlmostEqual(r["metadata"]["to"], 0.55)
        cap2 = interaction.InteractionCapability(timer_factory=FakeTimer, clock=lambda: 1000.0)
        ha2 = FakeHA(playing(0.20)); ctx2 = FakeCtx(ha2)
        r2 = run(cap2, ctx2, {"mode": "set_volume", "volume": 70})
        self.assertEqual(r2["metadata"]["applied"], "live")
        self.assertAlmostEqual(ha2.calls[-1][2]["volume_level"], 0.70)

    def test_volume_is_clamped(self):
        ha = FakeHA(playing(0.95)); ctx = FakeCtx(ha)
        run(self.cap, ctx, {"mode": "duck"})
        r = run(self.cap, ctx, {"mode": "volume_up", "step": 50})
        self.assertAlmostEqual(r["metadata"]["to"], 1.0)
        cap2 = interaction.InteractionCapability(timer_factory=FakeTimer, clock=lambda: 1000.0)
        ha2 = FakeHA(playing(0.05)); ctx2 = FakeCtx(ha2)
        r2 = run(cap2, ctx2, {"mode": "volume_down", "step": 50})
        self.assertAlmostEqual(r2["metadata"]["to"], 0.0)

    def test_set_volume_without_a_value_is_an_honest_no_op(self):
        ha = FakeHA(playing(0.34)); ctx = FakeCtx(ha)
        r = run(self.cap, ctx, {"mode": "set_volume"})
        self.assertFalse(r["metadata"]["changed"])
        self.assertEqual(r["metadata"]["reason"], "no_volume")
        self.assertEqual(ha.calls, [])

    def test_relative_change_with_no_readable_volume_is_an_honest_no_op(self):
        ha = FakeHA({"state": "playing", "attributes": {}}); ctx = FakeCtx(ha)
        r = run(self.cap, ctx, {"mode": "volume_up"})
        self.assertFalse(r["metadata"]["changed"])
        self.assertEqual(r["metadata"]["reason"], "no_current")
        self.assertEqual(ha.calls, [])


class FinishPollCutOffTest(unittest.TestCase):
    """LIVE ROOT CAUSE of "almost all commands had bumps/cutoffs".

        16:01:12  finish-poll exit after 0.5s: state=playing cid=
        16:01:29  finish-poll exit after 0.5s: state=playing cid=
        16:02:21  finish-poll exit after 1.0s: state=playing cid=

    MA transiently reports an EMPTY media_content_id while the clip is still playing. The old
    condition (`norm_uri not in (cid or "")`) is always true against "", so the poll concluded the
    clip had ended after 0.5-1.0s, restored the volume and replayed the source OVER the still-playing
    reply -- heard as the reply being cut off, with the restore as the volume "bump".

    A genuine ending looks different: state=idle, or a cid naming something else."""

    def setUp(self):
        FakeTimer.created = []
        self.zone = "media_player.ceiling_speakers"
        self.norm_uri = "http://192.168.122.10:8123/api/tts_proxy/x.mp3"
        self.reply_mid = "builtin://radio/" + self.norm_uri

    def _cap(self):
        return interaction.InteractionCapability(timer_factory=FakeTimer, clock=lambda: 1000.0,
                                                sleeper=FakeSleeper())

    def _blank(self):
        return {"state": "playing", "attributes": {"media_content_id": ""}}

    def test_empty_cid_while_playing_does_not_end_the_clip(self):
        sleeper = FakeSleeper()
        cap = interaction.InteractionCapability(timer_factory=FakeTimer, clock=lambda: 1000.0,
                                                sleeper=sleeper)
        ha = FakeHA(); ctx = FakeCtx(ha)
        ha.set_states([
            playing_with_id(0.32, "library://radio/2"),   # capture
            playing_with_id(0.40, self.reply_mid),        # start-poll: clip playing
            self._blank(),                                 # <- the live flicker; must NOT end it
            self._blank(),
            playing_with_id(0.40, self.reply_mid),        # still our clip
            idle_state(),                                  # genuine end #1
            idle_state(),                                  # genuine end #2 (debounce)
            playing(0.40),                                 # restore-step read
        ])
        r = run(cap, ctx, {"mode": "say", "uri": self.norm_uri})
        self.assertTrue(r["metadata"]["reply_started"])
        # The discriminating assertion: the poll must have kept WAITING through the blank cids.
        # Against the old condition it broke on the first blank and never slept again, so this
        # count was 0 -- the clip was cut off exactly here.
        self.assertGreaterEqual(sleeper.calls, 3)
        pm = [c for c in ha.calls if c[1] == "play_media"]
        self.assertEqual(len(pm), 2)                       # reply, then source replay
        self.assertEqual(pm[1][2]["media_id"], "library://radio/2")

    def test_a_single_flicker_to_idle_does_not_end_the_clip(self):
        cap = self._cap()
        ha = FakeHA(); ctx = FakeCtx(ha)
        ha.set_states([
            playing_with_id(0.32, "library://radio/2"),
            playing_with_id(0.40, self.reply_mid),
            idle_state(),                                  # one flicker only
            playing_with_id(0.40, self.reply_mid),         # back to playing -> counter resets
            idle_state(), idle_state(),                    # genuine end
            playing(0.40),
        ])
        run(cap, ctx, {"mode": "say", "uri": self.norm_uri})
        pm = [c for c in ha.calls if c[1] == "play_media"]
        self.assertEqual(len(pm), 2)

    def test_two_consecutive_idles_do_end_the_clip(self):
        cap = self._cap()
        ha = FakeHA(); ctx = FakeCtx(ha)
        ha.set_states([
            playing_with_id(0.32, "library://radio/2"),
            playing_with_id(0.40, self.reply_mid),
            idle_state(), idle_state(),
            playing(0.40),
        ])
        r = run(cap, ctx, {"mode": "say", "uri": self.norm_uri})
        self.assertTrue(r["metadata"]["replayed"])

    def test_a_cid_naming_something_else_ends_the_clip(self):
        cap = self._cap()
        ha = FakeHA(); ctx = FakeCtx(ha)
        ha.set_states([
            playing_with_id(0.32, "library://radio/2"),
            playing_with_id(0.40, self.reply_mid),
            playing_with_id(0.40, "library://radio/9"),    # something else took over
            playing_with_id(0.40, "library://radio/9"),
            playing(0.40),
        ])
        r = run(cap, ctx, {"mode": "say", "uri": self.norm_uri})
        self.assertTrue(r["metadata"]["reply_started"])


class ReplyBumpTest(unittest.TestCase):
    """OPERATOR REPORT: "a slight bump before the announcement -- the volume jumps up for a sec".

    _say raised the volume to reply_volume BEFORE the clip replaced the stream, so the ~1s of
    still-playing (ducked) music was played at 0.60. Silence the outgoing music first and the raise
    cannot be heard."""

    def setUp(self):
        FakeTimer.created = []
        self.zone = "media_player.ceiling_speakers"
        self.norm_uri = "http://192.168.122.10:8123/api/tts_proxy/x.mp3"
        self.reply_mid = "builtin://radio/" + self.norm_uri

    def _cap(self):
        return interaction.InteractionCapability(timer_factory=FakeTimer, clock=lambda: 1000.0,
                                                sleeper=FakeSleeper())

    def _states(self):
        return [playing_with_id(0.15, "library://radio/2"),      # capture: music playing
                playing_with_id(0.60, self.reply_mid),           # start-poll
                idle_state(), idle_state(),                      # end (debounce)
                playing(0.60)]                                   # restore-step read

    def test_music_is_silenced_before_the_volume_is_raised(self):
        cap = self._cap()
        ha = FakeHA(); ctx = FakeCtx(ha)
        ha.set_states(self._states())
        run(cap, ctx, {"mode": "say", "uri": self.norm_uri})
        order = [c[1] for c in ha.calls]
        self.assertIn("media_pause", order)
        self.assertLess(order.index("media_pause"), order.index("volume_set"))   # pause BEFORE raise
        self.assertLess(order.index("volume_set"), order.index("play_media"))    # raise before clip

    def test_no_pause_when_nothing_was_playing(self):
        cap = self._cap()
        ha = FakeHA(); ctx = FakeCtx(ha)
        ha.set_states([idle_state(), playing_with_id(0.60, self.reply_mid),
                       idle_state(), idle_state(), playing(0.60)])
        run(cap, ctx, {"mode": "say", "uri": self.norm_uri})
        self.assertNotIn("media_pause", [c[1] for c in ha.calls])

    def test_flag_off_keeps_the_old_order(self):
        class NoPause(FakeSettings):
            say_pause_before_reply = False
        cap = self._cap()
        ha = FakeHA(); ctx = FakeCtx(ha)
        ctx.settings = NoPause()
        ha.set_states(self._states())
        run(cap, ctx, {"mode": "say", "uri": self.norm_uri})
        self.assertNotIn("media_pause", [c[1] for c in ha.calls])

    def test_if_the_clip_never_goes_out_the_source_is_replayed_not_un_paused(self):
        # Was: test_if_the_clip_never_goes_out_the_music_is_un_paused, which asserted media_play.
        # AN-01 design 8.3a: a play_media that raised may still have LANDED, so the queue is
        # ambiguous and un-pausing could restart the reply clip instead of the music. The captured
        # source is replayed instead. This fake refuses that replay too, so nothing resumes -- the
        # zone is left paused at its baseline and the operator recovers with "resume".
        cap = self._cap()
        ha = FakeHA(playing(0.15))
        ctx = FakeCtx(ha)
        attempts = []
        real = ha.call_service_rest

        def boom(domain, service, data, timeout=None):
            if service == "play_media":
                attempts.append(data.get("media_id"))     # a REFUSED call reaches no ha.calls entry
                raise IOError("MA refused")
            real(domain, service, data)
        ha.call_service_rest = boom
        ha.set_states([playing_with_id(0.15, "library://radio/2")])
        r = run(cap, ctx, {"mode": "say", "uri": self.norm_uri})
        self.assertFalse(r["ok"])
        self.assertNotIn("media_play", [c[1] for c in ha.calls])   # no blind un-pause
        # The replay WAS attempted with the captured source, even though the fake refused it.
        self.assertIn("library://radio/2", attempts)

    def setUp(self):
        self.norm_uri = "http://192.168.122.10:8123/api/tts_proxy/t.mp3"
        self.reply_mid = "builtin://radio/" + self.norm_uri

    def _cap(self):
        return interaction.InteractionCapability(timer_factory=FakeTimer, clock=lambda: 1000.0,
                                                 sleeper=FakeSleeper())

    def _ha_ok(self):
        ha = FakeHA()
        ha.tts_url = self.norm_uri
        ha.set_states([idle_state(),                              # capture
                       playing_with_id(0.70, self.reply_mid),     # start-poll
                       idle_state()])                             # finish-poll
        return ha

    def test_text_is_resolved_to_a_clip_and_played_via_play_media(self):
        cap = self._cap(); ha = self._ha_ok()
        r = run(cap, FakeCtx(ha), {"mode": "say_text", "text": "Your timer is finished."})
        self.assertTrue(r["ok"])
        self.assertEqual(ha.tts_calls, [("tts.piper", "Your timer is finished.")])
        pm = [c for c in ha.calls if c[1] == "play_media"]
        self.assertEqual(len(pm), 1)
        self.assertEqual(pm[0][2]["media_id"], self.norm_uri)

    def test_it_never_uses_the_broken_announce_path(self):
        cap = self._cap(); ha = self._ha_ok()
        run(cap, FakeCtx(ha), {"mode": "say_text", "text": "hello"})
        for domain, service, _ in ha.calls:
            self.assertNotEqual((domain, service), ("tts", "speak"))
            self.assertNotIn("announce", service)

    def test_empty_text_is_rejected_before_any_call(self):
        cap = self._cap(); ha = FakeHA()
        r = run(cap, FakeCtx(ha), {"mode": "say_text", "text": "   "})
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"]["code"], "invalid_input")
        self.assertEqual(ha.tts_calls, [])
        self.assertEqual(ha.calls, [])

    def test_a_tts_failure_is_reported_not_swallowed(self):
        cap = self._cap(); ha = FakeHA(); ha.tts_boom = IOError("tts 500")
        r = run(cap, FakeCtx(ha), {"mode": "say_text", "text": "hello"})
        self.assertFalse(r["ok"])
        self.assertEqual([c for c in ha.calls if c[1] == "play_media"], [])

    def test_no_url_returned_is_an_honest_failure(self):
        cap = self._cap(); ha = FakeHA(); ha.tts_url = None
        r = run(cap, FakeCtx(ha), {"mode": "say_text", "text": "hello"})
        self.assertFalse(r["ok"])
        self.assertEqual([c for c in ha.calls if c[1] == "play_media"], [])



class SayTextFreshPlaybackTest(unittest.TestCase):
    """`say` declines to speak when the SAME turn already started playback -- correct for a media
    command, whose action is its own confirmation. It is wrong for say_text: a timer chime or any
    other pushed sentence is not confirmed by unrelated music starting, and the caller was told
    "Said." while nothing was spoken."""

    def setUp(self):
        self.norm_uri = "http://192.168.122.10:8123/api/tts_proxy/t.mp3"
        self.reply_mid = "builtin://radio/" + self.norm_uri

    def _cap(self):
        return interaction.InteractionCapability(timer_factory=FakeTimer, clock=lambda: 1000.0,
                                                 sleeper=FakeSleeper())

    def _ha(self):
        ha = FakeHA()
        ha.tts_url = self.norm_uri
        ha.set_states([idle_state(),
                       playing_with_id(0.70, self.reply_mid),
                       idle_state()])
        return ha

    def test_say_text_still_speaks_when_the_turn_started_playback(self):
        cap = self._cap(); ha = self._ha()
        zone = "media_player.ceiling_speakers"
        cap._turns[zone] = {"ts": 1000.0, "playback": "library://radio/2"}
        r = run(cap, FakeCtx(ha), {"mode": "say_text", "text": "Your timer is finished."})
        self.assertTrue(r["ok"])
        self.assertTrue(r["metadata"].get("said"), "say_text was skipped as a media confirmation")
        self.assertEqual(len([c for c in ha.calls if c[1] == "play_media"]), 1)

    def test_plain_say_is_still_skipped_when_the_turn_started_playback(self):
        # The original behaviour must survive: a media command's spoken confirmation stays skipped.
        cap = self._cap(); ha = self._ha()
        zone = "media_player.ceiling_speakers"
        cap._turns[zone] = {"ts": 1000.0, "playback": "library://radio/2"}
        r = run(cap, FakeCtx(ha), {"mode": "say", "uri": self.norm_uri})
        self.assertTrue(r["ok"])
        self.assertFalse(r["metadata"].get("said"))
        self.assertEqual([c for c in ha.calls if c[1] == "play_media"], [])



class GoldenSequenceTest(unittest.TestCase):
    """AN-01 Task 5: byte-level pin on the calls `say` and `say_text` emit on the SUCCESS path.

    Written BEFORE the AN-01 clip-loop refactor, deliberately. The _play_clip_and_wait extraction
    and the shared-_say fixes must not change these sequences, and a 300-line extraction is not
    proven safe by reading it -- only by asserting on what actually goes out to HA.

    Scope note: this pins the SUCCESS path only. AN-01 intentionally changes one FAILURE path
    (design 8.3a: an ambiguous play_media failure replays the captured source instead of
    un-pausing), which is asserted by its own tests rather than here.
    """

    def setUp(self):
        FakeTimer.created = []
        self.zone = "media_player.ceiling_speakers"
        self.norm_uri = "http://192.168.122.10:8123/api/tts_proxy/x.mp3"
        # MA does not echo the raw URL back; it wraps it.
        self.reply_mid = "builtin://radio/" + self.norm_uri

    def _cap(self):
        return interaction.InteractionCapability(timer_factory=FakeTimer, clock=lambda: 1000.0,
                                                 sleeper=FakeSleeper())

    def _states(self):
        return [playing_with_id(0.36, "library://radio/2"),   # step 1 capture
                playing_with_id(0.40, self.reply_mid),        # start-poll: clip is playing
                idle_state(), idle_state(),                   # finish-poll debounce (ended_seen>=2)
                playing(0.40)]                                # step 8 restore read

    EXPECTED = [("media_player", "media_pause"),
                ("media_player", "volume_set"),
                ("music_assistant", "play_media"),
                ("media_player", "volume_set"),
                ("music_assistant", "play_media")]

    def test_say_success_path_call_sequence(self):
        cap = self._cap()
        ha = FakeHA(playing(0.36)); ha.set_states(self._states())
        r = run(cap, FakeCtx(ha), {"mode": "say", "uri": self.norm_uri})
        self.assertTrue(r["ok"], r)
        self.assertEqual([(d, s) for d, s, _ in ha.calls], self.EXPECTED)
        self.assertEqual(ha.calls[1][2]["volume_level"], 0.40)      # reply_volume
        self.assertEqual(ha.calls[2][2]["media_id"], self.norm_uri)  # the clip
        self.assertEqual(ha.calls[3][2]["volume_level"], 0.36)      # baseline restored
        self.assertEqual(ha.calls[4][2]["media_id"], "library://radio/2")  # source replayed

    def test_say_success_path_timeouts(self):
        cap = self._cap()
        ha = FakeHA(playing(0.36)); ha.set_states(self._states())
        run(cap, FakeCtx(ha), {"mode": "say", "uri": self.norm_uri})
        # play_media gets the long call timeout; the volume writes keep the REST default.
        self.assertEqual([t for s, t in ha.timeouts if s == "play_media"], [20.0, 20.0])
        self.assertEqual([t for s, t in ha.timeouts if s == "volume_set"], [5, 5])
        self.assertEqual([t for s, t in ha.timeouts if s == "media_pause"], [5])

    def test_say_text_success_path_call_sequence(self):
        cap = self._cap()
        ha = FakeHA(playing(0.36)); ha.set_states(self._states())
        ha.tts_url = self.norm_uri
        r = run(cap, FakeCtx(ha), {"mode": "say_text", "text": "Your timer is finished."})
        self.assertTrue(r["ok"], r)
        self.assertEqual(ha.tts_calls, [("tts.piper", "Your timer is finished.")])
        self.assertEqual([(d, s) for d, s, _ in ha.calls], self.EXPECTED)
        self.assertEqual(ha.calls[1][2]["volume_level"], 0.40)
        self.assertEqual(ha.calls[2][2]["media_id"], self.norm_uri)
        self.assertEqual(ha.calls[3][2]["volume_level"], 0.36)
        self.assertEqual(ha.calls[4][2]["media_id"], "library://radio/2")



class AnnounceResolveValidateTest(unittest.TestCase):
    """AN-01 Task 10: design 6.3 and 7 step B.

    The length bound is on the RENDERED text (prefix + message), not the message alone: the prefix
    is configurable and is synthesised into the same clip, so bounding only the message would let
    config.json defeat design 6.5's whole timing model.

    Over-long is REJECTED, never truncated. Truncating a household message can invert its meaning
    -- "do not let the dog out the back gate" clipped at a word boundary becomes "do not let the dog
    out", still fluent, opposite intent, and nobody in the room can tell it was cut.
    """

    def _cap(self):
        return interaction.InteractionCapability(timer_factory=FakeTimer, clock=lambda: 1000.0,
                                                 sleeper=FakeSleeper())

    def _ctx(self):
        ctx = FakeCtx(FakeHA())
        ctx.settings = FakeSettings()          # a per-test instance, so edits do not leak
        return ctx

    # ---- mode surface -------------------------------------------------------

    def test_announce_is_a_valid_mode(self):
        cap = self._cap()
        self.assertIsNone(cap.validate(self._ctx(),
                                       {"mode": "announce", "zone": "z", "text": "hi"}))

    def test_announce_without_text_is_rejected(self):
        cap = self._cap()
        err = cap.validate(self._ctx(), {"mode": "announce", "zone": "z", "text": ""})
        self.assertEqual(err["code"], "invalid_input")
        self.assertIn("announce", err["chat_text"].lower())

    def test_existing_modes_still_validate(self):
        # Guard: extending _MODES must not disturb the modes already in production.
        cap = self._cap()
        ctx = self._ctx()
        for mode in ("duck", "restore", "resume", "pause",
                     "volume_up", "volume_down", "set_volume"):
            self.assertIsNone(cap.validate(ctx, {"mode": mode, "zone": "z"}), mode)
        self.assertIsNone(cap.validate(ctx, {"mode": "say", "zone": "z", "uri": "http://x"}))
        self.assertIsNone(cap.validate(ctx, {"mode": "say_text", "zone": "z", "text": "x"}))

    def test_an_unknown_mode_is_still_rejected(self):
        cap = self._cap()
        err = cap.validate(self._ctx(), {"mode": "annonce", "zone": "z", "text": "hi"})
        self.assertEqual(err["code"], "invalid_input")

    def test_blank_text_rejected_before_any_ha_call(self):
        cap = self._cap()
        ha = FakeHA(playing(0.36))
        ctx = FakeCtx(ha)
        r = run(cap, ctx, {"mode": "announce", "text": "   "})
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"]["code"], "invalid_input")
        self.assertEqual(ha.calls, [])

    # ---- rendering and the bound -------------------------------------------

    def test_a_message_at_exactly_the_limit_is_accepted(self):
        cap = self._cap()
        rendered, err, dropped = cap._render_announcement_text(self._ctx(), "x" * 300)
        self.assertIsNone(err)
        self.assertEqual(rendered, "x" * 300)
        self.assertFalse(dropped)

    def test_no_code_path_truncates_the_message(self):
        cap = self._cap()
        rendered, err, dropped = cap._render_announcement_text(self._ctx(), "y" * 301)
        self.assertIsNone(rendered)
        self.assertEqual(err["code"], "invalid_input")

    def test_the_bound_is_on_prefix_plus_message(self):
        cap = self._cap()
        ctx = self._ctx()
        ctx.settings.announce_prefix = "A" * 40
        ok, err, _ = cap._render_announcement_text(ctx, "m" * 259)     # 40 + 1 + 259 == 300
        self.assertIsNone(err)
        self.assertEqual(ok, "A" * 40 + " " + "m" * 259)
        bad, err2, _ = cap._render_announcement_text(ctx, "m" * 260)   # 301
        self.assertIsNone(bad)
        self.assertEqual(err2["code"], "invalid_input")

    def test_the_rejection_quotes_the_effective_limit(self):
        cap = self._cap()
        ctx = self._ctx()
        ctx.settings.announce_prefix = "Attention."                    # 10 chars + one space
        _, err, _ = cap._render_announcement_text(ctx, "m" * 295)
        self.assertIn("289", err["chat_text"])                         # 300 - 10 - 1

    def test_the_prefix_is_joined_with_a_single_space(self):
        cap = self._cap()
        ctx = self._ctx()
        ctx.settings.announce_prefix = "Announcement."
        rendered, err, _ = cap._render_announcement_text(ctx, "dinner is ready")
        self.assertIsNone(err)
        self.assertEqual(rendered, "Announcement. dinner is ready")

    def test_surrounding_whitespace_is_stripped(self):
        cap = self._cap()
        rendered, err, _ = cap._render_announcement_text(self._ctx(), "  dinner is ready  ")
        self.assertIsNone(err)
        self.assertEqual(rendered, "dinner is ready")

    def test_an_over_long_prefix_is_dropped_not_fatal(self):
        # A misconfigured prefix must not disable every announcement in the house.
        cap = self._cap()
        ctx = self._ctx()
        ctx.settings.announce_prefix = "P" * 41
        rendered, err, dropped = cap._render_announcement_text(ctx, "dinner is ready")
        self.assertIsNone(err)
        self.assertTrue(dropped)
        self.assertEqual(rendered, "dinner is ready")

    def test_a_dropped_prefix_does_not_eat_the_message_budget(self):
        cap = self._cap()
        ctx = self._ctx()
        ctx.settings.announce_prefix = "P" * 100
        rendered, err, dropped = cap._render_announcement_text(ctx, "m" * 300)
        self.assertIsNone(err)
        self.assertTrue(dropped)
        self.assertEqual(rendered, "m" * 300)

    def test_empty_text_is_reported_as_nothing_to_announce(self):
        cap = self._cap()
        rendered, err, _ = cap._render_announcement_text(self._ctx(), "   ")
        self.assertIsNone(rendered)
        self.assertEqual(err["code"], "invalid_input")

    def test_none_text_is_handled(self):
        cap = self._cap()
        rendered, err, _ = cap._render_announcement_text(self._ctx(), None)
        self.assertIsNone(rendered)
        self.assertEqual(err["code"], "invalid_input")

    def test_the_rejection_chat_text_is_ascii_only(self):
        # ONBOARDING section 3: the console throws UnicodeEncodeError on non-ASCII output, so a
        # plain hyphen rather than an en dash.
        cap = self._cap()
        _, err, _ = cap._render_announcement_text(self._ctx(), "z" * 400)
        err["chat_text"].encode("ascii")            # raises if a non-ASCII char slipped in

    # ---- error-code contract -----------------------------------------------

    def test_every_error_code_used_is_in_ERROR_CODES(self):
        # cr.err raises ValueError on an unknown code, so an invalid one turns a handled failure
        # into a crash. An earlier design draft used "precondition_failed", which is not valid.
        import command_result as cr_mod
        for code in ("invalid_input", "unavailable", "upstream_error"):
            self.assertIn(code, cr_mod.ERROR_CODES)
        self.assertNotIn("precondition_failed", cr_mod.ERROR_CODES)

    def test_the_render_helpers_error_codes_are_valid(self):
        import command_result as cr_mod
        cap = self._cap()
        ctx = self._ctx()
        for text in (None, "   ", "q" * 400):
            _, err, _ = cap._render_announcement_text(ctx, text)
            self.assertIsNotNone(err)
            self.assertIn(err["code"], cr_mod.ERROR_CODES)
            self.assertTrue(err["reason"])
            self.assertTrue(err["chat_text"])



class MovingClock(object):
    """A clock the test drives. Paired with AdvancingSleeper so a poll loop's simulated sleeps move
    it, which is what makes the deadline arithmetic in _play_clip_and_wait observable at all."""

    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, secs):
        self.t += secs


class AdvancingSleeper(object):
    def __init__(self, clock, hook=None):
        self.clock = clock
        self.calls = 0
        self._hook = hook

    def __call__(self, secs):
        self.calls += 1
        self.clock.advance(secs)
        if self._hook is not None:
            self._hook(self.calls)


def superseded_after(n):
    """A superseded() that reports False for its first n calls, then True."""
    box = [0]

    def sup():
        box[0] += 1
        return box[0] > n
    return sup


class PlayClipAndWaitTest(unittest.TestCase):
    """AN-01 Task 11: the per-clip play/start-poll/finish-poll body, extracted out of _say.

    Task 5's GoldenSequenceTest is the acceptance criterion for the extraction being
    behaviour-preserving. THIS class covers the surface the extraction newly exposes and which _say
    does not exercise, because _say passes deadline=None deliberately:

      * match_key independent of the played URI -- MA does not echo back what it plays, it wraps it,
        and wraps it differently per media type, so the caller must be able to say what to match on.
      * deadline clipping and the floor -- a read must not be started with less than the floor left.
      * the {"started", "issued", "clip"} return contract, which is how the caller's recovery path
        learns whether the clip actually went out.

    A note on what a deadline is NOT: clipping a socket read bounds that read's inactivity, not the
    wall-clock duration of the call. These tests pin the clipping arithmetic, not a guarantee.
    """

    ZONE = "media_player.ceiling_speakers"
    URI = "http://192.168.122.10:8123/api/tts_proxy/abc.mp3"
    WRAPPED = "builtin://radio/http://192.168.122.10:8123/api/tts_proxy/abc.mp3"

    def _cap(self, clock, sleeper):
        return interaction.InteractionCapability(timer_factory=FakeTimer, clock=clock,
                                                 sleeper=sleeper)

    def _opts(self, **over):
        opts = {"start_timeout": 5.0, "finish_timeout": 10.0, "call_timeout": 20.0,
                "poll_secs": 0.5, "blank_grace": 4.0, "deadline": None, "floor": 0.5}
        opts.update(over)
        return opts

    def _play(self, states, opts=None, superseded=None, match_key=None, ha=None, clock=None):
        clock = clock or MovingClock()
        sleeper = AdvancingSleeper(clock)
        cap = self._cap(clock, sleeper)
        ha = ha if ha is not None else FakeHA()
        if states is not None:
            ha.set_states(states)
        ctx = FakeCtx(ha)
        res = cap._play_clip_and_wait(ctx, "rid1", self.ZONE, self.URI,
                                      match_key if match_key is not None else self.URI,
                                      cap._clip_id(self.URI), opts or self._opts(),
                                      superseded or (lambda: False))
        return res, ha, cap, clock, sleeper

    def _match(self):
        return playing_with_id(0.70, self.WRAPPED)

    def _blank(self):
        return {"state": "playing", "attributes": {"volume_level": 0.70,
                                                   "media_content_id": ""}}

    # ---- play_media -----------------------------------------------------------

    def test_it_issues_play_media_with_the_uri_and_the_call_timeout(self):
        res, ha, _, _, _ = self._play([self._match(), idle_state(), idle_state()])
        self.assertIn(("music_assistant", "play_media",
                       {"entity_id": self.ZONE, "media_id": self.URI}), ha.calls)
        self.assertIn(("play_media", 20.0), ha.timeouts)
        self.assertTrue(res["issued"])

    def test_a_play_media_failure_propagates_rather_than_being_swallowed(self):
        # The caller's finally is the recovery path -- it owns the volume restore and the un-pause,
        # so it must see the exception. Handling it here would strand the zone at reply volume.
        clock = MovingClock()
        cap = self._cap(clock, AdvancingSleeper(clock))
        ctx = FakeCtx(FakeHA(write_boom=IOError("MA 500")))
        self.assertRaises(IOError, cap._play_clip_and_wait, ctx, "rid1", self.ZONE, self.URI,
                          self.URI, "clip", self._opts(), lambda: False)

    def test_the_clip_fingerprint_is_returned_untouched(self):
        res, _, cap, _, _ = self._play([self._match(), idle_state(), idle_state()])
        self.assertEqual(res["clip"], cap._clip_id(self.URI))

    # ---- start poll -----------------------------------------------------------

    def test_started_is_true_when_the_cid_merely_CONTAINS_the_match_key(self):
        # MA does not echo the URL back; it wraps it. Equality matching never fires.
        res, _, _, _, _ = self._play([self._match(), idle_state(), idle_state()])
        self.assertTrue(res["started"])

    def test_the_match_key_can_differ_from_the_uri_that_was_played(self):
        # The reason match_key is a separate parameter: a caller may need to match on something
        # other than what it handed to play_media.
        res, ha, _, _, _ = self._play([playing_with_id(0.7, "builtin://track/OTHER-KEY"),
                                       idle_state(), idle_state()],
                                      match_key="OTHER-KEY")
        self.assertTrue(res["started"])
        # ...and what went to MA is still the real URI, not the match key.
        self.assertIn(("music_assistant", "play_media",
                       {"entity_id": self.ZONE, "media_id": self.URI}), ha.calls)

    def test_a_clip_that_never_starts_reports_issued_but_not_started(self):
        res, _, _, _, _ = self._play([idle_state()] * 20)
        self.assertTrue(res["issued"])
        self.assertFalse(res["started"])

    def test_the_start_poll_is_bounded_by_the_start_timeout(self):
        res, ha, _, _, _ = self._play([idle_state()] * 40,
                                      opts=self._opts(start_timeout=2.0, poll_secs=0.5))
        self.assertFalse(res["started"])
        self.assertEqual(len(ha.state_timeouts), 4)          # 2.0s / 0.5s

    def test_a_read_failure_during_the_start_poll_is_survived(self):
        # A read blip must not abort a clip that is actually playing. FakeHA returns None once its
        # scripted states run out, which the implementation must tolerate as an empty state.
        ha = FakeHA()
        ha.set_states([None, self._match(), idle_state(), idle_state()])
        res, _, _, _, _ = self._play(None, ha=ha)
        self.assertTrue(res["started"])

    def test_it_returns_early_when_superseded_during_the_start_poll(self):
        res, ha, _, _, _ = self._play([self._match()] * 10, superseded=superseded_after(0))
        self.assertTrue(res["issued"])
        self.assertFalse(res["started"])
        self.assertEqual(ha.state_timeouts, [])              # bailed before reading anything

    # ---- finish poll ----------------------------------------------------------

    def test_it_returns_early_when_superseded_during_the_finish_poll(self):
        res, _, _, _, _ = self._play([self._match()] * 10, superseded=superseded_after(1))
        self.assertTrue(res["started"])

    def test_two_consecutive_ended_observations_are_required(self):
        # A single flicker of state or cid must not end the wait: doing so cut replies off and
        # replayed the source over them.
        states = [self._match(),        # start poll
                  self._match(),        # finish: playing
                  idle_state(),         # finish: flicker -- must NOT end it
                  self._match(),        # finish: playing again, streak reset
                  idle_state(),         # finish: ended #1
                  idle_state()]         # finish: ended #2 -> break
        res, ha, _, _, _ = self._play(states)
        self.assertTrue(res["started"])
        self.assertEqual(len(ha.state_timeouts), 6)

    def test_an_empty_cid_is_not_an_ending_while_the_player_says_playing(self):
        # MA transiently blanks media_content_id mid-clip.
        states = [self._match(), self._blank(), self._blank(), self._blank(),
                  self._match(), idle_state(), idle_state()]
        res, ha, _, _, _ = self._play(states, opts=self._opts(blank_grace=4.0))
        self.assertTrue(res["started"])
        self.assertEqual(len(ha.state_timeouts), 7)

    def test_a_blank_cid_past_the_grace_ends_the_wait(self):
        # Beyond the grace we cannot tell, and holding the zone at reply volume for the whole
        # finish timeout is worse than finishing.
        states = [self._match()] + [self._blank()] * 20
        with self.assertLogs("resolver", level="INFO") as cm:
            res, ha, _, _, _ = self._play(states, opts=self._opts(blank_grace=1.0))
        self.assertTrue(res["started"])
        self.assertEqual(len(ha.state_timeouts), 3)          # start + 2 blanks == 1.0s of grace
        self.assertTrue(any("cid stayed empty" in m for m in cm.output), cm.output)

    def test_the_blank_grace_is_never_shorter_than_one_poll(self):
        # A grace below the poll interval would make the very first blank fatal.
        states = [self._match()] + [self._blank()] * 20
        res, ha, _, _, _ = self._play(states, opts=self._opts(blank_grace=0.01, poll_secs=0.5))
        self.assertEqual(len(ha.state_timeouts), 2)

    def test_the_finish_poll_is_bounded_by_the_finish_timeout(self):
        states = [self._match()] * 40
        res, ha, _, _, _ = self._play(states, opts=self._opts(finish_timeout=2.0, poll_secs=0.5))
        self.assertTrue(res["started"])
        self.assertEqual(len(ha.state_timeouts), 5)          # 1 start + 2.0s/0.5s finish

    def test_a_read_failure_during_the_finish_poll_is_survived(self):
        ha = FakeHA()
        ha.set_states([self._match(), None] + [self._match()] * 3)
        res, _, _, _, _ = self._play(None, ha=ha, opts=self._opts(finish_timeout=1.5))
        self.assertTrue(res["started"])

    # ---- deadline clipping (design 6.5) --------------------------------------

    def test_with_no_deadline_reads_get_the_plain_default(self):
        # say / say_text keep accumulated-sleep bounding: converting a live, proven path with no
        # defect motivating it would be a timing change for its own sake.
        _, ha, _, _, _ = self._play([self._match(), idle_state(), idle_state()])
        self.assertEqual(set(ha.state_timeouts), set([10]))

    def test_reads_are_clipped_to_what_is_left_of_the_deadline(self):
        clock = MovingClock(1000.0)
        _, ha, _, _, _ = self._play([self._match(), idle_state(), idle_state()],
                                    opts=self._opts(deadline=1003.0), clock=clock)
        self.assertEqual(ha.state_timeouts[0], 3.0)

    def test_the_clip_is_only_ever_downward(self):
        # A deadline further out than the default must not INFLATE a read's timeout.
        clock = MovingClock(1000.0)
        _, ha, _, _, _ = self._play([self._match(), idle_state(), idle_state()],
                                    opts=self._opts(deadline=1600.0), clock=clock)
        self.assertEqual(ha.state_timeouts[0], 10)

    def test_no_read_is_started_with_less_than_the_floor_left(self):
        # Starting a blocking read with 0.2s of budget buys nothing and overshoots the phase.
        res, ha, _, _, _ = self._play([self._match()] * 10,
                                      opts=self._opts(deadline=1000.2, floor=0.5))
        self.assertTrue(res["issued"])
        self.assertFalse(res["started"])
        self.assertEqual(ha.state_timeouts, [])

    def test_the_deadline_can_end_the_start_poll_before_the_start_timeout(self):
        res, ha, _, _, _ = self._play([idle_state()] * 40,
                                      opts=self._opts(start_timeout=5.0, deadline=1001.0,
                                                      poll_secs=0.5, floor=0.5))
        self.assertFalse(res["started"])
        self.assertEqual(len(ha.state_timeouts), 2)          # not the 10 that 5.0s/0.5s would give

    def test_the_deadline_can_end_the_finish_poll_before_the_finish_timeout(self):
        res, ha, _, _, _ = self._play([self._match()] * 40,
                                      opts=self._opts(finish_timeout=30.0, deadline=1001.0,
                                                      poll_secs=0.5, floor=0.5))
        self.assertTrue(res["started"])
        self.assertEqual(len(ha.state_timeouts), 3)          # 1 start + 2 finish, then out of time

    # ---- the clip URL must not reach the log --------------------------------

    def test_the_uri_is_never_logged(self):
        states = [idle_state()] * 20                          # forces the "did not start" warning
        with self.assertLogs("resolver", level="INFO") as cm:
            self._play(states)
        joined = "\n".join(cm.output)
        self.assertTrue(joined, "expected log output, so this test is not vacuous")
        self.assertNotIn("tts_proxy", joined)
        self.assertNotIn(self.URI, joined)



# A signed media URL is a BEARER CREDENTIAL. Every fixture below uses an obvious placeholder, never
# a real signature, and the redaction tests assert on the placeholder to prove they are not vacuous.
FAKE_SIG = "REDACTED-NOT-A-REAL-SIGNATURE"


class ClipSequenceTest(unittest.TestCase):
    """AN-01 Task 12: design 8.1-8.3. One baseline, one raise, N clips, one restore, one replay.

    Fixtures follow the post-G1 design corrections, not design 8.2 as originally written:

      * MA wraps by MEDIA TYPE -- the chime comes back as "builtin://track/<url>", not the
        "builtin://radio/<url>" that interaction.py's comment documents for TTS clips.
      * The query string is PRESERVED in MA's echo. Design 8.2 assumed it would be stripped and
        specified a path-only match key for the chime; AN-1 measured otherwise, so every clip's
        match key is its full normalised URI.
    """

    def setUp(self):
        FakeTimer.created = []
        self.zone = "media_player.ceiling_speakers"
        self.chime = ("http://192.168.122.10:8123/media/local/timer_chime.wav?authSig="
                      + FAKE_SIG)
        self.tts = "http://192.168.122.10:8123/api/tts_proxy/x.mp3"

    def _cap(self):
        return interaction.InteractionCapability(timer_factory=FakeTimer, clock=lambda: 1000.0,
                                                 sleeper=FakeSleeper())

    def _states(self):
        return [playing_with_id(0.36, "library://radio/2"),                    # capture
                playing_with_id(0.80, "builtin://track/" + self.chime),        # chime start
                idle_state(), idle_state(),                                    # chime end
                playing_with_id(0.80, "builtin://radio/" + self.tts),          # tts start
                idle_state(), idle_state(),                                    # tts end
                playing(0.80)]                                                 # restore read

    def _two_clip(self, cap, ha, **over):
        params = {"mode": "say", "uri": self.tts,
                  "uris": [self.chime, self.tts],
                  "match_keys": [self.chime, self.tts],      # full URIs -- correction 1
                  "finish_timeouts": [15.0, 45.0],
                  "volume_override": 0.80}
        params.update(over)
        return capability.run(cap, FakeCtx(ha), params, "rid-seq")

    def _ready(self):
        cap = self._cap()
        ha = FakeHA(playing(0.36))
        ha.set_states(self._states())
        return cap, ha

    def test_two_clips_play_in_order_with_one_raise_and_one_restore(self):
        cap, ha = self._ready()
        r = self._two_clip(cap, ha)
        self.assertTrue(r["ok"])
        self.assertEqual([(d, sv) for d, sv, _ in ha.calls],
                         [("media_player", "media_pause"),
                          ("media_player", "volume_set"),
                          ("music_assistant", "play_media"),
                          ("music_assistant", "play_media"),
                          ("media_player", "volume_set"),
                          ("music_assistant", "play_media")])
        self.assertEqual(ha.calls[2][2]["media_id"], self.chime)
        self.assertEqual(ha.calls[3][2]["media_id"], self.tts)
        self.assertEqual(ha.calls[5][2]["media_id"], "library://radio/2")

    def test_volume_override_is_used_not_reply_volume(self):
        cap, ha = self._ready()
        self._two_clip(cap, ha)
        self.assertEqual(ha.calls[1][2]["volume_level"], 0.80)

    def test_volume_override_of_zero_is_honoured(self):
        # An `or` fallback would silently discard 0.0; the check must be `is None`.
        cap = self._cap()
        ha = FakeHA(playing(0.36))
        ha.set_states([playing_with_id(0.36, "library://radio/2"),
                       playing_with_id(0.0, "builtin://radio/" + self.tts),
                       idle_state(), idle_state(), playing(0.0)])
        capability.run(cap, FakeCtx(ha),
                       {"mode": "say", "uri": self.tts, "volume_override": 0.0}, "rid-z")
        self.assertEqual(ha.calls[1][2]["volume_level"], 0.0)

    def test_baseline_is_captured_once_and_restored_once(self):
        cap, ha = self._ready()
        self._two_clip(cap, ha)
        self.assertEqual([c[2]["volume_level"] for c in ha.calls if c[1] == "volume_set"],
                         [0.80, 0.36])

    def test_source_is_replayed_once_after_both_clips(self):
        cap, ha = self._ready()
        r = self._two_clip(cap, ha)
        self.assertTrue(r["metadata"]["replayed"])
        self.assertEqual(len([c for c in ha.calls if c[1] == "play_media"]), 3)   # 2 clips + replay

    def test_the_chime_match_key_is_the_full_uri_query_included(self):
        # AN-1 measured the query as PRESERVED in MA's echo, refuting design 8.2's assumption that
        # it would be stripped. Both clips must therefore be seen to start.
        cap, ha = self._ready()
        r = self._two_clip(cap, ha)
        clips = r["metadata"]["clips"]
        self.assertEqual(len(clips), 2)
        self.assertTrue(clips[0]["started"])
        self.assertTrue(clips[1]["started"])

    def test_a_path_only_match_key_would_still_match_but_is_not_what_we_send(self):
        # Guard on the CONTRACT, not just the outcome: containment means a path-only key happens to
        # match too, so an outcome-only assertion could not tell the two contracts apart. Assert on
        # what actually goes to MA and on the full-URI key being sufficient.
        cap, ha = self._ready()
        r = self._two_clip(cap, ha)
        self.assertTrue(r["metadata"]["clips"][0]["started"])
        self.assertIn("authSig=", ha.calls[2][2]["media_id"])

    def test_the_chime_is_matched_through_the_track_wrapper(self):
        # Names the exact wrapper MA used at AN-1. If MA's wrapping changes, this fails loudly.
        cap = self._cap()
        ha = FakeHA(playing(0.36))
        ha.set_states([playing_with_id(0.36, "library://radio/2"),
                       playing_with_id(0.80, "builtin://track/" + self.chime),
                       idle_state(), idle_state(),
                       playing_with_id(0.80, "builtin://radio/" + self.tts),
                       idle_state(), idle_state(), playing(0.80)])
        r = self._two_clip(cap, ha)
        self.assertTrue(r["metadata"]["clips"][0]["started"])

    def test_each_clip_gets_its_own_finish_budget(self):
        cap, ha = self._ready()
        r = self._two_clip(cap, ha)
        self.assertTrue(r["ok"])          # 15s chime + 45s message, not one budget twice

    def test_a_failed_chime_does_not_make_the_reply_a_failure(self):
        # design 8.3's asymmetry: reply_started tracks the LAST clip -- the message. A chime that
        # never starts is a degraded announcement, not a silent one.
        cap = self._cap()
        ha = FakeHA(playing(0.36))
        # Exactly the 10 reads the chime's start poll consumes (5.0s budget / 0.5s poll), so the
        # message's own start poll still finds its echo rather than more idle.
        ha.set_states([playing_with_id(0.36, "library://radio/2")]
                      + [idle_state()] * 10                            # chime never starts
                      + [playing_with_id(0.80, "builtin://radio/" + self.tts),   # message starts
                         idle_state(), idle_state(), playing(0.80)])
        r = self._two_clip(cap, ha, finish_timeouts=[15.0, 45.0])
        self.assertTrue(r["ok"])
        clips = r["metadata"]["clips"]
        self.assertFalse(clips[0]["started"])
        self.assertTrue(clips[1]["started"])
        self.assertTrue(r["metadata"]["reply_started"])
        self.assertFalse(r["metadata"]["likely_silent"])

    def test_a_failed_message_is_reported_as_likely_silent(self):
        cap = self._cap()
        ha = FakeHA(playing(0.36))
        ha.set_states([playing_with_id(0.36, "library://radio/2"),
                       playing_with_id(0.80, "builtin://track/" + self.chime),
                       idle_state(), idle_state()] + [idle_state()] * 120)
        r = self._two_clip(cap, ha)
        clips = r["metadata"]["clips"]
        self.assertTrue(clips[0]["started"])
        self.assertFalse(clips[1]["started"])
        self.assertFalse(r["metadata"]["reply_started"])
        self.assertTrue(r["metadata"]["likely_silent"])

    def test_every_clip_reports_issued_even_when_none_start(self):
        cap = self._cap()
        ha = FakeHA(playing(0.36))
        ha.set_states([playing_with_id(0.36, "library://radio/2")] + [idle_state()] * 200)
        r = self._two_clip(cap, ha)
        self.assertTrue(all(c["issued"] for c in r["metadata"]["clips"]))
        self.assertEqual(len([c for c in ha.calls if c[1] == "play_media"]), 3)   # 2 clips + replay

    def test_each_clip_gets_its_own_fingerprint(self):
        cap, ha = self._ready()
        r = self._two_clip(cap, ha)
        clips = r["metadata"]["clips"]
        self.assertNotEqual(clips[0]["clip"], clips[1]["clip"])
        self.assertEqual(clips[1]["clip"], cap._clip_id(self.tts))

    def test_a_single_uri_still_works(self):
        cap = self._cap()
        ha = FakeHA(playing(0.36))
        ha.set_states([playing_with_id(0.36, "library://radio/2"),
                       playing_with_id(0.40, "builtin://radio/" + self.tts),
                       idle_state(), idle_state(), playing(0.40)])
        r = capability.run(cap, FakeCtx(ha), {"mode": "say", "uri": self.tts}, "rid-one")
        self.assertTrue(r["ok"])
        self.assertEqual(len([c for c in ha.calls if c[1] == "play_media"]), 2)
        self.assertEqual(len(r["metadata"]["clips"]), 1)

    def test_match_keys_default_to_the_uris_when_omitted(self):
        cap = self._cap()
        ha = FakeHA(playing(0.36))
        ha.set_states(self._states())
        r = capability.run(cap, FakeCtx(ha),
                           {"mode": "say", "uri": self.tts,
                            "uris": [self.chime, self.tts],
                            "finish_timeouts": [15.0, 45.0],
                            "volume_override": 0.80}, "rid-nokeys")
        self.assertTrue(all(c["started"] for c in r["metadata"]["clips"]))

    def test_finish_timeouts_default_to_the_reply_timeout_when_omitted(self):
        cap = self._cap()
        ha = FakeHA(playing(0.36))
        ha.set_states(self._states())
        r = capability.run(cap, FakeCtx(ha),
                           {"mode": "say", "uri": self.tts,
                            "uris": [self.chime, self.tts],
                            "volume_override": 0.80}, "rid-nobudget")
        self.assertTrue(r["ok"])
        self.assertEqual(len(r["metadata"]["clips"]), 2)

    def test_the_match_key_list_is_positional_not_reordered(self):
        # Swapping the keys must break matching -- otherwise the pairing is not really per-clip and
        # the whole match_keys contract would be untested.
        #
        # Only the chime's echo is scripted, with an idle fallback. Matching is by CONTAINMENT and
        # the polls read straight through the script, so leaving the message's echo in would let
        # clip 1 -- now holding the message's key -- reach it and "match", passing for the wrong
        # reason.
        cap = self._cap()
        ha = FakeHA(idle_state())
        ha.set_states([playing_with_id(0.36, "library://radio/2"),
                       playing_with_id(0.80, "builtin://track/" + self.chime),
                       idle_state(), idle_state()])
        r = self._two_clip(cap, ha, match_keys=[self.tts, self.chime])
        self.assertFalse(any(c["started"] for c in r["metadata"]["clips"]))


class ClipDeadlineTest(unittest.TestCase):
    """AN-01 Task 12: design 6.5. Announcement clips poll against a wall-clock deadline and clip
    each read to what is left; say/say_text keep accumulated-sleep bounding.

    A deadline bounds each READ's inactivity allowance, not the call's wall-clock duration. These
    tests pin the clipping arithmetic; they do not assert a total-duration guarantee.
    """

    def setUp(self):
        self.tts = "http://192.168.122.10:8123/api/tts_proxy/x.mp3"
        self.now = [1000.0]

    def _sleep(self, secs):
        self.now[0] += secs

    def _cap(self):
        return interaction.InteractionCapability(timer_factory=FakeTimer,
                                                 clock=lambda: self.now[0],
                                                 sleeper=self._sleep)

    def _watching_ha(self, seen, burn):
        ha = FakeHA(idle_state())

        def watch(entity_id, timeout=None):
            # Only the clip poll passes a timeout. _say's own bookkeeping reads -- the pre-turn
            # capture and the pre-restore read -- call with no timeout at all, and recording those
            # would mix un-clipped reads into assertions about clipping.
            if timeout is not None:
                seen.append(timeout)
            self.now[0] += burn
            return idle_state()
        ha.get_entity_state = watch
        return ha

    def test_a_read_is_clipped_to_the_remaining_deadline(self):
        seen = []
        cap = self._cap()
        ha = self._watching_ha(seen, 0.5)
        capability.run(cap, FakeCtx(ha),
                       {"mode": "say", "uri": self.tts, "uris": [self.tts],
                        "match_keys": [self.tts], "finish_timeouts": [3.0],
                        "deadline_from_now": 3.0}, "rid-dl")
        self.assertTrue(seen)
        self.assertTrue(all(t <= 3.0 for t in seen), seen)
        self.assertTrue(min(seen) < 10)

    def test_no_blocking_call_is_started_below_the_floor(self):
        seen = []
        cap = self._cap()
        ha = self._watching_ha(seen, 0.9)
        capability.run(cap, FakeCtx(ha),
                       {"mode": "say", "uri": self.tts, "uris": [self.tts],
                        "match_keys": [self.tts], "finish_timeouts": [1.0],
                        "deadline_from_now": 1.0}, "rid-fl")
        self.assertTrue(all(t >= 0.5 for t in seen), seen)

    def test_the_deadline_spans_the_whole_sequence_not_each_clip(self):
        # One deadline for the turn: a two-clip announcement must not get two full budgets.
        seen = []
        cap = self._cap()
        ha = self._watching_ha(seen, 0.5)
        capability.run(cap, FakeCtx(ha),
                       {"mode": "say", "uri": self.tts, "uris": [self.tts, self.tts],
                        "match_keys": [self.tts, self.tts], "finish_timeouts": [3.0, 3.0],
                        "deadline_from_now": 3.0}, "rid-span")
        self.assertTrue(all(t <= 3.0 for t in seen), seen)
        self.assertLessEqual(self.now[0], 1000.0 + 3.0 + 1.0)   # one budget, plus a poll of slack

    def test_say_and_say_text_still_bound_by_accumulated_sleep(self):
        seen = []
        cap = self._cap()
        ha = self._watching_ha(seen, 30.0)
        capability.run(cap, FakeCtx(ha), {"mode": "say", "uri": self.tts}, "rid-acc")
        # No deadline: the default timeout is used unclipped, exactly as today.
        self.assertEqual(set(seen), set([10]))


class SignedUrlRedactionTest(unittest.TestCase):
    """AN-01 post-G1 correction 2: a signed media URL is a bearer credential, and it travels inside
    the media_content_id HA reports back on every poll.

    _say's finish-poll used to log cid[:60]. For the URL measured at AN-1 those 60 characters stop
    just short of authSig -- luck, not a guarantee. A shorter host or path writes a live credential
    into resolver.log, which is world-readable on the host. A truncation is not a redaction.
    """

    SECRET = "s3cr3t-" + FAKE_SIG

    def _cap(self):
        return interaction.InteractionCapability(timer_factory=FakeTimer, clock=lambda: 1000.0,
                                                 sleeper=FakeSleeper())

    # ---- the helper ---------------------------------------------------------

    def test_authsig_is_redacted(self):
        cap = self._cap()
        out = cap._redact_uri("http://h:8123/media/local/c.wav?authSig=" + self.SECRET)
        self.assertNotIn(self.SECRET, out)
        self.assertIn("authSig=REDACTED", out)

    def test_the_other_credential_parameters_are_redacted(self):
        cap = self._cap()
        for param in ("sig", "signature", "token", "access_token", "AUTHSIG"):
            out = cap._redact_uri("http://h/x?" + param + "=" + self.SECRET)
            self.assertNotIn(self.SECRET, out, param)

    def test_redaction_reaches_inside_a_wrapped_uri(self):
        # The credential arrives wrapped: "builtin://track/http://.../c.wav?authSig=..."
        cap = self._cap()
        out = cap._redact_uri("builtin://track/http://h:8123/media/local/c.wav?authSig="
                              + self.SECRET)
        self.assertNotIn(self.SECRET, out)
        self.assertTrue(out.startswith("builtin://track/"))

    def test_a_second_parameter_after_the_secret_survives(self):
        cap = self._cap()
        out = cap._redact_uri("http://h/x?authSig=" + self.SECRET + "&fmt=wav")
        self.assertNotIn(self.SECRET, out)
        self.assertIn("fmt=wav", out)

    def test_an_ordinary_uri_is_left_alone(self):
        cap = self._cap()
        for u in ("library://radio/2", "builtin://radio/http://h/api/tts_proxy/x.mp3", "", None):
            self.assertEqual(cap._redact_uri(u), u or "")

    def test_a_bare_word_that_merely_ends_in_sig_is_not_mangled(self):
        # "authSig" must not be found inside an unrelated word, and vice versa.
        cap = self._cap()
        self.assertEqual(cap._redact_uri("http://h/x?design=ok"), "http://h/x?design=ok")

    # ---- every log line that touches a cid ----------------------------------

    def test_no_log_record_of_a_chime_turn_contains_the_signature(self):
        cap = self._cap()
        chime = "http://192.168.122.10:8123/media/local/timer_chime.wav?authSig=" + self.SECRET
        tts = "http://192.168.122.10:8123/api/tts_proxy/x.mp3"
        other = "builtin://track/http://192.168.122.10:8123/media/local/z.wav?authSig=" + self.SECRET
        ha = FakeHA(playing(0.36))
        # The message clip ends because the cid names something ELSE -- which is the path that makes
        # the finish-poll exit line actually emit a cid. Ending on `idle` would emit an empty one and
        # the test would pass without proving anything.
        ha.set_states([playing_with_id(0.36, "library://radio/2"),
                       playing_with_id(0.80, "builtin://track/" + chime),
                       idle_state(), idle_state(),
                       playing_with_id(0.80, "builtin://radio/" + tts),
                       playing_with_id(0.80, other), playing_with_id(0.80, other),
                       playing(0.80)])
        with self.assertLogs("resolver", level="INFO") as cm:
            capability.run(cap, FakeCtx(ha),
                           {"mode": "say", "uri": tts, "uris": [chime, tts],
                            "match_keys": [chime, tts], "finish_timeouts": [15.0, 45.0],
                            "volume_override": 0.80}, "rid-red")
        joined = "\n".join(cm.output)
        self.assertIn("cid=", joined, "the finish-poll exit line must have emitted a cid")
        self.assertNotIn(self.SECRET, joined)
        self.assertNotIn("authSig=" + self.SECRET, joined)

    def test_the_pause_source_line_is_redacted(self):
        cap = self._cap()
        signed = "builtin://track/http://h:8123/media/local/c.wav?authSig=" + self.SECRET
        ha = FakeHA(playing_with_id(0.4, signed))
        with self.assertLogs("resolver", level="INFO") as cm:
            capability.run(cap, FakeCtx(ha), {"mode": "pause"}, "rid-p")
        self.assertNotIn(self.SECRET, "\n".join(cm.output))

    def test_the_resume_replay_lines_are_redacted(self):
        cap = self._cap()
        signed = "http://h:8123/media/local/c.wav?authSig=" + self.SECRET
        # Force it into _last_source directly: remember_source now refuses this shape on purpose
        # (correction 3), so this is the belt-and-braces case of a value that got in some other way.
        cap._last_source["media_player.ceiling_speakers"] = signed
        ha = FakeHA(playing(0.4))
        with self.assertLogs("resolver", level="INFO") as cm:
            capability.run(cap, FakeCtx(ha), {"mode": "resume"}, "rid-r")
        self.assertNotIn(self.SECRET, "\n".join(cm.output))

    def test_the_fresh_playback_skip_line_is_redacted(self):
        cap = self._cap()
        zone = "media_player.ceiling_speakers"
        signed = "builtin://track/http://h:8123/media/local/c.wav?authSig=" + self.SECRET
        cap._turns[zone] = {"ts": 1000.0, "playback": signed, "stopped": False}
        ha = FakeHA(playing(0.4))
        with self.assertLogs("resolver", level="INFO") as cm:
            capability.run(cap, FakeCtx(ha),
                           {"mode": "say", "uri": "http://h/api/tts_proxy/x.mp3"}, "rid-fp")
        self.assertNotIn(self.SECRET, "\n".join(cm.output))


class EphemeralChimeSourceTest(unittest.TestCase):
    """AN-01 post-G1 correction 3: a chime is an ephemeral clip, never a durable source.

    _is_reply_uri excluded exactly two forms -- tts_proxy and builtin://radio/http. The chime
    arrives as builtin://track/http://... and matched NEITHER, so remember_source would have kept a
    spent chime as the zone's last real source. `resume` would then replay it instead of the
    operator's music, by a URL whose signature has expired: a silent failure two layers from its
    symptom. Same class of defect as the 2026-09-05 stop/replay bug in CHANGELOG.md.
    """

    ZONE = "media_player.ceiling_speakers"
    SIGNED_CHIME = ("http://192.168.122.10:8123/media/local/timer_chime.wav?authSig="
                    + FAKE_SIG)

    def _cap(self):
        return interaction.InteractionCapability(timer_factory=FakeTimer, clock=lambda: 1000.0,
                                                 sleeper=FakeSleeper())

    def test_the_track_wrapped_chime_is_classified_as_a_clip(self):
        # Names MA's exact wrapper, so a change in MA's wrapping fails loudly here rather than
        # silently re-enabling the bug.
        cap = self._cap()
        self.assertTrue(cap._is_reply_uri("builtin://track/" + self.SIGNED_CHIME))

    def test_the_unwrapped_signed_chime_url_is_also_a_clip(self):
        # This is the form resolve_media_source returns and _say hands to play_media, so it is what
        # a capture read can see before MA has wrapped it.
        cap = self._cap()
        self.assertTrue(cap._is_reply_uri(self.SIGNED_CHIME))

    def test_the_existing_clip_forms_are_still_classified_as_clips(self):
        cap = self._cap()
        self.assertTrue(cap._is_reply_uri("http://h:8123/api/tts_proxy/x.mp3"))
        self.assertTrue(cap._is_reply_uri("builtin://radio/http://h:8123/api/tts_proxy/x.mp3"))

    def test_real_music_is_still_a_durable_source(self):
        # The narrow rule matters: a local library track must stay resumable.
        #
        # "builtin://radio/http..." is deliberately NOT in this list. The pre-existing rule claims
        # that whole prefix for reply clips, so a wrapped internet-radio stream would be classified
        # as ephemeral too. That is prior behaviour, unrelated to the chime, and in this house radio
        # stations arrive as "library://radio/N" -- so it is left exactly as it was rather than
        # widened or narrowed inside this task.
        cap = self._cap()
        for u in ("library://radio/2", "library://track/1234",
                  "http://stream.example/live.mp3", "spotify://track/abc"):
            self.assertFalse(cap._is_reply_uri(u), u)

    def test_a_track_wrapper_that_is_not_media_local_is_still_a_source(self):
        cap = self._cap()
        self.assertFalse(cap._is_reply_uri("builtin://track/http://stream.example/song.mp3"))

    def test_remember_source_refuses_the_chime(self):
        cap = self._cap()
        cap.remember_source(self.ZONE, "library://radio/2")
        cap.remember_source(self.ZONE, "builtin://track/" + self.SIGNED_CHIME)
        self.assertEqual(cap._last_source[self.ZONE], "library://radio/2")

    def test_resume_does_not_replay_a_chime_left_in_the_player(self):
        # The other door into the same bug: _resume's "replay the loaded source" branch reads the
        # cid straight off the player, so it needs the same classification.
        cap = self._cap()
        ha = FakeHA(playing_with_id(0.4, "builtin://track/" + self.SIGNED_CHIME))
        r = capability.run(cap, FakeCtx(ha), {"mode": "resume"}, "rid-rc")
        self.assertTrue(r["ok"])
        self.assertFalse(r["metadata"]["resumed"])
        self.assertEqual([c for c in ha.calls if c[1] == "play_media"], [])

    def test_a_chime_turn_leaves_the_real_source_resumable(self):
        # End to end: the announcement's own clips must not displace the radio station.
        cap = self._cap()
        tts = "http://192.168.122.10:8123/api/tts_proxy/x.mp3"
        ha = FakeHA(playing(0.36))
        ha.set_states([playing_with_id(0.36, "library://radio/2"),
                       playing_with_id(0.80, "builtin://track/" + self.SIGNED_CHIME),
                       idle_state(), idle_state(),
                       playing_with_id(0.80, "builtin://radio/" + tts),
                       idle_state(), idle_state(), playing(0.80)])
        capability.run(cap, FakeCtx(ha),
                       {"mode": "say", "uri": tts, "uris": [self.SIGNED_CHIME, tts],
                        "match_keys": [self.SIGNED_CHIME, tts],
                        "finish_timeouts": [15.0, 45.0], "volume_override": 0.80}, "rid-e2e")
        self.assertEqual(cap._last_source[self.ZONE], "library://radio/2")



class GenerationAdoptionTest(unittest.TestCase):
    """AN-01 Task 13: design 9.2. A pre-claimed gen is stale by the time _say adopts it.

    _announce has to own the turn BEFORE it touches the microphone, which is earlier than _say's
    step 2. Between the claim and the adoption it spends up to ~17s on the mic state capture (10s),
    the switch.turn_on write (5s) and up to 2s of confirmation -- steps F-G only; the two URL
    resolutions happen at C/D, before the claim, so they are outside that window.

    Adopting such a gen unchecked lets a stale announcement overwrite a NEWER turn's ownership
    marker: the ratchet the S1b-2 ownership decision exists to prevent, where a superseded turn
    restores its own baseline over the live one and the zone craters or sticks loud.

    The check and the publish must happen under ONE lock. A check outside it is the same race, one
    instruction later.
    """

    def setUp(self):
        FakeTimer.created = []
        self.zone = "media_player.ceiling_speakers"
        self.tts = "http://192.168.122.10:8123/api/tts_proxy/x.mp3"

    def _cap(self):
        return interaction.InteractionCapability(timer_factory=FakeTimer, clock=lambda: 1000.0,
                                                 sleeper=FakeSleeper())

    def _happy_states(self):
        return [playing_with_id(0.36, "library://radio/2"),
                playing_with_id(0.40, "builtin://radio/" + self.tts),
                idle_state(), idle_state(), playing(0.40)]

    # ---- the helper ---------------------------------------------------------

    def test_claim_gen_bumps_and_returns_the_new_generation(self):
        cap = self._cap()
        self.assertEqual(cap._claim_gen(self.zone), 1)
        self.assertEqual(cap._claim_gen(self.zone), 2)

    def test_claim_gen_records_the_claim_so_say_can_see_it(self):
        cap = self._cap()
        mine = cap._claim_gen(self.zone)
        self.assertEqual(cap._say_gen[self.zone], mine)

    def test_claim_gen_counts_per_zone(self):
        cap = self._cap()
        self.assertEqual(cap._claim_gen("media_player.a"), 1)
        self.assertEqual(cap._claim_gen("media_player.b"), 1)
        self.assertEqual(cap._claim_gen("media_player.a"), 2)

    def test_claim_gen_is_atomic_under_concurrent_callers(self):
        # "Atomic" is the whole point of the helper: HTTP threads and the timer thread claim against
        # the same counter. A read-then-write without the lock hands two turns the same generation,
        # and neither would ever see itself superseded.
        cap = self._cap()
        got = []
        guard = threading.Lock()

        def claim():
            g = cap._claim_gen(self.zone)
            with guard:
                got.append(g)

        threads = [threading.Thread(target=claim) for _ in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sorted(got), list(range(1, 51)))

    # ---- a stale claim ------------------------------------------------------

    def test_a_stale_gen_aborts_before_publishing_anything(self):
        cap = self._cap()
        mine = cap._claim_gen(self.zone)
        cap._claim_gen(self.zone)                       # a newer turn arrives
        ha = FakeHA(playing(0.36))
        r = capability.run(cap, FakeCtx(ha),
                           {"mode": "say", "uri": self.tts, "gen": mine}, "rid-st")
        self.assertTrue(r["ok"])
        self.assertTrue(r["metadata"]["superseded"])
        self.assertEqual(ha.calls, [])                  # no volume_set, no play_media
        self.assertNotIn(self.zone, cap._replies)       # the marker was never published

    def test_a_stale_gen_does_not_overwrite_a_newer_turns_marker(self):
        cap = self._cap()
        mine = cap._claim_gen(self.zone)
        newer = cap._claim_gen(self.zone)
        cap._replies[self.zone] = {"gen": newer, "baseline": 0.42, "ts": 1000.0, "rid": "newer"}
        ha = FakeHA(playing(0.36))
        capability.run(cap, FakeCtx(ha),
                       {"mode": "say", "uri": self.tts, "gen": mine}, "rid-st2")
        self.assertEqual(cap._replies[self.zone]["gen"], newer)
        self.assertEqual(cap._replies[self.zone]["baseline"], 0.42)
        self.assertEqual(cap._replies[self.zone]["rid"], "newer")

    def test_a_stale_gen_does_not_disturb_the_newer_turns_snapshot(self):
        # The other half of the ratchet: retiring someone else's duck snapshot strips the baseline
        # and its dead-man, so nothing is left to put the zone back.
        cap = self._cap()
        mine = cap._claim_gen(self.zone)
        cap._claim_gen(self.zone)
        snap = {"volume": 0.55, "target": 0.15, "ts": 999.0, "timer": None}
        cap._snaps[self.zone] = snap
        ha = FakeHA(playing(0.36))
        capability.run(cap, FakeCtx(ha),
                       {"mode": "say", "uri": self.tts, "gen": mine}, "rid-st3")
        self.assertIs(cap._snaps[self.zone], snap)
        self.assertEqual(cap._snaps[self.zone]["target"], 0.15)

    def test_a_stale_gen_does_not_end_the_newer_turn(self):
        cap = self._cap()
        mine = cap._claim_gen(self.zone)
        cap._claim_gen(self.zone)
        turn = {"ts": 1000.0, "playback": None, "stopped": False}
        cap._turns[self.zone] = turn
        ha = FakeHA(playing(0.36))
        capability.run(cap, FakeCtx(ha),
                       {"mode": "say", "uri": self.tts, "gen": mine}, "rid-st4")
        self.assertIs(cap._turns.get(self.zone), turn)

    def test_a_stale_gen_does_not_move_the_generation_counter(self):
        cap = self._cap()
        mine = cap._claim_gen(self.zone)
        newer = cap._claim_gen(self.zone)
        ha = FakeHA(playing(0.36))
        capability.run(cap, FakeCtx(ha),
                       {"mode": "say", "uri": self.tts, "gen": mine}, "rid-st5")
        self.assertEqual(cap._say_gen[self.zone], newer)

    def test_the_abort_is_logged_with_both_generations(self):
        cap = self._cap()
        mine = cap._claim_gen(self.zone)
        cap._claim_gen(self.zone)
        ha = FakeHA(playing(0.36))
        with self.assertLogs("resolver", level="INFO") as cm:
            capability.run(cap, FakeCtx(ha),
                           {"mode": "say", "uri": self.tts, "gen": mine}, "rid-st6")
        self.assertTrue(any("stale" in m for m in cm.output), cm.output)

    def test_a_gen_that_was_never_claimed_is_treated_as_stale(self):
        cap = self._cap()
        ha = FakeHA(playing(0.36))
        r = capability.run(cap, FakeCtx(ha),
                           {"mode": "say", "uri": self.tts, "gen": 7}, "rid-ghost")
        self.assertTrue(r["metadata"]["superseded"])
        self.assertEqual(ha.calls, [])

    def test_a_supplied_gen_of_zero_is_checked_not_ignored(self):
        # `is None`, never a truthiness test: `if supplied_gen:` would silently fall through to
        # "claim my own" for 0, so a bogus claim would play a full announcement instead of aborting.
        cap = self._cap()
        cap._claim_gen(self.zone)
        ha = FakeHA(playing(0.36))
        r = capability.run(cap, FakeCtx(ha),
                           {"mode": "say", "uri": self.tts, "gen": 0}, "rid-zero")
        self.assertTrue(r["metadata"]["superseded"])
        self.assertEqual(ha.calls, [])

    # ---- a current claim ----------------------------------------------------

    def test_a_current_gen_is_adopted_and_publishes_normally(self):
        cap = self._cap()
        mine = cap._claim_gen(self.zone)
        ha = FakeHA(playing(0.36))
        ha.set_states(self._happy_states())
        r = capability.run(cap, FakeCtx(ha),
                           {"mode": "say", "uri": self.tts, "gen": mine}, "rid-ok")
        self.assertTrue(r["ok"])
        self.assertFalse(r["metadata"]["superseded"])
        self.assertIn("play_media", [c[1] for c in ha.calls])

    def test_adopting_a_current_gen_does_not_bump_the_counter_again(self):
        # Adoption must reuse the claim, not claim again. A second bump would leave the caller's own
        # superseded() comparing against a generation it does not hold, so every later check would
        # read as "superseded" and the turn would abort mid-sequence.
        cap = self._cap()
        mine = cap._claim_gen(self.zone)
        ha = FakeHA(playing(0.36))
        ha.set_states(self._happy_states())
        capability.run(cap, FakeCtx(ha),
                       {"mode": "say", "uri": self.tts, "gen": mine}, "rid-nobump")
        self.assertEqual(cap._say_gen[self.zone], mine)

    def test_an_adopted_turn_releases_ownership_on_the_way_out(self):
        cap = self._cap()
        mine = cap._claim_gen(self.zone)
        ha = FakeHA(playing(0.36))
        ha.set_states(self._happy_states())
        capability.run(cap, FakeCtx(ha),
                       {"mode": "say", "uri": self.tts, "gen": mine}, "rid-rel")
        self.assertNotIn(self.zone, cap._replies)

    # ---- the no-generation path stays exactly as it was ---------------------

    def test_no_supplied_gen_bumps_its_own_exactly_as_today(self):
        cap = self._cap()
        ha = FakeHA(playing(0.36))
        ha.set_states(self._happy_states())
        capability.run(cap, FakeCtx(ha), {"mode": "say", "uri": self.tts}, "rid-own")
        self.assertEqual(cap._say_gen[self.zone], 1)

    def test_no_supplied_gen_still_supersedes_an_earlier_claim(self):
        # An ordinary reply must keep winning over an in-flight one; adoption must not have turned
        # the bump into a no-op.
        cap = self._cap()
        cap._claim_gen(self.zone)
        ha = FakeHA(playing(0.36))
        ha.set_states(self._happy_states())
        capability.run(cap, FakeCtx(ha), {"mode": "say", "uri": self.tts}, "rid-own2")
        self.assertEqual(cap._say_gen[self.zone], 2)

    def test_say_text_without_a_gen_is_unaffected(self):
        cap = self._cap()
        ha = FakeHA(playing(0.36))
        ha.tts_url = self.tts
        ha.set_states(self._happy_states())
        r = capability.run(cap, FakeCtx(ha), {"mode": "say_text", "text": "dinner is ready"},
                           "rid-txt")
        self.assertTrue(r["ok"])
        self.assertEqual(cap._say_gen[self.zone], 1)



class MicLeaseTest(unittest.TestCase):
    """AN-01 Task 14: design 9.1-9.5.

    A successful switch.turn_on is an accepted REQUEST, not a muted microphone: HA may accept it for
    a device that never receives it (this satellite drops its ESPHome API with Errno 113). AN-2 also
    measured HA answering the write in about 1ms while the state took ~255ms to report back. So the
    state is read back before any audio plays, and announce_require_mic_mute means what it says.
    """

    ENT = "switch.respeaker_test_microphone_mute"

    def setUp(self):
        FakeTimer.created = []
        self.zone = "media_player.ceiling_speakers"

    def _cap(self):
        return interaction.InteractionCapability(timer_factory=FakeTimer, clock=lambda: 1000.0,
                                                 sleeper=FakeSleeper())

    def _ctx(self, ha):
        ctx = FakeCtx(ha)
        ctx.settings = FakeSettings()               # per-test instance, so edits cannot leak
        ctx.settings.announce_mic_mute_entity = self.ENT
        return ctx

    def _off(self):
        return {"state": "off", "attributes": {}}

    def _on(self):
        return {"state": "on", "attributes": {}}

    # ---- claim --------------------------------------------------------------

    def test_claim_reads_prev_then_writes_turn_on(self):
        cap = self._cap()
        ha = FakeHA(self._off())
        ctx = self._ctx(ha)
        lease, err = cap._mic_claim(ctx, self.zone, cap._claim_gen(self.zone), "rid-m")
        self.assertIsNone(err)
        self.assertFalse(lease["prev"])
        self.assertEqual([(d, sv) for d, sv, _ in ha.calls], [("switch", "turn_on")])
        self.assertEqual(ha.calls[0][2]["entity_id"], self.ENT)

    def test_prev_true_is_recorded_when_the_operator_already_muted(self):
        cap = self._cap()
        ha = FakeHA(self._on())
        lease, err = cap._mic_claim(self._ctx(ha), self.zone, cap._claim_gen(self.zone), "rid-m")
        self.assertIsNone(err)
        self.assertTrue(lease["prev"])

    def test_the_lease_is_published_under_the_zone(self):
        cap = self._cap()
        ha = FakeHA(self._off())
        gen = cap._claim_gen(self.zone)
        cap._mic_claim(self._ctx(ha), self.zone, gen, "rid-m")
        self.assertEqual(cap._mic[self.zone]["gen"], gen)
        self.assertEqual(cap._mic[self.zone]["rid"], "rid-m")
        self.assertFalse(cap._mic[self.zone]["confirmed"])

    def test_a_second_announcement_inherits_prev_and_does_not_read_the_switch(self):
        # Without inheritance the second reads the live switch -- which the first set to `on` --
        # concludes muted was the operator's preference, and leaves the satellite deaf forever.
        cap = self._cap()
        ha = FakeHA(self._off())
        ctx = self._ctx(ha)
        cap._mic_claim(ctx, self.zone, cap._claim_gen(self.zone), "rid-a")
        ha._state = self._on()
        reads = []
        real = ha.get_entity_state
        ha.get_entity_state = lambda e, timeout=10: (reads.append(e), real(e))[1]
        lease2, err = cap._mic_claim(ctx, self.zone, cap._claim_gen(self.zone), "rid-b")
        self.assertIsNone(err)
        self.assertFalse(lease2["prev"])              # inherited from rid-a, not re-read
        self.assertEqual(reads, [])

    def test_an_inherited_prev_of_false_still_counts_as_inherited(self):
        # `is None`, not truthiness: prev=False is a real inherited value. A truthiness check would
        # re-read the switch -- which is exactly the bug inheritance exists to prevent.
        cap = self._cap()
        ha = FakeHA(self._off())
        ctx = self._ctx(ha)
        cap._mic_claim(ctx, self.zone, cap._claim_gen(self.zone), "rid-a")
        ha._state = self._on()
        lease2, _ = cap._mic_claim(ctx, self.zone, cap._claim_gen(self.zone), "rid-b")
        self.assertFalse(lease2["prev"])

    def test_an_unresolved_entity_refuses(self):
        cap = self._cap()
        ha = FakeHA(self._off())
        ctx = self._ctx(ha)
        ctx.settings.announce_mic_mute_entity = ""
        lease, err = cap._mic_claim(ctx, self.zone, cap._claim_gen(self.zone), "rid-m")
        self.assertIsNone(lease)
        self.assertEqual(err["code"], "unavailable")
        self.assertEqual(ha.calls, [])

    def test_an_unresolved_entity_with_require_false_proceeds_without_a_lease(self):
        cap = self._cap()
        ha = FakeHA(self._off())
        ctx = self._ctx(ha)
        ctx.settings.announce_mic_mute_entity = ""
        ctx.settings.announce_require_mic_mute = False
        lease, err = cap._mic_claim(ctx, self.zone, cap._claim_gen(self.zone), "rid-m")
        self.assertIsNone(lease)
        self.assertIsNone(err)
        self.assertNotIn(self.zone, cap._mic)

    def test_a_read_failure_refuses(self):
        cap = self._cap()
        ha = FakeHA(boom=IOError("HA down"))
        lease, err = cap._mic_claim(self._ctx(ha), self.zone, cap._claim_gen(self.zone), "rid-m")
        self.assertIsNone(lease)
        self.assertEqual(err["code"], "unavailable")

    def test_a_write_failure_refuses(self):
        cap = self._cap()
        ha = FakeHA(self._off(), write_boom=IOError("no route"))
        lease, err = cap._mic_claim(self._ctx(ha), self.zone, cap._claim_gen(self.zone), "rid-m")
        self.assertIsNone(lease)
        self.assertEqual(err["code"], "unavailable")

    def test_a_write_failure_leaves_no_lease_behind(self):
        # Nothing was muted, so a lingering lease would make the NEXT announcement inherit a prev it
        # never observed, and would give the dead-man a phantom to unmute.
        cap = self._cap()
        ha = FakeHA(self._off(), write_boom=IOError("no route"))
        cap._mic_claim(self._ctx(ha), self.zone, cap._claim_gen(self.zone), "rid-m")
        self.assertNotIn(self.zone, cap._mic)

    def test_every_refusal_uses_a_valid_error_code(self):
        import command_result as cr_mod
        cap = self._cap()
        for ha, tweak in ((FakeHA(boom=IOError("x")), None),
                          (FakeHA(self._off(), write_boom=IOError("x")), None),
                          (FakeHA(self._off()), "blank")):
            ctx = self._ctx(ha)
            if tweak == "blank":
                ctx.settings.announce_mic_mute_entity = ""
            _, err = cap._mic_claim(ctx, self.zone, cap._claim_gen(self.zone), "rid-m")
            self.assertIn(err["code"], cr_mod.ERROR_CODES)
            self.assertTrue(err["reason"])
            err["chat_text"].encode("ascii")          # console cannot print non-ASCII

    # ---- confirm ------------------------------------------------------------

    def test_confirmation_polls_until_on_then_proceeds(self):
        cap = self._cap()
        ha = FakeHA(self._off())
        ctx = self._ctx(ha)
        gen = cap._claim_gen(self.zone)
        cap._mic_claim(ctx, self.zone, gen, "rid-m")
        ha.set_states([self._off(), self._off(), self._on()])
        ok, err = cap._mic_confirm(ctx, self.zone, gen, "rid-m")
        self.assertTrue(ok)
        self.assertIsNone(err)
        self.assertTrue(cap._mic[self.zone]["confirmed"])

    def test_confirm_timeout_refuses_and_is_bounded(self):
        cap = self._cap()
        ha = FakeHA(self._off())
        ctx = self._ctx(ha)
        gen = cap._claim_gen(self.zone)
        cap._mic_claim(ctx, self.zone, gen, "rid-m")
        ok, err = cap._mic_confirm(ctx, self.zone, gen, "rid-m")
        self.assertFalse(ok)
        self.assertEqual(err["code"], "unavailable")

    def test_confirm_terminates_even_if_the_clock_never_advances(self):
        # This is not merely a test convenience. time.time is NOT monotonic: an NTP step backwards
        # mid-confirm keeps `deadline - now` large, and a purely wall-clock loop would keep polling.
        # The poll count derived from budget/step is the belt to that braces.
        cap = self._cap()
        ha = FakeHA(self._off())
        ctx = self._ctx(ha)
        gen = cap._claim_gen(self.zone)
        cap._mic_claim(ctx, self.zone, gen, "rid-m")
        before = len(ha.state_timeouts)
        ok, err = cap._mic_confirm(ctx, self.zone, gen, "rid-m")
        self.assertFalse(ok)
        polls = len(ha.state_timeouts) - before
        self.assertGreater(polls, 1)                  # it really did poll
        self.assertLessEqual(polls, 9)                # 2000ms / 250ms, plus one

    def test_a_raising_confirm_read_refuses_rather_than_propagating(self):
        cap = self._cap()
        ha = FakeHA(self._off())
        ctx = self._ctx(ha)
        gen = cap._claim_gen(self.zone)
        cap._mic_claim(ctx, self.zone, gen, "rid-m")
        ha._boom = IOError("read blip")
        ok, err = cap._mic_confirm(ctx, self.zone, gen, "rid-m")   # must not raise
        self.assertFalse(ok)
        self.assertEqual(err["code"], "unavailable")

    def test_require_false_proceeds_unconfirmed(self):
        cap = self._cap()
        ha = FakeHA(self._off())
        ctx = self._ctx(ha)
        ctx.settings.announce_require_mic_mute = False
        gen = cap._claim_gen(self.zone)
        cap._mic_claim(ctx, self.zone, gen, "rid-m")
        ok, err = cap._mic_confirm(ctx, self.zone, gen, "rid-m")
        self.assertFalse(ok)
        self.assertIsNone(err)                        # no refusal: broadcast anyway
        self.assertFalse(cap._mic[self.zone]["confirmed"])

    def test_confirm_does_not_mark_a_lease_that_is_no_longer_ours(self):
        cap = self._cap()
        ha = FakeHA(self._off())
        ctx = self._ctx(ha)
        first = cap._claim_gen(self.zone)
        cap._mic_claim(ctx, self.zone, first, "rid-a")
        second = cap._claim_gen(self.zone)
        cap._mic_claim(ctx, self.zone, second, "rid-b")
        ha.set_states([self._on()])
        ok, _ = cap._mic_confirm(ctx, self.zone, first, "rid-a")
        self.assertTrue(ok)                           # the switch IS on
        self.assertFalse(cap._mic[self.zone]["confirmed"])   # but rid-b's lease is untouched

    # ---- release ------------------------------------------------------------

    def test_release_restores_prev_and_clears_the_lease(self):
        cap = self._cap()
        ha = FakeHA(self._off())
        ctx = self._ctx(ha)
        gen = cap._claim_gen(self.zone)
        cap._mic_claim(ctx, self.zone, gen, "rid-m")
        self.assertTrue(cap._mic_release(ctx, self.zone, gen, "rid-m"))
        self.assertEqual([(d, sv) for d, sv, _ in ha.calls],
                         [("switch", "turn_on"), ("switch", "turn_off")])
        self.assertNotIn(self.zone, cap._mic)

    def test_release_leaves_an_already_muted_switch_on(self):
        cap = self._cap()
        ha = FakeHA(self._on())
        ctx = self._ctx(ha)
        gen = cap._claim_gen(self.zone)
        cap._mic_claim(ctx, self.zone, gen, "rid-m")
        cap._mic_release(ctx, self.zone, gen, "rid-m")
        self.assertNotIn("turn_off", [sv for _, sv, _ in ha.calls])
        self.assertNotIn(self.zone, cap._mic)

    def test_release_without_any_lease_is_a_no_op(self):
        cap = self._cap()
        ha = FakeHA(self._off())
        self.assertFalse(cap._mic_release(self._ctx(ha), self.zone, 1, "rid-none"))
        self.assertEqual(ha.calls, [])

    def test_release_is_a_no_op_when_a_newer_announcement_holds_the_lease(self):
        cap = self._cap()
        ha = FakeHA(self._off())
        ctx = self._ctx(ha)
        first = cap._claim_gen(self.zone)
        cap._mic_claim(ctx, self.zone, first, "rid-a")
        second = cap._claim_gen(self.zone)
        cap._mic_claim(ctx, self.zone, second, "rid-b")
        before = len(ha.calls)
        self.assertFalse(cap._mic_release(ctx, self.zone, first, "rid-a"))
        self.assertEqual(len(ha.calls), before)
        self.assertEqual(cap._mic[self.zone]["gen"], second)

    def test_the_second_release_restores_the_original_prev(self):
        cap = self._cap()
        ha = FakeHA(self._off())
        ctx = self._ctx(ha)
        first = cap._claim_gen(self.zone)
        cap._mic_claim(ctx, self.zone, first, "rid-a")
        second = cap._claim_gen(self.zone)
        cap._mic_claim(ctx, self.zone, second, "rid-b")
        cap._mic_release(ctx, self.zone, second, "rid-b")
        self.assertIn("turn_off", [sv for _, sv, _ in ha.calls])
        self.assertNotIn(self.zone, cap._mic)

    def test_a_write_failure_on_release_keeps_the_lease_for_the_dead_man(self):
        cap = self._cap()
        ha = FakeHA(self._off())
        ctx = self._ctx(ha)
        gen = cap._claim_gen(self.zone)
        cap._mic_claim(ctx, self.zone, gen, "rid-m")
        ha._write_boom = IOError("no route")
        self.assertFalse(cap._mic_release(ctx, self.zone, gen, "rid-m"))
        self.assertIn(self.zone, cap._mic)

    # ---- the ownership rule that makes supersession safe --------------------

    def test_a_zone_supersession_that_is_not_an_announcement_leaves_the_lease_ours(self):
        # design 9.4/9.6. The release check is on _mic, NOT on _say_gen. A satellite reply or a
        # say_text turn bumps _say_gen but never writes _mic, so the lease is still ours and we
        # unmute IMMEDIATELY -- which is what is wanted, because the superseding turn is a person
        # talking to the satellite and they need the microphone back now.
        cap = self._cap()
        ha = FakeHA(self._off())
        ctx = self._ctx(ha)
        gen = cap._claim_gen(self.zone)
        cap._mic_claim(ctx, self.zone, gen, "rid-m")
        cap._claim_gen(self.zone)                     # a satellite reply supersedes the zone
        self.assertTrue(cap._mic_release(ctx, self.zone, gen, "rid-m"))
        self.assertIn("turn_off", [sv for _, sv, _ in ha.calls])
        self.assertNotIn(self.zone, cap._mic)

    def test_no_other_mode_ever_writes_the_mic_lease(self):
        # The single invariant the whole scheme rests on: _mic is written only by the announcement
        # path. If any ordinary turn started touching it, a non-announcement supersession would
        # strand the mute instead of releasing it.
        tts = "http://192.168.122.10:8123/api/tts_proxy/x.mp3"
        for params in ({"mode": "duck"}, {"mode": "restore"}, {"mode": "resume"},
                       {"mode": "pause"}, {"mode": "volume_up"}, {"mode": "volume_down"},
                       {"mode": "set_volume", "volume": 0.3},
                       {"mode": "say", "uri": tts},
                       {"mode": "say_text", "text": "hello"}):
            cap = self._cap()
            ha = FakeHA(playing(0.36))
            ha.tts_url = tts
            ha.set_states([playing_with_id(0.36, "library://radio/2"),
                           playing_with_id(0.40, "builtin://radio/" + tts),
                           idle_state(), idle_state(), playing(0.40)])
            capability.run(cap, self._ctx(ha), params, "rid-inv")
            self.assertEqual(cap._mic, {}, params["mode"])


class MicDeadManTest(unittest.TestCase):
    """AN-01 Task 14: design 9.5. A stuck-muted microphone is a DEAF satellite -- a silent,
    open-ended failure nobody finds until they try to talk to it.

    The duration is a POLICY CUTOFF derived from an engineered budget, not a wall-clock bound: a
    pathologically slow-but-live turn could cross it. Firing early costs a few seconds of self-wake
    exposure; never firing leaves the satellite deaf with nothing scheduled to fix it, so the
    trade-off favours liveness.
    """

    ENT = "switch.respeaker_test_microphone_mute"

    def setUp(self):
        FakeTimer.created = []
        self.zone = "media_player.ceiling_speakers"

    def _cap(self):
        return interaction.InteractionCapability(timer_factory=FakeTimer, clock=lambda: 1000.0,
                                                 sleeper=FakeSleeper())

    def _ctx(self, ha):
        ctx = FakeCtx(ha)
        ctx.settings = FakeSettings()
        ctx.settings.announce_mic_mute_entity = self.ENT
        return ctx

    def _off(self):
        return {"state": "off", "attributes": {}}

    def test_claim_arms_a_timer(self):
        cap = self._cap()
        ha = FakeHA(self._off())
        cap._mic_claim(self._ctx(ha), self.zone, cap._claim_gen(self.zone), "rid-m")
        self.assertEqual(len(FakeTimer.created), 1)
        self.assertTrue(FakeTimer.created[0].started)

    def test_derived_mic_deadman_is_about_185s_with_shipped_defaults(self):
        cap = self._cap()
        ha = FakeHA(self._off())
        cap._mic_claim(self._ctx(ha), self.zone, cap._claim_gen(self.zone), "rid-m")
        self.assertAlmostEqual(FakeTimer.created[0].interval, 182.0, delta=6.0)

    def test_a_single_clip_announcement_gets_a_shorter_budget(self):
        cap = self._cap()
        ha = FakeHA(self._off())
        cap._mic_claim(self._ctx(ha), self.zone, cap._claim_gen(self.zone), "rid-m", clips=1)
        two = interaction.InteractionCapability(timer_factory=FakeTimer, clock=lambda: 1000.0,
                                                sleeper=FakeSleeper())
        ha2 = FakeHA(self._off())
        two._mic_claim(self._ctx(ha2), self.zone, two._claim_gen(self.zone), "rid-n", clips=2)
        self.assertLess(FakeTimer.created[0].interval, FakeTimer.created[1].interval)

    def test_an_explicit_deadman_ms_overrides_the_derivation(self):
        cap = self._cap()
        ha = FakeHA(self._off())
        ctx = self._ctx(ha)
        ctx.settings.announce_mic_deadman_ms = 30000
        cap._mic_claim(ctx, self.zone, cap._claim_gen(self.zone), "rid-m")
        self.assertEqual(FakeTimer.created[0].interval, 30.0)

    def test_release_cancels_it(self):
        cap = self._cap()
        ha = FakeHA(self._off())
        ctx = self._ctx(ha)
        gen = cap._claim_gen(self.zone)
        cap._mic_claim(ctx, self.zone, gen, "rid-m")
        cap._mic_release(ctx, self.zone, gen, "rid-m")
        self.assertTrue(FakeTimer.created[0].cancelled)

    def test_a_release_that_leaves_it_muted_also_cancels_it(self):
        cap = self._cap()
        ha = FakeHA({"state": "on", "attributes": {}})
        ctx = self._ctx(ha)
        gen = cap._claim_gen(self.zone)
        cap._mic_claim(ctx, self.zone, gen, "rid-m")
        cap._mic_release(ctx, self.zone, gen, "rid-m")
        self.assertTrue(FakeTimer.created[0].cancelled)

    def test_a_failed_unmute_does_NOT_cancel_the_dead_man(self):
        # Otherwise the log's promise that "the dead-man must reconcile" is a lie: the lease stays,
        # the microphone stays muted, and nothing is scheduled to ever fix it.
        cap = self._cap()
        ha = FakeHA(self._off())
        ctx = self._ctx(ha)
        gen = cap._claim_gen(self.zone)
        cap._mic_claim(ctx, self.zone, gen, "rid-m")
        ha._write_boom = IOError("no route")
        cap._mic_release(ctx, self.zone, gen, "rid-m")
        self.assertFalse(FakeTimer.created[0].cancelled)
        self.assertIn(self.zone, cap._mic)

    def test_firing_restores_prev(self):
        cap = self._cap()
        ha = FakeHA(self._off())
        ctx = self._ctx(ha)
        cap._mic_claim(ctx, self.zone, cap._claim_gen(self.zone), "rid-m")
        FakeTimer.created[0].fire()
        self.assertIn("turn_off", [sv for _, sv, _ in ha.calls])
        self.assertNotIn(self.zone, cap._mic)

    def test_firing_does_nothing_once_a_newer_announcement_owns_the_lease(self):
        cap = self._cap()
        ha = FakeHA(self._off())
        ctx = self._ctx(ha)
        cap._mic_claim(ctx, self.zone, cap._claim_gen(self.zone), "rid-a")
        stale = FakeTimer.created[0]
        cap._mic_claim(ctx, self.zone, cap._claim_gen(self.zone), "rid-b")
        before = len([sv for _, sv, _ in ha.calls if sv == "turn_off"])
        stale.fire()
        self.assertEqual(len([sv for _, sv, _ in ha.calls if sv == "turn_off"]), before)
        self.assertIn(self.zone, cap._mic)

    def test_a_raising_release_does_not_escape_the_timer_thread(self):
        # The dead-man runs on the timer thread; an exception there is unhandled and kills nothing
        # useful while the microphone stays muted.
        cap = self._cap()
        ha = FakeHA(self._off())
        ctx = self._ctx(ha)
        cap._mic_claim(ctx, self.zone, cap._claim_gen(self.zone), "rid-m")

        def boom(*a, **k):
            raise RuntimeError("kaboom")
        cap._mic_release = boom
        FakeTimer.created[0].fire()                   # must not raise



class AnnounceEndToEndTest(unittest.TestCase):
    """AN-01 Task 15: design 5, 7, 8.5, 10.

    Ordering (design 7) puts every cheap failure before anything is touched: A validate, B render
    and bound, C resolve TTS, D resolve chime, E claim generation, F lease and mute, G confirm by
    reading, H one reply-owned turn, I map the outcome, finally release. C before F is deliberate --
    a TTS failure is the likeliest failure here, and paying for it with a muted microphone and a
    raised volume would be gratuitous.

    Clocks advance here. _play_clip_and_wait's deadline-driven poll has no accumulated-sleep
    fallback, so a frozen clock never satisfies its exit condition; driving the clock from the
    sleeper is both realistic and terminating.
    """

    ENT = "switch.respeaker_test_microphone_mute"

    def setUp(self):
        FakeTimer.created = []
        self.zone = "media_player.ceiling_speakers"
        # A signed media URL is a bearer credential; the fixture is an obvious placeholder.
        self.chime_signed = ("http://192.168.122.10:8123/media/local/timer_chime.wav?authSig="
                             + FAKE_SIG)
        self.tts = "http://192.168.122.10:8123/api/tts_proxy/x.mp3"

    def _cap(self):
        clock = MovingClock()
        return interaction.InteractionCapability(timer_factory=FakeTimer, clock=clock,
                                                 sleeper=AdvancingSleeper(clock))

    def _ha(self):
        ha = FakeHA(playing(0.36))
        ha.tts_url = self.tts
        ha.media_url = self.chime_signed
        return ha

    def _ctx(self, ha):
        ctx = FakeCtx(ha)
        ctx.settings = FakeSettings()
        ctx.settings.announce_mic_mute_entity = self.ENT
        return ctx

    def _states(self):
        return [{"state": "off", "attributes": {}},                            # mic prev
                {"state": "on", "attributes": {}},                             # mic confirm
                playing_with_id(0.36, "library://radio/2"),                    # capture
                playing_with_id(0.80, "builtin://track/" + self.chime_signed), # chime start
                idle_state(), idle_state(),                                    # chime end
                playing_with_id(0.80, "builtin://radio/" + self.tts),          # tts start
                idle_state(), idle_state(),                                    # tts end
                playing(0.80)]                                                 # restore read

    def _no_chime_states(self):
        return [{"state": "off", "attributes": {}},
                {"state": "on", "attributes": {}},
                playing_with_id(0.36, "library://radio/2"),
                playing_with_id(0.80, "builtin://radio/" + self.tts),
                idle_state(), idle_state(), playing(0.80)]

    # ---- the golden order ---------------------------------------------------

    def test_golden_announce_call_order(self):
        cap = self._cap()
        ha = self._ha()
        ha.set_states(self._states())
        r = run(cap, self._ctx(ha), {"mode": "announce", "text": "dinner is ready"})
        self.assertTrue(r["ok"], r)
        self.assertEqual([(d, sv) for d, sv, _ in ha.calls],
                         [("switch", "turn_on"),
                          ("media_player", "media_pause"),
                          ("media_player", "volume_set"),
                          ("music_assistant", "play_media"),
                          ("music_assistant", "play_media"),
                          ("media_player", "volume_set"),
                          ("music_assistant", "play_media"),
                          ("switch", "turn_off")])
        self.assertEqual(ha.calls[2][2]["volume_level"], 0.80)
        self.assertEqual(ha.calls[5][2]["volume_level"], 0.36)
        self.assertEqual(ha.calls[3][2]["media_id"], self.chime_signed)
        self.assertEqual(ha.calls[4][2]["media_id"], self.tts)
        self.assertEqual(ha.calls[6][2]["media_id"], "library://radio/2")

    def test_the_mic_is_muted_before_the_first_audio_call(self):
        cap = self._cap()
        ha = self._ha()
        ha.set_states(self._states())
        run(cap, self._ctx(ha), {"mode": "announce", "text": "dinner is ready"})
        svcs = [sv for _, sv, _ in ha.calls]
        self.assertLess(svcs.index("turn_on"), svcs.index("play_media"))
        self.assertLess(svcs.index("turn_on"), svcs.index("volume_set"))

    def test_both_urls_are_resolved_before_the_microphone_is_touched(self):
        # design 7's whole point: the cheap failures come first.
        cap = self._cap()
        ha = self._ha()
        ha.set_states(self._states())
        order = []
        real_tts = ha.tts_get_url
        real_res = ha.resolve_media_source
        real_call = ha.call_service_rest
        ha.tts_get_url = lambda e, m, timeout=10: (order.append("tts"), real_tts(e, m))[1]
        ha.resolve_media_source = lambda u, timeout=10: (order.append("chime"), real_res(u))[1]

        def call(domain, service, data, timeout=5):
            order.append(domain + "." + service)
            return real_call(domain, service, data, timeout=timeout)
        ha.call_service_rest = call
        run(cap, self._ctx(ha), {"mode": "announce", "text": "dinner is ready"})
        self.assertLess(order.index("tts"), order.index("switch.turn_on"))
        self.assertLess(order.index("chime"), order.index("switch.turn_on"))
        self.assertLess(order.index("tts"), order.index("chime"))

    def test_success_chat_text_is_announced_not_said(self):
        cap = self._cap()
        ha = self._ha()
        ha.set_states(self._states())
        r = run(cap, self._ctx(ha), {"mode": "announce", "text": "dinner is ready"})
        self.assertEqual(r["chat_text"], "Announced.")
        self.assertIsNone(r["spoken_text"])
        self.assertTrue(r["metadata"]["announced"])

    def test_the_rendered_text_handed_to_tts_is_the_bounded_one(self):
        cap = self._cap()
        ha = self._ha()
        ha.set_states(self._states())
        ctx = self._ctx(ha)
        ctx.settings.announce_prefix = "Announcement."
        run(cap, ctx, {"mode": "announce", "text": "dinner is ready"})
        self.assertEqual(ha.tts_calls, [("tts.piper", "Announcement. dinner is ready")])

    def test_an_over_long_message_is_rejected_before_anything_is_touched(self):
        cap = self._cap()
        ha = self._ha()
        r = run(cap, self._ctx(ha), {"mode": "announce", "text": "x" * 400})
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"]["code"], "invalid_input")
        self.assertEqual(ha.calls, [])
        self.assertEqual(ha.tts_calls, [])

    def test_a_dropped_prefix_is_reported_in_the_metadata(self):
        cap = self._cap()
        ha = self._ha()
        ha.set_states(self._states())
        ctx = self._ctx(ha)
        ctx.settings.announce_prefix = "P" * 100
        r = run(cap, ctx, {"mode": "announce", "text": "dinner is ready"})
        self.assertTrue(r["metadata"]["prefix_dropped"])
        self.assertEqual(ha.tts_calls, [("tts.piper", "dinner is ready")])

    # ---- the chime degrades, it does not fail -------------------------------

    def test_the_chime_match_key_is_the_full_signed_uri(self):
        # post-G1 correction 1: AN-1 measured the query as PRESERVED in MA's echo, so there is no
        # path-only special case. The chime here is matched through the track wrapper WITH its query.
        cap = self._cap()
        ha = self._ha()
        ha.set_states(self._states())
        r = run(cap, self._ctx(ha), {"mode": "announce", "text": "dinner is ready"})
        self.assertTrue(r["metadata"]["chime"]["played"])
        self.assertTrue(r["metadata"]["clips"][0]["started"])

    def test_a_stale_signature_on_the_same_chime_path_is_NOT_a_match(self):
        # The discriminating case for correction 1, and the reason a path-only key is wrong rather
        # than merely redundant. Matching is by CONTAINMENT, so a path-only key matches the full
        # echoed cid too -- asserting only that "the chime started" cannot tell the two contracts
        # apart.
        #
        # Here the player is still echoing the SAME chime file from an earlier turn, under that
        # turn's now-expired signature. A path-only key matches it and the announcement would report
        # a chime that never played this turn. The full URI does not match, so the chime is honestly
        # reported as never started.
        stale = ("http://192.168.122.10:8123/media/local/timer_chime.wav?authSig=STALE-EXPIRED-SIG")
        cap = self._cap()
        ha = self._ha()
        ha.set_states([{"state": "off", "attributes": {}},
                       {"state": "on", "attributes": {}},
                       playing_with_id(0.36, "library://radio/2")]
                      + [playing_with_id(0.80, "builtin://track/" + stale)] * 10
                      + [playing_with_id(0.80, "builtin://radio/" + self.tts),
                         idle_state(), idle_state(), playing(0.80)])
        r = run(cap, self._ctx(ha), {"mode": "announce", "text": "dinner is ready"})
        self.assertTrue(r["ok"], r)
        self.assertFalse(r["metadata"]["chime"]["played"])
        self.assertEqual(r["metadata"]["chime"]["reason"], "never_started")

    def test_a_chime_resolve_failure_degrades_and_still_speaks(self):
        cap = self._cap()
        ha = self._ha()

        def boom(uri, timeout=10):
            raise IOError("resolve failed")
        ha.resolve_media_source = boom
        ha.set_states(self._no_chime_states())
        r = run(cap, self._ctx(ha), {"mode": "announce", "text": "dinner is ready"})
        self.assertTrue(r["ok"], r)
        self.assertFalse(r["metadata"]["chime"]["played"])
        self.assertEqual(r["metadata"]["chime"]["reason"], "resolve_failed")
        self.assertEqual(len([c for c in ha.calls if c[1] == "play_media"]), 2)   # tts + replay

    def test_an_empty_chime_uri_is_a_configured_skip(self):
        cap = self._cap()
        ha = self._ha()
        ctx = self._ctx(ha)
        ctx.settings.announce_chime_uri = ""
        ha.set_states(self._no_chime_states())
        r = run(cap, ctx, {"mode": "announce", "text": "dinner is ready"})
        self.assertTrue(r["ok"])
        self.assertEqual(r["metadata"]["chime"]["reason"], "disabled")
        self.assertEqual(ha.resolve_calls, [])

    def test_a_chime_that_resolves_but_never_starts_is_reported(self):
        cap = self._cap()
        ha = self._ha()
        # The chime's own start poll burns its budget, then the message plays normally.
        ha.set_states([{"state": "off", "attributes": {}},
                       {"state": "on", "attributes": {}},
                       playing_with_id(0.36, "library://radio/2")]
                      + [idle_state()] * 10
                      + [playing_with_id(0.80, "builtin://radio/" + self.tts),
                         idle_state(), idle_state(), playing(0.80)])
        r = run(cap, self._ctx(ha), {"mode": "announce", "text": "dinner is ready"})
        self.assertTrue(r["ok"], r)
        self.assertFalse(r["metadata"]["chime"]["played"])
        self.assertEqual(r["metadata"]["chime"]["reason"], "never_started")

    def test_the_chime_is_resolved_every_turn_and_never_cached(self):
        # The signature expires, so a cached URL is a silent failure two layers from its symptom.
        cap = self._cap()
        ha = self._ha()
        ctx = self._ctx(ha)
        for _ in range(2):
            ha.set_states(self._states())
            run(cap, ctx, {"mode": "announce", "text": "dinner is ready"})
        self.assertEqual(len(ha.resolve_calls), 2)

    # ---- honest failure mapping (design 8.5) --------------------------------

    def test_a_tts_failure_touches_nothing(self):
        cap = self._cap()
        ha = self._ha()
        ha.tts_boom = IOError("tts down")
        r = run(cap, self._ctx(ha), {"mode": "announce", "text": "dinner is ready"})
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"]["code"], "upstream_error")
        self.assertEqual(ha.calls, [])                 # no mute, no volume, no audio
        self.assertEqual(ha.resolve_calls, [])         # not even the chime

    def test_an_empty_tts_url_is_a_failure_not_a_silent_success(self):
        cap = self._cap()
        ha = self._ha()
        ha.tts_url = ""
        r = run(cap, self._ctx(ha), {"mode": "announce", "text": "dinner is ready"})
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"]["code"], "upstream_error")
        self.assertEqual(ha.calls, [])

    def test_a_silent_message_is_an_honest_failure_not_a_success(self):
        # say_text returns ok with likely_silent; for a broadcast that is "claimed success, did
        # nothing" -- the exact class this stack keeps producing (design 8.5).
        cap = self._cap()
        ha = self._ha()
        ha.set_states([{"state": "off", "attributes": {}},
                       {"state": "on", "attributes": {}},
                       playing_with_id(0.36, "library://radio/2")]
                      + [idle_state()] * 30 + [playing(0.80)])
        r = run(cap, self._ctx(ha), {"mode": "announce", "text": "dinner is ready"})
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"]["code"], "upstream_error")
        self.assertEqual(r["chat_text"], "I couldn't play the announcement.")

    def test_say_text_with_the_same_condition_still_returns_ok(self):
        # The divergence is intentional and pinned: a reply is confirmed by the action, a broadcast
        # is not.
        cap = self._cap()
        ha = FakeHA(playing(0.36))
        ha.tts_url = self.tts
        ha.set_states([playing_with_id(0.36, "library://radio/2")]
                      + [idle_state()] * 12 + [playing(0.40)])
        r = run(cap, FakeCtx(ha), {"mode": "say_text", "text": "hello"})
        self.assertTrue(r["ok"])
        self.assertTrue(r["metadata"]["likely_silent"])

    def test_every_failure_path_uses_a_valid_code_and_readable_text(self):
        import command_result as cr_mod
        cases = []

        def tts_down(ha, ctx):
            ha.tts_boom = IOError("x")

        def tts_empty(ha, ctx):
            ha.tts_url = ""

        def mic_missing(ha, ctx):
            ctx.settings.announce_mic_mute_entity = ""

        def too_long(ha, ctx):
            pass
        for setup, text in ((tts_down, "hi"), (tts_empty, "hi"), (mic_missing, "hi"),
                            (too_long, "z" * 400)):
            cap = self._cap()
            ha = self._ha()
            ctx = self._ctx(ha)
            setup(ha, ctx)
            r = run(cap, ctx, {"mode": "announce", "text": text})
            self.assertFalse(r["ok"], setup.__name__)
            self.assertIn(r["error"]["code"], cr_mod.ERROR_CODES, setup.__name__)
            self.assertTrue(r["chat_text"], setup.__name__)
            r["chat_text"].encode("ascii")             # the console cannot print non-ASCII
            self.assertNotIn("authSig", r["chat_text"])
            self.assertNotIn(FAKE_SIG, repr(r["metadata"]))

    def test_no_result_metadata_carries_the_signed_url(self):
        cap = self._cap()
        ha = self._ha()
        ha.set_states(self._states())
        r = run(cap, self._ctx(ha), {"mode": "announce", "text": "dinner is ready"})
        self.assertNotIn(FAKE_SIG, repr(r))

    def test_no_log_line_of_a_successful_announcement_carries_the_signature(self):
        cap = self._cap()
        ha = self._ha()
        ha.set_states(self._states())
        with self.assertLogs("resolver", level="INFO") as cm:
            run(cap, self._ctx(ha), {"mode": "announce", "text": "dinner is ready"})
        joined = "\n".join(cm.output)
        self.assertTrue(joined)
        self.assertNotIn(FAKE_SIG, joined)

    # ---- the microphone across every exit path ------------------------------

    def test_an_unconfirmed_mic_refuses_and_plays_nothing(self):
        cap = self._cap()
        ha = self._ha()
        ha.set_states([{"state": "off", "attributes": {}}] * 20)
        r = run(cap, self._ctx(ha), {"mode": "announce", "text": "dinner is ready"})
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"]["code"], "unavailable")
        self.assertNotIn("play_media", [sv for _, sv, _ in ha.calls])
        self.assertNotIn("volume_set", [sv for _, sv, _ in ha.calls])
        self.assertFalse(r["metadata"]["mic"]["confirmed"])

    def test_an_unconfirmed_mic_is_still_released(self):
        cap = self._cap()
        ha = self._ha()
        ha.set_states([{"state": "off", "attributes": {}}] * 20)
        run(cap, self._ctx(ha), {"mode": "announce", "text": "dinner is ready"})
        self.assertIn("turn_off", [sv for _, sv, _ in ha.calls])

    def test_an_unmutable_mic_refuses_before_any_audio(self):
        cap = self._cap()
        ha = self._ha()
        ctx = self._ctx(ha)
        ctx.settings.announce_mic_mute_entity = ""
        r = run(cap, ctx, {"mode": "announce", "text": "dinner is ready"})
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"]["code"], "unavailable")
        self.assertEqual(ha.calls, [])

    def test_the_mic_is_released_even_when_the_message_never_starts(self):
        cap = self._cap()
        ha = self._ha()
        ha.set_states([{"state": "off", "attributes": {}},
                       {"state": "on", "attributes": {}},
                       playing_with_id(0.36, "library://radio/2")]
                      + [idle_state()] * 30 + [playing(0.80)])
        r = run(cap, self._ctx(ha), {"mode": "announce", "text": "dinner is ready"})
        self.assertFalse(r["ok"])
        self.assertIn("turn_off", [sv for _, sv, _ in ha.calls])
        self.assertEqual(cap._mic, {})

    def test_the_mic_is_released_when_the_turn_raises(self):
        cap = self._cap()
        ha = self._ha()
        ha.set_states(self._states())
        ctx = self._ctx(ha)
        real = cap._say

        def boom(c, resolved, rid):
            raise RuntimeError("turn exploded")
        cap._say = boom
        self.assertRaises(RuntimeError, cap._announce, ctx, cap.resolve(ctx, {
            "mode": "announce", "text": "dinner is ready"}), "rid-x")
        self.assertIn("turn_off", [sv for _, sv, _ in ha.calls])
        self.assertEqual(cap._mic, {})
        cap._say = real

    def test_the_mic_lease_is_gone_after_a_successful_announcement(self):
        cap = self._cap()
        ha = self._ha()
        ha.set_states(self._states())
        run(cap, self._ctx(ha), {"mode": "announce", "text": "dinner is ready"})
        self.assertEqual(cap._mic, {})

    def test_an_operator_muted_mic_is_left_muted_afterwards(self):
        cap = self._cap()
        ha = self._ha()
        ha.set_states([{"state": "on", "attributes": {}}] + self._states()[1:])
        r = run(cap, self._ctx(ha), {"mode": "announce", "text": "dinner is ready"})
        self.assertTrue(r["ok"], r)
        self.assertNotIn("turn_off", [sv for _, sv, _ in ha.calls])
        self.assertEqual(cap._mic, {})

    def test_require_false_broadcasts_with_an_unconfirmed_mic(self):
        cap = self._cap()
        ha = self._ha()
        ctx = self._ctx(ha)
        ctx.settings.announce_require_mic_mute = False
        ha.set_states([{"state": "off", "attributes": {}}] * 10 + self._states()[2:])
        r = run(cap, ctx, {"mode": "announce", "text": "dinner is ready"})
        self.assertTrue(r["ok"], r)
        self.assertFalse(r["metadata"]["mic"]["confirmed"])
        self.assertTrue(r["metadata"]["mic"]["muted"])


class AnnounceSupersessionTest(unittest.TestCase):
    """AN-01 Task 15: design 9.6. Only a newer ANNOUNCEMENT transfers the mic lease.

    A satellite reply or a say_text turn bumps _say_gen but never writes _mic, so the announcement
    unmutes immediately. Rev 1 of the design asserted the opposite and accepted a deaf period that
    the design does not actually produce.
    """

    ENT = "switch.respeaker_test_microphone_mute"

    def setUp(self):
        FakeTimer.created = []
        self.zone = "media_player.ceiling_speakers"
        self.tts = "http://192.168.122.10:8123/api/tts_proxy/x.mp3"

    def _cap(self):
        clock = MovingClock()
        return interaction.InteractionCapability(timer_factory=FakeTimer, clock=clock,
                                                 sleeper=AdvancingSleeper(clock))

    def _ctx(self, ha):
        ctx = FakeCtx(ha)
        ctx.settings = FakeSettings()
        ctx.settings.announce_mic_mute_entity = self.ENT
        ctx.settings.announce_chime_uri = ""          # one clip, so the read counting is legible
        return ctx

    def _ha(self):
        ha = FakeHA(playing(0.36))
        ha.tts_url = self.tts
        return ha

    def _bump_on_nth_zone_read(self, cap, ha, n):
        """Simulate a NON-announcement turn superseding the zone mid-announcement."""
        seen = [0]
        real = ha.get_entity_state

        def watch(entity_id, timeout=None):
            if entity_id == self.zone:
                seen[0] += 1
                if seen[0] == n:
                    cap._say_gen[self.zone] = cap._say_gen.get(self.zone, 0) + 5
            return real(entity_id, timeout=timeout)
        ha.get_entity_state = watch

    def test_supersession_before_adoption_aborts_without_touching_the_zone(self):
        # The first zone read is _say's pre-turn capture, so the bump lands before adoption. Task
        # 13's revalidation then aborts before publishing OR raising anything -- strictly better
        # than raising and restoring, and the microphone still comes back.
        cap = self._cap()
        ha = self._ha()
        ctx = self._ctx(ha)
        ha.set_states([{"state": "off", "attributes": {}},
                       {"state": "on", "attributes": {}},
                       playing_with_id(0.36, "library://radio/2"),
                       playing_with_id(0.80, "builtin://radio/" + self.tts)])
        self._bump_on_nth_zone_read(cap, ha, 1)
        r = run(cap, ctx, {"mode": "announce", "text": "dinner is ready"})
        svcs = [sv for _, sv, _ in ha.calls]
        self.assertIn("turn_off", svcs)                            # the mic IS restored
        self.assertEqual([sv for sv in svcs if sv == "volume_set"], [])
        self.assertNotIn("play_media", svcs)
        self.assertTrue(r["ok"])
        self.assertTrue(r["metadata"]["superseded"])

    def test_supersession_after_adoption_leaves_the_zone_to_the_newer_turn(self):
        # The second zone read is the clip's start poll, so the announcement has already adopted,
        # published and raised. It then hands the zone over WITHOUT restoring: the superseding turn
        # owns the volume now, and restoring would undo what it just set.
        cap = self._cap()
        ha = self._ha()
        ctx = self._ctx(ha)
        ha.set_states([{"state": "off", "attributes": {}},
                       {"state": "on", "attributes": {}},
                       playing_with_id(0.36, "library://radio/2"),
                       playing_with_id(0.80, "builtin://radio/" + self.tts)])
        self._bump_on_nth_zone_read(cap, ha, 2)
        r = run(cap, ctx, {"mode": "announce", "text": "dinner is ready"})
        svcs = [sv for _, sv, _ in ha.calls]
        self.assertIn("turn_off", svcs)                            # the mic IS restored
        self.assertEqual(len([sv for sv in svcs if sv == "volume_set"]), 1)   # raise only
        self.assertTrue(r["metadata"]["superseded"])

    def test_a_superseded_announcement_is_not_reported_as_a_failure(self):
        # Being superseded is a person talking; it is not a fault to surface to the operator.
        cap = self._cap()
        ha = self._ha()
        ctx = self._ctx(ha)
        ha.set_states([{"state": "off", "attributes": {}},
                       {"state": "on", "attributes": {}},
                       playing_with_id(0.36, "library://radio/2"),
                       playing_with_id(0.80, "builtin://radio/" + self.tts)])
        self._bump_on_nth_zone_read(cap, ha, 2)
        r = run(cap, ctx, {"mode": "announce", "text": "dinner is ready"})
        self.assertTrue(r["ok"])
        self.assertEqual(r["chat_text"], "Announced.")
        self.assertIsNone(r["error"])

    def test_zone_supersession_does_not_transfer_the_mic_lease(self):
        cap = self._cap()
        ha = self._ha()
        ctx = self._ctx(ha)
        gen = cap._claim_gen(self.zone)
        cap._mic_claim(ctx, self.zone, gen, "rid-a")
        cap._say_gen[self.zone] = gen + 9                      # a non-announcement turn
        self.assertEqual(cap._mic[self.zone]["gen"], gen)
        self.assertTrue(cap._mic_release(ctx, self.zone, gen, "rid-a"))

    def test_the_mic_is_released_on_a_superseded_exit(self):
        cap = self._cap()
        ha = self._ha()
        ctx = self._ctx(ha)
        ha.set_states([{"state": "off", "attributes": {}},
                       {"state": "on", "attributes": {}},
                       playing_with_id(0.36, "library://radio/2"),
                       playing_with_id(0.80, "builtin://radio/" + self.tts)])
        self._bump_on_nth_zone_read(cap, ha, 1)
        run(cap, ctx, {"mode": "announce", "text": "dinner is ready"})
        self.assertEqual(cap._mic, {})

    def test_a_second_announcement_takes_the_lease_from_the_first(self):
        # The one case that DOES transfer: the newer announcement owns the restore, and the older
        # one's release becomes a no-op so it cannot unmute under the newer broadcast.
        cap = self._cap()
        ha = self._ha()
        ctx = self._ctx(ha)
        first = cap._claim_gen(self.zone)
        cap._mic_claim(ctx, self.zone, first, "rid-a")
        second = cap._claim_gen(self.zone)
        cap._mic_claim(ctx, self.zone, second, "rid-b")
        self.assertFalse(cap._mic_release(ctx, self.zone, first, "rid-a"))
        self.assertEqual(cap._mic[self.zone]["gen"], second)
        self.assertTrue(cap._mic_release(ctx, self.zone, second, "rid-b"))
        self.assertEqual(cap._mic, {})



class LostAckVolumeTest(unittest.TestCase):
    """AN-01 Task 16: design 8.4(c). _say set pending_restore AFTER the volume write.

    A lost acknowledgement -- the write lands, the response does not -- skipped the finally's
    restore AND the snap["target"] sync. A later _restore then read 0.80, classified it as a human
    override, KEPT it and discarded the baseline: the volume ratchet.

    This is a pre-existing defect reachable by any reply today. An announcement makes it dangerous,
    because a phone caller leaves no duck snapshot, so _arm_timer never ran and there is no volume
    dead-man at all -- _say's finally is the only net, and this is precisely the net the defect
    disabled.

    Claiming the obligation BEFORE the write can only cause a REDUNDANT restore to a value the zone
    already holds, which is harmless and idempotent. Claiming it after can cause a MISSING restore,
    which is neither.
    """

    def setUp(self):
        FakeTimer.created = []
        self.zone = "media_player.ceiling_speakers"
        self.tts = "http://192.168.122.10:8123/api/tts_proxy/x.mp3"

    def _cap(self):
        return interaction.InteractionCapability(timer_factory=FakeTimer, clock=lambda: 1000.0,
                                                 sleeper=FakeSleeper())

    def _lost_ack_ha(self):
        """Applies the volume write to its own state, THEN raises -- a lost ack."""
        ha = FakeHA(playing(0.36))
        ha.set_states([playing_with_id(0.36, "library://radio/2")])
        real = ha.call_service_rest
        state = {"raised": False}

        def lossy(domain, service, data, timeout=5):
            if service == "volume_set" and not state["raised"]:
                state["raised"] = True
                real(domain, service, data, timeout)      # the write LANDS
                raise IOError("connection reset after the write")
            real(domain, service, data, timeout)
        ha.call_service_rest = lossy
        return ha

    def _refusing_ha(self):
        """Refuses the first volume write BEFORE it lands."""
        ha = FakeHA(playing(0.36))
        ha.set_states([playing_with_id(0.36, "library://radio/2")])
        real = ha.call_service_rest
        state = {"n": 0}

        def refuse(domain, service, data, timeout=5):
            if service == "volume_set" and state["n"] == 0:
                state["n"] = 1
                raise IOError("refused before landing")
            real(domain, service, data, timeout)
        ha.call_service_rest = refuse
        return ha

    # ---- the defect ---------------------------------------------------------

    def test_a_lost_ack_on_the_volume_raise_still_restores_the_baseline(self):
        cap = self._cap()
        ha = self._lost_ack_ha()
        r = capability.run(cap, FakeCtx(ha), {"mode": "say", "uri": self.tts}, "rid-la")
        self.assertFalse(r["ok"])
        vols = [c[2]["volume_level"] for c in ha.calls if c[1] == "volume_set"]
        self.assertEqual(vols, [0.40, 0.36])          # raised, then restored on the way out

    def test_the_snap_target_sync_precedes_the_write(self):
        # So a later _restore or dead-man agrees with the device instead of classifying our own
        # reply volume as a human override and discarding the baseline.
        cap = self._cap()
        cap._snaps[self.zone] = {"volume": 0.36, "target": 0.15, "ts": 900.0, "timer": None}
        ha = self._lost_ack_ha()
        capability.run(cap, FakeCtx(ha), {"mode": "say", "uri": self.tts}, "rid-sync")
        # The snapshot was retired by the abort-restore; if it survives, target must not be 0.15.
        snap = cap._snaps.get(self.zone)
        if snap is not None:
            self.assertNotEqual(snap["target"], 0.15)

    def test_a_redundant_restore_is_harmless(self):
        # The write never landed: the restore writes a value the zone already holds.
        cap = self._cap()
        ha = self._refusing_ha()
        r = capability.run(cap, FakeCtx(ha), {"mode": "say", "uri": self.tts}, "rid-red")
        self.assertFalse(r["ok"])
        self.assertEqual([c[2]["volume_level"] for c in ha.calls if c[1] == "volume_set"], [0.36])

    # ---- the recovery paths the reordering touches --------------------------

    def test_the_lost_ack_snapshot_is_retired_so_no_stale_baseline_survives(self):
        # Leaving an armed snapshot behind carries a now-stale baseline into the next turn.
        cap = self._cap()
        cap._snaps[self.zone] = {"volume": 0.36, "target": 0.15, "ts": 900.0, "timer": None}
        ha = self._lost_ack_ha()
        capability.run(cap, FakeCtx(ha), {"mode": "say", "uri": self.tts}, "rid-ret")
        self.assertNotIn(self.zone, cap._snaps)

    def test_a_snapshot_belonging_to_a_LATER_turn_is_not_retired(self):
        # Ownership rule: we may only retire the snapshot our baseline came from. A duck that landed
        # during the reply owns the next turn's baseline and dead-man, and must survive us.
        cap = self._cap()
        ha = FakeHA(playing(0.36))
        ha.set_states([playing_with_id(0.36, "library://radio/2")])
        cap._snaps[self.zone] = {"volume": 0.36, "target": 0.15, "ts": 900.0, "timer": None}
        keep = {"volume": 0.55, "target": 0.15, "ts": 5000.0, "timer": None}
        real = ha.call_service_rest
        state = {"raised": False}

        def lossy(domain, service, data, timeout=5):
            if service == "volume_set" and not state["raised"]:
                state["raised"] = True
                real(domain, service, data, timeout)      # the write LANDS
                cap._snaps[self.zone] = keep              # a NEWER duck lands during our reply
                raise IOError("connection reset after the write")
            real(domain, service, data, timeout)
        ha.call_service_rest = lossy
        capability.run(cap, FakeCtx(ha), {"mode": "say", "uri": self.tts}, "rid-keep")
        self.assertIs(cap._snaps.get(self.zone), keep)
        self.assertEqual(keep["target"], 0.15)        # and we did not sync someone else's snapshot

    def test_the_sync_only_touches_the_snapshot_our_baseline_came_from(self):
        # The ownership half of the moved block. my_snap_ts is captured back at step 2; a snapshot
        # that appears AFTER that belongs to another turn, and writing our reply volume into its
        # target would tell that turn's reconciler the device sits somewhere it does not.
        #
        # Planted on the media_pause call, which is the last thing before the claim and the sync --
        # so the sync really does see a foreign snapshot, which is what the ts check is for.
        cap = self._cap()
        ha = FakeHA(playing(0.36))
        ha.set_states([playing_with_id(0.36, "library://radio/2"),
                       playing_with_id(0.40, "builtin://radio/" + self.tts),
                       idle_state(), idle_state(), playing(0.40)])
        late = {"volume": 0.55, "target": 0.15, "ts": 7000.0, "timer": None}
        real = ha.call_service_rest

        def plant(domain, service, data, timeout=5):
            if service == "media_pause":
                cap._snaps[self.zone] = late      # a duck lands between our claim and the sync
            real(domain, service, data, timeout)
        ha.call_service_rest = plant
        capability.run(cap, FakeCtx(ha), {"mode": "say", "uri": self.tts}, "rid-foreign")
        self.assertEqual(late["target"], 0.15)
        self.assertIs(cap._snaps.get(self.zone), late)     # nor did we retire it

    def test_the_reply_marker_is_released_on_the_lost_ack_path(self):
        cap = self._cap()
        ha = self._lost_ack_ha()
        capability.run(cap, FakeCtx(ha), {"mode": "say", "uri": self.tts}, "rid-rel")
        self.assertNotIn(self.zone, cap._replies)
        self.assertNotIn(self.zone, cap._turns)

    def test_the_music_is_un_paused_when_the_clip_never_went_out(self):
        # The other half of the finally. The volume write died, so play_media never issued and the
        # queue still holds the music -- un-pausing restores the zone rather than leaving it silent.
        cap = self._cap()
        ha = self._lost_ack_ha()
        capability.run(cap, FakeCtx(ha), {"mode": "say", "uri": self.tts}, "rid-unp")
        self.assertIn("media_play", [sv for _, sv, _ in ha.calls])

    def test_a_superseding_turn_keeps_the_zone_on_the_lost_ack_path(self):
        # A superseded turn must not restore: the newer turn owns the volume now, and restoring
        # would undo what it just set.
        cap = self._cap()
        ha = FakeHA(playing(0.36))
        ha.set_states([playing_with_id(0.36, "library://radio/2")])
        real = ha.call_service_rest
        state = {"raised": False}

        def lossy(domain, service, data, timeout=5):
            if service == "volume_set" and not state["raised"]:
                state["raised"] = True
                real(domain, service, data, timeout)
                cap._say_gen[self.zone] = cap._say_gen.get(self.zone, 0) + 5   # barge-in
                raise IOError("connection reset after the write")
            real(domain, service, data, timeout)
        ha.call_service_rest = lossy
        capability.run(cap, FakeCtx(ha), {"mode": "say", "uri": self.tts}, "rid-sup")
        self.assertEqual([c[2]["volume_level"] for c in ha.calls if c[1] == "volume_set"], [0.40])

    def test_with_owns_restore_off_the_lost_ack_does_not_restore(self):
        # say_owns_restore=False hands the restore to the duck/_restore path instead; the finally's
        # net is explicitly gated on owning it.
        cap = self._cap()
        ha = self._lost_ack_ha()
        ctx = FakeCtx(ha)
        ctx.settings = FakeSettings()
        ctx.settings.say_owns_restore = False
        capability.run(cap, ctx, {"mode": "say", "uri": self.tts}, "rid-noown")
        self.assertEqual([c[2]["volume_level"] for c in ha.calls if c[1] == "volume_set"], [0.40])

    # ---- the success path is unchanged --------------------------------------

    def test_on_the_success_path_the_snapshot_target_still_tracks_the_raise(self):
        cap = self._cap()
        ha = FakeHA(playing(0.36))
        ha.set_states([playing_with_id(0.36, "library://radio/2"),
                       playing_with_id(0.40, "builtin://radio/" + self.tts),
                       idle_state(), idle_state(), playing(0.40)])
        # A live duck snapshot, so the sync has something to write to.
        cap._snaps[self.zone] = {"volume": 0.36, "target": 0.15, "ts": 900.0, "timer": None}
        seen = []
        real = ha.call_service_rest

        def watch(domain, service, data, timeout=5):
            if service == "volume_set":
                snap = cap._snaps.get(self.zone)
                seen.append((data["volume_level"], snap["target"] if snap else None))
            real(domain, service, data, timeout)
        ha.call_service_rest = watch
        r = capability.run(cap, FakeCtx(ha), {"mode": "say", "uri": self.tts}, "rid-succ")
        self.assertTrue(r["ok"], r)
        # At the moment the raise is issued the snapshot already agrees with it.
        self.assertEqual(seen[0], (0.40, 0.40))

    def test_the_success_path_still_restores_exactly_once(self):
        cap = self._cap()
        ha = FakeHA(playing(0.36))
        ha.set_states([playing_with_id(0.36, "library://radio/2"),
                       playing_with_id(0.40, "builtin://radio/" + self.tts),
                       idle_state(), idle_state(), playing(0.40)])
        r = capability.run(cap, FakeCtx(ha), {"mode": "say", "uri": self.tts}, "rid-once")
        self.assertTrue(r["ok"], r)
        self.assertEqual([c[2]["volume_level"] for c in ha.calls if c[1] == "volume_set"],
                         [0.40, 0.36])
        self.assertNotIn("media_play", [sv for _, sv, _ in ha.calls])   # no spurious un-pause

    def test_an_announcement_with_a_lost_ack_restores_although_it_has_no_dead_man(self):
        # design 3.5: a phone caller leaves no duck snapshot, so _arm_timer never ran and there is
        # no volume dead-man. This finally is the ONLY net -- and it is louder, so a stranded value
        # is worse.
        cap = self._cap()
        ha = self._lost_ack_ha()
        ha.tts_url = self.tts
        ctx = FakeCtx(ha)
        ctx.settings = FakeSettings()
        ctx.settings.announce_mic_mute_entity = "switch.respeaker_test_microphone_mute"
        ctx.settings.announce_chime_uri = ""
        ha.set_states([{"state": "off", "attributes": {}},
                       {"state": "on", "attributes": {}},
                       playing_with_id(0.36, "library://radio/2")])
        r = capability.run(cap, ctx, {"mode": "announce", "text": "dinner is ready"}, "rid-anla")
        self.assertFalse(r["ok"])
        self.assertEqual([c[2]["volume_level"] for c in ha.calls if c[1] == "volume_set"],
                         [0.80, 0.36])
        self.assertNotIn(self.zone, cap._snaps)
        self.assertEqual(cap._mic, {})                # and the microphone came back



class AmbiguousPlayRecoveryTest(unittest.TestCase):
    """AN-01 Task 17: design 8.3a.

    A multi-clip turn creates a failure a single-clip turn cannot: the chime replaces the queue and
    the message dies. The old finalizer restored the volume and un-paused, and neither helped -- the
    replay lived only in step 9, which an exception skips, and the un-pause was gated on "no play
    was issued", which the chime's success falsifies. Even the un-pause would have been useless: the
    queue then holds a spent chime, not the music.

    The flag is claimed BEFORE each play, so any raising play leaves it set. "We may have changed
    the queue" is the only thing the caller can honestly know: a landed-but-unacknowledged play
    changes the queue while any success-gated flag stays False. So "no play was ever issued" has to
    mean the turn died before REACHING a play_media at all.

    Note on the fakes: a refused call never reaches ha.calls, so tests that need to observe an
    ATTEMPT record it themselves.
    """

    def setUp(self):
        FakeTimer.created = []
        self.zone = "media_player.ceiling_speakers"
        self.chime = ("http://192.168.122.10:8123/media/local/timer_chime.wav?authSig="
                      + FAKE_SIG)
        self.tts = "http://192.168.122.10:8123/api/tts_proxy/x.mp3"

    def _cap(self):
        return interaction.InteractionCapability(timer_factory=FakeTimer, clock=lambda: 1000.0,
                                                 sleeper=FakeSleeper())

    def _two_clip(self, cap, ha, rid):
        return capability.run(cap, FakeCtx(ha), {
            "mode": "say", "uri": self.tts,
            "uris": [self.chime, self.tts],
            "match_keys": [self.chime, self.tts],      # full URIs -- post-G1 correction 1
            "finish_timeouts": [15.0, 45.0],
            "volume_override": 0.80}, rid)

    def _plays(self, ha):
        return [c[2].get("media_id") for c in ha.calls if c[1] == "play_media"]

    def _svcs(self, ha):
        return [sv for _, sv, _ in ha.calls]

    # ---- the chime-first failure this task exists for -----------------------

    def test_chime_played_then_message_raises_replays_the_source(self):
        cap = self._cap()
        ha = FakeHA(playing(0.36))
        ha.set_states([playing_with_id(0.36, "library://radio/2"),
                       playing_with_id(0.80, "builtin://track/" + self.chime),
                       idle_state(), idle_state()])
        real = ha.call_service_rest
        n = {"plays": 0}

        def second_play_boom(domain, service, data, timeout=5):
            if service == "play_media":
                n["plays"] += 1
                if n["plays"] == 2:                       # the MESSAGE
                    raise IOError("MA refused")
            real(domain, service, data, timeout)
        ha.call_service_rest = second_play_boom
        r = self._two_clip(cap, ha, "rid-amb")
        self.assertFalse(r["ok"])
        self.assertIn("library://radio/2", self._plays(ha))       # the station is back
        self.assertNotIn("media_play", self._svcs(ha))            # no useless un-pause

    def test_the_chime_is_not_left_as_the_queue(self):
        # The concrete harm: without the replay the zone sits holding a spent chime.
        cap = self._cap()
        ha = FakeHA(playing(0.36))
        ha.set_states([playing_with_id(0.36, "library://radio/2"),
                       playing_with_id(0.80, "builtin://track/" + self.chime),
                       idle_state(), idle_state()])
        real = ha.call_service_rest
        n = {"plays": 0}

        def second_play_boom(domain, service, data, timeout=5):
            if service == "play_media":
                n["plays"] += 1
                if n["plays"] == 2:
                    raise IOError("MA refused")
            real(domain, service, data, timeout)
        ha.call_service_rest = second_play_boom
        self._two_clip(cap, ha, "rid-amb2")
        self.assertEqual(self._plays(ha)[-1], "library://radio/2")   # the LAST thing played

    # ---- replay versus un-pause --------------------------------------------

    def test_no_replay_when_the_turn_dies_before_any_play(self):
        # The step-4 volume_set raises, so no play_media was ever attempted and the flag is clear.
        # This CANNOT be written as "the first play_media raises": the flag is claimed before that
        # call, so a raising first play is an AMBIGUOUS failure and must replay.
        cap = self._cap()
        ha = FakeHA(playing(0.36))
        ha.set_states([playing_with_id(0.36, "library://radio/2")])
        real = ha.call_service_rest

        def volume_boom(domain, service, data, timeout=5):
            if service == "volume_set":
                raise IOError("refused")
            real(domain, service, data, timeout)
        ha.call_service_rest = volume_boom
        r = capability.run(cap, FakeCtx(ha), {"mode": "say", "uri": self.tts}, "rid-pre")
        self.assertFalse(r["ok"])
        self.assertEqual(self._plays(ha), [])
        self.assertIn("media_play", self._svcs(ha))      # un-pause, queue certainly intact

    def test_a_raising_first_play_replays_rather_than_unpausing(self):
        cap = self._cap()
        ha = FakeHA(playing(0.36))
        ha.set_states([playing_with_id(0.36, "library://radio/2")])
        real = ha.call_service_rest
        n = {"plays": 0}

        def first_play_boom(domain, service, data, timeout=5):
            if service == "play_media":
                n["plays"] += 1
                if n["plays"] == 1:
                    raise IOError("MA refused")
            real(domain, service, data, timeout)
        ha.call_service_rest = first_play_boom
        r = capability.run(cap, FakeCtx(ha), {"mode": "say", "uri": self.tts}, "rid-first")
        self.assertFalse(r["ok"])
        self.assertIn("library://radio/2", self._plays(ha))
        self.assertNotIn("media_play", self._svcs(ha))

    def test_lost_ack_on_the_chime_play_still_replays_the_source(self):
        cap = self._cap()
        ha = FakeHA(playing(0.36))
        ha.set_states([playing_with_id(0.36, "library://radio/2")])
        real = ha.call_service_rest
        n = {"plays": 0}

        def lossy(domain, service, data, timeout=5):
            if service == "play_media":
                n["plays"] += 1
                if n["plays"] == 1:
                    real(domain, service, data, timeout)     # the request LANDS
                    raise IOError("reset after the write")
            real(domain, service, data, timeout)
        ha.call_service_rest = lossy
        r = self._two_clip(cap, ha, "rid-lack")
        self.assertFalse(r["ok"])
        self.assertIn("library://radio/2", self._plays(ha))
        self.assertNotIn("media_play", self._svcs(ha))

    def test_lost_ack_on_the_message_play_when_it_is_the_only_clip(self):
        # The chime is disabled, so the message is the first and only play: the flag must already
        # be set when it raises.
        cap = self._cap()
        ha = FakeHA(playing(0.36))
        ha.set_states([playing_with_id(0.36, "library://radio/2")])
        real = ha.call_service_rest

        def lossy(domain, service, data, timeout=5):
            if service == "play_media":
                real(domain, service, data, timeout)
                raise IOError("reset after the write")
            real(domain, service, data, timeout)
        ha.call_service_rest = lossy
        r = capability.run(cap, FakeCtx(ha), {"mode": "say", "uri": self.tts}, "rid-monly")
        self.assertFalse(r["ok"])
        self.assertIn("library://radio/2", self._plays(ha))

    def test_the_flag_is_set_before_the_call_not_after(self):
        # White-box: a success-gated flag passes every other test here and fails this one.
        cap = self._cap()
        ha = FakeHA(playing(0.36))
        ha.set_states([playing_with_id(0.36, "library://radio/2")])
        seen = {"flag_at_call": None}
        real = ha.call_service_rest

        def probe(domain, service, data, timeout=5):
            if service == "play_media" and seen["flag_at_call"] is None:
                seen["flag_at_call"] = True                # reached only if claimed beforehand
                raise IOError("stop here")
            real(domain, service, data, timeout)
        ha.call_service_rest = probe
        capability.run(cap, FakeCtx(ha), {"mode": "say", "uri": self.tts}, "rid-probe")
        self.assertIn("library://radio/2", self._plays(ha))

    def test_no_replay_when_superseded(self):
        # A newer turn owns the zone and is about to play its own thing; replaying into it is the
        # CHANGELOG 2026-09-06 clobber defect from the other direction.
        cap = self._cap()
        ha = FakeHA(playing(0.36))
        ha.set_states([playing_with_id(0.36, "library://radio/2")])
        real = ha.call_service_rest

        n = {"plays": 0}

        def boom_then_supersede(domain, service, data, timeout=5):
            if service == "play_media":
                n["plays"] += 1
                if n["plays"] == 1:
                    cap._say_gen[self.zone] = cap._say_gen.get(self.zone, 0) + 5
                    raise IOError("MA refused")
            # Any LATER play is allowed through and recorded. Refusing every play would hide a
            # wrongly-attempted replay, and the test could not tell the two behaviours apart.
            real(domain, service, data, timeout)
        ha.call_service_rest = boom_then_supersede
        capability.run(cap, FakeCtx(ha), {"mode": "say", "uri": self.tts}, "rid-sup")
        self.assertEqual(self._plays(ha), [])
        self.assertEqual(n["plays"], 1)                  # the replay was never even attempted
        self.assertNotIn("media_play", self._svcs(ha))

    def test_exactly_one_replay_on_the_success_path(self):
        cap = self._cap()
        ha = FakeHA(playing(0.36))
        ha.set_states([playing_with_id(0.36, "library://radio/2"),
                       playing_with_id(0.40, "builtin://radio/" + self.tts),
                       idle_state(), idle_state(), playing(0.40)])
        capability.run(cap, FakeCtx(ha), {"mode": "say", "uri": self.tts}, "rid-one")
        self.assertEqual(len([m for m in self._plays(ha) if m == "library://radio/2"]), 1)

    def test_a_successful_two_clip_turn_still_replays_exactly_once(self):
        cap = self._cap()
        ha = FakeHA(playing(0.36))
        ha.set_states([playing_with_id(0.36, "library://radio/2"),
                       playing_with_id(0.80, "builtin://track/" + self.chime),
                       idle_state(), idle_state(),
                       playing_with_id(0.80, "builtin://radio/" + self.tts),
                       idle_state(), idle_state(), playing(0.80)])
        r = self._two_clip(cap, ha, "rid-2ok")
        self.assertTrue(r["ok"], r)
        self.assertEqual(len([m for m in self._plays(ha) if m == "library://radio/2"]), 1)
        self.assertNotIn("media_play", self._svcs(ha))

    # ---- design 8.3a's own no-source fallback -------------------------------

    def test_unpause_fallback_when_there_is_nothing_to_replay(self):
        # design 8.3a's own fallback: the flag is set, but the capture read gave no
        # media_content_id, so there is no source to replay. Without the un-pause the zone would be
        # left paused and silent. was_playing is true (volume present) while source_id is empty.
        cap = self._cap()
        ha = FakeHA(playing(0.36))
        ha.set_states([playing(0.36)])          # playing, but NO media_content_id
        real = ha.call_service_rest

        def play_boom(domain, service, data, timeout=5):
            if service == "play_media":
                raise IOError("MA refused")
            real(domain, service, data, timeout)
        ha.call_service_rest = play_boom
        r = capability.run(cap, FakeCtx(ha), {"mode": "say", "uri": self.tts}, "rid-nosrc")
        self.assertFalse(r["ok"])
        self.assertEqual(self._plays(ha), [])
        self.assertIn("media_play", self._svcs(ha))

    def test_no_unpause_when_we_did_not_pause(self):
        # The un-pause is only ever undoing OUR pause. An idle zone was never paused by us, so
        # starting playback would be inventing music nobody asked for.
        cap = self._cap()
        ha = FakeHA(idle_state())
        ha.set_states([idle_state()])
        real = ha.call_service_rest

        def play_boom(domain, service, data, timeout=5):
            if service == "play_media":
                raise IOError("MA refused")
            real(domain, service, data, timeout)
        ha.call_service_rest = play_boom
        capability.run(cap, FakeCtx(ha), {"mode": "say", "uri": self.tts}, "rid-idle")
        self.assertNotIn("media_play", self._svcs(ha))

    # ---- the doubly failed recovery, and the rejected addendum --------------

    def test_a_doubly_failed_recovery_leaves_the_zone_paused_rather_than_guessing(self):
        # design 8.3a as approved: a replay that RAISED may still have landed, so a following
        # media_play could resume the announcement clip instead of the music. The zone is left
        # paused at its restored baseline; the operator recovers with "resume".
        cap = self._cap()
        ha = FakeHA(playing(0.36))
        ha.set_states([playing_with_id(0.36, "library://radio/2")])
        attempts = []
        real = ha.call_service_rest

        def all_plays_boom(domain, service, data, timeout=5):
            if service == "play_media":
                attempts.append(data.get("media_id"))
                raise IOError("MA refused")
            real(domain, service, data, timeout)
        ha.call_service_rest = all_plays_boom
        r = capability.run(cap, FakeCtx(ha), {"mode": "say", "uri": self.tts}, "rid-both")
        self.assertFalse(r["ok"])
        self.assertNotIn("media_play", self._svcs(ha))   # no blind un-pause: the rejected addendum
        # The replay WAS attempted, and the volume still came back to the baseline.
        self.assertIn("library://radio/2", attempts)
        self.assertEqual([c[2]["volume_level"] for c in ha.calls if c[1] == "volume_set"][-1], 0.36)

    def test_the_doubly_failed_zone_is_recoverable_by_resume(self):
        # The accepted residual is only acceptable because a documented recovery exists: `resume`
        # un-pauses a paused zone. Pinned here so the residual cannot quietly become a dead end.
        cap = self._cap()
        ha = FakeHA({"state": "paused", "attributes": {"volume_level": 0.36}})
        r = capability.run(cap, FakeCtx(ha), {"mode": "resume"}, "rid-rec")
        self.assertTrue(r["ok"])
        self.assertTrue(r["metadata"]["resumed"])
        self.assertIn("media_play", [sv for _, sv, _ in ha.calls])

    def test_an_announcement_whose_message_dies_replays_the_station(self):
        # The end-to-end shape of the failure that motivated 8.3a, through the announce path.
        cap = self._cap()
        ha = FakeHA(playing(0.36))
        ha.tts_url = self.tts
        ha.media_url = self.chime
        ctx = FakeCtx(ha)
        ctx.settings = FakeSettings()
        ctx.settings.announce_mic_mute_entity = "switch.respeaker_test_microphone_mute"
        ha.set_states([{"state": "off", "attributes": {}},
                       {"state": "on", "attributes": {}},
                       playing_with_id(0.36, "library://radio/2"),
                       playing_with_id(0.80, "builtin://track/" + self.chime),
                       idle_state(), idle_state()])
        real = ha.call_service_rest
        n = {"plays": 0}

        def second_play_boom(domain, service, data, timeout=5):
            if service == "play_media":
                n["plays"] += 1
                if n["plays"] == 2:
                    raise IOError("MA refused")
            real(domain, service, data, timeout)
        ha.call_service_rest = second_play_boom
        r = capability.run(cap, ctx, {"mode": "announce", "text": "dinner is ready"}, "rid-anb")
        self.assertFalse(r["ok"])
        self.assertIn("library://radio/2", self._plays(ha))
        self.assertNotIn("media_play", self._svcs(ha))
        self.assertEqual(cap._mic, {})                    # and the microphone still came back



class MarkerBudgetTest(unittest.TestCase):
    """AN-01 Task 18: design 8.4(a). The orphan threshold is
    (say_start + say_reply)/1000 + 60 = ~95s with these settings. A turn owning the zone for two
    clips can legitimately hold it longer, so it would declare its OWN marker stale and be
    reclaimed mid-flight -- duck and restore would take the zone back while the announcement was
    still speaking.

    The marker carries its own budget: the step-2-to-finally span, NOT just the poll budgets. A
    clip-count multiplier was the first draft and is worse -- with per-clip timeouts the clips are
    different sizes, so clips x (start + reply) over-counts an announcement by roughly 3x.
    """

    def setUp(self):
        FakeTimer.created = []
        self.zone = "media_player.ceiling_speakers"
        self.tts = "http://192.168.122.10:8123/api/tts_proxy/x.mp3"

    def _cap(self, now):
        return interaction.InteractionCapability(timer_factory=FakeTimer, clock=lambda: now[0],
                                                 sleeper=FakeSleeper())

    def _marker(self, **over):
        m = {"gen": 1, "baseline": 0.36, "ts": 1000.0, "rid": "r"}
        m.update(over)
        return m

    # ---- _reply_active honours the published budget -------------------------

    def test_a_marker_with_a_budget_is_not_stale_before_it_elapses(self):
        now = [1000.0]
        cap = self._cap(now)
        cap._replies[self.zone] = self._marker(marker_budget_s=145.0)
        now[0] = 1000.0 + 145.0 + 30.0            # inside 145 + 60
        self.assertIsNotNone(cap._reply_active(FakeCtx(FakeHA()), self.zone))

    def test_a_marker_with_a_budget_is_stale_after_it_elapses(self):
        now = [1000.0]
        cap = self._cap(now)
        cap._replies[self.zone] = self._marker(marker_budget_s=145.0)
        now[0] = 1000.0 + 145.0 + 61.0
        self.assertIsNone(cap._reply_active(FakeCtx(FakeHA()), self.zone))

    def test_a_marker_without_a_budget_keeps_todays_threshold(self):
        now = [1000.0]
        cap = self._cap(now)
        cap._replies[self.zone] = self._marker()
        now[0] = 1000.0 + 240.0
        # FakeSettings has say_reply_timeout_ms = 30000, so the legacy budget is 95s.
        self.assertIsNone(cap._reply_active(FakeCtx(FakeHA()), self.zone))
        now[0] = 1000.0 + 50.0
        cap._replies[self.zone]["ts"] = now[0]
        self.assertIsNotNone(cap._reply_active(FakeCtx(FakeHA()), self.zone))

    def test_an_explicit_budget_of_none_falls_back_to_the_legacy_formula(self):
        # say/say_text publish the key as None rather than omitting it, so the fallback has to be
        # keyed on the VALUE, not on the key's presence.
        now = [1000.0]
        cap = self._cap(now)
        cap._replies[self.zone] = self._marker(marker_budget_s=None)
        now[0] = 1000.0 + 96.0
        self.assertIsNone(cap._reply_active(FakeCtx(FakeHA()), self.zone))

    def test_a_zero_budget_is_honoured_rather_than_treated_as_absent(self):
        # `is None`, not truthiness: 0.0 means "no span of its own", which is still an answer.
        now = [1000.0]
        cap = self._cap(now)
        cap._replies[self.zone] = self._marker(marker_budget_s=0.0)
        now[0] = 1000.0 + 61.0
        self.assertIsNone(cap._reply_active(FakeCtx(FakeHA()), self.zone))
        cap._replies[self.zone]["ts"] = now[0]
        self.assertIsNotNone(cap._reply_active(FakeCtx(FakeHA()), self.zone))

    def test_say_owns_restore_off_still_disowns_the_zone_regardless_of_the_budget(self):
        now = [1000.0]
        cap = self._cap(now)
        cap._replies[self.zone] = self._marker(marker_budget_s=145.0)
        ctx = FakeCtx(FakeHA())
        ctx.settings = FakeSettings()
        ctx.settings.say_owns_restore = False
        self.assertIsNone(cap._reply_active(ctx, self.zone))

    # ---- what _say publishes ------------------------------------------------

    def _spy_marker(self, cap):
        seen = {}
        real_play = cap._play_clip_and_wait

        def spy(ctx, rid, zone, norm_uri, match_key, clip, opts, superseded):
            # The marker is deleted by release_reply, so capture it WHILE in flight: the clip
            # helper runs after step 2 has published it.
            seen.setdefault("marker", dict(cap._replies.get(zone) or {}))
            return real_play(ctx, rid, zone, norm_uri, match_key, clip, opts, superseded)
        cap._play_clip_and_wait = spy
        return seen

    def test_say_publishes_a_budget_for_a_multi_clip_turn(self):
        now = [1000.0]
        cap = self._cap(now)
        ha = FakeHA(playing(0.36))
        ha.set_states([playing_with_id(0.36, "library://radio/2")])
        seen = self._spy_marker(cap)
        capability.run(cap, FakeCtx(ha), {"mode": "say", "uri": self.tts,
                                          "uris": [self.tts, self.tts],
                                          "match_keys": [self.tts, self.tts],
                                          "finish_timeouts": [15.0, 45.0]}, "rid-mb")
        self.assertIsNotNone(seen["marker"].get("marker_budget_s"))
        # 5 + 5 + sum(finish + start + call) + 5 + call, with FakeSettings' 5s start / 20s call.
        self.assertAlmostEqual(seen["marker"]["marker_budget_s"], 145.0, delta=1.0)

    def test_say_text_publishes_no_budget(self):
        now = [1000.0]
        cap = self._cap(now)
        ha = FakeHA(playing(0.36))
        ha.tts_url = self.tts
        ha.set_states([playing_with_id(0.36, "library://radio/2")])
        seen = self._spy_marker(cap)
        capability.run(cap, FakeCtx(ha), {"mode": "say_text", "text": "hello"}, "rid-st")
        self.assertIsNone(seen["marker"].get("marker_budget_s"))

    def test_plain_say_publishes_no_budget(self):
        now = [1000.0]
        cap = self._cap(now)
        ha = FakeHA(playing(0.36))
        ha.set_states([playing_with_id(0.36, "library://radio/2")])
        seen = self._spy_marker(cap)
        capability.run(cap, FakeCtx(ha), {"mode": "say", "uri": self.tts}, "rid-plain")
        self.assertIsNone(seen["marker"].get("marker_budget_s"))

    def test_an_announcement_publishes_a_budget_that_covers_its_own_span(self):
        now = [1000.0]
        cap = self._cap(now)
        ha = FakeHA(playing(0.36))
        ha.tts_url = self.tts
        ha.media_url = "http://192.168.122.10:8123/media/local/timer_chime.wav?authSig=" + FAKE_SIG
        ctx = FakeCtx(ha)
        ctx.settings = FakeSettings()
        ctx.settings.announce_mic_mute_entity = "switch.respeaker_test_microphone_mute"
        ha.set_states([{"state": "off", "attributes": {}},
                       {"state": "on", "attributes": {}},
                       playing_with_id(0.36, "library://radio/2")])
        seen = self._spy_marker(cap)
        capability.run(cap, ctx, {"mode": "announce", "text": "dinner is ready"}, "rid-an")
        budget = seen["marker"].get("marker_budget_s")
        self.assertIsNotNone(budget)
        self.assertGreater(budget, 95.0)          # i.e. beyond the legacy orphan threshold

    def test_a_longer_message_timeout_widens_the_budget(self):
        # The point of the whole task: announce_message_finish_timeout_ms is a tunable, and raising
        # it must not silently reintroduce mid-flight reclaim. This is defence for the config, not
        # for today's numbers.
        budgets = []
        for msg_ms in (45000, 240000):
            now = [1000.0]
            cap = self._cap(now)
            ha = FakeHA(playing(0.36))
            ha.tts_url = self.tts
            ctx = FakeCtx(ha)
            ctx.settings = FakeSettings()
            ctx.settings.announce_mic_mute_entity = "switch.respeaker_test_microphone_mute"
            ctx.settings.announce_chime_uri = ""
            ctx.settings.announce_message_finish_timeout_ms = msg_ms
            ha.set_states([{"state": "off", "attributes": {}},
                           {"state": "on", "attributes": {}},
                           playing_with_id(0.36, "library://radio/2")])
            seen = self._spy_marker(cap)
            capability.run(cap, ctx, {"mode": "announce", "text": "dinner is ready"}, "rid-w")
            budgets.append(seen["marker"]["marker_budget_s"])
        self.assertGreater(budgets[1], budgets[0] + 190.0)

    def test_a_long_announcement_does_not_declare_its_own_marker_stale(self):
        # The defect itself, end to end at the _reply_active level.
        now = [1000.0]
        cap = self._cap(now)
        cap._replies[self.zone] = self._marker(marker_budget_s=145.0)
        for offset in (100.0, 145.0, 200.0):
            now[0] = 1000.0 + offset
            self.assertIsNotNone(cap._reply_active(FakeCtx(FakeHA()), self.zone), offset)


class ClipPollBoundTest(unittest.TestCase):
    """AN-01 Task 18: the clip poll must be bounded by BOTH its accumulated sleep and its wall-clock
    deadline.

    A correction to something I reported after Task 15. I claimed the per-clip finish timeout was
    only advisory once a turn deadline was set. That was wrong: the breaks are
    min(start_deadline, deadline) and min(finish_deadline, deadline), so each clip's own budget is
    enforced. The tests below pin that, so the claim cannot be made again.

    The real defect in the same code is narrower. With a deadline set, the loop was PURELY
    wall-clock: it dropped the accumulated-sleep test entirely. time.time is not monotonic, so a
    clock that stalls or steps backwards leaves the poll unbounded -- which is also why the planned
    Task 15 tests, written against a frozen clock, could not terminate. Enforcing both bounds costs
    nothing under a sane clock, where the wall clock always fires first.
    """

    ZONE = "media_player.ceiling_speakers"
    URI = "http://192.168.122.10:8123/api/tts_proxy/abc.mp3"
    WRAPPED = "builtin://radio/http://192.168.122.10:8123/api/tts_proxy/abc.mp3"

    def _opts(self, **over):
        opts = {"start_timeout": 5.0, "finish_timeout": 10.0, "call_timeout": 20.0,
                "poll_secs": 0.5, "blank_grace": 4.0, "deadline": None, "floor": 0.5}
        opts.update(over)
        return opts

    def _run(self, cap, ha, opts):
        ctx = FakeCtx(ha)
        return cap._play_clip_and_wait(ctx, "rid1", self.ZONE, self.URI, self.URI,
                                       "clip", opts, lambda: False)

    def _match(self):
        return playing_with_id(0.70, self.WRAPPED)

    # ---- the belt: a clock that does not advance ----------------------------

    def test_a_start_poll_with_a_deadline_terminates_on_a_frozen_clock(self):
        cap = interaction.InteractionCapability(timer_factory=FakeTimer, clock=lambda: 1000.0,
                                                sleeper=FakeSleeper())
        ha = FakeHA(idle_state())
        res = self._run(cap, ha, self._opts(deadline=1070.0, start_timeout=5.0, poll_secs=0.5))
        self.assertFalse(res["started"])
        self.assertEqual(len(ha.state_timeouts), 10)      # 5.0s / 0.5s of accumulated sleep

    def test_a_finish_poll_with_a_deadline_terminates_on_a_frozen_clock(self):
        cap = interaction.InteractionCapability(timer_factory=FakeTimer, clock=lambda: 1000.0,
                                                sleeper=FakeSleeper())
        ha = FakeHA(self._match())
        res = self._run(cap, ha, self._opts(deadline=1070.0, finish_timeout=3.0, poll_secs=0.5))
        self.assertTrue(res["started"])
        self.assertEqual(len(ha.state_timeouts), 7)       # 1 start + 3.0s / 0.5s finish

    def test_a_poll_terminates_when_the_clock_steps_backwards(self):
        # An NTP correction mid-turn. A purely wall-clock loop keeps `deadline - now` large and
        # never exits.
        now = [1000.0]
        cap = interaction.InteractionCapability(timer_factory=FakeTimer,
                                               clock=lambda: now[0],
                                               sleeper=lambda secs: now.__setitem__(0, now[0] - 1))
        ha = FakeHA(idle_state())
        res = self._run(cap, ha, self._opts(deadline=1005.0, start_timeout=5.0, poll_secs=0.5))
        self.assertFalse(res["started"])
        self.assertLessEqual(len(ha.state_timeouts), 11)

    # ---- the braces: each clip's own budget really is enforced --------------

    def test_the_per_clip_finish_timeout_bounds_a_clip_inside_a_longer_turn_deadline(self):
        clock = MovingClock()
        cap = interaction.InteractionCapability(timer_factory=FakeTimer, clock=clock,
                                                sleeper=AdvancingSleeper(clock))
        ha = FakeHA(self._match())
        res = self._run(cap, ha, self._opts(deadline=clock.t + 600.0, finish_timeout=2.0,
                                            poll_secs=0.5))
        self.assertTrue(res["started"])
        self.assertEqual(len(ha.state_timeouts), 5)       # 1 start + 2.0s / 0.5s, NOT 600s worth

    def test_the_per_clip_wall_clock_bound_is_not_masked_by_the_sleep_belt(self):
        # The discriminating case for min(finish_deadline, deadline). With reads that cost no
        # wall-clock time the two bounds fire together, so a test like the one above cannot tell
        # whether the per-clip wall-clock bound exists at all -- the sleep belt would stop the poll
        # either way.
        #
        # Here each read burns 1.5s while a poll sleeps 0.5s, so the wall clock runs 4x the
        # accumulated sleep. This clip's own 2.0s budget is reached after a single read, long before
        # the sleep belt would notice, and the 600s turn deadline is nowhere near.
        clock = MovingClock()
        cap = interaction.InteractionCapability(timer_factory=FakeTimer, clock=clock,
                                                sleeper=AdvancingSleeper(clock))
        ha = FakeHA()
        reads = []
        first = [True]

        def watch(entity_id, timeout=None):
            reads.append(timeout)
            clock.advance(1.5)                            # a slow read
            if first[0]:
                first[0] = False
                return self._match()                      # the clip starts immediately
            return self._match()                          # ...and keeps playing
        ha.get_entity_state = watch
        res = self._run(cap, ha, self._opts(deadline=clock.t + 600.0, finish_timeout=2.0,
                                            poll_secs=0.5))
        self.assertTrue(res["started"])
        self.assertEqual(len(reads), 2)      # 1 start + 1 finish; NOT the 5 the sleep belt allows

    def test_a_short_turn_deadline_still_wins_over_a_long_per_clip_timeout(self):
        clock = MovingClock()
        cap = interaction.InteractionCapability(timer_factory=FakeTimer, clock=clock,
                                                sleeper=AdvancingSleeper(clock))
        ha = FakeHA(self._match())
        res = self._run(cap, ha, self._opts(deadline=clock.t + 1.0, finish_timeout=600.0,
                                            poll_secs=0.5))
        self.assertTrue(res["started"])
        self.assertLessEqual(len(ha.state_timeouts), 4)

    def test_the_wall_clock_bound_still_fires_first_under_a_normal_clock(self):
        # No behaviour change where it matters: reads take real time, so the wall clock reaches the
        # budget before the accumulated sleep does. The belt only bites when the clock misbehaves.
        clock = MovingClock()
        cap = interaction.InteractionCapability(timer_factory=FakeTimer, clock=clock,
                                                sleeper=AdvancingSleeper(clock))
        ha = FakeHA()
        burn = []

        def watch(entity_id, timeout=None):
            burn.append(timeout)
            clock.advance(0.5)                            # each read costs as much as a poll
            return idle_state()
        ha.get_entity_state = watch
        res = self._run(cap, ha, self._opts(deadline=clock.t + 600.0, start_timeout=5.0,
                                            poll_secs=0.5))
        self.assertFalse(res["started"])
        self.assertEqual(len(burn), 5)                    # 5.0s of WALL clock, not 10 sleeps

    # ---- say / say_text timing semantics are untouched ---------------------

    def test_with_no_deadline_a_slow_read_does_not_shorten_the_poll(self):
        # say and say_text keep accumulated-sleep bounding: time spent inside the reads must NOT
        # count against the budget, or their effective poll count would silently drop.
        clock = MovingClock()
        cap = interaction.InteractionCapability(timer_factory=FakeTimer, clock=clock,
                                                sleeper=AdvancingSleeper(clock))
        ha = FakeHA()
        seen = []

        def watch(entity_id, timeout=None):
            seen.append(timeout)
            clock.advance(30.0)                           # a very slow read
            return idle_state()
        ha.get_entity_state = watch
        res = self._run(cap, ha, self._opts(deadline=None, start_timeout=5.0, poll_secs=0.5))
        self.assertFalse(res["started"])
        self.assertEqual(len(seen), 10)                   # still 5.0s / 0.5s of sleep

    def test_with_no_deadline_reads_are_still_unclipped(self):
        clock = MovingClock()
        cap = interaction.InteractionCapability(timer_factory=FakeTimer, clock=clock,
                                                sleeper=AdvancingSleeper(clock))
        ha = FakeHA(self._match())
        self._run(cap, ha, self._opts(deadline=None))
        self.assertEqual(set(ha.state_timeouts), set([10]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
