# Foundation F1 — Synchronous Command Result — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Give every capability a synchronous, structured `CommandResult` so ChatGPT reports the real outcome instead of guessing — via a `resolve→validate→execute` capability interface and a resolver `POST /command` HTTP endpoint that HA scripts call with `rest_command` + `response_variable`. Migrate Music + Radio; keep Inc 0/1 working throughout.

**Architecture:** The resolver gains (a) a `CommandResult` contract, (b) a `resolve/validate/execute/run` capability interface, (c) a single `Speaker` that owns all speaker TTS, and (d) a stdlib HTTP server exposing `POST /command`. Capabilities are transport-agnostic; the existing HA-event adapter stays live (dual-path). HA scripts switch from firing events to calling `/command` and relaying `chat_text`.

**Tech Stack:** Python 3.5 (host), stdlib only (`http.server`, `socketserver`, `threading`, `json`); stdlib `unittest` (no pytest), fakes per existing `tests/` pattern. Design doc: `../2026-06-28-F1-synchronous-command-result-design.md`.

## Global Constraints

- **Python 3.5 compatible** (deployed): no f-strings, no `:=`, no `dict|dict`; `%`/`.format()`.
- **Single sync mechanism (no speculative fallback):** HA `rest_command` with `response_variable` → resolver `POST /command` → `CommandResult` JSON. A **pre-check task (T9) must prove `response_variable` works on the live HA before any script is migrated.** Do NOT design/build a second path (python_script/custom integration) unless T9 proves `response_variable` insufficient — then STOP and escalate for a design addendum.
- **Single TTS owner = the resolver.** A single `Speaker` (one HA connection, lock-protected) speaks `spoken_text` for BOTH the event and HTTP paths. **HA scripts must NOT call `tts.speak`** — they only set the conversation response from `chat_text`. A test (T10) must confirm resolver-side TTS fires during a synchronous `/command`; only if that fails do we revisit script-side TTS.
- **Additive / dual-path / reversible:** the event adapter (`mass_play_request`/`mass_radio_request`/`mass_sync_request`) stays live for the whole of F1; capabilities keep working via it (mapped from `CommandResult`). Inc 0/1 baseline + `resolver.py.orig` remain.
- **Do NOT expose new functionality to ChatGPT until validated**; migrate one capability at a time; `ceiling_play_radio` stays as fallback.
- **Secrets** (incl. any `/command` shared-secret) only in 0600 files, never logged/committed; secret-scan before commits. User runs sudo/restarts. No AI attribution in commits.
- Repo source of truth: `D:\repos\dotfiles\docs\homebrain\mass-resolver\` (mirrors `~costea/mass-resolver/`; host `costea@192.168.1.68`; MA `192.168.122.10:8095`, HA `192.168.122.10:8123`; `ssh-add ~/.ssh/id_homebrain` first).

### CommandResult contract (used everywhere)

```
{ "ok": bool, "intent": str, "request_id": str,
  "spoken_text": str|None,        # resolver speaks this (Speaker); None = silent
  "chat_text": str,               # always present; HA script returns this to ChatGPT
  "error": {"code": str, "reason": str} | None,   # code in ERROR_CODES
  "metadata": {..},               # capability-specific structured data
  "actions": [] }                 # reserved, future
```
`ERROR_CODES = {"not_found","invalid_input","play_failed","upstream_error","not_implemented","unauthorized","unavailable"}`

### File structure

- Create: `command_result.py`, `capability.py`, `speaker.py`, `http_server.py`.
- Modify: `music.py`, `radio.py` (to the capability interface), `core.py` (dispatch → CommandResult + Speaker), `resolver.py` (start HTTP server + Speaker + CLI), `config.py` (HTTP host/port/secret).
- Tests: `tests/test_command_result.py`, `test_capability.py`, `test_speaker.py`, `test_http_server.py`, + updates to `test_music.py`/`test_radio.py`/`test_core.py`/`test_resolver.py`.
- Stubs `news/acquire/status.py` adopt the interface opportunistically (return `not_implemented` CommandResult) — minor.

---

## Task 1: `command_result.py` — the contract + builders + legacy mapping

**Files:** Create `command_result.py`; Test `tests/test_command_result.py`.

**Interfaces produced:** `ERROR_CODES` (set); `ok(intent, rid, chat_text, spoken_text=None, metadata=None) -> dict`; `err(intent, rid, code, reason, chat_text, spoken_text=None, metadata=None) -> dict`; `from_legacy(d) -> dict` (maps Inc 0/1 result dict → CommandResult).

- [ ] **Step 1: Failing test** — `tests/test_command_result.py`:

```python
#!/usr/bin/env python3
"""Run: python tests/test_command_result.py"""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import command_result as cr


class CommandResultTest(unittest.TestCase):
    def test_ok_shape(self):
        r = cr.ok("music", "r1", "Playing Du Hast.", spoken_text="Playing Du Hast.", metadata={"uri": "x"})
        self.assertTrue(r["ok"]); self.assertIsNone(r["error"])
        self.assertEqual(r["intent"], "music"); self.assertEqual(r["request_id"], "r1")
        self.assertEqual(r["chat_text"], "Playing Du Hast.")
        self.assertEqual(r["spoken_text"], "Playing Du Hast.")
        self.assertEqual(r["metadata"], {"uri": "x"}); self.assertEqual(r["actions"], [])

    def test_err_shape_and_code(self):
        r = cr.err("music", "r2", "not_found", "no match for X", "X isn't in your library yet.",
                   spoken_text="Sorry, I couldn't find X.")
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"], {"code": "not_found", "reason": "no match for X"})
        self.assertIn(r["error"]["code"], cr.ERROR_CODES)
        self.assertEqual(r["chat_text"], "X isn't in your library yet.")

    def test_err_rejects_unknown_code(self):
        self.assertRaises(ValueError, cr.err, "music", "r", "bogus", "x", "y")

    def test_from_legacy_success(self):
        leg = {"ok": True, "intent": "music", "request_id": "r3", "spoken": None, "played": True,
               "uri": "u", "provider": "filesystem_smb", "candidate": "Du Hast", "media_type": "track"}
        r = cr.from_legacy(leg)
        self.assertTrue(r["ok"]); self.assertEqual(r["intent"], "music")
        self.assertEqual(r["metadata"]["uri"], "u"); self.assertEqual(r["metadata"]["played"], True)
        self.assertTrue(r["chat_text"])  # chat_text always present

    def test_from_legacy_failure_maps_reason_to_error(self):
        leg = {"ok": False, "intent": "music", "request_id": "r4", "reason": "no local match",
               "spoken": "Sorry, I couldn't find My Way in the local library."}
        r = cr.from_legacy(leg)
        self.assertFalse(r["ok"]); self.assertEqual(r["error"]["reason"], "no local match")
        self.assertEqual(r["error"]["code"], "not_found")
        self.assertEqual(r["spoken_text"], leg["spoken"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

- [ ] **Step 2: Run → FAIL** (`No module named 'command_result'`). `cd docs/homebrain/mass-resolver && python tests/test_command_result.py`

- [ ] **Step 3: Implement** — create `command_result.py`:

```python
#!/usr/bin/env python3
# Synchronous CommandResult contract: builders + legacy mapping. Python 3.5 safe.
ERROR_CODES = set(["not_found", "invalid_input", "play_failed", "upstream_error",
                   "not_implemented", "unauthorized", "unavailable"])

# legacy reason text -> error code
_REASON_CODE = {"no local match": "not_found", "no match": "not_found", "stub": "not_implemented",
                "play failed": "play_failed", "unknown intent": "invalid_input", "error": "upstream_error"}


def ok(intent, rid, chat_text, spoken_text=None, metadata=None):
    return {"ok": True, "intent": intent, "request_id": rid, "spoken_text": spoken_text,
            "chat_text": chat_text, "error": None, "metadata": metadata or {}, "actions": []}


def err(intent, rid, code, reason, chat_text, spoken_text=None, metadata=None):
    if code not in ERROR_CODES:
        raise ValueError("unknown error code: %s" % code)
    return {"ok": False, "intent": intent, "request_id": rid, "spoken_text": spoken_text,
            "chat_text": chat_text, "error": {"code": code, "reason": reason},
            "metadata": metadata or {}, "actions": []}


def from_legacy(d):
    d = d or {}
    intent = d.get("intent", "unknown"); rid = d.get("request_id", "")
    spoken = d.get("spoken")
    meta = {}
    for k in ("uri", "provider", "candidate", "media_type", "played", "station", "source", "stations", "query"):
        if k in d:
            meta[k] = d[k]
    if d.get("ok"):
        chat = spoken or "Done."
        return ok(intent, rid, chat, spoken_text=spoken, metadata=meta)
    reason = d.get("reason") or "error"
    code = "not_implemented" if d.get("not_implemented") else _REASON_CODE.get(reason, "upstream_error")
    chat = spoken or reason
    return err(intent, rid, code, reason, chat, spoken_text=spoken, metadata=meta)
```

- [ ] **Step 4: Run → PASS** (5 tests).

- [ ] **Step 5: Commit** — `git add command_result.py tests/test_command_result.py && git commit -m "feat(homebrain): add CommandResult contract (builders + legacy mapping)"`

---

## Task 2: `capability.py` — `resolve → validate → execute → run`

**Files:** Create `capability.py`; Test `tests/test_capability.py`.

**Interfaces:** `class Capability` (abstract: `name`, `resolve(ctx,params)`, `validate(ctx,resolved)`, `execute(ctx,resolved,rid)`); `run(cap, ctx, params, rid) -> CommandResult`.
- `resolve` → a plain `resolved` object (dict), no side effects.
- `validate` → `None` if OK to execute, else a dict `{"code","reason","chat_text","spoken_text"(opt),"metadata"(opt)}`.
- `execute` → a `CommandResult` (success path; may itself return an `err` for `play_failed`).
- `run` orchestrates the three, converts a validate-failure to `command_result.err`, and wraps exceptions as `upstream_error`.

- [ ] **Step 1: Failing test** — `tests/test_capability.py`:

```python
#!/usr/bin/env python3
"""Run: python tests/test_capability.py"""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import capability, command_result as cr


class FakeCap(capability.Capability):
    name = "music"
    def __init__(self, resolved=None, invalid=None, boom=False, exec_result=None):
        self._resolved = resolved; self._invalid = invalid; self._boom = boom; self._exec = exec_result
    def resolve(self, ctx, params):
        if self._boom:
            raise RuntimeError("kaboom")
        return self._resolved
    def validate(self, ctx, resolved):
        return self._invalid
    def execute(self, ctx, resolved, rid):
        return self._exec


class CapabilityTest(unittest.TestCase):
    def test_validate_failure_short_circuits(self):
        cap = FakeCap(resolved={"x": 1}, invalid={"code": "not_found", "reason": "nope",
                                                  "chat_text": "Not found.", "spoken_text": "Couldn't find it."})
        r = capability.run(cap, None, {}, "r1")
        self.assertFalse(r["ok"]); self.assertEqual(r["error"]["code"], "not_found")
        self.assertEqual(r["chat_text"], "Not found."); self.assertEqual(r["spoken_text"], "Couldn't find it.")

    def test_execute_runs_when_valid(self):
        good = cr.ok("music", "r2", "Playing.", spoken_text="Playing.")
        cap = FakeCap(resolved={"x": 1}, invalid=None, exec_result=good)
        r = capability.run(cap, None, {}, "r2")
        self.assertTrue(r["ok"]); self.assertEqual(r["chat_text"], "Playing.")

    def test_exception_becomes_upstream_error(self):
        cap = FakeCap(boom=True)
        r = capability.run(cap, None, {}, "r3")
        self.assertFalse(r["ok"]); self.assertEqual(r["error"]["code"], "upstream_error")
        self.assertTrue(r["chat_text"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

- [ ] **Step 2: Run → FAIL**.

- [ ] **Step 3: Implement** — create `capability.py`:

```python
#!/usr/bin/env python3
# Capability lifecycle: resolve -> validate -> execute -> CommandResult. Python 3.5 safe.
import logging
import command_result as cr

LOG = logging.getLogger("resolver")


class Capability(object):
    name = "base"
    def resolve(self, ctx, params):
        raise NotImplementedError
    def validate(self, ctx, resolved):
        return None
    def execute(self, ctx, resolved, rid):
        raise NotImplementedError


def run(cap, ctx, params, rid):
    try:
        resolved = cap.resolve(ctx, params)
        v = cap.validate(ctx, resolved)
        if v is not None:
            return cr.err(cap.name, rid, v.get("code", "invalid_input"), v.get("reason", ""),
                          v.get("chat_text", v.get("reason", "")), spoken_text=v.get("spoken_text"),
                          metadata=v.get("metadata"))
        return cap.execute(ctx, resolved, rid)
    except Exception as e:
        LOG.error("req=%s capability=%s error: %r", rid, getattr(cap, "name", "?"), e)
        return cr.err(getattr(cap, "name", "unknown"), rid, "upstream_error", repr(e),
                      "Sorry, something went wrong.")
```

- [ ] **Step 4: Run → PASS** (3 tests).

- [ ] **Step 5: Commit** — `git commit -m "feat(homebrain): add resolve/validate/execute capability interface"`

---

## Task 3: Migrate `music.py` to the capability interface (CommandResult)

**Files:** Modify `music.py`; Modify `tests/test_music.py`.

**Interfaces:** `class MusicCapability(Capability)` with `resolve` (rank candidates via `match`, filtered to preferred provider — moves current `_resolve_type`/`resolve_any` logic), `validate` (no candidate → `not_found`), `execute` (play via MA, build `command_result.ok`/`err(play_failed)`; honor `settings.dry_run`). Keep a thin `resolve_music(ma, query, media_type, settings, rid)` wrapper returning a **legacy dict** (via mapping) so the event path is unchanged.

**Consumes:** `match`, `maconn.WS_CMD`, `command_result`, `capability`. **chat_text:** success "Playing <candidate>." / dry-run "Would play <candidate>."; not_found "<query> isn't in your local library yet."; play_failed "I found <candidate>, but couldn't start it."

- [ ] **Step 1: Update tests** — extend `tests/test_music.py` to drive the capability (keep `FakeMA`/`smb_item`/`ytm_item`/`FakeSettings`). Add:

```python
    def test_capability_play_returns_commandresult(self):
        ma = FakeMA().set({"artist": [smb_item("Rammstein", "42")]})
        import capability, music
        r = capability.run(music.MusicCapability(), _ctx(ma), {"query": "Rammstein", "media_type": "artist"}, "r1")
        self.assertTrue(r["ok"]); self.assertEqual(r["intent"], "music")
        self.assertEqual(r["metadata"]["uri"], "filesystem_smb--kd66vco4://artist/42")
        self.assertTrue(r["chat_text"]); self.assertEqual(r["error"], None)

    def test_capability_not_found_is_error(self):
        ma = FakeMA().set({"artist": [], "album": [], "track": [], "playlist": []})
        import capability, music
        r = capability.run(music.MusicCapability(), _ctx(ma), {"query": "Nope"}, "r2")
        self.assertFalse(r["ok"]); self.assertEqual(r["error"]["code"], "not_found")
        self.assertIn("library", r["chat_text"].lower())

    def test_legacy_wrapper_still_returns_dict(self):
        ma = FakeMA().set({"artist": [smb_item("Rammstein", "42")]})
        import music
        d = music.resolve_music(ma, "Rammstein", "artist", FakeSettings(), "r3")  # legacy shape
        self.assertIn("ok", d); self.assertTrue(d["ok"])
```

Add a `_ctx(ma)` helper to the test that builds a minimal ctx exposing `ma_factory`/`settings` (a fresh `FakeCtx` like Task-4 Inc 1 — provide `ma_factory=lambda: ma`, `settings=FakeSettings()`). The existing 5 Inc-1 music tests stay (they call `resolve_music`).

- [ ] **Step 2: Run → FAIL** (no `MusicCapability`).

- [ ] **Step 3: Implement** — refactor `music.py`: keep `_resolve_type` (provider-filtered ranking, unchanged). Add:

```python
class MusicCapability(capability.Capability):
    name = "music"
    def resolve(self, ctx, params):
        ma = ctx.ma_factory(); ma.connect()
        try:
            q = params.get("query"); mt = params.get("media_type") or ""
            types = [mt] + [t for t in ctx.settings.type_order if t != mt] if mt in WS_CMD else list(ctx.settings.type_order)
            hit = None
            for t in types:
                hit = _resolve_type(ma, q, t, ctx.settings, params.get("_rid", ""))
                if hit:
                    break
            return {"ma": ma, "query": q, "hit": hit, "dry_run": params.get("dry_run") or ctx.settings.dry_run}
        except Exception:
            ma.close(); raise
    def validate(self, ctx, resolved):
        if not resolved.get("hit"):
            q = resolved.get("query") or "that"
            resolved["ma"].close()
            return {"code": "not_found", "reason": "no local match",
                    "chat_text": q + " isn't in your local library yet.",
                    "spoken_text": "Sorry, I couldn't find " + q + " in the local library.",
                    "metadata": {"query": q}}
        return None
    def execute(self, ctx, resolved, rid):
        ma = resolved["ma"]; hit = resolved["hit"]
        try:
            md = {"uri": hit["uri"], "provider": hit["provider"], "candidate": hit["candidate"], "media_type": hit["media_type"]}
            if resolved["dry_run"]:
                md["played"] = False
                return cr.ok(self.name, rid, "Would play " + hit["candidate"] + ".", spoken_text=None, metadata=md)
            pr = ma.play(ctx.settings.queue_id, hit["uri"])
            if pr and "error_code" in pr:
                md["played"] = False
                return cr.err(self.name, rid, "play_failed", str(pr.get("error_code")),
                              "I found " + hit["candidate"] + ", but couldn't start it.",
                              spoken_text="I found " + hit["candidate"] + ", but couldn't start playback.", metadata=md)
            md["played"] = True
            return cr.ok(self.name, rid, "Playing " + hit["candidate"] + ".", spoken_text=None, metadata=md)
        finally:
            ma.close()
```

Add imports `import capability, command_result as cr`. Keep `resolve_music(...)` as a legacy wrapper:

```python
def resolve_music(ma, query, media_type, settings, rid):
    # legacy dict (event path): adapt by running the capability against a one-off ctx wrapping `ma`
    class _C(object):
        def __init__(s):
            s.settings = settings
        def ma_factory(s):
            return ma
    res = capability.run(MusicCapability(), _C(), {"query": query, "media_type": media_type, "_rid": rid}, rid)
    # map CommandResult back to the Inc 0/1 legacy dict the event path expects
    out = {"ok": res["ok"], "intent": "music", "request_id": rid, "spoken": res.get("spoken_text")}
    out.update(res.get("metadata") or {})
    if not res["ok"]:
        out["reason"] = (res.get("error") or {}).get("reason")
    return out
```

> Note: `resolve_music` now takes an already-connected `ma` but the capability opens its own; adjust the legacy wrapper so `_C.ma_factory` returns the passed `ma` and the capability does not double-connect — guard `ma.connect()` to be idempotent (maconn `connect()` is safe to call once; if the legacy `ma` is already connected, skip). Implementer: make `MusicCapability.resolve` tolerant of an already-connected `ma` (e.g. `if ma.s is None: ma.connect()`), and have the legacy wrapper NOT pre-connect. Keep behavior identical for the event path.

- [ ] **Step 4: Run → PASS** (8 music tests). Also run `python tests/test_command_result.py` and `tests/test_capability.py` to confirm no breakage.

- [ ] **Step 5: Commit** — `git commit -m "refactor(homebrain): music capability returns CommandResult (legacy wrapper kept)"`

---

## Task 4: Migrate `radio.py` to the capability interface

**Files:** Modify `radio.py`; Modify `tests/test_radio.py`.

Mirror Task 3 for radio: `class RadioCapability(Capability)` — `resolve` builds favorites-first→RadioBrowser candidates (move current `_candidates`), `validate` (`mode=play` with no candidate → `not_found`; `mode=find` with none → `not_found`), `execute` (play → `ok`/`play_failed`; dry-run; `find` → `ok` with `spoken_text` = the top-3 list and `metadata.stations`). `chat_text`: play "Playing <station>."; find "Here are some stations: A, B, C."; not_found honest. Keep a legacy `resolve_radio(ctx, params, rid)` wrapper returning the Inc 1 dict (so the event path + `core.INTENTS["radio"]` keep working) by mapping the CommandResult.

- [ ] **Step 1: Update tests** — add capability-driven tests (play favorite, genre fallback, dry-run, find speaks top-3 via `spoken_text`, not_found error) asserting CommandResult shape; keep the existing 11 Inc-1 radio tests (they call `resolve_radio`).
- [ ] **Step 2: Run → FAIL**.
- [ ] **Step 3: Implement** `RadioCapability` (move `_candidates`/`_dedupe`; build CommandResult; `find` sets `spoken_text` = "I found A, B and C." and `metadata.stations`); keep `resolve_radio` legacy wrapper mapping CommandResult→Inc 1 dict.
- [ ] **Step 4: Run → PASS** (radio tests + full suite green).
- [ ] **Step 5: Commit** — `git commit -m "refactor(homebrain): radio capability returns CommandResult (legacy wrapper kept)"`

---

## Task 5: `speaker.py` — single TTS owner

**Files:** Create `speaker.py`; Test `tests/test_speaker.py`.

**Interfaces:** `class Speaker(settings, ha_factory)` with `speak(text)` — lock-protected; lazily connects an HA (via `ha_factory`) and calls `ha.announce(text, settings)`; on failure reconnects once; `None`/empty text → no-op. One instance is shared by the event loop and the HTTP server (the sole TTS path).

- [ ] **Step 1: Failing test** — `tests/test_speaker.py`:

```python
#!/usr/bin/env python3
"""Run: python tests/test_speaker.py"""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import speaker


class FakeHA(object):
    def __init__(self): self.said = []; self.connected = False; self.fail_connect = False
    def connect(self):
        if self.fail_connect: raise IOError("no ha")
        self.connected = True
    def announce(self, text, settings): self.said.append(text)
    def close(self): pass


class FakeSettings(object):
    announce_failures = True


class SpeakerTest(unittest.TestCase):
    def test_speak_connects_and_announces(self):
        ha = FakeHA(); sp = speaker.Speaker(FakeSettings(), lambda: ha)
        sp.speak("hello")
        self.assertEqual(ha.said, ["hello"]); self.assertTrue(ha.connected)

    def test_empty_text_is_noop(self):
        ha = FakeHA(); sp = speaker.Speaker(FakeSettings(), lambda: ha)
        sp.speak(None); sp.speak("")
        self.assertEqual(ha.said, [])

    def test_reuses_connection(self):
        ha = FakeHA(); sp = speaker.Speaker(FakeSettings(), lambda: ha)
        sp.speak("a"); sp.speak("b")
        self.assertEqual(ha.said, ["a", "b"])

    def test_reconnects_after_failure(self):
        bad = FakeHA(); good = FakeHA(); box = {"first": True}
        def factory():
            if box["first"]:
                box["first"] = False; bad.announce = _raiser; return bad
            return good
        sp = speaker.Speaker(FakeSettings(), factory)
        sp.speak("x")  # first announce raises -> reconnect -> good
        self.assertEqual(good.said, ["x"])


def _raiser(*a, **k):
    raise IOError("ws gone")


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

- [ ] **Step 2: Run → FAIL**.

- [ ] **Step 3: Implement** — create `speaker.py`:

```python
#!/usr/bin/env python3
# Single owner of speaker TTS. Lock-protected; shared by event + HTTP paths. Python 3.5 safe.
import logging, threading

LOG = logging.getLogger("resolver")


class Speaker(object):
    def __init__(self, settings, ha_factory):
        self.settings = settings; self.ha_factory = ha_factory
        self.ha = None; self.lock = threading.Lock()

    def speak(self, text):
        if not text:
            return
        with self.lock:
            try:
                if self.ha is None:
                    self.ha = self.ha_factory(); self.ha.connect()
                self.ha.announce(text, self.settings)
                return
            except Exception as e:
                LOG.error("speak: retrying after error %r", e)
            try:
                self.ha = self.ha_factory(); self.ha.connect()
                self.ha.announce(text, self.settings)
            except Exception as e:
                LOG.error("speak failed: %r", e); self.ha = None
```

- [ ] **Step 4: Run → PASS** (4 tests).

- [ ] **Step 5: Commit** — `git commit -m "feat(homebrain): add Speaker (single resolver-owned TTS path)"`

---

## Task 6: `core.py` — dispatch returns CommandResult + speaks via Speaker

**Files:** Modify `core.py`; Modify `tests/test_core.py`.

**Changes:** `Ctx` gains `speaker` (and keeps `ma_factory`/`settings`/`radio_cfg`/`news_cfg`). `dispatch(ctx, intent, params, rid=None) -> CommandResult`:
- route via the capability classes (`music.MusicCapability`, `radio.RadioCapability`) using `capability.run`; stubs/news/acquire/status return `command_result.err(..., "not_implemented", ...)`; `sync` runs library sync → `ok`.
- **TTS:** speak `result["spoken_text"]` via `ctx.speaker.speak(...)` when present (single owner). This replaces the old `ha.announce` + `speak_success` logic — `spoken_text` is now set by capabilities exactly when something should be said (find list, failures), so `dispatch` simply speaks it whenever non-None and `announce_failures` is on (failures) or always for non-failures that set it.

> Decision baked in: capabilities decide *what* to speak (set `spoken_text` or leave None); `dispatch` just owns *speaking it once*. Gate failure speech on `settings.announce_failures` (success speech like the find list is always spoken).

- [ ] **Step 1: Update tests** — rewrite `tests/test_core.py` to assert: dispatch returns a CommandResult (`ok`/`chat_text`/`error`); `ctx.speaker.speak` is called with `spoken_text` when set, not when None; music success (no spoken_text) → no speak; music not_found → speak + error code; sync → ok, no speak; unknown intent → `err invalid_input`. Use a `FakeSpeaker` capturing `.said`.
- [ ] **Step 2: Run → FAIL**.
- [ ] **Step 3: Implement** dispatch over capability classes + Speaker; keep `sync_library`. Provide a `dispatch_legacy(...)` shim only if the event adapter still needs the old dict (else map at the adapter).
- [ ] **Step 4: Run → PASS** (full suite green).
- [ ] **Step 5: Commit** — `git commit -m "feat(homebrain): dispatch returns CommandResult; Speaker is sole TTS"`

---

## Task 7: `http_server.py` — `POST /command`

**Files:** Create `http_server.py`; Test `tests/test_http_server.py`.

**Interfaces:** `make_handler(dispatch_fn, secret)` → a `BaseHTTPRequestHandler` subclass; `serve_http(host, port, dispatch_fn, secret)` → starts a threaded server (returns the server so resolver can run it in a thread). `POST /command` body `{"intent","params"}` → calls `dispatch_fn(intent, params)` → 200 + `CommandResult` JSON. Missing/blank `intent` → 400 `err invalid_input`. If `secret` set, require header `X-Resolver-Key: <secret>` else 401 `err unauthorized`. Non-`/command` path → 404.

- [ ] **Step 1: Failing test** — `tests/test_http_server.py` (drives the handler logic via a fake request, OR starts the server on `127.0.0.1:0` and uses urllib). Prefer a real loopback server:

```python
#!/usr/bin/env python3
"""Run: python tests/test_http_server.py"""
import os, sys, json, threading, unittest
import urllib.request, urllib.error
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import http_server, command_result as cr


def fake_dispatch(intent, params):
    if intent == "music":
        return cr.ok("music", "r", "Playing.", spoken_text="Playing.", metadata={"q": params.get("query")})
    return cr.err(intent, "r", "not_implemented", "stub", "Not available yet.")


class HttpServerTest(unittest.TestCase):
    def setUp(self):
        self.srv = http_server.serve_http("127.0.0.1", 0, fake_dispatch, secret="s3cr3t")
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever).start()
    def tearDown(self):
        self.srv.shutdown(); self.srv.server_close()
    def _post(self, body, key="s3cr3t"):
        h = {"Content-Type": "application/json"}
        if key is not None: h["X-Resolver-Key"] = key
        req = urllib.request.Request("http://127.0.0.1:%d/command" % self.port, data=json.dumps(body).encode(), headers=h, method="POST")
        try:
            return 200, json.loads(urllib.request.urlopen(req, timeout=5).read().decode())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode())

    def test_ok(self):
        code, r = self._post({"intent": "music", "params": {"query": "X"}})
        self.assertEqual(code, 200); self.assertTrue(r["ok"]); self.assertEqual(r["metadata"]["q"], "X")
    def test_missing_intent_400(self):
        code, r = self._post({"params": {}})
        self.assertEqual(code, 400); self.assertEqual(r["error"]["code"], "invalid_input")
    def test_bad_secret_401(self):
        code, r = self._post({"intent": "music"}, key="wrong")
        self.assertEqual(code, 401); self.assertEqual(r["error"]["code"], "unauthorized")


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

- [ ] **Step 2: Run → FAIL**.

- [ ] **Step 3: Implement** — create `http_server.py` (stdlib `http.server` + `socketserver.ThreadingMixIn`; read `Content-Length`; JSON parse; secret check; map exceptions to `err upstream_error`/500; never log the secret or tokens).

- [ ] **Step 4: Run → PASS** (3 tests).

- [ ] **Step 5: Commit** — `git commit -m "feat(homebrain): add POST /command HTTP server"`

---

## Task 8: `resolver.py` — start HTTP server + Speaker; config; CLI

**Files:** Modify `resolver.py`, `config.py`; Modify `tests/test_resolver.py`.

**Changes:** `config.Settings` gains `http_host` (default `0.0.0.0`), `http_port` (default `8770`), and `http_secret` read from `config.read_secret(here, ".http_secret")` (optional). `build_ctx` creates a `Speaker(settings, ha_factory_for_tts)`. `serve(here)` starts the HTTP server in a thread (`http_server.serve_http(...)` with a `dispatch_fn = lambda intent, params: core.dispatch(ctx, intent, params)`), then runs the existing event loop (unchanged). A pure `command_from_request(body) -> (intent, params)` helper (validates intent present) is unit-tested. CLI unchanged.

- [ ] **Step 1: Update tests** — `tests/test_resolver.py`: add `command_from_request` tests (valid → (intent, params); missing intent → None/raises). Keep existing event_to_call tests.
- [ ] **Step 2: Run → FAIL**.
- [ ] **Step 3: Implement** config fields + `command_from_request` + wire `serve` to start the HTTP thread + Speaker (guard: if HTTP server fails to bind, log and continue event-only).
- [ ] **Step 4: Run → PASS**; then the WHOLE suite (`for t in tests/test_*.py; do python "$t" || exit 1; done`).
- [ ] **Step 5: Commit** — `git commit -m "feat(homebrain): resolver starts /command HTTP server + Speaker"`

---

## Task 9 [HOST, STOP for approval]: prove `rest_command` + `response_variable`

Gate for Constraint #1. **Present plan + get approval before touching host.**
- [ ] Deploy F1 modules; user restarts `mass-resolver` (starts the HTTP server). Verify the server is listening and `POST /command` returns a CommandResult (curl from the HA VM to the resolver host:8770).
- [ ] Create a minimal HA `rest_command` (`resolver_command`) pointing at `/command`, and a throwaway test script that calls it with `response_variable` and writes the captured `chat_text` into an `input_text`/log. Fire it; **confirm HA captures the response**.
- [ ] **Decision gate:** if `response_variable` captures the result → proceed to T10. If NOT supported on this HA version → **STOP and escalate** for a fallback design addendum (do not build a fallback speculatively).

## Task 10 [HOST, STOP]: deploy + validate resolver-side synchronous TTS

Gate for Constraint #2.
- [ ] With the HTTP path live, call `/command` for a play and a not_found; **confirm the resolver (Speaker) speaks `spoken_text` during the synchronous call** (audible) and returns CommandResult. Capture/restore station+volume.
- [ ] **Decision gate:** resolver-side TTS works in sync mode → scripts will NOT call `tts.speak`. If it cannot → escalate before adding script-side TTS.

## Task 11 [HOST, STOP]: migrate `script.play_music` to `/command`

- [ ] Back up `script.play_music`. Re-point it: call `rest_command resolver_command` (intent=music) with `response_variable`; `set_conversation_response` = `{{ result.chat_text }}`; **no `tts.speak`**. Keep the event-firing version backed up.
- [ ] Validate conversationally: "play Rammstein" → plays + ChatGPT says "Playing Rammstein."; "play My Way" → ChatGPT truthfully "isn't in your library" (the F1 win). Restore baseline.
- [ ] Retire the music event path only after this passes (keep `mass_sync_request`).

## Task 12 [HOST, STOP]: migrate radio scripts + validate

- [ ] Back up + migrate `script.play_radio` and `script.find_stations` to `/command` (intent=radio, mode play/find), `chat_text` response, no `tts.speak`. Validate ("play Hit FM", "play Romanian radio", "find jazz stations" → ChatGPT relays the real list). Restore baseline. Retire radio event path after validation; `ceiling_play_radio` stays as fallback.

## Task 13: docs + close-out

- [ ] Update `assistant-capabilities.md` (now synchronous; chat_text is authoritative), `local-music-architecture.md` (F1 internals + the `/command` ingress + Speaker), and mark **F1 DONE** in the umbrella spec §7. Note the retained script backups. Commit (docs-only, separate).

---

## Self-Review

**Spec coverage:** CommandResult (T1) ✓; resolve/validate/execute (T2) ✓; Music/Radio migration (T3/T4, dual-path legacy wrappers) ✓; News/Status/Acquisition honest-by-construction via the same interface (stubs adopt it; full build in their increments) ✓; rollback (legacy wrappers + event path kept + script backups) ✓; transition/dual-path (event adapter live; capabilities mapped) ✓. Constraint #1 (single mechanism + T9 gate, no speculative fallback) ✓. Constraint #2 (Speaker single TTS owner T5/T6; scripts no tts.speak; T10 gate) ✓.

**Placeholder scan:** none — repo tasks (T1–T8) carry complete code/tests; host tasks (T9–T13) are procedural-by-design (live actions, stop-for-approval), mirroring Inc 0/1.

**Type consistency:** `CommandResult` keys identical across `command_result`/`capability`/`music`/`radio`/`core`/`http_server`; `Capability.resolve/validate/execute/run` signatures consistent; `Ctx` exposes `ma_factory`/`settings`/`radio_cfg`/`speaker`; `dispatch(ctx,intent,params,rid)->CommandResult` consumed by `http_server` (via `dispatch_fn`) and the event adapter. Legacy wrappers (`resolve_music`/`resolve_radio`) preserve the Inc 0/1 dict for the event path.

**Note for execution:** T3's legacy-wrapper/`ma` connection handling (capability opens its own MA vs. the event path passing a connected `ma`) is the one integration subtlety — the implementer must make `MusicCapability.resolve` tolerant of an already-connected `ma` and keep the event path's behavior identical (verified by the retained Inc-1 tests).
