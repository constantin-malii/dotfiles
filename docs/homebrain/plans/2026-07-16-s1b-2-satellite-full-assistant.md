# S1b-2 — Satellite Full-Assistant, Reply on Ceiling (implementation plan)

> **For agentic workers:** REQUIRED SUB-SKILL: use `superpowers:subagent-driven-development` (recommended)
> or `superpowers:executing-plans` to implement this plan slice-by-slice. Steps use `- [ ]` checkboxes.
> **This document is design/planning only.** No slice here is executed by writing the plan; every live
> slice is **approval-gated** and claims the single live-system gate (BACKLOG §10) in its own PR.
>
> Track: **S** · Item: **S1b-2** (`design→HA-live + firmware + resolver`) · builds on **S1b-1′** (deployed,
> dormant) · Parent design: `2026-07-15-s1b-satellite-ceiling-reply-design.md` (§4/§11/§12) · ADR:
> `2026-07-15-s1b-duck-ownership-adr.md` (largely superseded — see §Decision (b)).

**Goal:** turn the reSpeaker satellite into a full assistant whose spoken reply plays on the ceiling —
a new HA Assist pipeline (Whisper + `conversation.openai_conversation` prefer-local + Piper TTS) plus a
reSpeaker firmware redirect (`on_tts_end` suppresses local playback and hands the reply URI to the resolver
`say`), wired end-to-end on top of the already-built, already-validated announce mechanism.

**Architecture:** the settled announce path is **not re-litigated** — the resolver `interaction` `say`
mode already plays a reply URI on `media_player.ceiling_speakers` via `music_assistant.play_announcement`
(blocking; MA pauses the music → plays the reply → resumes resumable content) with radio **capture→replay**
(`library://radio/2`). S1b-2 supplies the two missing halves — the **pipeline** that produces a reply URI and
the **firmware** that redirects it off the satellite into `say` — plus three small, additive `_say`
hardening behaviours deferred from S1b-1′ (block-duration **silent-announce detection**, **internal-base URI
normalisation**, and **restore-on-return** so the ceiling un-ducks deterministically after the reply).

**Tech Stack:** Home Assistant 2026.6.4 (Assist pipelines, Piper/Whisper add-ons, `conversation.openai_conversation`
gpt-4o-mini); ESPHome (formatBCE reSpeaker XVF3800 firmware, OTA); resolver = Python 3.5 (host 3.5.2), stdlib
`unittest`, modules under `docs/homebrain/mass-resolver/`.

---

## Settled mechanism this plan builds on (do NOT re-open)

- **`say` primitive:** `music_assistant.play_announcement(url=<reply-uri>)` on `media_player.ceiling_speakers`
  — **audible**, **blocking ~7 s healthy**, **pause→reply→resume** (not an overlay). Validated live over
  healthy radio (7.2 s) and healthy local music (6.9 s) — CHANGELOG 2026-07-16, design §12.
- **Radio survives via capture→replay:** before the announce, `_say` captures the ceiling
  `media_content_id` (e.g. `library://radio/2`) + `state`; after, if the ceiling did **not** auto-resume
  (radio/live → `idle`), it re-plays the captured id via `music_assistant.play_media`. Local music
  auto-resumes → replay is a no-op. Spike-3 proven live.
- **`say` is deployed and dormant** (S1b-1′, 2026-07-16) — nothing in production invokes it; duck/restore
  currently runs in its AU-02/03 form via the S1a automation.
- **AU-02/AU-03** (resolver duck/restore/announce, live) and **S1a** (satellite→ceiling duck trigger, live)
  are the substrate the reply rides on.

## Carried-forward requirements folded into this plan

1. **Silent-announce detection** — an intermittent, likely **source-independent** degradation can render an
   announce silent (it silenced radio *and* local music on 2026-07-16, including MA's own chime). Healthy
   announce blocks **~7 s**; a silent one blocks **~12–13 s**. S1b-2 must **detect a likely-silent reply**
   (announce block > **~10 s** threshold) and **surface it** — never trust `ok:true`. **Do not assume radio
   replies are immune.** → Slice 1 + Slice 5. (The degradation's root cause is a *separate* reliability
   workstream, out of S1b scope.)
2. **Internal-base URI** — any reply URI handed to `say` must use the **MA-reachable internal base**
   `192.168.122.10:8123`, **not** HA's external base `192.168.1.104` (unreachable from the MA playback path;
   HA `tts_get_url` returns the external base). → Slice 1 (normalise at `say`) + Slice 3 (firmware sends a
   URL `say` can normalise).
3. **Prefer-local determinism + lockstep (NL-01/NL-02)** — switching the satellite's agent to the LLM must
   keep device/media commands **deterministic** (tool-fired, not paraphrased/dropped), and the exposed tool
   set must stay in lockstep with `assistant-capabilities.md`. → Slice 2.

---

## Global Constraints

- **Design/planning only in this document.** No pipeline is created, no firmware is flashed, no resolver
  code is deployed by producing this plan. Execution of each slice is separate and **approval-gated**.
- **One live gate at a time** (BACKLOG §10). S1b-2 touches **resolver + HA + firmware** — the highest-surface
  S-item. Each live slice claims the single `host-live / HA-live / exposure` gate in its own PR and releases
  it on merge. Firmware/OTA is the highest-risk gate and goes **last**.
- **No `media_stop` on the ceiling — ever.** `say` uses `play_announcement` + `play_media` only (Universal→
  Squeezelite wedges on stop). This is inherited from AU-01 and unchanged.
- **Resolver is Python 3.5.2:** no f-strings / type-hints / `async` / `_`-digit separators / `dataclasses`;
  use `%` / `.format()`. Tests = stdlib `unittest`, run from the resolver dir, existing
  `FakeHA`/`FakeSettings`/`FakeCtx`/`FakeTimer` style. Never log tokens/URIs containing secrets.
- **Resolver working dir:** `docs/homebrain/mass-resolver/`. Deploy path + rollback per
  `runbooks/resolver-deploy.md`; on-host backups under `~/mass-resolver/.bak/<ts>/`.
- **Exposure discipline:** `expose_new_entities` stays **off**; no new entity/tool exposure beyond what
  S1b-2 explicitly wires; keep `assistant-capabilities.md` in lockstep (NL-02).
- **No secrets** in repo/docs/logs. **No Claude/AI attribution** in commits or PR text. Keep doc, resolver-code,
  runtime-config, HA, and firmware changes in **separate commits**.

---

## Resolved design decisions (the six open questions)

Each decision below is what the slices implement. **(a)/(b) are load-bearing** and resolved explicitly.

### (a) Is the S1a duck still needed during a `say` turn? — **YES for listening, NO during the reply.**

**Decision.** Keep the S1a duck exactly as it is (AU-02/03 form) for the **listening/processing** phase, and
build **no** reply-turn duck-hold machinery. The duck's role **narrows to the listen phase**.

**Rationale.** The blocking `play_announcement` **pauses** the music for the whole reply, so there is nothing
playing to "duck under" during the reply — AU-01's "duck under TTS overlay" assumed the resolver's
*synthesised* `tts.speak` path, not URL playback (design §11). But while the user is **speaking** and the
pipeline is running STT→LLM→Piper, the ceiling music is still **playing at full volume**; attenuating it
(0.32→0.15 on wake, per S1a) aids the mic/UX. So the duck earns its keep before the reply, not during it.
This confirms the ADR's "B1 dissolves" conclusion without adopting its (now-unneeded) reply-active/
duration-hold mechanism.

**Fallback.** None required — this removes machinery rather than adding it.

### (b) Restore sequencing vs the blocking `say` — **the resolver `say` owns restore; S1a `idle→restore` becomes a grace-G backstop for this satellite.**  ⬅ load-bearing

**Decision.** After the blocking `play_announcement` (and any radio replay) **returns**, `_say` issues the
**restore itself** (single writer, deterministic order: **duck → announce(boost/revert) → replay → restore**).
For this satellite, **repurpose S1a's `idle→restore` to a short grace-G (~2–3 s) backstop** that fires only if
no `say` becomes active (the "URI never arrives" case); the **120 s dead-man** stays as the ultimate backstop.

**Rationale.** The hazard is the **MA auto-revert nesting** (ADR driver #4): `play_announcement` reverts the
ceiling volume to whatever it **captured at announce-start** (the 0.15 duck floor). If S1a's `idle→restore`
fires **early** — the satellite reaches `idle` at/near `on_tts_end`, *while* the announce is still blocking —
it sets the volume to 0.32 mid-announce; MA then reverts to its stale captured **0.15** and resumes the music
**too quiet**, stranding the un-restore. Because the announce **blocks**, the resolver knows the *exact*
moment playback is truly done, so a resolver-issued restore-on-return is trivially exact — **no reply timer,
no duration-hold, no `reply_active` polling** (all the S1b-1 machinery that a fast-return model needed). This
is the ADR's Option-A spirit made simple by the blocking model, and it keeps a **single writer** to ceiling
volume.

**Change called out:** this **modifies S1a's live automation** (drops `idle→restore` for this satellite,
repurposes `idle` to arm grace-G) and **re-couples `_say` to the duck snapshot** (`_snaps`) that S1b-1′
deliberately kept lock-free. Both are deliberate and justified; both are behaviour changes to live pieces and
are gated in Slice 5.

**Convergence spike — pull it forward (review refinement 2026-07-16).** The restore-ownership question is
the load-bearing decision here, and it is **testable now, cheaply, with the already-deployed `say` + S1a
duck — no firmware and no new pipeline**: over `/command`, `duck → say → idle-restore` and observe whether
MA's post-announce revert strands the ceiling at the 0.15 floor or converges to baseline. **Run this
convergence spike early (before the Slice-3 firmware OTA), not only in the Slice-5 E2E**, so
`say_owns_restore` is decided before the brick-risk reflash.

**Default (review refinement 2026-07-16): ship `say_owns_restore=false`** — the simpler, already-deployed,
**lock-free** path (`_say` untouched from S1b-1′; S1a's `idle→restore` unchanged). Re-coupling `_say` to the
`_snaps` snapshot is exactly the shared-state coupling S1b-1′ deliberately removed (the C1/H2/N1 class), so
do **not** adopt it speculatively. The early convergence spike **promotes** to `say_owns_restore=true`
(restore-on-return + the S1a `idle→restore`→grace-G edit) **only if** it demonstrates a strand. Slice 1
still *builds* restore-on-return behind the flag (cheap, unit-tested); the spike, not the default, decides
which path ships.

### (c) Prefer-local determinism + lockstep (NL-01/NL-02) — **prefer-local ON; commands stay tool-deterministic; capabilities doc kept in lockstep; no new exposure.**

**Decision.** The new pipeline runs `conversation.openai_conversation` with **"prefer handling commands
locally" ON**, so HA's built-in intents / sentence-triggers and the exposed resolver tools
(`play_music`/`play_radio`/`find_stations`/`news`) handle device+media commands **deterministically**, and
only **open Q&A** falls to the LLM. Keep `expose_new_entities` **off** (no new entities reachable by the LLM
agent) and update `assistant-capabilities.md` in lockstep with the exposed tool set. Slice 2 verifies a
representative command set stays tool-fired (not paraphrased/dropped) **before** the firmware redirect.

**Rationale.** Exposure is shared across all conversation agents; switching the satellite to the LLM agent is
exposure-adjacent, so it rides the HA-live/exposure gate and the lockstep is mandatory. Prefer-local keeps the
deterministic surface intact on the *primary* pipeline, which is what makes (d)'s single-wake choice safe.

**Fallback.** If prefer-local proves unreliable (commands paraphrased/dropped in testing), fall back to the
**2nd wake/assistant slot** for a local-only deterministic pipeline (see (d)).

### (d) Wake-slot choice — **primary wake → the new pipeline; 2nd slot reserved as documented fallback (not wired).**

**Decision.** Assign the new "Living Room ChatGPT" pipeline to the **primary** wake/assistant slot ("Okay
Nabu"). Leave the **2nd** wake-word/assistant slot **unused but documented** as the fallback for a local-only
deterministic pipeline. Do **not** wire slot-2 in S1b-2.

**Rationale.** S1b's approved target is "the satellite **is** a full assistant" with one wake word — the
simplest UX. Because (c)'s prefer-local keeps commands deterministic on the primary pipeline, a separate
local-only slot is **not** needed for determinism; slot-2 is the escape hatch if prefer-local, cost, or
latency proves unacceptable. Keeping slot-2 unused also avoids a two-pipeline firmware-redirect ambiguity
(the redirect would otherwise route *both* slots' TTS to the ceiling).

**Fallback.** If the primary-only assistant is unacceptable, move LLM Q&A to slot-2's second wake word and
restore the local-only "Living Room Voice" pipeline on primary — a config-only change, no re-flash.

### (e) Latency budget + cost — **budget the real announce floor; suppress media-command speech; local "working" cue.**

**Decision.** Set a **time-to-first-audio-on-ceiling** budget that **includes the ~7 s healthy announce
block**: STT+LLM+Piper (~2–5 s for gpt-4o-mini short answers) **+** ~7 s announce ⇒ **~9–12 s p50 for open
Q&A**. Accept this for Q&A (a spoken paragraph, not a snappy command). For **pure media commands**, default
`speak_confirmations=off` (design §6 tunable) so the *action* (music starting) is the fast confirmation and
the command does not pay the announce cost. Provide a **local "working…" cue** (LED/soft chirp, stays
on-device) during processing so the gap doesn't read as broken. Track per-query gpt-4o-mini cost (small);
measure the end-to-end latency in the Slice-5 spike.

**Rationale.** Design §10's "≤2–3 s time-to-first-audio" target is **unattainable** given `play_announcement`
alone blocks ~7 s; budgeting honestly (and hiding command speech + adding a local cue) is the realistic
stance.

**Fallback.** If measured Q&A latency materially exceeds ~12 s, make the local "working…" cue mandatory and
constrain answer length via the system prompt; re-evaluate gpt-4o vs gpt-4o-mini only under NL-03 (separate,
gated).

### (f) Dropped-reply UX — **local error chirp + LED for a dropped/silent Q&A reply; commands stay silent-on-success.**

**Decision.** When a reply is **dropped or detected likely-silent** (Slice-1 detection: announce block >
~10 s, or `say` error), fire a **local error chirp + LED** on the satellite (feedback stays local per design
§4) so a lost open-Q&A answer is at least **perceptible**. Command turns keep the current
**silent-on-success** contract (the action happened). Make the chirp a tunable, **default ON** for the
dropped-Q&A case.

**Rationale.** A command's silent drop is fine (the action is the confirmation); a dropped **open-Q&A** answer
is total silence with no signal — the one case design §7 flags as warranting a local cue. Tying the cue to the
Slice-1 `likely_silent`/error signal makes it fire exactly when the user would otherwise be left hanging.

**Fallback.** If a firmware-driven chirp proves impractical, downgrade to an **LED-only** error indication
(no audio) — still local, still perceptible.

---

## File structure

| File | Slice | Responsibility / change |
|---|---|---|
| `docs/homebrain/mass-resolver/interaction.py` | 1 | `_say`: add block-duration timing → `likely_silent`; normalise incoming URI host→internal base; add restore-on-return (guarded by `say_owns_restore`). |
| `docs/homebrain/mass-resolver/config.py` + `config.json` | 1 | New tunables: `say_silent_block_ms` (10000), `say_internal_base` (`192.168.122.10:8123`), `say_owns_restore` (true). |
| `docs/homebrain/mass-resolver/tests/test_interaction.py` + `tests/test_config.py` | 1 | Unit tests for the three `_say` behaviours + the tunables. |
| HA Assist pipeline "Living Room ChatGPT" (runtime config, not a repo file) | 2 | Whisper STT + `conversation.openai_conversation` (prefer-local ON) + Piper TTS; assigned to reSpeaker primary slot. |
| `docs/homebrain/assistant-capabilities.md` | 2 | Lockstep: reflect the satellite's LLM agent + exposed tool set (NL-02). |
| reSpeaker ESPHome YAML (device firmware, captured to scratchpad first) | 0, 3 | Slice 0 captures current YAML (rollback artifact); Slice 3 edits `voice_assistant` to suppress local TTS + hand `on_tts_end` URI to `say`, and adds the local error/working cue. |
| `automation.s1a_satellite_ceiling_duck_restore` (HA automation, runtime) | 5 | Repurpose `idle→restore` → grace-G backstop for this satellite (per decision (b)). |
| `docs/homebrain/CHANGELOG.md` (+ proposed BACKLOG note) | each live slice | Record each gated deploy/flash; BACKLOG status change **proposed for INF**, not made unilaterally. |

---

## Slices (ordered; each = deliverable · go/no-go spike · live gate · rollback)

Build order is **resolver hardening → pipeline → firmware → S1a-edit + E2E**, so the brick-risk OTA reflash
lands last and only after everything upstream is green. Each live slice is its own PR and claims the single
gate.

---

### Slice 0 — Reflash precondition: capture current reSpeaker YAML (read-only)

**Deliverable.** The reSpeaker's **current running ESPHome YAML** saved to the session scratchpad (the
rollback artifact the "reversible by reflashing current YAML" guarantee depends on), plus a note of the
current firmware version (ESPHome 2026.6.5 / project 2026.6.0, per S0 §1) and the primary/2nd wake+assistant
slot state (S0 §2). No device change.

- [ ] **Step 1:** From the ESPHome dashboard/config source, export the reSpeaker's full current YAML to
  `scratchpad/respeaker-current-<ts>.yaml`. Confirm it is complete (compiles/round-trips) and diffable.
- [ ] **Step 2:** Record the running firmware version + the `select.…_wake_word` / `select.…_assistant`
  (+ `_2` slots) values, so post-flash drift is detectable.
- [ ] **Step 3:** Confirm the config already defines `on_tts_start` / `on_tts_end` / `on_end` and
  `media_player: external_media_player` (design §3) — the hooks Slice 3 rewires.

**Go/no-go spike.** YAML captured, complete, and diffable → GO. If the current YAML cannot be exported
cleanly, **stop** — do not touch firmware without a rollback image in hand.

**Live gate.** **None** (read-only capture).

**Rollback.** n/a (no change made).

---

### Slice 1 — `_say` hardening: silent-announce detection + internal-base URI + restore-on-return (resolver, repo-code)

**Deliverable.** Three **additive** `_say` behaviours (the announce mechanism itself is unchanged):
1. **Silent-announce detection** — time the `play_announcement` block; if it exceeds `say_silent_block_ms`
   (default 10000), set `metadata.likely_silent=true` (+ `metadata.block_ms`) and emit a WARNING. `ok` stays
   `true` (the announce *was* issued) but the caller can react to `likely_silent`.
2. **Internal-base URI normalisation** — rewrite the incoming URI's host:port to `say_internal_base`
   (`192.168.122.10:8123`) before calling `play_announcement`, so an external-base (`192.168.1.104`) URL from
   the pipeline/firmware is made MA-reachable.
3. **Restore-on-return** — after the announce (+ replay) returns, if `say_owns_restore` is true and a duck
   snapshot exists for the zone, `_say` issues `self._restore(ctx, zone, rid)` (decision (b), single writer).

**Files:** `interaction.py`, `config.py`, `config.json`, `tests/test_interaction.py`, `tests/test_config.py`.

**Interfaces — Produces:** `_say` metadata gains `likely_silent` (bool) + `block_ms` (int); config gains
`say_silent_block_ms` (int ms, 10000), `say_internal_base` (str `host:port`), `say_owns_restore` (bool, true).
**Consumes:** existing `_restore(ctx, zone, rid)`, `_snaps`, `call_service_rest(..., timeout=)` (from S1b-1′),
`FakeHA.set_states` pop-through.

- [ ] **Step 1 — config, failing test.** In `tests/test_config.py` assert
  `Settings({}).say_silent_block_ms == 10000`, `.say_internal_base == "192.168.122.10:8123"`,
  `.say_owns_restore is True`, and that each is overridable. Run → FAIL.
- [ ] **Step 2 — config, implement.** In `config.py`:
  ```python
  # S1b-2 say hardening
  self.say_silent_block_ms = int(cfg.get("say_silent_block_ms", 10000))
  self.say_internal_base = cfg.get("say_internal_base", "192.168.122.10:8123")
  self.say_owns_restore = bool(cfg.get("say_owns_restore", True))
  ```
  In `config.json` add `"say_silent_block_ms": 10000, "say_internal_base": "192.168.122.10:8123",
  "say_owns_restore": true,`. Run `tests/test_config.py` → PASS. Commit code + config separately.
- [ ] **Step 3 — URI normalisation, failing test.** In `SayAnnounceTest`, assert that a URI with the external
  base is rewritten to the internal base in the `play_announcement` call:
  ```python
  def test_say_normalises_uri_to_internal_base(self):
      ha = FakeHA(playing(0.5)); ctx = FakeCtx(ha)
      run(self.cap, ctx, {"mode": "say", "uri": "http://192.168.1.104:8123/api/tts_proxy/x.mp3"})
      ann = [c for c in ha.calls if c[1] == "play_announcement"][0]
      self.assertEqual(ann[2]["url"], "http://192.168.122.10:8123/api/tts_proxy/x.mp3")
  ```
  Run → FAIL.
- [ ] **Step 4 — URI normalisation, implement.** In `_say`, before the announce call, rewrite the host:port
  of `uri` to `ctx.settings.say_internal_base` (parse with stdlib `urlparse`/`urlunparse`; preserve
  path+query; only swap netloc). Run → PASS. Commit.
- [ ] **Step 5 — silent detection, failing test.** Extend `FakeHA`/`FakeCtx` so the fake `call_service_rest`
  for `play_announcement` can be told to "block" a settable number of ms (a fake clock the test advances — do
  **not** sleep). Assert: a 13000 ms block → `metadata["likely_silent"] is True` and `metadata["block_ms"]
  >= 13000`; a 7000 ms block → `likely_silent is False`. Run → FAIL.
- [ ] **Step 6 — silent detection, implement.** In `_say`, wrap the `play_announcement` call with a monotonic
  timer (inject the clock via `ctx`/settings so tests are deterministic — mirror `FakeTimer` style; no real
  sleeps). Compute `block_ms`; if `block_ms > say_silent_block_ms` set `likely_silent=True` and
  `LOG.warning("SAY req=%s likely-silent block_ms=%s (>%s)", rid, block_ms, threshold)`. Add both to the
  returned `metadata`. Run → PASS. Commit.
- [ ] **Step 7 — restore-on-return, failing test.** With `say_owns_restore=True` and a pre-existing duck
  snapshot for the zone (seed `_snaps` via the existing duck path or a helper), assert `_say` calls
  `volume_set` back to the snapshot baseline **after** the `play_announcement` (and after any `play_media`
  replay) — i.e. a `volume_set` appears in `ha.calls` *after* the announce index. With
  `say_owns_restore=False`, assert **no** such `volume_set`. Run → FAIL.
- [ ] **Step 8 — restore-on-return, implement.** In `_say`, after the announce+replay block, if
  `getattr(ctx.settings, "say_owns_restore", True)` and `zone in self._snaps`, call
  `self._restore(ctx, zone, rid)`. Keep it best-effort (a restore failure must not swallow the reply result —
  wrap and log). Run → PASS. Commit.
- [ ] **Step 9 — full suite.** `python -m unittest discover -s tests -p "test_*.py"` → OK, no regressions
  (AU-02/03 duck/restore/dead-man + capture/replay tests still green). Commit `test(resolver): S1b-2 say
  hardening full-suite green`.

**Go/no-go spike.** No live spike needed for the *code* (fully unit-testable). The threshold's separation
(~7 s healthy vs ~12–13 s silent) is already characterised (CHANGELOG 2026-07-16); it is **confirmed live** at
the Slice-1 deploy and again in Slice 5.

**Live gate.** **None** for the branch/tests. The **deploy** is gated (single resolver deploy per
`runbooks/resolver-deploy.md`); it is a small additive change and can be its own gated deploy or fold into the
Slice-5 gate window — sequence with INF. `say` remains dormant until Slice 3 wires a caller, so deploying
Slice 1 early is safe (nothing invokes it).

**Rollback.** `git revert` on the branch; on-host `cp ~/mass-resolver/.bak/<ts>/*.py + config.json && sudo
systemctl restart mass-resolver`.

---

### Slice 2 — New satellite pipeline "Living Room ChatGPT" + capabilities lockstep (HA-live / exposure)

**Deliverable.** A new Assist pipeline **Living Room ChatGPT** = `stt.faster_whisper` +
`conversation.openai_conversation` (**prefer handling commands locally = ON**) + **`tts.piper`**, assigned to
the reSpeaker's **primary** wake/assistant slot (decision (d)). `assistant-capabilities.md` updated in
lockstep with the exposed tool set (decision (c) / NL-02). `expose_new_entities` stays off.

At this slice the reply still plays **locally on the satellite** (firmware not yet redirected) — this is the
intended, safe pre-redirect validation state.

- [ ] **Step 1:** Create the pipeline (Whisper + `conversation.openai_conversation` prefer-local ON + Piper).
  Do **not** assign it yet.
- [ ] **Step 2:** Update `assistant-capabilities.md` so the exposed tool set (`play_music`/`play_radio`/
  `find_stations`/`news` + ceiling controls + weather) and the prompt match what the satellite's LLM agent
  will see. Commit the doc.
- [ ] **Step 3:** Assign **Living Room ChatGPT** to the reSpeaker's **primary** slot (was "Living Room
  Voice").
- [ ] **Step 4 — determinism check (question c):** speak a representative command set — a media command
  (`play_radio`/`play_music`), a device/ceiling control, a timer, `find_stations`, `news` — and confirm each
  **fires the deterministic tool/intent** (not LLM-paraphrased or dropped) and the resolver returns the real
  `chat_text`.
- [ ] **Step 5 — Q&A + Piper check:** ask an open question; confirm it falls to the LLM and **Piper produces a
  spoken reply** (heard **locally** on the satellite for now). Confirm no new entities were exposed
  (`expose_new_entities` still off; exposure snapshot unchanged).
- [ ] **Step 6 — latency baseline (question e):** measure STT→LLM→Piper time-to-local-audio; note per-query
  cost. Record against the ~9–12 s ceiling budget (announce cost is added in Slice 5).

**Go/no-go spike.** GO iff Steps 4–5 pass: commands stay tool-deterministic **and** open Q&A yields a spoken
Piper reply, with **no** new exposure. If commands get paraphrased/dropped → **fallback to (c)/(d)**: local-
only deterministic pipeline on primary, LLM Q&A on the 2nd wake slot; re-scope the firmware redirect
accordingly before Slice 3.

**Live gate.** **HA-live / exposure** (shared conversation surface). Claim the single gate for this slice.

**Rollback.** Reassign the reSpeaker's primary slot back to **Living Room Voice** (local HA agent); `git
revert` the `assistant-capabilities.md` change. Config-only; no re-flash.

---

### Slice 3 — Firmware redirect: suppress local TTS, hand `on_tts_end` URI to `say` (device / OTA — LAST, gated on Slice 0)

> **Precondition (hard):** Slice 0 current-YAML captured in hand · Slice 1 deployed (`say` hardening live) ·
> Slice 2 green (pipeline validated). Highest-risk, brick-risk step — do not start until all three hold.

**Deliverable.** The reSpeaker `voice_assistant` reworked so that:
- the TTS response is **not auto-played** on `external_media_player` (no double-speak / no local reply), while
  **wake + feedback sounds stay on-device**;
- `on_tts_end` **hands the reply URI to the resolver `say`** (via an HA event or `homeassistant.service` →
  the resolver `say` path; the URI need not be pre-normalised — Slice 1's `_say` normalises the base);
- a **local "working…" cue** (LED/soft chirp, decision (e)) shows during processing, and a **local error
  chirp/LED** (decision (f)) is available to fire on a dropped/likely-silent reply.
OTA reflash of the edited YAML.

- [ ] **Step 1 — Spike 1 (go/no-go), on a test build first:** confirm the firmware can **suppress local TTS
  playback** while `on_tts_end` **still delivers the URI**. Validate in a test build/flash **before** the
  committing reflash.
- [ ] **Step 2:** wire `on_tts_end` → resolver `say` (HA event/service). Keep wake/feedback local.
- [ ] **Step 3:** add the local "working…" cue + the error cue (fired by the Slice-1 `likely_silent`/error
  signal, relayed back to the device).
- [ ] **Step 4:** OTA reflash the edited YAML.
- [ ] **Step 5:** smoke test — a single reply routes off the satellite (no local double-speak), the URI
  reaches `say`, and wake/feedback sounds still play locally.

**Go/no-go spike (Spike 1).** Clean local-TTS suppression **with** the `on_tts_end` URI still emitted → GO. If
clean suppression proves impractical → **fallback:** mute the satellite `media_player` during `responding`
(racy — accept only if Spike 1 shows it reliable) or reconsider mechanism **B** (HA plays the pipeline TTS URL
on the ceiling) — **stop and escalate** before adopting B, as it changes S1b-2's shape (splits TTS ownership).

**Live gate.** **Firmware / device (OTA reflash)** — the highest-risk gate. Claim the single gate.

**Rollback.** **Reflash the Slice-0 captured current YAML.** (This is exactly why Slice 0 is a hard
precondition.)

---

### Slice 4 — S1a automation edit: repurpose `idle→restore` to grace-G backstop (HA-live)

**Deliverable.** Per decision (b): for **this satellite**, S1a's `automation.s1a_satellite_ceiling_duck_restore`
no longer fires `restore` directly on `idle`; instead `idle` **arms a ~2–3 s grace-G** that restores **only if
no `say` became active** (URI-never-arrives case). The **120 s dead-man** backstop is unchanged. (`_say` now
owns the normal restore — Slice 1.)

- [ ] **Step 1:** Snapshot the current S1a automation YAML (rollback).
- [ ] **Step 2:** Edit the `idle` branch: replace the immediate `restore` call with the grace-G arm (a
  `delay` + a guard that skips restore if a `say`/reply-active marker is present, else restores).
- [ ] **Step 3:** Reload automations; verify the duck-on-wake still fires and the grace-G path restores when
  no reply arrives (simulate: wake with no follow-through).

**Go/no-go spike.** Validated jointly with Slice 5 (the two are the "restore sequencing" pair). GO iff the
grace-G backstop restores on a no-reply turn **and** does not fire during a real reply (Slice 5 confirms the
real-reply path).

**Live gate.** **HA-live** (behaviour change to a live automation — called out per ADR).

**Rollback.** Re-apply the Step-1 snapshot (restores the plain AU-02/03 `idle→restore`); pairs with setting
`say_owns_restore=false` (Slice 1) if reverting decision (b) wholesale.

---

### Slice 5 — End-to-end validation + restore-sequencing spike (HA-live)

**Deliverable.** The full path proven: **"Okay Nabu, &lt;question&gt;" → spoken reply on the ceiling** over the
listening-ducked / reply-paused music, radio surviving via capture→replay, restore landing cleanly at the
pre-duck baseline, silent replies detected+surfaced+chirped, and latency within budget.

- [ ] **Step 1 — audible reply, both sources:** reply audible on the ceiling over **healthy radio** *and*
  **healthy local music** (block ~7 s each).
- [ ] **Step 2 — restore convergence (the load-bearing spike, question b):** after the reply, the ceiling
  volume returns to the **pre-duck baseline (0.32)** — **not** stranded at the 0.15 floor. Confirms `_say`-owned
  restore sequences correctly after MA's revert. **If** this converges cleanly even with S1a's plain
  `idle→restore`, record the **fallback** applies (keep AU-02/03, `say_owns_restore=false`, revert Slice 4).
- [ ] **Step 3 — radio replay:** radio → `idle` after the announce → captured `library://radio/2` re-played →
  station resumes; local music auto-resumes (no double-play).
- [ ] **Step 4 — silent detection + dropped-Q&A UX (questions 1/f):** force/observe a degraded-stream announce
  (block > ~10 s) → `_say` returns `likely_silent=true` → the satellite fires the **local error chirp/LED**;
  confirm a healthy reply does **not** chirp. Do not assume radio is immune — test over radio too.
- [ ] **Step 5 — latency + cost (question e):** measure ceiling time-to-first-audio (target ~9–12 s p50 Q&A);
  confirm the local "working…" cue covers the gap; note per-query cost. Confirm media commands with
  `speak_confirmations=off` don't pay the announce cost.
- [ ] **Step 6 — barge-in:** a re-trigger during a ceiling reply → the new `say` replaces the in-flight
  announce (MA replace); restore fires only after the latest reply.
- [ ] **Step 7 — no regressions:** duck/restore/music/radio/news/status all unaffected.

**Go/no-go spike (Spike-E2E).** GO iff Steps 1–4 pass. The **decision point** for (b)'s fallback is Step 2.

**Live gate.** **HA-live** (firmware already live from Slice 3; this is the wiring/validation).

**Rollback.** Reassign primary pipeline → Living Room Voice (Slice 2 rollback) · re-apply S1a snapshot
(Slice 4 rollback) · `say_owns_restore=false` (Slice 1) · reflash Slice-0 YAML (Slice 3 rollback). Peeling the
slices back in reverse order returns the system to its pre-S1b-2 state.

---

## Deployment / gating summary

| Order | Slice | Live gate | Rollback anchor |
|---|---|---|---|
| 0 | Capture current YAML | none (read-only) | n/a |
| 1 | `_say` hardening (resolver) | resolver deploy (single) | `git revert` + on-host `.bak` restore |
| 2 | New pipeline + caps lockstep | HA-live / exposure | reassign to Living Room Voice + revert doc |
| 3 | Firmware redirect (OTA) | firmware/device (highest risk) | **reflash Slice-0 YAML** |
| 4 | S1a `idle→restore` → grace-G | HA-live | re-apply S1a snapshot |
| 5 | End-to-end validation | HA-live | peel slices 2→4→1→3 back |

**One gate at a time** (BACKLOG §10) — slices 2–5 each claim/release the single gate in their own PR; slice 1
deploys under its own gated window (or folds into slice 5's). Firmware (slice 3) is deliberately last.

---

## Self-review

- **Design questions (a–f):** each has an explicit decision + rationale + fallback above; (a)/(b) resolved as
  the load-bearing pair (duck narrows to listening; `say` owns restore, S1a `idle→restore`→grace-G).
- **Carried-forward requirements land in specific slices, not just the preamble:** silent-announce detection →
  Slice 1 (code) + Slice 5 (live); internal-base URI → Slice 1; prefer-local/lockstep (NL-01/NL-02) →
  Slice 2.
- **Firmware reflash is last, behind a hard "capture current YAML" precondition** (Slice 0 → Slice 3).
- **Each slice has deliverable · go/no-go spike · live gate (or "none") · rollback.**
- **Mechanism not re-opened:** everything rides `play_announcement` + capture/replay; the only `_say` changes
  are the three *additive* hardenings (silent-detect, URI-norm, restore-on-return) — the announce primitive
  and radio replay are untouched. Restore-on-return re-couples `_say` to `_snaps` (a deliberate, called-out
  change from S1b-1′'s lock-free form).
- **Scope honesty:** the announce-silence **root cause** is a *separate reliability workstream* (not S1b-2);
  S1b-2 only **detects/surfaces** it. No BACKLOG edit is made here — a status note is **proposed for INF**
  (below).
- **First slice to execute:** **Slice 1** (`_say` hardening) — pure repo-code + unit tests, no live gate for
  the branch; it de-risks the two carried-forward requirements and the (b) restore mechanism before any live
  or firmware step. Its deploy is the smallest gated action and leaves `say` dormant until Slice 3 wires it.

---

## Proposed BACKLOG note (for INF to reconcile — not applied here)

> `S1b`–`S4` row · **proposed** update: S1b-2 **planned** (`plans/2026-07-16-s1b-2-satellite-full-assistant.md`)
> on top of the 2026-07-16 announce root-cause (GO on the mechanism). Slices: resolver `say` hardening
> (silent-detect + internal-base URI + restore-on-return) → new "Living Room ChatGPT" pipeline (prefer-local)
> → firmware redirect (OTA, last) → S1a `idle→restore`→grace-G + E2E. Still `blocked`/`design→…` until the
> first live gate is claimed; recommend leaving the row's status to INF.

---

> **Rollback for this document:** `git revert` on `homebrain/s1b-2-satellite-full-assistant-plan`, or delete
> this file. No secrets, no implementation, no firmware/exposure change, no live gate claimed.
