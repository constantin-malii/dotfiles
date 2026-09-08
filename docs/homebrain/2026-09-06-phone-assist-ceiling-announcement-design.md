# AN-01 — Phone Assist → Ceiling-Speaker Announcement (design)

> **Design / documentation only. No implementation, no live change, no spike executed.**
> ⚠ **AMENDED 2026-09-07 by [`2026-09-07-an-01-post-g1-design-corrections.md`](./2026-09-07-an-01-post-g1-design-corrections.md)** — G1's spikes contradicted **§8.2**'s match-key rule
> and exposed two security/classification gaps (§6.1's no-logging rule is incompletely applied, and
> the chime is unclassified by §8.2's reply/source logic). Those sections are **left as written** on
> purpose — they record what was believed at G0 — so **read the correction alongside them.**
>
> **Status:** **rev 5 — G0 APPROVED** (2026-09-06). The next authorised phase is an **implementation
> plan only**. Nothing in this document has been built or deployed; nothing here modifies resolver
> code, resolver tests, live Home Assistant, automations, or services. G1's spikes remain unexecuted
> and operator-gated.
>
> Editorial errata applied at approval: the §6.5 table's *Ceiling* column renamed **Nominal
> allowance**; a stale "the bound's job is to be true" sentence deleted; "§6.5 enforceability
> requirement" reworded to "timeout-clipping requirement"; and both dead-man durations (§9.5, §9.7)
> now state explicitly that they are **policy cutoffs derived from an engineered budget, not
> wall-clock bounds** — recording the liveness-over-waiting trade-off.
>
> **Rev 5 (fourth review round).** Three issues plus two cleanups found in rev 4 and fixed here:
> 1. **The timing numbers are no longer described as a bound.** A socket `timeout=` is a
>    **per-operation inactivity timeout**, not a wall-clock deadline for a request: connect, send,
>    headers, body, WS auth, frames and pings each get their own allowance, and that applies to the
>    TTS and service-call rows too, not just the five poll reads. The 500 ms floor also bounds nothing
>    about scheduling jitter. §6.5 now presents **190 s as the engineered phase budget** and
>    **200 s as the configured operational timeout, validated empirically at G3**. The words
>    "enforceable", "hard bound" and "ceiling" are gone. Clipping and the two `timeout` parameters
>    stay in G2 — they reduce overshoot and `resolve_media_source` cannot be bounded at all without
>    them — but end-to-end transport deadlines are explicitly **not** proposed.
> 2. **The replay rule contradicted a retained test and failure row.** Because
>    `queue_may_be_replaced` is claimed *before* every `play_media`, any raising play leaves it set —
>    so "no play was ever issued" can only mean the turn died **before reaching a `play_media`**
>    (e.g. the step-4 `volume_set`). Row 15a and the no-replay test are reframed accordingly, and a
>    contrast test pins that a raising first play takes the ambiguous replay path.
> 3. **An async dead-man cannot retroactively report `"failed"`.** Once `/command` has answered with
>    `"deferred_to_deadman"`, the phone's response is already serialised. `metadata.volume_restore`
>    now carries only `"restored"` or `"deferred_to_deadman"`; **terminal exhaustion is log-only** at
>    `error`. Rev 4 stated the timing correctly in prose and then contradicted it in failure row 18
>    and the metadata test.
>
> Cleanups: microphone behaviour removed from the `_say`-level clip-outcome table (it depends on
> *who* superseded, which is §9.4/§9.6's business, not `_say`'s); and goal 7 restated as **unchanged
> public contract and success-path call sequence, with §8.3a's safer ambiguous-failure recovery as a
> documented exception** — matching §15 item 4.
>
> **Rev 4 (third review round).** Four issues plus three cleanups found in rev 3 and fixed then:
> 1. **Generation timing contradicted the sequence.** §7 resolves TTS and chime at C/D *before* the
>    claim at E, but §9.2 described those resolutions as inside the adoption window, and two tests
>    bumped `_say_gen` during resolution — before the claim existed, so they could not exercise stale
>    adoption at all. The C/D-before-E ordering is **kept**; the window is corrected to steps F–G
>    (mic capture, write, confirm ≈ **17 s**), and those two tests are replaced with ones matching the
>    real chronology, plus a guard test pinning that resolution precedes the claim. The atomic
>    adoption check and the mic-confirmation race test are retained.
> 2. **187 s was not a bound.** An absolute deadline stops the next iteration, not the one in
>    flight: a `get_entity_state` begun just before expiry still blocks its fixed 10 s
>    (`haconn.py:47`), across the mic confirmation and all four clip polls; and
>    `resolve_media_source`'s 10 s cannot hold while `wsutil.ws_connect` hardcodes 15 s
>    (`wsutil.py:7`). §6.5 now clips every blocking call to the remaining deadline behind a 500 ms
>    floor, adds `timeout` parameters to `get_entity_state` and `ws_connect` as **explicit G2 scope**,
>    and quotes **190 s** (187 s budgeted + 3 s start-of-call slack) instead of a "hard" 187 s.
>    *(Rev 5 downgrades this further — see rev 5 item 1.)*
> 3. **`queue_replaced` still mishandled lost acks** — it was set only after `play_media` returned, so
>    a landed-but-unacknowledged play left the flag false and row 15a would "un-pause" a queue that
>    may already hold the announcement clip. Replaced by **`queue_may_be_replaced`, claimed before
>    every play**; the un-pause is re-gated on it, with an un-pause fallback when there is nothing to
>    replay. Lost-ack tests added for both the chime and the message-only shapes.
> 4. **No volume dead-man existed for an unducked announcement.** Row 18 claimed reconciliation that
>    §8.4(c) had already shown impossible. New **§9.7** adds an announcement-owned volume recovery
>    timer with bounded retries, **and** weakens the invariant honestly: if the success path, the
>    finalizer retry and the dead-man all fail — or the process dies — the ceiling can be left at
>    announce volume. Returned metadata reports `"restored"` or `"deferred_to_deadman"`; terminal
>    exhaustion is **log-only** at `error`, since it occurs after `/command` has answered.
>    *(Rev 5 corrects rev 4's impossible `"failed"` metadata value — see rev 5 item 3.)*
>
> Cleanups: failure row 20 split into **20** (newer announcement — no unmute) and **20a**
> (non-announcement — mic **is** unmuted), matching §9.6; the mic dead-man test renamed from 145 s to
> **≈185 s**; and §8.4's "three latent defects / both" framing corrected to two introduced plus one
> pre-existing-but-exposed.
>
> **Rev 3 (second review round).** Six implementation-significant issues found in rev 2 and fixed then:
> 1. **Stale pre-claimed generation race** — a gen claimed at step E is stale by `_say`'s step 2, and
>    an unvalidated adoption lets a stale announcement overwrite a **newer** turn's ownership marker.
>    §9.2 now revalidates inside the same critical section that publishes `_replies`, aborting before
>    publishing; tests cover supersession during TTS resolution, chime resolution and mic confirmation.
> 2. **Fatal second-clip failure lost the source** — the chime replaces the queue, the message raises,
>    and the finalizer had no replay (the un-pause is gated on `not play_issued`, which the chime
>    falsifies). New §8.3a claims a `queue_may_be_replaced` obligation before each play and best-effort replays
>    unless superseded.
> 3. **The 150 s budget was not a bound** — it omitted both resolutions, all service-call and
>    state-read time, and the mic reads, and rested on accumulated-sleep polls. §6.5 is rebuilt:
>    announcement clips poll against **wall-clock deadlines**, all 16 phases are budgeted, the hard
>    bound is **187 s**, and `rest_command` needs **200 s**. `budget_s` is split into
>    `marker_budget_s` (≈145 s) and the turn bound, resolving the rev-2 70-vs-145 contradiction.
> 4. **A lost ack on the volume raise stranded the ceiling at 0.80** — `interaction.py:640-642` sets
>    `pending_restore` *after* the write, and an announcement has **no duck snapshot and therefore no
>    dead-man** (§3.5). §8.4(c) claims the restore obligation before issuing the write.
> 5. **G1b's exit criterion was unachievable read-only** — split into G1b (inspect and decide) and a
>    new **G4a** write gate with backup and rollback.
> 6. **The length bound excluded the configurable prefix** — `announce_max_chars` now bounds the
>    **rendered** `prefix + message`, with `announce_max_prefix_chars` so a misconfigured prefix
>    degrades instead of disabling announcements.
>
> Cleanup: the component table no longer calls result delivery optional, and the diagram, §5 and §15
> name the announcement-specific rest_command.
>
> **Rev 2 (first review round).** Seven defects found in rev 1 and fixed then:
> 1. **Mic ownership was reasoned backwards.** A satellite reply bumps `_say_gen` but never writes
>    `_mic`, so §9.4's own rule already unmutes immediately. The claimed multi-minute deaf period and
>    its "accepted trade-off" are **withdrawn** (§9.4, §9.6, D10), and pinned by new
>    non-announcement-supersession regression tests.
> 2. **The blocking `rest_command` timeout was unaddressed** — a real live failure
>    (`CHANGELOG.md:1328`), and rev 1's 370 s theoretical budget made it worse. New §6.5 derives every
>    budget from the bounded message size and states the required HA timeout and how a timeout reaches
>    the phone.
> 3. **`precondition_failed` is not a valid error code** — `command_result.py:2` would raise
>    `ValueError`. Now `unavailable`, with a test enumerating the codes used.
> 4. **Honest failures were being discarded.** New §5.2: the automation captures `response_variable`
>    and relays `chat_text` via `set_conversation_response`.
> 5. **"Phone-only" was not enforceable** and is no longer claimed (§5.1, §2, D12, SPIKE-AN-3).
> 6. **A successful `switch.turn_on` is not a muted microphone** — §9.3 now writes *then confirms by
>    reading*, which is what makes requirement 7 a real fail-safe (and raises D14).
> 7. **Truncation contradicted "verbatim"** — over-long messages are now **rejected** with the limit
>    stated (§7 step B, §10 row 2).
>
> Rev 1's signed-media-URL approach, graceful chime degradation, backward-compatible clip helper, and
> golden `say`/`say_text` regression tests were reviewed as sound and are unchanged.
>
> **Item code:** `AN-01`. This is the *announce delivery surface* leg of the `S1b`–`S4` chain in
> `BACKLOG.md` (the row reading "reply-on-ceiling relay (`S1b`) → `ResponseRoutingPolicy` → privacy
> gating → household announce/targeting"). It deliberately does **not** take the `S4`
> multi-zone/targeting leg — see §2.
>
> **Builds on (all live and proven):** AU-02/AU-03 duck/restore, S1b-2 `say` reply route, and
> `interaction` mode `say_text` (deployed 2026-09-05), which the
> `satellite_timer_announce_on_ceiling` automation already drives in production.
>
> **Reads as prerequisites:** `ONBOARDING.md` §1/§4/§5/§6, `CHANGELOG.md` 2026-09-05 and 2026-09-06,
> `2026-07-15-s1b-duck-ownership-adr.md`, `2026-07-15-s1b-satellite-ceiling-reply-design.md` §13.

---

## 1. Goals

1. From the **phone Home Assistant Companion app**, the operator says *"announce dinner is ready"* or
   *"broadcast the car is blocked in"*, and that sentence is spoken on the **ceiling speakers**.
2. It is an **explicit command**: it broadcasts immediately. No confirmation dialogue, no
   "are you sure", no second turn.
3. The message text is carried **verbatim** from STT to speech. No LLM is in the path, no model gets
   an opportunity to paraphrase, re-route or drop it, and **the resolver never silently alters it
   either** — an over-long message is rejected with its limit stated, not truncated (§7 step B).
4. An announcement is **attention-getting**: a chime precedes it, and it plays **louder** than an
   ordinary assistant reply (`0.80` vs the current `reply_volume` of `0.70`).
5. It **reuses the entire proven reply route** — internal-base URL normalisation, reply-volume
   handling, start/finish polling, volume restore, source replay, barge-in supersession, honest
   failure reporting, and `skip_on_fresh_playback=False` semantics. None of that sequencing is
   reproduced in Home Assistant.
6. The announcement **does not wake the satellite and get heard as a command**. The satellite
   microphone is muted for the duration and restored afterwards, on every exit path.
7. Existing `interaction` modes **`say` and `say_text` keep their public contract and their
   success-path call sequence exactly** — proven by a golden call-sequence regression test, not by
   inspection. **One documented exception:** their *ambiguous-failure* recovery changes, because
   §8.3a's lost-acknowledgement fix applies to shared `_say` code — a `play_media` that raises now
   replays the captured source instead of un-pausing a queue that may already have been replaced.
   That is strictly safer, it is the only behavioural change reaching replies, and it has its own
   test rather than being covered by the golden ones.

## 2. Explicit non-goals

| Not doing | Why / where it lives |
|---|---|
| **Multi-zone or targeted announcements** ("announce in the kitchen") | The ceiling is the only working zone (`ONBOARDING.md` §4: the Squeezelite child is not an HA entity and cannot be played to directly). Targeting is the `S4` leg of the backlog chain. |
| **Recorded-voice intercom** (play the operator's actual voice) | Needs audio capture, upload and hosting; `say_text`'s TTS resolution does not apply. Separate feature. |
| **An LLM-exposed `script.announce` tool** | Rejected in brainstorming. `CHANGELOG.md` 2026-09-06 records the model mis-routing parameters even after its tool schema was corrected; the decisive fix there was taking the model out of the loop. The same reasoning applies with more force here, because the payload is free text. |
| **Reviving `tts.speak` / `music_assistant.play_announcement`** | Both are proven broken on this Universal→Squeezelite player (`ONBOARDING.md` §5; S1b design §13). Not revisited. |
| **Unifying the Piper voice** | Known gap, `CHANGELOG.md` 2026-09-05 "Proposed BACKLOG notes" #1. An announcement will inherit Piper's default voice like every other `say_text` clip. Out of scope; tracked in §14. |
| **Saying *who* announced, or an announcement history surface** | No requirement. Would need a caller identity the sentence trigger does not carry. |
| **Satellite-initiated announcements** ("okay nabu, announce…") | *Preferred* excluded, **not claimed as enforced** — see §5.1. A sentence trigger participates in Assist generally, so the satellite pipelines reach it too whenever local handling is on. Gating depends on a dependable source identifier that current trigger documentation does not establish (D12), so it is a live-discovery item, not a design guarantee. If no gate is available, satellite invocation is accepted and documented rather than falsely excluded. |
| **Repeat-until-acknowledged** (as the timer announcement does) | An announcement is one-shot. The timer loop exists because a timer must not be missed; a person speaking into their phone can repeat themselves. |
| **Fixing the satellite false-wake problem generally** | `ONBOARDING.md` §6 / `CHANGELOG.md` 2026-09-05. AN-01 mutes the mic for its own clips; it does not address ambient false wakes. |

---

## 3. Current-state evidence

Everything in this section is quoted from the repo, not assumed.

### 3.1 The audible route exists and is proven

- `interaction.py:478` `_say_text` — text → `ctx.ha.tts_get_url(engine, text)` → clip URL → `_say`.
  It sets `resolved["skip_on_fresh_playback"] = False`, with the comment that a pushed sentence
  "is NOT confirmed by unrelated playback starting in the same turn, so it must not inherit `_say`'s
  media-confirmation skip". That is already announcement semantics.
- `haconn.py` `tts_get_url()` posts to `/api/tts_get_url`, and requires a non-empty **absolute**
  URL, raising otherwise.
- `CHANGELOG.md` 2026-09-05 records `say_text` as **VERIFIED live, voice-initiated, operator-eared**:
  `15:06:57 SAY_TEXT req=36ac6346 engine=tts.piper chars=23` → `finish-poll exit after 2.0s` →
  `restored -> 0.36`, `reply_started=True`.

**Corrections to earlier analysis, carried into this design:** `say_text` is deployed and proven — it
is not a candidate route. `reply_volume` is **`0.70`** in `config.json`; the `config.py` default of
`0.40` and `FakeSettings`' `0.40` are both stale relative to the deployed file.

### 3.2 The chime is the only genuinely unproven piece

`CHANGELOG.md:671-677` already diagnosed this, and that diagnosis is why the chime is designed as a
`haconn` addition rather than a config string:

- MA **rejects** `media-source://` URIs: `HomeAssistantError: Only URLs are supported for
  announcements`.
- MA **cannot fetch** HA's media files, which need auth: `/media/local/... -> 401`;
  `/local/... -> 404`, nothing in `/config/www`, and there is no VM shell to place a file.
- A 4-second two-note bell WAV **exists** at
  `media-source://media_source/local/./timer_chime.wav` and is "waiting".
- The recorded next step is verbatim: *"have the resolver resolve the media-source URI to a signed
  URL via HA and play it through the existing `_say` — same shape and size as the `say_text`
  change."* The alternative (serving the file from the resolver's own HTTP server) was judged to add
  "surface for no real gain".

This design adopts that recorded next step. **What remains unproven is whether MA will fetch and play
the signed URL** — that is the whole content of the spike in §12.

### 3.3 Ceiling audio already wakes the satellite

This is why microphone muting is a reliability requirement and not decoration:

- `CHANGELOG.md:651-657` — the timer announcement played on the ceiling was transcribed back as
  *"The pipeline is finished."* / *"The point is finished."* (pipeline traces, 21:05 and 21:14), and
  the resulting self-wake **sustained the announcement loop** until the fix required
  `assist_satellite` idle in the `while` condition.
- `CHANGELOG.md` 2026-09-05 "Proposed BACKLOG notes" #2 — "Ceiling audio can wake the satellite …
  it applies to **replies**, not just timers."
- `ONBOARDING.md` §6 — slot 2 ("Hey Mycroft") carries **web search** and no tools, so room audio
  reaching it "can leave the house". An announcement is louder and longer than a timer chime, so it
  is a stronger self-wake stimulus than anything measured so far.

### 3.4 A mute switch exists, with a placeholder ID

`s0-satellite-inventory.md:64-65` lists, under **Controls / feedback**:
`switch.…_wake_sound` (on) · `switch.…_mute_unmute_sound` (on) · `switch.…_beam_lock` (off) ·
**`switch.…_microphone_mute` (off)**.

The `…` is a documentation placeholder, not a real entity ID. The exact ID and — more importantly —
**whether that switch suppresses wake-word detection or merely mutes an audio stream** are deployment
discoveries (§14, D1/D2), gated by the spike.

Note also that `switch.…_mute_unmute_sound` is **on**, so flipping mute may play a feedback sound on
a satellite that `ONBOARDING.md` §1 records as having **no built-in speaker**. Expected to be
inaudible; listed as D6.

### 3.5 Phone callers create no duck markers

Stated in the task brief and confirmed by the code:

- `interaction.py` `note_playback()` and `note_stopped()` both return early when `self._turns` has no
  entry for the zone, with the comment that the call "came from a non-satellite caller (phone,
  ChatGPT text)" and that inventing a turn "would suppress that caller's announce for the whole turn
  window and skip a later satellite reply".
- Consequences for AN-01, all benign and relied upon:
  - `self._snaps[zone]` is empty → `_reply_baseline()` falls through to `fallback`, i.e. the live
    volume captured at `_say` step 1. Correct: there is no duck to undo, only a baseline to return
    to.
  - `interaction_in_flight()` returns `False` → `core.dispatch`'s
    `suppress_announce_during_interaction` does not engage. Harmless, because `_say` returns
    `spoken_text=None`, so there is no second voice to suppress.
  - `_turn_stopped()` is `False` and `turn["playback"]` is absent, so neither the stop-replay skip
    nor the fresh-playback skip can fire. The explicit `skip_on_fresh_playback=False` remains
    belt-and-braces for an announcement landing during a satellite turn.

### 3.6 `BACKLOG.md` is stale on this point

`BACKLOG.md:185` still says reply-on-ceiling is **blocked** on "an audible-announce fix", and
`BACKLOG.md:306` records the `host-live / HA-live / exposure` lane as **FREE** with the note "Spike-2
not passed — `play_announcement` silent on the ceiling".

Both were written **2026-07-16**, before the 2026-09-05 `say_text` work solved the audible-announce
problem by abandoning the announce/overlay path entirely.

**How this design reconciles it (§13.2):** by *appending* a dated reconciliation note and a new
`AN-01` row, never by rewriting the 2026-07-16 wording. Those lines are an accurate record of what
was known then, and this stack's own lesson (`CHANGELOG.md` 2026-09-06: a mitigation "measured to do
nothing should have been reverted then, not left in place") is about acting on new evidence, not
about erasing old evidence.

---

## 4. Architecture and component boundaries

```
┌─ phone ─────────┐   ┌─ Home Assistant (VM, 192.168.1.104) ──────────────┐   ┌─ host ─────────┐
│ Companion app   │   │                                                   │   │                │
│  Assist mic     │──▶│ STT (faster-whisper)                              │   │                │
└─────────────────┘   │   │                                               │   │                │
                      │   ▼  prefer_local_intents                         │   │                │
                      │ automation.voice_ceiling_speakers                 │   │                │
                      │   conversation trigger:                           │   │                │
                      │     "announce {message}"                          │   │                │
                      │     "broadcast {message}"                         │   │                │
                      │   │                                               │   │                │
                      │   ▼  rest_command.resolver_command_announce      │   │                │
                      │      X-Resolver-Key ────────────────────────────▶ │──▶│ mass-resolver  │
                      │                                                   │   │  /command      │
                      │ ◀── /api/tts_get_url ──────────────────────────── │◀──│  intent=       │
                      │ ◀── ws media_source/resolve_media ─────────────── │◀──│  interaction   │
                      │ ◀── switch.turn_on/off (mic mute) ─────────────── │◀──│  mode=announce │
                      │ ◀── media_player.volume_set / media_pause ─────── │◀──│                │
                      │ ◀── music_assistant.play_media (chime, tts, src) ─│◀──│  Interaction   │
                      │ ◀── GET /api/states (polling) ─────────────────── │◀──│  Capability    │
                      └───────────────────────────────────────────────────┘   └────────────────┘
                                            │ SlimProto/HTTP over NAT
                                            ▼
                                   Squeezelite → ceiling speakers
```

### Component responsibilities

| Component | Owns | Explicitly does **not** own |
|---|---|---|
| **Phone Assist + STT** | Capturing the sentence. | Anything downstream. |
| **`automation.voice_ceiling_speakers`** (live HA) | Matching the two sentences, extracting `{message}`, one `rest_command` call, and **relaying the result as a text-only conversation response — mandatory, not optional** (§5.2). Plus the §5.1 source condition if D12 permits one. | Volume, muting, chimes, sequencing, retries, TTS. It is a dumb trigger by design — see §5 and the `ONBOARDING.md` §4 warning about two paths drifting out of step. |
| **`http_server` + `core.dispatch`** | Auth, request id, routing `intent=interaction`. | Unchanged by AN-01. |
| **`InteractionCapability._announce`** (new) | Announcement *policy*: resolve both clips, claim the turn generation, own the microphone, build the clip list, map `_say`'s outcome onto announcement-grade honesty. | Volume, polling, restore, replay, supersession *mechanics* — all delegated to `_say`. |
| **`InteractionCapability._say`** (refactored, same external contract) | Turn ownership, baseline capture, one volume raise, the clip loop, one restore, one replay, release. | Knowing what a chime is, or that a microphone exists. |
| **`_play_clip_and_wait`** (new, extracted) | One clip: play → start-poll → finish-poll → report. | Volume, baseline, restore, replay, mic, generation bookkeeping. |
| **`haconn.resolve_media_source`** (new) | Turning a `media-source://` URI into an absolute, MA-fetchable URL. | Playing anything. |

The boundary that matters: **`_say` gains a clip *loop* and gains nothing else.** The microphone lives
entirely in `_announce`, and so does the chime concept. `_say` cannot tell an announcement from a
two-clip reply.

---

## 5. Data flow, end to end

1. **Operator** (phone Companion app, Assist): *"announce dinner is ready"*.
2. **STT** transcribes. With `prefer_local_intents` on, HA tries local intents and sentence triggers
   before any conversation agent.
3. **`automation.voice_ceiling_speakers`** matches the `conversation` trigger sentence
   `announce {message}` and binds `message = "dinner is ready"`.
   - The trailing wildcard is greedy: it captures the remainder of the sentence.
   - HA normalises trigger text (lower-casing, punctuation stripping), so the resolver receives
     `dinner is ready`, not `Dinner is ready.` See D7.
4. The automation calls the announcement rest_command — **preferably a dedicated
   `rest_command.resolver_command_announce`** carrying §6.5's 200 s timeout, using the same
   authenticated `X-Resolver-Key` shape as the `rest_command.resolver_command` that `script.play_radio`
   and the timer-announce automation already use — with `intent: interaction` and
   `params: {mode: announce, text: "{{ trigger.slots.message }}"}`, and **captures the result**
   (§5.2). Which of the two shapes ships is G1b's decision (D13); a dedicated command is preferred so
   no existing caller inherits a 200 s timeout.
   - **No confirmation *dialogue*.** A one-turn text result is not a dialogue: nothing is asked of
     the operator and no second turn happens. What is forbidden is a *spoken* confirmation on the
     ceiling, for the reason recorded in `ONBOARDING.md` §5 — it would be a second clip fighting the
     announcement it confirms.
5. **`core.dispatch`** routes `intent=interaction` to the singleton `InteractionCapability`
   (`core.py:9` `CAPS`) — a singleton precisely because it holds per-zone state.
6. **`resolve()`** returns `{mode: "announce", zone: <ceiling>, text: "dinner is ready", …}`.
   **`validate()`** rejects empty text before any I/O.
7. **`_announce()`** runs the ordered sequence in §7.
8. **`_say()`** performs one baseline capture, one volume raise to `announce_volume`, the clip loop
   (chime, then message), one restore, one replay, one release.
9. **Ceiling speakers**: chime, then the sentence, then the previous station or track resumes at the
   volume it was at before.
10. `_announce()`'s `finally` restores the microphone to its captured prior state.

### Golden call order (ceiling playing at `0.36`, source `S`, chime resolvable)

| # | Call | Issued by |
|---|---|---|
| 1 | `GET /api/states/<mute switch>` (capture `prev`) | `_announce` |
| 2 | `switch.turn_on` (mic mute) | `_announce` — **before any audio** |
| 3 | `GET /api/states/<mute switch>` → **must report `on`** | `_announce` — the confirm poll (§9.3) |
| 4 | `media_player.media_pause` | `_say` step 4, only when `was_playing` and `say_pause_before_reply` |
| 5 | `media_player.volume_set 0.80` | `_say` step 4, **once** |
| 6 | `music_assistant.play_media <chime>` | clip loop, iteration 1 |
| 7 | `music_assistant.play_media <tts>` | clip loop, iteration 2 |
| 8 | `media_player.volume_set 0.36` | `_say` step 8, **once** |
| 9 | `music_assistant.play_media S` | `_say` step 9, **once** |
| 10 | `switch.turn_off` (mic restore) | `_announce` `finally` |

Interleaved *clip* polls (`GET /api/states/media_player.ceiling_speakers`) are omitted; the two mute
reads are shown because they are load-bearing, not incidental. This table is the assertion target of
the primary unit test (§11.4).

**Accepted trade-off on step 10's position.** Unmuting in `_announce`'s `finally` leaves the microphone
muted across the restore and replay calls — roughly one to two seconds longer than strictly
necessary. The alternative, handing `_say` an end-of-last-clip callback, couples the microphone into
`_say` and violates §4's boundary. The simpler ordering is chosen; the cost is a ~1–2 s window in
which the satellite is deaf, immediately after an announcement nobody is talking over.

### 5.1 Source gating — preferred, not guaranteed

A `conversation` sentence trigger is **not phone-specific**. It participates in Assist generally, so
any pipeline with local handling enabled reaches it — including the two satellite pipelines, both of
which run with `prefer_local` on for slot 1 (`ONBOARDING.md` §1/§4). The earlier "phone-only by
design" claim was wrong and has been removed from §2.

*Preferred behaviour:* a condition on the trigger's source identifier so the automation only proceeds
for the phone. HA exposes trigger template data (`trigger.sentence`, `trigger.slots`,
`trigger.details`, `trigger.device_id`, and on newer cores `trigger.satellite_id`), but **current
official documentation does not establish a dependable phone identifier** — `device_id` is documented
as possibly absent depending on the source. So the identifier and its reliability are a live
discovery (**D12**), resolved at SPIKE-AN-3 and applied at G4b, not an assumption here.

*Why gating is preferred rather than cosmetic.* Satellite invocation is not merely redundant. A
satellite turn **does** create duck markers, so `self._turns[zone]` exists, `interaction_in_flight()`
returns true, and the satellite's own pipeline reply competes with the announcement for the zone —
the exact contention §3.5 relies on being absent. And requirement 6 becomes self-referential: the
announcement would mute the microphone of the satellite that just invoked it, mid-turn.

*If D12 finds no dependable identifier:* satellite invocation is **accepted and documented**, the
`trigger.slots.message` path is unchanged, and §9.6 already describes the resulting supersession
correctly. What this design will not do is claim an exclusion it cannot enforce.

### 5.2 Result relay — how a failure reaches the phone

Honest failure reporting is worthless if the result is discarded. The automation therefore captures
it:

1. The announcement rest_command (§5 step 4) with **`response_variable: r`** and
   **`continue_on_error: true`**.
   The `continue_on_error` is what makes a timeout observable rather than fatal — without it the
   automation aborts and sets no response at all, which is exactly how `CHANGELOG.md:1328` describes
   the current satellite reply automation failing quietly.
2. A `choose` on the outcome, each branch ending in `set_conversation_response`:
   - `r` undefined, or no `content` → the rest_command failed or **timed out**:
     *"I couldn't reach the announcer."* (§6.5 sizes the timeout so this is rare.)
   - `r.content.ok` false → **`r.content.chat_text` verbatim**. That is where "I can't announce
     without muting the microphone.", "That message is too long…" and "I couldn't play the
     announcement." surface.
   - `r.content.ok` true → `r.content.chat_text`, which `_announce` sets to **"Announced."**
3. `set_conversation_response` is the right mechanism here and the `ONBOARDING.md` §4 warning does
   **not** apply: that warning is about `set_conversation_response` being *"proven ignored by the
   OpenAI agent for tool-called scripts"*. This is a conversation-trigger automation returning a
   response to Assist directly, with no agent in the path — the same path that already gives the
   phone the text replies recorded in `ONBOARDING.md` §5.

`_announce` therefore owes every exit path a **useful `chat_text`**, not `_say`'s generic `"Said."`.
That is a requirement on the capability, listed in §10's result column.

---

## 6. Proposed interfaces and configuration

### 6.1 `haconn.HA.resolve_media_source(uri, timeout=10)` — new

> ⚠ **INCOMPLETE — see [`2026-09-07-an-01-post-g1-design-corrections.md`](./2026-09-07-an-01-post-g1-design-corrections.md) correction 2.** The never-log-the-URL rule below is right but
> was applied only to the resolved URL. The signature **also travels inside the
> `media_content_id` HA reports back**, which `_say` reads on every poll and logs as `cid[:60]` —
> a truncation that happens to stop short of `authSig` for the measured URL, and would not for a
> shorter host or path. An explicit redaction helper is required on every cid-touching log line.

```
Turn a media-source:// URI into an absolute, MA-fetchable URL.

Why: MA rejects media-source:// outright ("Only URLs are supported for announcements") and cannot
fetch HA's authenticated /media/local/... paths (401). HA's own resolver hands back a SIGNED path
that carries its authorisation in the query string, which is the only form MA can fetch.
```

- **Transport: a fresh, short-lived WebSocket per call.** `media_source/resolve_media` has no REST
  equivalent, and `haconn`'s `self.s` is the shared `subscribe_events` socket. `get_entity_state`'s
  docstring already states the rule — a fresh per-call connection, "so it never interleaves with the
  `subscribe_events` read loop and is safe to call from the HTTP server thread". This helper follows
  the same discipline using `wsutil.ws_connect` / `ws_send` / `ws_read`, then closes.
- Sends `{"id": 1, "type": "media_source/resolve_media", "media_content_id": <uri>}` after the
  standard `auth_required` → `auth` → `auth_ok` handshake.
- Reads `result.url`. HA typically returns a **relative** signed path
  (`/media/local/timer_chime.wav?authSig=…`), so the helper **absolutises it against its own
  `self.host:self.port`** — which is already the MA-reachable NAT base taken from `ha_url`.
- Mirrors `tts_get_url`'s guards: raise on a missing url; raise if the result is still not
  `http`-prefixed after absolutisation. Both exist because, per `tts_get_url`'s own comment, a
  malformed URL surfaces "only as a start-poll timeout, far from its cause".
- **Never logs the URL.** A signed URL is a bearer credential. Logging uses `_clip_id`'s SHA1
  fingerprint, exactly as reply clips already do ("reply URLs are unauthenticated-but-obscure
  `tts_proxy` links — never log them verbatim").
- **Resolved per announcement, never cached.** The signature has a finite lifetime (D3).

### 6.2 New settings (`config.py` defaults / `config.json`)

| Setting | Default | Purpose |
|---|---|---|
| `announce_volume` | `0.80` | Ceiling volume for an announcement turn. Louder than `reply_volume` (`0.70`). |
| `announce_prefix` | `""` | Optional spoken prefix prepended to the message before TTS resolution. **Empty by default: the chime is the attention signal.** Bounded by `announce_max_prefix_chars` — it is synthesised into the same clip, so an unbounded prefix would invalidate §6.5's timing model from config alone. |
| `announce_volume_deadman_ms` | `0` (derive) | Failsafe volume-restore timer for an **unducked** turn, which has no duck snapshot and therefore no `max_duck_timeout` (§9.7). `0` derives `marker_budget_s + 30 s` ≈ 175 s. |
| `announce_volume_deadman_retries` | `3` | Bounded re-arms on a failed recovery write, then an `error` and stop. `_auto_restore` re-arms indefinitely; a one-shot announcement should not. |
| `announce_min_call_timeout_ms` | `500` | Floor for a deadline-clipped blocking call (§6.5). A call with less than this left on the deadline is **not started**; the phase ends instead. |
| `announce_max_prefix_chars` | `40` | Hard cap on the prefix. Over-long → the prefix is **dropped** with an `error` log, and the announcement proceeds. Degrading here rather than refusing is deliberate: a misconfigured prefix must not silently disable every announcement in the house. |
| `announce_chime_uri` | `"media-source://media_source/local/timer_chime.wav"` | The existing asset. Set to `""` to disable the chime entirely. **CORRECTED 2026-09-07:** this default previously carried a `./` segment, which yields a signature HA cannot validate against its own returned URL — see the post-G1 corrections. Never reintroduce `./`. |
| `announce_mic_mute_entity` | `""` | The satellite mic-mute switch. **Empty until the spike establishes the real ID** (D1). |
| `announce_require_mic_mute` | `true` | When true, an announcement that cannot establish muting **fails and does not broadcast** (requirement 7). Set false only to deliberately accept self-wake. |
| `announce_mic_confirm_timeout_ms` | `2000` | How long to poll the mute switch for `on` after writing it. A successful `switch.turn_on` call is an *accepted request*, not a muted microphone (§9.3). |
| `announce_mic_confirm_poll_ms` | `250` | Poll interval for that confirmation. Replaces the blind settle delay of an earlier draft — a read that proves the state is strictly better than a sleep that hopes for it. |
| `announce_mic_deadman_ms` | `0` (derive) | Failsafe unmute timer. `0` derives it from the turn's real clip budget (§6.5/§9.5). |
| `announce_chime_finish_timeout_ms` | `15000` | Finish-poll budget for the 4-second chime. Not the 180 s reply budget (§6.5). |
| `announce_message_finish_timeout_ms` | `45000` | Finish-poll budget for a message bounded by `announce_max_chars` (§6.5). |
| `announce_max_chars` | `300` | Hard upper bound on the **final rendered TTS text** — `prefix + message`, not the message alone. Over-long messages are **rejected**, never truncated (§7 step B). This is the single number §6.5's whole timing model rests on, so nothing that reaches Piper may escape it. |

Two notes on the existing surface:

- **`config.py`'s `reply_volume` default of `0.40` is stale** — the deployed `config.json` says
  `0.70`. AN-01 changes neither, and a plan touching this file should not "helpfully" reconcile the
  default: `config.json` wins at runtime, and changing the fallback changes behaviour on a machine
  with no config file.
- **Naming collision, deliberate but hazardous.** The new mode is `announce`. Already present are
  `haconn.announce()` (the **broken** `tts.speak` path), `settings.announce_failures`, and
  `settings.suppress_announce_during_interaction`. The mode name was approved and is kept, but every
  doc and log line must be unambiguous: **mode `announce` never touches `haconn.announce()`**. The
  existing `SayTextTest.test_it_never_uses_the_broken_announce_path` gets a sibling for `announce`.

### 6.3 Mode surface

- `interaction.py` `_MODES` gains `"announce"`.
- `resolve()` needs no change — it already carries `text`.
- `validate()` gains: `announce` with no `text` → `invalid_input` / "Nothing to announce."
- Request shape:
  `{"intent": "interaction", "params": {"mode": "announce", "text": "...", "zone": "<optional>"}}`.

### 6.4 Internal keys on `resolved` (not public API)

| Key | Set by | Consumed by | Purpose |
|---|---|---|---|
| `uris` | `_announce` | `_say` | Ordered clip list. Absent for `say`/`say_text`. |
| `match_keys` | `_announce` | `_say` | Per-clip containment key for `media_content_id` matching (§8.2). |
| `volume_override` | `_announce` | `_say` | `announce_volume`. Absent → `settings.reply_volume`. |
| `gen` | `_announce` | `_say` | Pre-claimed turn generation (§9.2). Absent → `_say` claims its own. |
| `finish_timeouts` | `_announce` | `_say` | Per-clip finish-poll budget in seconds. Absent → `settings.say_reply_timeout_ms` for every clip (§6.5). |
| `skip_on_fresh_playback` | `_say_text`, `_announce` | `_say` | Existing key; `False` for pushed audio. |

All six are optional. Absent, `_say` behaves exactly as it does today.

### 6.5 Timeout budget — the blocking `rest_command` is the constraint

`/command` is **synchronous**: HA's `rest_command` blocks for the whole of `_say`. This is already a
known live failure, not a hypothetical — `CHANGELOG.md:1328` records *"The occasional `interaction …
timed out` is the HA `rest_command` timeout on a blocking long `_say`, absorbed by
`continue_on_error: true`."* A two-clip announcement makes it worse, and an earlier draft of this
design made it much worse by inheriting `say_reply_timeout_ms` (180 s) for **both** clips: a
theoretical `2 × (5 + 180) = 370 s` turn behind an HA timeout of tens of seconds.

Two things fix this: bound the message (`announce_max_chars`), then size every budget from that bound
rather than from the knowledge agent's worst case.

**Precondition: wall-clock deadlines.** Rev 2 derived a budget and then admitted in the same
paragraph that it was not a bound, because `_say`'s poll loops *"bound themselves by accumulated
sleep rather than wall clock"* (`CHANGELOG.md:1328`). A loop that counts only its own `sleep()` calls
does not count the `get_entity_state` round-trip between them, so its real duration is unbounded in
principle and simply unknown in practice. Deriving a timeout from such a figure is arithmetic, not
engineering.

So **announcement clips poll against an absolute deadline**: `_play_clip_and_wait` receives
`deadline = self._clock() + budget` and compares `self._clock()` each iteration, rather than
accumulating `poll_secs`.

**A deadline alone is not enough, and rev 3 stopped one step short.** An absolute deadline prevents
the *next* iteration; it does nothing about the iteration already in flight. A
`get_entity_state()` begun 0.1 s before expiry still blocks for its **fixed 10 s** socket timeout
(`haconn.py:47`), so each deadline-bounded phase could overshoot by up to 10 s. Five phases do this —
the mic confirmation and all four clip polls — which is up to 50 s of unbudgeted overshoot. And
`resolve_media_source`'s nominal 10 s cannot be honoured at all while `wsutil.ws_connect` hardcodes
`socket.create_connection(..., timeout=15)` (`wsutil.py:7`), whose value the handshake `recv` loop
then inherits.

**But a `timeout=` is not a deadline either, and rev 4 overstated what clipping buys.** Passing
`timeout=` to `http.client.HTTPConnection` or `socket.create_connection` sets a **per-operation
inactivity timeout on the socket**, not a total wall-clock limit for the request. Connect, send,
status line, headers and body reads each get their own allowance; the WebSocket path additionally has
the auth handshake, per-frame reads and ping handling, each with the same allowance. A slow-but-alive
peer can therefore keep a single logical call going well past its nominal timeout without ever
tripping it.

That is not confined to the five poll reads either — the TTS resolution, the chime resolution and
every `call_service_rest` use the same transport model, so the same reasoning applies to §6.5 rows
1–4, 6–8, 11, 14, 15 and 16. And the 500 ms floor bounds when a call is *started*; it says nothing
mathematically about scheduling jitter.

**So the numbers below are an engineered phase budget, not a proof.** Clipping and the two signature
changes are still worth doing — they stop a call from blocking on its full default when only seconds
remain, and `resolve_media_source` cannot be bounded *at all* today — but they reduce overshoot
rather than eliminate it. A genuine end-to-end transport deadline would mean threading a deadline
through every blocking operation in `haconn` and `wsutil`, which is a far larger transport change
than this feature warrants and is **not** proposed.

Two shared-surface changes, both additive and backward-compatible, and both explicitly in scope for
**G2**:

| Change | Today | After |
|---|---|---|
| `haconn.get_entity_state(entity_id)` | `timeout=10` hardcoded (`haconn.py:40,47`) | `get_entity_state(entity_id, timeout=10)` — same default, so every existing caller is unchanged |
| `wsutil.ws_connect(host, port, path)` | `timeout=15` hardcoded (`wsutil.py:7`) | `ws_connect(host, port, path, timeout=15)` — same default; the value is also applied to the handshake read, not just the connect |

The clipping rule, applied at each call site inside a bounded phase:

```
remaining = deadline - self._clock()
if remaining < floor:          # not enough left to be worth starting
    break                      #   -> end the phase; do NOT start another blocking call
timeout = min(default_timeout, remaining)
```

with `floor = announce_min_call_timeout_ms` (500 ms). A call is either given a timeout that fits
inside the deadline, or not started at all.

**What the two numbers actually are.**

- **190 s — the engineered phase budget.** The sum of every phase's nominal allowance, plus a small
  allowance for start-of-call slack. It is the figure the design is *engineered against*: it is what
  the dead-men and the marker staleness threshold are derived from, and what any future change to a
  timeout must be re-checked against. It is **not** a proven upper bound on wall-clock duration, for
  the transport reasons above.
- **200 s — the configured operational timeout**, on the announcement `rest_command`. Chosen to sit
  comfortably above the engineered budget. Whether it is *actually* sufficient is an empirical
  question, **validated at G3** by measuring a real announcement at `announce_max_chars` (§11.5
  item 6) — not settled by this arithmetic.

If G3's measurement lands anywhere near 200 s, the response is to raise the configured timeout and
re-derive, not to re-argue the table. The expected duration is roughly **10 s** (§6.5 below), so the
gap should be enormous; a measurement that is not enormous is itself the finding.

`say` and `say_text` **keep accumulated-sleep bounding.** Converting them is a timing-behaviour change
to a live, proven path with no defect motivating it, and it would need its own live gate; the §11.1
golden tests pin that AN-01 leaves it alone. Unifying the two is recorded as a follow-up, not smuggled
in here.

**Derivation.** Piper speaks at roughly 150 words per minute. `announce_max_chars` of 300 is about 50
words, so ~20 s of speech; the chime is a measured 4 s. Every row is a call's own timeout or a poll
deadline — nothing is omitted, including the resolutions and reads rev 2 left out:

| # | Phase | Nominal allowance | Source of the number |
|---|---|---|---|
| 1 | resolve TTS clip | 10 s | `tts_get_url` timeout |
| 2 | resolve chime | 10 s | `resolve_media_source` timeout |
| 3 | mic state capture | 10 s | `get_entity_state` timeout |
| 4 | mic `switch.turn_on` | 5 s | `call_service_rest` default |
| 5 | mic confirm poll | 2 s | `announce_mic_confirm_timeout_ms` |
| | *subtotal before `_say`* | **37 s** | |
| 6 | `media_pause` | 5 s | `call_service_rest` default |
| 7 | `volume_set` (raise) | 5 s | `call_service_rest` default |
| 8 | chime `play_media` | 20 s | `say_call_timeout_ms` |
| 9 | chime start poll | 5 s | `say_start_timeout_ms` |
| 10 | chime finish poll | 15 s | `announce_chime_finish_timeout_ms` |
| 11 | message `play_media` | 20 s | `say_call_timeout_ms` |
| 12 | message start poll | 5 s | `say_start_timeout_ms` |
| 13 | message finish poll | 45 s | `announce_message_finish_timeout_ms` |
| 14 | `volume_set` (restore) | 5 s | `call_service_rest` default |
| 15 | source replay `play_media` | 20 s | `say_call_timeout_ms` |
| | *subtotal inside `_say` — this is `marker_budget_s`* | **145 s** | rows 6–15 |
| 16 | mic `switch.turn_off` | 5 s | `call_service_rest` default |
| | *budgeted phases* | **187 s** | rows 1–16 |
| | start-of-call slack on the 5 deadline-bounded phases | 3 s | `announce_min_call_timeout_ms` × 5 (see the clipping rule above) |
| | **engineered phase budget** | **190 s** | what the dead-men and the staleness threshold derive from — **not** a proven wall-clock limit |

Poll rows count their read latency inside the phase budget rather than on top of it — that is what the
deadline and clipping rule buy. They remain nominal allowances, not guarantees.

**The three derived figures.**

| Quantity | Value | Covers |
|---|---|---|
| `marker_budget_s` (§8.4(a)) | **145 s** | step 2 → `finally`; `+ 60 s` existing margin → ~205 s orphan threshold |
| mic dead-man (§9.5) | **≈185 s** | armed before `_say` (rows 5–16 = 152 s) `+ 30 s` margin |
| `rest_command` timeout | **200 s** | the configured operational timeout, above the 190 s engineered budget; sufficiency validated at G3 |

**These are engineering allowances, not expectations.** The measured `say_text` turn in
`CHANGELOG.md` 2026-09-05 finished its poll in **2.0 s**; a real announcement should land around 10 s.
Reaching 190 s would need *every* call to consume *its own* full allowance at once, which will not
happen in practice.

**Corrections rev 2 got wrong here.**

- **The 150 s figure was not bounded.** It omitted rows 1–5, 14, 15 and 16 entirely — 82 s of the
  real budget — and rested on accumulated-sleep polls. Replaced by a 190 s engineered budget and a
  200 s configured timeout. (Rev 3 then called 187 s a *hard* bound, and rev 4 called 190 s
  *enforceable*; both overstated it, because a socket `timeout=` is a per-operation inactivity
  timeout rather than a request deadline. The clipping rule and the two G2 signature changes reduce
  overshoot; they do not prove a limit.)
- **§9.5's "≤30 s window" was wrong** and so was its `clips × (say_start + say_reply) + 30 s` formula
  (~400 s). Replaced by the dead-man row above.
- **`budget_s` was doing two jobs.** Split into `marker_budget_s` and the whole-turn budget (§8.4(a)).

**Trade-off, stated plainly.** A 200 s `rest_command` timeout means HA can block that long on a
pathological announcement. That is the cost of a synchronous `/command` and it is why option 1 below
is preferred — it confines the long timeout to the announcement path. If 200 s is judged too long to
tolerate, the lever is announcement-specific call timeouts (an `announce_call_timeout_ms` below
`say_call_timeout_ms`'s 20 s would remove up to 60 s from rows 8, 11 and 15), which is a config
addition, not a redesign. **Not proposed by default:** it would make an announcement give up on a
slow MA that a reply would wait for.

**`rest_command.resolver_command` timeout.** The announcement path needs **`timeout: 200`**.

Whether that can be set for announcements alone depends on how the existing `rest_command` is
defined in live config (**D8**, **D13**). Two shapes, in preference order:

1. **A second rest_command** (`rest_command.resolver_command_announce`) with the longer timeout,
   leaving every existing caller's timeout untouched. Preferred: no shared-surface change, and
   `script.play_radio`'s latency expectations are unaffected.
2. **Raise the shared timeout.** Simpler, but it lengthens how long *every* resolver call can block a
   script, including the five ChatGPT-exposed ones. Only if (1) proves awkward.

**How a timeout reaches the phone** is §5.2 branch 1: `continue_on_error: true` keeps the automation
alive, `r` is undefined, and the operator is told *"I couldn't reach the announcer."* — which is
honest, because a timed-out `/command` may well still be playing the announcement server-side. The
resolver log remains the authority on what actually happened, exactly as it is today for the
satellite reply path.

---

## 7. `_announce` ordered sequence

The ordering is chosen so that **every cheap failure happens before anything is touched**, and the
expensive, stateful steps happen last.

```
A. validate text             → empty: invalid_input, nothing touched
B. render + bound text       → prefix over announce_max_prefix_chars: DROP the prefix, log error
                               len(prefix + message) over announce_max_chars:
                                 REJECT with the EFFECTIVE limit stated, nothing touched
C. resolve TTS clip          → failure: HONEST FAILURE, nothing touched            (requirement 9)
D. resolve chime clip        → failure: DEGRADE, log, continue without a chime     (requirement 8)
E. claim generation          → establishes turn ownership before the mic is touched
F. capture prev + mute mic   → failure: HONEST FAILURE, no broadcast                    (req 7)
G. CONFIRM the mute by read  → not `on` within announce_mic_confirm_timeout_ms:
                               HONEST FAILURE, release the lease, no broadcast          (req 7)
H. _say(uris=[chime?, tts])  → one baseline, one raise, clip loop, one restore, one replay
I. map outcome               → message silent ⇒ honest failure (§8.5); ok ⇒ "Announced."
finally: restore microphone if still ours (§9.4)
```

Why C precedes F: a TTS failure is the most likely failure in the whole sequence — it is a network
call into HA's TTS pipeline — and paying for it with a muted microphone and a raised volume would be
gratuitous. Resolving both URLs first makes step F the point of no return.

Why D degrades rather than fails: requirement 8, and because the chime is the piece whose route is
unproven (§3.2). An announcement without its chime is still an announcement; an announcement that
refuses to play because a decoration failed is a worse product.

Why B rejects rather than truncates: the message is a **household communication**, and truncation
changes meaning silently. *"don't let the dog out the back gate"* clipped at a word boundary can
become *"don't let the dog out"* — still a fluent sentence, opposite intent, and nobody in the room
can tell it was cut. That is incompatible with the verbatim guarantee in goal 3, and a truncation
flag in `metadata` does not help a listener two rooms away. Rejecting costs the operator one retry
and tells them why (§10 row 2).

Why G exists at all: see §9.3. A `switch.turn_on` that returns 200 means HA accepted the request, not
that the microphone is muted — and requirement 7's fail-safe is worthless if it is satisfied by an
accepted request rather than an observed state.

**Why B bounds the *rendered* text, not the message.** `announce_prefix` is configurable and is
synthesised into the same clip, so bounding only the message leaves §6.5's timing model defeatable
from `config.json` alone: a 5 000-character prefix would produce a six-minute clip that every budget,
dead-man and `rest_command` timeout in this design was sized against 300 characters. The bound is
therefore on `prefix + message`, and the message's **effective** limit is
`announce_max_chars - len(prefix)` — which is what the rejection message must quote, or the operator
is told a limit they are already under. The prefix carries its own smaller cap so a misconfiguration
degrades to "no prefix" instead of "no announcements".

---

## 8. Clip-sequence state machine

### 8.1 What moves, and what does not

`_say` is refactored so the per-clip work is extracted into `_play_clip_and_wait`. The extraction is
mechanical: the body of today's steps 3, 5, 6 and 7 becomes the helper, and everything else stays
exactly where it is.

**Outside the loop, executed once per turn:**

- step 0 — the fresh-playback skip guard
- step 1 — before-state capture (`was_playing`, `source_id`, `prev_volume`), `remember_source`
- step 1b — the `_turn_stopped` override of `was_playing`
- step 2 — generation claim (or adoption, §9.2), `_reply_baseline`, `my_snap_ts`, `duck_floor`,
  publication of `self._replies[zone]`, and the `superseded` / `retire_snapshot` / `release_reply` /
  `superseded_result` closures
- step 4 — the optional `media_pause`, the single `volume_set` to the turn's volume,
  `pending_restore`, and the `snap["target"]` sync
- step 8 — the single volume restore, including the "someone moved it during the reply" check
- step 9 — the single source replay
- the `finally` — the pending-restore fallback, the never-issued un-pause, `release_reply`

**Inside the loop, once per clip:**

- URI normalisation via `_normalise_uri` against `say_internal_base`
- `music_assistant.play_media`
- the start poll, bounded by `say_start_timeout_ms`
- the finish poll, bounded by **this clip's** budget from `finish_timeouts` (falling back to
  `say_reply_timeout_ms`, so `say`/`say_text` are unchanged), retaining **both** existing
  subtleties: the `ended_seen >= 2` two-consecutive-observations rule, and the
  `say_blank_cid_grace_ms` tolerance for MA transiently reporting an empty `media_content_id`
  mid-clip
- a `superseded()` check on every poll iteration

### 8.2 Per-clip match key

> ⚠ **PARTLY SUPERSEDED — see [`2026-09-07-an-01-post-g1-design-corrections.md`](./2026-09-07-an-01-post-g1-design-corrections.md) corrections 1 and 3.** The premise below (that MA may
> strip the query) was **measured false** at AN-1: MA preserves it and wraps the chime as
> `builtin://track/<url>?authSig=…`. Every clip's match key is therefore its **full normalised
> URI**, and the path-only special case is withdrawn. The `builtin://track/` wrapper also means
> `_is_reply_uri` does not recognise a chime, so it must be reclassified as an ephemeral clip.
> The **containment** matching described below remains correct and necessary.

`_say` currently confirms a clip with `norm_uri in (attrs.get("media_content_id") or "")`, under the
comment that "MA does not echo the raw URL back as `media_content_id` — it wraps it, e.g.
`builtin://radio/<url>`. Match by containment, not equality."

A signed chime URL carries `?authSig=…`, and **it is not known whether MA preserves the query string
in what it echoes back** (D5). If it strips it, full-URI containment fails and the chime would be
reported as never started even while audibly playing.

So each clip carries its own `match_key`:

- **TTS clips:** the full normalised URI — byte-for-byte today's behaviour, so `say` and `say_text`
  are provably unaffected.
- **Chime clip:** the normalised URI with the **query string stripped**, i.e. the path only.

The key is computed once at clip-build time in `_announce`. `_play_clip_and_wait` takes it as a
parameter and never derives matching rules itself.

### 8.3 Per-clip outcomes

| Outcome | Chime clip | Message clip |
|---|---|---|
| Started and finished | record `played: true`, continue | `said: true` |
| `play_media` raises | log warning, record `reason: "play_failed"`, **continue to the message** | propagate — the turn's `finally` restores volume, **replays the source if any clip replaced the queue** (§8.3a), and restores the mic |
| Never starts (start-poll exhausted) | log warning, `reason: "never_started"`, **continue to the message** | `likely_silent: true` → §8.5 |
| Finish-poll exhausts its budget | log, treat as finished, continue | log, treat as finished, `said: true` |
| `superseded()` at any poll | abort the whole sequence, `superseded_result()`, **no restore, no replay** | same |

The asymmetry is the whole point: **a chime failure is never fatal; a message failure always is.**

**Microphone behaviour is deliberately absent from this table.** It is a `_say`-level table, and
`_say` does not own the microphone (§4). Whether a supersession unmutes depends on *who* superseded —
a newer announcement takes the lease and A stays quiet, any other turn does not and A unmutes
immediately — which is §9.4's rule and §9.6's matrix, not something `_say` can express. Rev 4 left an
unqualified "no unmute" here, contradicting its own correction two sections later.

### 8.3a Fatal later-clip failure must not lose the source

A multi-clip turn creates a failure shape a single-clip turn cannot: **an earlier clip succeeds in
replacing the queue, and a later one dies.**

Concretely: the chime plays (MA's `play_media` replaced the queue with it), then the message's
`play_media` raises. Today's finalizer (`interaction.py:780-803`) does two things — restores volume
if `pending_restore`, and un-pauses if `paused_by_us and not play_issued`. Neither helps:

- The **replay lives only in step 9**, on the success path. An exception skips it entirely.
- The **un-pause is gated on `not play_issued[0]`**, which the chime's successful play has already
  made false. And even if it fired, un-pausing is useless — the queue no longer holds the music, it
  holds a spent chime.

So the operator's station is gone, and the only thing they heard was a bell. For a single-clip reply
this case does not exist: if the one clip fails to play, the queue was never replaced, and the
un-pause is exactly the right recovery.

**Fix — claim the replay obligation *before* each play, not after the ack.** The same
lost-acknowledgement reasoning as §8.4(c): a `play_media` whose request lands but whose response is
lost has changed the queue while any success-gated flag stays `False`.

- A new **`queue_may_be_replaced[0]`**, set **immediately before** every `play_media` call — one per
  clip, and also before step 9's replay. It records *"we may have changed the queue"*, which is the
  only thing a caller can honestly know. Rev 3 set a `queue_replaced` flag *after* a successful
  return, which leaves the exact hole under review: request lands, ack lost, flag `False`, queue
  changed.
- In the `finally`: if `queue_may_be_replaced[0]` and `was_playing` and `source_id` and **not**
  `superseded()`, best-effort replay `source_id`, log at `warning`, swallow failures exactly as
  step 9 does.
- **The un-pause is re-gated on the same flag**, replacing `not play_issued[0]`. Un-pausing is only
  correct when the queue is certainly intact, which means *no play was ever attempted*. `play_issued`
  is set after the call returns and so cannot support that claim; `queue_may_be_replaced` can.
- **Consequence, made explicit because rev 4 stated it inconsistently:** since the flag is claimed
  *before* the call, **any** `play_media` that raises leaves it set. So "no play was ever issued"
  means the turn died **before reaching a `play_media` at all** — the step-4 `media_pause` or
  `volume_set` failing. A raising first clip is an *ambiguous* failure, not a clean one, and takes the
  replay path. Rev 4's row 15a and one test both described a raising `play_media` as leaving the flag
  clear, which the new ordering makes impossible; both are corrected.
- **Fallback for the un-replayable case:** if `queue_may_be_replaced[0]` is set but there is no
  `source_id` to replay (nothing captured, or the capture read failed), and `paused_by_us[0]`, still
  attempt the un-pause. Without this the zone would be left paused and silent — a regression against
  today's behaviour that a naive re-gating would introduce.
- The `superseded()` guard is the same one step 9 uses: a newer turn owns the zone and is about to
  play its own thing. Replaying into it would be the reply-clobbers-the-station defect from
  `CHANGELOG.md` 2026-09-06, arriving from the other direction.
- Idempotence: step 9 and the finalizer must not both replay. Step 9 clears the flag once it has
  replayed, so the normal path emits exactly one replay — which the §5 golden call order asserts.

**On an ambiguous failure, replay beats assuming the queue survived.** If the play did land, replay is
the only recovery. If it did not, replay re-plays the station that was already there — audible as a
brief restart, and correct. Un-pausing a queue that now holds the announcement clip would instead
play the announcement *again* as though it were the music, which is both wrong and confusing.

**This changes `say`/`say_text` behaviour on a failure path — deliberately, and it is the one
behavioural change in this design that reaches replies.** Today, a reply whose `play_media` raises
gets an un-pause; after this it gets a replay of the captured source (or an un-pause when there is
nothing to replay). The replay is strictly safer for the same lost-ack reason, and the reply path is
where `CHANGELOG.md` 2026-09-05 already recorded a failed announce leaving "the ceiling reporting a
**stale** cid from hours earlier". Success-path call sequences are untouched, so §11.1's golden tests
still hold; the failure-path change is asserted by its own tests (§11.4) rather than left implicit.

### 8.4 Two defects the sequence introduces, and one it exposes

**(a)** and **(b)** are consequences of a turn now owning the zone for two clips instead of one:
neither is a pre-existing bug, and both would be *introduced* by this change if not designed for.
**(c)** is the opposite — a **pre-existing** defect in `_say`, reachable by any reply today, that an
announcement merely makes dangerous enough to be worth fixing here (louder value, and no dead-man;
see §9.7). Rev 3's heading said "three latent defects" and its intro then said "both", which is where
that distinction got lost.

**(a) `_reply_active`'s staleness budget under-counts a multi-clip turn.**
`interaction.py` computes the orphan threshold as
`(say_start_timeout_ms + say_reply_timeout_ms)/1000 + 60`, which at the current `5000 + 180000` is
~245 s. A two-clip turn's worst case is `2 × (5 + 180) = 370 s`. A long announcement could therefore
have its **own** in-flight reply marker declared stale and be "reclaimed" mid-flight by a duck or
restore — precisely the ratchet/crater class the S1b-2 ownership decision exists to prevent.

*Fix:* the turn computes its **own** budget and stores it in the marker as
`self._replies[zone]["marker_budget_s"]`; `_reply_active` uses that when present and falls back to
today's formula when absent. A clip-count multiplier was the first draft and is worse: with §6.5's
per-clip timeouts the clips are no longer the same size, so `clips × (start + reply)` would over-count
an announcement by roughly 3×, widening the orphan window for no reason. Existing single-clip callers
store nothing and keep today's threshold exactly.

**What the marker budget must cover.** The marker is published at step 2 and released in the
`finally`, so its legitimate lifetime is *everything in between* — not just the polls. Per §6.5 that
is **≈145 s**: the pause and volume writes, both `play_media` calls at their 20 s call timeout, all
four poll budgets, the restore write, and the replay. With the existing `+ 60 s` margin the threshold
becomes ~205 s, inside the ~245 s fallback — so this remains defence for the config rather than for
today's numbers, and it matters because `announce_message_finish_timeout_ms` is a tunable.

**Rev 2 stated this wrong.** It gave `budget_s = (5 + 15) + (5 + 45) = 70 s` — poll budgets only —
and then claimed §9.5's dead-man reused "the same `budget_s` ≈145 s". Those are two different
quantities and cannot be one variable. §6.5 now names three, derived from one table:
`marker_budget_s` (≈145 s, step 2 → `finally`), the **mic dead-man** (≈185 s, armed before `_say`),
and the **whole-turn budget** (≈190 s, the whole capability call, which is what HA's `rest_command` must
outlast).

**(b) `reply_volume` is read from settings inside `_say`.**
An announcement needs `0.80` where a reply needs `0.70`. `_say` reads
`float(getattr(ctx.settings, "reply_volume", 0.40))` and uses that value in four places: the raise,
the `snap["target"]` sync, the mid-reply "did someone move it" comparison, and the abort path.

*Fix:* resolve the turn's volume once at the top of `_say` from `resolved.get("volume_override")`,
falling back to `settings.reply_volume`. The fallback must be an **explicit `is None` check**, not
`or` — a `volume_override` of `0.0` is a legitimate value that `or` would silently discard. All four
existing uses then read the local.

**(c) A lost acknowledgement on the volume raise strands the zone at announce volume.**
`interaction.py:640-642` issues `volume_set` and sets `pending_restore[0] = True` **afterwards**. If
HA applies the write but the response is lost — a timeout, a dropped connection, a 5xx after the
write landed — `_say_call` raises, `pending_restore` is still `False`, and the `finally`'s restore is
skipped. Rev 3's "the zone is never left at announce volume" claim (§10 row 12) was therefore false
as written; §9.7 both adds the missing recovery timer and restates the invariant honestly.

It is worse than a stuck volume, for two reasons:

- The `snap["target"]` sync immediately after also never runs, so a later `_restore` or dead-man
  reads the device at 0.80, does not recognise it as ours, classifies it as `user_override`, **keeps
  it and discards the baseline**. That is the exact volume ratchet the S1b-2 ownership work fixed.
- **For an announcement there is no dead-man at all.** Per §3.5 a phone caller creates no duck
  marker, so `self._snaps[zone]` never exists and `_arm_timer` never ran. The mic dead-man (§9.5)
  covers the microphone; nothing covers the volume. `_say`'s `finally` is the only net, and this
  defect is precisely what disables it. The ceiling stays at 0.80 until someone changes it by hand.

**Fix — claim the restore obligation before issuing the write:**

```
pending_restore[0] = True          # we may already have moved it; assume we did
if owns_restore: ...sync snap["target"] = turn_volume...
self._say_call(ctx, rid, zone, "media_player", "volume_set", {...})
```

Setting the flag first can only cause a **redundant** restore to a value the zone is already at —
harmless, idempotent, and invisible. Setting it second can cause a **missing** restore, which is
neither. The `snap["target"]` sync moves ahead of the write for the same reason: it must describe
what we are *about to* write, so a turn that dies mid-write still leaves a device a later reconciler
agrees with.

This is a **pre-existing defect in `_say`**, not one AN-01 introduces — it is reachable by any reply
today. AN-01 makes it materially worse (louder value, no dead-man), which is why it is fixed here
rather than deferred. Fixing it changes no emitted call in the success path, so the §11.1 golden
sequences hold; it changes only which calls appear on a *failure* path, which is what the new
lost-ack regression asserts.

Also worth stating: `max_duck_timeout` is `120000` ms, shorter than a worst-case two-clip turn. That
tension is **pre-existing** — a single 180 s reply already exceeds it — and is handled by `_restore`'s
deferral plus re-arm while a reply is active. AN-01 does not change it and does not need to; it is
noted so a reviewer does not mistake it for a new hazard.

### 8.5 A silent announcement is a failure

`say_text` returns `cr.ok(..., metadata={"said": True, "likely_silent": True, ...})` when a clip never
starts — reasonable for a reply, where the operator is present and can simply ask again.

For an announcement it is wrong: the caller is broadcasting to a room they may not be in, and
"claimed success, did nothing" is the exact failure class `CHANGELOG.md` 2026-09-05 flags as one
"this stack keeps producing".

**Decision:** when the *message* clip reports `likely_silent`, `_announce` converts `_say`'s `ok` into
`cr.err(self.name, rid, "upstream_error", "announcement did not start", "I couldn't play the
announcement.")`, carrying `_say`'s metadata through unchanged so the log and the result still say
exactly what happened.

This mapping lives **entirely in `_announce`**. `_say`'s return contract is untouched, and `say_text`
keeps its current behaviour.

---

## 9. Ownership: microphone, volume and supersession

The microphone is a second resource with the same hazard shape as the ceiling volume: two overlapping
turns can each believe they own it, and the loser can restore a value the winner has already
overwritten. It is therefore modelled on `_reply_baseline`'s ownership chain rather than invented
fresh.

### 9.1 State

```
self._mic = {}   # zone -> {"gen": int, "prev": bool|None, "confirmed": bool,
                 #          "rid": str, "ts": float, "timer": obj|None}
                 # guarded by self._lock, like every other per-zone dict in this class
```

**`_mic` is written only by `_announce`.** Nothing else in the class touches it — not `_duck`, not
`_restore`, not `_say`, not the dead-man for the duck snapshot. That single fact is what makes §9.4
and §9.6 come out right, and it is the point the first draft of this design got wrong.

### 9.2 Claiming — generation before microphone

Requirement 1 says the microphone must be muted **before audio begins**; `_say` establishes the turn
generation at its step 2, which is after `_announce` needs it. Resolved by letting `_announce`
**pre-claim** the generation:

- A small helper bumps `self._say_gen[zone]` under `_lock` and returns `my_gen`.
- `_announce` passes it to `_say` as `resolved["gen"]`.
- `_say` uses a supplied `gen` when present and otherwise bumps its own, so `say` and `say_text` are
  unchanged.

One counter, one meaning, and microphone ownership can be established before any sound.

**Adoption must revalidate, atomically.** A pre-claimed generation can go stale before `_say` sees
it.

**The window is steps F and G only — about 17 s.** §7 resolves both URLs at C and D, *before* the
claim at E, so the resolutions are **not** in this window. What is: the mic state capture
(10 s), the `switch.turn_on` write (5 s), and up to 2 s of confirmation polling — §6.5 rows 3–5.
Rev 3 described the window as including the two resolutions and put it at ~37 s, which contradicted
its own §7 ordering. The C/D-before-E ordering is right and is kept — it is what makes a TTS failure
cost nothing (§7) — so the window shrinks rather than the sequence changing.

17 s is still ample for a satellite wake to arrive, and the confirmation poll is the longest stretch
where `_announce` is doing nothing but waiting on another device.

If `_say` simply trusts the supplied value and publishes `self._replies[zone]`, the **stale
announcement overwrites a newer turn's ownership marker**, and that newer turn then loses its
baseline, its restore and its `release_reply` guard. That is the ratchet/crater failure the S1b-2
ownership decision exists to prevent, reintroduced through the back door.

So in the *same* critical section that publishes the marker, `_say` checks:

```
with self._lock:
    if supplied_gen is not None:
        if self._say_gen.get(zone) != supplied_gen:   # someone arrived while we resolved
            return superseded_result()                #   -> abort BEFORE publishing anything
        my_gen = supplied_gen
    else:
        my_gen = self._say_gen.get(zone, 0) + 1       # today's behaviour, unchanged
        self._say_gen[zone] = my_gen
    ...resolve baseline, publish self._replies[zone]...
```

The check and the publish must not be separated — a check outside the lock is the same race one
instruction later.

**The abort still has to unmute.** Returning `superseded_result()` here means `_say` never reaches
its own `finally` bookkeeping for this turn, but `_announce`'s `finally` runs regardless, and §9.4's
lease check is on `_mic` rather than `_say_gen` — so a stale announcement that aborts at adoption
**does** release the microphone it muted, unless a newer *announcement* has taken the lease. That is
the correct outcome and it falls out of §9.1's invariant rather than needing a special case.

`say` and `say_text` pass no `gen`, take the `else` branch, and are unchanged by *this* fix.

**Inheriting `prev` — the load-bearing rule.** In the same critical section:

- If `self._mic[zone]` **does not** exist: read the switch's live state and store it as `prev`.
- If it **does** exist (an older *announcement* is still in flight): **inherit that entry's `prev`**
  and do not read the switch.

Without inheritance the second announcement would read the live switch — which the first has already
set to `on` — conclude that muted was the operator's preference, and leave the satellite permanently
deaf. Same reasoning and same ordering as `_reply_baseline` preferring the duck snapshot over the
live volume.

**Why an equality check on `gen` is sufficient.** `_mic[zone]["gen"]` is drawn from the shared,
monotonic `_say_gen` counter, so a newer announcement's gen is always strictly greater than an older
one's. And because §9.1's invariant holds — only `_announce` writes `_mic` — a non-announcement turn
bumping `_say_gen` cannot change `_mic[zone]["gen"]`. So `_mic[zone]["gen"] == my_gen` answers exactly
one question, "is the microphone lease still mine", and never conflates it with "does this turn still
own the zone".

### 9.3 Establishing the mute — write, then confirm by reading

**A successful `switch.turn_on` does not establish muting.** `call_service_rest` raises on non-2xx, so
a returning call proves only that HA *accepted the request*. It does not prove the ESPHome device
received it, applied it, or is reachable at all — and `CHANGELOG.md` records this satellite dropping
its API connection (`Can't connect to ESPHome API for respeaker-living-room @ 192.168.1.132`,
Errno 113). Treating an accepted request as a muted microphone would make
`announce_require_mic_mute: true` a fail-safe in name only: it would broadcast into a live microphone
while reporting that it had prevented exactly that.

So after the write, `_announce` **polls the switch's state** until it reports `on`:

- Interval `announce_mic_confirm_poll_ms` (250 ms), budget `announce_mic_confirm_timeout_ms` (2 s),
  via the injected `self._sleeper` so it is testable without real time.
- **Confirmed** → set `confirmed: true` on the lease and proceed to `_say`.
- **Not confirmed within the budget** → `announce_require_mic_mute` decides:
  - `true` (default): **no broadcast.** Return `unavailable`, and release the lease on the way out —
    attempting to restore `prev` first, since the write may have partially landed.
  - `false`: log at `warning`, set `confirmed: false`, and broadcast anyway. The result metadata
    carries `mic.confirmed: false` so the log says which of the two happened.
- **A read that raises** is treated as "not confirmed", not as an error to propagate: the outcome is
  the same fail-safe decision, and a transient read blip should produce the documented refusal rather
  than a bare traceback.

The lease is created **before** the write, so a crash between write and confirmation still leaves an
entry for the dead-man (§9.5) and the `finally` (§9.4) to reconcile. This ordering also replaces the
blind settle delay of an earlier draft: a read that proves the state is strictly better than a sleep
that hopes for it, and it is faster in the common case.

### 9.4 Restoring — only if still ours

`_announce`'s `finally` restores the microphone **only when `self._mic[zone]["gen"] == my_gen`** — the
**mic lease**, not zone ownership.

- **Lease still ours** → write `prev` back (skipping the write when `prev` already matches the
  current value), cancel the dead-man, delete the entry. **This applies even when the *zone* has been
  superseded** — see below.
- **Lease taken by a newer announcement** → do nothing. That turn holds the original `prev` (§9.2)
  and will restore it. This is requirement 6: an older superseded announcement must not restore or
  unmute while a newer announcement owns the microphone.
- **Write fails** → log at `error`, leave the entry in place, and let the dead-man reconcile.

**Zone supersession does not defer the unmute.** `_say`'s `superseded()` compares `_say_gen`, which
any turn bumps; the mic check compares `_mic`, which only `_announce` writes (§9.1). So when a
**satellite reply** supersedes an announcement mid-clip, `_say` returns `superseded_result()`
promptly, `_announce`'s `finally` finds the lease still its own, and the microphone is **unmuted
immediately**. That is both what the rule says and what is wanted: the superseding turn is a person
talking to the satellite, and leaving its microphone muted would break the conversation that
interrupted us.

An earlier draft of this design asserted the opposite — that a satellite reply would strand the mute
until the dead-man — and accepted a multi-minute deaf period on that basis. It was wrong: it
conflated `_say_gen` supersession with mic ownership. There is no deaf period, the "accepted
trade-off" has been removed, and §11.4 carries a **regression test for non-announcement
supersession** so the claim is enforced rather than reasoned about.

Deliberately parallel to `release_reply()`'s "only if it is still ours" and `retire_snapshot()`'s
timestamp match — both of which are likewise scoped to their own resource, not to the zone.

### 9.5 Dead-man

A stuck-muted microphone means a **deaf satellite** — a silent, open-ended availability failure nobody
discovers until they try to talk to it. So the microphone gets the same treatment as the duck
snapshot:

- Armed at mute time via the existing `self._timer_factory` — injectable, so it is testable without
  real time.
- Duration: `announce_mic_deadman_ms`, or when that is `0`, derived from **this turn's actual
  budget** (§6.5) — the sum of its per-clip start and finish timeouts, plus the mic and
  restore/replay allowances, plus 30 s of margin. With the shipped defaults that is
  **≈185 s** — rows 5–16 of §6.5's table (152 s, since the dead-man is armed *before* `_say`) plus
  30 s of margin. **This is a policy cutoff, not a proof of lateness.** It is derived from §6.5's
  engineered phase budget, which is not a wall-clock bound, so a pathologically slow-but-live turn
  could still be running when the timer fires. The trade-off is deliberate and points toward
  liveness: an unmute that arrives while a genuine announcement is somehow still playing costs a few
  seconds of self-wake exposure, whereas waiting indefinitely for a turn that may never return leaves
  the satellite deaf with nothing scheduled to fix it. Not the ~400 s an earlier draft's `clips × (say_start + say_reply)` formula
  produced, and **not** the same number as `marker_budget_s`: the marker is published later and
  released earlier, so it covers strictly less of the turn. Both are computed from §6.5's single
  table, so they move together without being conflated.
- On fire: log at `warning`, restore `prev`, delete the entry — guarded by the same generation check.
- Cancelled on every normal exit.

**Residual risk, stated rather than solved:** if the resolver *process* dies between the mute and the
unmute, the timer dies with it and the microphone stays muted. This is the same in-memory-state gap
the duck snapshot already has (`2026-07-15-s1b-duck-ownership-adr.md`, Consequences:
"Resolver-restart-mid-reply strand is unchanged from S1a — same deferred-persistence gap"). Operator
recovery is one toggle of the switch in the HA UI, and it is the one failure in this design that is
**silent and unbounded** — the process death takes the timer with it, so nothing ever reconciles.
That earns the runbook line in §13.2 rather than a shrug. Persistence is still not proposed: it would
mean durable state for a window the dead-man already covers in every case except process death, and
this stack has no persistence layer to put it in.

### 9.6 Supersession matrix

| Scenario | Volume | Source replay | Microphone |
|---|---|---|---|
| Announcement A alone | A restores baseline | A replays | A restores `prev` |
| A, then A2 mid-chime | A2 restores; A does not | A2 replays; A does not | A2 restores A's `prev`; A does nothing |
| A, then a **satellite reply** mid-message | the reply restores; A does not | the reply replays; A does not | **A unmutes immediately** — the lease is still A's (§9.4) |
| A, then a `say_text` (timer) mid-message | the `say_text` turn restores; A does not | that turn replays; A does not | **A unmutes immediately** — same reason |
| A, then a duck request | duck defers (`reply_active`) | — | untouched |

Rows 3 and 4 are the correction from review. Both are **non-announcement** supersessions: they bump
`_say_gen`, so `_say` aborts A's restore and replay, but they never write `_mic`, so A's lease check
passes and A unmutes on its way out. No dead period, no reliance on the dead-man, and no coupling of
the microphone into `_say`.

Only **row 2** transfers the microphone, and only because `_announce` is the sole writer of `_mic`.
The asymmetry between row 2 and rows 3–4 is the whole design: the zone is contended by every turn,
the microphone only by announcements.

These two rows are the regression test named in §11.4 under *Supersession*. They are the kind of
claim that reads as obviously true once stated and was asserted backwards in the first draft, so it
is pinned by a test rather than by prose.

### 9.7 Volume recovery — an announcement-owned dead-man

§8.4(c) establishes that **an unducked phone announcement has no volume dead-man**: no duck request
means no `self._snaps[zone]`, so `_arm_timer` never ran and `max_duck_timeout` never applies. Rev 3
nonetheless had failure row 18 saying a failed restore is reconciled by "the dead-man". Those two
statements cannot both be true, and row 18 was the false one.

The finalizer gives **one immediate retry**. If that write also fails — the same HA blip that broke
the first one, still ongoing — the ceiling stays at `announce_volume` with nothing scheduled to
correct it.

**Decision: introduce an announcement-owned volume dead-man.** The alternative offered in review was
to weaken the invariant and surface the failure. That is not sufficient on its own here: the failure
mode is a ceiling stuck at **0.80** in a house, discovered by whoever next plays music, and the
recovery is a timer this class already knows how to arm. So the design does **both** — it adds the
timer *and* stops overclaiming.

Mechanism, deliberately symmetric with the mic dead-man (§9.5):

- **Armed** inside `_say`, at the moment `pending_restore` is claimed (§8.4(c)), **only when
  `my_snap_ts is None`** — i.e. only when no duck snapshot already provides a dead-man. A satellite
  reply is unaffected: it has a snapshot and `max_duck_timeout`.
- **State:** `self._vol_recovery = {}`, `zone -> {"gen", "baseline", "rid", "ts", "timer"}`, guarded
  by `_lock` like every other per-zone dict. Written only by `_say`.
- **Duration:** `announce_volume_deadman_ms`, or when `0`, derived as `marker_budget_s + 30 s`
  ≈ **175 s** — long enough that a normal turn always cancels it first. Like the mic dead-man
  (§9.5), this is a **policy cutoff derived from an engineered budget, not a wall-clock bound**: a
  pathologically slow-but-live turn could cross it. Two guards make an early fire cheap rather than
  harmful — it does nothing if a newer turn owns the zone, and it leaves a volume that is no longer
  the one we wrote alone — so the worst case is restoring the baseline under a clip that is still
  playing. Preferring that to an indefinitely stuck 0.80 is the same liveness-over-waiting trade-off.
- **Cancelled** on any successful restore, in step 8 or in the finalizer.
- **On fire:** if `self._say_gen[zone] != gen`, a newer turn owns the zone — do nothing, it owns the
  restore too. Otherwise read the live volume: if it is **not** the turn volume we wrote, a human or
  another writer moved it — leave it (the same `user_override` courtesy `_restore` already extends).
  Only if it is still sitting at our announce volume, write the baseline back.
- **Bounded retries:** on write failure, re-arm, up to `announce_volume_deadman_retries` (default
  `3`), then log at **`error`** and stop. Mirrors `_auto_restore`'s guarded re-arm, but bounded —
  `_auto_restore` re-arms indefinitely, which is defensible for a snapshot that a later duck will
  coalesce with, and not for a one-shot announcement.

**What is still not guaranteed, said plainly.** The timer is in memory. If the resolver **process**
dies between the raise and the restore, nothing recovers the volume — identical in kind to the mic
residual in §9.5, and to the deferred-persistence gap the duck-ownership ADR already records. So the
honest invariant is:

> The zone is returned to its baseline on the success path, retried once immediately in the
> finalizer, and reconciled by an announcement-owned dead-man with bounded retries. If all of those
> fail, or the process dies mid-turn, **the ceiling can be left at announce volume** — and the
> result metadata says a recovery was deferred, and the **log** is the only record of whether that
> recovery ever succeeded.

That replaces rev 3's unqualified "the zone is never left at announce volume".

**The surfacing is asymmetric, and rev 4 got this wrong.** `metadata.volume_restore` can only ever
carry a value known *before* the result is serialised:

| Value | Meaning | When it is known |
|---|---|---|
| `"restored"` | step 8 or the finalizer retry succeeded | synchronously, before returning |
| `"deferred_to_deadman"` | both failed; a recovery timer is armed | synchronously, before returning |
| ~~`"failed"`~~ | **removed** | would only be known *after* the timer exhausts its retries — by which point `/command` has answered and the phone's response is already sent |

So **terminal dead-man exhaustion is log-only**, at `error`. Rev 4 acknowledged the timing in prose
and then contradicted it in failure row 18 and in the metadata test; both are corrected. The
resolver log is the sole witness to an unrecovered volume, which is the honest position — the
alternative would be making the retries synchronous and adding them to the turn budget, which is
**not** proposed: it would hold HA's `rest_command` open for minutes to fix a volume level.

## 10. Failure behaviour, by stage

| # | Stage | Failure | Behaviour | Result |
|---|---|---|---|---|
| 1 | `validate` | no/blank `text` | reject before any I/O | `err invalid_input` — "Nothing to announce." |
| 2 | bound text | `prefix + message` over `announce_max_chars` | **reject**, nothing touched — never truncate (§7) | `err invalid_input` quoting the **effective** limit (`announce_max_chars - len(prefix)`) |
| 2a | bound text | `announce_prefix` over `announce_max_prefix_chars` | **drop the prefix**, log at `error`, continue — a config fault must not disable announcing | `ok`, `metadata.prefix_dropped: true` |
| 3 | TTS resolve | `tts_get_url` raises | nothing touched — no mute, no volume, no audio | `err upstream_error` — "I couldn't say that." |
| 4 | TTS resolve | returns an empty or relative URL | `haconn`'s existing guards raise; as #3 | `err upstream_error` |
| 5 | chime resolve | `announce_chime_uri` empty | skip silently — configured off | `ok`, `chime.played: false`, `reason: "disabled"` |
| 6 | chime resolve | `resolve_media_source` raises | log `warning`, continue with the message only | `ok`, `reason: "resolve_failed"` |
| 7 | mic | `announce_mic_mute_entity` empty | when `announce_require_mic_mute`: **no broadcast** | `err unavailable` — "I can't announce without muting the microphone." |
| 8 | mic | state read raises | as #7 | `err unavailable` |
| 9 | mic | `switch.turn_on` raises | as #7 — nothing else has been touched yet | `err unavailable` |
| 9a | mic | **write accepted but the switch never reports `on`** within `announce_mic_confirm_timeout_ms` (§9.3) | **no broadcast**; attempt to restore `prev`, release the lease | `err unavailable` — "I couldn't mute the microphone, so I didn't announce." |
| 9b | mic | the confirm **read** raises | treated as not-confirmed, i.e. as #9a — not propagated as a traceback | `err unavailable` |
| 10 | mic | any of #7–#9b with `announce_require_mic_mute: false` | log `warning`, broadcast anyway | `ok`, `mic.muted`/`mic.confirmed` false |
| 11 | `_say` step 4 | `media_pause` raises | best-effort, already swallowed today ("a failed pause only costs us the bump") | `ok` |
| 12 | `_say` step 4 | `volume_set` raises **before the write lands** | propagates; `finally` fires, mic restored; at worst a redundant restore to a value the zone already holds | `err`; the zone is at its baseline (it was never moved) |
| 12a | `_say` step 4 | `volume_set` **lost acknowledgement** — the write landed, the response did not | `pending_restore` and the `snap["target"]` sync are both claimed *before* the write (§8.4(c)), so the `finally` restores the baseline | `err`; the zone still returns to baseline. **Without the §8.4(c) fix this row strands the ceiling at 0.80 with no dead-man to reconcile it** (§3.5: a phone caller leaves no duck snapshot, so `_arm_timer` never ran). |
| 13 | chime clip | `play_media` raises | log `warning`, continue to the message | `ok`, `chime.played: false` |
| 14 | chime clip | never starts | log `warning`, continue to the message | `ok`, `reason: "never_started"` |
| 15 | message clip | `play_media` raises **after the chime played** | propagates; `finally` restores volume, **replays the captured source because `queue_may_be_replaced` is set** (§8.3a), restores mic. The un-pause does *not* fire — the queue may hold a spent chime. | `err`; the station is back. **Without the §8.3a fix the operator's source is silently lost and all they heard was a bell.** |
| 15a | before any clip | the turn dies **before reaching any `play_media`** — e.g. the step-4 `volume_set` raises | `queue_may_be_replaced` is still clear, so the queue is certainly intact: restore volume and un-pause | `err`; the source resumes. This is the **only** un-pause path left: once a `play_media` has been attempted the flag is set, so every play-time failure takes the ambiguous replay path (row 15b). |
| 15b | any clip | `play_media` **lost acknowledgement** — the request landed, the response did not | `queue_may_be_replaced` was claimed *before* the call (§8.3a), so the finalizer **replays** rather than un-pausing | `err`; the station is back. Rev 3's success-gated flag left this row un-pausing a queue that may already hold the announcement clip — replaying the announcement as if it were the music. |
| 16 | message clip | never starts | the §8.5 mapping | `err upstream_error` — "I couldn't play the announcement." |
| 17 | any poll | `get_entity_state` raises | already tolerated today — log and proceed with an empty reading | unchanged |
| 18 | step 8 | restore `volume_set` raises | swallowed as today, **then** the finalizer retries once, **then** the §9.7 announcement-owned volume dead-man reconciles with bounded retries. No duck snapshot exists for a phone caller, so `max_duck_timeout` is **not** the net — rev 3 wrongly claimed it was. | `ok`, `metadata.volume_restore: "deferred_to_deadman"`, `warning` logged. **Terminal dead-man exhaustion is log-only** (`error`): it happens after `/command` has answered, so it cannot appear in the returned metadata — rev 4's `"failed"` value on this row was impossible. |
| 19 | step 9 | replay raises | already swallowed today | `ok`, `replayed: false` |
| 20 | any point | superseded by a **newer announcement** | no restore, no replay, **no unmute** — the newer announcement holds the mic lease and the original `prev` (§9.4) | `ok`, `superseded: true` |
| 20a | any point | superseded by a **non-announcement** turn (satellite reply, `say_text`) | no restore, no replay, **but the mic IS unmuted** — the lease is still ours because only `_announce` writes `_mic` (§9.1/§9.6 rows 3–4). Rev 3's blanket "no unmute" on this row contradicted its own correction. | `ok`, `superseded: true`, `mic.restored: true` |
| 21 | `finally` | mic restore raises | log `error`; dead-man reconciles | result unchanged |
| 22 | process | resolver dies mid-turn | mic stays muted until the operator toggles it (§9.5) | — |
| 23 | **HA transport** | `rest_command` **times out** while `/command` still blocks (`CHANGELOG.md:1328`) | `continue_on_error: true` keeps the automation alive; `r` is undefined | §5.2 branch 1 — "I couldn't reach the announcer." The announcement may still be playing; the resolver log is the authority. |
| 24 | **HA transport** | resolver unreachable / `/command` unbound (the cold-boot bind race, `ONBOARDING.md` §7) | as #23 | as #23 |

Rows 11, 17, 18 and 19 are existing `_say` behaviour, listed so the table is a complete account of an
announcement rather than only of the new code. Rows 23–24 are the **transport** failures that the
resolver cannot report on itself, which is why §5.2's first `choose` branch exists at all.

**Every `err` row above reaches the operator's phone**, because §5.2 relays `r.content.chat_text`
verbatim on the failure branch. That is the difference between honest failure *reporting* and honest
failure *delivery*, and the first draft of this design only had the former.

---

## 11. Test strategy

All unit tests are **offline**. `FakeHA`, `FakeSettings`, `FakeSleeper` and `FakeTimer` already exist
in `tests/test_interaction.py`, and `FakeHTTPConnection` in `tests/test_haconn.py`. No live host, no
audio, no network. The suite runs on host Python 3.5.2 as well as locally — `CHANGELOG.md` 2026-09-05
records **344 local tests**.

### 11.1 The backward-compatibility proof (write this first)

The single most important test is not about announcements. It is a pair of **golden call-sequence
tests** for `say` and `say_text`, asserting the exact `ha.calls` list and the exact `ha.timeouts`
list, added **before** the refactor and unchanged after it.

Inspection is not proof that a 300-line extraction preserved behaviour; a byte-level assertion on the
emitted service calls is. `FakeHA` already records both lists, so this is cheap.

Supporting regressions, all of which must stay green untouched: `SayPlayMediaTest`,
`FinishPollCutOffTest`, `ReplyBumpTest`, `SayTextTest`, `SayTextFreshPlaybackTest`,
`DuckOwnershipSlice4Test`, `HumanVolumeChangeDuringTurnTest`, `SayObservabilityTest`.

### 11.2 `tests/test_config.py`

- `AnnounceTunablesTest.test_defaults` — `announce_volume 0.80`, `announce_prefix ""`,
  `announce_chime_uri` the timer-chime path, `announce_require_mic_mute True`,
  `announce_max_chars 300`, `announce_mic_mute_entity ""`,
  `announce_mic_confirm_timeout_ms 2000`, `announce_mic_confirm_poll_ms 250`,
  `announce_chime_finish_timeout_ms 15000`, `announce_message_finish_timeout_ms 45000`,
  `announce_mic_deadman_ms 0`, `announce_volume_deadman_ms 0`, `announce_volume_deadman_retries 3`,
  `announce_min_call_timeout_ms 500`, `announce_max_prefix_chars 40`.
- `…test_overrides` — each is overridable from `config.json`.
- `…test_announce_volume_is_above_reply_volume_in_the_shipped_config` — reads the real `config.json`
  and asserts `announce_volume > reply_volume`. Guards against a future edit quietly making
  announcements quieter than replies.
- `…test_the_engineered_phase_budget_stays_under_the_rest_command_timeout` — asserts §6.5's
  **engineered phase budget** (all 16 rows, not just the polls) from the shipped defaults is below the
  documented `rest_command` timeout of 200 s. It checks the arithmetic stays self-consistent as
  timeouts are tuned; it does not claim the budget bounds wall-clock duration. This is the test that would have caught both rev 1's 370 s budget
  rev 2's 150 s under-count, and rev 3/4's overstated 187–190 s bound claims.
- `…test_marker_budget_and_mic_deadman_are_derived_from_the_same_table_and_differ` — pins that the two
  are distinct quantities (≈145 s vs ≈185 s) and that neither is silently reused as the other, which
  is the rev-2 error.

### 11.3 `tests/test_haconn.py`

- `ResolveMediaSourceTest.test_sends_the_resolve_command_and_returns_an_absolute_url`
- `…test_relative_url_is_absolutised_against_the_internal_base`
- `…test_missing_url_raises_rather_than_returning_none` (mirrors `TtsGetUrlTest`)
- `…test_a_non_http_result_is_rejected` (mirrors `TtsGetUrlAbsoluteTest`)
- `…test_never_touches_the_shared_websocket` — the direct analogue of the existing
  `CallServiceRestTest.test_never_touches_shared_websocket`
- `…test_closes_its_connection_on_failure`
- `…test_the_signed_url_is_never_logged` — asserts against captured log output
- `…test_the_timeout_is_passed_through_to_ws_connect` — the §6.5 timeout-clipping requirement: a
  nominal 10 s cannot be applied at all while `wsutil.py:7` hardcodes 15 s

*New timeout parameters (§6.5) — shared surface, so pinned on both sides*
- `GetEntityStateTimeoutTest.test_default_is_still_10s` — every existing caller unchanged
- `…test_an_explicit_timeout_is_passed_to_the_connection` — mirrors the existing
  `CallServiceRestTest.test_timeout_parameter_is_passed_to_connection`
- `WsConnectTimeoutTest.test_default_is_still_15s` — existing `HA.connect()` unchanged
- `…test_an_explicit_timeout_is_applied_to_the_connect_and_the_handshake_read` — the handshake `recv`
  loop currently inherits the connect timeout; the parameter must reach both or the ceiling leaks

### 11.4 `tests/test_interaction.py`

*Resolve / validate*
- `announce` is a valid mode; unknown modes are still rejected
- blank text rejected **before any `ha` call** (assert `ha.calls == []`)
- text over `announce_max_chars` **rejected** with `invalid_input`, `ha.calls == []`, and a
  `chat_text` that states the limit
- `test_no_code_path_truncates_the_message` — a message at exactly the limit is announced whole; one
  character over is refused. Pins goal 3 against a future "helpful" truncation.
- `test_the_bound_is_on_prefix_plus_message` — with a 40-char prefix configured, a 270-char message is
  accepted and a 280-char one is refused. Pins that config cannot defeat §6.5's timing model.
- `test_the_rejection_quotes_the_effective_limit` — the `chat_text` reflects
  `announce_max_chars - len(prefix)`, not the raw 300
- `test_an_over_long_prefix_is_dropped_not_fatal` — prefix over `announce_max_prefix_chars` → the
  announcement still plays, `metadata.prefix_dropped` set, an `error` logged
- `test_the_rendered_text_handed_to_tts_get_url_is_prefix_plus_message` — asserts on
  `FakeHA.tts_calls`, so the thing actually synthesised is the thing that was bounded
- `test_every_error_code_used_is_in_ERROR_CODES` — enumerates the codes `_announce` can emit and
  checks each against `command_result.ERROR_CODES`. `cr.err` raises `ValueError` on an unknown code,
  so an invalid one (the first draft used `precondition_failed`) turns a handled failure into a
  crash. Cheap, and it fails loudly at authoring time.

*Sequence*
- `test_golden_announce_call_order` — the §5 table, exactly: one mute, one pause, one
  `volume_set 0.80`, chime then message in order, one restore, one replay, one unmute
- `test_volume_is_announce_volume_not_reply_volume`
- `test_baseline_is_captured_once_and_restored_once`
- `test_source_is_replayed_once_after_both_clips`
- `test_volume_override_of_zero_is_honoured` — the `is None` vs `or` defect from §8.4(b)
- `test_chime_uses_a_query_stripped_match_key_and_tts_does_not`

*Chime degradation*
- resolve raises → message still played, `chime.played False`, result `ok`
- `announce_chime_uri` empty → single clip, `reason: "disabled"`
- chime `play_media` raises → message still played
- chime never starts → message still played

*Honest failure*
- `tts_get_url` raises → `err`, and `ha.calls == []` (nothing touched)
- message clip never starts → `err`, not `ok` (§8.5)
- `say_text` under the same condition still returns `ok` — the divergence is intentional and pinned

*Microphone*
- `test_mic_is_muted_before_the_first_audio_call` — asserts on call **index**, not just presence
- unmuted on success; unmuted when `_say` raises; unmuted when the message never starts
- `prev == on` → left on (the operator already had it muted)
- unresolved entity / read failure / write failure → `err unavailable`, no audio calls
- `announce_require_mic_mute: false` → broadcasts, `mic.muted`/`mic.confirmed` false

*Microphone — mute confirmation (§9.3)*
- `test_the_switch_is_read_back_before_any_audio` — a `switch.turn_on` that returns cleanly but whose
  state never reports `on` produces **no `play_media` at all**. This is the test that makes
  `announce_require_mic_mute` a real fail-safe rather than a claim.
- `…test_confirmation_polls_until_on_then_proceeds` — reports `off`, `off`, `on` via
  `FakeHA.set_states`; asserts the audio starts only after the third read
- `…test_confirm_timeout_is_bounded_and_refuses` — never reports `on` → `err unavailable`, and the
  poll count matches `announce_mic_confirm_timeout_ms / announce_mic_confirm_poll_ms`
- `…test_a_raising_confirm_read_refuses_rather_than_propagating` (row 9b)
- `…test_a_failed_confirmation_still_attempts_to_restore_prev_and_releases_the_lease`
- `…test_require_false_broadcasts_unconfirmed_and_says_so_in_metadata`

*Supersession — by a newer announcement (§9.6 row 2)*
- superseded mid-chime → no restore, no replay, **no unmute**
- superseded mid-message → same
- a second announcement **inherits the first's `prev`** and does not read the switch (the §9.2 rule)
- the second's unmute restores the original `prev`

*Supersession — by a NON-announcement (§9.6 rows 3–4) — the review regression*
- `test_a_satellite_reply_superseding_an_announcement_unmutes_immediately` — bump `_say_gen` mid-clip
  **without** writing `_mic`, then assert the mic-restore `switch.turn_off` **is** emitted while the
  volume restore and the source replay are **not**. This is the exact claim the first draft got
  backwards.
- `…test_a_say_text_turn_superseding_an_announcement_unmutes_immediately` — same shape via a real
  `say_text` call rather than a hand-bumped counter, so the test exercises the actual interleaving
- `…test_zone_supersession_does_not_transfer_the_mic_lease` — asserts `_mic[zone]["gen"]` is unchanged
  by a non-announcement turn, i.e. §9.1's sole-writer invariant
- `…test_the_dead_man_is_not_relied_on_in_this_path` — the unmute happens with the timer still
  pending, and the timer is cancelled rather than fired

*Stale pre-claimed generation (§9.2) — the adoption race*
The window is steps F–G only (§9.2), so every test here bumps `_say_gen` **after** the claim at E.
Rev 3 had two tests that bumped during TTS and chime resolution; those run *before* the claim, so
they could not exercise stale adoption at all and are replaced:

- `test_supersession_during_mic_state_capture_aborts_before_publishing` — bump `_say_gen` from inside
  the `get_entity_state` that reads the mute switch (§6.5 row 3, the widest single call in the
  window), then assert the announcement returns `superseded: true`, emits **no** `volume_set` and
  **no** `play_media`, and **does not** write `self._replies[zone]`
- `…test_supersession_during_the_mute_write_aborts_before_publishing` — bump from inside the
  `switch.turn_on` call (row 4)
- `…test_supersession_during_mic_confirmation_aborts_before_publishing` — bump during the confirm
  poll; **the most realistic case**, since it is the longest stretch where `_announce` is only waiting
  on another device
- `…test_resolution_happens_before_the_generation_claim` — the chronology guard: a bump from inside
  `tts_get_url` or `resolve_media_source` is **not** a stale adoption, because the claim has not
  happened yet; the announcement proceeds normally and claims a fresh generation. This pins §7's
  C/D-before-E ordering so the window cannot silently widen back out.
- `…test_a_stale_announcement_does_not_overwrite_a_newer_turns_marker` — the black-box version: start
  A, let a real `say_text` turn claim the zone **during A's mic confirmation**, then assert the newer
  turn's marker, baseline and restore all survive intact. This is the defect the race actually
  causes.
- `…test_an_aborted_stale_announcement_still_unmutes` — §9.2's corollary: the mic lease is still A's,
  so `_announce`'s `finally` releases it even though `_say` bailed at adoption
- `…test_a_non_stale_adoption_publishes_normally` — the happy path, so the guard cannot be satisfied
  by never adopting at all

*Fatal later-clip failure (§8.3a)*
- `test_chime_played_then_message_raises_replays_the_source` — the review's finding: `play_media`
  raises on the second clip; assert the finalizer emits `music_assistant.play_media` with the
  captured `source_id`
- `…test_no_replay_when_the_turn_dies_before_any_play` — the step-4 `volume_set` raises, so no
  `play_media` was ever attempted and the flag is still clear → un-pause path, no replay. It cannot be
  written as "the first `play_media` raises": the flag is claimed *before* that call, so a raising
  first play is an **ambiguous** failure and must replay (see the lost-ack block below).
- `…test_no_replay_when_superseded` — a newer turn owns the zone; replaying into it is the
  `CHANGELOG.md` 2026-09-06 clobber defect from the other direction
- `…test_exactly_one_replay_on_the_success_path` — step 9 and the finalizer must not both fire; this
  is also asserted by the §5 golden order
- `…test_unpause_fallback_when_there_is_nothing_to_replay` — flag set, `source_id` absent,
  `paused_by_us` true → un-pause, so the zone is not left paused and silent

*Lost-acknowledgement `play_media` (§8.3a) — the rev-3 hole*
- `test_lost_ack_on_the_chime_play_still_replays_the_source` — `FakeHA` mutates its own state to the
  chime **and then** raises; assert the finalizer replays `source_id` and does **not** un-pause
- `…test_lost_ack_on_the_message_play_when_it_is_the_only_clip` — the chime is disabled, so the
  message is the first and only play; the flag must already be set when it raises. Covers the
  message-only shape the review asked for explicitly.
- `…test_a_raising_first_play_replays_rather_than_unpausing` — the direct contrast with
  `test_no_replay_when_the_turn_dies_before_any_play` above: the flag is already set, so this is
  ambiguous and must replay. The two tests together pin exactly where the un-pause path ends.
- `…test_the_flag_is_set_before_the_call_not_after` — white-box ordering assertion; a success-gated
  flag passes every other test in this block and fails this one
- `…test_say_and_say_text_failure_path_replays_instead_of_unpausing` — pins the **intended**
  behaviour change to the shared reply path (§8.3a), so it is a decision on record rather than a
  surprise found later in a live reply

*Lost-acknowledgement volume raise (§8.4(c))*
- `test_a_lost_ack_on_the_volume_raise_still_restores_the_baseline` — `FakeHA` applies the write to
  its own state **and then** raises; assert the `finally` emits the restoring `volume_set`
- `…test_the_snap_target_sync_precedes_the_write` — so a later `_restore` or dead-man agrees with the
  device instead of classifying 0.80 as `user_override` and discarding the baseline
- `…test_a_redundant_restore_is_harmless` — the write never landed; the restore writes a value the
  zone already holds and the result is unchanged
- `…test_say_and_say_text_success_path_call_sequence_is_unchanged` — the §11.1 golden assertion,
  re-stated here because this fix touches shared `_say` code on a path replies also use

*Dead-man*
- mute arms a timer via `FakeTimer`; a normal exit cancels it
- firing restores `prev`
- firing does nothing once the generation has moved on
- the derived duration scales with clip count

*The §8.4(a) budget*
- an announcement's marker carries a `marker_budget_s` derived from §6.5's table
- a marker carrying `marker_budget_s` is not declared stale before it elapses
- a marker **without** `marker_budget_s` (every `say`/`say_text` turn) keeps today's threshold exactly

*Wall-clock deadlines and timeout clipping (§6.5)*
- `test_announcement_polls_use_a_wall_clock_deadline` — a `FakeHA` whose reads consume simulated time
  via the injected clock exits the poll on **elapsed time**, not on sleep count
- `test_say_and_say_text_still_bound_by_accumulated_sleep` — the deliberate divergence, pinned so a
  later unification is a conscious change rather than a drift
- `test_a_read_is_clipped_to_the_remaining_deadline` — with 3 s left on a phase, the
  `get_entity_state` call receives `timeout=3`, not the 10 s default. Asserts on the timeout actually
  passed, which is the only thing that makes the bound real.
- `…test_no_blocking_call_is_started_below_the_floor` — with 0.2 s left and a 500 ms floor, the phase
  ends and **no** further read is issued
- `…test_total_overshoot_stays_within_one_floor_per_phase` — the residual §6.5 quotes (~3 s across
  five phases), so the 190 s figure is asserted rather than asserted-about
- `…test_mic_confirmation_reads_are_clipped_too` — the confirmation poll is one of the five bounded
  phases and is easy to overlook

*Volume dead-man for an unducked turn (§9.7)*
- `test_an_unducked_announcement_arms_a_volume_recovery_timer` — no duck snapshot → a timer is armed
  when `pending_restore` is claimed
- `…test_a_ducked_reply_arms_no_second_timer` — a satellite reply has `max_duck_timeout` already; two
  timers on one zone would fight
- `…test_a_successful_restore_cancels_it` (both step 8 and the finalizer paths)
- `…test_firing_restores_the_baseline_when_the_zone_is_still_at_announce_volume`
- `…test_firing_does_nothing_when_a_newer_turn_owns_the_zone`
- `…test_firing_leaves_a_human_changed_volume_alone` — the `user_override` courtesy `_restore` already
  extends
- `…test_retries_are_bounded_then_it_logs_error_and_stops` — unlike `_auto_restore`'s unbounded
  re-arm
- `…test_returned_metadata_is_only_restored_or_deferred_to_deadman` — §9.7's honest surfacing. There
  is deliberately **no** `"failed"` value: the result is serialised before the timer can run, so a
  terminal failure cannot reach it.
- `…test_terminal_exhaustion_logs_at_error_and_returns_nothing` — the only witness to an unrecovered
  volume is the resolver log, which is why that path logs at `error`
- raising `announce_message_finish_timeout_ms` widens the derived budget, the dead-man and the
  documented `rest_command` timeout requirement together — they are computed from one place

*Dead-man duration (§6.5/§9.5)*
- `test_derived_mic_deadman_is_about_185s_with_shipped_defaults` — pins the corrected derivation
  (§6.5 rows 5–16 plus 30 s) and would fail against both rev 1's ~400 s formula and rev 3's mislabelled
  145 s
- `test_explicit_announce_mic_deadman_ms_overrides_the_derivation`

*Result text (§5.2)*
- `test_success_chat_text_is_announced_not_said` — `_announce` must not leak `_say`'s generic
  `"Said."` to the phone
- `test_each_failure_carries_an_operator_readable_chat_text` — every `err` path in §10 has non-empty
  `chat_text`, since that string *is* what the operator sees

*Anti-regression on the broken path*
- `test_announce_never_uses_tts_speak_or_play_announcement` — the sibling of the existing
  `SayTextTest.test_it_never_uses_the_broken_announce_path`

### 11.5 Integration (live, approval-gated — G3/G4a/G4b, not part of the code gate)

1. `/command` with `{"intent":"interaction","params":{"mode":"announce","text":"test"}}`, ceiling
   **idle**. Expect: chime, speech, no restore needed, mic back to `off`.
2. The same with music **playing**. Expect the §5 golden order, and the station back at its original
   volume.
3. Two announcements ~1 s apart. Expect the second to supersede, and the mic to end `off` — the §9.3
   inheritance rule, live.
4. From the **phone**, both sentences, with music playing and with the ceiling idle.
5. Read the satellite's pipeline traces afterwards (`assist_pipeline/pipeline_debug/list`, per
   `ONBOARDING.md` §4) and confirm **no run** was recorded during the announcement. This is the
   acceptance test for requirement 6 — the resolver log cannot show it, because a self-wake never
   reaches the resolver.
6. **Timeout path (§6.5).** Announce a message at `announce_max_chars`, and confirm the phone gets
   `"Announced."` rather than a timeout — i.e. that the `rest_command` timeout is genuinely above the
   real wall-clock duration, not merely above the nominal budget. Record the observed duration; it is
   the only measurement of the accumulated-sleep undercount we will have.
7. **Failure delivery (§5.2).** Force one refusal end to end — easiest is temporarily pointing
   `announce_mic_mute_entity` at a non-existent entity — and confirm the **phone displays the
   resolver's `chat_text`**, not a generic Assist error. Untested, §5.2 is just an intention.
8. **Source behaviour (§5.1).** Say the same sentence to the **satellite**. Record what actually
   happens, and whether the trigger's template data offers a usable phone/satellite discriminator
   (D12). This determines whether §2's exclusion becomes a gate or a documented behaviour.

---

## 12. SPIKE-AN — chime, microphone and source feasibility (first gate, NOT executed)

**Not run as part of this design.** It is the first gate of implementation and requires operator
approval, a quiet moment in the house, and one audible clip.

Three questions, one sitting. All are pure discovery, and each can invalidate design choices above.
AN-3 is the cheapest and needs neither audio nor operator ears, so it can run first.

### SPIKE-AN-1 — will MA fetch and play a signed HA media URL?

*Question.* Can `media-source://media_source/local/./timer_chime.wav` be resolved to a URL that
`music_assistant.play_media` will actually fetch and play on `media_player.ceiling_speakers`?

*Steps* (from the host; step 2 is the only audible action)
1. Fresh WS to HA, `media_source/resolve_media` on the chime URI. Record: the URL's **shape**
   (relative or absolute), whether it carries a signature, and the signature's **lifetime**.
2. Absolutise against `192.168.122.10:8123` and call `music_assistant.play_media` on the ceiling.
3. Poll `/api/states/media_player.ceiling_speakers` at 500 ms and record the state sequence and,
   critically, **the exact `media_content_id` MA echoes** — with or without the query string.
4. Note the time from call to audible sound, and the clip's duration.

*Go criteria — all five*
- (a) `resolve_media` returns a URL.
- (b) MA accepts it — no `Only URLs are supported for announcements`, no `401`.
- (c) The player reaches `playing` within `say_start_timeout_ms` (5 s).
- (d) **The operator hears the chime.** Non-negotiable: `ONBOARDING.md` §5 and the whole S1b history
  are about routes that reported success and played nothing.
- (e) A stable containment `match_key` is derivable from the echoed `media_content_id` (§8.2).

*No-go fallbacks, in preference order*
1. **Piper-spoken attention token** — set `announce_chime_uri: ""` and `announce_prefix` to a short
   utterance. Zero new route, works today, single clip. The clip-sequence work still lands and stays
   exercised by the two-clip tests, but ships disabled.
2. **Serve the WAV from the resolver's own HTTP server** — needs a static-file route plus a
   `_normalise_uri` bypass. `CHANGELOG.md` 2026-09-05 already judged this "surface for no real
   gain"; recorded for completeness, not recommended.
3. **Ship without an attention signal** — `announce_chime_uri: ""`, `announce_prefix: ""`. Least
   good: an announcement's first words get missed.

Note that fallback 1 **inverts requirement 13's default** (prefix empty because the chime is the
signal). That inversion is a no-go consequence, not a design change, and would be recorded as such.

### SPIKE-AN-2 — does the mic-mute switch actually stop the wake word?

*Question.* What is the switch's exact entity ID, and does turning it on prevent wake-word detection
— or does it only mute an audio stream while the on-device wake engine keeps listening?

*Steps*
1. `GET /api/states`, filtered to the satellite's `switch.*` entities. Record the exact
   `microphone_mute` ID (D1) and its current state.
2. Turn it on, then poll `/api/states` and **measure how long the switch takes to report `on`**.
   This sizes `announce_mic_confirm_timeout_ms` (§9.3) — 2 s is a guess until measured, and too tight
   a budget turns every announcement into a refusal. Note also whether the satellite emits a mute
   feedback sound (`switch.…_mute_unmute_sound` is on) and whether it is audible at all, given the
   satellite has no speaker (D6).
2a. Repeat with the satellite's ESPHome API **disconnected** if that can be arranged safely — the
   `Errno 113` condition in `CHANGELOG.md`. The question is whether HA accepts the `switch.turn_on`
   and reports `on` optimistically, or correctly leaves it `off`/`unavailable`. If HA reports `on`
   for an unreachable device, the read-back in §9.3 does not prove muting either, and requirement 7
   needs a different mechanism. **This is the single most important unknown in the mic design**
   (D14).
3. Speak the wake word twice, then a full sentence.
4. Check `assist_pipeline/pipeline_debug/list` for **any** new run.
5. Turn it off. Confirm the wake word works again.

*Go criteria*
- (a) The exact entity ID is established.
- (b) **No pipeline run** is recorded while muted.
- (c) The switch reliably returns to its prior state.
- (d) Any feedback sound is inaudible in the room.
- (e) The state reports `on` well inside a budget worth shipping — if it takes seconds, say so and
  set `announce_mic_confirm_timeout_ms` from the measurement rather than from the guess.
- (f) An unreachable device does **not** report `on` (D14). If it does, §9.3's read-back is not
  proof of muting and §9 reopens.

*No-go.* If muting does not suppress wake detection, requirement 6 cannot be met this way, and the
options become: LED / `beam_lock` experimentation; suppressing runs *after* the fact (the softer
option weighed and rejected in brainstorming, which still lets room audio reach STT and, on slot 2,
web search); or shipping with `announce_require_mic_mute: false` and accepting self-wake as a known
wart. **This design does not pre-choose** — a no-go here reopens §9 and warrants a fresh decision
with the measurement in hand.

### SPIKE-AN-3 — is there a dependable phone/satellite discriminator?

*Question.* Can a sentence trigger tell **which source** invoked it, reliably enough to gate on
(§5.1, D12)?

*Steps.* Add a **temporary, throwaway** sentence trigger on a nonsense phrase whose only action logs
the full trigger payload (`trigger.device_id`, `trigger.satellite_id` if the core exposes it,
`trigger.details`, `trigger.user_input`). Speak it from the phone, then from the satellite, then from
the HA web Assist dialog. Compare payloads. Remove the trigger.

*Go criteria.* A field that is (a) present and (b) **different** across all three sources, and (c)
stable across repeats.

*No-go.* No gate. §2's "preferred excluded" becomes "accepted and documented", §5.1's fallback
paragraph applies unchanged, and the `ONBOARDING.md` §4 note records that announcements can be
triggered from the satellite too. **No design change is needed for the no-go path** — that is the
point of having written §5.1 as a preference rather than a guarantee.

*Cheaper than it looks:* this is the only one of the three spikes that needs no audio, no quiet
moment, and no operator ears — just a temporary trigger and three utterances. It could run first.

---

## 13. Staged implementation and deployment gates

Each gate ends in a state that is safe to stop at.

| Gate | Work | Lane | Approval | Exit criteria |
|---|---|---|---|---|
| **G0** | This design reviewed and approved | docs | operator | Design approved; only then is an implementation plan written |
| **G1** | **SPIKE-AN-1 + AN-2 + AN-3** (§12) | host-live / HA-live | operator, plus a quiet moment | Go/no-go recorded; D1–D6, D12 and D14 resolved; chime route, mute entity, confirm budget and source gating all fixed |
| **G1b** | **Inspect only.** Read the live `rest_command.resolver_command` definition and its current timeout (D8/D13); **decide and record** the §6.5 shape — a second rest_command vs. raising the shared one | HA-live | operator (read-only) | The current definition and timeout are written down, and the chosen shape is recorded. **Nothing is configured here** — inspection cannot change a timeout, which is what rev 2's exit criterion wrongly claimed. |
| **G2** | Repo code: `haconn.resolve_media_source`; **`haconn.get_entity_state` and `wsutil.ws_connect` gain `timeout` parameters** (§6.5 — without these, `resolve_media_source` cannot be bounded at all and a nearly-expired phase still blocks on a full default); `config.py`/`config.json` settings; `interaction.py` `_play_clip_and_wait` extraction, the `announce` mode, the §8.3a replay obligation, the §8.4 fixes and the §9.7 volume dead-man; all of §11.1–§11.4 | repo, **worktree + PR** | none needed — offline | Golden say/say_text sequences unchanged; new tests green; `py_compile` clean under 3.5; PR merged to `main` |
| **G3** | Host deploy | host-live | operator runs the restart | Backup to `~/mass-resolver/.bak/<ts>/`; host 3.5.2 `py_compile` OK; host `test_interaction.py` OK; restart; `/command` bound; zero tracebacks; §11.5 items 1–3 pass |
| **G4a** | **Write gate — REST command.** Create `rest_command.resolver_command_announce` with `timeout: 200` (or, per G1b's decision, raise the shared one), back up the prior `configuration.yaml` / packages fragment first, and reload | HA-live | operator | The announcement REST command exists with a ≥200 s timeout; **no existing caller's timeout changed** (or, if the shared shape was chosen, the change is recorded with its latency exposure). Verified by one `/command` round trip through it. |
| **G4b** | Live HA: the two sentence triggers on `automation.voice_ceiling_speakers`, pointed at the G4a command, plus the §5.2 `response_variable` / `choose` / `set_conversation_response` block and the §5.1 source condition if D12 allows one | HA-live / exposure | operator | Automation JSON backed up first (the 2026-09-06 precedent); §11.5 items 4–8 pass |
| **G5** | Docs | docs | none | §13.2 files updated; `CHANGELOG.md` entry written from what actually happened |

**Lane discipline.** G1, G1b, G3, G4a and G4b all claim the single `host-live / HA-live / exposure` lane that
`BACKLOG.md:306` tracks. It currently reads **FREE**. Each gate claims it and releases it on
completion, as `S1b-1′` did.

**Worktree discipline.** `CLAUDE.md` requires every repository change in an isolated worktree off
`origin/main`, integrated by PR. G2 and G5 follow that. (This design document itself is committed as
`259c730` on the `homebrain/an-01-design` branch and is being integrated by PR.)

### 13.1 Rollback, per gate

| Gate | Rollback |
|---|---|
| G2 | `git revert` the PR. Nothing is deployed. |
| G3 | Restore `~/mass-resolver/.bak/<ts>/{haconn,interaction,config}.py` and `config.json`, then restart. **Rarely needed:** no existing mode changes behaviour, and with no caller the `announce` mode is inert code. |
| G3, softer | Config-only, no code change: `announce_chime_uri: ""` disables the chime; `announce_require_mic_mute: false` drops the mute precondition; `announce_volume` down to `0.70` matches replies. |
| G4a | Restore the backed-up config fragment and reload. If the **second-command** shape was used, the blast radius is zero — no existing caller referenced it. If the **shared timeout** was raised, restoring returns every caller to its prior timeout. |
| G4b | Restore the `automation.voice_ceiling_speakers` JSON backup. **This is the real kill switch** — with the sentence triggers gone, nothing calls `mode=announce`, and G4a's command becomes an unused definition. |
| G5 | `git revert`. |

### 13.2 Documentation updated during implementation

| File | Change |
|---|---|
| `CHANGELOG.md` | New dated entry: the spike result, the deploy, the live verification, and anything that went wrong. Written from observed behaviour, not from this design. |
| `ONBOARDING.md` §4 | Add `announce` to the `interaction` modes; note the two new sentences on `automation.voice_ceiling_speakers`; note that `announce` is **not** exposed to ChatGPT. |
| `ONBOARDING.md` §5 | Add announcements to "What works", held to the same "verified, operator-eared" standard as `say_text`. |
| `ONBOARDING.md` §2/§4 | Record whichever §6.5 shape was chosen — a second `rest_command.resolver_command_announce` with its 200 s timeout, or a raised shared timeout and the latency exposure that adds to the five exposed scripts. This is live config that exists nowhere in the repo, so the doc is the only record. |
| `ONBOARDING.md` §4 | If D12 finds no source discriminator, state plainly that announcements can also be triggered from the satellite — an un-enforced exclusion documented is fine; one silently assumed is not. |
| `ONBOARDING.md` §6 | Amend the satellite false-wake entry: announcements now mute the mic for their own audio; ambient false wakes are unchanged. |
| `BACKLOG.md` | **Append** a dated reconciliation note to the `S1b`–`S4` row (`:185`) recording that the 2026-07-16 "audible announce blocked" status was superseded by `say_text` on 2026-09-05 — leaving the original wording intact. Add an `AN-01` row. Update the lane table at `:306` on each claim and release. |
| `assistant-capabilities.md` | A short note that announcements are **deliberately not** an LLM-exposed tool, and why (`CHANGELOG.md` 2026-09-06's take-the-model-out-of-the-loop lesson). No exposure-lockstep (NL-02) work is needed, because nothing new is exposed. |
| `runbooks/quick-connect-and-health-check.md` | One line: if the satellite has gone deaf, check the mic-mute switch — a crashed announcement can strand it (§9.5). |
| This document | Status header updated as gates pass. |

---

## 14. Unresolved deployment discoveries

**These are not design decisions.** Each is a fact about the live system that this design deliberately
does not assume, and each is resolved by observation at G1 or G3 — not by choosing an answer now.

| # | Discovery | Resolved at | If it goes the other way |
|---|---|---|---|
| **D1** | The exact `switch.…_microphone_mute` entity ID. `s0-satellite-inventory.md` records only a placeholder. | SPIKE-AN-2 | `announce_mic_mute_entity` ships `""`, so nothing can announce until it is set. |
| **D2** | Whether that switch suppresses **wake-word detection** or only mutes a stream. | SPIKE-AN-2 | Reopens §9 — see the AN-2 no-go. |
| **D3** | The `media_source/resolve_media` URL shape: relative or absolute, signed or not, and the signature's TTL. | SPIKE-AN-1 | A long TTL would permit caching; the design resolves per announcement regardless, which is correct either way. |
| **D4** | Whether MA will fetch a **signed** `/media/local/...?authSig=…` URL. The recorded `401` was for an unsigned path and the "Only URLs" error for `media-source://`; neither tested this. | SPIKE-AN-1 | AN-1 fallback 1 (Piper attention token). |
| **D5** | Whether MA preserves the **query string** in the `media_content_id` it echoes back. | SPIKE-AN-1 | The §8.2 query-stripped match key exists precisely for the stripping case; if it also strips the path, the chime clip needs a different confirmation strategy. |
| **D6** | Whether the mute/unmute feedback sound is audible (`switch.…_mute_unmute_sound` is on; the satellite has no speaker). | SPIKE-AN-2 | Turn that switch off for the announcement window, or leave it off permanently. |
| **D7** | How HA normalises sentence-trigger wildcard text (lower-casing, punctuation), and how flat Piper reads the result. | G4b | Cosmetic. Would motivate light re-punctuation before TTS, or the voice work in `CHANGELOG.md` 2026-09-05 note #1. |
| **D8** | The exact `rest_command.resolver_command` payload shape for `params` — live HA config, not in the repo. | G1b (read), G4a (write) | Copy the shape `satellite_timer_announce_on_ceiling` already uses for `say_text`. |
| **D9** | The real gap between chime end and speech start on this player. `CHANGELOG.md` measured **1.5 s** from the satellite's own chime to speech; MA-played back-to-back clips are unmeasured. | G3 | A long gap makes the chime feel disconnected; `say_blank_cid_grace_ms` and the `ended_seen` rule are the tuning surface. |
| **D10** | ~~How often a satellite reply strands the mute until the dead-man~~ — **WITHDRAWN at review.** It was not a discovery, it was an error: `_mic` is written only by `_announce` (§9.1), so a satellite reply never takes the lease and §9.4 unmutes immediately. Kept as a numbered entry so the correction is traceable rather than silently vanished. | n/a — resolved by design | Pinned by the §11.4 non-announcement supersession regression tests. |
| **D11** | Whether `announce_volume: 0.80` is actually the right loudness in the room. | G3, by ear | Config-only change. |
| **D12** | Whether any sentence-trigger template field (`trigger.device_id`, `trigger.satellite_id`, `trigger.details`) dependably distinguishes phone from satellite from web Assist. Official documentation does not establish one. | SPIKE-AN-3 | No gate: satellite invocation is accepted and documented (§5.1), and §2's row already says so. No design change. |
| **D13** | The **current** timeout on the live `rest_command.resolver_command`, and whether a second announcement-specific rest_command is cleaner than raising the shared one (§6.5). | G1b (read-only inspection) | If the shared timeout must rise, note the latency exposure it adds to the five ChatGPT-exposed scripts. |
| **D14** | **Whether HA reports a `switch` as `on` for an unreachable ESPHome device.** If it reports optimistically, §9.3's read-back does not prove muting and requirement 7 needs a different mechanism. | SPIKE-AN-2 step 2a | Reopens §9. The fallbacks are an availability check on the satellite's own entities before announcing, or accepting `announce_require_mic_mute: false`. |

---

## 15. Summary of decisions

1. Deterministic HA sentence triggers with a greedy wildcard — `announce {message}` and
   `broadcast {message}` — on `automation.voice_ceiling_speakers`. No LLM in the path. Phone is the
   intended source but **not an enforced one** until D12 says a dependable discriminator exists
   (§5.1).
2. A new `interaction` mode **`announce`**, reached over an authenticated rest_command carrying the
   200 s timeout §6.5 requires — preferably a dedicated
   `rest_command.resolver_command_announce`, so no existing caller's timeout moves (D13).
3. `_say` gains a **clip loop** and nothing else. Generation ownership, baseline capture, the single
   volume raise, the single restore, the single replay and the release all stay outside the loop;
   per-clip play/start/finish polling goes inside it, extracted into `_play_clip_and_wait`.
4. `say` and `say_text` keep their public contract and success-path call sequence, with §8.3a's safer
   ambiguous-failure recovery as the one documented exception (goal 7). The new `resolved` keys are all optional,
   and the guarantee is proven by golden call-sequence tests written before the refactor.
5. Microphone ownership is modelled on the existing duck/reply ownership chain: pre-claimed
   generation, inherited `prev`, **write then confirm by reading** (an accepted service call is not a
   muted microphone), restore only if the **lease** is still ours, and a dead-man failsafe. `_mic` is
   written **only** by `_announce`, which is why a non-announcement supersession unmutes immediately
   rather than stranding the mute.
6. Failures are honest, staged so the cheap ones cost nothing, and **actually delivered**: a TTS
   failure fails before anything is touched; an over-long message is **rejected, never truncated**; a
   chime failure degrades; a **silent announcement is an error, not a success**; and every one of
   those reaches the operator's phone via `set_conversation_response` (§5.2). Error codes come from
   `command_result.ERROR_CODES` — `unavailable`, not an invented one.
7. Every timeout is derived from the **bounded** message size, not from the knowledge agent's
   180 s reply budget, because `/command` blocks HA's `rest_command` for the whole turn (§6.5). One
   derivation feeds the per-clip budgets, the reply-marker staleness threshold, the mic dead-man and
   the required `rest_command` timeout, so they cannot drift.
8. The chime is the unproven piece, and it is gated behind a spike with an operator-eared go criterion
   and three ranked fallbacks.
9. `BACKLOG.md`'s stale "blocked" wording is reconciled by **appending** a dated note, not by
   rewriting the record.

---

> **Rollback for this document:** delete the file, or `git revert` the commit that adds it.
