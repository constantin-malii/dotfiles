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

---

> **Rollback:** `git revert` the commit adding this file. It records a measurement and blocks a gate;
> no code or configuration depends on it.
