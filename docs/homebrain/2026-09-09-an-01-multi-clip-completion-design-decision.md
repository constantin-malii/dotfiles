# AN-01 — Multi-clip completion detection: design decision

> **Status:** DECISION DOCUMENT, for review. **Nothing implemented.** Offline: no code, no config, no
> deploy, no audio, no G4 work. Live lane free.
>
> **Context:** [`2026-09-08-an-01-post-g3-clip-completion-correction.md`](./2026-09-08-an-01-post-g3-clip-completion-correction.md)
> records the G3 failure and, in its 2026-09-09 append, records that Option D failed and that the
> **wrapper-based explanation was falsified**. This document decides how to find the real mechanism,
> and scopes the two fixes that are worth making regardless of what it turns out to be.
>
> **It does not choose a remedy.** Choosing one before the mechanism is known is what produced Option
> D: a plausible story, a clean spike, and no effect.

---

## 1. What is actually known

| # | When | Case | Ceiling before | Clips | Exit |
|---|---|---|---|---|---|
| 1 | 2026-09-08 16:50 | `say_text` | **playing** radio | 1 | blank-cid grace, 8.0 s |
| 2 | 2026-09-08 18:36 | `say_text` | **unknown** | 1 | `idle`, 2.0 s |
| 3 | 2026-09-09 16:18 | `say_text` | **idle** | 1 | `idle`, 2.5 s |
| 4 | 2026-09-08 17:10 | `announce` | **paused** | 2 | **never ended — 45 s budget** |

Also measured, and still true: for a `builtin://radio/`-wrapped clip, `media_duration` and
`media_position` are both `None`. The wrapper is not the cause of the hang, but it does remove the
fallback signal, so a duration-based exit is unavailable either way.

**Three distinct exit behaviours have been observed**, not two: clean `idle`, the blank-cid grace, and
budget exhaustion. Any explanation has to accommodate all three.

## 2. The confound

Observation 4 is the only failure, and it differs from the passing observations in **two** ways at
once:

- it played **two clips** (chime, then message), and
- the ceiling was **paused** beforehand.

Nothing in the data separates them. Observation 2's before-state was never recorded, so it cannot
break the tie either — that is a gap in our own record, not a fact about the system.

**Any fix chosen now would be a guess about which of the two matters.** That is precisely the error
Option D made.

## 3. The spike matrix

Four cells, two factors. Each cell is **one short `say_text` or `announce`**, attended, with the
operator listening, and each records: `media_content_id`, `media_duration`, `media_position`, the
`state` sequence, the finish-poll exit line, elapsed time, mic state and volume restoration.

| Cell | Clips | Ceiling before | Status | Purpose |
|---|---|---|---|---|
| **A** | 1 | **idle** | **already observed** (obs. 3) — ended `idle` in 2.5 s | baseline |
| **B** | 1 | **paused** | **NOT observed — required** | isolates the paused start |
| **C** | 2 | **idle** | **NOT observed — required** | isolates the sequence |
| **D** | 2 | **paused** | **already observed** (obs. 4) — **failed** | the known failure |

B and C are the two that must be run. A and D are already in hand.

### How to read the outcome

| B (1 clip, paused) | C (2 clips, idle) | Conclusion |
|---|---|---|
| ends | ends | **Neither factor alone is sufficient.** The failure needs both together — an interaction effect. The remedy must handle the combination, and the hypothesis in the correction is too simple. |
| ends | **fails** | **The sequence is the cause.** Investigate MA's queue and the `enqueue` parameter (§4). This is the outcome the current hypothesis predicts. |
| **fails** | ends | **The paused start is the cause.** The sequence is irrelevant; the correction's replacement hypothesis is also wrong. Investigate what `play_media` does to a paused player. |
| **fails** | **fails** | **Both are independently sufficient.** Two mechanisms, or one more general than either factor. Stop and re-derive before proposing anything. |

Recording B's before-state and C's before-state explicitly closes the gap that observation 2 left.

### Order, and why

Run **C first**. It tests the standing hypothesis, it is the case AN-01 actually ships (an
announcement over an idle ceiling), and if it fails it reproduces the defect in the simplest
configuration we have — which is the best position from which to investigate the queue. Run **B**
second regardless of C's result, because the confound is only broken by having both.

### Cost and safety

Two attended turns, each a few seconds of audio, both on the existing deployed build with **no code
change**. A failing cell costs a 45-second mute window, which is the defect already recorded — so the
spike risks nothing new. Cell D's own run showed the mic dead-man armed correctly at 184 s and not
firing, and the volume restoring, so the recovery paths hold even when the poll burns its budget.

## 4. Candidate mechanisms

None of these is established. They are what the matrix would discriminate between.

### 4a. `enqueue` — the resolver does not pass it

`music_assistant.play_media` accepts `enqueue` with options `play`, `replace`, `next`,
`replace_next`, `add`. **The resolver omits it**, exactly as it omitted `media_type`, so MA chooses
the default. If the default appends rather than replaces, a two-clip turn builds a **two-item queue**,
and the player's end-of-queue behaviour after item 2 may differ from a single-item queue's.

This is the most testable candidate and the strongest fit to the standing hypothesis. Note the
cautionary parallel: `media_type` was also an unpassed parameter with a plausible story, and it did
nothing. Passing `enqueue: "replace"` should be treated as another hypothesis needing its own
measurement, **not** as a fix.

### 4b. Queue-finished versus item-finished

MA may transition the player to `idle` only when the **queue** empties, not when an item completes.
A single-item queue empties on completion; a two-item queue's second item may leave the queue in a
state that does not produce the transition. This would explain 3 and 4 together without involving the
paused start.

### 4c. The paused start

`_say` skips its `media_pause` when the zone is not playing, so a paused-start turn takes a different
path through the turn than a playing-start one. What `play_media` does to a **paused** MA player —
whether it resumes into the existing queue rather than starting a fresh one — is unknown to us and
would explain 4 without involving the sequence at all.

### 4d. The blank-cid grace is a third behaviour

Observation 1 exited via the blank-cid grace from a **playing** start. Whatever mechanism is proposed
must also explain why a playing start produces a transient blank cid while an idle start produces a
clean `idle`. An explanation that only covers the failure is incomplete.

## 5. Explicit stop/go criteria

**Go to a remedy design** only when the matrix is complete and the outcome table above yields a
single unambiguous row.

**Stop and return to design, proposing nothing, if:**

- both B and C fail (two mechanisms — the model is wrong, not incomplete);
- both B and C pass (the failure needs a combination not yet characterised);
- any cell produces a **fourth** distinct exit behaviour;
- any cell leaves the microphone muted or the volume raised after the turn — that is a recovery-path
  regression and outranks the investigation;
- a cell cannot be run cleanly (satellite not idle, ceiling not in the required state) — record it as
  not run rather than approximating it.

**Abort the spike immediately if** the mic does not return to `off`, the volume does not return to
its captured value, or the resolver logs a traceback. Recovery is the existing rollback pointer
`.bak/20260909-160351`.

**Explicitly not a go signal:** a cell that merely *ends faster*. Option D ended in 4.39 s and meant
nothing, because the pre-spike build already did that. Every future claim of improvement needs a
same-build control.

## 6. The two mechanism-independent fixes

These do not depend on the mechanism and can proceed on review without waiting for the matrix. Both
are small, offline, and would have shortened this investigation considerably.

### 6a. Warning-level budget-exit logging

`_play_clip_and_wait`'s finish poll logs the ended-twice exit and the blank-cid-grace exit. Falling
out of the loop because the budget expired **logs nothing**, which is why the G3 failure appeared as a
45-second hole between two ordinary lines and was diagnosable only by subtracting timestamps.

**Scope:** one `LOG.warning` on the finish poll's budget exit, carrying the clip fingerprint, the
elapsed time and the budget. The start poll already warns (`did not start (likely silent)`), so only
the finish poll needs it.

**Tests:** the budget exit emits a warning naming the clip and the elapsed time; the ended-twice and
blank-grace exits keep their existing lines and do **not** gain a spurious warning; no log line
carries a credential.

### 6b. The divergent clip fingerprint

The turn-level `clip` is computed from the **raw** URI (`interaction.py:1226`) while the loop's
`one_clip` is computed from the **normalised** URI (`:1479`). Because the TTS URL's host differs from
`say_internal_base`, the two hash differently, so a single turn logs **two different clip ids** —
defeating the correlation `_clip_id` exists for. Observed live at G3: `clip=58bf0413` on the start
line, `clip=47dcf789` on the finish-poll line, same clip.

Introduced by the Task 12 clip loop; cosmetic, no behavioural effect.

**Scope:** derive the turn-level fingerprint from the **normalised** URI so it matches the message
clip's id. The alternative — passing the turn's id down into the loop — is worse, because the chime
would then be logged under the message's id and two genuinely different clips would become
indistinguishable.

**Tests:** a turn whose TTS host differs from `say_internal_base` logs one id across the start line
and the per-clip lines; a two-clip turn still logs **distinct** ids for chime and message; the golden
say/say_text sequences are unchanged.

### Deliberately out of scope here

No change to completion detection, no `enqueue` or `media_type` parameter, no budget or grace tuning,
no fallback to a character-count estimate. Those all wait on the matrix.

## 7. Recommendation

1. Review and approve **§6a and §6b** — offline, mechanism-independent, and they make the next
   failure legible. Ordinary G2-style work: tests first, full suite, `py_compile`, the 3.5 sweep, PR.
2. Approve the **attended spike matrix**, cell **C** then cell **B**, on the currently deployed build
   with no code change.
3. Only then design the remedy, against whichever row of §3's outcome table the results select.

**G4a and G4b remain blocked** until an announcement's mute window tracks its speech.

## 8. OUTCOME — the matrix is complete, and it selected no row. Appended 2026-09-26

Cells B and C were run on 2026-09-26 against `52d03d8`, in the order this document specifies. Both
**passed**. Cell D was then re-run as a **same-build control**, because "both B and C pass" is
ambiguous between the interaction-effect row of §3 and the failure simply no longer occurring — and
§5's own rule that "every future claim of improvement needs a same-build control" applies just as
much to a claim that a failure still exists.

**Cell D passed too: 52.7 s on 2026-09-08 became 9.50 s.**

| Cell | Clips | Before | Result |
|---|---|---|---|
| A | 1 | idle | ended, 2.5 s (2026-09-08) |
| B | 1 | paused | ✅ ended, 3.14 s |
| C | 2 | idle | ✅ ended, 11.35 s |
| D | 2 | paused | ✅ ended, 9.50 s — **the 2026-09-08 failure did not reproduce** |

**§3's outcome table does not cover this.** It has four rows, all of which presuppose that the defect
still occurs. The matrix was designed to attribute a failure between two factors and cannot, because
there is no failure left to attribute.

Per §5, **no remedy is proposed**. §4's candidate mechanisms — `enqueue` (4a), queue-versus-item
finished (4b), the paused start (4c) — are neither confirmed nor eliminated; they are simply untested
against a live failure, and must not be carried forward as if the matrix had supported any of them.
Cell C's clean two-clip run does remove the direct evidence for the sequence hypothesis that §3 named
as the predicted outcome.

The full measurement, the per-cell detail, and the reasoning for why PR #49's observability changes
**cannot** explain the result are recorded in
`2026-09-08-an-01-post-g3-clip-completion-correction.md` under "The matrix is complete and the defect
DID NOT REPRODUCE".

**The requirement-7 failure is intermittent, not reproducible as of 2026-09-26, cause unknown, and
not fixed.**

**G4a and G4b are unblocked** — not because the defect is understood, but because it cannot presently
be observed, its worst case is bounded by the 184 s dead-man, and §6a now makes a recurrence legible.
Waiting for an unreproducible failure to recur is not a plan.

---

> **Rollback:** `git revert` the commit adding this file. It is a decision record; no code or
> configuration depends on it.
