# Speaker Reconnect Bugfix — Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use superpowers:subagent-driven-development (or
> executing-plans) to implement task-by-task. **Design only — do NOT implement until approved**
> (code change + a `sudo systemctl restart mass-resolver` are required).

**Goal:** make the resolver's Speaker recover automatically after its Home Assistant WebSocket dies
(e.g. an HA restart), so Piper announcements resume without a manual resolver restart.

**Architecture:** one-line-of-responsibility change in `haconn.HA.announce()` so send/connection failures
**propagate** instead of being swallowed; `Speaker.speak()`'s existing reconnect-once then heals the
socket. Plus tests that lock the behaviour in.

**Tech Stack:** Python 3.5 (resolver host), `unittest` (existing suite under `tests/`).

## Root cause (recorded)
- An HA restart **killed the Speaker's HA WebSocket**; the next `ws_send` raised `BrokenPipeError(32)`.
- `speaker.py` **has** reconnect-once logic (`Speaker.speak()` retries on exception → new HA + connect).
- **But** `haconn.HA.announce()` wraps the send in `try/except Exception` and **only logs**
  (`ANNOUNCE failed (...)`) — it **never re-raises**. So `Speaker.speak()` sees `announce()` return
  normally, never enters its retry branch, and the dead socket persists for **every** later announce
  (observed: all announces from 20:19 onward failed; the 21:08 restart was the only recovery).
- Net: a latent robustness bug — reconnect-once is dead code because the layer below eats the error.

Evidence: `resolver.log` shows repeated `ERROR ANNOUNCE failed (BrokenPipeError(32, 'Broken pipe'))`
for no-match/status announces across the session, and a clean `ANNOUNCE via tts.speak` only immediately
after each fresh resolver start.

## Global Constraints
- Python 3.5-safe (no f-strings/walrus/`dict|dict`). Match existing `tests/` style (`unittest`,
  dependency injection via fakes; no network in tests).
- **Behaviour-preserving** except for the bug: the "no `tts_service` configured" path and the message
  templating must be unchanged; only **send/connection failures** change from swallowed → propagated.
- Resolver stays sole TTS owner; no change to `core.py`/`speaker.py` public shape. No change to the
  event/HTTP paths, `/command`, or any HA script.
- Additive/reversible; deploy is one file (`haconn.py`) + a user-run service restart; `.f1bak`-style
  backup of the previous `haconn.py` before deploy.

## File Structure
- Modify: `haconn.py` — `HA.announce()` (log **and re-raise** on send failure).
- Modify/Test: `tests/test_haconn.py` — assert `announce()` propagates a send failure; keep existing
  no-op/templating tests green.
- Test: `tests/test_speaker.py` — add an integration test using **real** `haconn.HA` (with `call_service`
  patched to fail-then-succeed) proving reconnect-once recovers, and a both-fail test proving no
  infinite loop.

---

### Task 1: `announce()` propagates send/connection failures

**Files:**
- Modify: `haconn.py:35-53` (`HA.announce`)
- Test: `tests/test_haconn.py`

**Interfaces:**
- Consumes: `HA.call_service(domain, service, data)` (may raise on a dead socket).
- Produces: `HA.announce(message, settings)` — returns `None` on success or no-op; **raises** the
  underlying exception on a send/connection failure (after logging it).

- [ ] **Step 1: Write the failing test** (add to `tests/test_haconn.py`)

```python
    def test_announce_propagates_send_failure(self):
        h = self._ha()
        def boom(domain, service, data):
            raise BrokenPipeError(32, "Broken pipe")
        h.call_service = boom
        s = FakeSettings(tts_service="tts.speak",
                         tts_data={"media_player_entity_id": "{entity}", "message": "{msg}"})
        with self.assertRaises(BrokenPipeError):
            h.announce("hello", s)
```

- [ ] **Step 2: Run it — expect FAIL** (current `announce` swallows the error)

Run: `python tests/test_haconn.py HaConnTest.test_announce_propagates_send_failure`
Expected: FAIL (no exception raised).

- [ ] **Step 3: Implement the fix** — replace `HA.announce` body so the send re-raises after logging:

```python
    def announce(self, message, settings):
        svc = (getattr(settings, "tts_service", "") or "").strip()
        parts = svc.split(".", 1)
        if len(parts) != 2 or not parts[0] or not parts[1]:
            LOG.info("ANNOUNCE (no tts_service configured): %s", message)
            return
        domain, service = parts
        entity = getattr(settings, "ceiling_entity", "") or ""
        data = {}
        for k, v in (getattr(settings, "tts_data", {}) or {}).items():
            if isinstance(v, str):
                data[k] = v.replace("{msg}", message).replace("{entity}", entity)
            else:
                data[k] = v
        try:
            self.call_service(domain, service, data)
            LOG.info("ANNOUNCE via %s: %s", svc, message)
        except Exception as e:
            LOG.error("ANNOUNCE send failed (%r): %s", e, message)
            raise
```

- [ ] **Step 4: Run the whole haconn suite — expect PASS** (new test + the 4 existing ones)

Run: `python tests/test_haconn.py`
Expected: all PASS (no-op + templating behaviour unchanged; send failure now propagates).

- [ ] **Step 5: Commit**

```bash
git add haconn.py tests/test_haconn.py
git commit -m "fix(resolver): announce re-raises send failures so Speaker can reconnect"
```

---

### Task 2: Speaker reconnect-once heals a dropped socket (integration) + no infinite loop

**Files:**
- Test: `tests/test_speaker.py`

**Interfaces:**
- Consumes: real `haconn.HA` instances from a factory; `Speaker.speak(text)`.
- Produces: proof that one dropped socket → exactly one reconnect → success; two dropped → no loop.

- [ ] **Step 1: Write the failing/again-green tests** (add to `tests/test_speaker.py`)

```python
    def test_real_announce_failure_triggers_reconnect(self):
        import haconn
        made = []
        def factory():
            h = haconn.HA("host", 1, "tok"); h.sent = []
            if not made:                       # first HA: send dies (dead socket)
                def boom(domain, service, data):
                    raise BrokenPipeError(32, "Broken pipe")
                h.call_service = boom
            else:                              # reconnect HA: send works
                h.call_service = lambda d, s, dd: h.sent.append((d, s, dd))
            h.connect = lambda: None
            made.append(h)
            return h
        sp = speaker.Speaker(_RealishSettings(), factory)
        sp.speak("hello")
        self.assertEqual(len(made), 2)                 # exactly one reconnect
        self.assertEqual(len(made[1].sent), 1)         # second HA actually announced

    def test_both_attempts_fail_no_infinite_loop(self):
        import haconn
        made = []
        def factory():
            h = haconn.HA("host", 1, "tok")
            def boom(domain, service, data):
                raise BrokenPipeError(32, "Broken pipe")
            h.call_service = boom; h.connect = lambda: None
            made.append(h); return h
        sp = speaker.Speaker(_RealishSettings(), factory)
        sp.speak("hello")                              # must not raise, must not loop
        self.assertEqual(len(made), 2)                 # tried twice, then gave up
        self.assertIsNone(sp.ha)                       # cleared for a fresh attempt next time
```

Add a settings fake that yields a real tts_service so `announce` reaches the send:
```python
class _RealishSettings(object):
    announce_failures = True
    tts_service = "tts.speak"
    tts_data = {"media_player_entity_id": "{entity}", "message": "{msg}"}
    ceiling_entity = "media_player.ceiling_speakers"
```

- [ ] **Step 2: Run — expect FAIL before Task 1's fix, PASS after**

Run: `python tests/test_speaker.py`
Expected: with Task 1 applied, all PASS (reconnect heals; both-fail clears `self.ha`, no loop).

- [ ] **Step 3: Commit**

```bash
git add tests/test_speaker.py
git commit -m "test(resolver): Speaker recovers from a dropped announce socket; no retry loop"
```

---

## Deploy (gated — requires your restart; NOT part of this design)
- Back up host `haconn.py` → `~/mass-resolver/.f1bak/haconn.py.bak`.
- Deploy `haconn.py`; `python3 -c "import haconn"` parse/import check; run full `tests/` on host.
- **You run:** `sudo systemctl restart mass-resolver`; confirm `SERVICE: connected …` + `/command …`.
- Verify: trigger a no-match → `ANNOUNCE via tts.speak` (success); then simulate recovery by reproducing
  a dropped socket if feasible (or accept the unit/integration tests as the guarantee).
- **Rollback:** restore `.f1bak/haconn.py.bak` + restart.

## Known limitation (explicitly out of scope)
This fixes the *swallow-prevents-reconnect* bug. It does **not** add send-acknowledgement; a rare
half-open socket that accepts a write but drops it silently would still lose one announce until the next
send raises. Detecting that would need a read-ack round-trip — a separate, larger change.

## Self-review
- Root cause + fix localized to `haconn.HA.announce()` (log **and** re-raise); `Speaker.speak()`
  unchanged (its reconnect-once becomes effective). Tests cover: propagation (Task 1), reconnect-once
  success, and no-infinite-loop (Task 2). Behaviour-preserving for no-op/templating paths. Python-3.5
  safe; matches existing `unittest` fake-injection style. Deploy/rollback documented; restart gated to
  the user.
