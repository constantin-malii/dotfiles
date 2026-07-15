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
duck. Chosen mechanism: **hybrid C+A** (§4).

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
- **A (playback, resolver):** a new resolver intent **`say`** (or an extension of `interaction`) takes the
  **URI** and plays it on the ceiling via **MA announce** (overlay + auto-resume). Because the URI is
  already-synthesized Piper audio, the resolver **replays it — no re-synthesis**. Resolver stays sole TTS owner.

## 5. Components

| # | Component | Owner | What |
|---|---|---|---|
| 1 | **New satellite pipeline** "Living Room ChatGPT" | HA | Whisper STT + `conversation.openai_conversation` (**prefer handling commands locally** ON) + **Piper TTS**. Assigned to the reSpeaker. |
| 2 | **Firmware redirect** | device (ESPHome) | Suppress local TTS playback; `on_tts_end` → hand URI to the resolver. OTA reflash. |
| 3 | **Resolver `say` (URI → ceiling announce)** | resolver | New capability: play a given audio URI on `media_player.ceiling_speakers` via MA announce (overlay + resume). Silent contract otherwise. Reuses AU announce path. |
| 4 | **S1a duck reconciliation** | HA/resolver | Reply overlays during the ducked window; restore on `idle` unchanged. Ensure announce overlays at normal level over the ducked floor and completes before restore. |

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
- **URI never arrives** (firmware/pipeline issue) → nothing plays; the S1a dead-man still restores the music.
- **Reply longer than the S1a dead-man (120 s):** the S1a re-fire keeps the duck alive; the announce itself is
  bounded by the reply length. Validate long-answer behaviour (§10).

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

- **Build order:** resolver `say` (behind the gate, deployable + testable via `/command` with a test URI) →
  new pipeline (HA) → firmware redirect (device) → end-to-end. Each live step is **approval-gated**; S1b touches
  **HA + firmware + resolver** — the highest-surface S-item so far.
- **NL overlap:** the "LLM prefers local commands" behaviour overlaps **NL-01** (thin routing over deterministic
  caps) and **NL-02** (prompt/`assistant-capabilities.md` lockstep). Keep the capability set + prompt in lockstep
  when the satellite gains open Q&A.

## 10. Open questions / validation (before build)

- `TODO:` **Spike 1 (go/no-go):** in the reSpeaker firmware, can local TTS playback be **suppressed** while
  `on_tts_end` still delivers the URI (keeping wake/feedback sounds local)? If clean suppression proves
  impractical, fall back to **muting the satellite `media_player` during `responding`** (racy) or reconsider B.
- `TODO:` **Spike 2:** the resolver **announce of the URI** overlays + auto-resumes on the ceiling MA player
  (does not replace the stream), and composes with the S1a duck (reply audible over the floor; restore only
  after the announce completes).
- `TODO:` **ChatGPT prefer-local**: verify device/media commands stay **deterministic** (not LLM-paraphrased or
  dropped) and the exposed tools still fire — the NL-01/NL-02 concern; keep `assistant-capabilities.md` in lockstep.
- `TODO:` **Latency / cost:** LLM round-trip + URI relay hop acceptable for spoken replies; per-query LLM cost.
- `TODO:` **Wake-slot choice:** primary wake → this pipeline, or the 2nd on-device wake-word slot (S0 dual-slot
  note) so the local-only pipeline stays available. Decide at plan time.

---

> **Rollback for this document:** `git revert` on `homebrain/s1b-satellite-ceiling-reply`, or delete this file.
> No secrets, no implementation, no firmware/exposure change, no live gate.
