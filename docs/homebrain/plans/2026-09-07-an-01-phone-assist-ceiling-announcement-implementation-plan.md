# AN-01 — Phone Assist → Ceiling Announcement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development`
> (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the operator say *"announce dinner is ready"* into the phone Home Assistant Companion
app and hear that sentence on the ceiling speakers, preceded by a chime, with the satellite
microphone muted for the duration and the previous music restored afterwards.

**Architecture:** A deterministic HA `conversation` sentence trigger extracts the message verbatim and
calls the resolver's authenticated `/command` with `intent=interaction`, `mode=announce`. A new
`_announce` method resolves both clips, claims turn ownership, leases and confirms the microphone
mute, then hands an ordered clip list to the **existing** `_say` reply route — which gains a clip loop
and nothing else. All duck/restore/replay/barge-in sequencing stays in `_say`; none of it is
reproduced in Home Assistant.

**Tech Stack:** Python 3.5.2 (host target), stdlib `unittest` (no pytest), raw-socket WebSocket and
`http.client` transports, Home Assistant 2026.6.4, Music Assistant 2.9.3.

**Spec:** [`../2026-09-06-phone-assist-ceiling-announcement-design.md`](../2026-09-06-phone-assist-ceiling-announcement-design.md)
at commit **`259c730`** — the authoritative design, G0-approved 2026-09-06. Read it alongside this
plan. Section references below (`§6.5`, `§9.3`, …) are to that document.

---

## Global Constraints

Every task's requirements implicitly include this section.

- **Python 3.5.2 is the compatibility floor.** The host runs 3.5.2; the dev machine runs 3.12.0, so
  the local test run does **not** catch 3.6+ syntax. Forbidden: f-strings, variable annotations
  (`x: int = 1`), numeric underscores (`1_000`), `dict` insertion-order assumptions, `async`/`await`,
  `subprocess.run(capture_output=…)`, trailing commas in function signatures after `**kwargs`. Use
  `%`-formatting or `.format()`, and comment-style type hints only.
- **Two test entry points, both already available.** `tests/test_interaction.py:5` imports
  `capability`, and `:94` defines `run(cap, ctx, params)` which calls
  `capability.run(cap, ctx, params, "rid1")`. Use the module-level `run(...)` when the request id does
  not matter, and `capability.run(cap, ctx, params, "<rid>")` directly when a test asserts on a
  specific id. Both are directly usable as written — no new helper is needed.
- **Tests are stdlib `unittest`, run from `docs/homebrain/mass-resolver/`.** One file:
  `python tests/test_interaction.py`. Whole suite: `python -m unittest discover -s tests -t .`.
  **Baseline at `259c730`: `Ran 376 tests … OK`.** No pytest anywhere.
- **Shell quirk in this repo's Bash tool:** a `cd` wrapper in `~/.bash_profile` errors with
  `ll: command not found`. Use `builtin cd <dir> && …` in this harness. Plain `cd` is correct in the
  plan's own commands for any normal shell.
- **Never print, log, stage, or commit secrets.** That includes the HA long-lived token, the
  `X-Resolver-Key`, the MA token, and **signed media URLs** (`?authSig=…`) — a signed URL is a bearer
  credential. Log clip identity with `_clip_id()`'s 8-char SHA1 fingerprint, never the URL. No example
  in any commit, test fixture, or log line may contain a real token or signature; use
  `http://192.168.122.10:8123/media/local/chime.wav?authSig=REDACTED` shapes in tests.
- **Worktree discipline (`CLAUDE.md`).** All repo work happens on
  `homebrain/an-01-implementation-plan` (this plan) and a fresh worktree for G2's code. Never commit
  on `main`.
- **Commits:** frequent and scoped, one per task minimum. No mention of Claude, Claude Code, or AI.
  No `Co-Authored-By` lines. Keep doc commits separate from code commits.
- **Approval boundaries are load-bearing.** G1, G1b, G3, G4a and G4b touch live systems and each
  requires explicit operator approval at the time. G2 and G5 are offline. **An executor of this plan
  must stop at every gate marked 🔴 and wait.**
- **The single live lane.** `BACKLOG.md:306` tracks one `host-live / HA-live / exposure` lane.
  G1/G1b/G3/G4a/G4b each claim it and release it on completion. Only one may be in flight.
- **Timing figures are an engineered phase budget, not a wall-clock bound** (§6.5). Do not reintroduce
  language claiming otherwise in code comments.

---

## File Structure

All paths relative to repo root.

| File | Responsibility | Touched in |
|---|---|---|
| `docs/homebrain/mass-resolver/wsutil.py` | Raw WS transport. Gains a `timeout` parameter on `ws_connect` so a WS call can be bounded at all. | Task 6 |
| `docs/homebrain/mass-resolver/haconn.py` | HA REST/WS client. Gains a `timeout` parameter on `get_entity_state`, and the new `resolve_media_source`. | Tasks 7, 8 |
| `docs/homebrain/mass-resolver/config.py` | `Settings`. Gains 15 `announce_*` tunables. | Task 9 |
| `docs/homebrain/mass-resolver/config.json` | Deployed values for the new tunables. | Task 9 |
| `docs/homebrain/mass-resolver/interaction.py` | The whole capability: new `announce` mode, `_announce`, the `_play_clip_and_wait` extraction, clip sequencing, generation adoption, mic lease, and the four `_say` fixes. | Tasks 10–19 |
| `docs/homebrain/mass-resolver/tests/test_wsutil.py` | `ws_connect` timeout parameter. | Task 6 |
| `docs/homebrain/mass-resolver/tests/test_haconn.py` | `get_entity_state` timeout, `resolve_media_source`. | Tasks 7, 8 |
| `docs/homebrain/mass-resolver/tests/test_config.py` | `AnnounceTunablesTest`. | Task 9 |
| `docs/homebrain/mass-resolver/tests/test_interaction.py` | Golden regressions first, then every announce behaviour. | Tasks 5, 10–19 |
| `docs/homebrain/CHANGELOG.md` | Discovery results (Checkpoint A), deploy record (G3), live record (G4a/G4b). | Tasks 4a, 22, 26 |
| `docs/homebrain/BACKLOG.md` | Lane claim/release each gate; the `AN-01` row; the dated `S1b`–`S4` reconciliation note. | Tasks 4a, 27 |
| `docs/homebrain/ONBOARDING.md` | §2/§4/§5/§6 updates. | Task 27 |
| `docs/homebrain/assistant-capabilities.md` | "deliberately not LLM-exposed" note. | Task 27 |
| `docs/homebrain/runbooks/quick-connect-and-health-check.md` | Deaf-satellite / stuck-mute recovery line. | Task 27 |
| `docs/homebrain/2026-09-06-…-design.md` | Status header updated as gates pass. | Tasks 4a, 27 |

**Not touched by any task:** `core.py` (routing already dispatches `intent=interaction` to the
singleton `InteractionCapability`; no registry change is needed), `command_result.py` (the design uses
only existing `ERROR_CODES`), `speaker.py`, `http_server.py`, and the `.claude/` directory.

---

## Gate Map

| Gate | Nature | Lane | Tasks | Approval |
|---|---|---|---|---|
| **G1** | Live discovery spikes | host-live / HA-live | 1, 2, 3 | 🔴 operator, per spike |
| **G1b** | Read-only HA config inspection | HA-live | 4 | 🔴 operator |
| **Checkpoint A** | Record discoveries, reconcile the plan | offline | 4a | 🟢 none, but **blocks G2** |
| **G2** | Offline repo code + tests | none | 5–21 | 🟢 none |
| **G3** | Host deploy + restart | host-live | 22–24 | 🔴 operator runs the restart |
| **G4a** | Create the announcement REST command | HA-live | 25 | 🔴 operator |
| **G4b** | Sentence triggers + result relay | HA-live / exposure | 26 | 🔴 operator |
| **G5** | Documentation reconciliation | offline | 27 | 🟢 none |

---

# Phase G1 — Discovery (🔴 OPERATOR-GATED — DO NOT EXECUTE)

> **These three tasks are procedures to hand to the operator, not steps to run.** An executor of this
> plan must **stop here**, present Tasks 1–3, and wait. Each needs explicit approval at the time it is
> run; approval of this plan is **not** approval to run them. Task 2 plays audio in the house and
> needs a quiet moment. Task 3 changes a live satellite setting.
>
> Claim the live lane in `BACKLOG.md:306` before the first spike; release it after Task 4.

### Task 1: SPIKE-AN-3 — source discriminator (run first; no audio, no operator ears)

Resolves **D12**. Cheapest of the three; determines whether §5.1's source gate is buildable.

**Files:** none in the repo. Output is a Checkpoint A record.

**Interfaces:**
- Consumes: nothing.
- Produces: **D12** — the name of a trigger template field that distinguishes phone / satellite / web
  Assist, or the finding that none exists. Task 26 consumes this.

- [ ] **Step 1: Operator adds a throwaway sentence trigger.** In HA, on any scratch automation (not
  `automation.voice_ceiling_speakers`), a `conversation` trigger on a nonsense phrase — suggested
  `"zibble wombat probe"` — whose only action is `logbook.log` (or `system_log.write`) of the full
  trigger payload:

```yaml
# THROWAWAY — delete after this spike.
triggers:
  - trigger: conversation
    command: "zibble wombat probe"
actions:
  - action: system_log.write
    data:
      level: warning
      logger: an01.spike
      message: >-
        device_id={{ trigger.device_id | default('<absent>') }}
        satellite_id={{ trigger.satellite_id | default('<absent>') }}
        details={{ trigger.details | default('<absent>') }}
```

- [ ] **Step 2: Speak the phrase from each of the three sources** — the phone Companion app, the
  reSpeaker satellite ("okay nabu, zibble wombat probe"), and the HA web Assist dialog.

- [ ] **Step 3: Read the three log lines** and compare. Record verbatim in Checkpoint A.

- [ ] **Step 4: Delete the throwaway automation.** It must not survive the spike.

**Go criteria:** a field that is (a) present, (b) **different** across all three sources, and
(c) stable across repeats.

**No-go:** no gate is possible. §2's "preferred excluded" becomes "accepted and documented", and
Task 26 ships **without** a source condition. **No code change is needed for the no-go path** — that
is why §5.1 was written as a preference.

---

### Task 2: SPIKE-AN-1 — will MA fetch and play a signed HA media URL? (🔴 needs a quiet house)

Resolves **D3, D4, D5**. Step 2 is the only audible action in G1.

**Files:** none in the repo.

**Interfaces:**
- Consumes: nothing.
- Produces: **D3** (URL shape: relative/absolute, signed, signature TTL), **D4** (does MA accept it),
  **D5** (the `media_content_id` MA echoes — with or without the query string). Tasks 8 and 12
  consume all three.

- [ ] **Step 1: Resolve the chime URI.** From the **host** (per `runbooks/resolver-deploy.md`
  §Connect), open a fresh WS to HA and send:

```json
{"id": 1, "type": "media_source/resolve_media",
 "media_content_id": "media-source://media_source/local/./timer_chime.wav"}
```

Record the **shape** of `result.url` — relative or absolute, whether it carries a signature
parameter, and the signature's stated or observed lifetime. **Record the shape, never the signature
value.** Write `authSig=REDACTED` in the Checkpoint A record.

- [ ] **Step 2: Play it once.** Absolutise against `192.168.122.10:8123` and call
  `music_assistant.play_media` on `media_player.ceiling_speakers`.

- [ ] **Step 3: Poll and record.** Poll `/api/states/media_player.ceiling_speakers` at 500 ms.
  Record the state sequence and — critically — **the exact `media_content_id` MA echoes**, noting
  whether the query string survives. Redact any signature in what you write down.

- [ ] **Step 4: Record timings.** Call → audible sound, and the clip's duration.

**Go criteria — all five:** (a) `resolve_media` returns a URL; (b) MA accepts it (no `Only URLs are
supported for announcements`, no `401`); (c) the player reaches `playing` within 5 s; (d) **the
operator hears the chime** — non-negotiable, per §3.2 and the entire S1b history of routes that
reported success and played nothing; (e) a stable containment `match_key` is derivable from the echoed
`media_content_id`.

**No-go fallbacks, in order (§12):** ① Piper-spoken attention token — `announce_chime_uri: ""` plus a
short `announce_prefix`; ② serve the WAV from the resolver's own HTTP server (**not recommended**,
`CHANGELOG.md` 2026-09-05 judged it "surface for no real gain"); ③ ship with no attention signal.
Fallback ① **inverts the §6.2 default** for `announce_prefix` — that is a no-go consequence to record,
not a design change.

---

### Task 3: SPIKE-AN-2 — does the mic-mute switch actually stop the wake word? (🔴 live satellite)

Resolves **D1, D2, D6, D14**.

**Files:** none in the repo.

**Interfaces:**
- Consumes: nothing.
- Produces: **D1** (exact entity ID), **D2** (does muting suppress wake detection), **D6** (is the
  feedback sound audible), **D14** (does HA report `on` for an unreachable device). Tasks 9 and 14
  consume all four.

- [ ] **Step 1: Find the entity.** `GET /api/states`, filtered to the satellite's `switch.*`
  entities. Record the exact `…_microphone_mute` entity ID and its current state.
  `s0-satellite-inventory.md:64-65` has only a `switch.…_microphone_mute` placeholder.

- [ ] **Step 2: Turn it on and measure the read-back latency.** Poll `/api/states` and record how
  long the switch takes to report `on`. **This sizes `announce_mic_confirm_timeout_ms`** — the 2 s
  default in §6.2 is a guess until measured, and too tight a budget turns every announcement into a
  refusal. Note whether the satellite emits a mute feedback sound (`switch.…_mute_unmute_sound` is
  on) and whether it is audible at all given the satellite has no speaker.

- [ ] **Step 3 (D14 — the most important unknown in the mic design):** repeat with the satellite's
  ESPHome API **disconnected**, if that can be arranged safely — the `Errno 113` condition already in
  `CHANGELOG.md`. Does HA accept the `switch.turn_on` and report `on` optimistically, or correctly
  leave it `off`/`unavailable`?

- [ ] **Step 4: Speak the wake word** twice, then a full sentence, while muted.

- [ ] **Step 5: Check for pipeline runs.** WS `assist_pipeline/pipeline_debug/list` for pipeline
  `01kxygpr39jas5hgsf28cph108`. Any new run means muting did not suppress detection.

- [ ] **Step 6: Turn it off** and confirm the wake word works again.

**Go criteria:** (a) exact entity ID established; (b) **no pipeline run** while muted; (c) the switch
reliably returns to its prior state; (d) any feedback sound is inaudible; (e) the read-back lands well
inside a shippable budget; (f) an unreachable device does **not** report `on`.

**No-go on (b) or (f):** requirement 6 cannot be met this way. §9 reopens — options are LED /
`beam_lock` experimentation, post-hoc run suppression (weighed and rejected in brainstorming), or
shipping `announce_require_mic_mute: false` and accepting self-wake. **This plan does not pre-choose;
a no-go here returns to design, not to G2.**

---

# Phase G1b — REST command inspection (🔴 OPERATOR-GATED, READ-ONLY)

### Task 4: Inspect the live `rest_command.resolver_command` and choose the §6.5 shape

Resolves **D8, D13**. **Inspection only — this task configures nothing.** Rev 4 of the design wrongly
gave G1b an exit criterion it could not achieve read-only; the write is Task 25.

**Files:** none in the repo.

**Interfaces:**
- Consumes: nothing.
- Produces: **D8** (the caller's `params` shape — settled 2026-09-07), **D13a** (the current
  timeout), **D13b** (the `payload:` body template — a stop gate), and the recorded shape decision:
  dedicated command vs. raised shared timeout. Tasks 15 (result shape), 25 (the write) and 26 (the
  caller) consume these.

- [ ] **Step 1: Read the definition.** With the operator, open the live `configuration.yaml` (or the
  packages fragment holding `rest_command:`) and record verbatim: the `url`, the header names
  (**not** the `X-Resolver-Key` value), the `payload` template, and the current `timeout`.

- [ ] **Step 2: Record the payload shape for `params`.** Copy the shape
  `automation.satellite_timer_announce_on_ceiling` already uses for `say_text` — that is the working
  reference for how `params` is nested.

- [ ] **Step 3: Decide and record the shape**, per §6.5:
  1. **Preferred — a second command**, `rest_command.resolver_command_announce`, with `timeout: 200`,
     leaving every existing caller's timeout untouched.
  2. **Raise the shared timeout** — simpler, but lengthens how long *every* resolver call can block a
     script, including the five ChatGPT-exposed ones. Only if (1) proves awkward, and the latency
     exposure must be written down.

- [ ] **Step 3c: D13 — resolved without reading the YAML (2026-09-07). No longer blocking.**
  The `rest_command:` block cannot be read from an agent: it is YAML-only, has no config entry, no API
  route, and `ONBOARDING.md:63` records there is no VM shell. `tools/ha_export.py` confirms this
  independently — purpose-built to capture HA managed state, it exports automations, scripts,
  pipelines and exposure, and **no rest_commands**, because no route exists.

  **D13b passes by production evidence — inferred, not directly read:** nine live scripts call `rest_command.resolver_command` with top-level `intent`/`params`, `response_variable` and `continue_on_error`, passing `params` mappings of **0 to 5 keys** (`news` `{}`; `ceiling_set_volume` `{mode, volume}`; `find_stations` 3 keys; `play_radio` 5 keys with `\| default('', true)` templating). A raw `{{ params }}` interpolation would emit Python dict repr with single quotes, which `/command` cannot parse — so nine working callers rule that out. Announce's `{mode, text}` is structurally identical to `ceiling_set_volume`'s proven `{mode, volume}`. Source: the `tools/ha_export.py` baseline under `docs/homebrain/ha/scripts/`.

  **D13a is informational.** AN-01 ships a dedicated `resolver_command_announce` with `timeout: 200`,
  so the existing timeout is neither inherited nor changed. Record it if the YAML is open anyway.

  **The inference is not the final word.** Task 25 step 5's round trip through the new command is the
  validation. If it fails, stop and return to design — do not patch forward on the assumption that a
  template can be adjusted, because that template has five live callers.

  *Optional, if convenient:* read the `payload:` line anyway and record it verbatim, which upgrades
  D13b from inferred to read. Header *name* and `!secret` *name* only — never the key, the token, or a
  full URL.

- [ ] **Step 4: Release the live lane** in `BACKLOG.md:306` back to FREE.

> **G1b outcome, 2026-09-07 (recorded — this part is done).**
> **D8 settled** by reading `automation.satellite_timer_announce_on_ceiling` via
> `/api/config/automation/config/satellite_timer_announce`: the caller passes `intent` and `params`
> as **top-level `data:` keys**, `params` a structured mapping, **no `payload:` wrapper**. Task 26 is
> corrected accordingly.
> `GET /api/services` shows only **`rest_command.reload`** and **`rest_command.resolver_command`** —
> no `resolver_command_announce`, so Task 25 creates it from scratch.
> **D13 still OPEN, and it is two things:** the current `timeout`, *and* the `payload:` body
> template. Neither is reachable without a YAML read (no config entry, no API, no VM shell). The
> body template is now a **stop gate at G1b step 3c**, which blocks Checkpoint A, and is
> re-checked at Task 25 step 3a before the write.

---

# ⛔ CHECKPOINT A — HARD GATE BEFORE G2

### Task 4a: Record the discoveries and reconcile the plan

**G2 MUST NOT BEGIN until this task is complete.** Every discovery below is consumed by a specific G2
task; starting G2 with any of them unrecorded means coding against a guess.

**Files:**
- Modify: `docs/homebrain/CHANGELOG.md` (new dated entry, prepended)
- Modify: `docs/homebrain/BACKLOG.md` (lane released; `AN-01` row status)
- Modify: `docs/homebrain/2026-09-06-phone-assist-ceiling-announcement-design.md` (status header)
- Modify: this plan, if any reconciliation below applies

**Interfaces:**
- Consumes: Tasks 1–4 outputs.
- Produces: a settled value for each of **D1–D6, D8, D12, D13, D14**, and a reconciled G2.

- [ ] **Step 1: Write the discovery table into `CHANGELOG.md`.** One row per discovery, with the
  observed value and the evidence (log line, state read, timing). Redact signatures and tokens.

| Discovery | Recorded value | Consumed by |
|---|---|---|
| **D1** exact mic-mute entity ID | **SETTLED 2026-09-07 (AN-2).** `switch.respeaker_living_room_microphone_mute` — available, `off` at baseline. Goes into `config.json`'s `announce_mic_mute_entity`; the `config.py` default stays `""`. | done — Task 9 |
| **D2** does muting suppress wake detection | **PASSES 2026-09-07 (AN-2).** With the mic muted 19:12:36→19:1x the operator said the wake word twice plus a full sentence: **zero** new pipeline runs on slot 1 (`01kxygpr39jas5hgsf28cph108`) **or** slot 2. **Positive control:** once unmuted, the operator's *"what time is it"* produced a run at 19:19:43 with `STT='What time is it?'`, so the zero is real suppression and not a broken capture path. Corroborated by the device's own LED ring turning **red** while muted — the firmware knows, so the wake engine is gated at the device rather than the audio merely dropped downstream. | done |
| **D3** `resolve_media` URL shape + signature TTL | | Task 8 |
| **D4** does MA fetch a signed URL | | Task 2 go/no-go → Task 12's chime clip |
| **D5** echoed `media_content_id` (query preserved?) | | Task 12 (`match_key`) |
| **D6** mute feedback sound audible | **NO AUDIBLE FEEDBACK OBSERVED 2026-09-07 (AN-2) — confirmed on a second run with the output path verified.** Two runs, and the sequence matters. **Run 1** (mute `16:07:30`, unmute `16:07:38`): nothing heard, but the reSpeaker's audio output had not been independently verified, so a negative was indistinguishable from “nothing could play” — recording it as measured was premature. **Run 2** (mute `16:13:45`, unmute `16:13:54`), after the operator tested and confirmed the connected speakers: again nothing heard at either transition. With the output path proven, the negative is now a measurement rather than an assumption. Both runs: output at 50%, `switch.…_mute_unmute_sound` left `on`, `switch.…_wake_sound` left `on`, no config changed, two writes per run to the mic-mute switch only. Confound noted in both: the ceiling was `playing` at `volume_level=0.1`. **Consequence: none** — `mute_unmute_sound` can stay `on`, so an announcement will not open with a satellite chirp layered under the ceiling chime. | done — Task 27 note only |
| **D8** `params` payload shape | **SETTLED 2026-09-07:** `intent`/`params` are top-level `data:` keys, `params` structured, **no `payload:` wrapper**. Task 26 corrected. | done |
| **D13a** the live `rest_command` `timeout` | **INFORMATIONAL / UNRESOLVED — does not block.** AN-01 ships a **dedicated** `rest_command.resolver_command_announce` with `timeout: 200`, so the existing command's timeout is never inherited and never changed. Its value would only matter if the shared shape were chosen, which it is not. Record it if convenient; do not wait for it. | not blocking |
| **D13b** the live `payload:` **body template** | **PASSES BY PRODUCTION EVIDENCE — INFERRED, NOT DIRECTLY READ.** The template itself was never read: `rest_command` is YAML-only with no config entry, no API route, and no VM shell — confirmed independently by `tools/ha_export.py`, which captures automations, scripts, pipelines and exposure but no rest_commands. The inference: nine live scripts call `rest_command.resolver_command` with top-level `intent`/`params`, `response_variable` and `continue_on_error`, passing `params` mappings of **0 to 5 keys** (`news` `{}`; `ceiling_set_volume` `{mode, volume}`; `find_stations` 3 keys; `play_radio` 5 keys with `\| default('', true)` templating). A raw `{{ params }}` interpolation would emit Python dict repr with single quotes, which `/command` cannot parse — so nine working callers rule that out. Announce's `{mode, text}` is structurally identical to `ceiling_set_volume`'s proven `{mode, volume}`. Source: the `tools/ha_export.py` baseline under `docs/homebrain/ha/scripts/`. **The stop condition (raw interpolation) is ruled out.** Task 25's dedicated-command round trip (step 5) is the **final validation**, and until it passes this remains inferred. | not blocking; validated at Task 25 step 5 |
| **D12** source discriminator field | **SETTLED 2026-09-07 (SPIKE-AN-3).** The discriminator is **`trigger.satellite_id`**. Observed, one probe sentence from three sources: phone `device_id=1542a2a3…` (SM-S948W-Costea) / `satellite_id=None`; satellite `device_id=b30ac5e3…` (reSpeaker Living Room) / `satellite_id=assist_satellite.respeaker_living_room_assist_satellite`; web Assist `device_id=None` / `satellite_id=None`. Stable over three phone repeats. `agent_id`, `user_id` and `details` carry nothing. Both candidate fields are present-and-null rather than absent on non-satellite sources, so `\| default(none)` is cheap defence, not load-bearing. **Chosen condition (recorded, NOT yet implemented):** `{{ trigger.satellite_id \| default(none) is none }}` — admits phone and web Assist, blocks satellite Assist, and avoids fragile Companion-device-id pinning, which would break on re-registration. | done — Task 26 carries it |
| **D7** wildcard-slot normalisation | **UNRESOLVED BUT INFORMED 2026-09-07.** HA **preserves** capitalisation and punctuation in the received sentence: STT delivered `Run the source probe.` while typed input gave `run the source probe`. That **contradicts** the design's §5 step 3 claim that trigger text is lower-cased and stripped. **Do not assume `trigger.slots.message` and `trigger.sentence` normalise identically** — only `sentence` was observed, and a wildcard slot may differ. | still needs the **G4b** observation; design corrected at Task 27 step 8a |
| **D13** chosen shape | **DECIDED:** dedicated `resolver_command_announce`, `timeout: 200`. No existing caller's timeout moves. | Task 25 |
| **D14** does HA report `on` for an unreachable device | **PASSES 2026-09-07 (AN-2).** Per the operator's agreed method: reversible per-device isolation (USB power unplug), no host or router change. HA marked the whole device `unavailable` after **45 s** (two consecutive reads). `switch.turn_on` against the dead device returned **HTTP 200, body `[]`** — and the entity stayed **`unavailable` on all 10 polls over 18 s**, never `on`; the `assist_satellite` and firmware sensor were `unavailable` throughout too. Recovery on replug was immediate, mute left `off`. **So HA does not optimistically fake the state, and §9.3's read-back is meaningful proof of muting.** Note the trap this closes: the same 200-in-1 ms response comes back from a *healthy* device *before* the state changes, so the service response carries no information — only the state read does. | done |

- [ ] **Step 2: Apply each reconciliation rule.** These are the only sanctioned plan edits at this
  checkpoint:

| If | Then, before G2 |
|---|---|
| **D4/D2 no-go** (MA won't fetch the chime) | Task 12 keeps the clip-loop code and tests, but `config.json` ships `announce_chime_uri: ""` and a non-empty `announce_prefix`; Task 9's default flips. Two-clip tests still run against a synthetic URI. |
| **D5 shows the query is stripped** | Task 12's chime `match_key` is the path only — as designed. **If the path is stripped too**, the chime clip needs a different confirmation strategy: **stop and return to design.** |
| **D1 found** | Task 9 sets `announce_mic_mute_entity` to the real ID in `config.json`; the `config.py` default stays `""`. |
| **D1 not found** | `announce_mic_mute_entity` stays `""`, so nothing can announce (§10 row 7). Not shippable — return to Task 3. |
| **D2 no-go** (muting doesn't stop the wake word) | **Return to design.** §9 reopens; do not proceed to G2 with a fail-safe that does not fail safe. |
| **D14 no-go** (HA reports `on` optimistically) | **Return to design.** §9.3's read-back is not proof of muting. |
| **D3 shows an absolute URL** | Task 8's absolutisation becomes a no-op guard rather than a rewrite; keep the guard and the test. |
| **D3 shows a very short TTL** | Confirm Task 15 resolves the chime **per announcement** (it does by design — never cached). No change; record the TTL. |
| ~~**Step-2 latency > 2 s**~~ | **NOT TRIGGERED.** Measured 2026-09-07: the switch reports `on` after **255 ms**, and `off` after 255 ms on the way back. The shipped `announce_mic_confirm_timeout_ms: 2000` fits with ~8× headroom, so Task 9 needs no change and §6.5's arithmetic stands. |
| **D12 no-go** | Task 26 ships without a source condition; Task 27 documents that announcements can also be triggered from the satellite. |
| **D13 disposition (accepted 2026-09-07)** | **D13b passes by inference, D13a is informational.** Neither blocks Checkpoint A or G2. The dedicated-command shape is decided, so Task 25 never touches the shared timeout and the five exposed scripts keep theirs. Task 25 step 5's round trip is the final validation of the D13b inference — **if it fails, stop and return to design rather than patching forward.** |

> **AN-2 incidental findings (2026-09-07), recorded because they change operational docs rather
> than code:**
>
> 1. **The LED ring turns red while the mic is muted.** Undocumented — `s0-satellite-inventory.md`
>    lists `light.…_led_ring` and its brightness but not that it signals mute state. This matters for
>    §9.5's residual risk: if a crashed announcement strands the mic muted after the in-memory
>    dead-man dies with the process, a red ring makes that **visible across the room** instead of
>    discoverable only by talking to a deaf satellite. Task 27's runbook line should say so.
> 2. **HA marks the satellite `unavailable` ~45 s after it loses power.** Bounds how long a stale
>    reading could persist if the device dies mid-announcement.
> 3. **Nine slot-1 runs with empty STT in the ~40 minutes after the replug** (19:20 → 20:00). The
>    known `stt-no-text-recognized` / false-wake pattern (`ONBOARDING.md` §6, `CHANGELOG.md`
>    2026-09-06), but brisker than the "8 of 20" that entry describes. **Not diagnosed** — only the
>    STT text was pulled, not the error codes, so whether these are VAD cut-offs, ambient false
>    wakes, or something the power cycle provoked is open. No bearing on D2, which was measured with
>    the mic muted. Worth a look before any further wake-word tuning.

- [ ] **Step 3: Update the design doc's status header** to note G1/G1b complete with the date, and
  which no-go fallbacks (if any) are now in force.

- [ ] **Step 4: Commit.**

```bash
git add docs/homebrain/CHANGELOG.md docs/homebrain/BACKLOG.md \
        docs/homebrain/2026-09-06-phone-assist-ceiling-announcement-design.md \
        docs/homebrain/plans/2026-09-07-an-01-phone-assist-ceiling-announcement-implementation-plan.md
git commit -m "docs(homebrain): record AN-01 G1/G1b discovery results (D1-D6, D8, D12-D14)"
```

- [ ] **Step 5: Confirm the gate.** D8 and D12 are settled; **D13b passes by inference and D13a is
  informational**, so neither blocks. **AN-2 is complete: D1, D2, D6 and D14 are all recorded.** What remains is **D3, D4 and D5** from the AN-1 chime spike — the one that needs a quiet house, because its go criterion is the operator *hearing* the chime. Formally, the confirmation line is still *"Checkpoint A complete; D1–D6, D8, D12–D14
  session. State explicitly: *"Checkpoint A complete; D1–D6, D8, D12–D14
  recorded; reconciliations applied; G2 may begin."* Do not start Task 5 without that statement.

---

# Phase G2 — Offline repo work (🟢 no approval needed)

> Create a **fresh worktree** for the code, separate from this plan's worktree:
>
> **Base it on the design commit, not `origin/main`.** Design commit **`259c730`** was committed to
> local `main` and **not pushed**, so `origin/main` is still `7a99f04` and does **not** contain the
> authoritative spec. A worktree cut from `origin/main` would not contain the design this plan
> implements. `CLAUDE.md` covers exactly this case: *"if `main` is ever ahead of `origin/main`,
> branch from local `HEAD`."*
>
> ```bash
> cd /d/repos/dotfiles
> # Confirm the base actually carries the spec.
> git cat-file -e 259c730^{commit} && echo "design commit present"
> git worktree add .claude/worktrees/an-01-code -b homebrain/an-01-announce 259c730
> cd .claude/worktrees/an-01-code
> test -f docs/homebrain/2026-09-06-phone-assist-ceiling-announcement-design.md \
>   && echo "spec present in the worktree"
> cd docs/homebrain/mass-resolver
> ```
>
> Pinning the **SHA** rather than `main` means this works whether or not `259c730` is later moved off
> `main` onto a branch.
>
> **Consequence for Task 21's PR:** if `origin/main` is still `7a99f04` when the branch is pushed,
> the PR diff will also contain `259c730` (the design doc). Either push `main` first so
> `origin/main` contains the design commit and the PR shows only AN-01 code, or accept a two-commit
> PR and say so in the body. Task 21 step 1 checks this.
>
> Every command below runs from `docs/homebrain/mass-resolver/` unless stated. No live system is
> touched anywhere in G2.

### Task 5: Golden `say` / `say_text` regression tests — BEFORE any refactor

The most important task in G2, and it must be first. A 300-line extraction is not proven safe by
reading it; only a byte-level assertion on emitted service calls proves it (§11.1). `FakeHA` already
records `calls` and `timeouts`.

**Files:**
- Test: `docs/homebrain/mass-resolver/tests/test_interaction.py` (append a new class)

**Interfaces:**
- Consumes: existing `FakeHA`, `FakeSettings`, `FakeSleeper`, `FakeTimer`, `FakeCtx`, `playing`,
  `playing_with_id`, `idle_state`, `run` from `tests/test_interaction.py:8-96`.
- Produces: `GoldenSequenceTest`, the invariant every later task must keep green.

- [ ] **Step 1: Write the golden tests.**

```python
class GoldenSequenceTest(unittest.TestCase):
    """AN-01 Task 5: byte-level pin on the calls `say` and `say_text` emit on the SUCCESS path.

    The _play_clip_and_wait extraction (Task 11) and the shared-_say fixes (Tasks 16-18) must not
    change these. Written BEFORE the refactor on purpose: inspection is not proof."""

    def setUp(self):
        FakeTimer.created = []
        self.zone = "media_player.ceiling_speakers"
        self.norm_uri = "http://192.168.122.10:8123/api/tts_proxy/x.mp3"
        self.reply_mid = "builtin://radio/" + self.norm_uri

    def _cap(self):
        return interaction.InteractionCapability(timer_factory=FakeTimer, clock=lambda: 1000.0,
                                                 sleeper=FakeSleeper())

    def _states(self):
        return [playing_with_id(0.36, "library://radio/2"),   # step 1 capture
                playing_with_id(0.40, self.reply_mid),        # start-poll: clip playing
                idle_state(), idle_state(),                   # finish-poll debounce
                playing(0.40)]                                # step 8 restore read

    def test_say_success_path_call_sequence(self):
        cap = self._cap()
        ha = FakeHA(playing(0.36)); ha.set_states(self._states())
        r = run(cap, FakeCtx(ha), {"mode": "say", "uri": self.norm_uri})
        self.assertTrue(r["ok"])
        self.assertEqual(
            [(d, s) for d, s, _ in ha.calls],
            [("media_player", "media_pause"),
             ("media_player", "volume_set"),
             ("music_assistant", "play_media"),
             ("media_player", "volume_set"),
             ("music_assistant", "play_media")])
        self.assertEqual(ha.calls[1][2]["volume_level"], 0.40)   # reply_volume
        self.assertEqual(ha.calls[2][2]["media_id"], self.norm_uri)
        self.assertEqual(ha.calls[3][2]["volume_level"], 0.36)   # baseline
        self.assertEqual(ha.calls[4][2]["media_id"], "library://radio/2")

    def test_say_success_path_timeouts(self):
        cap = self._cap()
        ha = FakeHA(playing(0.36)); ha.set_states(self._states())
        run(cap, FakeCtx(ha), {"mode": "say", "uri": self.norm_uri})
        # play_media gets the long call timeout; volume writes keep the REST default.
        self.assertEqual([t for s, t in ha.timeouts if s == "play_media"], [20.0, 20.0])
        self.assertEqual([t for s, t in ha.timeouts if s == "volume_set"], [5, 5])

    def test_say_text_success_path_call_sequence(self):
        cap = self._cap()
        ha = FakeHA(playing(0.36)); ha.set_states(self._states())
        ha.tts_url = self.norm_uri
        r = run(cap, FakeCtx(ha), {"mode": "say_text", "text": "Your timer is finished."})
        self.assertTrue(r["ok"])
        self.assertEqual(ha.tts_calls, [("tts.piper", "Your timer is finished.")])
        self.assertEqual(
            [(d, s) for d, s, _ in ha.calls],
            [("media_player", "media_pause"),
             ("media_player", "volume_set"),
             ("music_assistant", "play_media"),
             ("media_player", "volume_set"),
             ("music_assistant", "play_media")])
```

- [ ] **Step 2: Run them against unmodified code.**

Run: `python tests/test_interaction.py GoldenSequenceTest -v`
Expected: **PASS, 3 tests.** These describe today's behaviour, so they must pass *before* any change.
If any fails, the assertion is wrong — fix the test to match reality, not the code.

- [ ] **Step 3: Run the whole suite to confirm the baseline.**

Run: `python -m unittest discover -s tests -t .`
Expected: `Ran 379 tests … OK` (376 baseline + 3).

- [ ] **Step 4: Commit.**

```bash
git add tests/test_interaction.py
git commit -m "test(resolver): pin say/say_text success-path call sequences before the clip-loop refactor"
```

---

### Task 6: `wsutil.ws_connect` gains a `timeout` parameter

Without this, `resolve_media_source` cannot be bounded at all: `wsutil.py:7` hardcodes
`socket.create_connection(..., timeout=15)`, and the handshake `recv` loop inherits it.

**Files:**
- Modify: `docs/homebrain/mass-resolver/wsutil.py:6-14`
- Create: `docs/homebrain/mass-resolver/tests/test_wsutil.py` — **check first**; a `test_wsutil.py`
  already exists, so **append** a class to it rather than creating it.

**Interfaces:**
- Consumes: nothing.
- Produces: `wsutil.ws_connect(host, port, path, timeout=15)`. Task 8 consumes it.

- [ ] **Step 1: Write the failing tests.** Append to `tests/test_wsutil.py`:

```python
class WsConnectTimeoutTest(unittest.TestCase):
    """AN-01 Task 6: ws_connect must accept a timeout so a WS call can be bounded (design 6.5).
    The default stays 15s so HA.connect() is unchanged."""

    def setUp(self):
        self.seen = []
        self.real_create = wsutil.socket.create_connection

        class FakeSock(object):
            def __init__(self, outer): self.outer = outer; self.sent = b""
            def setsockopt(self, *a): pass
            def settimeout(self, t): self.outer.seen.append(("settimeout", t))
            def sendall(self, b): self.sent += b
            def recv(self, n): return b"HTTP/1.1 101 x\r\n\r\n"

        def fake_create(addr, timeout=None):
            self.seen.append(("create_connection", timeout))
            return FakeSock(self)

        wsutil.socket.create_connection = fake_create
        self.addCleanup(setattr, wsutil.socket, "create_connection", self.real_create)

    def test_default_is_still_15s(self):
        wsutil.ws_connect("h", 1, "/ws")
        self.assertIn(("create_connection", 15), self.seen)

    def test_explicit_timeout_reaches_the_connect(self):
        wsutil.ws_connect("h", 1, "/ws", timeout=3)
        self.assertIn(("create_connection", 3), self.seen)

    def test_explicit_timeout_is_also_applied_to_the_handshake_read(self):
        # The handshake recv loop must be bounded too, or the ceiling leaks past the connect.
        wsutil.ws_connect("h", 1, "/ws", timeout=3)
        self.assertIn(("settimeout", 3), self.seen)
```

- [ ] **Step 2: Run to verify failure.**

Run: `python tests/test_wsutil.py WsConnectTimeoutTest -v`
Expected: FAIL — `test_explicit_timeout_reaches_the_connect` with
`TypeError: ws_connect() got an unexpected keyword argument 'timeout'`, and
`test_explicit_timeout_is_also_applied_to_the_handshake_read` likewise.

- [ ] **Step 3: Implement.** Replace `wsutil.py:6-8`:

```python
def ws_connect(host, port, path, timeout=15):
    # timeout is a PER-OPERATION socket inactivity timeout, not a deadline for the whole
    # handshake (design 6.5). It is applied to the connect AND the handshake read, so a
    # caller with a short remaining budget cannot block on the 15s default.
    s = socket.create_connection((host, port), timeout=timeout)
    s.settimeout(timeout)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
```

(The rest of the function body is unchanged.)

- [ ] **Step 4: Run to verify pass.**

Run: `python tests/test_wsutil.py -v` → Expected: PASS, all tests.
Run: `python -m unittest discover -s tests -t .` → Expected: `Ran 382 tests … OK`.

**Watch for:** `HA.connect()` calls `self.s.settimeout(None)` immediately after `ws_connect`, so the
long-lived event socket still ends up unbounded — which is correct and must not be "fixed" here.

- [ ] **Step 5: Commit.**

```bash
git add wsutil.py tests/test_wsutil.py
git commit -m "feat(resolver): let ws_connect take a timeout for connect and handshake read"
```

---

### Task 7: `haconn.get_entity_state` gains a `timeout` parameter

`haconn.py:40,47` hardcodes `timeout=10`, so a poll read started just before its phase deadline
blocks for the full default (§6.5).

**Files:**
- Modify: `docs/homebrain/mass-resolver/haconn.py:40-60`
- Test: `docs/homebrain/mass-resolver/tests/test_haconn.py`

**Interfaces:**
- Consumes: existing `FakeResponse` / `FakeHTTPConnection` at `tests/test_haconn.py:81-107`.
- Produces: `HA.get_entity_state(entity_id, timeout=10)`. Task 12 (clip polls) and Task 14 (mic
  confirm) consume it.

- [ ] **Step 1: Write the failing tests.** Append to `tests/test_haconn.py`, mirroring the existing
  `CallServiceRestTest.test_timeout_parameter_is_passed_to_connection`:

```python
class GetEntityStateTimeoutTest(unittest.TestCase):
    """AN-01 Task 7: deadline clipping needs a per-call timeout (design 6.5)."""

    def setUp(self):
        self.made = []
        real = haconn.http.client.HTTPConnection

        def fake(host, port, timeout=None):
            self.made.append(timeout)
            return FakeHTTPConnection(host, port, timeout=timeout,
                                      response=FakeResponse(200, b'{"state":"on"}'))

        haconn.http.client.HTTPConnection = fake
        self.addCleanup(setattr, haconn.http.client, "HTTPConnection", real)
        self.ha = haconn.HA("h", 1, "tok")

    def test_default_is_still_10s(self):
        self.ha.get_entity_state("switch.x")
        self.assertEqual(self.made, [10])

    def test_explicit_timeout_is_passed_to_the_connection(self):
        self.ha.get_entity_state("switch.x", timeout=2.5)
        self.assertEqual(self.made, [2.5])
```

**Note:** `FakeHTTPConnection`'s existing constructor signature must accept `response=`. If it does
not, extend it in this step rather than duplicating it.

- [ ] **Step 2: Run to verify failure.**

Run: `python tests/test_haconn.py GetEntityStateTimeoutTest -v`
Expected: FAIL — `TypeError: get_entity_state() got an unexpected keyword argument 'timeout'`.

- [ ] **Step 3: Implement.** Change `haconn.py:40` and `:47`:

```python
    def get_entity_state(self, entity_id, timeout=10):
        ...
        conn = http.client.HTTPConnection(self.host, self.port, timeout=timeout)
```

Leave the docstring's "FRESH per-call HTTP connection" reasoning intact and add one line: `timeout is
a per-operation socket timeout, clipped by callers that hold a phase deadline (design 6.5).`

- [ ] **Step 4: Run to verify pass.**

Run: `python tests/test_haconn.py -v` → PASS.
Run: `python -m unittest discover -s tests -t .` → `Ran 384 tests … OK`.

- [ ] **Step 5: Commit.**

```bash
git add haconn.py tests/test_haconn.py
git commit -m "feat(resolver): let get_entity_state take a per-call timeout"
```

---

### Task 8: `haconn.resolve_media_source` — fresh-WebSocket media resolution

`media_source/resolve_media` has no REST equivalent, and `haconn`'s `self.s` is the shared
`subscribe_events` socket — `get_entity_state`'s own docstring states the rule. So: a fresh,
short-lived WS per call.

**Files:**
- Modify: `docs/homebrain/mass-resolver/haconn.py` (new method after `tts_get_url`)
- Test: `docs/homebrain/mass-resolver/tests/test_haconn.py`

**Interfaces:**
- Consumes: `wsutil.ws_connect(host, port, path, timeout)` (Task 6), `wsutil.ws_send`, `wsutil.ws_read`.
- Produces: `HA.resolve_media_source(uri, timeout=10)` → **absolute** `http://…` URL string; raises
  `IOError` on any failure. Task 15 consumes it.

- [ ] **Step 1: Write the failing tests.**

```python
class ResolveMediaSourceTest(unittest.TestCase):
    """AN-01 Task 8: media-source:// -> an absolute, MA-fetchable URL.

    MA rejects media-source:// outright ("Only URLs are supported for announcements") and cannot
    fetch HA's authenticated /media/local/... paths (401). HA's resolver returns a SIGNED path,
    which is the only form MA can fetch. That URL is a bearer credential: never logged."""

    SIGNED = "/media/local/timer_chime.wav?authSig=REDACTED"

    def setUp(self):
        self.sent = []
        self.connects = []
        self.closed = []
        self.reads = [{"type": "auth_required"}, {"type": "auth_ok"},
                      {"id": 1, "type": "result", "success": True,
                       "result": {"url": self.SIGNED}}]

        class FakeSock(object):
            def __init__(self, outer): self.outer = outer
            def close(self): self.outer.closed.append(True)
            def settimeout(self, t): pass

        outer = self

        def fake_connect(host, port, path, timeout=15):
            outer.connects.append((host, port, path, timeout))
            return FakeSock(outer), {"b": b""}

        def fake_send(s, obj): outer.sent.append(obj)
        def fake_read(s, box): return outer.reads.pop(0) if outer.reads else None

        for name, fn in (("ws_connect", fake_connect), ("ws_send", fake_send),
                         ("ws_read", fake_read)):
            real = getattr(haconn.wsutil, name)
            setattr(haconn.wsutil, name, fn)
            self.addCleanup(setattr, haconn.wsutil, name, real)

        self.ha = haconn.HA("192.168.122.10", 8123, "tok")

    def test_sends_the_resolve_command_and_returns_an_absolute_url(self):
        url = self.ha.resolve_media_source("media-source://media_source/local/./timer_chime.wav")
        self.assertEqual(url, "http://192.168.122.10:8123" + self.SIGNED)
        self.assertIn({"id": 1, "type": "media_source/resolve_media",
                       "media_content_id": "media-source://media_source/local/./timer_chime.wav"},
                      self.sent)

    def test_authenticates_before_resolving(self):
        self.ha.resolve_media_source("media-source://x")
        self.assertEqual(self.sent[0]["type"], "auth")

    def test_never_touches_the_shared_websocket(self):
        self.ha.s = object()          # a bare object: any use of it raises
        self.ha.resolve_media_source("media-source://x")   # must not raise

    def test_an_absolute_url_is_returned_unchanged(self):
        self.reads[-1]["result"]["url"] = "http://1.2.3.4:8123/m.wav?authSig=REDACTED"
        self.assertEqual(self.ha.resolve_media_source("media-source://x"),
                         "http://1.2.3.4:8123/m.wav?authSig=REDACTED")

    def test_missing_url_raises_rather_than_returning_none(self):
        self.reads[-1]["result"] = {}
        self.assertRaises(IOError, self.ha.resolve_media_source, "media-source://x")

    def test_a_non_http_result_is_rejected(self):
        self.reads[-1]["result"]["url"] = "ftp://nope/x.wav"
        self.assertRaises(IOError, self.ha.resolve_media_source, "media-source://x")

    def test_an_unsuccessful_result_raises(self):
        self.reads[-1] = {"id": 1, "type": "result", "success": False,
                          "error": {"code": "not_found", "message": "no such media"}}
        self.assertRaises(IOError, self.ha.resolve_media_source, "media-source://x")

    def test_closes_its_connection_on_success_and_on_failure(self):
        self.ha.resolve_media_source("media-source://x")
        self.assertTrue(self.closed)
        self.closed = []
        self.reads = [{"type": "auth_required"}, {"type": "auth_ok"},
                      {"id": 1, "type": "result", "success": True, "result": {}}]
        self.assertRaises(IOError, self.ha.resolve_media_source, "media-source://x")
        self.assertTrue(self.closed)

    def test_the_timeout_is_passed_through_to_ws_connect(self):
        # design 6.5 timeout-clipping requirement: a nominal 10s cannot be applied at all
        # while wsutil.py:7 hardcodes 15s.
        self.ha.resolve_media_source("media-source://x", timeout=4)
        self.assertEqual(self.connects[0][3], 4)

    def test_the_signed_url_is_never_logged(self):
        import logging
        recs = []

        class Grab(logging.Handler):
            def emit(self, r): recs.append(r.getMessage())

        log = logging.getLogger("resolver")
        h = Grab(); log.addHandler(h); self.addCleanup(log.removeHandler, h)
        self.ha.resolve_media_source("media-source://x")
        for m in recs:
            self.assertNotIn("authSig", m)
            self.assertNotIn(self.SIGNED, m)
```

- [ ] **Step 2: Run to verify failure.**

Run: `python tests/test_haconn.py ResolveMediaSourceTest -v`
Expected: FAIL — `AttributeError: 'HA' object has no attribute 'resolve_media_source'` on all 10.

- [ ] **Step 3: Implement.** Add to `haconn.py` after `tts_get_url`, and add `import wsutil` if the
  module-level import is not already present (it is — `haconn.py:6`):

```python
    def resolve_media_source(self, uri, timeout=10):
        """Turn a media-source:// URI into an absolute, MA-fetchable URL.

        Why: MA rejects media-source:// outright ("Only URLs are supported for announcements") and
        cannot fetch HA's authenticated /media/local/... paths (401). HA's own resolver hands back a
        SIGNED path that carries its authorisation in the query string, which is the only form MA can
        fetch.

        Transport: a FRESH, short-lived WebSocket per call. media_source/resolve_media has no REST
        equivalent, and self.s is the shared subscribe_events socket -- same rule as
        get_entity_state. Resolved per use, never cached: the signature expires.

        The returned URL is a bearer credential. NEVER log it; log self-fingerprints instead.
        """
        s = None
        try:
            s, box = wsutil.ws_connect(self.host, self.port, "/api/websocket", timeout=timeout)
            hello = wsutil.ws_read(s, box)
            if (hello or {}).get("type") != "auth_required":
                raise IOError("unexpected HA hello resolving a media source")
            wsutil.ws_send(s, {"type": "auth", "access_token": self.token})
            if (wsutil.ws_read(s, box) or {}).get("type") != "auth_ok":
                raise IOError("HA auth failed resolving a media source")
            wsutil.ws_send(s, {"id": 1, "type": "media_source/resolve_media",
                               "media_content_id": uri})
            msg = wsutil.ws_read(s, box) or {}
            if not msg.get("success"):
                err = (msg.get("error") or {}).get("code", "unknown")
                raise IOError("HA resolve_media failed: %s" % err)
            url = (msg.get("result") or {}).get("url")
            if not url:
                raise IOError("HA resolve_media returned no url")
            if not str(url).startswith("http"):
                # HA usually returns a RELATIVE signed path. Absolutise against our own
                # host:port, which is already the MA-reachable NAT base from ha_url.
                url = "http://%s:%s%s" % (self.host, self.port, url)
            if not str(url).startswith("http"):
                raise IOError("HA resolve_media returned a non-absolute url")
            return url
        finally:
            if s is not None:
                try:
                    s.close()
                except Exception:
                    pass
```

- [ ] **Step 4: Run to verify pass.**

Run: `python tests/test_haconn.py -v` → PASS.
Run: `python -m unittest discover -s tests -t .` → `Ran 394 tests … OK`.

- [ ] **Step 5: Commit.**

```bash
git add haconn.py tests/test_haconn.py
git commit -m "feat(resolver): resolve media-source URIs to a playable URL over a fresh websocket"
```

---

### Task 9: The `announce_*` settings

**Files:**
- Modify: `docs/homebrain/mass-resolver/config.py` (after the `say_*` block, ~line 94)
- Modify: `docs/homebrain/mass-resolver/config.json`
- Test: `docs/homebrain/mass-resolver/tests/test_config.py`

**Interfaces:**
- Consumes: **D1** (the mic entity ID) and the **D2 step-2 latency** from Checkpoint A.
- Produces: 15 `Settings` attributes, consumed by Tasks 10–19.

- [ ] **Step 1: Write the failing tests.** Append to `tests/test_config.py`:

```python
class AnnounceTunablesTest(unittest.TestCase):
    """AN-01 Task 9: design 6.2 + 6.5."""

    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="cfg_")
        self.addCleanup(shutil.rmtree, self.d, ignore_errors=True)

    def _write(self, obj):
        with open(os.path.join(self.d, "config.json"), "w") as f:
            json.dump(obj, f)

    def test_defaults(self):
        s = config.load_settings(self.d)
        self.assertEqual(s.announce_volume, 0.80)
        self.assertEqual(s.announce_prefix, "")
        self.assertEqual(s.announce_max_prefix_chars, 40)
        self.assertEqual(s.announce_chime_uri,
                         "media-source://media_source/local/./timer_chime.wav")
        self.assertEqual(s.announce_mic_mute_entity, "")
        self.assertTrue(s.announce_require_mic_mute)
        self.assertEqual(s.announce_mic_confirm_timeout_ms, 2000)
        self.assertEqual(s.announce_mic_confirm_poll_ms, 250)
        self.assertEqual(s.announce_mic_deadman_ms, 0)
        self.assertEqual(s.announce_volume_deadman_ms, 0)
        self.assertEqual(s.announce_volume_deadman_retries, 3)
        self.assertEqual(s.announce_chime_finish_timeout_ms, 15000)
        self.assertEqual(s.announce_message_finish_timeout_ms, 45000)
        self.assertEqual(s.announce_max_chars, 300)
        self.assertEqual(s.announce_min_call_timeout_ms, 500)

    def test_overrides(self):
        self._write({"announce_volume": 0.55, "announce_prefix": "Attention.",
                     "announce_chime_uri": "", "announce_require_mic_mute": False,
                     "announce_max_chars": 120, "announce_mic_confirm_timeout_ms": 4000})
        s = config.load_settings(self.d)
        self.assertEqual(s.announce_volume, 0.55)
        self.assertEqual(s.announce_prefix, "Attention.")
        self.assertEqual(s.announce_chime_uri, "")
        self.assertFalse(s.announce_require_mic_mute)
        self.assertEqual(s.announce_max_chars, 120)
        self.assertEqual(s.announce_mic_confirm_timeout_ms, 4000)

    def test_announce_volume_is_above_reply_volume_in_the_shipped_config(self):
        # Guards against an edit quietly making announcements quieter than replies.
        here = os.path.dirname(os.path.dirname(os.path.abspath(config.__file__)))
        s = config.load_settings(os.path.join(here, "mass-resolver"))
        self.assertGreater(s.announce_volume, s.reply_volume)

    def test_the_engineered_phase_budget_stays_under_the_rest_command_timeout(self):
        # design 6.5: an arithmetic self-consistency check as timeouts are tuned. It does NOT
        # claim the budget bounds wall-clock duration -- a socket timeout is a per-operation
        # inactivity timeout, not a request deadline.
        s = config.load_settings(self.d)
        start = s.say_start_timeout_ms
        budget_ms = (10000 + 10000 + 10000 + 5000 + s.announce_mic_confirm_timeout_ms
                     + 5000 + 5000
                     + s.say_call_timeout_ms + start + s.announce_chime_finish_timeout_ms
                     + s.say_call_timeout_ms + start + s.announce_message_finish_timeout_ms
                     + 5000 + s.say_call_timeout_ms + 5000
                     + 5 * s.announce_min_call_timeout_ms)
        self.assertLess(budget_ms / 1000.0, 200.0)
```

**Fix the path helper if it fails:** `test_announce_volume_is_above_reply_volume_in_the_shipped_config`
must locate the real `config.json`. If the `os.path` walk above resolves wrongly, replace it with
`os.path.dirname(os.path.dirname(os.path.abspath(__file__)))` (the `mass-resolver` dir, since the test
file lives in `tests/`).

- [ ] **Step 2: Run to verify failure.**

Run: `python tests/test_config.py AnnounceTunablesTest -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'announce_volume'`.

- [ ] **Step 3: Implement in `config.py`,** inserted after the `say_pause_before_reply` line:

```python
        # AN-01 announce mode (design 6.2). Louder than reply_volume; the chime is the default
        # attention signal, so announce_prefix is empty.
        self.announce_volume = float(cfg.get("announce_volume", 0.80))
        self.announce_prefix = cfg.get("announce_prefix", "")
        self.announce_max_prefix_chars = int(cfg.get("announce_max_prefix_chars", 40))
        self.announce_chime_uri = cfg.get(
            "announce_chime_uri", "media-source://media_source/local/./timer_chime.wav")
        # Empty until the spike establishes the real entity id (D1). Empty means announcements
        # refuse, per announce_require_mic_mute.
        self.announce_mic_mute_entity = cfg.get("announce_mic_mute_entity", "")
        self.announce_require_mic_mute = bool(cfg.get("announce_require_mic_mute", True))
        # A successful switch.turn_on is an accepted REQUEST, not a muted microphone: poll the
        # state back before any audio (design 9.3).
        self.announce_mic_confirm_timeout_ms = int(cfg.get("announce_mic_confirm_timeout_ms", 2000))
        self.announce_mic_confirm_poll_ms = int(cfg.get("announce_mic_confirm_poll_ms", 250))
        # Failsafe timers. 0 derives from the turn's own budget (design 6.5). Both are POLICY
        # CUTOFFS based on an engineered budget, not wall-clock bounds -- a pathologically
        # slow-but-live turn can cross one. The trade-off favours liveness over waiting.
        self.announce_mic_deadman_ms = int(cfg.get("announce_mic_deadman_ms", 0))
        self.announce_volume_deadman_ms = int(cfg.get("announce_volume_deadman_ms", 0))
        self.announce_volume_deadman_retries = int(cfg.get("announce_volume_deadman_retries", 3))
        # Per-clip finish budgets. NOT say_reply_timeout_ms (180s), which is sized for the
        # knowledge agent's long answers.
        self.announce_chime_finish_timeout_ms = int(cfg.get("announce_chime_finish_timeout_ms", 15000))
        self.announce_message_finish_timeout_ms = int(cfg.get("announce_message_finish_timeout_ms", 45000))
        # Bound on the FINAL RENDERED text (prefix + message). The whole timing model rests on
        # this, so nothing reaching Piper may escape it. Over-long is REJECTED, never truncated.
        self.announce_max_chars = int(cfg.get("announce_max_chars", 300))
        # Floor for a deadline-clipped blocking call: below this, do not start the call.
        self.announce_min_call_timeout_ms = int(cfg.get("announce_min_call_timeout_ms", 500))
```

- [ ] **Step 4: Add the deployed values to `config.json`.** Insert before `"ha_url"`, using **D1**
  from Checkpoint A for the entity ID and the measured latency for the confirm timeout:

```json
  "announce_volume": 0.80,
  "announce_prefix": "",
  "announce_chime_uri": "media-source://media_source/local/./timer_chime.wav",
  "announce_mic_mute_entity": "<D1: the exact switch entity id from Checkpoint A>",
  "announce_require_mic_mute": true,
  "announce_mic_confirm_timeout_ms": 2000,
  "announce_chime_finish_timeout_ms": 15000,
  "announce_message_finish_timeout_ms": 45000,
  "announce_max_chars": 300,
```

**Do not leave the placeholder.** If Checkpoint A did not produce D1, stop — Task 3 is incomplete.
Settings whose defaults are correct are deliberately omitted from `config.json`, matching the existing
file's style (it omits `tts_engine`, `say_skip_replay_on_stop`, etc.).

- [ ] **Step 5: Run to verify pass.**

Run: `python tests/test_config.py -v` → PASS.
Run: `python -m unittest discover -s tests -t .` → `Ran 398 tests … OK`.

- [ ] **Step 6: Commit.**

```bash
git add config.py config.json tests/test_config.py
git commit -m "feat(resolver): add announce mode tunables"
```

---

### Task 10: `announce` mode, text rendering, and the rejection bound

**Files:**
- Modify: `docs/homebrain/mass-resolver/interaction.py:9-10` (`_MODES`), `:45-56` (`validate`), plus a
  new `_render_announcement_text` helper
- Test: `docs/homebrain/mass-resolver/tests/test_interaction.py`

**Interfaces:**
- Consumes: `Settings.announce_prefix`, `announce_max_prefix_chars`, `announce_max_chars` (Task 9).
- Produces: `"announce"` in `_MODES`; `_render_announcement_text(self, ctx, text)` returning the
  tuple `(rendered_or_None, err_dict_or_None, prefix_dropped_bool)`. Task 15 consumes it.

- [ ] **Step 1: Extend `FakeSettings` first.** In `tests/test_interaction.py:39-51`, add the Task 9
  names so every announce test runs against production values rather than `getattr` defaults:

```python
    announce_volume = 0.80
    announce_prefix = ""
    announce_max_prefix_chars = 40
    announce_chime_uri = "media-source://media_source/local/./timer_chime.wav"
    announce_mic_mute_entity = "switch.respeaker_test_microphone_mute"
    announce_require_mic_mute = True
    announce_mic_confirm_timeout_ms = 2000
    announce_mic_confirm_poll_ms = 250
    announce_mic_deadman_ms = 0
    announce_volume_deadman_ms = 0
    announce_volume_deadman_retries = 3
    announce_chime_finish_timeout_ms = 15000
    announce_message_finish_timeout_ms = 45000
    announce_max_chars = 300
    announce_min_call_timeout_ms = 500
```

`FakeSettings` is class-attribute based, so tests that need a different value assign it on their own
`ctx.settings` instance.

- [ ] **Step 2: Write the failing tests.**

```python
class AnnounceResolveValidateTest(unittest.TestCase):
    """AN-01 Task 10: design 6.3 + 7 step B. The bound is on the RENDERED text (prefix + message),
    and over-long is REJECTED, never truncated -- truncating a household message can invert its
    meaning ("do not let the dog out the back gate" -> "do not let the dog out") and a metadata
    flag does not help a listener two rooms away."""

    def _cap(self):
        return interaction.InteractionCapability(timer_factory=FakeTimer, clock=lambda: 1000.0,
                                                 sleeper=FakeSleeper())

    def test_announce_is_a_valid_mode(self):
        cap = self._cap()
        self.assertIsNone(cap.validate(FakeCtx(FakeHA()),
                                       {"mode": "announce", "zone": "z", "text": "hi"}))

    def test_announce_without_text_is_rejected(self):
        cap = self._cap()
        err = cap.validate(FakeCtx(FakeHA()), {"mode": "announce", "zone": "z", "text": ""})
        self.assertEqual(err["code"], "invalid_input")

    def test_blank_text_rejected_before_any_ha_call(self):
        cap = self._cap(); ha = FakeHA(playing(0.36))
        r = run(cap, FakeCtx(ha), {"mode": "announce", "text": "   "})
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"]["code"], "invalid_input")
        self.assertEqual(ha.calls, [])

    def test_a_message_at_exactly_the_limit_is_accepted(self):
        cap = self._cap(); ctx = FakeCtx(FakeHA())
        rendered, err, dropped = cap._render_announcement_text(ctx, "x" * 300)
        self.assertIsNone(err)
        self.assertEqual(rendered, "x" * 300)

    def test_no_code_path_truncates_the_message(self):
        cap = self._cap(); ctx = FakeCtx(FakeHA())
        rendered, err, dropped = cap._render_announcement_text(ctx, "y" * 301)
        self.assertIsNone(rendered)
        self.assertEqual(err["code"], "invalid_input")

    def test_the_bound_is_on_prefix_plus_message(self):
        cap = self._cap(); ctx = FakeCtx(FakeHA())
        ctx.settings.announce_prefix = "A" * 40
        ok, err, dropped = cap._render_announcement_text(ctx, "m" * 259)
        self.assertIsNone(err)
        self.assertEqual(ok, "A" * 40 + " " + "m" * 259)
        bad, err2, _ = cap._render_announcement_text(ctx, "m" * 280)
        self.assertIsNone(bad)
        self.assertEqual(err2["code"], "invalid_input")

    def test_the_rejection_quotes_the_effective_limit(self):
        cap = self._cap(); ctx = FakeCtx(FakeHA())
        ctx.settings.announce_prefix = "Attention."          # 10 chars + one space
        _, err, _ = cap._render_announcement_text(ctx, "m" * 295)
        self.assertIn("289", err["chat_text"])               # 300 - 10 - 1

    def test_an_over_long_prefix_is_dropped_not_fatal(self):
        cap = self._cap(); ctx = FakeCtx(FakeHA())
        ctx.settings.announce_prefix = "P" * 41
        rendered, err, dropped = cap._render_announcement_text(ctx, "dinner is ready")
        self.assertIsNone(err)
        self.assertTrue(dropped)
        self.assertEqual(rendered, "dinner is ready")

    def test_every_error_code_used_is_in_ERROR_CODES(self):
        # cr.err raises ValueError on an unknown code, turning a handled failure into a crash.
        # An earlier design draft used "precondition_failed", which is not a valid code.
        import command_result as cr_mod
        for code in ("invalid_input", "unavailable", "upstream_error"):
            self.assertIn(code, cr_mod.ERROR_CODES)
        self.assertNotIn("precondition_failed", cr_mod.ERROR_CODES)
```

- [ ] **Step 3: Run to verify failure.**

Run: `python tests/test_interaction.py AnnounceResolveValidateTest -v`
Expected: FAIL — `test_announce_is_a_valid_mode` returns a `bad mode` dict instead of `None`, and the
five `_render_announcement_text` tests raise
`AttributeError: 'InteractionCapability' object has no attribute '_render_announcement_text'`.

- [ ] **Step 4: Implement.** Extend `_MODES` (line 9):

```python
_MODES = ("duck", "restore", "say", "say_text", "announce", "resume", "pause", "volume_up",
          "volume_down", "set_volume")
```

Add to `validate`, after the `say_text` clause:

```python
        if resolved["mode"] == "announce" and not resolved.get("text"):
            return {"code": "invalid_input", "reason": "no text",
                    "chat_text": "Nothing to announce."}
```

Add the helper immediately above `_say_text`:

```python
    def _render_announcement_text(self, ctx, text):
        """Build the sentence Piper will speak, and bound the RESULT.

        Returns (rendered, err, prefix_dropped); `err` is a dict for cr.err, or None.

        The bound covers prefix + message because announce_prefix is configurable and is
        synthesised into the same clip: bounding only the message would let config.json defeat the
        whole timing model. Over-long is REJECTED rather than truncated (design 7).
        """
        msg = (text or "").strip()
        prefix = (getattr(ctx.settings, "announce_prefix", "") or "").strip()
        max_prefix = int(getattr(ctx.settings, "announce_max_prefix_chars", 40))
        max_chars = int(getattr(ctx.settings, "announce_max_chars", 300))
        dropped = False
        if prefix and len(prefix) > max_prefix:
            # A misconfigured prefix must not disable every announcement in the house.
            LOG.error("ANNOUNCE announce_prefix is %d chars (max %d); dropping it for this turn",
                      len(prefix), max_prefix)
            prefix = ""
            dropped = True
        if not msg:
            return (None, {"code": "invalid_input", "reason": "no text",
                           "chat_text": "Nothing to announce."}, dropped)
        rendered = (prefix + " " + msg) if prefix else msg
        if len(rendered) > max_chars:
            effective = max_chars - (len(prefix) + 1 if prefix else 0)
            LOG.info("ANNOUNCE refused: rendered %d chars over the %d limit (effective %d)",
                     len(rendered), max_chars, effective)
            return (None, {"code": "invalid_input", "reason": "text too long",
                           "chat_text": "That message is too long to announce - keep it under "
                                        "%d characters." % effective}, dropped)
        return (rendered, None, dropped)
```

**ASCII only in that `chat_text`** — a plain hyphen, not an en dash. `ONBOARDING.md` §3 records
`UnicodeEncodeError` on non-ASCII console output.

- [ ] **Step 5: Run to verify pass.**

Run: `python tests/test_interaction.py AnnounceResolveValidateTest -v` → PASS, 9 tests.
Run: `python -m unittest discover -s tests -t .` → `Ran 407 tests ... OK`.

`execute()` has no `announce` branch until Task 15, so a full `run(...)` with `mode=announce` still
falls through to `_restore`. That is why only `validate`- and helper-level assertions appear here; the
one end-to-end test above (`test_blank_text_rejected_before_any_ha_call`) passes because `validate`
rejects before `execute` is reached.

- [ ] **Step 6: Commit.**

```bash
git add interaction.py tests/test_interaction.py
git commit -m "feat(resolver): add announce mode validation and a rendered-text bound"
```

---

### Task 11: Extract `_play_clip_and_wait` — behaviour-preserving

A pure refactor. Task 5's golden tests are the acceptance criterion: they must stay green with no
edit.

**Files:**
- Modify: `docs/homebrain/mass-resolver/interaction.py:509-803` (`_say`), plus a new
  `_play_clip_and_wait` method

**Interfaces:**
- Consumes: Task 5's `GoldenSequenceTest`, Task 7's `get_entity_state(entity_id, timeout=10)`.
- Produces: `_play_clip_and_wait(self, ctx, rid, zone, norm_uri, match_key, clip, opts, superseded)`
  → `{"started": bool, "issued": bool, "clip": str}`. `opts` is a dict carrying `start_timeout`,
  `finish_timeout`, `call_timeout`, `poll_secs`, `blank_grace`, `deadline` (float or `None`) and
  `floor`. Tasks 12–19 consume it.

- [ ] **Step 1: Add the new method.** Move the bodies of today's step 3 (`interaction.py:616`),
  step 5 (`:646-656`), step 6 (`:658-686`) and step 7 (`:687-745`) into:

```python
    def _play_clip_and_wait(self, ctx, rid, zone, norm_uri, match_key, clip, opts, superseded):
        """Play ONE clip and wait for it: play_media -> start-poll -> finish-poll.

        Everything a TURN owns stays in _say -- generation ownership, baseline capture, the single
        volume raise, the single restore, the single replay, release. This method owns one clip.

        Returns {"started", "issued", "clip"}. Propagates whatever play_media raises; _say's finally
        is the recovery path.
        """
        out = {"started": False, "issued": False, "clip": clip}
        deadline = opts.get("deadline")
        poll_secs = opts["poll_secs"]
        floor = opts["floor"]

        def read_timeout(default_timeout):
            # Clip a blocking read to what is left of this phase (design 6.5). A socket timeout is
            # a per-operation inactivity timeout, not a request deadline, so this reduces overshoot
            # rather than proving a limit. None means: do not start another blocking call.
            if deadline is None:
                return default_timeout
            left = deadline - self._clock()
            if left < floor:
                return None
            return min(default_timeout, left)

        self._say_call(ctx, rid, zone, "music_assistant", "play_media",
                       {"entity_id": zone, "media_id": norm_uri}, timeout=opts["call_timeout"])
        out["issued"] = True

        start_timeout = opts["start_timeout"]
        start_deadline = self._clock() + start_timeout
        elapsed = 0.0
        while True:
            if superseded():
                return out
            if deadline is None:
                if elapsed >= start_timeout:
                    break
            elif self._clock() >= min(start_deadline, deadline):
                break
            rt = read_timeout(10)
            if rt is None:
                break
            try:
                state = ctx.ha.get_entity_state(zone, timeout=rt) or {}
            except Exception as e:
                LOG.warning("SAY req=%s zone=%s start-poll read failed (%r)", rid, zone, e)
                state = {}
            attrs = state.get("attributes") or {}
            # MA does not echo the raw URL back as media_content_id -- it wraps it, e.g.
            # "builtin://radio/<url>". Match by containment, not equality.
            if state.get("state") == "playing" and match_key in (attrs.get("media_content_id") or ""):
                out["started"] = True
                break
            self._sleeper(poll_secs)
            elapsed += poll_secs

        if not out["started"]:
            LOG.warning("SAY req=%s zone=%s clip=%s did not start (likely silent)", rid, zone, clip)
            return out

        finish_timeout = opts["finish_timeout"]
        finish_deadline = self._clock() + finish_timeout
        blank_grace = max(opts["blank_grace"], poll_secs)
        elapsed = 0.0
        ended_seen = 0
        blank_for = 0.0
        while True:
            if superseded():
                return out
            if deadline is None:
                if elapsed >= finish_timeout:
                    break
            elif self._clock() >= min(finish_deadline, deadline):
                break
            rt = read_timeout(10)
            if rt is None:
                break
            try:
                state = ctx.ha.get_entity_state(zone, timeout=rt) or {}
            except Exception as e:
                LOG.warning("SAY req=%s zone=%s finish-poll read failed (%r)", rid, zone, e)
                state = {}
            attrs = state.get("attributes") or {}
            cid = attrs.get("media_content_id") or ""
            # MA transiently reports an EMPTY media_content_id mid-clip. Treating that as "ended"
            # cut replies off after 0.5-1.0s and replayed the source over them, so an empty cid is
            # NOT an ending while the player still says `playing`.
            ended = (state.get("state") != "playing") or (cid != "" and match_key not in cid)
            if not ended and cid == "":
                blank_for += poll_secs
                if blank_for >= blank_grace:
                    LOG.info("SAY req=%s zone=%s clip=%s finish-poll: cid stayed empty for %.1fs "
                             "(state=playing); treating the clip as finished",
                             rid, zone, clip, blank_for)
                    break
            elif cid != "":
                blank_for = 0.0
            if ended:
                # Two consecutive observations: a single flicker must not trigger restore+replay.
                ended_seen += 1
                if ended_seen >= 2:
                    LOG.info("SAY req=%s zone=%s clip=%s finish-poll exit after %.1fs: state=%s cid=%s",
                             rid, zone, clip, elapsed, state.get("state"), cid[:60])
                    break
            else:
                ended_seen = 0
            self._sleeper(poll_secs)
            elapsed += poll_secs
        return out
```

- [ ] **Step 2: Rewire `_say` to call it once.** Replace the excised block with:

```python
            norm_uri = self._normalise_uri(uri, getattr(ctx.settings, "say_internal_base", ""))
            opts = {"start_timeout": start_timeout, "finish_timeout": reply_timeout,
                    "call_timeout": call_timeout, "poll_secs": poll_secs,
                    "blank_grace": int(getattr(ctx.settings, "say_blank_cid_grace_ms", 4000)) / 1000.0,
                    "deadline": None,
                    "floor": int(getattr(ctx.settings, "announce_min_call_timeout_ms", 500)) / 1000.0}
            res = self._play_clip_and_wait(ctx, rid, zone, norm_uri, norm_uri, clip, opts, superseded)
            play_issued[0] = res["issued"]
            reply_started = res["started"]
            likely_silent = not reply_started
            if superseded():
                return superseded_result()
```

`deadline=None` keeps accumulated-sleep bounding for `say`/`say_text`, which §6.5 preserves
deliberately: converting them is a timing change to a live, proven path with no defect motivating it.
`match_key` equals `norm_uri` here, so matching is byte-for-byte today's.

- [ ] **Step 3: Run the golden tests — the whole point of this task.**

Run: `python tests/test_interaction.py GoldenSequenceTest -v`
Expected: **PASS, 3 tests, unchanged.** If any fails, the extraction changed behaviour — fix the
extraction, never the golden test.

- [ ] **Step 4: Run the full suite.**

Run: `python -m unittest discover -s tests -t .` → `Ran 407 tests ... OK`.
`SayPlayMediaTest`, `FinishPollCutOffTest`, `ReplyBumpTest`, `SayTextTest`,
`SayTextFreshPlaybackTest`, `DuckOwnershipSlice4Test`, `HumanVolumeChangeDuringTurnTest` and
`SayObservabilityTest` must all stay green with no edit.

- [ ] **Step 5: Commit.**

```bash
git add interaction.py
git commit -m "refactor(resolver): extract the per-clip play/poll body out of _say"
```

---

### Task 12: Clip sequencing — `uris`, `match_keys`, `finish_timeouts`, `volume_override`, deadlines

**Files:**
- Modify: `docs/homebrain/mass-resolver/interaction.py` (`_say`)
- Test: `docs/homebrain/mass-resolver/tests/test_interaction.py`

**Interfaces:**
- Consumes: `_play_clip_and_wait` (Task 11); **D5** from Checkpoint A (does MA preserve the query
  string in the echoed `media_content_id`).
- Produces: `_say` honouring optional `resolved["uris"]`, `["match_keys"]`, `["finish_timeouts"]`,
  `["volume_override"]`, `["deadline_from_now"]`, and a `metadata["clips"]` list of
  `{"clip", "started", "issued"}`. Task 15 consumes them.

- [ ] **Step 1: Write the failing tests.**

```python
class ClipSequenceTest(unittest.TestCase):
    """AN-01 Task 12: design 8.1-8.3. One baseline, one raise, N clips, one restore, one replay."""

    def setUp(self):
        FakeTimer.created = []
        self.zone = "media_player.ceiling_speakers"
        # A signed media URL is a bearer credential: fixtures use a REDACTED placeholder.
        self.chime = "http://192.168.122.10:8123/media/local/chime.wav?authSig=REDACTED"
        self.chime_key = "http://192.168.122.10:8123/media/local/chime.wav"
        self.tts = "http://192.168.122.10:8123/api/tts_proxy/x.mp3"

    def _cap(self):
        return interaction.InteractionCapability(timer_factory=FakeTimer, clock=lambda: 1000.0,
                                                 sleeper=FakeSleeper())

    def _states(self):
        return [playing_with_id(0.36, "library://radio/2"),                    # capture
                playing_with_id(0.80, "builtin://radio/" + self.chime),        # chime start
                idle_state(), idle_state(),                                    # chime end
                playing_with_id(0.80, "builtin://radio/" + self.tts),          # tts start
                idle_state(), idle_state(),                                    # tts end
                playing(0.80)]                                                 # restore read

    def _two_clip(self, cap, ha):
        return capability.run(cap, FakeCtx(ha), {
            "mode": "say", "uri": self.tts,
            "uris": [self.chime, self.tts],
            "match_keys": [self.chime_key, self.tts],
            "finish_timeouts": [15.0, 45.0],
            "volume_override": 0.80,
            "skip_on_fresh_playback": False}, "rid-seq")

    def test_two_clips_play_in_order_with_one_raise_and_one_restore(self):
        cap = self._cap(); ha = FakeHA(playing(0.36)); ha.set_states(self._states())
        r = self._two_clip(cap, ha)
        self.assertTrue(r["ok"])
        self.assertEqual([(d, s) for d, s, _ in ha.calls],
                         [("media_player", "media_pause"),
                          ("media_player", "volume_set"),
                          ("music_assistant", "play_media"),
                          ("music_assistant", "play_media"),
                          ("media_player", "volume_set"),
                          ("music_assistant", "play_media")])
        self.assertEqual(ha.calls[2][2]["media_id"], self.chime)
        self.assertEqual(ha.calls[3][2]["media_id"], self.tts)
        self.assertEqual(ha.calls[5][2]["media_id"], "library://radio/2")

    def test_volume_override_is_used_not_reply_volume(self):
        cap = self._cap(); ha = FakeHA(playing(0.36)); ha.set_states(self._states())
        self._two_clip(cap, ha)
        self.assertEqual(ha.calls[1][2]["volume_level"], 0.80)

    def test_volume_override_of_zero_is_honoured(self):
        # An `or` fallback would silently discard 0.0; the check must be `is None`.
        cap = self._cap(); ha = FakeHA(playing(0.36))
        ha.set_states([playing_with_id(0.36, "library://radio/2"),
                       playing_with_id(0.0, "builtin://radio/" + self.tts),
                       idle_state(), idle_state(), playing(0.0)])
        capability.run(cap, FakeCtx(ha),
                       {"mode": "say", "uri": self.tts, "volume_override": 0.0}, "rid-z")
        self.assertEqual(ha.calls[1][2]["volume_level"], 0.0)

    def test_baseline_is_captured_once_and_restored_once(self):
        cap = self._cap(); ha = FakeHA(playing(0.36)); ha.set_states(self._states())
        self._two_clip(cap, ha)
        self.assertEqual([c[2]["volume_level"] for c in ha.calls if c[1] == "volume_set"],
                         [0.80, 0.36])

    def test_source_is_replayed_once_after_both_clips(self):
        cap = self._cap(); ha = FakeHA(playing(0.36)); ha.set_states(self._states())
        r = self._two_clip(cap, ha)
        self.assertTrue(r["metadata"]["replayed"])
        self.assertEqual(len([c for c in ha.calls if c[1] == "play_media"]), 3)   # 2 clips + replay

    def test_the_chime_match_key_strips_the_query_and_the_tts_key_does_not(self):
        cap = self._cap(); ha = FakeHA(playing(0.36)); ha.set_states(self._states())
        r = self._two_clip(cap, ha)
        clips = r["metadata"]["clips"]
        self.assertEqual(len(clips), 2)
        self.assertTrue(clips[0]["started"])
        self.assertTrue(clips[1]["started"])

    def test_each_clip_gets_its_own_finish_budget(self):
        cap = self._cap(); ha = FakeHA(playing(0.36)); ha.set_states(self._states())
        r = self._two_clip(cap, ha)
        self.assertTrue(r["ok"])          # 15s chime + 45s message, not 180s twice

    def test_a_single_uri_still_works(self):
        cap = self._cap(); ha = FakeHA(playing(0.36))
        ha.set_states([playing_with_id(0.36, "library://radio/2"),
                       playing_with_id(0.40, "builtin://radio/" + self.tts),
                       idle_state(), idle_state(), playing(0.40)])
        r = capability.run(cap, FakeCtx(ha), {"mode": "say", "uri": self.tts}, "rid-one")
        self.assertTrue(r["ok"])
        self.assertEqual(len([c for c in ha.calls if c[1] == "play_media"]), 2)


class ClipDeadlineTest(unittest.TestCase):
    """AN-01 Task 12: design 6.5. Announcement clips poll against a wall-clock deadline and clip
    each read to what is left; say/say_text keep accumulated-sleep bounding."""

    def setUp(self):
        self.tts = "http://192.168.122.10:8123/api/tts_proxy/x.mp3"
        self.now = [1000.0]

    def _sleep(self, secs):
        self.now[0] += secs

    def _cap(self):
        return interaction.InteractionCapability(timer_factory=FakeTimer,
                                                 clock=lambda: self.now[0],
                                                 sleeper=self._sleep)

    def _watching_ha(self, seen, burn):
        ha = FakeHA(idle_state())

        def watch(entity_id, timeout=10):
            seen.append(timeout)
            self.now[0] += burn
            return idle_state()
        ha.get_entity_state = watch
        return ha

    def test_a_read_is_clipped_to_the_remaining_deadline(self):
        seen = []
        cap = self._cap(); ha = self._watching_ha(seen, 0.5)
        capability.run(cap, FakeCtx(ha),
                       {"mode": "say", "uri": self.tts, "uris": [self.tts],
                        "match_keys": [self.tts], "finish_timeouts": [3.0],
                        "deadline_from_now": 3.0}, "rid-dl")
        self.assertTrue(seen)
        self.assertTrue(all(t <= 3.0 for t in seen), seen)
        self.assertTrue(min(seen) < 10)

    def test_no_blocking_call_is_started_below_the_floor(self):
        seen = []
        cap = self._cap(); ha = self._watching_ha(seen, 0.9)
        capability.run(cap, FakeCtx(ha),
                       {"mode": "say", "uri": self.tts, "uris": [self.tts],
                        "match_keys": [self.tts], "finish_timeouts": [1.0],
                        "deadline_from_now": 1.0}, "rid-fl")
        self.assertTrue(all(t >= 0.5 for t in seen), seen)

    def test_say_and_say_text_still_bound_by_accumulated_sleep(self):
        seen = []
        cap = self._cap(); ha = self._watching_ha(seen, 30.0)
        capability.run(cap, FakeCtx(ha), {"mode": "say", "uri": self.tts}, "rid-acc")
        # No deadline: the default timeout is used unclipped, exactly as today.
        self.assertEqual(set(seen), set([10]))
```

- [ ] **Step 2: Run to verify failure.**

Run: `python tests/test_interaction.py ClipSequenceTest ClipDeadlineTest -v`
Expected: FAIL — `test_two_clips_play_in_order...` emits only one `play_media` (the `uris` key is
ignored); `test_volume_override_is_used_not_reply_volume` writes `0.40`;
`test_the_chime_match_key...` raises `KeyError: 'clips'`; the deadline tests see only `10`.

- [ ] **Step 3: Resolve the turn volume once.** Replace `_say`'s existing `reply_volume` local:

```python
            override = resolved.get("volume_override")
            reply_volume = (float(override) if override is not None
                            else float(getattr(ctx.settings, "reply_volume", 0.40)))
```

**`is None`, never `or`** — `0.0` is a legitimate override that `or` would discard.

- [ ] **Step 4: Replace Task 11's single call with the loop.**

```python
            uris = resolved.get("uris") or [uri]
            match_keys = resolved.get("match_keys") or uris
            finish_timeouts = resolved.get("finish_timeouts") or ([reply_timeout] * len(uris))
            dl = resolved.get("deadline_from_now")
            deadline = (self._clock() + float(dl)) if dl is not None else None
            base_opts = {"call_timeout": call_timeout, "poll_secs": poll_secs,
                         "blank_grace": int(getattr(ctx.settings, "say_blank_cid_grace_ms", 4000)) / 1000.0,
                         "deadline": deadline,
                         "floor": int(getattr(ctx.settings, "announce_min_call_timeout_ms", 500)) / 1000.0,
                         "start_timeout": start_timeout}
            clip_results = []
            for i, one in enumerate(uris):
                norm_uri = self._normalise_uri(one, getattr(ctx.settings, "say_internal_base", ""))
                norm_key = self._normalise_uri(match_keys[i],
                                               getattr(ctx.settings, "say_internal_base", ""))
                one_clip = self._clip_id(norm_uri)
                opts = dict(base_opts)
                opts["finish_timeout"] = finish_timeouts[i]
                res = self._play_clip_and_wait(ctx, rid, zone, norm_uri, norm_key, one_clip,
                                               opts, superseded)
                play_issued[0] = play_issued[0] or res["issued"]
                clip_results.append({"clip": one_clip, "started": res["started"],
                                     "issued": res["issued"]})
                if superseded():
                    return superseded_result()
            reply_started = bool(clip_results) and clip_results[-1]["started"]
            likely_silent = not reply_started
```

`reply_started` tracks the **last** clip — the message. A chime that fails is not the reply failing;
§8.3 makes that asymmetry explicit.

- [ ] **Step 5: Add `clips` to the success metadata.** In the final `cr.ok`, add
  `"clips": clip_results` alongside the existing keys.

- [ ] **Step 6: Run to verify pass.**

Run: `python tests/test_interaction.py ClipSequenceTest ClipDeadlineTest -v` → PASS, 11 tests.
Run: `python tests/test_interaction.py GoldenSequenceTest -v` → **still PASS.**
Run: `python -m unittest discover -s tests -t .` → `Ran 418 tests ... OK`.

- [ ] **Step 7: Commit.**

```bash
git add interaction.py tests/test_interaction.py
git commit -m "feat(resolver): play an ordered clip sequence in one reply-owned turn"
```

---

### Task 13: Generation adoption — revalidate atomically

**Window:** steps F–G only, about **17 s** (§9.2) — the mic state capture (10 s), the `switch.turn_on`
write (5 s) and up to 2 s of confirmation. The two URL resolutions happen at C/D, **before** the
claim, so they are not in this window.

**Files:**
- Modify: `docs/homebrain/mass-resolver/interaction.py:556-579`, plus a new `_claim_gen`
- Test: `docs/homebrain/mass-resolver/tests/test_interaction.py`

**Interfaces:**
- Consumes: `_say`'s existing `_say_gen` / `_replies` bookkeeping.
- Produces: `_claim_gen(self, zone)` → `int`; `_say` honouring `resolved["gen"]` with an atomic
  staleness check. Tasks 14 and 15 consume `_claim_gen`.

- [ ] **Step 1: Write the failing tests.**

```python
class GenerationAdoptionTest(unittest.TestCase):
    """AN-01 Task 13: design 9.2. A pre-claimed gen is stale by the time _say adopts it; adopting
    it unchecked lets a stale announcement overwrite a NEWER turn's ownership marker -- the
    ratchet/crater the S1b-2 ownership decision exists to prevent."""

    def setUp(self):
        self.zone = "media_player.ceiling_speakers"
        self.tts = "http://192.168.122.10:8123/api/tts_proxy/x.mp3"

    def _cap(self):
        return interaction.InteractionCapability(timer_factory=FakeTimer, clock=lambda: 1000.0,
                                                 sleeper=FakeSleeper())

    def test_claim_gen_bumps_and_returns_the_new_generation(self):
        cap = self._cap()
        self.assertEqual(cap._claim_gen(self.zone), 1)
        self.assertEqual(cap._claim_gen(self.zone), 2)

    def test_a_stale_gen_aborts_before_publishing_anything(self):
        cap = self._cap()
        mine = cap._claim_gen(self.zone)
        cap._claim_gen(self.zone)                       # a newer turn arrives
        ha = FakeHA(playing(0.36))
        r = capability.run(cap, FakeCtx(ha),
                           {"mode": "say", "uri": self.tts, "gen": mine}, "rid-st")
        self.assertTrue(r["ok"])
        self.assertTrue(r["metadata"]["superseded"])
        self.assertEqual(ha.calls, [])                  # no volume_set, no play_media
        self.assertNotIn(self.zone, cap._replies)       # the marker was never published

    def test_a_stale_gen_does_not_overwrite_a_newer_turns_marker(self):
        cap = self._cap()
        mine = cap._claim_gen(self.zone)
        newer = cap._claim_gen(self.zone)
        cap._replies[self.zone] = {"gen": newer, "baseline": 0.42, "ts": 1000.0, "rid": "newer"}
        ha = FakeHA(playing(0.36))
        capability.run(cap, FakeCtx(ha),
                       {"mode": "say", "uri": self.tts, "gen": mine}, "rid-st2")
        self.assertEqual(cap._replies[self.zone]["gen"], newer)
        self.assertEqual(cap._replies[self.zone]["baseline"], 0.42)

    def test_a_current_gen_is_adopted_and_publishes_normally(self):
        cap = self._cap()
        mine = cap._claim_gen(self.zone)
        ha = FakeHA(playing(0.36))
        ha.set_states([playing_with_id(0.36, "library://radio/2"),
                       playing_with_id(0.40, "builtin://radio/" + self.tts),
                       idle_state(), idle_state(), playing(0.40)])
        r = capability.run(cap, FakeCtx(ha),
                           {"mode": "say", "uri": self.tts, "gen": mine}, "rid-ok")
        self.assertTrue(r["ok"])
        self.assertFalse(r["metadata"]["superseded"])
        self.assertIn("play_media", [c[1] for c in ha.calls])

    def test_no_supplied_gen_bumps_its_own_exactly_as_today(self):
        cap = self._cap()
        ha = FakeHA(playing(0.36))
        ha.set_states([playing_with_id(0.36, "library://radio/2"),
                       playing_with_id(0.40, "builtin://radio/" + self.tts),
                       idle_state(), idle_state(), playing(0.40)])
        capability.run(cap, FakeCtx(ha), {"mode": "say", "uri": self.tts}, "rid-own")
        self.assertEqual(cap._say_gen[self.zone], 1)
```

- [ ] **Step 2: Run to verify failure.**

Run: `python tests/test_interaction.py GenerationAdoptionTest -v`
Expected: FAIL — `test_claim_gen_bumps...` raises
`AttributeError: ... has no attribute '_claim_gen'`; the two stale-gen tests emit calls and publish a
marker because `resolved["gen"]` is ignored.

- [ ] **Step 3: Add the helper** near `_reply_baseline`:

```python
    def _claim_gen(self, zone):
        """Claim this zone's next turn generation up front.

        _announce needs turn ownership BEFORE it touches the microphone (requirement 1), which is
        earlier than _say's step 2. One counter, one meaning; _say revalidates on adoption.
        """
        with self._lock:
            my_gen = self._say_gen.get(zone, 0) + 1
            self._say_gen[zone] = my_gen
            return my_gen
```

- [ ] **Step 4: Revalidate on adoption.** Replace the head of `_say`'s step-2 lock block:

```python
        supplied_gen = resolved.get("gen")
        with self._lock:
            if supplied_gen is not None:
                # A pre-claimed gen is STALE by the time we see it: the caller spent up to ~17s on
                # the mic capture, write and confirmation (design 9.2). If a turn arrived in that
                # window, publishing our marker would overwrite ITS ownership. Check and publish
                # under ONE lock -- a check outside it is the same race one instruction later.
                if self._say_gen.get(zone) != supplied_gen:
                    LOG.info("SAY req=%s zone=%s adoption aborted: gen %s is stale (now %s)",
                             rid, zone, supplied_gen, self._say_gen.get(zone))
                    return cr.ok(self.name, rid, "Said.", spoken_text=None,
                                 metadata={"said": False, "reply_started": False,
                                           "likely_silent": False, "replayed": False,
                                           "superseded": True, "zone": zone})
                my_gen = supplied_gen
            else:
                my_gen = self._say_gen.get(zone, 0) + 1
                self._say_gen[zone] = my_gen
            baseline = self._reply_baseline(zone, prev_volume)
            # ... the rest of the existing block is unchanged ...
```

The early return is a literal `cr.ok`, not the `superseded_result()` closure — that closure is defined
*after* this block. The metadata shape is identical.

**The abort still unmutes:** `_announce`'s `finally` runs regardless, and §9.4's lease check is on
`_mic`, not `_say_gen`, so a stale announcement that aborts here does release its microphone unless a
newer *announcement* took the lease. Task 14 asserts that.

- [ ] **Step 5: Run to verify pass.**

Run: `python tests/test_interaction.py GenerationAdoptionTest -v` → PASS, 5 tests.
Run: `python tests/test_interaction.py GoldenSequenceTest -v` → still PASS.
Run: `python -m unittest discover -s tests -t .` → `Ran 423 tests ... OK`.

- [ ] **Step 6: Commit.**

```bash
git add interaction.py tests/test_interaction.py
git commit -m "feat(resolver): revalidate a pre-claimed turn generation atomically on adoption"
```

---

### Task 14: Microphone leasing — capture, inherit, mute, confirm, release, dead-man

The design's most subtle piece. `_mic` is written **only** by `_announce` (§9.1) — that single
invariant is what makes a non-announcement supersession unmute immediately instead of stranding the
mute.

**Files:**
- Modify: `docs/homebrain/mass-resolver/interaction.py` — `__init__` (add `self._mic = {}`), plus new
  `_mic_claim`, `_mic_confirm`, `_mic_release`, `_mic_deadman` methods
- Test: `docs/homebrain/mass-resolver/tests/test_interaction.py`

**Interfaces:**
- Consumes: `_claim_gen` (Task 13); **D1** (entity ID), **D2** (muting suppresses wake detection),
  **D14** (HA does not report `on` for an unreachable device) from Checkpoint A.
- Produces:
  - `_mic_claim(self, ctx, zone, my_gen, rid)` → `(lease_dict, err_dict_or_None)`. Reads the switch,
    inherits `prev` from an existing lease, writes `switch.turn_on`, arms the dead-man.
  - `_mic_confirm(self, ctx, zone, my_gen, rid)` → `(True, None)` or `(False, err_dict)`.
  - `_mic_release(self, ctx, zone, my_gen, rid)` → `bool` (whether it restored).
  Task 15 consumes all three.

- [ ] **Step 1: Write the failing tests.**

```python
class MicLeaseTest(unittest.TestCase):
    """AN-01 Task 14: design 9.1-9.5.

    A successful switch.turn_on is an accepted REQUEST, not a muted microphone: HA may accept it for
    a device that never receives it (this satellite drops its ESPHome API with Errno 113). So the
    state is read back before any audio, and announce_require_mic_mute means what it says."""

    ENT = "switch.respeaker_test_microphone_mute"

    def setUp(self):
        FakeTimer.created = []
        self.zone = "media_player.ceiling_speakers"

    def _cap(self):
        return interaction.InteractionCapability(timer_factory=FakeTimer, clock=lambda: 1000.0,
                                                 sleeper=FakeSleeper())

    def _ctx(self, ha):
        ctx = FakeCtx(ha)
        ctx.settings.announce_mic_mute_entity = self.ENT
        return ctx

    def test_claim_reads_prev_then_writes_turn_on(self):
        cap = self._cap()
        ha = FakeHA({"state": "off", "attributes": {}})
        ctx = self._ctx(ha)
        lease, err = cap._mic_claim(ctx, self.zone, cap._claim_gen(self.zone), "rid-m")
        self.assertIsNone(err)
        self.assertFalse(lease["prev"])
        self.assertEqual([(d, s) for d, s, _ in ha.calls], [("switch", "turn_on")])
        self.assertEqual(ha.calls[0][2]["entity_id"], self.ENT)

    def test_prev_true_is_recorded_when_the_operator_already_muted(self):
        cap = self._cap()
        ha = FakeHA({"state": "on", "attributes": {}})
        lease, err = cap._mic_claim(self._ctx(ha), self.zone, cap._claim_gen(self.zone), "rid-m")
        self.assertIsNone(err)
        self.assertTrue(lease["prev"])

    def test_a_second_announcement_inherits_prev_and_does_not_read_the_switch(self):
        # Without inheritance the second reads the live switch -- which the first set to `on` --
        # concludes muted was the operator's preference, and leaves the satellite deaf forever.
        cap = self._cap()
        ha = FakeHA({"state": "off", "attributes": {}})
        ctx = self._ctx(ha)
        cap._mic_claim(ctx, self.zone, cap._claim_gen(self.zone), "rid-a")
        ha._state = {"state": "on", "attributes": {}}
        reads = []
        real = ha.get_entity_state
        ha.get_entity_state = lambda e, timeout=10: (reads.append(e), real(e))[1]
        lease2, err = cap._mic_claim(ctx, self.zone, cap._claim_gen(self.zone), "rid-b")
        self.assertIsNone(err)
        self.assertFalse(lease2["prev"])              # inherited from rid-a, not re-read
        self.assertEqual(reads, [])

    def test_an_unresolved_entity_refuses(self):
        cap = self._cap()
        ha = FakeHA({"state": "off", "attributes": {}})
        ctx = FakeCtx(ha)
        ctx.settings.announce_mic_mute_entity = ""
        lease, err = cap._mic_claim(ctx, self.zone, cap._claim_gen(self.zone), "rid-m")
        self.assertIsNone(lease)
        self.assertEqual(err["code"], "unavailable")
        self.assertEqual(ha.calls, [])

    def test_a_read_failure_refuses(self):
        cap = self._cap()
        ha = FakeHA(boom=IOError("HA down"))
        lease, err = cap._mic_claim(self._ctx(ha), self.zone, cap._claim_gen(self.zone), "rid-m")
        self.assertIsNone(lease)
        self.assertEqual(err["code"], "unavailable")

    def test_a_write_failure_refuses(self):
        cap = self._cap()
        ha = FakeHA({"state": "off", "attributes": {}}, write_boom=IOError("no route"))
        lease, err = cap._mic_claim(self._ctx(ha), self.zone, cap._claim_gen(self.zone), "rid-m")
        self.assertIsNone(lease)
        self.assertEqual(err["code"], "unavailable")

    def test_confirmation_polls_until_on_then_proceeds(self):
        cap = self._cap()
        ha = FakeHA({"state": "off", "attributes": {}})
        ctx = self._ctx(ha)
        gen = cap._claim_gen(self.zone)
        cap._mic_claim(ctx, self.zone, gen, "rid-m")
        ha.set_states([{"state": "off", "attributes": {}},
                       {"state": "off", "attributes": {}},
                       {"state": "on", "attributes": {}}])
        ok, err = cap._mic_confirm(ctx, self.zone, gen, "rid-m")
        self.assertTrue(ok)
        self.assertIsNone(err)
        self.assertTrue(cap._mic[self.zone]["confirmed"])

    def test_confirm_timeout_refuses_and_is_bounded(self):
        cap = self._cap()
        ha = FakeHA({"state": "off", "attributes": {}})
        ctx = self._ctx(ha)
        gen = cap._claim_gen(self.zone)
        cap._mic_claim(ctx, self.zone, gen, "rid-m")
        ok, err = cap._mic_confirm(ctx, self.zone, gen, "rid-m")
        self.assertFalse(ok)
        self.assertEqual(err["code"], "unavailable")

    def test_a_raising_confirm_read_refuses_rather_than_propagating(self):
        cap = self._cap()
        ha = FakeHA({"state": "off", "attributes": {}})
        ctx = self._ctx(ha)
        gen = cap._claim_gen(self.zone)
        cap._mic_claim(ctx, self.zone, gen, "rid-m")
        ha._boom = IOError("read blip")
        ok, err = cap._mic_confirm(ctx, self.zone, gen, "rid-m")   # must not raise
        self.assertFalse(ok)
        self.assertEqual(err["code"], "unavailable")

    def test_require_false_proceeds_unconfirmed(self):
        cap = self._cap()
        ha = FakeHA({"state": "off", "attributes": {}})
        ctx = self._ctx(ha)
        ctx.settings.announce_require_mic_mute = False
        gen = cap._claim_gen(self.zone)
        cap._mic_claim(ctx, self.zone, gen, "rid-m")
        ok, err = cap._mic_confirm(ctx, self.zone, gen, "rid-m")
        self.assertFalse(ok)
        self.assertIsNone(err)                        # no refusal: broadcast anyway
        self.assertFalse(cap._mic[self.zone]["confirmed"])

    def test_release_restores_prev_and_clears_the_lease(self):
        cap = self._cap()
        ha = FakeHA({"state": "off", "attributes": {}})
        ctx = self._ctx(ha)
        gen = cap._claim_gen(self.zone)
        cap._mic_claim(ctx, self.zone, gen, "rid-m")
        self.assertTrue(cap._mic_release(ctx, self.zone, gen, "rid-m"))
        self.assertEqual([(d, s) for d, s, _ in ha.calls],
                         [("switch", "turn_on"), ("switch", "turn_off")])
        self.assertNotIn(self.zone, cap._mic)

    def test_release_leaves_an_already_muted_switch_on(self):
        cap = self._cap()
        ha = FakeHA({"state": "on", "attributes": {}})
        ctx = self._ctx(ha)
        gen = cap._claim_gen(self.zone)
        cap._mic_claim(ctx, self.zone, gen, "rid-m")
        cap._mic_release(ctx, self.zone, gen, "rid-m")
        self.assertNotIn("turn_off", [s for _, s, _ in ha.calls])

    def test_release_is_a_no_op_when_a_newer_announcement_holds_the_lease(self):
        cap = self._cap()
        ha = FakeHA({"state": "off", "attributes": {}})
        ctx = self._ctx(ha)
        first = cap._claim_gen(self.zone)
        cap._mic_claim(ctx, self.zone, first, "rid-a")
        second = cap._claim_gen(self.zone)
        cap._mic_claim(ctx, self.zone, second, "rid-b")
        before = len(ha.calls)
        self.assertFalse(cap._mic_release(ctx, self.zone, first, "rid-a"))
        self.assertEqual(len(ha.calls), before)
        self.assertEqual(cap._mic[self.zone]["gen"], second)

    def test_the_second_release_restores_the_original_prev(self):
        cap = self._cap()
        ha = FakeHA({"state": "off", "attributes": {}})
        ctx = self._ctx(ha)
        first = cap._claim_gen(self.zone)
        cap._mic_claim(ctx, self.zone, first, "rid-a")
        second = cap._claim_gen(self.zone)
        cap._mic_claim(ctx, self.zone, second, "rid-b")
        cap._mic_release(ctx, self.zone, second, "rid-b")
        self.assertIn("turn_off", [s for _, s, _ in ha.calls])
        self.assertNotIn(self.zone, cap._mic)

    def test_a_write_failure_on_release_keeps_the_lease_for_the_dead_man(self):
        cap = self._cap()
        ha = FakeHA({"state": "off", "attributes": {}})
        ctx = self._ctx(ha)
        gen = cap._claim_gen(self.zone)
        cap._mic_claim(ctx, self.zone, gen, "rid-m")
        ha._write_boom = IOError("no route")
        self.assertFalse(cap._mic_release(ctx, self.zone, gen, "rid-m"))
        self.assertIn(self.zone, cap._mic)


class MicDeadManTest(unittest.TestCase):
    """AN-01 Task 14: design 9.5. A stuck-muted microphone is a DEAF satellite -- a silent,
    open-ended failure nobody finds until they try to talk to it.

    The duration is a POLICY CUTOFF derived from an engineered budget, not a wall-clock bound: a
    pathologically slow-but-live turn could cross it. The trade-off favours liveness."""

    ENT = "switch.respeaker_test_microphone_mute"

    def setUp(self):
        FakeTimer.created = []
        self.zone = "media_player.ceiling_speakers"

    def _cap(self):
        return interaction.InteractionCapability(timer_factory=FakeTimer, clock=lambda: 1000.0,
                                                 sleeper=FakeSleeper())

    def _ctx(self, ha):
        ctx = FakeCtx(ha)
        ctx.settings.announce_mic_mute_entity = self.ENT
        return ctx

    def test_claim_arms_a_timer(self):
        cap = self._cap()
        ha = FakeHA({"state": "off", "attributes": {}})
        cap._mic_claim(self._ctx(ha), self.zone, cap._claim_gen(self.zone), "rid-m")
        self.assertEqual(len(FakeTimer.created), 1)
        self.assertTrue(FakeTimer.created[0].started)

    def test_derived_mic_deadman_is_about_185s_with_shipped_defaults(self):
        cap = self._cap()
        ha = FakeHA({"state": "off", "attributes": {}})
        cap._mic_claim(self._ctx(ha), self.zone, cap._claim_gen(self.zone), "rid-m")
        self.assertAlmostEqual(FakeTimer.created[0].interval, 182.0, delta=6.0)

    def test_an_explicit_deadman_ms_overrides_the_derivation(self):
        cap = self._cap()
        ha = FakeHA({"state": "off", "attributes": {}})
        ctx = self._ctx(ha)
        ctx.settings.announce_mic_deadman_ms = 30000
        cap._mic_claim(ctx, self.zone, cap._claim_gen(self.zone), "rid-m")
        self.assertEqual(FakeTimer.created[0].interval, 30.0)

    def test_release_cancels_it(self):
        cap = self._cap()
        ha = FakeHA({"state": "off", "attributes": {}})
        ctx = self._ctx(ha)
        gen = cap._claim_gen(self.zone)
        cap._mic_claim(ctx, self.zone, gen, "rid-m")
        cap._mic_release(ctx, self.zone, gen, "rid-m")
        self.assertTrue(FakeTimer.created[0].cancelled)

    def test_firing_restores_prev(self):
        cap = self._cap()
        ha = FakeHA({"state": "off", "attributes": {}})
        ctx = self._ctx(ha)
        cap._mic_claim(ctx, self.zone, cap._claim_gen(self.zone), "rid-m")
        FakeTimer.created[0].fire()
        self.assertIn("turn_off", [s for _, s, _ in ha.calls])
        self.assertNotIn(self.zone, cap._mic)

    def test_firing_does_nothing_once_a_newer_announcement_owns_the_lease(self):
        cap = self._cap()
        ha = FakeHA({"state": "off", "attributes": {}})
        ctx = self._ctx(ha)
        cap._mic_claim(ctx, self.zone, cap._claim_gen(self.zone), "rid-a")
        stale = FakeTimer.created[0]
        cap._mic_claim(ctx, self.zone, cap._claim_gen(self.zone), "rid-b")
        before = len([s for _, s, _ in ha.calls if s == "turn_off"])
        stale.fire()
        self.assertEqual(len([s for _, s, _ in ha.calls if s == "turn_off"]), before)
        self.assertIn(self.zone, cap._mic)
```

- [ ] **Step 2: Run to verify failure.**

Run: `python tests/test_interaction.py MicLeaseTest MicDeadManTest -v`
Expected: FAIL — every test raises
`AttributeError: 'InteractionCapability' object has no attribute '_mic_claim'`.

- [ ] **Step 3: Add the state.** In `__init__`, after `self._replies = {}`:

```python
        self._mic = {}                                # zone -> {"gen", "prev", "confirmed",
                                                      #          "rid", "ts", "timer"}
                                                      #   WRITTEN ONLY BY _announce. Nothing else in
                                                      #   this class touches it -- that invariant is
                                                      #   why a NON-announcement supersession unmutes
                                                      #   immediately instead of stranding the mute
                                                      #   (design 9.1/9.4/9.6).
```

- [ ] **Step 4: Implement the four methods** (place them after `_claim_gen`):

```python
    def _mic_budget_s(self, ctx, clips):
        """Policy cutoff for the mic dead-man, derived from the engineered phase budget (design
        6.5). NOT a wall-clock bound: a pathologically slow-but-live turn can cross it. Firing
        early costs a few seconds of self-wake exposure; never firing leaves the satellite deaf
        with nothing scheduled to fix it, so the trade-off favours liveness."""
        explicit = int(getattr(ctx.settings, "announce_mic_deadman_ms", 0))
        if explicit > 0:
            return explicit / 1000.0
        start = int(getattr(ctx.settings, "say_start_timeout_ms", 5000)) / 1000.0
        call = int(getattr(ctx.settings, "say_call_timeout_ms", 20000)) / 1000.0
        confirm = int(getattr(ctx.settings, "announce_mic_confirm_timeout_ms", 2000)) / 1000.0
        chime_fin = int(getattr(ctx.settings, "announce_chime_finish_timeout_ms", 15000)) / 1000.0
        msg_fin = int(getattr(ctx.settings, "announce_message_finish_timeout_ms", 45000)) / 1000.0
        floor = int(getattr(ctx.settings, "announce_min_call_timeout_ms", 500)) / 1000.0
        # rows 5-16 of the design 6.5 table, then 30s of margin
        total = (confirm + 5.0 + 5.0                       # confirm, pause, raise
                 + call + start + chime_fin                # chime
                 + call + start + msg_fin                  # message
                 + 5.0 + call + 5.0                        # restore, replay, unmute
                 + 5 * floor)
        if clips < 2:
            total -= (call + start + chime_fin)
        return total + 30.0

    def _mic_claim(self, ctx, zone, my_gen, rid, clips=2):
        """Lease the microphone and mute it. Returns (lease, err); err is a dict for cr.err."""
        entity = (getattr(ctx.settings, "announce_mic_mute_entity", "") or "").strip()
        require = bool(getattr(ctx.settings, "announce_require_mic_mute", True))
        refusal = {"code": "unavailable", "reason": "mic mute unavailable",
                   "chat_text": "I can't announce without muting the microphone."}
        if not entity:
            LOG.warning("ANNOUNCE req=%s no announce_mic_mute_entity configured", rid)
            return (None, refusal if require else None)
        with self._lock:
            existing = self._mic.get(zone)
            inherited = existing["prev"] if existing is not None else None
        if inherited is None:
            # First claim: read the live state. A later announcement INHERITS this instead of
            # re-reading, or it would see the `on` we just wrote and treat muted as the
            # operator's preference -- leaving the satellite deaf forever (design 9.2).
            try:
                st = ctx.ha.get_entity_state(entity) or {}
            except Exception as e:
                LOG.warning("ANNOUNCE req=%s could not read %s (%r)", rid, entity, e)
                return (None, refusal if require else None)
            inherited = (st.get("state") == "on")
        lease = {"gen": my_gen, "prev": bool(inherited), "confirmed": False,
                 "rid": rid, "ts": self._clock(), "timer": None}
        with self._lock:
            self._mic[zone] = lease            # published BEFORE the write, so a crash between
                                               #   write and confirm still leaves something for the
                                               #   dead-man and the finally to reconcile
        try:
            ctx.ha.call_service_rest("switch", "turn_on", {"entity_id": entity})
        except Exception as e:
            LOG.warning("ANNOUNCE req=%s switch.turn_on %s failed (%r)", rid, entity, e)
            with self._lock:
                if self._mic.get(zone) is lease:
                    del self._mic[zone]
            return (None, refusal if require else None)
        secs = self._mic_budget_s(ctx, clips)
        t = self._timer_factory(secs, self._mic_deadman, [ctx, zone, my_gen])
        lease["timer"] = t
        t.start()
        LOG.info("ANNOUNCE req=%s zone=%s mic leased gen=%s prev=%s deadman=%.0fs",
                 rid, zone, my_gen, lease["prev"], secs)
        return (lease, None)

    def _mic_confirm(self, ctx, zone, my_gen, rid):
        """Poll the switch until it reports `on`. A 200 from switch.turn_on means HA ACCEPTED the
        request, not that the microphone is muted -- this satellite drops its ESPHome API
        (Errno 113), so requirement 7's fail-safe would otherwise be satisfied by an accepted
        request rather than an observed state (design 9.3)."""
        entity = (getattr(ctx.settings, "announce_mic_mute_entity", "") or "").strip()
        require = bool(getattr(ctx.settings, "announce_require_mic_mute", True))
        budget = int(getattr(ctx.settings, "announce_mic_confirm_timeout_ms", 2000)) / 1000.0
        step = max(int(getattr(ctx.settings, "announce_mic_confirm_poll_ms", 250)) / 1000.0, 0.05)
        floor = int(getattr(ctx.settings, "announce_min_call_timeout_ms", 500)) / 1000.0
        deadline = self._clock() + budget
        while True:
            left = deadline - self._clock()
            if left < floor:
                break
            try:
                st = ctx.ha.get_entity_state(entity, timeout=min(10, max(left, floor))) or {}
            except Exception as e:
                # A read blip must produce the documented refusal, not a bare traceback.
                LOG.warning("ANNOUNCE req=%s confirm read of %s failed (%r)", rid, entity, e)
                st = {}
            if st.get("state") == "on":
                with self._lock:
                    lease = self._mic.get(zone)
                    if lease is not None and lease.get("gen") == my_gen:
                        lease["confirmed"] = True
                LOG.info("ANNOUNCE req=%s zone=%s mic mute CONFIRMED", rid, zone)
                return (True, None)
            self._sleeper(step)
        LOG.warning("ANNOUNCE req=%s zone=%s mic mute NOT confirmed within %.1fs (require=%s)",
                    rid, zone, budget, require)
        if require:
            return (False, {"code": "unavailable", "reason": "mic mute not confirmed",
                            "chat_text": "I couldn't mute the microphone, so I didn't announce."})
        return (False, None)

    def _mic_release(self, ctx, zone, my_gen, rid):
        """Restore the microphone -- only if the LEASE is still ours.

        The check is on _mic, not _say_gen. Zone supersession by a satellite reply or a say_text
        turn bumps _say_gen but never writes _mic, so the lease is still ours and we unmute
        IMMEDIATELY -- which is what is wanted: the superseding turn is a person talking to the
        satellite (design 9.4/9.6)."""
        entity = (getattr(ctx.settings, "announce_mic_mute_entity", "") or "").strip()
        with self._lock:
            lease = self._mic.get(zone)
            if lease is None or lease.get("gen") != my_gen:
                LOG.info("ANNOUNCE req=%s zone=%s mic release skipped: lease is not ours", rid, zone)
                return False
        self._cancel_timer(lease)
        if lease.get("prev"):
            # The operator already had it muted; leave it muted.
            with self._lock:
                if self._mic.get(zone) is lease:
                    del self._mic[zone]
            LOG.info("ANNOUNCE req=%s zone=%s mic left muted (prev=on)", rid, zone)
            return True
        try:
            ctx.ha.call_service_rest("switch", "turn_off", {"entity_id": entity})
        except Exception as e:
            LOG.error("ANNOUNCE req=%s zone=%s mic unmute FAILED (%r); dead-man must reconcile",
                      rid, zone, e)
            return False
        with self._lock:
            if self._mic.get(zone) is lease:
                del self._mic[zone]
        LOG.info("ANNOUNCE req=%s zone=%s mic restored", rid, zone)
        return True

    def _mic_deadman(self, ctx, zone, my_gen):
        LOG.warning("ANNOUNCE mic dead-man fired zone=%s gen=%s; restoring the microphone",
                    zone, my_gen)
        try:
            self._mic_release(ctx, zone, my_gen, "mic-deadman")
        except Exception as e:
            LOG.error("ANNOUNCE mic dead-man failed zone=%s (%r)", zone, e)
```

**`_cancel_timer(lease)` reuse:** the existing `_cancel_timer` takes any dict with a `"timer"` key, so
the lease works unchanged. Verify that when writing the code.

- [ ] **Step 5: Run to verify pass.**

Run: `python tests/test_interaction.py MicLeaseTest MicDeadManTest -v` → PASS, 21 tests.
Run: `python -m unittest discover -s tests -t .` → `Ran 444 tests ... OK`.

- [ ] **Step 6: Commit.**

```bash
git add interaction.py tests/test_interaction.py
git commit -m "feat(resolver): lease and confirm the satellite mic mute for an announcement"
```

---

### Task 15: `_announce` — the orchestration, result relay text, and honest failure mapping

**Files:**
- Modify: `docs/homebrain/mass-resolver/interaction.py` — `execute()` gains an `announce` branch, plus
  the new `_announce`
- Test: `docs/homebrain/mass-resolver/tests/test_interaction.py`

**Interfaces:**
- Consumes: `_render_announcement_text` (10), the clip-sequence keys (12), `_claim_gen` (13),
  `_mic_claim` / `_mic_confirm` / `_mic_release` (14), `ctx.ha.tts_get_url`,
  `ctx.ha.resolve_media_source` (8); **D4** (does MA fetch the chime) from Checkpoint A.
- Produces: `mode=announce` end to end, with `chat_text` `"Announced."` on success and an
  operator-readable string on every failure. Task 26's automation relays that `chat_text`.

**Order (§7).** `A` validate → `B` render+bound → `C` resolve TTS → `D` resolve chime →
`E` claim gen → `F` mic claim → `G` mic confirm → `H` `_say` → `I` map outcome → `finally` release.
C before F is deliberate: a TTS failure is the likeliest failure in the sequence, and paying for it
with a muted microphone and a raised volume would be gratuitous.

- [ ] **Step 1: Write the failing tests.**

```python
class AnnounceEndToEndTest(unittest.TestCase):
    """AN-01 Task 15: design 5, 7, 8.5, 10."""

    ENT = "switch.respeaker_test_microphone_mute"

    def setUp(self):
        FakeTimer.created = []
        self.zone = "media_player.ceiling_speakers"
        self.chime_signed = "http://192.168.122.10:8123/media/local/chime.wav?authSig=REDACTED"
        self.tts = "http://192.168.122.10:8123/api/tts_proxy/x.mp3"

    def _cap(self):
        return interaction.InteractionCapability(timer_factory=FakeTimer, clock=lambda: 1000.0,
                                                 sleeper=FakeSleeper())

    def _ha(self):
        ha = FakeHA(playing(0.36))
        ha.tts_url = self.tts
        ha.media_url = self.chime_signed
        ha.resolve_media_source = lambda uri, timeout=10: ha.media_url
        return ha

    def _ctx(self, ha):
        ctx = FakeCtx(ha)
        ctx.settings.announce_mic_mute_entity = self.ENT
        return ctx

    def _states(self):
        return [{"state": "off", "attributes": {}},                            # mic prev
                {"state": "on", "attributes": {}},                             # mic confirm
                playing_with_id(0.36, "library://radio/2"),                    # capture
                playing_with_id(0.80, "builtin://radio/" + self.chime_signed), # chime start
                idle_state(), idle_state(),                                    # chime end
                playing_with_id(0.80, "builtin://radio/" + self.tts),          # tts start
                idle_state(), idle_state(),                                    # tts end
                playing(0.80)]                                                 # restore read

    def test_golden_announce_call_order(self):
        cap = self._cap(); ha = self._ha(); ha.set_states(self._states())
        r = run(cap, self._ctx(ha), {"mode": "announce", "text": "dinner is ready"})
        self.assertTrue(r["ok"], r)
        self.assertEqual([(d, s) for d, s, _ in ha.calls],
                         [("switch", "turn_on"),
                          ("media_player", "media_pause"),
                          ("media_player", "volume_set"),
                          ("music_assistant", "play_media"),
                          ("music_assistant", "play_media"),
                          ("media_player", "volume_set"),
                          ("music_assistant", "play_media"),
                          ("switch", "turn_off")])
        self.assertEqual(ha.calls[2][2]["volume_level"], 0.80)
        self.assertEqual(ha.calls[5][2]["volume_level"], 0.36)

    def test_the_mic_is_muted_before_the_first_audio_call(self):
        cap = self._cap(); ha = self._ha(); ha.set_states(self._states())
        run(cap, self._ctx(ha), {"mode": "announce", "text": "dinner is ready"})
        svcs = [s for _, s, _ in ha.calls]
        self.assertLess(svcs.index("turn_on"), svcs.index("play_media"))
        self.assertLess(svcs.index("turn_on"), svcs.index("volume_set"))

    def test_success_chat_text_is_announced_not_said(self):
        cap = self._cap(); ha = self._ha(); ha.set_states(self._states())
        r = run(cap, self._ctx(ha), {"mode": "announce", "text": "dinner is ready"})
        self.assertEqual(r["chat_text"], "Announced.")
        self.assertIsNone(r["spoken_text"])

    def test_the_rendered_text_handed_to_tts_is_the_bounded_one(self):
        cap = self._cap(); ha = self._ha(); ha.set_states(self._states())
        ctx = self._ctx(ha)
        ctx.settings.announce_prefix = "Announcement."
        run(cap, ctx, {"mode": "announce", "text": "dinner is ready"})
        self.assertEqual(ha.tts_calls, [("tts.piper", "Announcement. dinner is ready")])

    def test_a_tts_failure_touches_nothing(self):
        cap = self._cap(); ha = self._ha()
        ha.tts_boom = IOError("tts down")
        r = run(cap, self._ctx(ha), {"mode": "announce", "text": "dinner is ready"})
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"]["code"], "upstream_error")
        self.assertEqual(ha.calls, [])                 # no mute, no volume, no audio

    def test_a_chime_resolve_failure_degrades_and_still_speaks(self):
        cap = self._cap(); ha = self._ha()

        def boom(uri, timeout=10):
            raise IOError("resolve failed")
        ha.resolve_media_source = boom
        ha.set_states([{"state": "off", "attributes": {}},
                       {"state": "on", "attributes": {}},
                       playing_with_id(0.36, "library://radio/2"),
                       playing_with_id(0.80, "builtin://radio/" + self.tts),
                       idle_state(), idle_state(), playing(0.80)])
        r = run(cap, self._ctx(ha), {"mode": "announce", "text": "dinner is ready"})
        self.assertTrue(r["ok"], r)
        self.assertFalse(r["metadata"]["chime"]["played"])
        self.assertEqual(r["metadata"]["chime"]["reason"], "resolve_failed")
        self.assertEqual(len([c for c in ha.calls if c[1] == "play_media"]), 2)   # tts + replay

    def test_an_empty_chime_uri_is_a_configured_skip(self):
        cap = self._cap(); ha = self._ha()
        ctx = self._ctx(ha)
        ctx.settings.announce_chime_uri = ""
        ha.set_states([{"state": "off", "attributes": {}},
                       {"state": "on", "attributes": {}},
                       playing_with_id(0.36, "library://radio/2"),
                       playing_with_id(0.80, "builtin://radio/" + self.tts),
                       idle_state(), idle_state(), playing(0.80)])
        r = run(cap, ctx, {"mode": "announce", "text": "dinner is ready"})
        self.assertTrue(r["ok"])
        self.assertEqual(r["metadata"]["chime"]["reason"], "disabled")

    def test_a_silent_message_is_an_honest_failure_not_a_success(self):
        # say_text returns ok with likely_silent; for a broadcast that is "claimed success, did
        # nothing" -- the exact class this stack keeps producing (design 8.5).
        cap = self._cap(); ha = self._ha()
        ha.set_states([{"state": "off", "attributes": {}},
                       {"state": "on", "attributes": {}},
                       playing_with_id(0.36, "library://radio/2"),
                       idle_state(), idle_state(), idle_state(), idle_state(),
                       idle_state(), idle_state(), idle_state(), idle_state(),
                       idle_state(), idle_state(), playing(0.80)])
        r = run(cap, self._ctx(ha), {"mode": "announce", "text": "dinner is ready"})
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"]["code"], "upstream_error")
        self.assertEqual(r["chat_text"], "I couldn't play the announcement.")

    def test_say_text_with_the_same_condition_still_returns_ok(self):
        # The divergence is intentional and pinned.
        cap = self._cap(); ha = FakeHA(playing(0.36)); ha.tts_url = self.tts
        ha.set_states([playing_with_id(0.36, "library://radio/2"),
                       idle_state(), idle_state(), idle_state(), idle_state(),
                       idle_state(), idle_state(), idle_state(), idle_state(),
                       idle_state(), idle_state(), playing(0.40)])
        r = run(cap, FakeCtx(ha), {"mode": "say_text", "text": "hello"})
        self.assertTrue(r["ok"])
        self.assertTrue(r["metadata"]["likely_silent"])

    def test_an_unconfirmed_mic_refuses_and_plays_nothing(self):
        cap = self._cap(); ha = self._ha()
        ha.set_states([{"state": "off", "attributes": {}},
                       {"state": "off", "attributes": {}},
                       {"state": "off", "attributes": {}},
                       {"state": "off", "attributes": {}},
                       {"state": "off", "attributes": {}}])
        r = run(cap, self._ctx(ha), {"mode": "announce", "text": "dinner is ready"})
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"]["code"], "unavailable")
        self.assertNotIn("play_media", [s for _, s, _ in ha.calls])
        self.assertNotIn("volume_set", [s for _, s, _ in ha.calls])

    def test_the_mic_is_released_even_when_the_message_never_starts(self):
        cap = self._cap(); ha = self._ha()
        ha.set_states([{"state": "off", "attributes": {}},
                       {"state": "on", "attributes": {}},
                       playing_with_id(0.36, "library://radio/2"),
                       idle_state(), idle_state(), idle_state(), idle_state(),
                       idle_state(), idle_state(), idle_state(), idle_state(),
                       idle_state(), idle_state(), playing(0.80)])
        r = run(cap, self._ctx(ha), {"mode": "announce", "text": "dinner is ready"})
        self.assertFalse(r["ok"])
        self.assertIn("turn_off", [s for _, s, _ in ha.calls])

    def test_each_failure_carries_an_operator_readable_chat_text(self):
        cap = self._cap()
        for setup, code in ((lambda ha: setattr(ha, "tts_boom", IOError("x")), "upstream_error"),):
            ha = self._ha(); setup(ha)
            r = run(cap, self._ctx(ha), {"mode": "announce", "text": "hi"})
            self.assertEqual(r["error"]["code"], code)
            self.assertTrue(r["chat_text"])
            self.assertNotIn("authSig", r["chat_text"])


class AnnounceSupersessionTest(unittest.TestCase):
    """AN-01 Task 15: design 9.6. Only a newer ANNOUNCEMENT transfers the mic lease. A satellite
    reply or a say_text turn bumps _say_gen but never writes _mic, so the announcement unmutes
    immediately -- rev 1 of the design asserted the opposite and accepted a deaf period that the
    design does not actually produce."""

    ENT = "switch.respeaker_test_microphone_mute"

    def setUp(self):
        FakeTimer.created = []
        self.zone = "media_player.ceiling_speakers"
        self.tts = "http://192.168.122.10:8123/api/tts_proxy/x.mp3"

    def _cap(self):
        return interaction.InteractionCapability(timer_factory=FakeTimer, clock=lambda: 1000.0,
                                                 sleeper=FakeSleeper())

    def _ctx(self, ha):
        ctx = FakeCtx(ha)
        ctx.settings.announce_mic_mute_entity = self.ENT
        ctx.settings.announce_chime_uri = ""
        return ctx

    def _ha(self):
        ha = FakeHA(playing(0.36)); ha.tts_url = self.tts
        return ha

    def test_a_satellite_reply_superseding_an_announcement_unmutes_immediately(self):
        cap = self._cap(); ha = self._ha(); ctx = self._ctx(ha)
        bumped = [False]
        real = ha.get_entity_state

        def watch(entity_id, timeout=10):
            if entity_id == self.zone and not bumped[0]:
                bumped[0] = True
                cap._say_gen[self.zone] = cap._say_gen.get(self.zone, 0) + 5   # NOT via _announce
            return real(entity_id)
        ha.get_entity_state = watch
        ha.set_states([{"state": "off", "attributes": {}},
                       {"state": "on", "attributes": {}},
                       playing_with_id(0.36, "library://radio/2"),
                       playing_with_id(0.80, "builtin://radio/" + self.tts)])
        r = run(cap, ctx, {"mode": "announce", "text": "dinner is ready"})
        svcs = [s for _, s, _ in ha.calls]
        self.assertIn("turn_off", svcs)                       # the mic IS restored
        self.assertEqual(len([s for s in svcs if s == "volume_set"]), 1)   # raise only, no restore

    def test_zone_supersession_does_not_transfer_the_mic_lease(self):
        cap = self._cap(); ha = self._ha(); ctx = self._ctx(ha)
        gen = cap._claim_gen(self.zone)
        cap._mic_claim(ctx, self.zone, gen, "rid-a")
        cap._say_gen[self.zone] = gen + 9                      # a non-announcement turn
        self.assertEqual(cap._mic[self.zone]["gen"], gen)
        self.assertTrue(cap._mic_release(ctx, self.zone, gen, "rid-a"))
```

**`FakeHA` needs two additions in this step:** a `resolve_media_source` attribute (the tests assign a
lambda, so only a default is needed) and support for `get_entity_state(entity, timeout=...)`. Add
`def resolve_media_source(self, uri, timeout=10): return self.media_url` and give
`get_entity_state` a `timeout=10` keyword.

- [ ] **Step 2: Run to verify failure.**

Run: `python tests/test_interaction.py AnnounceEndToEndTest AnnounceSupersessionTest -v`
Expected: FAIL — `test_golden_announce_call_order` emits no calls at all, because `execute()` has no
`announce` branch and falls through to `_restore` ("Nothing to restore.").

- [ ] **Step 3: Add the `execute` branch.** After the `say_text` clause:

```python
        if resolved["mode"] == "announce":
            return self._announce(ctx, resolved, rid)
```

- [ ] **Step 4: Implement `_announce`** (place it after `_say_text`):

```python
    def _announce(self, ctx, resolved, rid):
        """Broadcast a sentence on the zone: chime + speech, as one reply-owned turn.

        Ordering (design 7) puts every cheap failure before anything is touched: both URLs are
        resolved BEFORE the microphone is muted or the volume is raised, so a TTS failure -- the
        likeliest failure here -- costs nothing.
        """
        zone = resolved["zone"]
        rendered, err, prefix_dropped = self._render_announcement_text(ctx, resolved.get("text"))
        if err is not None:
            return cr.err(self.name, rid, err["code"], err["reason"], err["chat_text"],
                          spoken_text=None,
                          metadata={"announced": False, "zone": zone,
                                    "prefix_dropped": prefix_dropped})

        # C. TTS clip. Nothing has been touched yet, so a failure here is free.
        engine = getattr(ctx.settings, "tts_engine", "") or "tts.piper"
        try:
            tts_uri = ctx.ha.tts_get_url(engine, rendered)
        except Exception as e:
            LOG.warning("ANNOUNCE req=%s zone=%s could not resolve text to a clip (%r)",
                        rid, zone, e)
            return cr.err(self.name, rid, "upstream_error", "tts_get_url failed",
                          "I couldn't say that.", spoken_text=None,
                          metadata={"announced": False, "zone": zone})
        if not tts_uri:
            LOG.warning("ANNOUNCE req=%s zone=%s resolved to an empty clip uri", rid, zone)
            return cr.err(self.name, rid, "upstream_error", "no clip uri",
                          "I couldn't say that.", spoken_text=None,
                          metadata={"announced": False, "zone": zone})

        # D. Chime. A failure DEGRADES: an announcement without its chime is still an
        #    announcement. Resolved per turn, never cached -- the signature expires.
        chime_uri = (getattr(ctx.settings, "announce_chime_uri", "") or "").strip()
        chime = {"played": False, "reason": None}
        chime_resolved = None
        if not chime_uri:
            chime["reason"] = "disabled"
        else:
            try:
                chime_resolved = ctx.ha.resolve_media_source(chime_uri)
            except Exception as e:
                # Never log the resolved URL: it is a bearer credential.
                LOG.warning("ANNOUNCE req=%s zone=%s chime resolve failed (%r); continuing "
                            "without a chime", rid, zone, e)
                chime["reason"] = "resolve_failed"

        uris = ([chime_resolved] if chime_resolved else []) + [tts_uri]
        # design 8.2: MA may not preserve the query string in the media_content_id it echoes, so
        # the chime matches on its PATH; TTS keeps full-URI matching, unchanged.
        match_keys = ([chime_resolved.split("?")[0]] if chime_resolved else []) + [tts_uri]
        finish_timeouts = (
            ([int(getattr(ctx.settings, "announce_chime_finish_timeout_ms", 15000)) / 1000.0]
             if chime_resolved else [])
            + [int(getattr(ctx.settings, "announce_message_finish_timeout_ms", 45000)) / 1000.0])

        # E. Claim the generation BEFORE touching the microphone (requirement 1).
        my_gen = self._claim_gen(zone)

        # F. Lease + mute.
        lease, mic_err = self._mic_claim(ctx, zone, my_gen, rid, clips=len(uris))
        if mic_err is not None:
            return cr.err(self.name, rid, mic_err["code"], mic_err["reason"],
                          mic_err["chat_text"], spoken_text=None,
                          metadata={"announced": False, "zone": zone,
                                    "mic": {"muted": False, "confirmed": False}})
        muted = lease is not None
        try:
            # G. CONFIRM by reading. A 200 is an accepted request, not a muted microphone.
            confirmed = False
            if muted:
                confirmed, conf_err = self._mic_confirm(ctx, zone, my_gen, rid)
                if conf_err is not None:
                    return cr.err(self.name, rid, conf_err["code"], conf_err["reason"],
                                  conf_err["chat_text"], spoken_text=None,
                                  metadata={"announced": False, "zone": zone,
                                            "mic": {"muted": True, "confirmed": False}})

            # H. One reply-owned turn.
            seq = dict(resolved)
            seq["uri"] = tts_uri
            seq["uris"] = uris
            seq["match_keys"] = match_keys
            seq["finish_timeouts"] = finish_timeouts
            seq["volume_override"] = float(getattr(ctx.settings, "announce_volume", 0.80))
            seq["gen"] = my_gen
            seq["deadline_from_now"] = sum(finish_timeouts) + (
                len(uris) * int(getattr(ctx.settings, "say_start_timeout_ms", 5000)) / 1000.0)
            # A pushed sentence is NOT confirmed by unrelated playback starting in the same turn.
            seq["skip_on_fresh_playback"] = False
            LOG.info("ANNOUNCE req=%s zone=%s clips=%d chars=%d volume=%s",
                     rid, zone, len(uris), len(rendered), seq["volume_override"])
            res = self._say(ctx, seq, rid)

            # I. Map the outcome. A silent announcement is a FAILURE, not a success: the caller is
            #    broadcasting to a room they may not be in (design 8.5).
            meta = dict(res.get("metadata") or {})
            clips = meta.get("clips") or []
            if chime_resolved and clips:
                chime["played"] = bool(clips[0].get("started"))
                if not chime["played"] and chime["reason"] is None:
                    chime["reason"] = "never_started"
            meta["chime"] = chime
            meta["mic"] = {"muted": muted, "confirmed": confirmed}
            meta["prefix_dropped"] = prefix_dropped
            meta["announced"] = bool(meta.get("said")) and not meta.get("likely_silent")
            if meta.get("superseded"):
                return cr.ok(self.name, rid, "Announced.", spoken_text=None, metadata=meta)
            if not meta["announced"]:
                return cr.err(self.name, rid, "upstream_error", "announcement did not start",
                              "I couldn't play the announcement.", spoken_text=None, metadata=meta)
            return cr.ok(self.name, rid, "Announced.", spoken_text=None, metadata=meta)
        finally:
            if muted:
                self._mic_release(ctx, zone, my_gen, rid)
```

- [ ] **Step 5: Run to verify pass.**

Run: `python tests/test_interaction.py AnnounceEndToEndTest AnnounceSupersessionTest -v` → PASS,
14 tests.
Run: `python tests/test_interaction.py GoldenSequenceTest -v` → still PASS.
Run: `python -m unittest discover -s tests -t .` → `Ran 458 tests ... OK`.

- [ ] **Step 6: Commit.**

```bash
git add interaction.py tests/test_interaction.py
git commit -m "feat(resolver): add interaction mode announce"
```

---

### Task 16: §8.4(c) — claim the restore obligation before issuing the volume raise

A **pre-existing** defect in `_say`, reachable by any reply today, that an announcement makes
dangerous: a louder stranded value, and **no volume dead-man at all**, because §3.5 means a phone
caller leaves no duck snapshot so `_arm_timer` never ran.

**Files:**
- Modify: `docs/homebrain/mass-resolver/interaction.py:639-650`
- Test: `docs/homebrain/mass-resolver/tests/test_interaction.py`

**Interfaces:**
- Consumes: `_say`'s existing `pending_restore`, `my_snap_ts`, `owns_restore` locals.
- Produces: no new signature. Task 19's volume dead-man arms at the same point.

- [ ] **Step 1: Write the failing tests.**

```python
class LostAckVolumeTest(unittest.TestCase):
    """AN-01 Task 16: design 8.4(c). interaction.py:640-642 sets pending_restore AFTER the write.

    A lost acknowledgement -- the write lands, the response does not -- skips the finally's restore
    and also skips the snap["target"] sync, so a later _restore reads 0.80, calls it user_override,
    KEEPS it and discards the baseline: the volume ratchet. For an announcement there is no duck
    snapshot and therefore no dead-man, so _say's finally is the only net -- exactly the net this
    defect disables."""

    def setUp(self):
        FakeTimer.created = []
        self.zone = "media_player.ceiling_speakers"
        self.tts = "http://192.168.122.10:8123/api/tts_proxy/x.mp3"

    def _cap(self):
        return interaction.InteractionCapability(timer_factory=FakeTimer, clock=lambda: 1000.0,
                                                 sleeper=FakeSleeper())

    def _lost_ack_ha(self):
        """Applies the volume write to its own state, THEN raises -- a lost ack."""
        ha = FakeHA(playing(0.36))
        ha.set_states([playing_with_id(0.36, "library://radio/2")])
        real = ha.call_service_rest
        state = {"raised": False}

        def lossy(domain, service, data, timeout=5):
            if service == "volume_set" and not state["raised"]:
                state["raised"] = True
                real(domain, service, data, timeout)      # the write LANDS
                raise IOError("connection reset after the write")
            real(domain, service, data, timeout)
        ha.call_service_rest = lossy
        return ha

    def test_a_lost_ack_on_the_volume_raise_still_restores_the_baseline(self):
        cap = self._cap(); ha = self._lost_ack_ha()
        r = capability.run(cap, FakeCtx(ha), {"mode": "say", "uri": self.tts}, "rid-la")
        self.assertFalse(r["ok"])
        vols = [c[2]["volume_level"] for c in ha.calls if c[1] == "volume_set"]
        self.assertEqual(vols, [0.40, 0.36])          # raised, then restored on the way out

    def test_the_snap_target_sync_precedes_the_write(self):
        # So a later _restore or dead-man agrees with the device instead of classifying our own
        # reply volume as a human override and discarding the baseline.
        cap = self._cap()
        cap._snaps[self.zone] = {"volume": 0.36, "target": 0.15, "ts": 900.0, "timer": None}
        ha = self._lost_ack_ha()
        capability.run(cap, FakeCtx(ha), {"mode": "say", "uri": self.tts}, "rid-sync")
        # The snapshot was retired by the abort-restore; if it survives, target must not be 0.15.
        snap = cap._snaps.get(self.zone)
        if snap is not None:
            self.assertNotEqual(snap["target"], 0.15)

    def test_a_redundant_restore_is_harmless(self):
        # The write never landed: the restore writes a value the zone already holds.
        cap = self._cap()
        ha = FakeHA(playing(0.36))
        ha.set_states([playing_with_id(0.36, "library://radio/2")])
        real = ha.call_service_rest
        state = {"n": 0}

        def refuse(domain, service, data, timeout=5):
            if service == "volume_set" and state["n"] == 0:
                state["n"] = 1
                raise IOError("refused before landing")
            real(domain, service, data, timeout)
        ha.call_service_rest = refuse
        r = capability.run(cap, FakeCtx(ha), {"mode": "say", "uri": self.tts}, "rid-red")
        self.assertFalse(r["ok"])
        self.assertEqual([c[2]["volume_level"] for c in ha.calls if c[1] == "volume_set"], [0.36])
```

- [ ] **Step 2: Run to verify failure.**

Run: `python tests/test_interaction.py LostAckVolumeTest -v`
Expected: FAIL — `test_a_lost_ack_on_the_volume_raise_still_restores_the_baseline` sees
`[0.40]` only: the restore never ran because `pending_restore` was still `False`.

- [ ] **Step 3: Implement — move the claim ahead of the write.** Replace `interaction.py:639-650`:

```python
            # Claim the restore obligation BEFORE issuing the write. Setting the flag first can
            # only cause a REDUNDANT restore to a value the zone already holds -- harmless and
            # idempotent. Setting it second can cause a MISSING restore, which is neither: a lost
            # acknowledgement (write lands, response does not) would strand the zone at the reply
            # volume, and for an announcement there is no duck snapshot and so no dead-man to
            # reconcile it (design 8.4c).
            pending_restore[0] = True
            if owns_restore:
                with self._lock:
                    snap = self._snaps.get(zone)
                    if snap is not None and snap.get("ts") == my_snap_ts:
                        # Keep the duck's "last value we wrote" in step with what we are ABOUT to
                        # write, so a turn that dies mid-write leaves a device a later reconciler
                        # agrees with -- rather than reading our reply volume as a human override,
                        # keeping it, and discarding the baseline (the ratchet).
                        snap["target"] = reply_volume
            self._say_call(ctx, rid, zone, "media_player", "volume_set",
                           {"entity_id": zone, "volume_level": reply_volume})
```

- [ ] **Step 4: Run to verify pass.**

Run: `python tests/test_interaction.py LostAckVolumeTest -v` → PASS, 3 tests.
Run: `python tests/test_interaction.py GoldenSequenceTest -v` → **still PASS** (the success path emits
the same calls in the same order; only a failure path changes).
Run: `python -m unittest discover -s tests -t .` → `Ran 461 tests ... OK`.

Watch `DuckOwnershipSlice4Test.test_say_crash_after_reply_volume_leaves_a_reconcilable_zone` — it
asserts precisely this reconcilability and should get *stronger*, not fail. If it fails, the snapshot
sync moved incorrectly.

- [ ] **Step 5: Commit.**

```bash
git add interaction.py tests/test_interaction.py
git commit -m "fix(resolver): claim the volume restore obligation before issuing the raise"
```

---

### Task 17: §8.3a — ambiguous-play recovery (`queue_may_be_replaced`)

> ### ⚠ The legacy un-pause test changes meaning — read before implementing
>
> **No design deviation. Implement §8.3a exactly as approved.**
>
> An earlier draft of this plan proposed an addendum: if the replay itself fails, un-pause as a last
> resort. **That is unsafe and is not in this plan.** A replay call that raises may still have
> *landed* — the same lost-acknowledgement reasoning that motivates §8.3a in the first place. So a
> following `media_play` would resume either the source (harmless) or **the announcement clip**
> (plays the announcement again as though it were the music). Recovering an ambiguous queue with a
> blind `media_play` cannot be justified without first confirming the zone's state, and no
> state-confirmed recovery rule is in the approved design.
>
> **What this means for the existing test.** `tests/test_interaction.py:1703`
> (`ReplyBumpTest.test_if_the_clip_never_goes_out_the_music_is_un_paused`) makes **every**
> `play_media` raise. Under §8.3a the clip fails, the replay is attempted and also fails, and the
> un-pause is correctly gated off — so its current assertion (`media_play` in `ha.calls`) becomes
> **false by design**. Step 2 rewrites that test to assert the approved behaviour instead. This is
> an intended failure-path change to a shared `_say` code path, listed as such in Task 21's PR body.
>
> **§8.3a's own no-`source_id` fallback stays exactly as approved.** When the flag is set but there
> is nothing to replay (`was_playing` true, `media_content_id` empty or unreadable) and
> `paused_by_us`, the un-pause still fires — that is in the design and the condition below
> implements it. Worth recording for a future design pass: that path carries a milder form of the
> same ambiguity, since un-pausing an already-replaced queue could resume the clip. It is rare
> (music playing but no readable content id) and it is **not** changed here — implementing the
> approved design is the instruction, and widening the fix would be a second deviation.
>
> **The residual, accepted:** when a clip play *and* the replay both fail, the zone is left
> **paused** at its restored baseline volume, and the result is an honest `err` with an `error` log.
> It is recoverable without touching the resolver — the operator says *"resume"*, which routes to
> `interaction` mode `resume`, and `_resume` un-pauses a paused zone (or replays the last real
> source). Task 27 documents that recovery. Do **not** add a blind un-pause to shorten it.

**Files:**
- Modify: `docs/homebrain/mass-resolver/interaction.py` — `_say` locals, the clip loop, the `finally`
- Modify: `docs/homebrain/mass-resolver/tests/test_interaction.py:1703` (the existing un-pause test)
- Test: same file, new class

**Interfaces:**
- Consumes: `_say`'s `paused_by_us`, `was_playing`, `source_id`, `superseded` locals.
- Produces: `queue_may_be_replaced` semantics; no new public signature.

- [ ] **Step 1: Write the failing tests.**

```python
class AmbiguousPlayRecoveryTest(unittest.TestCase):
    """AN-01 Task 17: design 8.3a.

    A multi-clip turn creates a failure a single-clip turn cannot: the chime replaces the queue and
    the message dies. Today's finalizer restores volume and un-pauses, and neither helps -- the
    replay lives only in step 9 (skipped by an exception) and the un-pause is gated on
    `not play_issued`, which the chime's success falsifies. And even the un-pause would be useless:
    the queue holds a spent chime, not the music.

    The flag is claimed BEFORE each play, so any raising play leaves it set: "no play was ever
    issued" means the turn died before REACHING a play_media at all."""

    def setUp(self):
        FakeTimer.created = []
        self.zone = "media_player.ceiling_speakers"
        self.chime = "http://192.168.122.10:8123/media/local/chime.wav?authSig=REDACTED"
        self.tts = "http://192.168.122.10:8123/api/tts_proxy/x.mp3"

    def _cap(self):
        return interaction.InteractionCapability(timer_factory=FakeTimer, clock=lambda: 1000.0,
                                                 sleeper=FakeSleeper())

    def _two_clip(self, cap, ha, rid):
        return capability.run(cap, FakeCtx(ha), {
            "mode": "say", "uri": self.tts,
            "uris": [self.chime, self.tts],
            "match_keys": [self.chime.split("?")[0], self.tts],
            "finish_timeouts": [15.0, 45.0],
            "volume_override": 0.80,
            "skip_on_fresh_playback": False}, rid)

    def test_chime_played_then_message_raises_replays_the_source(self):
        cap = self._cap()
        ha = FakeHA(playing(0.36))
        ha.set_states([playing_with_id(0.36, "library://radio/2"),
                       playing_with_id(0.80, "builtin://radio/" + self.chime),
                       idle_state(), idle_state()])
        real = ha.call_service_rest
        n = {"plays": 0}

        def second_play_boom(domain, service, data, timeout=5):
            if service == "play_media":
                n["plays"] += 1
                if n["plays"] == 2:                       # the MESSAGE
                    raise IOError("MA refused")
            real(domain, service, data, timeout)
        ha.call_service_rest = second_play_boom
        r = self._two_clip(cap, ha, "rid-amb")
        self.assertFalse(r["ok"])
        replays = [c[2]["media_id"] for c in ha.calls if c[1] == "play_media"]
        self.assertIn("library://radio/2", replays)          # the station is back
        self.assertNotIn("media_play", [s for _, s, _ in ha.calls])   # no useless un-pause

    def test_no_replay_when_the_turn_dies_before_any_play(self):
        # The step-4 volume_set raises, so no play_media was ever attempted and the flag is clear.
        # This CANNOT be written as "the first play_media raises": the flag is claimed before that
        # call, so a raising first play is an AMBIGUOUS failure and must replay.
        cap = self._cap()
        ha = FakeHA(playing(0.36))
        ha.set_states([playing_with_id(0.36, "library://radio/2")])
        real = ha.call_service_rest

        def volume_boom(domain, service, data, timeout=5):
            if service == "volume_set":
                raise IOError("refused")
            real(domain, service, data, timeout)
        ha.call_service_rest = volume_boom
        r = capability.run(cap, FakeCtx(ha), {"mode": "say", "uri": self.tts}, "rid-pre")
        self.assertFalse(r["ok"])
        self.assertEqual([c[2].get("media_id") for c in ha.calls if c[1] == "play_media"], [])
        self.assertIn("media_play", [s for _, s, _ in ha.calls])      # un-pause, queue intact

    def test_a_raising_first_play_replays_rather_than_unpausing(self):
        cap = self._cap()
        ha = FakeHA(playing(0.36))
        ha.set_states([playing_with_id(0.36, "library://radio/2")])
        real = ha.call_service_rest
        n = {"plays": 0}

        def first_play_boom(domain, service, data, timeout=5):
            if service == "play_media":
                n["plays"] += 1
                if n["plays"] == 1:
                    raise IOError("MA refused")
            real(domain, service, data, timeout)
        ha.call_service_rest = first_play_boom
        r = capability.run(cap, FakeCtx(ha), {"mode": "say", "uri": self.tts}, "rid-first")
        self.assertFalse(r["ok"])
        self.assertIn("library://radio/2",
                      [c[2].get("media_id") for c in ha.calls if c[1] == "play_media"])

    def test_lost_ack_on_the_chime_play_still_replays_the_source(self):
        cap = self._cap()
        ha = FakeHA(playing(0.36))
        ha.set_states([playing_with_id(0.36, "library://radio/2")])
        real = ha.call_service_rest
        n = {"plays": 0}

        def lossy(domain, service, data, timeout=5):
            if service == "play_media":
                n["plays"] += 1
                if n["plays"] == 1:
                    real(domain, service, data, timeout)     # the request LANDS
                    raise IOError("reset after the write")
            real(domain, service, data, timeout)
        ha.call_service_rest = lossy
        r = self._two_clip(cap, ha, "rid-lack")
        self.assertFalse(r["ok"])
        self.assertIn("library://radio/2",
                      [c[2].get("media_id") for c in ha.calls if c[1] == "play_media"])
        self.assertNotIn("media_play", [s for _, s, _ in ha.calls])

    def test_lost_ack_on_the_message_play_when_it_is_the_only_clip(self):
        # The chime is disabled, so the message is the first and only play: the flag must already
        # be set when it raises.
        cap = self._cap()
        ha = FakeHA(playing(0.36))
        ha.set_states([playing_with_id(0.36, "library://radio/2")])
        real = ha.call_service_rest

        def lossy(domain, service, data, timeout=5):
            if service == "play_media":
                real(domain, service, data, timeout)
                raise IOError("reset after the write")
            real(domain, service, data, timeout)
        ha.call_service_rest = lossy
        r = capability.run(cap, FakeCtx(ha), {"mode": "say", "uri": self.tts}, "rid-monly")
        self.assertFalse(r["ok"])
        self.assertIn("library://radio/2",
                      [c[2].get("media_id") for c in ha.calls if c[1] == "play_media"])

    def test_the_flag_is_set_before_the_call_not_after(self):
        # White-box: a success-gated flag passes every other test here and fails this one.
        cap = self._cap()
        ha = FakeHA(playing(0.36))
        ha.set_states([playing_with_id(0.36, "library://radio/2")])
        seen = {"flag_at_call": None}
        real = ha.call_service_rest

        def probe(domain, service, data, timeout=5):
            if service == "play_media" and seen["flag_at_call"] is None:
                seen["flag_at_call"] = True                # reached only if claimed beforehand
                raise IOError("stop here")
            real(domain, service, data, timeout)
        ha.call_service_rest = probe
        capability.run(cap, FakeCtx(ha), {"mode": "say", "uri": self.tts}, "rid-probe")
        self.assertIn("library://radio/2",
                      [c[2].get("media_id") for c in ha.calls if c[1] == "play_media"])

    def test_no_replay_when_superseded(self):
        # A newer turn owns the zone and is about to play its own thing; replaying into it is the
        # CHANGELOG 2026-09-06 clobber defect from the other direction.
        cap = self._cap()
        ha = FakeHA(playing(0.36))
        ha.set_states([playing_with_id(0.36, "library://radio/2")])
        real = ha.call_service_rest

        def boom_then_supersede(domain, service, data, timeout=5):
            if service == "play_media":
                cap._say_gen[self.zone] = cap._say_gen.get(self.zone, 0) + 5
                raise IOError("MA refused")
            real(domain, service, data, timeout)
        ha.call_service_rest = boom_then_supersede
        capability.run(cap, FakeCtx(ha), {"mode": "say", "uri": self.tts}, "rid-sup")
        self.assertEqual([c[2].get("media_id") for c in ha.calls if c[1] == "play_media"], [])
        self.assertNotIn("media_play", [s for _, s, _ in ha.calls])

    def test_exactly_one_replay_on_the_success_path(self):
        cap = self._cap()
        ha = FakeHA(playing(0.36))
        ha.set_states([playing_with_id(0.36, "library://radio/2"),
                       playing_with_id(0.40, "builtin://radio/" + self.tts),
                       idle_state(), idle_state(), playing(0.40)])
        capability.run(cap, FakeCtx(ha), {"mode": "say", "uri": self.tts}, "rid-one")
        self.assertEqual(
            len([c for c in ha.calls
                 if c[1] == "play_media" and c[2]["media_id"] == "library://radio/2"]), 1)

    def test_unpause_fallback_when_there_is_nothing_to_replay(self):
        # design 8.3a's own fallback: the flag is set, but the capture read gave no
        # media_content_id, so there is no source to replay. Without the un-pause the zone would be
        # left paused and silent. was_playing is true (volume present) while source_id is empty.
        cap = self._cap()
        ha = FakeHA(playing(0.36))
        ha.set_states([playing(0.36)])          # playing, but NO media_content_id
        real = ha.call_service_rest

        def play_boom(domain, service, data, timeout=5):
            if service == "play_media":
                raise IOError("MA refused")
            real(domain, service, data, timeout)
        ha.call_service_rest = play_boom
        r = capability.run(cap, FakeCtx(ha), {"mode": "say", "uri": self.tts}, "rid-nosrc")
        self.assertFalse(r["ok"])
        self.assertEqual([c[2].get("media_id") for c in ha.calls if c[1] == "play_media"], [])
        self.assertIn("media_play", [s for _, s, _ in ha.calls])

    def test_a_doubly_failed_recovery_leaves_the_zone_paused_rather_than_guessing(self):
        # design 8.3a as approved: a replay that RAISED may still have landed, so a following
        # media_play could resume the announcement clip instead of the music. The zone is left
        # paused at its restored baseline; the operator recovers with "resume".
        cap = self._cap()
        ha = FakeHA(playing(0.36))
        ha.set_states([playing_with_id(0.36, "library://radio/2")])
        real = ha.call_service_rest

        def all_plays_boom(domain, service, data, timeout=5):
            if service == "play_media":
                raise IOError("MA refused")
            real(domain, service, data, timeout)
        ha.call_service_rest = all_plays_boom
        r = capability.run(cap, FakeCtx(ha), {"mode": "say", "uri": self.tts}, "rid-both")
        self.assertFalse(r["ok"])
        self.assertNotIn("media_play", [s for _, s, _ in ha.calls])   # no blind un-pause
        # The replay WAS attempted, and the volume still came back to the baseline.
        self.assertIn("library://radio/2",
                      [c[2].get("media_id") for c in ha.calls if c[1] == "play_media"])
        self.assertEqual([c[2]["volume_level"] for c in ha.calls if c[1] == "volume_set"][-1], 0.36)
```

- [ ] **Step 2: Rewrite the existing un-pause test to the approved behaviour.**
  `tests/test_interaction.py:1703`, `ReplyBumpTest.test_if_the_clip_never_goes_out_the_music_is_un_paused`
  — its `boom` raises on **all** `play_media`, so under §8.3a the replay is attempted, fails, and the
  un-pause is correctly gated off. Its current assertion becomes false by design. **Replace the whole
  method** (name included) with:

```python
    def test_if_the_clip_never_goes_out_the_source_is_replayed_not_un_paused(self):
        # Was: test_if_the_clip_never_goes_out_the_music_is_un_paused, which asserted media_play.
        # AN-01 design 8.3a: a play_media that raised may still have LANDED, so the queue is
        # ambiguous and un-pausing could restart the reply clip instead of the music. The captured
        # source is replayed instead. This fake refuses that replay too, so nothing resumes -- the
        # zone is left paused at its baseline and the operator recovers with "resume".
        cap = self._cap()
        ha = FakeHA(playing(0.15)); ctx = FakeCtx(ha)
        real = ha.call_service_rest

        def boom(domain, service, data, timeout=None):
            if service == "play_media":
                raise IOError("MA refused")
            real(domain, service, data)
        ha.call_service_rest = boom
        ha.set_states([playing_with_id(0.15, "library://radio/2")])
        r = run(cap, ctx, {"mode": "say", "uri": self.norm_uri})
        self.assertFalse(r["ok"])
        self.assertNotIn("media_play", [c[1] for c in ha.calls])   # no blind un-pause
        # The replay WAS attempted with the captured source, even though the fake refused it.
        self.assertIn("library://radio/2",
                      [c[2].get("media_id") for c in ha.calls if c[1] == "play_media"])
```

This is the **only** existing test whose expectation AN-01 changes. Record it in Task 21's PR body.

- [ ] **Step 3: Run to verify failure.**

Run: `python tests/test_interaction.py AmbiguousPlayRecoveryTest -v`
Expected: FAIL — `test_chime_played_then_message_raises_replays_the_source` finds no
`library://radio/2` replay (the finalizer has no replay at all), and
`test_a_raising_first_play_replays_rather_than_unpausing` likewise.

- [ ] **Step 4: Implement.** Add the local beside the others (`interaction.py:~610`):

```python
        queue_may_be_replaced = [False]    # design 8.3a: claimed BEFORE each play_media. "We may
                                           #   have changed the queue" is the only thing a caller
                                           #   can honestly know -- a landed-but-unacknowledged play
                                           #   changes it while any success-gated flag stays False.
        replay_done = [False]
```

In the Task 12 clip loop, set it immediately before the helper call:

```python
                queue_may_be_replaced[0] = True
                res = self._play_clip_and_wait(ctx, rid, zone, norm_uri, norm_key, one_clip,
                                               opts, superseded)
```

In step 9, mark the replay done:

```python
            replayed = False
            if was_playing and source_id and not superseded():
                try:
                    queue_may_be_replaced[0] = True
                    self._say_call(ctx, rid, zone, "music_assistant", "play_media",
                                   {"entity_id": zone, "media_id": source_id}, timeout=call_timeout)
                    replayed = True
                    replay_done[0] = True
                except Exception as e:
                    LOG.warning("SAY req=%s zone=%s replay failed (%r); source NOT resumed",
                                rid, zone, e)
```

Replace the `finally`'s un-pause block:

```python
            # design 8.3a: an earlier clip may have replaced the queue, so un-pausing could restart
            # a spent chime instead of the music. On an AMBIGUOUS failure, replaying the captured
            # source is the safer recovery: if the play landed, replay is the only fix; if it did
            # not, replay re-plays the station that was already there.
            replayed_here = False
            if (queue_may_be_replaced[0] and not replay_done[0] and was_playing
                    and source_id and not superseded()):
                try:
                    ctx.ha.call_service_rest(
                        "music_assistant", "play_media",
                        {"entity_id": zone, "media_id": source_id},
                        timeout=int(getattr(ctx.settings, "say_call_timeout_ms", 20000)) / 1000.0)
                    replayed_here = True
                    LOG.warning("SAY req=%s zone=%s aborted after a play; replayed the source",
                                rid, zone)
                except Exception as e:
                    LOG.error("SAY req=%s zone=%s abort-replay failed (%r)", rid, zone, e)
            # design 8.3a: un-pause ONLY when the queue is certainly intact -- i.e. no play_media was
            # ever attempted, or there was no source to replay. A replay that RAISED may still have
            # landed, so un-pausing after one would resume either the source or the announcement
            # clip. That ambiguity is why there is no blind last-resort un-pause here: when a play
            # and its replay both fail, the zone is left paused at its baseline and the operator
            # recovers with "resume" (interaction mode resume un-pauses a paused zone).
            if (paused_by_us[0] and not superseded()
                    and not replay_done[0] and not replayed_here
                    and (not queue_may_be_replaced[0] or not source_id)):
                try:
                    ctx.ha.call_service_rest("media_player", "media_play", {"entity_id": zone})
                    LOG.warning("SAY req=%s zone=%s un-paused the source (queue intact, or nothing "
                                "to replay)", rid, zone)
                except Exception as e:
                    LOG.error("SAY req=%s zone=%s un-pause failed (%r)", rid, zone, e)
```

`play_issued[0]` is now unused for gating; keep it only if a log line reads it, otherwise delete it
and its assignments in the same step.

- [ ] **Step 5: Run to verify pass.**

Run: `python tests/test_interaction.py AmbiguousPlayRecoveryTest -v` → PASS, 10 tests.
Run: `python tests/test_interaction.py ReplyBumpTest GoldenSequenceTest -v` → PASS.
Run: `python -m unittest discover -s tests -t .` → `Ran 471 tests ... OK`.

- [ ] **Step 6: Commit.**

```bash
git add interaction.py tests/test_interaction.py
git commit -m "fix(resolver): replay the captured source when a clip play may have replaced the queue"
```

---

### Task 18: §8.4(a) — `marker_budget_s` on the reply marker

**Files:**
- Modify: `docs/homebrain/mass-resolver/interaction.py:168-189` (`_reply_active`), `:578` (the marker)
- Test: `docs/homebrain/mass-resolver/tests/test_interaction.py`

**Interfaces:**
- Consumes: the `_replies[zone]` marker.
- Produces: `_replies[zone]["marker_budget_s"]` (float, optional) and `_reply_active` honouring it.

- [ ] **Step 1: Write the failing tests.**

```python
class MarkerBudgetTest(unittest.TestCase):
    """AN-01 Task 18: design 8.4(a). The orphan threshold is
    (say_start + say_reply)/1000 + 60 = ~245s. A turn owning the zone for two clips can legitimately
    hold it longer, so it would declare its OWN marker stale and be reclaimed mid-flight.

    The marker carries its own budget -- the step-2-to-finally span, NOT just the poll budgets. A
    clip-count multiplier was the first draft and is worse: with per-clip timeouts the clips are
    different sizes, so clips x (start + reply) over-counts an announcement by roughly 3x."""

    def setUp(self):
        self.zone = "media_player.ceiling_speakers"

    def _cap(self, now):
        return interaction.InteractionCapability(timer_factory=FakeTimer, clock=lambda: now[0],
                                                 sleeper=FakeSleeper())

    def test_a_marker_with_a_budget_is_not_stale_before_it_elapses(self):
        now = [1000.0]
        cap = self._cap(now)
        cap._replies[self.zone] = {"gen": 1, "baseline": 0.36, "ts": 1000.0, "rid": "r",
                                   "marker_budget_s": 145.0}
        now[0] = 1000.0 + 145.0 + 30.0            # inside 145 + 60
        self.assertIsNotNone(cap._reply_active(FakeCtx(FakeHA()), self.zone))

    def test_a_marker_with_a_budget_is_stale_after_it_elapses(self):
        now = [1000.0]
        cap = self._cap(now)
        cap._replies[self.zone] = {"gen": 1, "baseline": 0.36, "ts": 1000.0, "rid": "r",
                                   "marker_budget_s": 145.0}
        now[0] = 1000.0 + 145.0 + 61.0
        self.assertIsNone(cap._reply_active(FakeCtx(FakeHA()), self.zone))

    def test_a_marker_without_a_budget_keeps_todays_threshold(self):
        now = [1000.0]
        cap = self._cap(now)
        cap._replies[self.zone] = {"gen": 1, "baseline": 0.36, "ts": 1000.0, "rid": "r"}
        now[0] = 1000.0 + 240.0                   # inside (5 + 30) + 60 for FakeSettings
        # FakeSettings has say_reply_timeout_ms = 30000, so the legacy budget is 95s.
        self.assertIsNone(cap._reply_active(FakeCtx(FakeHA()), self.zone))
        now[0] = 1000.0 + 50.0
        cap._replies[self.zone]["ts"] = now[0]
        self.assertIsNotNone(cap._reply_active(FakeCtx(FakeHA()), self.zone))

    def test_say_publishes_a_budget_for_a_multi_clip_turn(self):
        # The marker is deleted by release_reply, so capture it WHILE in flight: the clip helper
        # runs after step 2 has published it.
        now = [1000.0]
        cap = self._cap(now)
        tts = "http://192.168.122.10:8123/api/tts_proxy/x.mp3"
        ha = FakeHA(playing(0.36))
        ha.set_states([playing_with_id(0.36, "library://radio/2")])
        seen = {}
        real_play = cap._play_clip_and_wait

        def spy(ctx, rid, zone, norm_uri, match_key, clip, opts, superseded):
            seen.setdefault("marker", dict(cap._replies.get(zone) or {}))
            return real_play(ctx, rid, zone, norm_uri, match_key, clip, opts, superseded)
        cap._play_clip_and_wait = spy
        capability.run(cap, FakeCtx(ha), {"mode": "say", "uri": tts,
                                          "uris": [tts, tts],
                                          "match_keys": [tts, tts],
                                          "finish_timeouts": [15.0, 45.0]}, "rid-mb")
        self.assertIsNotNone(seen["marker"].get("marker_budget_s"))
        # 5 + 5 + sum(finish + start + call) + 5 + call, with FakeSettings' 5s start / 20s call.
        self.assertAlmostEqual(seen["marker"]["marker_budget_s"], 145.0, delta=1.0)

    def test_say_text_publishes_no_budget(self):
        now = [1000.0]
        cap = self._cap(now)
        tts = "http://192.168.122.10:8123/api/tts_proxy/x.mp3"
        ha = FakeHA(playing(0.36)); ha.tts_url = tts
        ha.set_states([playing_with_id(0.36, "library://radio/2")])
        seen = {}
        real_play = cap._play_clip_and_wait

        def spy(ctx, rid, zone, norm_uri, match_key, clip, opts, superseded):
            seen.setdefault("marker", dict(cap._replies.get(zone) or {}))
            return real_play(ctx, rid, zone, norm_uri, match_key, clip, opts, superseded)
        cap._play_clip_and_wait = spy
        capability.run(cap, FakeCtx(ha), {"mode": "say_text", "text": "hello"}, "rid-st")
        self.assertIsNone(seen["marker"].get("marker_budget_s"))
```

- [ ] **Step 2: Run to verify failure.**

Run: `python tests/test_interaction.py MarkerBudgetTest -v`
Expected: FAIL — `test_a_marker_with_a_budget_is_not_stale_before_it_elapses` returns `None`, because
`_reply_active` ignores `marker_budget_s` and uses the 95 s legacy budget from `FakeSettings`.

- [ ] **Step 3: Implement.** In `_reply_active`, replace the budget computation:

```python
        # The marker's legitimate lifetime is step 2 -> finally: the pause and volume writes, both
        # play_media calls at their call timeout, all poll budgets, the restore write and the
        # replay. A turn that knows its own span publishes it; older callers keep today's formula.
        budget = reply.get("marker_budget_s")
        if budget is None:
            budget = (int(getattr(ctx.settings, "say_start_timeout_ms", 5000)) +
                      int(getattr(ctx.settings, "say_reply_timeout_ms", 30000))) / 1000.0
```

In `_say`'s step-2 marker publication, add the span when the caller supplied per-clip timeouts:

```python
            marker_budget = None
            if resolved.get("finish_timeouts"):
                call = int(getattr(ctx.settings, "say_call_timeout_ms", 20000)) / 1000.0
                start = int(getattr(ctx.settings, "say_start_timeout_ms", 5000)) / 1000.0
                per_clip = sum(float(t) + start + call
                               for t in resolved["finish_timeouts"])
                marker_budget = 5.0 + 5.0 + per_clip + 5.0 + call     # pause, raise, clips, restore, replay
            self._replies[zone] = {"gen": my_gen, "baseline": baseline,
                                   "ts": self._clock(), "rid": rid,
                                   "marker_budget_s": marker_budget}
```

`marker_budget_s` is `None` for `say`/`say_text`, so `_reply_active` falls back to today's formula and
their behaviour is unchanged.

**With the shipped defaults an announcement's `marker_budget_s` is ≈145 s** — comfortably inside the
~245 s fallback. This is defence for the config, not for today's numbers: it matters because
`announce_message_finish_timeout_ms` is a tunable, and raising it would otherwise silently
reintroduce the defect.

- [ ] **Step 4: Run to verify pass.**

Run: `python tests/test_interaction.py MarkerBudgetTest -v` → PASS.
Run: `python tests/test_interaction.py DuckOwnershipSlice4Test -v` → PASS (the stale-marker reclaim
tests still work: they publish markers without a budget).
Run: `python -m unittest discover -s tests -t .` → `Ran 476 tests ... OK`.

- [ ] **Step 5: Commit.**

```bash
git add interaction.py tests/test_interaction.py
git commit -m "fix(resolver): derive the reply marker staleness budget from the turn's own span"
```

---

### Task 19: §9.7 — the announcement-owned volume dead-man

§8.4(c) established that an unducked phone announcement has **no** volume dead-man: no duck request
means no `_snaps[zone]`, so `_arm_timer` never ran and `max_duck_timeout` never applies. The
finalizer gives one immediate retry; if that also fails, nothing is scheduled to correct a ceiling
stuck at 0.80.

**Files:**
- Modify: `docs/homebrain/mass-resolver/interaction.py` — `__init__`, `_say` (arm + cancel), plus a
  new `_volume_recovery` method
- Test: `docs/homebrain/mass-resolver/tests/test_interaction.py`

**Interfaces:**
- Consumes: `self._timer_factory`, `_say`'s `my_gen`, `baseline`, `my_snap_ts` locals.
- Produces: `self._vol_recovery = {}`; `_volume_recovery(self, ctx, zone, gen, attempt)`;
  `metadata["volume_restore"]` ∈ `{"restored", "deferred_to_deadman"}`.

- [ ] **Step 1: Write the failing tests.**

```python
class VolumeRecoveryTest(unittest.TestCase):
    """AN-01 Task 19: design 9.7. The duration is a POLICY CUTOFF derived from an engineered
    budget, not a wall-clock bound: a pathologically slow-but-live turn could cross it. Two guards
    make an early fire cheap -- it does nothing if a newer turn owns the zone, and it leaves a
    volume we did not write alone -- so the worst case is restoring the baseline under a clip that
    is still playing. Preferring that to an indefinitely stuck 0.80 is liveness over waiting."""

    def setUp(self):
        FakeTimer.created = []
        self.zone = "media_player.ceiling_speakers"
        self.tts = "http://192.168.122.10:8123/api/tts_proxy/x.mp3"

    def _cap(self):
        return interaction.InteractionCapability(timer_factory=FakeTimer, clock=lambda: 1000.0,
                                                 sleeper=FakeSleeper())

    def _states(self):
        return [playing_with_id(0.36, "library://radio/2"),
                playing_with_id(0.80, "builtin://radio/" + self.tts),
                idle_state(), idle_state(), playing(0.80)]

    def test_an_unducked_turn_arms_a_volume_recovery_timer(self):
        cap = self._cap(); ha = FakeHA(playing(0.36)); ha.set_states(self._states())
        capability.run(cap, FakeCtx(ha), {"mode": "say", "uri": self.tts,
                                          "volume_override": 0.80}, "rid-vr")
        self.assertTrue(any(t.interval > 100 for t in FakeTimer.created))

    def test_a_ducked_reply_arms_no_second_timer(self):
        cap = self._cap()
        cap._snaps[self.zone] = {"volume": 0.36, "target": 0.15, "ts": 900.0, "timer": None}
        FakeTimer.created = []
        ha = FakeHA(playing(0.15)); ha.set_states(self._states())
        capability.run(cap, FakeCtx(ha), {"mode": "say", "uri": self.tts}, "rid-duck")
        self.assertEqual(FakeTimer.created, [])

    def test_a_successful_restore_cancels_it(self):
        cap = self._cap(); ha = FakeHA(playing(0.36)); ha.set_states(self._states())
        capability.run(cap, FakeCtx(ha), {"mode": "say", "uri": self.tts,
                                          "volume_override": 0.80}, "rid-vr2")
        vr = [t for t in FakeTimer.created if t.interval > 100]
        self.assertTrue(vr and vr[0].cancelled)
        self.assertNotIn(self.zone, cap._vol_recovery)

    def test_firing_restores_the_baseline_when_still_at_announce_volume(self):
        cap = self._cap()
        cap._say_gen[self.zone] = 1
        cap._vol_recovery[self.zone] = {"gen": 1, "baseline": 0.36, "target": 0.80,
                                        "rid": "r", "ts": 1000.0, "timer": None}
        ha = FakeHA(playing(0.80))
        cap._volume_recovery(FakeCtx(ha), self.zone, 1, 0)
        self.assertEqual([c[2]["volume_level"] for c in ha.calls if c[1] == "volume_set"], [0.36])
        self.assertNotIn(self.zone, cap._vol_recovery)

    def test_firing_does_nothing_when_a_newer_turn_owns_the_zone(self):
        cap = self._cap()
        cap._say_gen[self.zone] = 7
        cap._vol_recovery[self.zone] = {"gen": 1, "baseline": 0.36, "target": 0.80,
                                        "rid": "r", "ts": 1000.0, "timer": None}
        ha = FakeHA(playing(0.80))
        cap._volume_recovery(FakeCtx(ha), self.zone, 1, 0)
        self.assertEqual(ha.calls, [])

    def test_firing_leaves_a_human_changed_volume_alone(self):
        cap = self._cap()
        cap._say_gen[self.zone] = 1
        cap._vol_recovery[self.zone] = {"gen": 1, "baseline": 0.36, "target": 0.80,
                                        "rid": "r", "ts": 1000.0, "timer": None}
        ha = FakeHA(playing(0.55))                 # not the 0.80 we wrote
        cap._volume_recovery(FakeCtx(ha), self.zone, 1, 0)
        self.assertEqual(ha.calls, [])
        self.assertNotIn(self.zone, cap._vol_recovery)

    def test_retries_are_bounded_then_it_stops(self):
        cap = self._cap()
        cap._say_gen[self.zone] = 1
        cap._vol_recovery[self.zone] = {"gen": 1, "baseline": 0.36, "target": 0.80,
                                        "rid": "r", "ts": 1000.0, "timer": None}
        ha = FakeHA(playing(0.80), write_boom=IOError("no route"))
        FakeTimer.created = []
        cap._volume_recovery(FakeCtx(ha), self.zone, 1, 0)
        self.assertEqual(len(FakeTimer.created), 1)         # re-armed
        cap._volume_recovery(FakeCtx(ha), self.zone, 1, 3)  # attempt == retries
        self.assertEqual(len(FakeTimer.created), 1)         # no further re-arm

    def test_returned_metadata_is_only_restored_or_deferred_to_deadman(self):
        # There is deliberately NO "failed" value: the result is serialised before the timer can
        # run, so a terminal failure cannot reach it (design 9.7).
        cap = self._cap(); ha = FakeHA(playing(0.36)); ha.set_states(self._states())
        r = capability.run(cap, FakeCtx(ha), {"mode": "say", "uri": self.tts,
                                             "volume_override": 0.80}, "rid-md")
        self.assertIn(r["metadata"]["volume_restore"], ("restored", "deferred_to_deadman"))
```

- [ ] **Step 2: Run to verify failure.**

Run: `python tests/test_interaction.py VolumeRecoveryTest -v`
Expected: FAIL — `AttributeError: ... no attribute '_vol_recovery'` and
`... no attribute '_volume_recovery'`.

- [ ] **Step 3: Add the state.** In `__init__`:

```python
        self._vol_recovery = {}                       # zone -> {"gen", "baseline", "target",
                                                      #          "rid", "ts", "timer"}
                                                      #   design 9.7: an unducked turn has no duck
                                                      #   snapshot, so max_duck_timeout is not its
                                                      #   net. Written only by _say.
```

- [ ] **Step 4: Implement `_volume_recovery`:**

```python
    def _volume_recovery(self, ctx, zone, gen, attempt):
        """Last-resort restore for an UNDUCKED turn whose step-8 and finalizer writes both failed.

        POLICY CUTOFF, not a wall-clock bound (design 9.7): a pathologically slow-but-live turn
        could cross it. Two guards make an early fire cheap -- a newer turn owning the zone is left
        alone, and a volume we did not write is left alone -- so the worst case is restoring the
        baseline under a clip that is still playing, which beats an indefinitely stuck 0.80.
        """
        with self._lock:
            rec = self._vol_recovery.get(zone)
            if rec is None or rec.get("gen") != gen:
                return
        if self._say_gen.get(zone) != gen:
            LOG.info("VOLUME-RECOVERY zone=%s gen=%s superseded; a newer turn owns the restore",
                     zone, gen)
            with self._lock:
                if self._vol_recovery.get(zone) is rec:
                    del self._vol_recovery[zone]
            return
        try:
            live = ((ctx.ha.get_entity_state(zone) or {}).get("attributes") or {}).get("volume_level")
        except Exception as e:
            LOG.warning("VOLUME-RECOVERY zone=%s read failed (%r)", zone, e)
            live = None
        target = rec.get("target")
        if live is not None and target is not None and abs(live - target) > 0.01:
            LOG.info("VOLUME-RECOVERY zone=%s volume is %s, not the %s we wrote; leaving it",
                     zone, live, target)
            with self._lock:
                if self._vol_recovery.get(zone) is rec:
                    del self._vol_recovery[zone]
            return
        try:
            ctx.ha.call_service_rest("media_player", "volume_set",
                                     {"entity_id": zone, "volume_level": rec["baseline"]})
            LOG.warning("VOLUME-RECOVERY zone=%s restored -> %s (attempt %d)",
                        zone, rec["baseline"], attempt + 1)
            with self._lock:
                if self._vol_recovery.get(zone) is rec:
                    del self._vol_recovery[zone]
            return
        except Exception as e:
            retries = int(getattr(ctx.settings, "announce_volume_deadman_retries", 3))
            if attempt + 1 >= retries:
                # Terminal exhaustion is LOG-ONLY: /command has already answered, so this cannot
                # reach the phone. The resolver log is the sole witness -- hence error, not warning.
                LOG.error("VOLUME-RECOVERY zone=%s GAVE UP after %d attempts (%r); the ceiling may "
                          "be left at %s", zone, attempt + 1, e, rec.get("target"))
                with self._lock:
                    if self._vol_recovery.get(zone) is rec:
                        del self._vol_recovery[zone]
                return
            LOG.warning("VOLUME-RECOVERY zone=%s attempt %d failed (%r); re-arming",
                        zone, attempt + 1, e)
            secs = self._volume_recovery_secs(ctx)
            t = self._timer_factory(secs, self._volume_recovery, [ctx, zone, gen, attempt + 1])
            rec["timer"] = t
            t.start()

    def _volume_recovery_secs(self, ctx):
        explicit = int(getattr(ctx.settings, "announce_volume_deadman_ms", 0))
        if explicit > 0:
            return explicit / 1000.0
        call = int(getattr(ctx.settings, "say_call_timeout_ms", 20000)) / 1000.0
        start = int(getattr(ctx.settings, "say_start_timeout_ms", 5000)) / 1000.0
        chime_fin = int(getattr(ctx.settings, "announce_chime_finish_timeout_ms", 15000)) / 1000.0
        msg_fin = int(getattr(ctx.settings, "announce_message_finish_timeout_ms", 45000)) / 1000.0
        # marker_budget_s (design 8.4a) + 30s of margin
        return (5.0 + 5.0 + call + start + chime_fin + call + start + msg_fin
                + 5.0 + call) + 30.0
```

- [ ] **Step 5: Arm and cancel it in `_say`.** Immediately after Task 16's
  `pending_restore[0] = True` block, and only when there is no duck snapshot:

```python
            if owns_restore and my_snap_ts is None and baseline is not None:
                # No duck snapshot -> _arm_timer never ran -> max_duck_timeout is not our net.
                secs = self._volume_recovery_secs(ctx)
                rec = {"gen": my_gen, "baseline": baseline, "target": reply_volume,
                       "rid": rid, "ts": self._clock(), "timer": None}
                with self._lock:
                    self._vol_recovery[zone] = rec
                t = self._timer_factory(secs, self._volume_recovery, [ctx, zone, my_gen, 0])
                rec["timer"] = t
                t.start()
```

Add a `_cancel_volume_recovery(zone, gen)` helper that cancels the timer and drops the entry, and call
it wherever the zone reaches its baseline: after step 8's successful `volume_set`, and after the
finalizer's abort-restore. Set `meta["volume_restore"] = "restored"` there and
`"deferred_to_deadman"` on the failure paths, then include it in the returned metadata.

- [ ] **Step 6: Run to verify pass.**

Run: `python tests/test_interaction.py VolumeRecoveryTest -v` → PASS, 8 tests.
Run: `python tests/test_interaction.py GoldenSequenceTest DuckOwnershipSlice4Test -v` → PASS.
Run: `python -m unittest discover -s tests -t .` → `Ran 484 tests ... OK`.

- [ ] **Step 7: Commit.**

```bash
git add interaction.py tests/test_interaction.py
git commit -m "fix(resolver): add a volume recovery timer for an unducked announcement turn"
```

---

### Task 20: Python 3.5 compatibility sweep and the full-suite gate

The dev machine runs 3.12.0, so the local run does **not** catch 3.6+ syntax. The host is the real
target.

**Files:** all files touched in Tasks 6–19.

**Interfaces:**
- Consumes: everything above.
- Produces: a branch that compiles and passes under 3.5, ready for G3.

- [ ] **Step 1: Grep for 3.6+ syntax.** From `docs/homebrain/mass-resolver/`:

```bash
grep -nE 'f"|f\x27|^\s*[a-z_]+\s*:\s*(int|str|float|bool|dict|list)\s*=' \
     interaction.py haconn.py config.py wsutil.py
grep -nE '[0-9]_[0-9]' interaction.py haconn.py config.py wsutil.py
grep -nE 'async |await |:=' interaction.py haconn.py config.py wsutil.py
```

Expected: **no output.** Any hit is a 3.5 incompatibility — rewrite with `%`-formatting or
`.format()`, and comment-style type hints.

- [ ] **Step 2: Byte-compile with the local interpreter as a syntax smoke test.**

```bash
python -m py_compile interaction.py haconn.py config.py wsutil.py && echo "COMPILE OK"
```

Expected: `COMPILE OK`. This proves nothing about 3.5 — G3 step 3 is the real parity check — but it
catches typos before the host.

- [ ] **Step 3: Check for non-ASCII in anything that reaches a log or a console.**

```bash
grep -nP '[^\x00-\x7F]' interaction.py haconn.py config.py config.json | head -20
```

Expected: no output. `ONBOARDING.md` §3 records `UnicodeEncodeError` on non-ASCII Windows console
output; the design's `chat_text` strings deliberately use a plain hyphen.

- [ ] **Step 4: Confirm no secret ever reaches a log or a fixture.**

```bash
grep -rn "authSig" . --include=*.py | grep -v REDACTED
grep -rniE "bearer [a-z0-9]{8,}|X-Resolver-Key: [a-z0-9]" . --include=*.py --include=*.json
```

Expected: **no output.** Test fixtures must use `authSig=REDACTED`; the only permitted mention of a
credential in code is a comment saying not to log it.

- [ ] **Step 5: Run the whole suite and record the count.**

Run: `python -m unittest discover -s tests -t .`
Expected: `Ran 484 tests ... OK` (376 baseline + 108 new). Record the exact number for the
`CHANGELOG.md` entry at G3.

- [ ] **Step 6: Commit anything the sweep changed.**

```bash
git add -A
git commit -m "chore(resolver): python 3.5 compatibility sweep for the announce mode work"
```

---

### Task 21: Open the PR

**Files:** none.

- [ ] **Step 1: Check the PR base, then push.** The branch is based on `259c730`, which may not yet
  be on `origin/main` (see the G2 preamble).

```bash
git fetch origin
if git merge-base --is-ancestor 259c730 origin/main; then
  echo "PR will contain ONLY the AN-01 code commits"
else
  echo "WARNING: origin/main lacks 259c730 -- the PR will also carry the design commit."
  echo "Either push main first, or note the extra commit in the PR body."
fi
git push -u origin homebrain/an-01-announce
```

- [ ] **Step 2: Open the PR against `main`.** `reference_gh_account_mismatch` applies in this repo:
  `git push` works over the SSH work key but `gh pr create` authenticates as the personal account and
  fails. **Open the PR via the browser URL** that `git push` prints, and title it
  `AN-01: interaction mode announce (phone Assist -> ceiling)`.

- [ ] **Step 3: PR body — the review checklist.** State plainly:
  - Design commit `259c730`, gates G1/G1b complete (link the Checkpoint A `CHANGELOG.md` entry).
  - `say`/`say_text` public contract and **success-path** call sequences unchanged, proven by
    `GoldenSequenceTest`; the **one** intended failure-path change is Task 17's ambiguous-play
    replay (§8.3a), which renames and rewrites `ReplyBumpTest`'s un-pause test — the only existing
    expectation AN-01 alters.
  - The branch is based on `259c730`; if `origin/main` does not yet contain it, the PR carries that
    design commit too (Task 21 step 1 reports which).
  - Test count before/after: `376 -> 484`.
  - No live system touched. No secrets in the diff.
  - **Nothing is deployed by merging** — the `announce` mode is inert until G4b's sentence triggers
    exist.

- [ ] **Step 4: After merge, remove the code worktree.**

```bash
cd /d/repos/dotfiles
git worktree remove .claude/worktrees/an-01-code
git branch -d homebrain/an-01-announce
```

`reference_worktree_cleanup_windows` applies: if `git worktree remove` orphans the directory,
`rm -rf` it and clear any stale `index.lock`; use `git branch -d`, not `-D`.

---

# Phase G3 — Host deploy (🔴 OPERATOR-GATED)

> Follow [`../runbooks/resolver-deploy.md`](../runbooks/resolver-deploy.md). Staging (backup, copy,
> compile, test) is agent-safe over SSH; **the restart is a user-run `sudo` step** and needs explicit
> approval. Claim the live lane in `BACKLOG.md:306` first.
>
> **Preflight, from the runbook §0:** deploy only when no interaction is active
> (`assist_satellite` idle). A restart mid-duck loses the in-memory duck snapshot and dead-man and
> strands the ceiling at the floor — and AN-01 adds two more in-memory structures (`_mic`,
> `_vol_recovery`) with the same property.

### Task 22: Stage the deploy (agent-safe)

**Files (deployed):** `interaction.py`, `haconn.py`, `wsutil.py`, `config.py`, `config.json`, and
`tests/test_interaction.py`, `tests/test_haconn.py`, `tests/test_config.py`, `tests/test_wsutil.py`
for the on-host parity run.

- [ ] **Step 1: Connect** per `runbooks/resolver-deploy.md` §Connect.

```bash
eval "$(ssh-agent -s)"; ssh-add ~/.ssh/id_homebrain
SSH='ssh -o ConnectTimeout=15 -o ServerAliveInterval=8 -o ServerAliveCountMax=3 costea@192.168.1.68'
OPTS='-o ConnectTimeout=15 -o ServerAliveInterval=8 -o ServerAliveCountMax=3'
```

- [ ] **Step 2: Health check** (runbook §2 / `quick-connect-and-health-check.md`): resolver `active`,
  VM `running`, `/command` bound, `200`/`401`. Abort if anything is off — deploying onto a broken
  stack makes the next failure ambiguous.

- [ ] **Step 3: Back up the five existing files.** `wsutil.py` is included because Task 6 changes it.

```bash
timeout 45 $SSH 'ts=$(date +%Y%m%d-%H%M%S); cd ~/mass-resolver && mkdir -p .bak/$ts && \
  cp interaction.py haconn.py wsutil.py config.py config.json .bak/$ts/ && \
  echo "BACKUP_TS=$ts" && ls .bak/$ts'
```

Record `BACKUP_TS` — it is the rollback pointer. Put it in the `CHANGELOG.md` entry.

- [ ] **Step 4: Copy.** `scp` treats `D:` as a hostname, so use the POSIX path.

```bash
LOCAL=/d/repos/dotfiles/docs/homebrain/mass-resolver
timeout 90 scp $OPTS "$LOCAL/interaction.py" "$LOCAL/haconn.py" "$LOCAL/wsutil.py" \
  "$LOCAL/config.py" "$LOCAL/config.json" costea@192.168.1.68:~/mass-resolver/
timeout 90 scp $OPTS "$LOCAL/tests/test_interaction.py" "$LOCAL/tests/test_haconn.py" \
  "$LOCAL/tests/test_config.py" "$LOCAL/tests/test_wsutil.py" \
  costea@192.168.1.68:~/mass-resolver/tests/
```

- [ ] **Step 5: Verify the content landed.** Do not trust `scp`'s exit code alone — the runbook warns
  the PQ-warning banner can mask output. `grep` for a distinctive marker per file:

```bash
timeout 45 $SSH 'cd ~/mass-resolver && \
  grep -c "_mic_claim" interaction.py && \
  grep -c "resolve_media_source" haconn.py && \
  grep -c "def ws_connect(host, port, path, timeout=15)" wsutil.py && \
  grep -c "announce_volume" config.py && \
  grep -c "announce_mic_mute_entity" config.json'
```

Expected: non-zero counts for all five.

- [ ] **Step 6: Compile and test on host Python 3.5.2 — the real parity check.**

```bash
timeout 120 $SSH 'cd ~/mass-resolver && python3 --version && \
  python3 -m py_compile interaction.py haconn.py wsutil.py config.py && echo "COMPILE OK" && \
  python3 tests/test_interaction.py 2>&1 | tail -3 && \
  python3 tests/test_haconn.py 2>&1 | tail -3 && \
  python3 tests/test_config.py 2>&1 | tail -3 && \
  python3 tests/test_wsutil.py 2>&1 | tail -3'
```

Expected: `Python 3.5.2`, `COMPILE OK`, and `OK` from each of the four files. A `SyntaxError` here is
a 3.6+ construct Task 20's grep missed — fix it in the repo, re-run Task 20, and re-copy. **Do not
patch on the host.**

- [ ] **Step 7: Confirm the config is still valid JSON on-host.**

```bash
timeout 45 $SSH 'cd ~/mass-resolver && python3 -c "
import json
d = json.load(open(\"config.json\"))
print(\"JSON OK\", d[\"announce_volume\"], d[\"reply_volume\"])
assert d[\"announce_volume\"] > d[\"reply_volume\"]
assert d[\"announce_mic_mute_entity\"], \"D1 entity id is empty\"
print(\"CONFIG SANE\")"'
```

Expected: `JSON OK 0.8 0.7` then `CONFIG SANE`.

---

### Task 23: Restart — 🔴 USER-RUN

- [ ] **Step 1: Hand this to the operator.** Agent SSH cannot do it: there is no passwordless sudo and
  the prompt hangs a non-interactive shell.

```bash
ssh -t costea@192.168.1.68 'sudo systemctl restart mass-resolver'
```

- [ ] **Step 2: Wait for the operator's confirmation** before Task 24.

---

### Task 24: Validate the deploy (read-only, then one audible test)

- [ ] **Step 1: Service and bind check.**

```bash
timeout 45 $SSH 'systemctl is-active mass-resolver && \
  tail -40 ~/mass-resolver/resolver.log | grep -E "SERVICE: /command|connected; subscribed" && \
  ! grep -c "Traceback" <(tail -200 ~/mass-resolver/resolver.log)'
```

Expected: `active`, a fresh `SERVICE: /command HTTP server on 192.168.122.1:8770`, and no traceback.
If the bind is missing, this is the known cold-boot bind race (`ONBOARDING.md` §7) — restart again.

- [ ] **Step 2: `/command` auth check** — 200 with the key, 401 without. Read the secret from the
  on-host file into a shell variable and **never echo it**:

```bash
timeout 45 $SSH 'cd ~/mass-resolver && K=$(cat .http_secret) && \
  curl -s -o /dev/null -w "with-key:%{http_code}\n" -H "X-Resolver-Key: $K" \
    -H "Content-Type: application/json" \
    -d "{\"intent\":\"status\",\"params\":{}}" http://192.168.122.1:8770/command && \
  curl -s -o /dev/null -w "no-key:%{http_code}\n" \
    -H "Content-Type: application/json" \
    -d "{\"intent\":\"status\",\"params\":{}}" http://192.168.122.1:8770/command'
```

Expected: `with-key:200`, `no-key:401`.

- [ ] **Step 3: No-regression smoke of the untouched capabilities.** Exercise `radio`, `music`,
  `news` and `media_status` over `/command` and confirm each returns `ok`. `say_text` matters most —
  it shares all of `_say`:

```bash
timeout 90 $SSH 'cd ~/mass-resolver && K=$(cat .http_secret) && \
  curl -s -H "X-Resolver-Key: $K" -H "Content-Type: application/json" \
    -d "{\"intent\":\"interaction\",\"params\":{\"mode\":\"say_text\",\"text\":\"Deploy check.\"}}" \
    http://192.168.122.1:8770/command | python3 -c "
import json,sys
d = json.load(sys.stdin)
print(\"ok\", d[\"ok\"], \"said\", d[\"metadata\"].get(\"said\"),
      \"likely_silent\", d[\"metadata\"].get(\"likely_silent\"))"'
```

Expected: `ok True said True likely_silent False`, and the operator **hears** "Deploy check." on the
ceiling. A `likely_silent True` means the shared `_say` path regressed — roll back (§Rollback).

- [ ] **Step 4: §11.5 item 1 — announce with the ceiling idle.**

```bash
timeout 120 $SSH 'cd ~/mass-resolver && K=$(cat .http_secret) && \
  curl -s -H "X-Resolver-Key: $K" -H "Content-Type: application/json" \
    -d "{\"intent\":\"interaction\",\"params\":{\"mode\":\"announce\",\"text\":\"test announcement\"}}" \
    http://192.168.122.1:8770/command | python3 -c "
import json,sys
d = json.load(sys.stdin)
m = d[\"metadata\"]
print(\"ok\", d[\"ok\"], \"chat\", d[\"chat_text\"])
print(\"announced\", m.get(\"announced\"), \"chime\", m.get(\"chime\"),
      \"mic\", m.get(\"mic\"), \"volume_restore\", m.get(\"volume_restore\"))"'
```

Expected: `ok True`, `chat Announced.`, `announced True`, `chime {"played": true, ...}`,
`mic {"muted": true, "confirmed": true}`, `volume_restore restored`. **The operator must hear the
chime then the sentence.** Then read the mic switch back and confirm it returned to `off`.

- [ ] **Step 5: §11.5 item 2 — announce over music.** Start a station, note its volume, announce, and
  confirm the §5 golden order in `resolver.log` plus the station returning at its original volume.
  Read `media_player.ceiling_speakers` before and after via HA REST (token from on-host
  `~/mass-resolver/.ha_token` into a shell var, **never printed**).

- [ ] **Step 6: §11.5 item 3 — two announcements ~1 s apart.** Expect the second to supersede, and
  the mic to end `off` — the §9.2 `prev`-inheritance rule, live.

- [ ] **Step 7: §11.5 item 6 — the timeout measurement.** Announce a message at
  `announce_max_chars` and record the wall-clock duration of the `/command` call. This is the only
  measurement of the accumulated-sleep/inactivity-timeout undercount we will have, and it decides
  whether 200 s is enough (§6.5). Record it in the `CHANGELOG.md` entry.

- [ ] **Step 8: §11.5 item 5 — the self-wake acceptance test.** Read the satellite's pipeline traces
  (WS `assist_pipeline/pipeline_debug/list`, pipeline `01kxygpr39jas5hgsf28cph108`) and confirm **no
  run** was recorded during any announcement. The resolver log cannot show this, because a self-wake
  never reaches the resolver.

- [ ] **Step 9: Release the live lane** in `BACKLOG.md:306`, and write the `CHANGELOG.md` deploy
  entry: files deployed, `BACKUP_TS`, host test counts, the measured duration, and the operator's
  audible confirmation.

- [ ] **Step 10: Commit the docs.**

```bash
git add docs/homebrain/CHANGELOG.md docs/homebrain/BACKLOG.md
git commit -m "docs(homebrain): record the AN-01 resolver deploy and live validation"
```

---

# Phase G4a — The announcement REST command (🔴 OPERATOR-GATED, WRITE)

### Task 25: Create `rest_command.resolver_command_announce`

Per **D13**'s recorded decision. The preferred shape is a **dedicated** command so no existing
caller's timeout moves.

- [ ] **Step 1: Claim the live lane** in `BACKLOG.md:306`.

- [ ] **Step 2: Back up the config fragment first.** Copy the current `configuration.yaml` (or the
  `rest_command:` package file) to a timestamped file outside HA's config reload path, and record the
  path. This is G4a's rollback pointer.

- [ ] **Step 3a: Confirm D13b before writing — the inference gets checked here.** Checkpoint A
  passed D13b **by inference from nine working callers, not by reading the template** (G1b step 3c).
  The YAML is open in front of you for this task anyway, so read the `payload:` line now and classify
  it. This is the cheapest moment to turn the inference into a fact.

  The classification:

  | Body template | Meaning | Action |
  |---|---|---|
  | `{{ params \| to_json }}` (or `\| tojson`) | `params` is serialised to JSON properly | **Go.** Task 26's structured form is correct as written. |
  | `{"intent": "{{ intent }}", "params": {{ params \| to_json }}}` | same, spelled out | **Go.** |
  | `{{ params }}` — raw interpolation | Python's `dict` repr, which uses **single quotes** (`{'mode': 'announce'}`) and is **not valid JSON** | **🛑 STOP. Do not create the command.** The resolver's `/command` would reject or mis-parse the body. Report it and return to design: either the rest_command body needs fixing (a change to a template five live callers share) or `mode=announce` needs a different transport. |
  | Anything else | unknown | **🛑 STOP** and report the literal template before proceeding. |

  **Why this is a gate rather than a test-and-see:** a raw-interpolation failure would surface as an
  announcement that silently does nothing, or a `400` from `/command`, at G4b — after the command
  exists and the sentence triggers are live. Reading one line first is cheaper than debugging that,
  which is why the primary read blocks Checkpoint A instead of sitting here.

  **Note the existing five callers work today**, which is *evidence* that the template serialises
  `params` correctly for `say_text` and `radio`/`music`/`news`/`media_status` — but it is not proof
  for a nested mapping with a different key set, so read it rather than infer it.

- [ ] **Step 3b: Add the command**, copying the verified `url`, header names and `payload` template
  from `resolver_command` verbatim. Substitute the real values; do not invent them:

```yaml
rest_command:
  # AN-01: a DEDICATED command so no existing caller inherits a 200s timeout (design 6.5).
  # /command is synchronous, so HA blocks for the whole announcement.
  resolver_command_announce:
    url: <the same url as resolver_command>
    method: POST
    timeout: 200                                # D13: resolver_command's own timeout is lower
    headers:
      X-Resolver-Key: !secret <the exact secret name resolver_command uses>
      Content-Type: application/json
    payload: <the SAME body template as resolver_command, verified at step 3a>
```

**Never inline the key** — reference the existing `!secret`. **Never paste the template from
memory** — copy it from the live file, because step 3a's whole point is that its exact text matters.

- [ ] **Step 4: Reload.** Developer Tools → YAML → *Reload REST commands* (or restart HA if that
  reload is unavailable). Confirm `rest_command.resolver_command_announce` appears in the service
  list.

- [ ] **Step 5: One round-trip through it.** Call it from Developer Tools → Actions with
  `{"intent": "interaction", "params": {"mode": "announce", "text": "rest command check"}}` and
  confirm the announcement plays and the response carries `chat_text: "Announced."`.

- [ ] **Step 6: Confirm no existing caller changed.** `script.play_radio`, `script.play_music`,
  `script.find_stations`, `script.news` and `script.media_status` must still reference
  `rest_command.resolver_command` with its original timeout. If D13 chose the **shared** shape
  instead, record the new timeout and the latency exposure it adds to those five in `CHANGELOG.md`.

- [ ] **Step 7: Release the lane** and note the change in `CHANGELOG.md`.

---

# Phase G4b — Sentence triggers and result relay (🔴 OPERATOR-GATED)

### Task 26: Add the two sentences, the result relay, and the source condition

- [ ] **Step 1: Claim the live lane.**

- [ ] **Step 2: Back up the automation.** Follow the 2026-09-06 precedent:
  `~/mass-resolver/.bak/automation-voice_ceiling_speakers-<ts>.json`. **This backup is the kill
  switch** — restoring it removes the triggers, and with no caller the `announce` mode is inert.

- [ ] **Step 3: Add the trigger and action to `automation.voice_ceiling_speakers`.** Two sentences
  with a greedy trailing wildcard; the source condition only if **D12** found a dependable
  discriminator:

```yaml
  - id: announce
    trigger: conversation
    command:
      - "announce {message}"
      - "broadcast {message}"
```

```yaml
      - conditions:
          - condition: trigger
            id: announce
          # D12 SETTLED at SPIKE-AN-3 (2026-09-07). Gate on satellite_id, NOT on a pinned
          # Companion device_id: the harm design 5.1 identified is SATELLITE invocation (duck-marker
          # contention, and muting the microphone of the satellite that just invoked it). Web Assist
          # invocation is harmless, so this admits phone + web and blocks only the satellite. A
          # pinned device_id would also break silently on Companion-app re-registration.
          # `| default(none)` is defence for a source where the key is absent; on all three observed
          # sources it is present-and-null.
          - condition: template
            value_template: "{{ trigger.satellite_id | default(none) is none }}"
        sequence:
          - action: rest_command.resolver_command_announce
            data:
              intent: interaction
              params:
                mode: announce
                text: "{{ trigger.slots.message }}"
            response_variable: r
            continue_on_error: true
          - choose:
              # 1. The rest_command failed or TIMED OUT. Without continue_on_error the automation
              #    would abort and set no response at all -- how CHANGELOG:903 describes the
              #    satellite reply automation failing quietly.
              - conditions: "{{ r is not defined or r.content is not defined }}"
                sequence:
                  - set_conversation_response: "I couldn't reach the announcer."
              # 2. The resolver refused. Relay its chat_text VERBATIM -- that string is the whole
              #    point of the honest-failure work (design 5.2).
              - conditions: "{{ not r.content.ok }}"
                sequence:
                  - set_conversation_response: "{{ r.content.chat_text }}"
            default:
              - set_conversation_response: "{{ r.content.chat_text }}"
```

**This is the confirmed shape, measured at G1b — not a guess.**
`automation.satellite_timer_announce_on_ceiling` calls the rest_command with `intent` and `params` as
**top-level `data:` keys**, and `params` as a **structured mapping**:

```yaml
action: rest_command.resolver_command
continue_on_error: true
data:
  intent: interaction
  params: {mode: say_text, text: "Your timer is finished."}
```

There is **no `payload:` wrapper**. An earlier draft of this plan wrapped everything in
`payload: >- {"intent": …}` with a `| to_json` filter on the message; that was wrong and would not
have worked, because no `payload` variable exists in the template namespace. Both are removed.

**No `| to_json` is needed here, and adding one would be wrong.** The message stays a plain
templated string inside a structured mapping; serialising it to JSON is the **rest_command's own
body template's** job, one layer down. That is the part still unverified — see the D13b gate at
**G1b step 3c**, which blocks Checkpoint A, and its re-check at Task 25 step 3a.

**D7 caution on `trigger.slots.message` (unresolved).** SPIKE-AN-3 showed HA **preserves**
capitalisation and punctuation in `trigger.sentence` — STT gave `Run the source probe.`, typed input
gave `run the source probe`. The design's §5 step 3 assumes the opposite (lower-cased, stripped).
**Only `sentence` was observed**, and a wildcard *slot* may normalise differently, so step 4 below
must record what `trigger.slots.message` actually contains — capitalisation, trailing punctuation,
and whether a trailing period survives into the spoken clip. Better prosody than the design predicted
is the likely outcome; either way it is an observation, not an assumption.

**No spoken confirmation.** A text-only conversation response is not a dialogue — nothing is asked of
the operator and no second turn happens. A *spoken* confirmation is forbidden (`ONBOARDING.md` §5):
it would be a second clip fighting the announcement it confirms.

- [ ] **Step 4: §11.5 item 4 — test from the phone, and settle D7.** Both sentences, with music
  playing and with the ceiling idle. Confirm the message is spoken **verbatim** and the app shows
  `Announced.` **Record `trigger.slots.message`'s exact content** — dictate a message with a capital
  and a natural full stop, then compare the resolver log's `chars=` count and the `tts_calls` text
  against what you said. That closes D7.

- [ ] **Step 5: §11.5 item 7 — failure delivery.** Force one refusal end to end — easiest is
  temporarily pointing `announce_mic_mute_entity` at a non-existent entity — and confirm the **phone
  displays the resolver's `chat_text`**, not a generic Assist error. Untested, §5.2 is only an
  intention. Restore the setting afterwards.

- [ ] **Step 6: Test the rejection path.** Dictate a message over `announce_max_chars` and confirm the
  phone shows the limit, and that **nothing plays**.

- [ ] **Step 7: §11.5 item 8 — source behaviour.** Say the same sentence to the **satellite** and
  record what happens. If D12 gave no gate, this is documented behaviour, not a defect.

- [ ] **Step 8: Check the prefer-local interaction.** `ONBOARDING.md` §4 warns the exposed `script.*`
  surface is not the only path to the ceiling and that a fix applied to one path is invisible to the
  other. Confirm the new sentences beat the LLM (they should: `prefer_local_intents` is on) and that
  they do not shadow any of the 34 existing `play_favorite` sentences.

- [ ] **Step 9: Release the lane** and record everything in `CHANGELOG.md` — including that this is
  **live config only, not in the repo**, which is what makes the entry the sole record.

---

# Phase G5 — Documentation reconciliation (🟢 offline)

### Task 27: Reconcile the docs

**Files:**
- Modify: `docs/homebrain/ONBOARDING.md` (§2/§4/§5/§6)
- Modify: `docs/homebrain/BACKLOG.md` (`:185` reconciliation note, the `AN-01` row, `:306`)
- Modify: `docs/homebrain/assistant-capabilities.md`
- Modify: `docs/homebrain/runbooks/quick-connect-and-health-check.md`
- Modify: `docs/homebrain/2026-09-06-phone-assist-ceiling-announcement-design.md` (status header,
  and the §8.3a addendum from Task 17's deviation)

- [ ] **Step 1: `ONBOARDING.md` §4** — add `announce` to the `interaction` mode list; record the two
  new sentences on `automation.voice_ceiling_speakers`; state that `announce` is **not** exposed to
  ChatGPT.

- [ ] **Step 2: `ONBOARDING.md` §2** — record whichever G4a shape shipped: the dedicated
  `rest_command.resolver_command_announce` with its 200 s timeout, or a raised shared timeout and the
  latency exposure that adds to the five exposed scripts. This is live config that exists nowhere in
  the repo, so the doc is the only record.

- [ ] **Step 3: `ONBOARDING.md` §5** — add announcements to "What works", held to the same
  "verified, operator-eared" standard `say_text` was: quote the log line and the operator's
  confirmation, not the design's intent.

- [ ] **Step 4: `ONBOARDING.md` §6** — amend the satellite false-wake entry: announcements now mute
  the mic for their own audio (with the measured confirm latency); ambient false wakes are unchanged.
  If D12 gave no source gate, state that announcements can also be triggered from the satellite.

- [ ] **Step 5: `BACKLOG.md`** — **append** a dated reconciliation note to the `S1b`–`S4` row
  (`:185`) recording that the 2026-07-16 "audible announce blocked" status was superseded by
  `say_text` on 2026-09-05 and delivered by AN-01. **Leave the original wording intact** — it is an
  accurate record of what was known then. Add the `AN-01` row as `done`, and confirm `:306` reads
  FREE.

- [ ] **Step 6: `assistant-capabilities.md`** — a short note that announcements are **deliberately
  not** an LLM-exposed tool, and why (`CHANGELOG.md` 2026-09-06's take-the-model-out-of-the-loop
  lesson). No exposure-lockstep (NL-02) work is needed, because nothing new is exposed.

- [ ] **Step 7: `runbooks/quick-connect-and-health-check.md`** — two lines. (a) If the satellite has
  gone deaf, check the mic-mute switch; a crashed announcement can strand it, and the in-memory
  dead-man dies with the process (§9.5) — recovery is to toggle the switch in the HA UI. (b) If the
  ceiling is silent and `paused` after a failed announcement, both the clip play and its replay
  failed (§8.3a); recovery is *"resume"* (`interaction` mode `resume`), not a resolver restart.

- [ ] **Step 8a: The design doc — correct the §5 step 3 normalisation claim.** It states HA
  normalises trigger text by lower-casing and stripping punctuation, so the resolver receives
  `dinner is ready` rather than `Dinner is ready.` SPIKE-AN-3 contradicted that for
  `trigger.sentence`, and Task 26 step 4 settles it for `trigger.slots.message`. Replace the claim
  with what was measured, and remove D7 from the open list once step 4 has recorded the slot's
  behaviour.

- [ ] **Step 8: The design doc** — update the status header to record G1–G5 complete with dates.
  **No §8.3a addendum:** the plan implements §8.3a as approved. Add one short note recording the
  accepted residual instead — when a clip play and its replay both fail the zone is left paused at
  its baseline, because a blind `media_play` after a raised replay could resume the announcement clip
  rather than the music — and that the operator recovery is *"resume"*.

- [ ] **Step 9: Commit docs separately from code**, per `CLAUDE.md`.

```bash
git add docs/homebrain/ONBOARDING.md docs/homebrain/BACKLOG.md \
        docs/homebrain/assistant-capabilities.md \
        docs/homebrain/runbooks/quick-connect-and-health-check.md \
        docs/homebrain/2026-09-06-phone-assist-ceiling-announcement-design.md
git commit -m "docs(homebrain): reconcile AN-01 announcement into onboarding, backlog and runbook"
```

---

# Rollback

Per gate, most-recent-first. Each is independently sufficient.

| Gate | Rollback |
|---|---|
| **G5** | `git revert` the docs commit. |
| **G4b** | Restore the `automation.voice_ceiling_speakers` JSON backup from Task 26 step 2 and reload. **This is the real kill switch** — with the sentences gone nothing calls `mode=announce`, and G4a's command becomes an unused definition. |
| **G4a** | Restore the config fragment backup from Task 25 step 2 and reload REST commands. With the **dedicated** shape the blast radius is zero: no existing caller referenced it. With the **shared** shape, restoring returns all five exposed scripts to their prior timeout. |
| **G3** | `cp ~/mass-resolver/.bak/<BACKUP_TS>/* ~/mass-resolver/` then the user-run `sudo systemctl restart mass-resolver`. Rarely needed: no existing mode changes behaviour on its success path, and with no caller the `announce` mode is inert code. |
| **G3, config-only (no restart of changed code)** | `announce_chime_uri: ""` disables the chime; `announce_require_mic_mute: false` drops the mute precondition; `announce_volume: 0.70` matches replies. A resolver restart is still needed for `config.json` to take effect. |
| **G2** | `git revert` the PR merge commit. Nothing is deployed by the merge. |
| **G1/G1b** | Nothing to roll back — Task 1 deletes its throwaway automation, Task 3 restores the switch, Task 4 writes nothing. |

**Two in-memory structures do not survive a restart** — `_mic` and `_vol_recovery`, plus the existing
`_snaps`. A restart mid-announcement can therefore leave the satellite muted or the ceiling at 0.80
with nothing scheduled to fix it (§9.5, §9.7). Recovery is manual: toggle the mic switch and set the
volume in the HA UI. This is why Task 22's preflight requires an idle satellite.

---

# Self-Review

Run against the design at `259c730`.

### 1. Design coverage

| Design section | Task(s) | Status |
|---|---|---|
| §1 goals 1–7 | 15, 26 (1–3); 9, 15 (4); 11, 12 (5); 14 (6); 5, 11 (7) | covered |
| §2 non-goals | not implemented, by construction | covered |
| §3 current-state evidence | quoted in task rationales | covered |
| §4 component boundaries | 8 (haconn), 11 (`_play_clip_and_wait`), 14 (`_mic` in `_announce` only), 15 (`_announce` policy) | covered |
| §5 data flow, §5.1 source gating, §5.2 result relay | 26 (all three), 1 + Checkpoint A (D12) | covered |
| §6.1 `resolve_media_source` | 8 | covered |
| §6.2 settings | 9 | covered |
| §6.3 mode surface | 10 | covered |
| §6.4 internal `resolved` keys | 12 (`uris`/`match_keys`/`finish_timeouts`/`volume_override`), 13 (`gen`), 15 (`skip_on_fresh_playback`) | covered |
| §6.5 budgets, clipping, `rest_command` timeout | 6, 7, 12, 20, 25; measured at 24 step 7 | covered |
| §7 ordered sequence A–I | 15 | covered |
| §8.1 what moves | 11 | covered |
| §8.2 per-clip match key | 12 | covered |
| §8.3 per-clip outcomes | 12, 15 | covered |
| §8.3a fatal later-clip failure | 17 | covered, **no deviation** — an unsafe last-resort un-pause was proposed and removed (see Task 17's note); the accepted residual is documented at Task 27 |
| §8.4(a) marker budget | 18 | covered |
| §8.4(b) `volume_override` `is None` | 12 | covered |
| §8.4(c) lost-ack volume | 16 | covered |
| §8.5 silent announcement is a failure | 15 | covered |
| §9.1 `_mic` state + sole-writer invariant | 14 | covered |
| §9.2 gen claim + `prev` inheritance + atomic adoption | 13, 14 | covered |
| §9.3 write-then-confirm | 14 | covered |
| §9.4 restore only if the lease is ours | 14 | covered |
| §9.5 mic dead-man | 14 | covered |
| §9.6 supersession matrix | 15 (`AnnounceSupersessionTest`) | covered |
| §9.7 volume dead-man | 19 | covered |
| §10 failure table rows 1–24 | 10 (1, 2, 2a); 15 (3–6, 16); 14 (7–10); 12/16/17 (11–15b); 11 (17); 19 (18); 17 (19); 15 (20, 20a); 14 (21); Rollback note (22); 26 (23, 24) | covered |
| §11.1–§11.4 tests | 5, and each implementing task | covered |
| §11.5 integration items 1–8 | 24 (1–3, 5, 6), 26 (4, 7, 8) | covered |
| §12 SPIKE-AN-1/2/3 | 2, 3, 1 | covered, unexecuted |
| §13 gates G1–G5 | all phases | covered |
| §13.1 rollback | Rollback section | covered |
| §13.2 doc updates | 27 | covered |
| §14 D1–D14 | 1–4, Checkpoint A | D1–D6, D8, D12–D14 covered. **D8 is settled** (G1b, 2026-09-07). **D13 split into D13a** (timeout — **informational**, since a dedicated command is used) **and D13b** (body template — **passes by production evidence, explicitly inferred rather than read**; nine live callers passing 0–5-key `params` mappings rule out raw interpolation, and Task 25 step 5's round trip is the final validation). **D12 is settled** (SPIKE-AN-3, 2026-09-07) and Task 26 carries the condition. **D7 is unresolved-but-informed** — HA preserves capitalisation/punctuation in `trigger.sentence`, contradicting the design's §5 step 3; the wildcard *slot* is still unobserved, so Task 26 step 4 records it and Task 27 step 8a corrects the design. **D9, D10, D11 remain observational** — recorded at G3/after-use, no task implements them |

**One gap, deliberate:** D9 (chime→speech gap), D10 (how often a non-announcement supersedes) and
D11 (is 0.80 right by ear) are observations with no code consequence. **D7 was in this group and has
been promoted** — SPIKE-AN-3 contradicted the design's normalisation claim, so Task 26 step 4 now
records the slot's real content and Task 27 step 8a corrects the design. They are recorded at G3/G4b or after a week of use, not built.

**One behavioural change to a shared path, intended:** Task 17 changes `say`/`say_text` recovery on
an *ambiguous* play failure from un-pause to replay, per §8.3a. It is the only existing test
expectation AN-01 alters (`ReplyBumpTest`, Task 17 step 2), it is asserted by its own tests, and it is
called out in Task 21's PR body. Success-path sequences are unchanged and pinned by `GoldenSequenceTest`.

### 2. Placeholder scan

- No `TBD`, `TODO`, "implement later", or "add appropriate error handling".
- Every code step carries real code.
- **Three intentional substitution points**, each labelled and each blocked by Checkpoint A rather
  than left vague: `<D1: the exact switch entity id>` (Task 9 step 4), the copy-from-live values in
  Task 25 step 3b (gated by step 3a),
  (D12 is now settled, so Task 26 step 3 carries a real condition). Task 9 step 4 says explicitly: *do not leave the placeholder; if
  Checkpoint A did not produce D1, stop.*
- **Every code snippet is directly usable as written.** An earlier draft carried two that were not:
  Task 17's `_seq` helper referenced an undefined `cap_or_none`, and Task 18's last test ended in
  `assertTrue(True)`. Both are rewritten — `_seq` is now `_two_clip(cap, ha, rid)` and is used by the
  two tests that previously inlined the same dict, and Task 18 now asserts the published
  `marker_budget_s` via a `_play_clip_and_wait` spy, plus a companion test that `say_text` publishes
  none. `capability.run(...)` is valid as written: `capability` is imported at
  `tests/test_interaction.py:5` (see Global Constraints).

### 3. Type and signature consistency

Checked across tasks:

| Symbol | Defined | Used |
|---|---|---|
| `ws_connect(host, port, path, timeout=15)` | 6 | 8 |
| `get_entity_state(entity_id, timeout=10)` | 7 | 11, 14, 19 |
| `resolve_media_source(uri, timeout=10)` → `str`, raises `IOError` | 8 | 15 |
| `_render_announcement_text(ctx, text)` → `(str|None, dict|None, bool)` | 10 | 15 |
| `_play_clip_and_wait(ctx, rid, zone, norm_uri, match_key, clip, opts, superseded)` → `{"started","issued","clip"}` | 11 | 12 |
| `_claim_gen(zone)` → `int` | 13 | 14, 15 |
| `_mic_claim(ctx, zone, my_gen, rid, clips=2)` → `(dict|None, dict|None)` | 14 | 15 |
| `_mic_confirm(ctx, zone, my_gen, rid)` → `(bool, dict|None)` | 14 | 15 |
| `_mic_release(ctx, zone, my_gen, rid)` → `bool` | 14 | 15, dead-man |
| `_volume_recovery(ctx, zone, gen, attempt)` | 19 | timer |
| `_volume_recovery_secs(ctx)` → `float` | 19 | 19 |
| `metadata` keys `clips`, `chime`, `mic`, `announced`, `prefix_dropped`, `volume_restore` | 12, 15, 19 | 15, 24 |

`opts` carries the same seven keys in Tasks 11 and 12. `err` dicts use `{"code", "reason",
"chat_text"}` in Tasks 10 and 14, matching `cr.err`'s parameter order in Task 15. Error codes are
`invalid_input`, `unavailable` and `upstream_error` throughout — all in `ERROR_CODES`.

### 4. Gate ordering

G1 → G1b → **Checkpoint A** → G2 → G3 → G4a → G4b → G5. Checkpoint A blocks G2 and names which task
consumes each discovery. G4a precedes G4b because the automation references the command G4a creates.
Every live gate claims and releases the single `BACKLOG.md:306` lane. The three 🔴 phases each say
explicitly to stop and wait.

### 5. Executable commands

Verified against this repo at `259c730`:
- `python -m unittest discover -s tests -t .` → `Ran 376 tests ... OK` (the stated baseline).
- `python tests/test_<name>.py` is the documented per-file convention
  (`local-music-architecture.md:231`).
- The SSH/`scp`/`py_compile` shapes are copied from `runbooks/resolver-deploy.md`, including the
  `/d/repos/...` path note for `scp`.
- Expected test counts step 376 → 379 → 382 → 384 → 394 → 398 → 407 → 418 → 423 → 444 → 458 → 461 →
  471 → 476 → 484. Treat these as guides: they assume every test in this plan is written exactly as
  given, and a differing count is not a failure by itself.

---

> **Execution handoff.** This plan is written for `superpowers:subagent-driven-development`
> (recommended) or `superpowers:executing-plans`. **Do not begin at Task 5.** The first authorised
> action is presenting Tasks 1–4 to the operator for G1/G1b approval, then Checkpoint A. G2 must not
> start until Checkpoint A states that D1–D6, D8 and D12–D14 are recorded.

