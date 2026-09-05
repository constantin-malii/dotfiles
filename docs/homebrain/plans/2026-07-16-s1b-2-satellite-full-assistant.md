# S1b-2 — Satellite Full-Assistant, Reply on Ceiling (implementation plan)

> **For agentic workers:** REQUIRED SUB-SKILL: use `superpowers:subagent-driven-development` (recommended)
> or `superpowers:executing-plans` to implement this plan slice-by-slice. Steps use `- [ ]` checkboxes.
> **This document is design/planning only.** No slice here is executed by writing the plan; every live
> slice is **approval-gated** and claims the single live-system gate (BACKLOG §10) in its own PR.
>
> Track: **S** · Item: **S1b-2** (`design→HA-live + firmware + resolver`) · builds on **S1b-1′** (deployed,
> dormant) · Parent design: `2026-07-15-s1b-satellite-ceiling-reply-design.md` (§4/§11/§12/**§13**) · ADR:
> `2026-07-15-s1b-duck-ownership-adr.md`.

> ### ⚠️ REVISED 2026-07-17 — mechanism changed from `play_announcement` to `play_media`
> This plan was first written 2026-07-16 on the premise that `music_assistant.play_announcement` is the
> **audible** reply primitive. The **2026-07-17 diagnostic (CHANGELOG; design §13) disproved that**:
> `play_announcement` (and `tts.speak`) are **deterministically silent** on the ceiling (the announce/overlay
> path is broken on this Universal→Squeezelite player), while **plain `media_player.play_media` of the exact
> same reply clip is audible** — validated live end-to-end (*music → reply → music*). This revision **re-opens
> the mechanism** (the earlier "do NOT re-open" was based on the false premise) and rebuilds Slice 1 + decisions
> (a)/(b)/(e) around `play_media` + capture/replay. Slices 2 (pipeline) and 3 (firmware) are largely unchanged
> — they are independent of which `_say` primitive delivers the audio.

**Goal:** turn the reSpeaker satellite into a full assistant whose spoken reply plays on the ceiling —
a new HA Assist pipeline (Whisper + `conversation.openai_conversation` prefer-local + Piper TTS) plus a
reSpeaker firmware redirect (`on_tts_end` suppresses local playback and hands the reply URI to the resolver
`say`), wired end-to-end on top of the **audible `play_media` reply route** proven on 2026-07-17.

**Architecture:** the reply mechanism is the **`play_media` route** (design §13): `_say` **captures** the
ceiling source (state / `media_content_id` / volume), **sets a reply volume**, **`play_media`s the reply URI**
(replaces the stream, audible, non-blocking), **polls** the player until the clip finishes, **restores** the
volume, and **re-plays the captured source** (radio → `library://radio/2`; local music → the prior item —
handled uniformly since the reply replaced the queue). **No `media_stop`** (Universal→Squeezelite wedges on
stop). S1b-2 supplies the two missing halves — the **pipeline** that produces a reply URI and the **firmware**
that redirects it off the satellite into `say` — and reworks `_say` from the silent announce/overlay to this
audible route (Slice 1).

**Tech Stack:** Home Assistant 2026.6.4 (Assist pipelines, Piper/Whisper add-ons, `conversation.openai_conversation`
gpt-4o-mini); ESPHome (formatBCE reSpeaker XVF3800 firmware, OTA); resolver = Python 3.5 (host 3.5.2), stdlib
`unittest`, modules under `docs/homebrain/mass-resolver/`.

---

## Mechanism this plan builds on (the audible route — proven 2026-07-17)

- **`say` primitive:** `music_assistant.play_media(media_content_id=<reply-uri>, media_content_type=music)` on
  `media_player.ceiling_speakers` — **audible**, **non-blocking** (returns ~instantly), and it **replaces** the
  current stream with the reply clip (replace-not-overlay). The announce/overlay primitives
  (`play_announcement`, `tts.speak`) are **silent on this player** and are **not used**.
- **Completion by polling (not duration):** after `play_media`, poll the ceiling every ~0.5 s until the clip
  **ends** (state leaves `playing`, or `media_content_id` changes away from the reply URI), capped by a
  timeout. `media_duration` reads **0** for the clip, so duration math is unusable — polling is the robust
  signal. Design §13 / CHANGELOG 2026-07-17.
- **Source survives via capture→replay:** before the reply, `_say` captures the ceiling `media_content_id`
  (e.g. `library://radio/2`) + `state` + `volume_level`; after the clip ends it **re-plays the captured id**
  via `play_media`. Because the reply *replaced* the queue, the replay is needed for **both** radio and local
  music (not just radio) — validated live (*music → reply → music*).
- **Reply volume:** because the reply fires during the S1a listening-duck (ceiling pulled to ~0.15),
  `play_media` at the current volume would be too quiet. `_say` sets a **`reply_volume`** for the clip, then
  restores. See decision (b) for who owns the final baseline restore.
- **No auto-resume, no MA auto-revert:** unlike `play_announcement`, `play_media` does **not** pause/auto-resume
  and does **not** MA-revert the volume — `_say` owns the volume and the replay explicitly. This *removes* the
  auto-revert-nesting hazard the 07-16 draft worried about.
- **AU-02/AU-03** (resolver duck/restore, live) and **S1a** (satellite→ceiling duck trigger, live) are the
  substrate the reply rides on. The **overlay-path silence** is a *separate reliability workstream* (design §13
  / CHANGELOG 2026-07-17) — S1b-2 does not depend on fixing it.

## Carried-forward requirements folded into this plan

1. **Reply-started guard (replaces "block > ~10 s silent-detection").** With `play_media` the old
   block-duration heuristic is moot (the call returns instantly, and the overlay path it measured is silent by
   design). The new signal: after `play_media`, confirm the clip actually **reached `playing`** (cid = reply
   URI) within `say_start_timeout`. If it never starts, mark `metadata.reply_started=false` /
   `likely_silent=true`, **do not report a successful spoken reply**, but still **restore volume + replay** the
   source so the ceiling is never left stuck. → Slice 1 + Slice 5. **Do not assume radio is immune.**
2. **Internal-base URI** — the reply URI handed to `say` must use the **MA-reachable internal base**
   `192.168.122.10:8123`, **not** HA's external base `192.168.1.104` (unreachable from the MA playback path;
   HA `tts_get_url` returns the external base). This still applies: MA must **fetch** the reply URI for
   `play_media`. → Slice 1 (normalise at `say`) + Slice 3 (firmware sends a URL `say` can normalise).
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
- **No `media_stop` on the ceiling — ever.** `say` uses `play_media` (replace) + `volume_set` only (Universal→
  Squeezelite wedges on stop). Inherited from AU-01 and unchanged.
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

### (a) Is the S1a duck still needed during a `say` turn? — **YES for listening; during the reply `_say` sets the reply volume itself.**

**Decision.** Keep the S1a duck (AU-02/03 form) for the **listening/processing** phase. During the **reply**,
`_say` explicitly sets `reply_volume` for the clip (the reply *replaces* the stream, so there is no music to
"duck under"), then restores. No separate reply-turn duck machinery.

**Rationale.** While the user is **speaking** and STT→LLM→Piper runs, the ceiling music is still playing;
attenuating it (0.32→0.15 on wake, per S1a) aids the mic/UX — the duck earns its keep **before** the reply.
During the reply the `play_media` clip is the only audio (it replaced the stream), so the relevant control is
its **volume**, which `_say` owns (set `reply_volume`, restore after). This confirms the ADR's "reply-active
duck machinery not needed" conclusion — for `play_media` because there is nothing concurrent to duck, rather
than because of a blocking pause.

**Fallback.** None required — this adds only a volume set/restore, not a hold loop.

### (b) Restore sequencing vs the polling `say` — **the resolver `say` owns the reply-turn restore (to the pre-duck baseline); S1a `idle→restore` becomes a grace-G backstop for this satellite.**  ⬅ load-bearing

**Decision.** `_say` runs the whole reply turn as a single writer: **set `reply_volume` → `play_media` reply →
poll until the clip ends → restore the pre-duck baseline volume → re-play the captured source.** For this
satellite, **repurpose S1a's `idle→restore` to a short grace-G (~2–3 s) backstop** that fires only if no `say`
becomes active (the "URI never arrives" case); the **120 s dead-man** stays as the ultimate backstop.

**Rationale (updated for `play_media`).** The hazard is a **timing race**, not MA auto-revert: `on_tts_end`
hands the URI to `_say` and the satellite then reaches `idle` — but `_say`'s poll spans the whole reply
(~clip length). If S1a's `idle→restore` fires **during** that window it would move the volume mid-reply, then
`_say`'s own restore would fight it — the same strand class the 07-16 draft feared, now caused by
poll-duration overlap rather than a blocking-announce revert. Because `_say` **polls to completion**, it knows
the exact moment the reply is done, so a `_say`-owned restore-on-completion is exact, with a **single writer**
to ceiling volume. `_say` must restore to the **pre-duck baseline** (0.32), which it reads from S1a's duck
snapshot (`_snaps`) — a deliberate, called-out re-coupling to `_snaps` (S1b-1′ kept `_say` lock-free; this
adds a brief, lock-guarded read/restore).

**Change called out:** this **modifies S1a's live automation** (drops `idle→restore` for this satellite,
repurposes `idle` to arm grace-G) and **re-couples `_say` to `_snaps`**. Both are deliberate; both are
behaviour changes to live pieces and are gated (Slice 4).

**Convergence spike — pull it forward.** The restore-ownership question is testable **now, cheaply, over
`/command`, with no firmware and no new pipeline**: with music playing, `duck → say(test URI) → idle` and
observe whether the ceiling converges to the pre-duck baseline or is left at the 0.15 floor / a mid-reply
value. **Run this early (before the Slice-3 firmware OTA)**, so `say_owns_restore` is decided before the
brick-risk reflash.

**Default: ship `say_owns_restore=true`** here — unlike the 07-16 draft (which defaulted `false` to avoid
re-coupling under the *blocking* model), the `play_media` model **needs** `_say` to own volume anyway (it sets
`reply_volume` and replays the source), so owning the final baseline restore is the coherent, single-writer
choice. Slice 1 still gates it behind `say_owns_restore` so the spike can fall back to `false` (leave volume as
`_say` captured it and let S1a `idle→restore` handle the baseline) if the convergence spike shows that path
converges cleanly.

### (c) Prefer-local determinism + lockstep (NL-01/NL-02) — **prefer-local ON; commands stay tool-deterministic; capabilities doc kept in lockstep; no new exposure.**

**Decision.** The new pipeline runs `conversation.openai_conversation` with **"prefer handling commands
locally" ON**, so HA's built-in intents / sentence-triggers and the exposed resolver tools
(`play_music`/`play_radio`/`find_stations`/`news`) handle device+media commands **deterministically**, and
only **open Q&A** falls to the LLM. Keep `expose_new_entities` **off** and update `assistant-capabilities.md`
in lockstep with the exposed tool set. Slice 2 verifies a representative command set stays tool-fired **before**
the firmware redirect.

**Rationale.** Exposure is shared across all conversation agents; switching the satellite to the LLM agent is
exposure-adjacent, so it rides the HA-live/exposure gate and the lockstep is mandatory. Prefer-local keeps the
deterministic surface intact on the *primary* pipeline, which makes (d)'s single-wake choice safe.

**Fallback.** If prefer-local proves unreliable (commands paraphrased/dropped in testing), fall back to the
**2nd wake/assistant slot** for a local-only deterministic pipeline (see (d)).

### (d) Wake-slot choice — **primary wake → the new pipeline; 2nd slot reserved as documented fallback (not wired).**

**Decision.** Assign the new "Living Room ChatGPT" pipeline to the **primary** wake/assistant slot ("Okay
Nabu"). Leave the **2nd** wake-word/assistant slot **unused but documented** as the fallback for a local-only
deterministic pipeline. Do **not** wire slot-2 in S1b-2.

**Rationale.** S1b's approved target is "the satellite **is** a full assistant" with one wake word — the
simplest UX. Because (c)'s prefer-local keeps commands deterministic on the primary pipeline, a separate
local-only slot is **not** needed for determinism; slot-2 is the escape hatch if prefer-local, cost, or
latency proves unacceptable. Keeping slot-2 unused also avoids a two-pipeline firmware-redirect ambiguity.

**Fallback.** If the primary-only assistant is unacceptable, move LLM Q&A to slot-2's second wake word and
restore the local-only "Living Room Voice" pipeline on primary — a config-only change, no re-flash.

### (e) Latency budget + cost — **no announce block; time-to-first-audio improves; suppress media-command speech; local "working" cue.**

**Decision.** With `play_media` the reply audio starts ~immediately after the call (no ~7 s announce block),
so **time-to-first-audio-on-ceiling ≈ STT+LLM+Piper (~2–5 s for gpt-4o-mini short answers) + ~1 s play_media
start** ⇒ **~3–6 s p50 for open Q&A** — materially better than the 07-16 estimate. For **pure media commands**,
default `speak_confirmations=off` (design §6 tunable) so the *action* (music starting) is the fast
confirmation. Provide a **local "working…" cue** (LED/soft chirp, on-device) during processing. Track per-query
gpt-4o-mini cost (small); measure end-to-end latency in the Slice-5 spike. **Note:** the reply *turn* still
occupies the ceiling for `reply_length + replay` (music is replaced, not overlaid) — budget the **turn**
duration for UX, distinct from time-to-first-audio.

**Rationale.** Design §10's "≤2–3 s time-to-first-audio" target is now **near-attainable** (the ~7 s announce
block that made it impossible is gone). The residual latency is the pipeline (STT→LLM→Piper), not playback.

**Fallback.** If measured Q&A latency exceeds budget, make the local "working…" cue mandatory and constrain
answer length via the system prompt; re-evaluate gpt-4o vs gpt-4o-mini only under NL-03 (separate, gated).

### (f) Dropped-reply UX — **local error chirp + LED for a dropped/never-started Q&A reply; commands stay silent-on-success.**

**Decision.** When a reply is **dropped or never starts** (Slice-1 guard: `reply_started=false` / `say`
error), fire a **local error chirp + LED** on the satellite (feedback stays local per design §4) so a lost
open-Q&A answer is **perceptible**. Command turns keep the **silent-on-success** contract. Chirp is a tunable,
**default ON** for the dropped-Q&A case.

**Rationale.** A command's silent drop is fine (the action is the confirmation); a dropped **open-Q&A** answer
is total silence with no signal. Tying the cue to the Slice-1 `reply_started`/error signal makes it fire
exactly when the user would otherwise be left hanging.

**Fallback.** If a firmware-driven chirp proves impractical, downgrade to **LED-only** (still local, still
perceptible).

---

## File structure

| File | Slice | Responsibility / change |
|---|---|---|
| `docs/homebrain/mass-resolver/interaction.py` | 1 | `_say`: replace `play_announcement` with **`play_media` + poll-to-completion**; capture source (state/cid/volume) + **barge-in gen-id**; set/restore `reply_volume`; **reply-started guard** → `reply_started`/`likely_silent`; normalise incoming URI host→internal base; **replay** the captured source; restore-on-completion (guarded by `say_owns_restore`). |
| `docs/homebrain/mass-resolver/config.py` + `config.json` | 1 | New tunables: `reply_volume` (0.40), `say_start_timeout_ms` (5000), `say_reply_timeout_ms` (30000), `say_poll_ms` (500), `say_internal_base` (`192.168.122.10:8123`), `say_owns_restore` (true). **Retire** `say_announce_timeout_ms`. |
| `docs/homebrain/mass-resolver/tests/test_interaction.py` + `tests/test_config.py` | 1 | Unit tests: normal finish, never-starts (guard), barge-in supersede, radio vs local replay, volume set/restore, URI normalisation, tunables. |
| HA Assist pipeline "Living Room ChatGPT" (runtime config, not a repo file) | 2 | Whisper STT + `conversation.openai_conversation` (prefer-local ON) + Piper TTS; assigned to reSpeaker primary slot. |
| `docs/homebrain/assistant-capabilities.md` | 2 | Lockstep: reflect the satellite's LLM agent + exposed tool set (NL-02). |
| reSpeaker ESPHome YAML (device firmware, captured to scratchpad first) | 0, 3 | Slice 0 captures current YAML (rollback artifact); Slice 3 edits `voice_assistant` to suppress local TTS + hand `on_tts_end` URI to `say`, and adds the local error/working cue. |
| `automation.s1a_satellite_ceiling_duck_restore` (HA automation, runtime) | 4 | Repurpose `idle→restore` → grace-G backstop for this satellite (decision (b)). |
| `docs/homebrain/CHANGELOG.md` (+ proposed BACKLOG note) | each live slice | Record each gated deploy/flash; BACKLOG status change **proposed for INF**, not made unilaterally. |

---

## Slices (ordered; each = deliverable · go/no-go spike · live gate · rollback)

Build order is **resolver rework → pipeline → firmware → S1a-edit + E2E**, so the brick-risk OTA reflash
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

### Slice 1 — `_say` rework: `play_media` + poll + capture/replay + reply-started guard (resolver, repo-code)

**Deliverable.** `_say` reworked from the silent `play_announcement` overlay to the audible `play_media`
route (design §13). The capability shell + validation are unchanged; the `execute` body changes.

**New `_say` flow:**
1. **Capture** before-state: `was_playing`, `source_id` (`media_content_id`), `prev_volume`.
2. **Barge-in guard:** bump a per-zone generation id under `_lock`; remember this call's `gen`. Later steps
   abort if `gen` is stale (a newer `say` started) — only the latest reply restores/replays.
3. **Normalise** the reply URI host:port → `say_internal_base` (MA must fetch it).
4. **Set reply volume** → `reply_volume` via `call_service_rest("media_player","volume_set")`.
5. **`play_media`** the reply URI (`music_assistant.play_media`, `media_content_type=music`) — replace,
   non-blocking.
6. **Confirm start:** poll every `say_poll_ms` up to `say_start_timeout_ms` until state=`playing` and cid=reply
   URI. If it never starts → `reply_started=false` / `likely_silent=true`, skip the wait (go to 8).
7. **Wait for end:** poll every `say_poll_ms` up to `say_reply_timeout_ms` until state≠`playing` or cid≠reply
   URI.
8. **Restore volume** → the pre-duck baseline if `say_owns_restore` and a `_snaps` snapshot exists (decision
   (b)); else restore `prev_volume`. Best-effort (a restore failure must not swallow the reply result).
9. **Replay source:** if `was_playing` and `source_id` and `gen` still current, `play_media(source_id)`.

**Guard replaces the block>10 s heuristic:** the silent signal is now **"the clip never reached `playing`"**
(`reply_started=false`). `ok` may stay `true` (the call was issued) but `metadata.likely_silent=true` tells the
caller (Slice 3 chirp) not to treat it as a delivered answer. **No sleeps in tests** — inject the clock/poll so
poll sequences are deterministic (mirror `FakeTimer`).

**Files:** `interaction.py`, `config.py`, `config.json`, `tests/test_interaction.py`, `tests/test_config.py`.

**Interfaces — Produces:** `_say` metadata gains `reply_started` (bool), `likely_silent` (bool), `replayed`
(bool); config gains `reply_volume` (float 0.40), `say_start_timeout_ms` (5000), `say_reply_timeout_ms`
(30000), `say_poll_ms` (500), `say_internal_base` (`192.168.122.10:8123`), `say_owns_restore` (true).
**Consumes:** `call_service_rest`, `get_entity_state`, `_snaps`, `_restore`, `_lock`; a pollable/injectable
clock + state-reader in `FakeHA` (extend the fake so scripted poll sequences drive start/finish).

- [ ] **Step 1 — config, failing test.** In `tests/test_config.py` assert the six new defaults and that each
  is overridable; assert `say_announce_timeout_ms` is gone (or ignored). Run → FAIL.
- [ ] **Step 2 — config, implement.** Add the tunables in `config.py`; add them to `config.json`; remove
  `say_announce_timeout_ms`. Run → PASS. Commit code + config separately.
- [ ] **Step 3 — URI normalisation, failing test then implement.** External-base URI → rewritten to
  `say_internal_base` in the `play_media` call (stdlib `urlparse`/`urlunparse`, swap netloc only). FAIL→PASS,
  commit.
- [ ] **Step 4 — happy path (poll-to-completion + replay), failing test.** Fake a poll sequence: after
  `play_media`, state=`playing`/cid=reply for N polls then cid=source/`idle`. Assert: `volume_set` to
  `reply_volume` **before** `play_media`; `play_media(reply)`; then `play_media(source_id)` replay after the
  clip ends; `reply_started=true`, `replayed=true`. Run → FAIL, then implement the flow. PASS, commit.
- [ ] **Step 5 — reply-started guard, failing test.** Fake a sequence where the clip **never** reaches
  `playing` within `say_start_timeout_ms`. Assert `reply_started=false`, `likely_silent=true`, **and** volume
  restore + source replay **still** happen (ceiling not left stuck). FAIL→implement→PASS, commit.
- [ ] **Step 6 — barge-in supersede, failing test.** Simulate a second `say` bumping `gen` mid-poll; assert
  the first call **aborts** its restore/replay (no `volume_set`/`play_media(source)` after supersede) and the
  latest call owns the finish. FAIL→implement (gen check under `_lock`)→PASS, commit.
- [ ] **Step 7 — restore ownership, failing test.** With `say_owns_restore=true` and a seeded `_snaps`
  baseline, assert the post-clip `volume_set` targets the **baseline** (not `prev_volume`); with `false`,
  targets `prev_volume`. FAIL→implement→PASS, commit.
- [ ] **Step 8 — full suite.** `python -m unittest discover -s tests -p "test_*.py"` → OK, no regressions
  (AU-02/03 duck/restore/dead-man still green). Commit `test(resolver): S1b-2 say play_media rework full-suite green`.

**Go/no-go spike (convergence, decision (b)).** Over `/command` with music playing:
`duck → say(test tts_proxy URI) → idle`. Confirm (i) the reply is **audible**, (ii) the source **replays**
(radio via `library://radio/2`; local resumes), (iii) the ceiling **converges to the pre-duck baseline**
(not stranded at 0.15). Decides `say_owns_restore` true/false. Run **before** the Slice-3 OTA. (This is the
same *music → reply → music* flow validated ad-hoc on 2026-07-17; formalise it here.)

**Live gate.** **None** for the branch/tests. The **deploy** is gated (single resolver deploy per
`runbooks/resolver-deploy.md`); small change; `say` stays dormant until Slice 3 wires a caller, so deploying
early is safe.

**Rollback.** `git revert` on the branch; on-host `cp ~/mass-resolver/.bak/<ts>/*.py + config.json && sudo
systemctl restart mass-resolver`.

---

### Slice 2 — New satellite pipeline "Living Room ChatGPT" + capabilities lockstep (HA-live / exposure)

**Deliverable.** A new Assist pipeline **Living Room ChatGPT** = `stt.faster_whisper` +
`conversation.openai_conversation` (**prefer handling commands locally = ON**) + **`tts.piper`**, assigned to
the reSpeaker's **primary** wake/assistant slot (decision (d)). `assistant-capabilities.md` updated in
lockstep (decision (c) / NL-02). `expose_new_entities` stays off. At this slice the reply still plays
**locally on the satellite** (firmware not yet redirected) — the intended, safe pre-redirect validation state.

- [ ] **Step 1:** Create the pipeline (Whisper + `conversation.openai_conversation` prefer-local ON + Piper).
  Do **not** assign it yet.
- [ ] **Step 2:** Update `assistant-capabilities.md` so the exposed tool set (`play_music`/`play_radio`/
  `find_stations`/`news` + ceiling controls + weather) and the prompt match what the satellite's LLM agent
  will see. Commit the doc.
- [ ] **Step 3:** Assign **Living Room ChatGPT** to the reSpeaker's **primary** slot (was "Living Room Voice").
- [ ] **Step 4 — determinism check (question c):** speak a representative command set — a media command,
  a device/ceiling control, a timer, `find_stations`, `news` — and confirm each **fires the deterministic
  tool/intent** (not LLM-paraphrased or dropped) and the resolver returns the real `chat_text`.
- [ ] **Step 5 — Q&A + Piper check:** ask an open question; confirm it falls to the LLM and **Piper produces a
  spoken reply** (heard **locally** on the satellite for now). Confirm no new entities were exposed.
- [ ] **Step 6 — latency baseline (question e):** measure STT→LLM→Piper time-to-local-audio; note per-query
  cost. Record against the ~3–6 s time-to-first-audio budget (playback cost added in Slice 5).

**Go/no-go spike.** GO iff Steps 4–5 pass: commands stay tool-deterministic **and** open Q&A yields a spoken
Piper reply, with **no** new exposure. If commands get paraphrased/dropped → **fallback to (c)/(d)**.

**Live gate.** **HA-live / exposure** (shared conversation surface). Claim the single gate.

**Rollback.** Reassign the reSpeaker's primary slot back to **Living Room Voice**; `git revert` the
`assistant-capabilities.md` change. Config-only; no re-flash.

---

### Slice 3 — Firmware redirect: suppress local TTS, hand `on_tts_end` URI to `say` (device / OTA — LAST, gated on Slice 0)

> **Precondition (hard):** Slice 0 current-YAML captured · Slice 1 deployed (`say` `play_media` rework live) ·
> Slice 2 green (pipeline validated). Highest-risk, brick-risk step — do not start until all three hold.

**Deliverable.** The reSpeaker `voice_assistant` reworked so that:
- the TTS response is **not auto-played** on `external_media_player` (no double-speak / no local reply), while
  **wake + feedback sounds stay on-device**;
- `on_tts_end` **hands the reply URI to the resolver `say`** (via an HA event or `homeassistant.service`; the
  URI need not be pre-normalised — Slice 1's `_say` normalises the base);
- a **local "working…" cue** (LED/soft chirp, decision (e)) shows during processing, and a **local error
  chirp/LED** (decision (f)) fires on a dropped / `reply_started=false` reply.
OTA reflash of the edited YAML.

- [ ] **Step 1 — Spike 1 (go/no-go), on a test build first:** confirm the firmware can **suppress local TTS
  playback** while `on_tts_end` **still delivers the URI**. Validate in a test build/flash **before** the
  committing reflash.
- [ ] **Step 2:** wire `on_tts_end` → resolver `say` (HA event/service). Keep wake/feedback local.
- [ ] **Step 3:** add the local "working…" cue + the error cue (fired by the Slice-1 `reply_started`/error
  signal relayed back to the device).
- [ ] **Step 4:** OTA reflash the edited YAML.
- [ ] **Step 5:** smoke test — a single reply routes off the satellite (no local double-speak), the URI
  reaches `say`, the reply is **audible on the ceiling**, and wake/feedback sounds still play locally.

**Go/no-go spike (Spike 1).** Clean local-TTS suppression **with** the `on_tts_end` URI still emitted → GO. If
clean suppression proves impractical → **fallback:** mute the satellite `media_player` during `responding`
(racy — accept only if reliable) or reconsider mechanism **B** (HA plays the reply URL on the ceiling) —
**stop and escalate** before adopting B (it splits TTS ownership).

**Live gate.** **Firmware / device (OTA reflash)** — the highest-risk gate. Claim the single gate.

**Rollback.** **Reflash the Slice-0 captured current YAML.**

---

### Slice 4 — S1a automation edit: repurpose `idle→restore` to grace-G backstop (HA-live)

**Deliverable.** Per decision (b): for **this satellite**, S1a's `automation.s1a_satellite_ceiling_duck_restore`
no longer fires `restore` directly on `idle`; instead `idle` **arms a ~2–3 s grace-G** that restores **only if
no `say` became active** (URI-never-arrives case). The **120 s dead-man** backstop is unchanged. (`_say` now
owns the normal reply-turn restore — Slice 1, `say_owns_restore=true`.) **If** the Slice-1 convergence spike
showed the ceiling converges cleanly with S1a's plain `idle→restore` (i.e. `say_owns_restore=false` shipped),
**skip this slice** and leave S1a unchanged.

- [ ] **Step 1:** Snapshot the current S1a automation YAML (rollback).
- [ ] **Step 2:** Edit the `idle` branch: replace the immediate `restore` with the grace-G arm (a `delay` + a
  guard that skips restore if a `say`/reply-active marker is present, else restores).
- [ ] **Step 3:** Reload automations; verify duck-on-wake still fires and grace-G restores when no reply
  arrives (simulate: wake with no follow-through).

**Go/no-go spike.** Validated jointly with Slice 5. GO iff grace-G restores on a no-reply turn **and** does
not fire during a real reply.

**Live gate.** **HA-live** (behaviour change to a live automation).

**Rollback.** Re-apply the Step-1 snapshot; pairs with `say_owns_restore=false` (Slice 1) if reverting (b).

---

### Slice 5 — End-to-end validation + convergence spike (HA-live)

**Deliverable.** The full path proven: **"Okay Nabu, &lt;question&gt;" → spoken reply on the ceiling**, source
surviving via capture→replay, volume converging to the pre-duck baseline, never-started replies
detected+surfaced+chirped, latency within budget.

- [ ] **Step 1 — audible reply, both sources:** reply audible on the ceiling over **healthy radio** *and*
  **healthy local music** (heard as *music → reply → music*).
- [ ] **Step 2 — restore convergence (load-bearing, question b):** after the reply the ceiling volume returns
  to the **pre-duck baseline (0.32)** — **not** stranded at 0.15 or a mid-reply value. Confirms `_say`-owned
  restore. If it converges cleanly even with S1a's plain `idle→restore`, record the **fallback**
  (`say_owns_restore=false`, revert Slice 4).
- [ ] **Step 3 — source replay:** radio → captured `library://radio/2` re-played → station resumes; local
  music → prior item re-played (no double-play, no stop-wedge).
- [ ] **Step 4 — reply-started guard + dropped-Q&A UX (questions 1/f):** force/observe a reply that never
  starts (e.g. an unfetchable URI) → `_say` returns `reply_started=false`/`likely_silent=true` → the satellite
  fires the **local error chirp/LED**; a healthy reply does **not** chirp. Test over radio too.
- [ ] **Step 5 — latency + cost (question e):** measure ceiling time-to-first-audio (target ~3–6 s p50 Q&A);
  confirm the local "working…" cue covers the pipeline gap; note per-query cost. Confirm media commands with
  `speak_confirmations=off` don't play a spoken confirmation.
- [ ] **Step 6 — barge-in:** a re-trigger during a ceiling reply → the new `say` replaces the in-flight clip
  (`play_media` replace) and its `gen` supersedes; restore/replay fire only after the latest reply.
- [ ] **Step 7 — no regressions:** duck/restore/music/radio/news/status all unaffected.

**Go/no-go spike (Spike-E2E).** GO iff Steps 1–4 pass. The **decision point** for (b)'s fallback is Step 2.

**Live gate.** **HA-live** (firmware already live from Slice 3; this is the wiring/validation).

**Rollback.** Reassign primary pipeline → Living Room Voice (Slice 2) · re-apply S1a snapshot (Slice 4) ·
`say_owns_restore=false` (Slice 1) · reflash Slice-0 YAML (Slice 3). Peel back in reverse order.

---

## Deployment / gating summary

| Order | Slice | Live gate | Rollback anchor |
|---|---|---|---|
| 0 | Capture current YAML | none (read-only) | n/a |
| 1 | `_say` play_media rework (resolver) | resolver deploy (single) | `git revert` + on-host `.bak` restore |
| 2 | New pipeline + caps lockstep | HA-live / exposure | reassign to Living Room Voice + revert doc |
| 3 | Firmware redirect (OTA) | firmware/device (highest risk) | **reflash Slice-0 YAML** |
| 4 | S1a `idle→restore` → grace-G (if needed) | HA-live | re-apply S1a snapshot |
| 5 | End-to-end validation | HA-live | peel slices 2→4→1→3 back |

**One gate at a time** (BACKLOG §10). Firmware (slice 3) is deliberately last.

---

## Self-review

- **Mechanism corrected (2026-07-17):** the plan now rides `play_media` + poll + capture/replay (audible,
  validated live), **not** the silent `play_announcement`/overlay. The old "do NOT re-open the mechanism"
  instruction is retired — re-opening it was exactly right.
- **Design questions (a–f):** each has an explicit decision + rationale + fallback; (a)/(b) resolved as the
  load-bearing pair (duck narrows to listening; `_say` owns the reply-turn volume + baseline restore, S1a
  `idle→restore`→grace-G, gated on the convergence spike).
- **Carried-forward requirements land in specific slices:** reply-started guard → Slice 1 (code) + Slice 5
  (live); internal-base URI → Slice 1; prefer-local/lockstep (NL-01/NL-02) → Slice 2.
- **Firmware reflash is last, behind a hard "capture current YAML" precondition** (Slice 0 → Slice 3).
- **Each slice has deliverable · go/no-go spike · live gate (or "none") · rollback.**
- **No `media_stop`** anywhere — `play_media` (replace) + `volume_set` only.
- **Scope honesty:** the announce/overlay-path silence is a *separate reliability workstream* (design §13 /
  CHANGELOG 2026-07-17); S1b-2 sidesteps it via the `play_media` route and only detects a never-started reply.
- **First slice to execute:** **Slice 1** (`_say` play_media rework) — pure repo-code + unit tests, no live
  gate for the branch; its convergence spike (over `/command`, no firmware) decides `say_owns_restore` before
  any firmware step.

---

## Proposed BACKLOG note (for INF to reconcile — not applied here)

> `S1b`–`S4` row · **proposed** update: S1b-2 **planned** (`plans/2026-07-16-s1b-2-satellite-full-assistant.md`,
> revised 2026-07-17) on the **`play_media` reply route** (the 2026-07-17 diagnostic found `play_announcement`
> deterministically silent; design §13). Slices: resolver `say` play_media rework (poll + capture/replay +
> reply-started guard) → new "Living Room ChatGPT" pipeline (prefer-local) → firmware redirect (OTA, last) →
> S1a `idle→restore`→grace-G (if needed) + E2E. Still `blocked`/`design→…` until the first live gate is claimed;
> recommend leaving the row's status to INF. **Separate item:** announce/overlay-path silence (reliability).

---

> **Rollback for this document:** `git revert` on `homebrain/s1b-2-satellite-full-assistant-plan`, or delete
> this file. No secrets, no implementation, no firmware/exposure change, no live gate claimed.
