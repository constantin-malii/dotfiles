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
    def set_states(self, states):
        self._states = list(states)
    def get_entity_state(self, entity_id):
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
                       idle_state()])
        real_write = ha.call_service_rest

        def write_then_next_turn_ducks(domain, service, data):
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

        def boom_on_play_media(domain, service, data):
            if service == "play_media":
                raise IOError("MA play_media 500")
            real_write(domain, service, data)
        ha.call_service_rest = boom_on_play_media
        r = run(cap, ctx, {"mode": "say", "uri": self.norm_uri})
        self.assertFalse(r["ok"])
        self.assertNotIn(zone, cap._replies)                     # ownership handed back
        # the abort path put the zone back on the baseline itself...
        self.assertAlmostEqual(ha.calls[-1][2]["volume_level"], 0.32)
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
                           idle_state()])
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
