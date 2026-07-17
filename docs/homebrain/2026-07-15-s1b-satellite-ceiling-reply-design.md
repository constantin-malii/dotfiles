# S1b — Satellite Full-Assistant, Reply on Ceiling (design)

> **Design / research only. No implementation, no firmware/resolver/HA/pipeline change, no exposure, no
> live gate.** Defines how the **reSpeaker Living Room** satellite becomes a full assistant — deterministic
> **commands handled locally**, **open Q&A via the LLM** — with **every spoken reply played on the ceiling
> zone** (overlay over the S1a-ducked music), not the satellite's own speaker.
> Inputs: `2026-07-14-s1a-satellite-ceiling-duck-design.md` (duck/restore trigger, now live),
> `2026-07-06-au-01-interaction-audio-policy-design.md` + AU-02/AU-03 (resolver duck/announce, live),
> `2026-06-28-F1-R-chatgpt-tool-result-relay-design.md` (tool-result relay), `s0-satellite-inventory.md`
> (pipelines, TTS-reach), ONBOARDING §5/§6/§12.
>
> Track: **S** · Item: **S1b** (`design`, second slice of `S1`) · Branch: `homebrain/s1b-satellite-ceiling-reply`.
> Live gate (BACKLOG §10) left **FREE**.

---

## 1. Scope

**In scope:** turning the single satellite into a full assistant whose **reply is heard on the ceiling**
(`media_player.ceiling_speakers`): (a) a new satellite **pipeline** (LLM agent that prefers local commands +
Piper TTS), (b) a **firmware redirect** so the reply audio leaves the satellite instead of playing locally,
and (c) a **resolver ceiling-announce** that overlays the reply on the ceiling (auto-resume) during the S1a
duck. Chosen mechanism: **hybrid C+A** (§4). Sliced for delivery — **S1b-1** (resolver `say` + duck-ownership,
no firmware) then **S1b-2** (pipeline + firmware); see §9. Duck ownership for reply turns is decided in the
companion **ADR** `2026-07-15-s1b-duck-ownership-adr.md` (resolves review finding **B1**).

**Out of scope:**
- The duck/restore trigger itself → **S1a** (live). S1b plays the reply *inside* the window S1a already ducks.
- Multi-room / multi-satellite / privacy gating / household announce-targeting → **S2–S4**.
- Phone assist → **unchanged** (its own pipeline; phone mic → reply on phone).

## 2. Target behaviour (approved)

| Endpoint | Mic | Reply output | Agent |
|---|---|---|---|
| **Satellite** (reSpeaker) | on-device | **Ceiling** (always) | **LLM, prefers local commands** |
| **Phone** | phone | phone (unchanged) | unchanged |

- **Commands** (device control, timers, and the exposed resolver media tools — `play_music`/`play_radio`/
  `find_stations`/`news`) are handled **deterministically** via the agent's *prefer-handle-locally* path +
  existing tool-calls. **Open Q&A** falls through to the **LLM** (ChatGPT / `conversation.openai_conversation`).
- **The satellite says nothing on its own speaker** — every spoken reply comes out of the ceiling, overlaid
  on the (S1a-ducked) music and auto-resumed after.
- **Explicit behavior change (not just TTS routing):** this **swaps the satellite's conversation agent** from
  today's local `conversation.home_assistant` to the **LLM** — open Q&A now runs on the **live conversation
  surface**. Keep `assistant-capabilities.md` / the prompt in lockstep (NL-01/NL-02); this is exposure-adjacent.

## 3. Constraints that shape it

| Constraint | Source | Consequence |
|---|---|---|
| A voice satellite's reply plays **on itself** by default; `assist_satellite` exposes no "route response to another media_player" (`supported_features=3` = ANNOUNCE + START_CONVERSATION only) | live check 2026-07-15 (HA 2026.6.4) | Redirect is **not** a config toggle — needs a deliberate mechanism (§4). |
| ESPHome `voice_assistant` fires **`on_tts_end`** with the finished **TTS audio URI**; the reSpeaker config already defines `on_tts_start`/`on_tts_end`/`on_end` and `media_player: external_media_player` | formatBCE config + ESPHome docs | The URI can be **handed to HA/the resolver natively** — no fragile "capture the reply text" hook needed. |
| Today's **ChatGPT pipeline has `tts=None`** (S0 §4) | S0 | The satellite must run a **new** pipeline with **Piper TTS on** (so `on_tts_end` has a URI to redirect); switching to the existing ChatGPT pipeline would yield **no speech**. |
| Ceiling player is **MA Universal → Squeezelite**; `media_stop` wedges it; **announce = overlay + auto-resume** is the safe lever | AU-01 §2, local-music notes | The reply must play as an **announce/overlay**, not `play_media` that replaces the stream (which would kill the music). |
| Resolver = **sole TTS owner**; no second TTS path | assistant-tooling design §6 | Ceiling playback of the reply is **resolver-owned** (it already holds the MA/HA connections + `announce`). |
| Satellite reply arrives during the **`responding`** state; S1a restores on **`idle`** (after) | S1a live behaviour | The reply overlays *before* restore; S1a's restore must not fire mid-reply (it won't — `idle` follows `responding`). |

## 4. Chosen mechanism — hybrid C+A

Two other mechanisms were considered and rejected as primaries: **B** (HA automation plays the pipeline TTS
URL on the ceiling) splits TTS ownership away from the resolver; **pure A** (resolver *re-synthesizes* the
reply from captured text) has no clean HA hook to capture a hardware-satellite conversation reply. The hybrid
takes the best of each:

```
"Okay Nabu, <question>"
  satellite mic → Whisper STT → OpenAI agent (prefer-local)
      ├─ command  → local intent / resolver tool-call (deterministic; media = silent-by-action)
      └─ open Q&A → LLM answer
  → Piper TTS (new pipeline) produces reply audio URI
  → [C] firmware on_tts_end: DO NOT play locally; hand the URI to the resolver
  → [A] resolver plays the URI on media_player.ceiling_speakers via MA ANNOUNCE (overlay + auto-resume),
        riding the S1a duck (reply at normal level over the quiet music)
  → interaction ends → assist_satellite → idle → S1a RESTORE (unchanged)
```

- **C (capture + suppress, firmware):** rework the reSpeaker `voice_assistant` so the TTS response is **not
  auto-played on `external_media_player`** (no double-speak) and `on_tts_end` **hands the URI to the resolver**
  (HA event or `homeassistant.service` → resolver `say`). Local wake/feedback sounds stay on-device. Requires
  an ESPHome YAML edit + **OTA reflash** (reversible by reflashing the current YAML).
- **A (playback, resolver):** a new resolver intent **`say`** takes the **URI** and plays it on the ceiling.
  This is a **new playback primitive** — `media_player.play_media(announce=true)` with the URI (an overlay
  that auto-reverts), **not** the AU `tts.speak` path (which *synthesizes*): it shares the duck-composition
  concept, not the code. Because the URI is already-synthesized Piper audio, the resolver **replays it — no
  re-synthesis**. Resolver stays sole TTS owner, and **owns the duck lifetime for reply turns** (ADR — §5, §7).

## 5. Components

| # | Component | Owner | What |
|---|---|---|---|
| 1 | **New satellite pipeline** "Living Room ChatGPT" | HA | Whisper STT + `conversation.openai_conversation` (**prefer handling commands locally** ON) + **Piper TTS**. Assigned to the reSpeaker. |
| 2 | **Firmware redirect** | device (ESPHome) | Suppress local TTS playback; `on_tts_end` → hand URI to the resolver. OTA reflash. |
| 3 | **Resolver `say` (URI → ceiling)** | resolver | New capability: `media_player.play_media(announce=true)` of a given audio URI on `media_player.ceiling_speakers` (overlay + auto-revert). **New primitive, not `tts.speak`.** Silent contract otherwise. |
| 4 | **Duck ownership (reply turns)** | resolver | Per **ADR `2026-07-15-s1b-duck-ownership-adr.md` (Option H)**: `say` holds the duck when the announce starts and issues **restore on playback-end** (await MA completion, else duration-hold — never ceiling state-watch). **S1a's `idle→restore` is removed for this satellite**, repurposed to arm a ~2–3 s grace fallback; 120 s dead-man unchanged as backstop; barge-in → new `say` interrupts, restore after the latest reply. |

## 6. Command vs Q&A on the ceiling (decision)

Media commands are **silent-by-action today** (the stream starting is the confirmation). With prefer-local +
tools, a command still yields a spoken confirmation (`chat_text` relayed by the LLM → TTS → ceiling). **Default:
speak all replies on the ceiling** (simplest, consistent with "ceiling always"); a `speak_confirmations` tunable
can later suppress spoken confirmations for pure media commands if the double-confirmation (music + speech) is
noisy. Open Q&A always speaks.

## 7. Error handling

- **Ceiling announce fails** (URI unreachable / MA error) → reply is **dropped + logged**; do **not** fall back
  to the satellite speaker (that needs un-suppressing local playback → reintroduces double-speak). The command's
  action still happened; a lost *spoken* answer is the accepted failure.
- **URI never arrives** (firmware/pipeline issue) → no `say` becomes active → the repurposed `idle` **grace G
  (~2–3 s)** restores the music (no long quiet gap); 120 s dead-man is the ultimate backstop (ADR).
- **Reply longer than the dead-man (120 s):** `say` holds the duck for the reply and issues restore on
  playback-end; the dead-man is only the failure backstop. Validate long-answer behaviour (§10).
- **Dropped Q&A reply UX:** a command's silent drop is fine (the action happened), but a dropped *open-Q&A*
  answer is total silence with no signal. Consider a **local error chirp / LED** on the satellite (feedback
  stays local per §4) so a lost answer is at least perceptible. (Tunable; decide at plan time.)

## 8. What S1b does NOT do

- **No `media_stop`** on the ceiling (overlay/announce only).
- **No second TTS path** — the resolver plays the reply URI; it does not synthesize a parallel TTS.
- **No phone change**, **no multi-room/targeting** (S2–S4), **no change to S1a's duck/restore**.

## 9. Dependencies, build order, ownership

| Piece | Track / item | Notes |
|---|---|---|
| Duck/restore trigger | **S1a** ✅ live | S1b plays the reply inside S1a's ducked window. |
| Resolver duck/announce + ceiling zone | **AU-02/AU-03** ✅ live | `say` reuses the announce path. |
| Tool-result relay (media commands) | **F1-R** ✅ live | Command confirmations already return `chat_text`. |
| New satellite pipeline (LLM + Piper) | **S1b** (HA-live) | Prefer-local; assign to satellite. |
| Firmware redirect (`on_tts_end` + suppress local) | **S1b** (device/firmware) | ESPHome edit + OTA reflash. |
| Resolver `say` (URI → ceiling announce) | **S1b** (resolver) | New capability + deploy (single live gate). |

- **Slices / build order (review recommendation):**
  - **S1b-1** = resolver `say` (URI → ceiling) **+ the ADR duck-ownership mechanism** (reply-active hold,
    restore-on-playback-end, `idle`→grace-G, dead-man) **+ Spike 2**. Fully testable over `/command` with a
    **test URI — no firmware.** This proves the entire duck/announce/restore choreography (all of **B1**)
    behind one resolver gate.
  - **S1b-2** = new pipeline (OpenAI prefer-local + Piper) + firmware redirect (`on_tts_end` → `say`, suppress
    local) **+ Spike 1** — only once S1b-1 is green (firmware/brick-risk last).
  - Each live step is **approval-gated**; S1b touches **HA + firmware + resolver** — the highest-surface S-item.
- **S1b modifies S1a's live automation** (drops `idle→restore` for this satellite, repurposes `idle` to arm
  grace G — per ADR). A **behavior change to a live automation**, not additive; call it out in the plan.
- **NL overlap:** the "LLM prefers local commands" behaviour overlaps **NL-01** (thin routing over deterministic
  caps) and **NL-02** (prompt/`assistant-capabilities.md` lockstep). Keep the capability set + prompt in lockstep
  when the satellite gains open Q&A.

## 10. Open questions / validation (before build)

- `TODO:` **Spike 1 (go/no-go):** in the reSpeaker firmware, can local TTS playback be **suppressed** while
  `on_tts_end` still delivers the URI (keeping wake/feedback sounds local)? If clean suppression proves
  impractical, fall back to **muting the satellite `media_player` during `responding`** (racy) or reconsider B.
- `TODO:` **Spike 2 (S1b-1 — three concrete things, per ADR):** (1) does MA `play_media(announce=true)` give a
  **completion signal**, or must we use **duration-hold** (`clip_len + margin`)? (2) MA's auto-revert targets
  the **live floor** volume (0.15), **not a stale capture**; (3) the resolver-issued restore lands cleanly
  **after** MA's revert (duck → announce boost/revert → restore, sequential). **Plus:** the reply URI is
  **fetchable by MA and outlives the fetch** (internal-URL/LAN + TTS-cache-TTL, per S0 §5).
- `TODO:` **Barge-in default:** a re-trigger during a ceiling reply → new `say` **interrupts/replaces** the
  in-flight announce; restore after the latest reply (confirm MA replace semantics).
- `TODO:` **Reflash precondition (S1b-2):** capture the reSpeaker's **current running ESPHome YAML** before any
  edit — the "reversible by reflashing current YAML" rollback depends on having it in hand.
- `TODO:` **ChatGPT prefer-local**: verify device/media commands stay **deterministic** (not LLM-paraphrased or
  dropped) and the exposed tools still fire — the NL-01/NL-02 concern; keep `assistant-capabilities.md` in lockstep.
- `TODO:` **Latency budget + cost:** the reply path is long (STT → OpenAI → Piper → URI → firmware → resolver
  → MA). Set a **time-to-first-audio target (≤2–3 s)** and a stance if exceeded (accept / local "working…"
  chirp); track per-query LLM cost. Q&A can *feel* broken even when correct if this is unbudgeted.
- `TODO:` **Wake-slot choice:** primary wake → this pipeline, or the 2nd on-device wake-word slot (S0 dual-slot
  note) so the local-only pipeline stays available. Decide at plan time.

## 11. Spike 2 results + design revision (VALIDATED 2026-07-15) — supersedes §4 mechanism

S1b-1 (resolver `say`) shipped, and its Spike-2 live validation over `/command` **disproved the core
mechanism assumption**. Measured on the live ceiling (MA Universal → Squeezelite, radio playing):

| Probe | Result |
|---|---|
| `media_player.play_media(announce=true)` (a URI) | **synchronous ~14 s block**, **stops the stream**, **clip inaudible**, then resumes → wrong primitive |
| `music_assistant.play_announcement` (a URI) | **synchronous ~7 s block**, **audible ✅**, but **pause → reply → resume** (music stops *before* the reply — NOT an overlay), and **radio cannot resume → drops to `idle`** |

**Three §4 assumptions were wrong:**
1. **Not an overlay** — the player **pauses**, plays the reply, resumes. (AU-01's duck-under-TTS overlay was
   the resolver's `tts.speak` path, not URL playback.)
2. **Synchronous + slow (7–14 s)** — the call **blocks** until the reply finishes. This breaks the
   "`say` returns fast, a reply timer restores later" model — and with it, most of S1b-1's machinery
   (`reply_active`, duration-hold reply timer, deferred `idle→restore`, H2 `ignore_user_override`, N1 gen-id)
   exists to solve problems a **blocking, self-pausing, self-resuming** call does not have.
3. **Radio wedges** — a live stream can't resume after an announcement (RQ-01/RQ-02).

### Revised mechanism (replaces the §4 hybrid C+A reply-timer model)
- **Primitive:** `music_assistant.play_announcement` (URI, audible) — **not** `media_player.play_media`.
- **Model:** `say` = a **blocking** call (MA pauses → plays the reply → resumes); on return the reply is done
  and resumable content is back. Needs a **long/adequate timeout** (≥ longest reply; today's `call_service_rest`
  5 s is far too short) or a non-blocking variant with a completion signal.
- **Simplification:** the reply timer / duration-hold / `reply_active` defer / H2 / N1 machinery is **no longer
  needed** for the reply — **restore-on-return is exact**. The B1 duck-ownership problem largely dissolves (the
  announce call spans the whole reply). S1a's duck remains only for the *listening* phase.
- **UX:** pause→reply→resume is acceptable (arguably clearer) for a conversational answer.

### Radio policy — DECIDED 2026-07-15: (b) resolver re-plays the station
Reply always goes to the ceiling; after it, the resolver re-issues the station that was playing. (Considered,
not chosen: (a) local-music-only — reply on the satellite for radio; (c) accept radio stops.)

**Replay mechanism (grounded by a read-only check 2026-07-15):** while playing radio, the ceiling exposes a
**stable, re-playable MA id — `media_content_id = library://radio/2`** (type `music`, source "Music Assistant
Queue"; `media_title` = the current track, **not** the identifier). So `say` will:
1. **Before** the announce, read the ceiling state; capture `media_content_id` (and whether it was `playing`).
2. `music_assistant.play_announcement` (blocking).
3. **After**, if the ceiling did **not** auto-resume (state ≠ `playing` — the radio case), **re-play the
   captured `media_content_id`** via `music_assistant.play_media`. Local music auto-resumes → this is a no-op.
   Reacting to the *actual* post-announce state handles radio vs local uniformly, without pre-classifying.

**Spike-3 — VALIDATED 2026-07-15 (live):** capture→announce→replay confirmed on radio — captured
`library://radio/2` → `music_assistant.play_announcement` (audible, blocked **8.2 s**) → ceiling `idle` (radio
didn't auto-resume) → `music_assistant.play_media {media_id: library://radio/2}` → **radio restarted**
(`playing library://radio/2`). So (b) is proven. **Not yet** explicitly tested: local-music **auto-resume**
(the easy case — `play_announcement` resumes resumable content, so the post-announce state is `playing` and the
replay step is skipped) — confirm in the S1b-1′ validation. The **reply-on-ceiling mechanism is now fully
grounded**: audible reply + radio survives via capture/replay + blocking restore-on-return.

### Impact
- **S1b-1 as built is superseded** — `say` must be reworked to `play_announcement` + the blocking model,
  dropping the now-unneeded timer machinery. The deployed code is dormant/harmless meanwhile (nothing invokes it).
- The duck-ownership ADR (`2026-07-15-s1b-duck-ownership-adr.md`) is largely mooted by the blocking model (see
  its superseded note).
- **Next:** decide the radio policy → a new, much simpler **S1b-1′ plan** (`say` → `play_announcement`, long
  timeout, restore-on-return, radio-policy branch), re-validated by a fresh Spike before S1b-2.

---

## 12. Spike-2 RE-OPENED (2026-07-16 investigation) — URI form exonerated, announce works

The 2026-07-16 S1b-1′ deploy validation recorded `music_assistant.play_announcement` as **silent** on the
ceiling (CHANGELOG 2026-07-16, and the "hold S1b-2" block). A follow-up live diagnostic (operator listening,
read-only host + coordinated audio tests) **re-opened that finding and overturned it**:

- **The URI form is NOT the cause.** The same plain `tts_proxy` URL (rewritten to the internal base
  `192.168.122.10`) fed to `play_announcement` was **audible over both radio (7.2 s block) and working local
  music (6.9 s block)** — confirmed by ear. The leading "media-source vs tts_proxy" hypothesis is dead: a raw
  `media-source://tts/…` URI is rejected by `play_announcement` (HTTP 500 "Only URLs are supported"), and
  resolving one just yields the same `tts_proxy` URL.
- **The silence was a confound.** The announces measured silent were fired while the ceiling's underlying
  queue was in a degraded **"produced no audio data"** state (intermittent SMB / local-music failure). In
  that state the announce inherits the stalled stream and is silent; it also **blocks ~12–13 s** instead of
  the healthy ~7 s. Even MA's own pre-announce chime was silent then. This is the block-duration tell:
  **~7 s = audible / healthy; ~12–13 s = silent / degraded underlying stream.**
- **No infra regression:** host, VM, Squeezelite (`v1.8`) and MA (`2.9.3`) are all unchanged since
  2026-06-30 — the 07-15-audible vs 07-16-silent gap is the intermittent stream health, not a restart.
- **Spike-3 (radio capture→replay) re-confirmed live:** radio → `idle` after the announce →
  `play_media {media_id: library://radio/2}` restarts the station. `_say`'s existing capture→replay branch
  is correct.

**Net for the design:** §11's "audible via `play_announcement`" revised mechanism **stands**; §11's later
S1b-1′ "silent" note is superseded by this re-open. **`_say` needs no URI-form change** — it already sends
`play_announcement` with the tts_proxy internal-base URL and the radio replay branch. **S1b-2 is GO** on the
announce mechanism, with one caveat carried forward: an intermittent degradation makes the ceiling silent
for **both music and replies**. The reproduced trigger is an SMB / "produced no audio data" local-music
stall, but that does **not** explain the original 07-16 announce `531187df` — silent over an
audibly-healthy **radio** source with a reachable internal-base URL. So the degradation is likely
**source-independent** (it silenced radio and local on 07-16, incl. MA's chime); the SMB stall is one
confirmed instance, not the full trigger set. Track it as a **separate reliability item** (not S1b scope),
**do not assume radio is safe**, and require S1b-2 to **detect a likely-silent announce** (block > ~10 s)
and surface it rather than trusting `ok:true`.

---

> **Rollback for this document:** `git revert` on `homebrain/s1b-satellite-ceiling-reply`, or delete this file.
> No secrets, no implementation, no firmware/exposure change, no live gate.
