# AU-02 + AU-03 — Interaction Duck/Restore (`InteractionCapability`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use `superpowers:subagent-driven-development` (recommended)
> or `superpowers:executing-plans` to implement this plan task-by-task. Steps use `- [ ]` checkboxes.

**Goal:** Add a resolver capability that **ducks** the ceiling media zone's volume during an assistant
interaction and **restores** it afterward — satisfying **AU-02** (restore/resume, AU-01 §6) and **AU-03**
(duck-not-boost, AU-01 §5) as one unit, and providing the `interaction` intent that **S1a**'s HA automation
will trigger.

**Architecture:** A new `InteractionCapability` (`interaction.py`) following the existing
`resolve → validate → execute → CommandResult` pattern. It reads volume via `haconn.HA.get_entity_state`
and writes via `haconn.HA.call_service("media_player","volume_set",…)` — no MA calls, no new TTS path. It
holds a **per-zone snapshot** on the singleton instance, with **coalesce** (re-duck keeps the original
baseline), **last-writer-wins** restore (don't clobber a user's mid-interaction volume change), and a
**dead-man timeout** (auto-restore if the restore trigger never arrives). The intent is **silent**
(`spoken_text=None`) — resolver stays sole TTS owner.

**Tech Stack:** Python 3.5 (host runs 3.5.2), stdlib `unittest`, resolver modules under
`docs/homebrain/mass-resolver/`.

## Global Constraints

- **Python 3.5 only:** no f-strings, no type hints, no `async`/`await`, no `_` numeric separators
  (`45000` not `45_000`), no `dataclasses`. Use `%`/`.format()`.
- **Tests:** stdlib `unittest`; new file `tests/test_interaction.py`; run from the resolver dir:
  `python tests/test_interaction.py`. Follow the `FakeHA`/`FakeSettings`/`FakeCtx` style in
  `tests/test_status.py` and `tests/test_core.py`.
- **Silent intent:** every `InteractionCapability` result has `spoken_text=None` (volume action, not
  speech). Resolver = sole TTS owner (ONBOARDING §12).
- **No deploy in this plan.** Code + tests land on the branch (ungated). The host deploy to
  `~/mass-resolver` + restart is a **separate, approval-gated live step** (see "Deployment" at the end).
- **Volume lever:** `media_player.volume_set` only — never `volume_mute` (HTTP-errors on the Universal
  player, AU-01 §2) and never `media_stop` (stop-wedge).
- **Working dir for all commands:** `docs/homebrain/mass-resolver/`.

## File structure

- **Create:** `docs/homebrain/mass-resolver/interaction.py` — `InteractionCapability`.
- **Create:** `docs/homebrain/mass-resolver/tests/test_interaction.py` — unit tests.
- **Modify:** `docs/homebrain/mass-resolver/config.py` — add 4 tunables to `Settings.__init__`.
- **Modify:** `docs/homebrain/mass-resolver/config.json` — add the 4 tunables (deployed config).
- **Modify:** `docs/homebrain/mass-resolver/core.py` — register `InteractionCapability` in `CAPS`.

**Interfaces produced (later tasks + S1a rely on these):**
- `interaction.InteractionCapability(timer_factory=None, clock=None)` — capability singleton; `name="interaction"`.
- `execute` params (via `resolve`): `{"mode": "duck"|"restore", "zone": <entity_id, default ceiling>}`.
- `CommandResult.metadata` keys: `ducked`(bool), `restored`(bool), `from`/`to`(float|None), `reason`(str).
- Config: `settings.interaction_floor` (int %), `fade_ms` (int), `max_duck_timeout` (int ms),
  `interaction_ignore_when_idle` (bool).

---

### Task 0: Thread-safe HA sends (concurrency prerequisite — must ship with the code)

**Why:** `haconn.HA.call_service` sends on the **shared** event WebSocket `self.s` with **no lock**
(`haconn.py:32-35` → `wsutil.ws_send` → `s.sendall`). The HTTP server is `ThreadingMixIn`, and Task 3's
dead-man runs `call_service` on a **`threading.Timer` thread** — so two threads can `sendall` on one socket
at once → interleaved bytes → corrupt WS frames → broken HA connection. `get_entity_state` already dodges
this with a fresh per-call HTTP connection (`haconn.py:37-43`); `call_service` needs an explicit lock. This
is invisible to the fake-based suite, so it **lands with the code, not deferred to deploy.** (It also fixes
the pre-existing latent race between concurrent `/command` requests.)

**Files:** Modify `haconn.py`; Modify `tests/test_haconn.py`.

- [ ] **Step 1: Failing test** — add to `tests/test_haconn.py`:

```python
class SendLockTest(unittest.TestCase):
    def test_call_service_holds_lock_during_send(self):
        ha = haconn.HA("h", 1, "tok")
        held = {"during_send": None}
        class FakeSock(object):
            def sendall(self, b):
                held["during_send"] = ha._send_lock.locked()
        ha.s = FakeSock()
        ha.call_service("media_player", "volume_set", {"entity_id": "x", "volume_level": 0.1})
        self.assertTrue(held["during_send"])          # lock held while sending
        self.assertFalse(ha._send_lock.locked())      # released after
```

- [ ] **Step 2: Run, verify fail** — `python tests/test_haconn.py` → FAIL (`no attribute '_send_lock'`).

- [ ] **Step 3: Implement** — in `haconn.py`: add `import threading` at top; in `HA.__init__` add
  `self._send_lock = threading.Lock()`; wrap the send + `cmd_id` bump in `call_service`:

```python
    def call_service(self, domain, service, data):
        with self._send_lock:
            self.cmd_id += 1
            wsutil.ws_send(self.s, {"id": self.cmd_id, "type": "call_service",
                                    "domain": domain, "service": service, "service_data": data})
```

(The interaction path and `announce` both go through `call_service`, so wrapping it covers them; `subscribe`
runs only at startup on the main thread. `Speaker.speak` already serializes its own calls.)

- [ ] **Step 4: Run, verify pass** — `python tests/test_haconn.py` → PASS.

- [ ] **Step 5: Commit**

```bash
git add haconn.py tests/test_haconn.py
git commit -m "fix(resolver): thread-safe HA call_service send (lock shared WS)"
```

---

### Task 1: Config tunables

**Files:** Modify `config.py:Settings.__init__`; Modify `config.json`; Test `tests/test_config.py`.

**Interfaces — Produces:** `settings.interaction_floor`, `settings.fade_ms`, `settings.max_duck_timeout`,
`settings.interaction_ignore_when_idle`.

- [ ] **Step 1: Write the failing test** — append to `tests/test_config.py`:

```python
class InteractionTunablesTest(unittest.TestCase):
    def test_defaults(self):
        s = config.Settings({})
        self.assertEqual(s.interaction_floor, 15)
        self.assertEqual(s.fade_ms, 0)
        self.assertEqual(s.max_duck_timeout, 120000)
        self.assertTrue(s.interaction_ignore_when_idle)

    def test_overrides(self):
        s = config.Settings({"interaction_floor": 25, "fade_ms": 200,
                             "max_duck_timeout": 30000, "interaction_ignore_when_idle": False})
        self.assertEqual(s.interaction_floor, 25)
        self.assertEqual(s.fade_ms, 200)
        self.assertEqual(s.max_duck_timeout, 30000)
        self.assertFalse(s.interaction_ignore_when_idle)
```

- [ ] **Step 2: Run it, verify it fails**

Run: `python tests/test_config.py`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'interaction_floor'`.

- [ ] **Step 3: Implement** — in `config.py`, add to the end of `Settings.__init__`:

```python
        # AU-02/AU-03 interaction duck/restore tunables
        self.interaction_floor = int(cfg.get("interaction_floor", 15))          # % while interacting
        self.fade_ms = int(cfg.get("fade_ms", 0))                               # reserved (no fade v1)
        self.max_duck_timeout = int(cfg.get("max_duck_timeout", 120000))        # ms dead-man auto-restore (>= longest reply)
        self.interaction_ignore_when_idle = bool(cfg.get("interaction_ignore_when_idle", True))
```

- [ ] **Step 4: Add deployed config** — in `config.json`, add the four keys (near the ceiling entries):

```json
  "interaction_floor": 15,
  "fade_ms": 0,
  "max_duck_timeout": 120000,
  "interaction_ignore_when_idle": true,
```

- [ ] **Step 5: Run it, verify it passes**

Run: `python tests/test_config.py`
Expected: PASS (all tests, including the two new ones).

- [ ] **Step 6: Commit (code + runtime config separately, per CLAUDE.md)**

```bash
git add config.py tests/test_config.py
git commit -m "feat(resolver): add interaction duck/restore tunables"
git add config.json
git commit -m "config(resolver): interaction duck/restore tunable values"
```

---

### Task 2: Capability skeleton — resolve + validate

**Files:** Create `interaction.py`; Create `tests/test_interaction.py`.

**Interfaces — Consumes:** `capability.Capability`, `command_result`. **Produces:** `InteractionCapability`
with `resolve` (mode/zone) + `validate` (mode ∈ {duck,restore}).

- [ ] **Step 1: Write the failing test** — create `tests/test_interaction.py`:

```python
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

- [ ] **Step 2: Run it, verify it fails**

Run: `python tests/test_interaction.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'interaction'`.

- [ ] **Step 3: Implement** — create `interaction.py`:

```python
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

    # implemented in later tasks
    def _duck(self, ctx, zone, rid):
        raise NotImplementedError

    def _restore(self, ctx, zone, rid):
        raise NotImplementedError
```

- [ ] **Step 4: Run it, verify it passes**

Run: `python tests/test_interaction.py`
Expected: PASS (resolve/validate tests). (`test_invalid_mode_rejected` passes because `validate`
short-circuits before `_duck`.)

- [ ] **Step 5: Commit**

```bash
git add interaction.py tests/test_interaction.py
git commit -m "feat(resolver): InteractionCapability resolve/validate skeleton"
```

---

### Task 3: Duck

**Files:** Modify `interaction.py` (`_duck`); Modify `tests/test_interaction.py`.

**Interfaces — Produces:** `_duck` snapshots current volume (per zone), sets `volume_set` to the floor,
schedules the dead-man timer, coalesces re-ducks, ignores when not playing.

- [ ] **Step 1: Write the failing tests** — add to `tests/test_interaction.py`:

```python
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
        self.assertAlmostEqual(FakeTimer.created[0].interval, 45.0)  # 45000ms -> 45s
```

- [ ] **Step 2: Run, verify fail**

Run: `python tests/test_interaction.py`
Expected: FAIL — `NotImplementedError` from `_duck`.

- [ ] **Step 3: Implement** — replace `_duck` in `interaction.py`:

```python
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
```

- [ ] **Step 4: Run, verify pass**

Run: `python tests/test_interaction.py`
Expected: PASS (duck tests). (`_restore` still raises but no duck test calls it directly; `_auto_restore`
is only fired by the fake timer in Task 5.)

- [ ] **Step 5: Commit**

```bash
git add interaction.py tests/test_interaction.py
git commit -m "feat(resolver): interaction duck (snapshot + volume_set + coalesce + dead-man arm)"
```

---

### Task 4: Restore (with last-writer-wins)

**Files:** Modify `interaction.py` (`_restore`); Modify `tests/test_interaction.py`.

**Interfaces — Produces:** `_restore` restores the snapshot volume unless the user changed volume
mid-interaction (last-writer-wins); no-op when no snapshot; cancels the dead-man timer.

- [ ] **Step 1: Write the failing tests** — add to `tests/test_interaction.py`:

```python
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
```

- [ ] **Step 2: Run, verify fail**

Run: `python tests/test_interaction.py`
Expected: FAIL — `NotImplementedError` from `_restore`.

- [ ] **Step 3: Implement** — replace `_restore` in `interaction.py`:

```python
    def _restore(self, ctx, zone, rid):
        with self._lock:
            snap = self._snaps.pop(zone, None)
        if snap is None:
            return cr.ok(self.name, rid, "Nothing to restore.", spoken_text=None,
                         metadata={"restored": False, "reason": "no_snapshot", "zone": zone})
        if snap.get("timer") is not None:
            try:
                snap["timer"].cancel()
            except Exception:
                pass
        floor = int(getattr(ctx.settings, "interaction_floor", 15)) / 100.0
        cur = None
        try:
            state = ctx.ha.get_entity_state(zone) or {}
            cur = (state.get("attributes") or {}).get("volume_level")
        except Exception:
            cur = None
        # last-writer-wins: if the current volume is no longer our floor, the user changed it -> keep it.
        if cur is not None and abs(cur - floor) > 0.01:
            LOG.info("RESTORE req=%s zone=%s user_override cur=%s (kept)", rid, zone, cur)
            return cr.ok(self.name, rid, "Kept.", spoken_text=None,
                         metadata={"restored": False, "reason": "user_override", "zone": zone})
        target = snap.get("volume")
        if target is None:
            return cr.ok(self.name, rid, "Nothing to restore.", spoken_text=None,
                         metadata={"restored": False, "reason": "no_baseline", "zone": zone})
        ctx.ha.call_service("media_player", "volume_set",
                            {"entity_id": zone, "volume_level": target})
        LOG.info("RESTORE req=%s zone=%s -> %s", rid, zone, target)
        return cr.ok(self.name, rid, "Restored.", spoken_text=None,
                     metadata={"restored": True, "to": target, "zone": zone})
```

- [ ] **Step 4: Run, verify pass**

Run: `python tests/test_interaction.py`
Expected: PASS (all duck + restore tests).

- [ ] **Step 5: Commit**

```bash
git add interaction.py tests/test_interaction.py
git commit -m "feat(resolver): interaction restore (last-writer-wins + timer cancel)"
```

---

### Task 5: Dead-man timeout auto-restore

**Files:** Modify `tests/test_interaction.py` (behavior already implemented in Task 3/4).

**Interfaces — Consumes:** `_auto_restore`, `FakeTimer.fire()`.

- [ ] **Step 1: Write the failing test** — add to `tests/test_interaction.py`:

```python
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
```

- [ ] **Step 2: Run, verify pass** (implementation from Tasks 3–4 already supports it)

Run: `python tests/test_interaction.py`
Expected: PASS. (If it fails, the bug is in `_arm_timer` passing `[ctx, zone]` or `_auto_restore`
delegating to `_restore` — fix there.)

- [ ] **Step 3: Commit**

```bash
git add tests/test_interaction.py
git commit -m "test(resolver): dead-man timeout auto-restore"
```

---

### Task 6: Register in core + dispatch (silent)

**Files:** Modify `core.py`; Modify `tests/test_interaction.py`.

**Interfaces — Produces:** `"interaction"` routable via `core.dispatch(ctx, "interaction", {"mode": …})`,
silent (never calls `ctx.speaker.speak`).

- [ ] **Step 1: Write the failing tests** — add to `tests/test_interaction.py`:

```python
import core   # add to imports at top of file


class FakeSpeaker(object):
    def __init__(self): self.said = []
    def speak(self, text):
        if text: self.said.append(text)


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
```

Note: `FakeSettings` in this file has no `announce_failures`; add `announce_failures = True` to it so
`core.dispatch` (which reads it on the error path) is safe. Since duck returns `ok` with
`spoken_text=None`, nothing is spoken regardless.

- [ ] **Step 2: Run, verify fail**

Run: `python tests/test_interaction.py`
Expected: FAIL — `test_interaction_registered_in_caps_not_stubs` (`"interaction"` not in `core.CAPS`).

- [ ] **Step 3: Implement** — in `core.py`:

Add the import (line 4, extend the existing import list):
```python
import music, radio, status, news, interaction, capability, command_result as cr
```

Register in `CAPS`:
```python
CAPS = {
    "music": music.MusicCapability(),
    "radio": radio.RadioCapability(),
    "status": status.StatusCapability(),
    "news": news.NewsCapability(),
    "interaction": interaction.InteractionCapability(),
}
```

Also correct the stale comment at `core.py:8` — it claims "re-instantiated per call via capability.run",
but `dispatch` reuses the singleton `CAPS[intent]`, and `InteractionCapability` deliberately holds per-zone
snapshot state on that singleton. Replace with:
```python
# Capability registry (singletons; dispatch reuses one instance per intent — InteractionCapability keeps state)
```

- [ ] **Step 4: Run, verify pass**

Run: `python tests/test_interaction.py`
Expected: PASS (all classes).

- [ ] **Step 5: Full-suite regression**

Run: `python -m unittest discover -s tests -p "test_*.py"` (from the resolver dir)
Expected: PASS — no regressions in existing modules (music/radio/status/news/core/etc.).

- [ ] **Step 6: Commit**

```bash
git add core.py tests/test_interaction.py
git commit -m "feat(resolver): register interaction capability in core dispatch"
```

---

## Round-2 review fixes (opus adversarial review, 2026-07-14)

A whole-branch adversarial pass found the volume writes fragile: they ride the shared event
WebSocket (unverified, reconnect-fragile), and `_restore` discards the baseline *before* the write is
confirmed — so any failed/rejected restore write strands the ceiling at the floor. Fixes below collapse
review findings #1/#3/#4/#5/#6/#7/#8 into one write-path rewrite. #2 (restart-while-ducked) is handled
operationally (see Deployment), not persisted.

### Invariants (Round 2)
- **Writes go via a fresh REST call** (`POST /api/services/media_player/volume_set`), status-checked —
  never the event WebSocket. `ctx.ha` is read-only for event subscription (`resolver.py:118-119`); this
  mirrors `get_entity_state`'s fresh-connection idiom and removes the concurrent-send, `cmd_id`-vs-subscribe,
  and reconnect hazards.
- **Duck**: write the floor first; record the snapshot + arm the dead-man only after the write succeeds.
  Coalesce keeps the original baseline. Duck target = `min(current, floor)` (never raise volume). Store the
  *applied target* in the snapshot.
- **Restore**: peek the snapshot (don't pop); compare current volume against the *applied target* (not the
  config floor) for user-override; write first, and discard the snapshot + cancel the timer only after the
  write succeeds. On write failure, keep the snapshot and leave the dead-man armed to retry.
- **Duck and restore for a zone are mutually exclusive** — hold `_lock` across the whole read→decide→write.
  The REST calls are bounded by a short timeout; serializing one ceiling zone is free.

### Task 7: Round-2 write-path hardening (#1, #3, #4, #5, #6, #7, #8)

**Files:** Modify `haconn.py` + `tests/test_haconn.py`; Modify `interaction.py` + `tests/test_interaction.py`.

- [ ] **Step 1: haconn — failing test then implement** `HA.call_service_rest`:

```python
    def call_service_rest(self, domain, service, data):
        """Call an HA service over a FRESH REST connection (POST /api/services/<d>/<s>).

        Like get_entity_state: fresh per-call HTTPConnection, safe from any thread, never touches the
        shared event WebSocket self.s, raises on non-2xx so callers confirm the write before discarding
        state. Never logs the token.
        """
        conn = http.client.HTTPConnection(self.host, self.port, timeout=5)
        try:
            headers = {"Authorization": "Bearer " + (self.token or ""),
                       "Content-Type": "application/json"}
            conn.request("POST", "/api/services/" + domain + "/" + service,
                         body=json.dumps(data).encode("utf-8"), headers=headers)
            resp = conn.getresponse(); resp.read()
            if resp.status not in (200, 201):
                raise IOError("HA REST POST services/%s/%s -> HTTP %s" % (domain, service, resp.status))
        finally:
            try:
                conn.close()
            except Exception:
                pass
```
  Test it the same way `test_haconn.py` already exercises `get_entity_state` (mock
  `http.client.HTTPConnection`): assert POST, path `/api/services/media_player/volume_set`, Bearer header,
  raises on non-2xx, and `ha.s` is never touched.

- [ ] **Step 2: interaction — failing tests then rewrite** `_duck`/`_arm_timer`/`_cancel_timer`/`_auto_restore`/`_restore`:

```python
    def _duck(self, ctx, zone, rid):
        floor = int(getattr(ctx.settings, "interaction_floor", 15)) / 100.0
        with self._lock:
            state = ctx.ha.get_entity_state(zone) or {}
            player_state = state.get("state")
            vol = (state.get("attributes") or {}).get("volume_level")
            if player_state != "playing" and getattr(ctx.settings, "interaction_ignore_when_idle", True):
                return cr.ok(self.name, rid, "Nothing to duck.", spoken_text=None,
                             metadata={"ducked": False, "reason": "not_playing", "zone": zone})
            if vol is None:
                return cr.ok(self.name, rid, "Nothing to duck.", spoken_text=None,
                             metadata={"ducked": False, "reason": "no_volume", "zone": zone})
            target = min(vol, floor)                                   # never duck upward (#7)
            ctx.ha.call_service_rest("media_player", "volume_set",     # write first, verified
                                     {"entity_id": zone, "volume_level": target})
            if zone not in self._snaps:                                # coalesce: keep original baseline
                self._snaps[zone] = {"volume": vol, "target": target, "ts": self._clock(), "timer": None}
            self._arm_timer(ctx, zone)
            LOG.info("DUCK req=%s zone=%s %s -> %s", rid, zone, vol, target)
            return cr.ok(self.name, rid, "Ducked.", spoken_text=None,
                         metadata={"ducked": True, "from": vol, "to": target, "zone": zone})

    def _arm_timer(self, ctx, zone):
        snap = self._snaps.get(zone)
        if snap is None:
            return
        self._cancel_timer(snap)
        secs = int(getattr(ctx.settings, "max_duck_timeout", 120000)) / 1000.0   # fallback 120s (#6)
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
        except Exception as e:                                         # write failed -> keep + retry
            LOG.error("auto-restore failed zone=%s: %r; re-arming", zone, e)
            with self._lock:
                if zone in self._snaps:
                    self._arm_timer(ctx, zone)

    def _restore(self, ctx, zone, rid):
        with self._lock:
            snap = self._snaps.get(zone)                              # peek; discard only after write
            if snap is None:
                return cr.ok(self.name, rid, "Nothing to restore.", spoken_text=None,
                             metadata={"restored": False, "reason": "no_snapshot", "zone": zone})
            cur = None
            try:
                state = ctx.ha.get_entity_state(zone) or {}
                cur = (state.get("attributes") or {}).get("volume_level")
            except Exception:
                cur = None
            applied = snap.get("target")
            # last-writer-wins vs the value WE set (not the config floor) -> honors min()/#7
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
```

  Update `FakeHA` to route `call_service_rest` into `.calls` and accept a `write_boom` to simulate a
  failing write. Existing duck/restore tests keep working (same `.calls` shape). **Add tests** (finding → test):
    - #7: baseline 0.10, floor 0.15 → write 0.10 (not 0.15); snapshot `target` == 0.10.
    - #1: `write_boom` on restore → result `ok:False`, snapshot **still present**, dead-man timer **not** cancelled.
    - #6: settings object lacking `max_duck_timeout` → armed interval == 120.0.
    - #5: probe `call_service_rest` asserting `cap._lock.locked()` is True during the write (proves
      duck/restore run under the lock → mutually exclusive).

- [ ] **Step 3: full-suite regression** — `python -m unittest discover -s tests -p "test_*.py"` → OK.
- [ ] **Step 4: Commit** — `git commit -m "fix(resolver): verified fresh-REST interaction writes; restore-after-confirm; no upward duck"`

### BACKLOG follow-up (#2)
Snapshots + the dead-man timer are in-memory; a resolver restart *while a duck is active* loses both and
strands the ceiling at the floor (self-correcting on the next volume/play command). Handled operationally
via the Deployment precondition below; snapshot **persistence is deferred** — the stale-baseline risk of
restoring across a restart outweighs the self-correcting annoyance. Revisit only if it recurs.

## Round-3 review fixes (PR #18 multi-specialist review, 2026-07-15)

The Round-2 rework closed the adversarial findings but introduced **two strand-at-floor
regressions** (the exact failure this capability exists to prevent), plus two silent-failure
gaps. All confirmed against source by multiple reviewers.

### Invariants (Round 3, additive)
- **Duck records the snapshot + arms the dead-man BEFORE the volume write** (symmetry with
  restore's write-before-discard). A failed/lost-ack write is then always recoverable: the
  dead-man later sees `cur == baseline`, treats it as `user_override`, and cleans up.
- **`snap["target"]` = the last value we actually wrote** — updated on *every* duck (first or
  coalesced); `snap["volume"]` (the restore baseline) is captured once on the first duck.
  Override detection compares live volume to `snap["target"]`.
- **Self-healing never lets an exception escape the Timer thread** — the `_auto_restore` re-arm
  is itself wrapped.
- **Read failures during restore are logged (WARNING), never silent.**
- **I/O stays under `_lock`** (deliberate — it's the Round-2 #5 mutual-exclusion guarantee;
  do not move it out).

### Task 8: Round-3 strand-at-floor fixes (C1, C2, F3, F5)

**Files:** Modify `interaction.py` + `tests/test_interaction.py`.

- [ ] **Step 1 (C1 + C2): reorder `_duck` — snapshot/arm before write; sync target on re-duck:**

```python
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
```

- [ ] **Step 2 (F3): wrap the `_auto_restore` re-arm** so a re-arm failure can't kill the Timer thread:

```python
    def _auto_restore(self, ctx, zone):
        LOG.warning("DUCK dead-man timeout: auto-restoring zone=%s", zone)
        try:
            self._restore(ctx, zone, "deadman")
        except Exception as e:
            LOG.error("auto-restore failed zone=%s: %r; re-arming", zone, e)
            try:
                with self._lock:
                    if zone in self._snaps:
                        self._arm_timer(ctx, zone)
            except Exception as e2:
                LOG.error("auto-restore re-arm failed zone=%s: %r", zone, e2)
```

- [ ] **Step 3 (F5): log the restore read failure** (keep fail-safe behavior, lose the silence):

```python
            try:
                state = ctx.ha.get_entity_state(zone) or {}
                cur = (state.get("attributes") or {}).get("volume_level")
            except Exception as e:
                LOG.warning("RESTORE req=%s zone=%s read failed (%r); restoring baseline", rid, zone, e)
                cur = None
```

- [ ] **Step 4: comments** — fix the `_snaps` schema comment to include `target`
  (`# zone -> {"volume": baseline, "target": last-written, "ts": float, "timer": obj|None}`); add a one-line
  note that the read+write stay under `_lock` intentionally (Round-2 #5 serialization); drop the bare `#N`
  finding refs from code comments (keep self-contained prose).

- [ ] **Step 5: tests** (all must fail first where applicable):
    - **C2 regression:** duck at 0.40 (target 0.15) → simulate user drop to 0.05 → re-duck (writes 0.05,
      `target` now 0.05) → restore → reaches **baseline 0.40** (not a false `user_override`).
    - **C1:** first-duck write raises after snapshot/arm → snapshot **present**, timer armed; a subsequent
      dead-man/`restore` cleans up (no permanent strand).
    - **Real threading:** two threads, one holding `_lock` inside a blocking `call_service_rest` (gated by an
      `Event`), the other's duck/restore must block until released — proves mutual exclusion (not the
      single-threaded `_lock.locked()` probe).
    - **Re-arm loop:** `_auto_restore` write fails once → re-arms → second fire succeeds → snapshot cleared.
    - **Behavioral asserts:** `user_override` path cancels the timer + pops the snapshot; `get_entity_state`
      raising mid-restore still restores baseline (with the new WARNING).

- [ ] **Step 6: full-suite regression** — `python -m unittest discover -s tests -p "test_*.py"` → OK.
- [ ] **Step 7: Commit** — `git commit -m "fix(resolver): duck snapshots before write; sync coalesce target; guard self-heal paths"`

### BACKLOG follow-up (#2, sharpened)
The "deploy-when-idle" mitigation covers **planned** deploys only; an **unplanned** crash/OOM/reboot during
the ≤120 s ducked window still strands (silently, low probability). Persistence remains deferred; if this
class recurs, a persist-baseline-and-reconcile-on-startup would neutralize it (and the C1 lost-ack case) at once.

## Deployment (gated — NOT part of this plan's code)

Implementation above is **branch-only and ungated**. Shipping it is a **separate live step requiring
explicit user approval** and claims the single live gate (BACKLOG §10), following the resolver deploy
pattern in `CHANGELOG.md`:
0. **Precondition (Round-2 #2):** deploy/restart only when no interaction is active (verify
   `assist_satellite` idle) — a restart mid-duck loses the in-memory snapshot + dead-man timer and strands
   the ceiling at the floor.
1. Deploy `haconn.py`, `config.py`, `config.json`, `interaction.py`, `core.py` to host `~/mass-resolver/`
   (timestamped backup dir; checksum; `py_compile` on host Python 3.5.2).
2. Restart the resolver service (**user-run sudo**), confirm active + 0 tracebacks.
3. Live-validate `/command` `intent=interaction {mode:duck}` ducks the ceiling and `{mode:restore}`
   restores; confirm silence (no TTS); confirm no regression to music/radio/news/status.
4. **Then** the S1a HA automation (satellite state → `interaction` intent) is wired — separate S1a change.

## Self-review notes

- **Coverage:** AU-01 §5 duck (Task 3), §6 restore + edge cases — user-override/last-writer-wins (Task 4),
  coalesce (Task 3), dead-man/resolver-safety (Task 5). Ignore-when-idle (Task 3). Tunables (Task 1).
- **Deferred (YAGNI):** `fade_ms` config key reserved but no fade in v1 (single `volume_set`); pause-mode
  (AU-01 §4 fallback) not built — duck-only per S1a. Both noted for a follow-up if validation needs them.
- **No placeholders:** every step has runnable code + exact commands + expected output.
- **Silent by construction:** all results `spoken_text=None`; Task 6 asserts dispatch never speaks.
- **Concurrency (review #1):** Task 0 adds a `haconn` send lock so the dead-man's off-thread `call_service`
  can't interleave `sendall` with a concurrent `/command`; Task 3/4 add a capability lock for `_snaps`.
- **Dead-man vs long replies (review #2, cross-ref S1a):** default `max_duck_timeout` = **120000 ms** so a
  single duck survives long replies (news, long ChatGPT answers). **S1a's automation SHOULD also re-fire
  `duck` on each intermediate `assist_satellite` transition** — the coalesce path re-arms the timer
  (`_arm_timer`), refreshing the dead-man for free. This plan and the S1a design must agree on who keeps it
  alive; **follow-up: add this cross-reference to the S1a design doc.**
- **Unrestorable duck (review #3):** playing-but-`volume_level=None` → don't duck (Task 3), so we never
  strand the zone at the floor.
