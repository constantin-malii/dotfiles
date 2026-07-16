# S1b-1′ — Resolver `say` via `play_announcement` (rework) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use `superpowers:subagent-driven-development` (recommended)
> or `superpowers:executing-plans`. Steps use `- [ ]` checkboxes.

**Goal:** rework the resolver's `interaction` `say` mode to the **Spike-2/3-validated** mechanism —
`music_assistant.play_announcement` (audible, blocking, pause→reply→resume) with **capture→replay** for radio
— and **remove the superseded S1b-1 machinery** (reply timer, `reply_active`, H2 `ignore_user_override`, N1
gen-stamping) that the old fast-return model needed.

**Architecture:** `say` becomes **lock-free and independent of the duck**: it reads the ceiling's current
`media_content_id`, calls `music_assistant.play_announcement` (blocking; MA pauses the music, plays the reply,
resumes resumable content), and — if the ceiling did **not** auto-resume (radio/live stream) — re-plays the
captured id via `music_assistant.play_media` (Spike-3 proven). It touches **no** `_snaps`/`_lock`; S1a's
duck/restore (AU-02/03) is unchanged and composes cleanly — during a reply the music is **paused**, so S1a's
`idle→restore` un-duck is inaudible (this is why B1 dissolves). Net: the duck/restore reverts to its AU-02/03
form and `say` is a small standalone capability.

**Mechanism — VALIDATED by Spike-2/3 (2026-07-15; design §11 / merged PR #23):** `music_assistant.play_announcement`
is **audible**, **synchronous/blocking ~7–14 s** (measured), and **pauses → plays → resumes** (not an overlay);
radio does not auto-resume, so the captured `media_content_id` (e.g. `library://radio/2`) is re-played after —
proven live end-to-end (heard by ear + state-verified). `media_player.play_media(announce=true)` was **rejected**
(stops the stream, inaudible, ~14 s). This plan builds only on that validated behavior; the one case still to
confirm at deploy is **local-music auto-resume** (low risk — resumable content resumes on its own).

**Tech Stack:** Python 3.5 (host 3.5.2), stdlib `unittest`, resolver modules under `docs/homebrain/mass-resolver/`.

## Global Constraints

- **Python 3.5 only:** no f-strings/type-hints/`async`/`_`-separators/`dataclasses`. `%`/`.format()`.
- **Tests:** stdlib `unittest`, `tests/test_interaction.py`, run from the resolver dir; existing
  `FakeHA`/`FakeSettings`/`FakeCtx`/`FakeTimer` style.
- **`say` is silent** (`spoken_text=None`) and **lock-free** (touches no `_snaps`/`_lock`) — it is the audio
  path, independent of the duck. Resolver stays sole media/TTS owner.
- **Blocking call:** `play_announcement` blocks ~7–14 s (Spike-2/3). The `say` REST call MUST use a long
  timeout (`say_announce_timeout_ms`, default 30000) — the default 5 s `call_service_rest` timeout is too short.
- **Levers:** `music_assistant.play_announcement` + `music_assistant.play_media` only. Never `media_stop`.
- **No deploy in this plan.** Deploy + validation (local-music auto-resume; S1a composition) is a separate,
  approval-gated step. Radio capture/replay is already Spike-3-proven.
- **Working dir:** `docs/homebrain/mass-resolver/`.

## File structure

- **Modify:** `haconn.py` — add optional `timeout` to `call_service_rest`.
- **Modify:** `interaction.py` — rework `_say`; **remove** `_arm_reply_timer`, `_reply_complete`, `_gen`,
  `reply_active`, and revert `_restore`/`_auto_restore`/`_arm_timer` to their AU-02/03 form.
- **Modify:** `config.py` + `config.json` — replace `say_hold_default_ms`/`say_margin_ms` (reply-timer, now
  unused) with `say_announce_timeout_ms` (30000).
- **Modify:** `tests/test_interaction.py` + `tests/test_config.py` — new `say` tests; **remove** the obsolete
  reply-timer / H2 / N1 / hold-clamp tests; keep AU-02/03 duck/restore/dead-man tests.

**Interfaces produced:** `interaction` `say` params `{uri|media_content_id, zone(default ceiling)}` (no more
`hold_ms`); `CommandResult.metadata` `{said, replayed(bool), zone}`; `haconn.call_service_rest(domain, service,
data, timeout=5)`; config `settings.say_announce_timeout_ms` (int ms).

---

### Task 1: Config — replace reply-timer tunables with the announce timeout

**Files:** `config.py`, `config.json`, `tests/test_config.py`.

- [ ] **Step 1: Failing test** — in `tests/test_config.py`, replace `SayTunablesTest` with:

```python
class SayTunablesTest(unittest.TestCase):
    def test_defaults(self):
        s = config.Settings({})
        self.assertEqual(s.say_announce_timeout_ms, 30000)

    def test_override(self):
        s = config.Settings({"say_announce_timeout_ms": 20000})
        self.assertEqual(s.say_announce_timeout_ms, 20000)
```

- [ ] **Step 2: Run, verify fail** — `python tests/test_config.py` → FAIL.

- [ ] **Step 3: Implement** — in `config.py` replace the two `say_hold_default_ms`/`say_margin_ms` lines with:

```python
        # S1b-1' say (ceiling reply) — play_announcement is blocking (~7-14s); allow a long timeout
        self.say_announce_timeout_ms = int(cfg.get("say_announce_timeout_ms", 30000))
```
  In `config.json`, replace the `say_hold_default_ms`/`say_margin_ms` keys with `"say_announce_timeout_ms": 30000,`.

- [ ] **Step 4: Run, verify pass** — `python tests/test_config.py` → PASS.

- [ ] **Step 5: Commit** (code + runtime config separate):

```bash
git add config.py tests/test_config.py
git commit -m "feat(resolver): replace say reply-timer tunables with say_announce_timeout_ms"
git add config.json
git commit -m "config(resolver): say_announce_timeout_ms"
```

---

### Task 2: haconn — optional timeout on `call_service_rest`

**Files:** `haconn.py`, `tests/test_haconn.py`.

- [ ] **Step 1: Failing test** — add to `tests/test_haconn.py` (mirror the existing `call_service_rest` test
  style): assert that passing `timeout=30` is used for the `HTTPConnection` timeout (mock `http.client.HTTPConnection`,
  capture the `timeout` kwarg), and that omitting it defaults to `5`.

- [ ] **Step 2: Run, verify fail** — `python tests/test_haconn.py` → FAIL.

- [ ] **Step 3: Implement** — change the signature + connection line in `haconn.py`:

```python
    def call_service_rest(self, domain, service, data, timeout=5):
        conn = http.client.HTTPConnection(self.host, self.port, timeout=timeout)
```
  (body otherwise unchanged: Bearer, POST `/api/services/<d>/<s>`, raise on non-2xx, fresh conn, never log token.)

- [ ] **Step 4: Run, verify pass** — `python tests/test_haconn.py` → PASS.

- [ ] **Step 5: Commit** — `git commit -m "feat(resolver): call_service_rest optional timeout"`

---

### Task 3: Replace the say model — `_say` via `play_announcement` + strip superseded machinery (ONE atomic task)

**Files:** `interaction.py`, `tests/test_interaction.py`.

**Interfaces — Produces:** new `_say`; `resolve` drops `hold_ms`; `say` still requires `uri`.

- [ ] **Step 1: Failing tests** — the file's `FakeHA` already records `call_service_rest` into `.calls` and
  returns `self._state` from `get_entity_state`. Add a way for the fake to return a *different* state on the
  second `get_entity_state` (post-announce) — extend `FakeHA` with an optional `states` list it pops through,
  falling back to `_state`. Then add `SayAnnounceTest`:

```python
class SayAnnounceTest(unittest.TestCase):
    def setUp(self):
        self.cap = interaction.InteractionCapability()
        self.zone = "media_player.ceiling_speakers"

    def test_say_calls_play_announcement_with_uri(self):
        ha = FakeHA(playing(0.5)); ctx = FakeCtx(ha)
        r = run(self.cap, ctx, {"mode": "say", "uri": "http://x/a.mp3"})
        self.assertTrue(r["ok"]); self.assertIsNone(r["spoken_text"]); self.assertTrue(r["metadata"]["said"])
        ann = [c for c in ha.calls if c[1] == "play_announcement"]
        self.assertEqual(len(ann), 1)
        self.assertEqual(ann[0][0], "music_assistant")
        self.assertEqual(ann[0][2]["entity_id"], self.zone)
        self.assertEqual(ann[0][2]["url"], "http://x/a.mp3")

    def test_say_replays_station_when_not_resumed(self):     # radio: idle after announce -> re-play captured id
        ha = FakeHA(); ctx = FakeCtx(ha)
        ha.set_states([radio_playing("library://radio/2"), idle_state()])   # before=playing radio, after=idle
        r = run(self.cap, ctx, {"mode": "say", "uri": "http://x/a.mp3"})
        self.assertTrue(r["metadata"]["replayed"])
        pm = [c for c in ha.calls if c[1] == "play_media"]
        self.assertEqual(len(pm), 1)
        self.assertEqual(pm[0][2]["media_id"], "library://radio/2")

    def test_say_no_replay_when_music_resumed(self):         # local music: playing after announce -> no re-play
        ha = FakeHA(); ctx = FakeCtx(ha)
        ha.set_states([playing_with_id(0.5, "library://track/9"), playing_with_id(0.5, "library://track/9")])
        r = run(self.cap, ctx, {"mode": "say", "uri": "http://x/a.mp3"})
        self.assertFalse(r["metadata"]["replayed"])
        self.assertEqual([c for c in ha.calls if c[1] == "play_media"], [])
```
  (Add the small `radio_playing`/`idle_state`/`playing_with_id` helpers + `FakeHA.set_states`/pop-through
  `get_entity_state`.)

- [ ] **Step 2: Run, verify fail.**

- [ ] **Step 3: Implement** — replace `_say` (lock-free, independent of the duck):

```python
    def _say(self, ctx, resolved, rid):
        zone = resolved["zone"]; uri = resolved["uri"]
        timeout = int(getattr(ctx.settings, "say_announce_timeout_ms", 30000)) / 1000.0
        # capture what's playing so we can re-play it if the announcement doesn't auto-resume (radio/live)
        before = ctx.ha.get_entity_state(zone) or {}
        was_playing = before.get("state") == "playing"
        media_id = (before.get("attributes") or {}).get("media_content_id")
        # blocking: MA pauses the music, plays the reply, resumes resumable content
        ctx.ha.call_service_rest("music_assistant", "play_announcement",
                                 {"entity_id": zone, "url": uri}, timeout=timeout)
        replayed = False
        if was_playing and media_id:
            after = ctx.ha.get_entity_state(zone) or {}
            if after.get("state") != "playing":               # radio didn't auto-resume -> re-play the station
                ctx.ha.call_service_rest("music_assistant", "play_media",
                                         {"entity_id": zone, "media_id": media_id})
                replayed = True
        LOG.info("SAY req=%s zone=%s uri=%s replayed=%s", rid, zone, uri, replayed)
        return cr.ok(self.name, rid, "Said.", spoken_text=None,
                     metadata={"said": True, "replayed": replayed, "zone": zone})
```
  Also drop `hold_ms` from `resolve` (return `{"mode","zone","uri"}`); keep the `say` requires-`uri` check in `validate`.

- [ ] **Step 4: Run the NEW tests** — `python tests/test_interaction.py` shows `SayAnnounceTest` green.
  (The old reply-timer say tests now fail against the new `_say` — expected. **Steps 3–9 are ONE atomic
  model-swap with a single green checkpoint at Step 8**; do not commit or gate a review between them. This is
  why the machinery strip + test swap live in the same task — a split would leave the suite red at the boundary.)

- [ ] **Step 5: Strip the superseded machinery — REMOVE-ONLY (do NOT check out an old snapshot).**
  Reverting via `git show d466475` (or any pre-Round-3 snapshot) would **silently drop the Round-3 hardening**
  — F3 (`_auto_restore`'s guarded re-arm) and F5 (`_restore`'s read-failure log). Instead delete only the
  S1b-1 additions from the **current** file; keep everything else:
  - `__init__`: delete `self._gen = 0`; revert the `_snaps` comment to
    `# zone -> {"volume": baseline, "target": last-written, "ts": float, "timer": obj|None}`.
  - Delete methods `_arm_reply_timer` and `_reply_complete` (their only caller left `_say` in Step 3).
  - `_arm_timer` — drop the `secs` param and gen stamping; final form:
```python
    def _arm_timer(self, ctx, zone):
        snap = self._snaps.get(zone)
        if snap is None:
            return
        self._cancel_timer(snap)
        secs = int(getattr(ctx.settings, "max_duck_timeout", 120000)) / 1000.0
        t = self._timer_factory(secs, self._auto_restore, [ctx, zone])
        snap["timer"] = t
        t.start()
```
  - `_auto_restore` — drop the `gen` param + gen-guard and `force=True`; **KEEP the inner try/except re-arm (F3)**:
```python
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
```
  - `_restore` — signature `(self, ctx, zone, rid)`; delete the `reply_active` deferral; drop
    `not ignore_user_override` from the guard; **KEEP the read try/except WARNING (F5)** and write-before-discard body:
```python
    def _restore(self, ctx, zone, rid):
        with self._lock:
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
```

- [ ] **Step 6: Swap the tests** — remove `SayTest`, `SayHoldClampTest`, `Round3FindingsTest`, and the
  `Round2FindingsTest` reply-timer cases; **keep** the AU-02/03 duck/restore/dead-man cases (`RestoreTest`,
  `DeadManTest`, `Round2FindingsTest`'s duck cases), the `say` resolve/validate tests, and `SayAnnounceTest`.

- [ ] **Step 7: Grep-gate** (cheap insurance — fails loudly if the revert was too aggressive or a remnant survived):
```bash
grep -nE "reply_active|ignore_user_override|_gen|_arm_reply_timer|_reply_complete|force=" interaction.py   # expect: no matches
grep -c "read failed" interaction.py      # expect: 1   (F5 kept)
grep -c "re-arm failed" interaction.py    # expect: 1   (F3 kept)
```

- [ ] **Step 8: Run** `python tests/test_interaction.py` → PASS (duck/restore/dead-man + say). **The single
  green checkpoint for Steps 3–8.**

- [ ] **Step 9: Commit** (one commit for the whole model-swap):
```bash
git add interaction.py tests/test_interaction.py
git commit -m "feat(resolver): say via play_announcement; strip superseded reply-timer machinery; keep AU-02/03 Round-3 form"
```

---

### Task 4: Dispatch (silent) + full-suite regression

- [ ] **Step 1:** ensure a `say` dispatch test asserts `core.dispatch(ctx, "interaction", {"mode":"say","uri":…})`
  returns `said:True` and is silent (`spk.said == []`). (Adapt the existing `SayDispatchTest`; `FakeSettings`
  needs `say_announce_timeout_ms`.)
- [ ] **Step 2: Full-suite** — `python -m unittest discover -s tests -p "test_*.py"` → OK, no regressions.
- [ ] **Step 3: Commit** — `git commit -m "test(resolver): say dispatch silent; full-suite green"`

---

## Deployment + validation (gated — NOT part of this plan's code)

Branch-only/ungated above. Deploy is a separate, approval-gated step (`runbooks/resolver-deploy.md`); files:
`haconn.py`, `config.py`, `config.json`, `interaction.py` (+ changed tests for the on-host 3.5.2 run).

Live validation (radio capture/replay already Spike-3-proven):
1. **Local music (the remaining unproven case):** with **local** music playing, `/command say {uri}` → confirm
   the reply is audible, MA **auto-resumes** the music (state `playing` after), and `replayed=false` (no double-play).
2. **Radio (re-confirm end-to-end via the resolver):** with radio playing, `/command say {uri}` → reply audible,
   ceiling `idle` after, resolver re-plays the captured station (`replayed=true`, `playing` again).
3. **S1a composition:** `duck` → `say {uri}` → `restore` (idle) — confirm the un-duck during the paused reply is
   inaudible and the music ends at the pre-duck baseline (B1 no longer applies — music is paused, not ducked-and-playing).
4. No regression to duck/restore/music/radio/news/status.

## Self-review notes

- **Mechanism = Spike-2/3-validated:** `play_announcement` (audible), capture/replay for radio (proven), blocking
  restore-on-return.
- **Simplification:** removes reply timer / `reply_active` / H2 `ignore_user_override` / N1 gen — the fast-return
  model's machinery. `say` is lock-free and independent of the duck; duck/restore reverts to AU-02/03.
- **B1 dissolved:** the reply plays with the music **paused**, so S1a's `idle→restore` un-duck is inaudible.
- **Deferred:** local-music auto-resume is validated at deploy (low risk); S1b-2 (pipeline + firmware + real
  `hold_ms`/media) follows.
