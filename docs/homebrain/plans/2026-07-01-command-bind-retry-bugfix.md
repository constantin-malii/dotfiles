# `/command` Bind-Retry Bugfix — Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use superpowers:subagent-driven-development. **Design
> only — do NOT implement until approved** (code change + a `sudo systemctl restart mass-resolver`).

**Goal:** make the resolver's `/command` HTTP server **self-heal after a host reboot / power outage**,
so ChatGPT tools work without a manual resolver restart.

**Architecture:** replace the one-shot HTTP bind in `serve()` with a **retry-with-backoff loop in a
daemon thread** — mirroring the event-connection reconnect that already self-heals directly below it.

**Tech Stack:** Python 3.5 (host), `unittest` (existing `tests/`).

## Root cause (observed 2026-06-30 → 2026-07-01)
On cold boot, `mass-resolver` starts **before** libvirt's bridge IP `192.168.122.1` is assigned, so the
`/command` bind fails:
```
SERVICE: HTTP server failed to start (OSError(99, 'Cannot assign requested address')); continuing event-only
```
The bind is **one-shot** (`resolver.py:86–93`): on failure it logs and drops to event-only **forever**.
The event loop, by contrast, retries and recovers. Result after an outage: MA/HA/event path healthy but
`/command` down → ChatGPT's three tools (all on `/command`) get connection-refused → "can't reach
music/radio." Manual `systemctl restart mass-resolver` fixes it (bridge is up by then) — that manual step
is what this bugfix removes.

## Global Constraints
- Python 3.5-safe (no f-strings/walrus/`dict|dict`); match `tests/` style (`unittest`, dependency
  injection, no real sockets/network in tests).
- Behaviour-preserving except the fix: event path, `/command` semantics, auth, and TTS ownership
  unchanged. No HA-script, model, or exposure changes.
- Additive/reversible; deploy = one file (`resolver.py`) + a `.f1bak`-style backup + user-run restart.

## File Structure
- Modify: `resolver.py` — factor the HTTP-server start into a retrying helper; call it in a daemon thread.
- Test: `tests/test_resolver.py` — assert the helper retries a failing bind then succeeds, resets
  backoff, and does not loop forever in the test.
- (Optional, secondary) `mass-resolver.service` — add `After=libvirtd.service` +
  `Wants=/After=network-online.target` as belt-and-suspenders (does not by itself guarantee the bridge
  IP is assigned, so the app-level retry remains the primary fix).

---

### Task 1: Retrying `/command` bind helper

**Files:**
- Modify: `resolver.py` (replace the one-shot block at ~lines 86–93; add a helper)
- Test: `tests/test_resolver.py`

**Interfaces:**
- Produces: `run_command_server(serve_http_fn, host, port, dispatch_fn, secret, sleep_fn=time.sleep,
  max_backoff=60, should_stop=None)` — loops: build server via `serve_http_fn`, log bound, `serve_forever`;
  on ANY exception log + `sleep_fn(backoff)` + exponential backoff (cap `max_backoff`); `should_stop()` (test
  hook) breaks the loop. `serve()` runs it in a daemon thread.

- [ ] **Step 1: Write the failing test** (add to `tests/test_resolver.py`)

```python
    def test_command_server_retries_bind_then_binds(self):
        import resolver
        calls = {"n": 0}
        class FakeSrv:
            def serve_forever(self_):
                raise _StopLoop()          # unblock so the test can inspect
        def fake_serve_http(host, port, dispatch, secret):
            calls["n"] += 1
            if calls["n"] == 1:
                raise OSError(99, "Cannot assign requested address")  # bridge not up yet
            return FakeSrv()               # bridge came up -> bind succeeds
        slept = []
        stop = {"n": 0}
        def fake_sleep(b):
            slept.append(b); stop["n"] += 1
        # stop after the 2nd serve_forever unblocks (n>=2 fake_serve_http calls)
        resolver.run_command_server(fake_serve_http, "192.168.122.1", 8770,
                                    lambda i, p: None, "sek",
                                    sleep_fn=fake_sleep, should_stop=lambda: calls["n"] >= 2)
        self.assertGreaterEqual(calls["n"], 2)     # retried after the first failure
        self.assertEqual(slept[0], 2)              # first backoff = 2s
```
(with a module-level `class _StopLoop(Exception): pass` in the test file, or reuse a simple raise).

- [ ] **Step 2: Run it — expect FAIL** (`run_command_server` doesn't exist yet)

Run: `python tests/test_resolver.py -k test_command_server_retries_bind_then_binds` (or run the file).
Expected: FAIL (AttributeError / not defined).

- [ ] **Step 3: Implement** — add the helper and use it in `serve()`:

```python
def run_command_server(serve_http_fn, host, port, dispatch_fn, secret,
                       sleep_fn=time.sleep, max_backoff=60, should_stop=None):
    b = 2
    while True:
        try:
            srv = serve_http_fn(host, port, dispatch_fn, secret)
            LOG.info("SERVICE: /command HTTP server on %s:%s", host, port)
            b = 2
            srv.serve_forever()   # blocks until shutdown/error
            LOG.error("SERVICE: /command HTTP server stopped; rebinding in %ss", b)
        except Exception as e:
            LOG.error("SERVICE: /command bind/serve failed (%r); retrying in %ss", e, b)
        sleep_fn(b); b = min(b * 2, max_backoff)
        if should_stop is not None and should_stop():
            return
```
Replace the old one-shot block in `serve()` with:
```python
    ht = threading.Thread(target=lambda: run_command_server(
        http_server.serve_http, s.http_host, s.http_port, dispatch_fn, http_secret))
    ht.daemon = True
    ht.start()
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `python tests/test_resolver.py` (new test + existing resolver tests green).

- [ ] **Step 5: Commit**

```bash
git add docs/homebrain/mass-resolver/resolver.py docs/homebrain/mass-resolver/tests/test_resolver.py
git commit -m "fix(resolver): retry /command bind so it self-heals after a host reboot"
```

---

## Deploy (gated — requires your restart; NOT part of this design)
- Back up host `resolver.py` → `~/mass-resolver/.f1bak/resolver.py.bak`.
- Deploy `resolver.py`; `python3 -c "import resolver"` import check; run `tests/` on the host (3.5).
- **You run:** `sudo systemctl restart mass-resolver`; confirm `SERVICE: /command HTTP server on
  192.168.122.1:8770` + `/command` 200/401.
- **Optional post-check (proves self-heal):** since the bridge is already up, normal start binds
  immediately; the retry path is covered by the unit test. A full reboot test can be deferred to the next
  real outage.
- **Rollback:** restore `.f1bak/resolver.py.bak` + restart.

## Known limitation / secondary option
The retry is app-level and robust to the bridge appearing late. Optionally also add systemd ordering
(`After=libvirtd.service`, `Wants=network-online.target`, `After=network-online.target`) to
`mass-resolver.service` — this narrows the race but does **not** guarantee the bridge IP is assigned at
`ExecStart`, so it is a supplement, not a replacement, for the retry.

## Self-review
- Fix localized to `serve()` + a testable `run_command_server` helper; event loop, `/command` semantics,
  auth, TTS ownership unchanged. Test proves retry-after-failure and backoff reset without an infinite
  loop (via `should_stop`). Python-3.5 safe; matches `unittest` DI style. Deploy/rollback documented;
  restart gated to the user. **No implementation performed — design only.**
