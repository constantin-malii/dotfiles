#!/usr/bin/env python3
"""AU-02/03 InteractionCapability unit tests. Run: python tests/test_interaction.py"""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import capability, interaction


class FakeHA(object):
    def __init__(self, state=None, boom=None):
        self._state = state
        self._boom = boom
        self.calls = []                              # (domain, service, data)
    def get_entity_state(self, entity_id):
        if self._boom is not None:
            raise self._boom
        return self._state
    def call_service(self, domain, service, data):
        self.calls.append((domain, service, data))


class FakeSettings(object):
    ceiling_entity = "media_player.ceiling_speakers"
    interaction_floor = 15
    max_duck_timeout = 45000
    interaction_ignore_when_idle = True


class FakeCtx(object):
    def __init__(self, ha):
        self.ha = ha
        self.settings = FakeSettings()


def playing(vol):
    return {"state": "playing", "attributes": {"volume_level": vol}}


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


if __name__ == "__main__":
    unittest.main(verbosity=2)
