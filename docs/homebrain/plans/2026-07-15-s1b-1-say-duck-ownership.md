# S1b-1 — Resolver `say` + Duck-Ownership Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use `superpowers:subagent-driven-development` (recommended)
> or `superpowers:executing-plans`. Steps use `- [ ]` checkboxes.

**Goal:** add a `say` mode to the resolver's `interaction` capability that plays a given audio **URI** on the
ceiling zone as an **overlay announcement** and — per the duck-ownership ADR (Option H) — **owns the duck
lifetime for reply turns**: it holds the active S1a duck, then issues restore when the reply finishes
(duration-hold), while an incoming `restore` (the future satellite `idle` trigger) **defers** to it.

**Architecture:** extend the existing `InteractionCapability` (not a new capability) so `say` shares the
singleton's `_snaps`/`_lock` and composes with the deployed AU-02/03 duck/restore (coalesce, last-writer-wins,
120 s dead-man, pop-after-confirm). `say` uses a **new playback primitive** — `media_player.play_media`
with `announce: true` over the existing `haconn.call_service_rest` (fresh REST) — **not** `tts.speak`
(no synthesis; the URI is already-rendered audio). Restore-on-playback-end uses a **duration-hold timer**
(the ADR's robust primary given the Universal→Squeezelite player's weak announce-state observability).

**Tech Stack:** Python 3.5 (host runs 3.5.2), stdlib `unittest`, resolver modules under
`docs/homebrain/mass-resolver/`.

## Global Constraints

- **Python 3.5 only:** no f-strings, no type hints, no `async`/`await`, no `_` numeric separators
  (`8000` not `8_000`), no `dataclasses`. Use `%`/`.format()`.
- **Tests:** stdlib `unittest`; extend `tests/test_interaction.py`; run from the resolver dir. Follow the
  existing `FakeHA`/`FakeSettings`/`FakeCtx`/`FakeTimer` style already in that file.
- **Resolver-only:** **no firmware, no pipeline, no HA-automation change** — those are **S1b-2**. S1b-1 is
  validated by driving `/command` directly with a **test URI**.
- **No new TTS path:** `say` plays a pre-rendered URI via `play_media(announce=true)`; it never synthesizes.
  Resolver stays sole TTS/media owner. All `say` results are `spoken_text=None` (it *is* the audio path).
- **No deploy in this plan.** Code + tests land on the branch (ungated). Host deploy to `~/mass-resolver`
  + restart + the **Spike 2** live validation is a **separate, approval-gated step** (see "Deployment").
- **Volume levers unchanged:** `volume_set` / `play_media` only — never `volume_mute`, never `media_stop`.
- **Working dir for all commands:** `docs/homebrain/mass-resolver/`.

## File structure

- **Modify:** `interaction.py` — add `say` to `_MODES`, `uri`/`hold_ms` to `resolve`, `say` validation,
  `execute` routing, and `_say` / `_arm_reply_timer` / `_reply_complete` + a `reply_active` deferral guard in
  `_restore`. Generalize `_arm_timer` to accept an optional interval.
- **Modify:** `config.py` — add `say_hold_default_ms`, `say_margin_ms` to `Settings.__init__`.
- **Modify:** `config.json` — the two tunables (deployed config).
- **Modify:** `tests/test_interaction.py` — new tests.
- **No `core.py` change** — `interaction` is already registered in `CAPS`; `say` is a new mode of it.

**Interfaces produced:**
- `interaction` intent gains `mode="say"`, params `{uri|media_content_id: <url>, zone: <entity, default ceiling>, hold_ms?: int}`.
- `CommandResult.metadata` for say: `said`(bool), `held`(bool), `zone`(str); on failure the usual `err`.
- `_restore` gains a `reply_active` deferral branch → metadata `{restored: False, reason: "reply_active"}`.
- Config: `settings.say_hold_default_ms` (int ms), `settings.say_margin_ms` (int ms).

---

### Task 1: Config tunables

**Files:** Modify `config.py:Settings.__init__`; Modify `config.json`; Test `tests/test_config.py`.

- [ ] **Step 1: Failing test** — append to `tests/test_config.py`:

```python
class SayTunablesTest(unittest.TestCase):
    def test_defaults(self):
        s = config.Settings({})
        self.assertEqual(s.say_hold_default_ms, 8000)
        self.assertEqual(s.say_margin_ms, 1500)

    def test_overrides(self):
        s = config.Settings({"say_hold_default_ms": 5000, "say_margin_ms": 500})
        self.assertEqual(s.say_hold_default_ms, 5000)
        self.assertEqual(s.say_margin_ms, 500)
```

- [ ] **Step 2: Run, verify fail** — `python tests/test_config.py` → FAIL (`no attribute 'say_hold_default_ms'`).

- [ ] **Step 3: Implement** — in `config.py`, at the end of `Settings.__init__`:

```python
        # S1b-1 say (ceiling reply) tunables
        self.say_hold_default_ms = int(cfg.get("say_hold_default_ms", 8000))   # duration-hold when clip length unknown
        self.say_margin_ms = int(cfg.get("say_margin_ms", 1500))               # added to the hold before restore
```

- [ ] **Step 4: Deployed config** — in `config.json`, near the interaction keys:

```json
  "say_hold_default_ms": 8000,
  "say_margin_ms": 1500,
```

- [ ] **Step 5: Run, verify pass** — `python tests/test_config.py` → PASS.

- [ ] **Step 6: Commit (code + runtime config separately, per CLAUDE.md)**

```bash
git add config.py tests/test_config.py
git commit -m "feat(resolver): add say hold/margin tunables"
git add config.json
git commit -m "config(resolver): say hold/margin tunable values"
```

---

### Task 2: `say` resolve + validate

**Files:** Modify `interaction.py`; Modify `tests/test_interaction.py`.

**Interfaces — Produces:** `mode="say"` accepted; `uri` resolved from `uri` or `media_content_id`; `say`
requires a non-empty `uri`.

- [ ] **Step 1: Failing tests** — add to `tests/test_interaction.py`:

```python
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
```

- [ ] **Step 2: Run, verify fail** — `python tests/test_interaction.py` → FAIL (`say` not a valid mode / no `uri`).

- [ ] **Step 3: Implement** — in `interaction.py`: extend `_MODES`, `resolve`, `validate`, `execute`:

```python
_MODES = ("duck", "restore", "say")
```
```python
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

    # implemented in Task 3
    def _say(self, ctx, resolved, rid):
        raise NotImplementedError
```

- [ ] **Step 4: Run, verify pass** — `python tests/test_interaction.py` → PASS (resolve/validate; `test_say_without_uri_rejected` passes because `validate` short-circuits before `_say`). Existing duck/restore tests still pass (they don't pass `uri`; `resolve` just adds `uri=""`/`hold_ms=None`, unused by duck/restore).

- [ ] **Step 5: Commit**

```bash
git add interaction.py tests/test_interaction.py
git commit -m "feat(resolver): interaction say mode resolve/validate (uri)"
```

---

### Task 3: `_say` playback + duck-ownership (the core)

**Files:** Modify `interaction.py`; Modify `tests/test_interaction.py`.

**Interfaces — Produces:** `_say` plays the URI via `play_media(announce=true)`; if a duck snapshot exists it
sets `reply_active`, arms a **reply timer** (duration-hold) that restores on playback-end; if no snapshot it
just plays (held:False). `_restore` **defers** while `reply_active`. `_arm_timer` gains an optional interval.

- [ ] **Step 1: Failing tests** — add to `tests/test_interaction.py` (extend `FakeHA` first so it records
  `play_media`; it already records `call_service_rest` into `.calls`, so `play_media` lands there too):

```python
class SayTest(unittest.TestCase):
    def setUp(self):
        FakeTimer.created = []
        self.cap = interaction.InteractionCapability(timer_factory=FakeTimer, clock=lambda: 1000.0)
        self.zone = "media_player.ceiling_speakers"

    def test_say_plays_uri_as_announcement(self):
        ha = FakeHA(playing(0.40)); ctx = FakeCtx(ha)
        r = run(self.cap, ctx, {"mode": "say", "uri": "http://x/a.flac"})
        self.assertTrue(r["ok"]); self.assertIsNone(r["spoken_text"])
        self.assertTrue(r["metadata"]["said"])
        dom, svc, data = ha.calls[-1]
        self.assertEqual((dom, svc), ("media_player", "play_media"))
        self.assertEqual(data["entity_id"], self.zone)
        self.assertEqual(data["media_content_id"], "http://x/a.flac")
        self.assertTrue(data["announce"])

    def test_say_without_active_duck_does_not_hold(self):
        ha = FakeHA(playing(0.40)); ctx = FakeCtx(ha)           # no prior duck -> no snapshot
        r = run(self.cap, ctx, {"mode": "say", "uri": "http://x/a.flac"})
        self.assertTrue(r["ok"]); self.assertFalse(r["metadata"]["held"])
        self.assertEqual(len(FakeTimer.created), 0)             # no reply timer armed

    def test_say_during_duck_holds_and_arms_reply_timer(self):
        ha = FakeHA(playing(0.40)); ctx = FakeCtx(ha)
        run(self.cap, ctx, {"mode": "duck"})                    # snapshot 0.40, dead-man armed
        ha._state = playing(0.15); ha.calls = []; FakeTimer.created = []
        r = run(self.cap, ctx, {"mode": "say", "uri": "http://x/a.flac", "hold_ms": 4000})
        self.assertTrue(r["metadata"]["held"])
        self.assertTrue(self.cap._snaps[self.zone]["reply_active"])
        self.assertEqual(len(FakeTimer.created), 1)             # reply timer replaces the dead-man
        self.assertAlmostEqual(FakeTimer.created[0].interval, 5.5)   # 4000 + 1500 margin -> 5.5s

    def test_restore_defers_while_reply_active(self):
        ha = FakeHA(playing(0.40)); ctx = FakeCtx(ha)
        run(self.cap, ctx, {"mode": "duck"})
        ha._state = playing(0.15)
        run(self.cap, ctx, {"mode": "say", "uri": "http://x/a.flac"})
        ha.calls = []
        r = run(self.cap, ctx, {"mode": "restore"})             # simulates the future idle trigger
        self.assertFalse(r["metadata"]["restored"])
        self.assertEqual(r["metadata"]["reason"], "reply_active")
        self.assertIn(self.zone, self.cap._snaps)               # NOT restored yet
        self.assertEqual(ha.calls, [])                          # no volume write

    def test_reply_timer_restores_baseline_on_playback_end(self):
        ha = FakeHA(playing(0.40)); ctx = FakeCtx(ha)
        run(self.cap, ctx, {"mode": "duck"})                    # snapshot 0.40
        ha._state = playing(0.15)
        run(self.cap, ctx, {"mode": "say", "uri": "http://x/a.flac"})
        ha.calls = []
        FakeTimer.created[-1].fire()                            # playback-end
        self.assertNotIn(self.zone, self.cap._snaps)            # cleared
        vol_writes = [c for c in ha.calls if c[1] == "volume_set"]
        self.assertEqual(len(vol_writes), 1)
        self.assertAlmostEqual(vol_writes[0][2]["volume_level"], 0.40)   # restored baseline

    def test_barge_in_rearms_reply_timer_keeps_baseline(self):
        ha = FakeHA(playing(0.40)); ctx = FakeCtx(ha)
        run(self.cap, ctx, {"mode": "duck"})
        ha._state = playing(0.15)
        run(self.cap, ctx, {"mode": "say", "uri": "http://x/a.flac"})
        first = FakeTimer.created[-1]
        run(self.cap, ctx, {"mode": "say", "uri": "http://x/b.flac"})   # barge-in
        self.assertTrue(first.cancelled)                        # old reply timer cancelled
        self.assertAlmostEqual(self.cap._snaps[self.zone]["volume"], 0.40)   # baseline preserved
```

- [ ] **Step 2: Run, verify fail** — `python tests/test_interaction.py` → FAIL (`NotImplementedError` from `_say`).

- [ ] **Step 3: Implement** — in `interaction.py`, replace the `_say` stub and generalize `_arm_timer`; add
  `_arm_reply_timer` and `_reply_complete`; add the `reply_active` guard to `_restore`:

```python
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

    def _say(self, ctx, resolved, rid):
        zone = resolved["zone"]; uri = resolved["uri"]
        with self._lock:
            ctx.ha.call_service_rest("media_player", "play_media",
                                     {"entity_id": zone, "media_content_id": uri,
                                      "media_content_type": "music", "announce": True})
            snap = self._snaps.get(zone)
            if snap is None:                                   # music wasn't ducked -> just play the reply
                LOG.info("SAY req=%s zone=%s uri=%s (no active duck)", rid, zone, uri)
                return cr.ok(self.name, rid, "Said.", spoken_text=None,
                             metadata={"said": True, "held": False, "zone": zone})
            snap["reply_active"] = True                        # reply turn: hold the duck until playback ends
            margin = int(getattr(ctx.settings, "say_margin_ms", 1500))
            hold = resolved.get("hold_ms")
            hold = (int(hold) if hold is not None
                    else int(getattr(ctx.settings, "say_hold_default_ms", 8000))) + margin
            self._arm_reply_timer(ctx, zone, hold / 1000.0)
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
```

  And add the guard at the top of `_restore`, immediately after the `snap is None` check:

```python
            if snap.get("reply_active"):                       # a ceiling reply is playing; the reply timer owns restore
                LOG.info("RESTORE req=%s zone=%s deferred (reply active)", rid, zone)
                return cr.ok(self.name, rid, "Deferred.", spoken_text=None,
                             metadata={"restored": False, "reason": "reply_active", "zone": zone})
```

- [ ] **Step 4: Run, verify pass** — `python tests/test_interaction.py` → PASS (all say + existing duck/restore/dead-man tests).

- [ ] **Step 5: Commit**

```bash
git add interaction.py tests/test_interaction.py
git commit -m "feat(resolver): interaction say (play URI overlay) + duck-ownership (reply-active hold, restore-on-playback-end, deferred restore)"
```

---

### Task 4: Dispatch (silent) + full-suite regression

**Files:** Modify `tests/test_interaction.py`.

**Interfaces — Produces:** `say` routable via `core.dispatch(ctx, "interaction", {"mode":"say","uri":…})`, silent.

- [ ] **Step 1: Failing test** — add to `tests/test_interaction.py` (reuses the file's `FakeSpeaker`/`core` imports):

```python
class SayDispatchTest(unittest.TestCase):
    def test_dispatch_say_is_silent(self):
        ha = FakeHA(playing(0.40)); spk = FakeSpeaker()
        ctx = core.Ctx(ma_factory=lambda: None, ha=ha, settings=FakeSettings(),
                       radio_cfg={}, news_cfg={}, speaker=spk)
        r = core.dispatch(ctx, "interaction", {"mode": "say", "uri": "http://x/a.flac"})
        self.assertTrue(r["ok"]); self.assertEqual(r["intent"], "interaction")
        self.assertTrue(r["metadata"]["said"])
        self.assertEqual(spk.said, [])                          # silent: no TTS
```

Note: `FakeSettings` in this file needs `say_hold_default_ms`/`say_margin_ms`; add them (e.g. `8000`/`1500`)
so `_say`'s `getattr` uses real ints in the no-`hold_ms` path.

- [ ] **Step 2: Run, verify fail (or pass)** — `python tests/test_interaction.py`. If `FakeSettings` lacks the
  attrs the getattr fallback still yields ints, so this may pass immediately; the assertion that matters is
  `spk.said == []`.

- [ ] **Step 3: Full-suite regression** — from the resolver dir:

Run: `python -m unittest discover -s tests -p "test_*.py"`
Expected: PASS — no regressions (music/radio/status/news/core/haconn/interaction).

- [ ] **Step 4: Commit**

```bash
git add tests/test_interaction.py
git commit -m "test(resolver): interaction say dispatch is silent"
```

---

## Deployment + Spike 2 (gated — NOT part of this plan's code)

Branch-only and ungated above. Shipping + validating is a **separate live step requiring explicit approval**;
it claims the single live gate (BACKLOG §10) and follows `runbooks/resolver-deploy.md`.

1. Deploy `interaction.py`, `config.py`, `config.json` to `~/mass-resolver/` (timestamped backup; host
   `py_compile` on 3.5.2; the changed test files for the on-host parity run). Restart (user-run sudo).
2. **Spike 2 — live go/no-go** (this is what S1b-1 must prove; with music playing on the ceiling):
   - `POST /command interaction {mode: duck}` → ceiling to floor (0.15).
   - `POST /command interaction {mode: say, uri: <a reachable test audio URL>, hold_ms: <clip length>}` →
     confirm: (a) the clip **overlays** (music keeps playing, doesn't stop) and MA **auto-reverts to the live
     floor 0.15**, not a stale value; (b) whether MA gives a **completion signal** or we must rely on the
     duration-hold (this plan assumes duration-hold — the robust default); (c) the **test URI is fetchable by
     MA** and long-lived (internal-URL/LAN + TTS-cache-TTL, S0 §5). Use a **host-hosted** URL first to isolate
     the announce mechanics from the TTS-cache question, then an HA `/api/tts_proxy/...` URL.
   - After `hold_ms + say_margin_ms`, confirm the resolver **restores to 0.40** (reply timer fired).
   - `POST /command interaction {mode: restore}` **while the reply is playing** → confirm it returns
     `deferred/reply_active` and does **not** un-duck.
   - Barge-in: a second `say` mid-reply → old reply timer cancelled, new clip plays, restore after the latest.
3. If Spike 2 shows announce does **not** overlay/revert cleanly, or the URI isn't fetchable/long-lived →
   **stop**; that's the S1b go/no-go and feeds back into the design before S1b-2.

## Self-review notes

- **ADR coverage:** reply-active hold + restore-on-playback-end (Task 3 `_say`/`_arm_reply_timer`/
  `_reply_complete`); duration-hold detection (Task 1 tunables + Task 3); deferred `idle→restore` (Task 3
  `_restore` guard); barge-in interrupt (Task 3 test); 120 s dead-man retained as failure backstop
  (`_reply_complete` re-arms `_arm_timer` on restore failure). Spike 2 = the three ADR assertions + URI reach.
- **New primitive, not `tts.speak`:** `_say` uses `play_media(announce=true)` — no synthesis (Task 3).
- **Composes with AU-02/03:** shares `_snaps`/`_lock`; coalesce/last-writer-wins/pop-after-confirm in
  `_restore` unchanged except the added `reply_active` deferral at the top.
- **Scope:** resolver-only; no firmware/pipeline/HA-automation (S1b-2). The `idle→restore` *deferral* is
  resolver-side and tested via `/command`; the *automation* that sends `idle→restore`+grace-G is S1b-2.
- **Deferred/YAGNI:** MA completion-signal path (if Spike 2 finds one, swap duration-hold later); dropped-Q&A
  chirp/LED and latency budget are S1b-2 (they need the real pipeline/firmware).

## Post-review fixes (whole-branch reviews, 2026-07-15)

Two strand-at-floor bugs were found by review and fixed on-branch before merge (both had regression tests
added that fail against the pre-fix code):

- **F1 — bad `hold_ms` poisoned `reply_active` (commit `62ff4c6`).** `_say` set `reply_active=True` *before*
  computing `int(hold_ms)`; a non-numeric `hold_ms` raised after the flag was set but before the reply timer
  was armed → flag stuck True, dead-man deferred → permanent strand. Fix: compute the hold **up-front** with a
  `try/except (TypeError, ValueError)` fallback to `say_hold_default_ms`, and **arm-then-flag** (arm the reply
  timer before setting `reply_active`, with `play_media` still first so its failure leaves the dead-man intact).
- **Dead-man vs `reply_active` composition (commit `9e38d82`).** A barge-in `duck` while a reply is active
  re-arms the 120 s dead-man (replacing the reply timer) but does not clear `reply_active`; the dead-man's
  `_restore` then **deferred** (a normal result, not an exception) → no re-arm → strand. Fix: `_restore` gains
  `force=False`; the `reply_active` guard is `and not force`; **`_auto_restore` (the dead-man) passes
  `force=True`** so the ultimate backstop always breaks through, while the external `idle→restore` path still
  defers. (Re-arm-on-deferral was rejected — it would strand-and-loop instead of letting the backstop win.)

**S1b-2 precondition / Spike-2 checks (write down so they aren't silently inherited):**
- S1b-2 must supply a **valid numeric `hold_ms`** for each reply (derived from the reply clip length, e.g.
  `on_tts_end` duration / `Content-Length` / HEAD). The resolver's fallback to `say_hold_default_ms` is a
  **safety net, not the intended path** — a wrong default un-ducks mid-reply (early) or holds too long (late).
- **Spike 2 must confirm** the `say_hold_default_ms` default is adequate for a typical reply, and that S1b-2's
  derived `hold_ms` matches actual playback length within `say_margin_ms`.
