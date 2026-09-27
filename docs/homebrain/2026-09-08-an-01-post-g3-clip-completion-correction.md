# AN-01 — Post-G3 Design Correction: a clip's completion is not observable

> **Status:** Recorded 2026-09-08 from measurement at G3. **Amends §6.5 and §8.3** of
> [`2026-09-06-phone-assist-ceiling-announcement-design.md`](./2026-09-06-phone-assist-ceiling-announcement-design.md)
> (commit `259c730`, rev 5, G0-approved), and follows
> [`2026-09-07-an-01-post-g1-design-corrections.md`](./2026-09-07-an-01-post-g1-design-corrections.md).
>
> **Append-only.** Those sections are **left exactly as written** — they are an accurate record of
> what was believed at G0 and G2 — so read this alongside them. The convention is §3.6's: append a
> dated correction, never rewrite history.
>
> **Scope:** one measured fact and its consequences. It does not change the clip-sequence state
> machine, the mic lease, the generation model, the dead-men, the recovery paths, or any failure row.
> Every one of those was exercised at G3 and behaved as designed.
>
> **No fix is specified here.** This records what is wrong and why it matters. The remedy is a
> separate decision, pending a read-only measurement of whether HA reports a usable duration for such
> a clip.

---

## The measurement

G3 Task 24 step 4, announce with the ceiling paused, message `"test announcement"` (17 characters).
Deployed code from `main` `4cb2869`. From `resolver.log`:

```
17:10:18.433  SAY start … clip=d2742595 baseline=0.4 prev=0.4 reply_volume=0.8
17:10:25.060  clip=f3ff7804 finish-poll exit after 6.0s: state=idle cid=builtin://track/…/timer_chime.wav?authSig=R
              (45.8 s with no log line at all)
17:11:10.907  restored -> 0.4
17:11:10.908  mic restored
```

`/command` returned in **52.7 s**. A state read taken **4 s after the call returned** still showed:

```
playing | 0.4 | builtin://radio/http://192.168.122.10:8123/api/tts_proxy/H65P50….mp3
```

Every asserted field passed: `ok True`, `chat_text "Announced."`, `announced True`,
`chime {played: True}`, `mic {muted: True, confirmed: True}`, `volume_restore "restored"`, both clips
`started` and `issued`. The defect is entirely in **when** the turn ended.

## The fact

**Music Assistant wraps by media type, and the wrapper decides whether an end exists.**

| Clip | Wrapper | Ends? |
|---|---|---|
| chime, a `.wav` file | `builtin://track/…` | **yes** — reached `state=idle`, detected in 6.0 s |
| Piper speech, an `.mp3` behind `tts_proxy` | `builtin://radio/…` | **no** — a *stream*; the player stays `state=playing` on that cid indefinitely |

Correction 1 of the post-G1 document recorded that MA wraps by media type, and that `track` was
unanticipated. What was not appreciated then is the **consequence**: the wrapper determines whether a
completion event exists at all. A `radio`-wrapped clip has no end to observe.

## Correction to §8.3 — "per-clip outcomes" presumes an observable end

§8.3 tabulates each clip's outcome — started, never started, ended, superseded — and the design's
`_play_clip_and_wait` detects an end three ways:

1. **two consecutive `ended` observations** — `state != playing`, or a cid naming something else.
   For a `radio`-wrapped clip this **never occurs**.
2. **the blank-cid grace** — MA transiently reports an empty `media_content_id`; after
   `say_blank_cid_grace_ms` (8 s live) that is treated as finished. This is what `say_text` has in
   fact always relied on: G3 step 3 logged `cid stayed empty for 8.0s (state=playing)`.
3. **the finish budget** — a timeout.

For the message clip, (1) is unavailable by construction and (2) is not guaranteed — it did not occur
at all in step 4. **So (3) is the only reliable exit, and a timeout is not a detection.**

§8.3 should be read as: *the chime's outcome is observed; the message clip's is inferred from a
timeout unless the transient blank happens to occur.*

## Correction to §6.5 — the message finish timeout is a duration, not a ceiling

§6.5's table was renamed at G0 approval so its column reads **Nominal allowance**, precisely to avoid
claiming the numbers were bounds. That care was well placed but insufficient: the table's arithmetic
still assumed each phase would **usually finish early**, with the allowance covering the bad case.

Measured, that is false for one row. `announce_message_finish_timeout_ms` (45 s) is not the worst case
for the message clip — it is **the ordinary case**, because nothing else ends the poll. The engineered
190 s figure remains an arithmetic self-consistency check and is not violated; what changes is that
the **typical** announcement costs ~53 s rather than the ~15 s the model implied.

This also means §6.5's deadline machinery is working correctly and is not the problem: the per-clip
budget was enforced exactly as specified. The specification is what is wrong.

## Why this is a requirement-7 failure, not a performance note

Requirement 7 mutes the satellite microphone **for the announcement**, so the satellite cannot wake on
the resolver's own audio. The lease is released in `_announce`'s `finally`, after `_say` returns.
Because the turn's length is set by the budget rather than by the speech:

- the microphone was muted **~53 s** for ~2 s of speech;
- the ceiling was held at announcement volume **0.8 for ~45 s after the speech ended**;
- anyone speaking to the satellite in that window is **not heard, and has no way to know why**.

A fail-safe an order of magnitude wider than the thing it protects is not calibrated. The design's
intent — mute for the clip — is not met by the implementation of §8.3 as specified, which is why this
is recorded as a **failure against requirement 7** rather than as a slow path.

## A second, independent defect — budget exhaustion is unlogged

`_play_clip_and_wait` logs the ended-twice exit and the blank-grace exit. Falling out of the poll loop
because the budget expired writes **nothing**. The operator sees `SAY start`, a 45 s hole, then
`restored`. At G3 this was diagnosable only by subtracting timestamps across two log lines.

This is a design-level omission in §8.3's observability, not merely a missing log call: the failure
mode the design most needs to see is the one it cannot see. **A budget exit must log at warning with
the clip fingerprint and the elapsed time**, independently of how completion detection is fixed.

## What does not change

- **§8.2's containment matching** and the full-URI match keys from the post-G1 correction. Both clips
  matched correctly; that is why both reported `started: True`.
- **§9.1–§9.5, the microphone lease.** Mute confirmed after **2 polls**, consistent with AN-2's 255 ms;
  the dead-man armed at **184 s**, matching the derived budget, and correctly did **not** fire; the
  lease was released on the way out and the switch returned to `off`.
- **§9.7, the volume dead-man**, and **§8.4(c)**: `volume_restore` reported `restored` and the ceiling
  returned to the captured `0.4`.
- **§8.3a, the ambiguous-play recovery.** Not exercised at step 4 (nothing failed), and untouched here.
- **§6.1's no-logging rule.** Confirmed working live: the chime's finish-poll line reads
  `…timer_chime.wav?authSig=R`, which is `authSig=REDACTED` cut by the 80-character truncation. The
  credential never reached the log.
- The **200 s** `rest_command` timeout is not at risk. The budget does not scale with message length,
  so a 300-character announcement lands near the same ~53 s.

## Open, and what settles it

Whether HA reports a usable `media_duration` / `media_position` for a `builtin://radio/`-wrapped TTS
clip. If it does, the poll can exit on a **detected** end and the mute window tracks the speech. If it
reports `null` — which is common for a stream — that option is unavailable and the remedy must be
chosen from weaker ones.

That is a **read-only** question and must be answered before any remedy is designed. It does not
require playing audio: the attributes recorded during G3's own clips are retrievable from Home
Assistant's history.

**G4a and G4b remain blocked** until the mute window tracks the announcement. Sentence triggers would
expose this window to the household.

## Result of the read-only spike — appended 2026-09-08

Answers the *"Open, and what settles it"* question above. That section is left as written; this is the
result appended beneath it.

**Method: read-only, and nothing was played.** Home Assistant's recorder had already captured the
`media_player.ceiling_speakers` attributes while G3's own clips were playing, so the question was
answered from history rather than by generating new audio. HA 2026.6.4, recorder enabled, rows
returned for both windows.

| Clip | Wrapper | `media_duration` | `media_position` | `media_position_updated_at` | Reaches `idle`? |
|---|---|---|---|---|---|
| Piper speech, step 3 (16:50) | `builtin://radio/…tts_proxy…` | **None** | **None** | **None** | **no** |
| Piper speech, step 4 (17:10) | `builtin://radio/…tts_proxy…` | **None** | **None** | **None** | **no** |
| chime, step 4 (17:10) | `builtin://track/…timer_chime.wav` | **4** | None | None | **yes**, at 23:10:24 |
| live radio stream, for contrast | `library://radio/4` | None | **1101**, updating | present | n/a |

**Option A is ruled out.** Exiting the finish poll on `media_position >= media_duration` is
impossible for the clip that matters: *both* fields are `None`, across three samples in two separate
turns.

Two facts from the same data matter more than the negative result:

1. **The wrapper decides everything.** A `track`-wrapped clip reports a duration **and** reaches
   `idle`; a `radio`-wrapped one does neither. Same player, same turn, about seven seconds apart.
   This is the mechanism behind this correction's central claim, now measured directly.
2. **The TTS clip is the worst case.** A genuine radio stream at least reports a moving
   `media_position`; the radio-wrapped TTS clip reports no duration, no position and no end.

*Confidence:* recorder rows are state-change rows, so the absence of intermediate rows across the
45 s is itself consistent with nothing updating. A live poll during a clip would be belt-and-braces
confirmation, but it requires audio.

## Option D — ask MA for a `track` (recommended next spike)

A second read-only spike read HA's service registry:

```
service: music_assistant.play_media
    media_id     required=True
    media_type   required=False  options=['artist','album','audiobook','folder',
                                          'playlist','podcast','track','radio']
    enqueue      required=False  options=['play','replace','next','replace_next','add']
    radio_mode   required=False
```

**The resolver does not pass `media_type`.** `_play_clip_and_wait` sends only
`{"entity_id": zone, "media_id": norm_uri}`, so MA infers the type — and infers `radio` for a
`tts_proxy` URL while inferring `track` for the chime's `/media/local/…wav`.

**Option D: pass `media_type: "track"` for the speech clip.** If MA then wraps it as a track, the
clip reaches `idle` and §8.3's existing ended-twice detection works **unchanged** — no new detection
logic, no duration estimates, no timing guesses — and the mute window tracks the speech, which is
what requirement 7 asks for. It addresses the cause identified above rather than the symptom.

**Not yet verified, and the gap is stated plainly.** MA chose `track` for the chime unprompted;
whether an *explicit* `media_type: track` makes MA treat a `tts_proxy` URL as a finite track is a
strong inference from the table above, **not a measurement**. It needs **one attended, audible
spike** — a single `say_text` with the parameter added, watching whether the state reaches `idle` and
a duration appears. That cannot be done read-only, and it is **not authorised** as of this append.
Failure costs nothing: MA would ignore or reject the parameter and behaviour would be unchanged.

## Option C — retained as the fallback

If D fails, estimate the clip's length from the message's character count using a measured
chars-per-second rate for `tts.piper`, and bound the finish poll by
`min(estimate × slack, budget)`. It needs no new signal and degrades gracefully, but it is
**open-loop**: a mis-estimate either truncates the speech or waits too long, and the rate varies with
punctuation, language and voice — this house mixes Russian station names with English sentences. It
treats the symptom, so it is the fallback rather than the choice.

Tuning the finish budget or the blank-cid grace remains a **stopgap only**, for the reason already
recorded: the budget cannot go below the longest legitimate clip, so any value that helps a
seventeen-character message risks truncating a three-hundred-character one.

## Unconditional, whichever remedy is chosen

The budget exit must log at warning with the clip fingerprint and the elapsed time — the second
defect recorded above, independent of how completion is detected. While there, the turn-level `clip`
fingerprint is computed from the **raw** URI while the per-clip one is computed from the
**normalised** URI, so a single turn logs two different ids and defeats the correlation `_clip_id`
exists for. Cosmetic, one line, and it belongs in the same commit.

**G4a and G4b remain blocked.**

## Option D FAILED, and it falsifies this document's central claim — appended 2026-09-09

An attended spike measured Option D. It did not work, and the control it produced overturns the
mechanism this correction asserted above. **The sections above are left exactly as written** — they
record what was believed on 2026-09-08 — and this is the correction to them.

### What was tried

A temporary build passed `media_type: "track"` on the clip's `play_media`, inert by default and
enabled by one temporary config line. Deployed through the normal procedure: byte-identical copies
verified by sha256, `COMPILE OK` and 442 tests on host Python 3.5.2, health green, operator-run
restart, then **exactly one** short `say_text` with the operator listening. Reverted immediately
afterwards.

### Result — no effect

| Measure | Result |
|---|---|
| Reached `idle`? | yes, at +5.0 s; the finish poll exited `state=idle` after 2.5 s |
| **`media_duration`** | **`None` — unchanged** |
| `media_content_id` | **still `builtin://radio/…tts_proxy…`** — MA did not wrap it as a track |
| `media_position` | 0 → 2 |
| elapsed | 4.39 s |
| volume | 0.4 → 0.7 → **0.4 restored** |
| mic mute | `off` throughout (a `say_text` does not lease it) |

The criterion set for the spike was *reach `idle` **with a duration***. The duration stayed `None`
and the wrapper did not change, so **Option D failed**. Asking MA explicitly for a track had no
observable effect on a `tts_proxy` URL.

### The control — why the clean exit proves nothing about the spike

The resolver log carries a `say_text` from **2026-09-08 18:36:09**, on the **pre-spike** build:

```
SAY req=8200a07e … finish-poll exit after 2.0s: state=idle
```

The build already reached `idle` in 2.0 s without the change. So the spike's 2.5 s exit is **not
attributable to it**.

### What this falsifies

This document's central claim — *"Music Assistant wraps by media type, and the wrapper decides
whether an end exists"* — **is wrong.** A `builtin://radio/`-wrapped clip demonstrably **can** reach
`idle`. The G3 evidence for that claim (the chime ending while the message did not, in the same turn)
was a **correlation mistaken for the mechanism**: both facts were true, but the wrapper was not the
cause.

Everything else recorded above stands: the 45 s wait, the requirement-7 consequence, the unlogged
budget exit, and the list of behaviours that were correct. Only the **explanation** was wrong.

### The distinguishing feature, and it is UNTESTED

Four observations are now available:

| When | Case | Ceiling before | Exit |
|---|---|---|---|
| 2026-09-08 16:50 | `say_text`, one clip | playing radio | blank-cid grace, 8.0 s |
| 2026-09-08 18:36 | `say_text`, one clip | — | **`idle`, 2.0 s** (no spike) |
| 2026-09-09 16:18 | `say_text`, one clip | idle | **`idle`, 2.5 s** (spike) |
| 2026-09-08 17:10 | announce, **clip 2 of 2** | paused | **never ended — 45 s budget** |

Every single-clip turn ended. The only turn that did not was the **second clip in a sequence**, played
after the chime. That — not the wrapper — is what distinguishes the failing case.

**This is a hypothesis, not a finding.** It has not been tested, and it should not be built on. The
next spike should target the multi-clip sequence: whether MA's queue leaves the player `playing` after
the final item when that item was enqueued behind another. Note also that the blank-cid grace path
(16:50, over music) is a third distinct behaviour, so the picture may be more than binary.

**No remedy is chosen.** The character-count estimate remains untried and was deliberately **not**
attempted as a fallback. The unlogged budget exit and the divergent clip fingerprint remain worth
fixing regardless.

### State after the spike

Fully reverted and verified byte-identical to the post-G3 build — `interaction.py ff03c969`,
`config.py b978ce0a`, `config.json 2ea59677`, `tests/test_interaction.py 7ba49361`, spike flag absent,
**435 tests pass on host Python 3.5.2**, service active with fresh startup lines and no tracebacks,
`key=200`/`nokey=401`, satellite and ceiling idle, microphone `off`. Backups retained:
`.bak/20260909-160351` (pre-spike) and `.bak/20260908-163353` (pre-AN-01).

**G4a and G4b remain blocked.**

## The matrix is complete and the defect DID NOT REPRODUCE — appended 2026-09-26

All four cells of the spike matrix in `2026-09-09-an-01-multi-clip-completion-design-decision.md`
now have a measurement, and **every one of them ends cleanly.** Cells B and C were run as designed.
Cell D — the configuration that failed on 2026-09-08 — was then re-run as a **same-build control**,
because without it B and C cannot be interpreted: "both pass" is consistent both with an interaction
effect and with the failure having stopped happening altogether.

It had stopped happening.

| Cell | Clips | Ceiling before | 2026-09-08 | 2026-09-26 on `52d03d8` |
|---|---|---|---|---|
| A | 1 | idle | ended, 2.5 s | — |
| B | 1 | **paused** | not run | ✅ **ended, 3.14 s** |
| C | 2 | **idle** | not run | ✅ **ended, 11.35 s** |
| D | 2 | paused | ❌ **52.7 s, never observed ending** | ✅ **ended, 9.50 s** |

Cell D is the same configuration, the same two clips, the same paused start, and the same code path
as the failure this document was written about. **52.7 s became 9.50 s.**

### Per-cell detail

**Cell B** (`say_text`, paused start, req `07887514`) — `finish-poll exit after 1.0s: state=idle`.
Volume 0.2 → 0.7 → 0.2. One transient blank `media_content_id` at t=1.1 s, the §4d behaviour, then a
clean `idle`.

**Cell C** (`announce`, idle start, req `4cf93767`) — chime `27e20264` exit after 6.5 s `state=idle`
(`builtin://track/`, `media_duration: 4`); message `52c446f9` exit after 2.0 s `state=idle`
(`builtin://radio/`, `media_duration: None`). Mic leased, confirmed after 2 polls, restored.
Volume 0.2 → 0.8 → 0.2.

**Cell D** (`announce`, paused start, req `32b34d76`) — chime `42f3ebce` exit after 5.0 s, message
`2400ff86` exit after 2.0 s, both `state=idle`. **Microphone muted for 8.4 s, not ~53 s.**
Volume 0.2 → 0.8 → 0.2. Dead-man armed at 184 s and did not fire.

In all three turns: `ok=True`, `superseded=False`, `replayed=False`, `volume_restore='restored'`,
microphone back to `off`, no tracebacks, and the captured music restored afterwards.

### The 6a warning fired zero times

`finish-poll gave up after ...` appears **0 times** across all three turns. The budget-exit logging
deployed in PR #49 is present in the running file and stayed quiet, which is the correct behaviour
when no poll exhausts its budget — and is the positive control showing that a silent budget exit
would now be visible.

### This is NOT a fix, and the new build is not the reason

**The observability changes cannot explain cell D passing.** `clip` at `interaction.py:1251` feeds
only `LOG` calls at 1265, 1290 and 1430 plus `_warn_if_double_speak`, which warns and returns; 6a is
a `LOG.warning`. Both changes are observability-only exactly as §6 specified. Nothing in PR #49
touches completion detection, timing, or any success path.

So the honest status of the requirement-7 failure recorded in this document is:

> **Intermittent. Not reproducible on 2026-09-26. Cause unknown. Not fixed.**

Nobody should read the green matrix above as a resolution. What changed between 2026-09-08 and
2026-09-26 is uncharacterised. The resolver process had been running since 2026-09-09 16:27 and was
restarted 2026-09-26 11:31:45; the host has 12 weeks' uptime; HAOS and the Music Assistant add-on may
have moved in the intervening 17 days. **Nothing measured distinguishes these**, and per the stop/go
criteria in the design decision — "both B and C pass … stop and return to design, proposing nothing"
— no remedy is proposed here.

### What the matrix cost and what it bought

The matrix was built to discriminate between two factors. It cannot, because there is no failure left
to attribute. This is a **fifth outcome**, absent from the design's four-row table.

That is not a wasted measurement. Three things are now true that were not before:

1. **Two hypotheses are falsified by measurement** — the `media_type` wrapper story (2026-09-09) and
   the clip-sequence story (cell C). Neither will be re-proposed from memory.
2. **The recovery paths are verified live on the current build** — microphone lease, confirm and
   restore; volume capture and restore; dead-man arming. Three turns, three clean recoveries.
3. **A recurrence will leave evidence.** The silence that made 2026-09-08 expensive to investigate is
   gone: a budget exit now logs its elapsed time, its budget and its `reason=`.

### Consequence for the gates

**G4a and G4b are no longer blocked by this defect**, because the defect does not currently reproduce
and its worst case is bounded and instrumented. They were blocked on understanding a failure that
cannot presently be observed; waiting for it to recur is not a plan. The residual risk is a ~45 s
microphone mute window that the dead-man bounds at 184 s, and that now logs a reason when it happens.

If it recurs, the `finish-poll gave up` line is the first thing to read, and this document is the
history behind it.

## IT REPRODUCES — and it is a DIFFERENT failure. Appended 2026-09-27

**This falsifies the previous section.** Yesterday's entry concluded the defect was "intermittent,
not reproducible, cause unknown". Today, on the **first** announcement issued through the G4b phone
path, it reproduced on the first attempt — and the failure is not the one recorded on 2026-09-08.

### The measurement — req `f864d0ff`, 2026-09-27 16:01:50

```
16:01:50  ANNOUNCE mic leased gen=11 prev=False deadman=184s
16:01:50  mic mute CONFIRMED after 2 poll(s)
16:01:50  clips=2 chars=15 volume=0.8
16:01:56  SAY clip=8a266f28 finish-poll exit after 5.5s: state=idle   <- chime, fine
16:02:42  WARNING SAY clip=414d2b19 finish-poll gave up after 45.0s without observing
          the clip end (budget 45.0s, reason=finish_timeout)
16:02:42  restored -> 0.3 (owns_restore=True)
16:02:42  mic restored
```

**Microphone muted for 52 s**, the same magnitude as 2026-09-08's 52.7 s.

### What is NEW, and why this is a fourth behaviour

**The message was never audible.** The operator heard the chime and nothing else. On 2026-09-08 the
announcement **was** heard — only its completion went unobserved. Today no sound was produced at all.

The player state explains why the poll never saw an end: **the clip sat at `state=playing`,
`media_position=0`, `media_duration=None` and never advanced.** It was still sitting there minutes
after the turn returned, holding the zone, until it was stopped manually.

So the two failures are not the same event:

| | 2026-09-08 | 2026-09-27 |
|---|---|---|
| Audible | **yes** | **no** |
| Player | advanced, end unobserved | **stuck at `position=0`** |
| Mic held | 52.7 s | 52 s |
| Exit | budget exhausted (unlogged) | budget exhausted (**logged by 6a**) |

Per the stop/go criteria in the design decision — *"any cell produces a fourth distinct exit
behaviour → stop and report, proposing nothing"* — **no remedy is proposed here.**

### 6a worked, and this is the first evidence of it

The `WARNING ... finish-poll gave up after 45.0s ... reason=finish_timeout` line is the budget-exit
logging from PR #49, firing in production for the first time. The identical failure on 2026-09-08
logged **nothing**, which is what made it expensive to investigate. The clip, the elapsed time, the
budget and the reason now arrive in one line, unprompted.

### A NEW defect: the relay reported success for an announcement nobody heard

The automation trace shows the `choose` took `choice=default`, i.e. `r.content.ok` was true, so the
phone was told **"Announced."** The metadata carried `likely_silent: False` and both clips
`issued: True, started: True`.

**The resolver genuinely believes it succeeded.** `started` means the play call was accepted, which
it was; nothing in the turn observes that no audio emerged. The honest-failure work in design 5.2
maps refusals to truthful text, but it has no concept of *"the play was accepted and produced
silence"*. A user asked to trust `chat_text` was, here, told the opposite of what happened.

This is independent of the completion-detection defect and would survive a fix to it.

### D7, partially settled

`chars=15`. The spoken sentence was *"Announce dinner is ready."*, so `trigger.slots.message` carried
**`dinner is ready`** — 15 characters, **the trailing full stop stripped**.

That is the opposite of SPIKE-AN-3's finding for `trigger.sentence`, which **preserved**
capitalisation and punctuation. **The slot and the sentence normalise differently**, exactly the
divergence the plan warned might exist and refused to assume either way. Capitalisation of the first
letter is not determined by a character count and remains unconfirmed; two attempts to read the trace
variables directly failed on harness bugs of mine (`wsutil.ws_connect` returns `(sock, box)`, and the
trigger variables are not at `result.variables.trigger` in this HA version).

### What differs from the runs that passed

Listed as facts, not as a hypothesis. Nothing here is tested.

- **G4a step 5 passed at 14:54 the same day** through the *same* `rest_command`, so the HA transport
  and the payload template are not implicated.
- Cell C passed with two clips from an **idle** ceiling; this turn was also from an idle ceiling.
- Differences that remain: the invocation path (conversation trigger vs direct service call), the
  message text itself, and roughly an hour of elapsed time.
- The chime, a `builtin://track/`, behaved perfectly in both. Only the `builtin://radio/`-wrapped
  Piper clip failed, and this time it failed *earlier* than before — it never started producing audio.

### State

`automation.voice_ceiling_announce` was **disabled** immediately (the kill switch — a service call,
no config change). The stuck TTS clip was cleared and `library://radio/4` restored at volume 0.3.
Microphone `off`, satellite `idle`, resolver `active`, no tracebacks. The other seven automations
were untouched, and `automation.voice_ceiling_speakers` remains byte-identical to
`.bak/automation-voice_ceiling_speakers-20260927-111309.json` (sha256 `b8c6cd48`).

**G4b is halted at step 4.** Steps 5-8 assume a working announcement and would measure nothing.

### Control experiment — the invocation path is EXONERATED. 2026-09-27 16:20

The section above named the invocation path as the one untested difference between the runs that
passed and the run that failed. It was tested 19 minutes after the failure, both legs back to back,
same build, same idle ceiling, same 18-character message.

| Leg | Path | Result |
|---|---|---|
| A | `rest_command.resolver_command_announce` called directly | **passed, 10.49 s** — chime 6.5 s, message 2.0 s, both `state=idle` |
| B | `conversation.process` → the **conversation trigger** on `automation.voice_ceiling_announce` | **passed, 9.50 s** — chime 6.0 s, message 1.5 s, both `state=idle` |

Leg B exercised the same automation, the same trigger and the same relay that failed at 16:01. The
assistant returned `'Announced.'` with `response_type: action_done`. No 6a warning in either leg,
microphone and volume restored in both, no tracebacks.

**So the conversation trigger is not the cause.** The hypothesis the previous section offered as its
only untested candidate is dead.

### The tally, which is the real finding

On this build (`52d03d8`), 2026-09-27:

| Announcement | Origin | Result |
|---|---|---|
| Matrix cells B, C, D | direct | passed |
| G4a step 5 | direct `rest_command` | passed |
| **G4b step 4** | **phone, via STT** | **FAILED — 52 s, silent** |
| Control leg A | direct `rest_command` | passed |
| Control leg B | conversation trigger, typed text | passed |

**Seven announcements, one failure.** The failure was the only one that originated from the phone
through speech-to-text. That is a correlation of one, on a sample of one, and it is **not** offered as
a hypothesis — it is recorded so the next person does not re-test the paths already exonerated here.

What remains untested: whether a phone/STT-originated announcement fails at a rate different from a
programmatic one. Settling that needs several real phone announcements, which needs the operator; it
cannot be simulated, because `conversation.process` is precisely the simulation that just passed.

**The defect is intermittent at roughly 1 in 7 today, cause still unknown, and still not fixed.** The
"fourth behaviour" recorded above — no audio at all, player stuck at `position=0` — has been observed
exactly once.

A minor observation for whoever writes the next harness: the microphone state read immediately after
a turn returns can still show `on` for about a second before HA settles, while the resolver has
already logged `mic restored`. Both legs showed this and both were `off` on the later check. Poll it
twice before calling it a recovery failure.

## ROOT CAUSE — Music Assistant classifies a still-generating TTS stream as RADIO. 2026-09-27

**This is the mechanism.** It explains every observation in this document, including the ones that
looked contradictory: the intermittency, the 2026-09-08 clip that was audible but never ended, the
2026-09-27 clip that produced no sound at all, and the chime that has never once failed.

**Epistemic status, stated plainly because it matters here: this is an inference from VERIFIED
upstream source, not a maintainer's diagnosis, and the exact signature is NOT filed upstream.** No
issue in `music-assistant/server`, `music-assistant/support` or `home-assistant/core` matches it. It
has not been confirmed against this host's own Music Assistant log, for the reason in "What is not
verified" below. Treat it as the best available explanation, and as something that would take one
log line to confirm or kill.

### The mechanism

Music Assistant's builtin provider classifies a URL by running **ffprobe against it**. There is no
file-extension check and no Content-Type sniffing — the classification is purely what ffprobe
reports. In `music_assistant/providers/builtin/__init__.py`, `parse_item()`:

```python
is_radio = media_info.get("icyname") or not media_info.duration
...
elif (is_radio or force_radio) and requested_media_type != MediaType.TRACK:
    # treat as radio, unless a track was explicitly requested
```

and in `helpers/tags.py`, duration is `float(raw["format"].get("duration", 0)) or None` — **None
when ffprobe cannot determine it**.

Home Assistant's `tts_proxy` is a `web.StreamResponse` written chunk by chunk (`components/tts/
__init__.py`). It carries **no Content-Length**, it is chunked, and on a cache miss **the bytes
appear only as Piper synthesises them**.

Put those together:

| Case | ffprobe sees | duration | classified as | outcome |
|---|---|---|---|---|
| clip already cached | a complete mp3 | a real number | **track** | plays, reaches `idle`, ends |
| clip still generating | a chunked, incomplete stream | **None** | **radio** | an ENDLESS STREAM |
| the chime (`.wav`, local, signed) | a complete file | a real number | **track** | has never failed |

A radio stream has no end by definition. `media_duration` is `None` *by design*, MA never expects a
completion, and the player sits in `playing` holding the queue until something stops it. That is not
a stall to be detected — it is the player doing exactly what it was told.

### What this explains that nothing else did

- **The ~1-in-7 rate.** It is a race between Piper's synthesis and MA's ffprobe, not a property of
  any code path. Repeating the same text warms the cache; new text on a busy moment loses.
- **Why the chime never fails.** A complete local file always has a duration. This document has
  recorded that asymmetry three times without an explanation for it; here it is.
- **Why `media_duration` was `None` on every failure.** Not a symptom — the *cause*, one step
  upstream.
- **Why the 2026-09-08 clip was AUDIBLE and the 2026-09-27 clip was SILENT.** Both were classified
  as radio and so neither could ever end. Whether sound emerged depends on how much of the stream
  survived the probe, which is a second race inside the first. The "fourth distinct behaviour"
  recorded above is the same fault with a different amount of audio.
- **Why the matrix cells, the control legs and G4a step 5 all passed.** Every one of them was a
  cache hit or a fast enough synthesis. The matrix was measuring the race, not the factors it was
  built to separate.
- **Why `media_type: "track"` changed nothing (2026-09-09 spike).** The
  `requested_media_type != MediaType.TRACK` escape hatch is on MA's dev branch. **This host runs
  Music Assistant server 2.9.3** (verified on the host 2026-09-27 via `:8095/info`). The spike was
  testing a parameter this version does not honour, so its negative result says nothing about the
  idea — and the falsification recorded above under "Option D FAILED" should be read with that in
  mind.

### The fix is a different API, not a parameter

`tts.speak` with `media_player_entity_id` pointing at the MA entity calls `media_player.play_media`
with `ATTR_MEDIA_ANNOUNCE: True` (verified, `components/tts/entity.py`). The MA integration routes
that to `mass.players.play_announcement(...)` — a **player-level** API that never touches the
builtin music provider, never calls `parse_item`, never runs the ffprobe classifier and never
creates a queue item. **The classification bug structurally cannot occur on that path.**

MA handles ducking and resume itself. Before committing to it, three verified limitations:

1. **Native overlay announcements exist only for Sonos S2 and Sendspin.** On Squeezelite — this
   house — MA **stops** playback, announces, then resumes. The MA docs call this out for AirPlay and
   Squeezelite specifically: the resume "will be noticeable".
2. MA's docs state announcements "require accurate state and progress reporting from players for
   reliable operation" — the same reporting measured as frozen for 20s below. Immune to the
   *classification* bug is not immune to every stall.
3. `music_assistant.play_announcement` takes an audio URL, not text. For Piper speech the entry
   point is `tts.speak`.

Note the irony for the G4b decision recorded elsewhere: **`script.ceiling_announce`, the pre-AN-01
"unsafe duplicate" flagged for deletion, calls `tts.speak`** — the transport that avoids this bug.
It lacks the microphone mute and the turn lock, but it was on the right path all along.

### Adjacent upstream issues — verified, none is this bug

- `music-assistant/support#6415` (open, 2.10.2) — MA fails to ffprobe a `tts_proxy` URL, logging
  `Unable to retrieve info for <url>`. A different cause (http/https mismatch) but **the same code
  path**. That log string is the one-line confirmation for the hypothesis above.
- `music-assistant/support#6320` (open, regression since 2.10) — `play_media` with a plain audio URL
  plays a random library track. Same URL-resolution area.
- `home-assistant/core#151757` (closed, not planned) — `tts.speak` to MA: bell plays then silence,
  reporter attributing it to a cached URL handed over while still loading. The closest upstream
  analogue to a 1-in-7 timing race. **Reporter's diagnosis, not a maintainer's.**
- `music-assistant/support#6359` — a Squeezelite `STMu`/`STMd` race. Different symptom; ruled out.

### `media_position` cannot be used to detect this

Measured on this host 2026-09-27, sampling the ceiling player every 2s for 20s **while it was
audibly playing**: `media_position` stayed at `1799` and `media_position_updated_at` never changed,
on every sample. Both fields are pushed from MA's `elapsed_time` / `elapsed_time_last_updated`
(verified in `components/music_assistant/media_player.py`), not computed by HA, and MA throttles
that reporting.

A detector built on "position has not moved" was implemented and **removed** for this reason: it
would have cut off audible speech. Do not reintroduce it without a signal a healthy player
demonstrably moves. HA's developer docs define these attributes but say **nothing** about polling
behaviour or streams — there is no contract to cite here, in either direction.

### What is NOT verified

- No maintainer has confirmed the mechanism, and the signature is **unfiled upstream**.
- **It has not been confirmed against this host's MA log.** The decisive check is grepping the
  Music Assistant add-on log for `Unable to retrieve info for` around a failing run. That log lives
  inside the HAOS VM and is reachable through the Supervisor API or the MA add-on UI, neither of
  which is reachable from the resolver host with the HA token alone. HA's own core error log was
  empty (14 bytes) and does not carry add-on output.
- Whether MA 2.9.3 contains the `requested_media_type` guard at all is **not determined**; the PR
  that added it was not dated.

### The next step this implies

Confirm with the MA add-on log, then design the move to `tts.speak` as its own increment with its
own live gate. It replaces the transport rather than compensating for it, which is why none of the
resolver-side work recorded above — honest reporting, the microphone handover, the unreadable-poll
handling — makes an announcement any more likely to be heard. That work makes failures legible and
safe. **It does not fix this.**

## ⛔ THE "ROOT CAUSE" ABOVE IS WRONG. The MA log says otherwise. 2026-09-27, later

The section above was written from upstream source-reading alone, before Music Assistant's own log
had been read. **The log falsifies its mechanism.** It is left in place rather than deleted, because
the reasoning is a useful record of how a plausible story survived until it met evidence — but
**do not act on it**.

### How the log was obtained, since the previous section said it could not be

It said the MA add-on log was unreachable. That was wrong, and only half-checked: MA's own
websocket API accepts a **`logging/get`** command, and the resolver already holds `.ma_token` and a
working client (`maconn.py`). An HTTP probe returned 404 for `/logs` and friends, and `logging/get`
initially answered *"Authentication required"* — which I first read as "unavailable" instead of
"authenticate first". 3755 lines, spanning 2026-07-17 to 2026-09-27, one websocket call away the
whole time.

### What the log actually shows at the failure

```
16:01:50.897 INFO  [streams.audio]   Start Queue Flow stream for Queue Ceiling Speakers
16:01:50.988 WARN  [player_queues]   Skipping unplayable item -x6odQg9FAYNmkJ6x-4KTw
                                     (builtin://radio/.../api/tts_proxy/-x6odQg9FAYNmkJ6x-4KTw.flac)
                                     ... x20 within 85 ms ...
16:01:51.073 INFO  [streams.audio]   Finished Queue Flow stream for Queue Ceiling Speakers
```

MA decided the item was **unplayable and skipped it, 91 ms after the stream started**. It never
tried to play anything. The resolver then polled a player that was never going to produce audio,
for the full 45 s budget.

### The actual discriminator is the FILE EXTENSION, and the URL 404s

Every `.flac` TTS URL in the log fails, and ffmpeg says why:

```
[http @ ...] HTTP error 404 Not Found
[in#0 @ ...] Error opening input: Server returned 404 Not Found
Error opening input file http://192.168.122.10:8123/api/tts_proxy/<id>.flac.
ERROR [player_queues] Failed to stream audio
```

Census of every `tts_proxy` URL MA has logged since July:

| extension | clips | failed |
|---|---|---|
| `.mp3` | 28 | **0** |
| `.flac` | 4 | **4** — three with a 404, one "unplayable" |

**The audio is not fetchable.** It is not a classification problem, not a duration problem, and not
a stall.

### What this falsifies in the section above

1. **"MA classifies a still-generating stream as radio, and radio never ends."** The radio wrapping
   is **normal and happens on the runs that WORK**. Both passing control legs at 16:20 logged
   `Live media item ... (radio) encountered in flow stream - breaking out to single item stream`
   and then played. `builtin://radio/` is not the discriminator; it is the background.
2. **The ffprobe story has no support in the log at all.** Zero occurrences of `ffprobe`, zero of
   `InvalidDataError`. The only two `Unable to retrieve info for` lines are the **chime** on
   2026-09-05 and 2026-09-07, both `401 Unauthorized`, both unrelated.
3. **"2026-09-08 audible and 2026-09-27 silent are the same fault."** Almost certainly **not**. A
   404 produces no audio at all, which is 2026-09-27. The 2026-09-08 announcement was **heard in
   full** — its URL resolved and its audio played. Those are two different faults, and unifying
   them was the same over-reach as the mechanism itself. The "fourth distinct behaviour" recorded
   earlier was right; retracting it was wrong.

### What is established

- The failing clip's URL ended `.flac`; MA skipped it as unplayable within 91 ms; no audio.
- All four `.flac` TTS URLs in ten weeks of log failed; all 28 `.mp3` ones did not.
- Three of the four failed with an explicit **HTTP 404** from ffmpeg.
- `tts_get_url` returns `.mp3` **right now**, three probes out of three.
- MA server 2.9.3, HA core 2026.6.4.

### What is NOT established — and this is the open question

**Why HA returned a `.flac` URL for that turn, and an `.mp3` for every probe since.** The resolver
calls `ha.tts_get_url(engine_id, message)` and does not request a format, so the extension is HA's
choice. Nothing in hand explains the variation. Candidates, none tested:

- HA negotiating a format per call, or per target player's declared capabilities.
- A `.flac` URL generated for a format HA's proxy then declines to serve, which would make the 404
  a *consequence* of the extension rather than a coincidence.
- URL expiry (`home-assistant/core#159537` records `tts_proxy` 404s after idle) — though the 16:01
  URL 404'd within a second of being minted, which argues against expiry.

Note the three older `.flac` 404s sit beside lines reading
`Playback announcement to player Ceiling Speakers (with pre-announce: True): ....mp3` — **MA's own
announcement path**, i.e. `tts.speak`. So the `.flac` URLs are not unique to the resolver's path,
which weakens the case for the `tts.speak` migration being an automatic escape from this.

### The next measurement, and it is cheap

Capture the **full** URL the resolver receives from `tts_get_url` on every announce — the resolver
log truncates the cid at 80 characters, which is exactly why the `.flac` extension went unnoticed
for a day. Then a failure is self-diagnosing: extension in hand, and a `curl -I` against the URL
says 404 or 200 immediately.

Until that is in place, the honest statement is: **an announcement fails when its TTS URL is not
fetchable, the extension is the only known correlate, and why the extension varies is unknown.**

---

> **Rollback:** `git revert` the commit adding this file. It records a measurement and blocks a gate;
> no code or configuration depends on it.
