# ADR — S1b Duck-Ownership: who restores the ceiling after a reply

> **Design / research only. No implementation, no live change, no gate.**
> **Status:** Accepted, then **largely SUPERSEDED by Spike 2 (2026-07-15).** The spike proved
> `music_assistant.play_announcement` is **synchronous/blocking** (it pauses → plays the reply → resumes),
> so the reply-timer duck-ownership mechanism below is **unnecessary — restore-on-return replaces it**, and the
> B1 timing race largely dissolves. Kept for the reasoning record. See S1b design **§11**. (Originally resolved
> review finding **B1**; superseded S1b design §5 comp-4 + the §10 Spike-2 wording.)
> Parent: `2026-07-15-s1b-satellite-ceiling-reply-design.md`. Builds on S1a (live) + AU-02/AU-03 (live).

## Context

In S1b the spoken reply is offloaded from the satellite onto the ceiling (firmware `on_tts_end` → resolver
`say` → MA announce). This **decouples reply duration from `assist_satellite` state**: once local TTS is
suppressed, the satellite reaches `idle` at/near hand-off, but the ceiling reply is only just starting. S1a
restores on `idle`, so restore un-ducks the music **mid-reply**. We must decide **who owns restore for a
reply turn** and how the duck is held until ceiling playback actually ends.

Hazard timeline:

```
wake→listening→processing→responding   HA (S1a): duck (snap 0.40→floor 0.15, arm 120s dead-man); re-duck+re-arm each transition
  on_tts_end → URI → resolver say       resolver starts MA announce on ceiling (boost over 0.15, auto-reverts to 0.15)
  local TTS suppressed → idle           ⚠ HA (S1a): idle→restore fires HERE, mid-announce → volume jumps to 0.40 under the reply
  ceiling announce still playing… ends  (nothing keys restore off THIS, the only signal that bounds the window)
```

## Decision drivers

1. **Single writer to ceiling volume** — the resolver is already sole media/TTS owner; two independent restore paths invite races.
2. **Restore must key off ceiling playback-end**, not satellite state — that's the only signal that bounds the duck window in S1b.
3. **"Announce complete" is weakly observable** on an MA Universal→Squeezelite player — announce is an *overlay*; the underlying `media_player` state may never leave `playing`, so a state-watch is unreliable.
4. Must survive: the **idle-before-`say`** race, the **120 s dead-man**, **barge-in** re-trigger, resolver restart, and **MA-announce's own boost/auto-revert nested inside the S1a duck**.

## Options

- **A — Resolver `say` owns the duck lifetime.** `say` marks the zone "reply-active" when it starts the announce, detects playback-end, then issues restore itself. `idle→restore` is removed for this satellite.
- **B — HA automation watches the ceiling player** and fires restore on "announce complete" (ceiling media state, not satellite state).
- **H — Hybrid (chosen).** Option A as primary, with the satellite's `idle` transition **repurposed** from "restore now" to "arm a short no-reply grace fallback": if no `say` becomes active within grace **G (~2–3 s)**, restore early (covers "URI never arrives" without a 120 s quiet gap). The 120 s dead-man remains the ultimate backstop.

**Playback-end detection** (orthogonal to A/B/H):
1. **Await MA completion** if `play_media(announce=true)` blocks or emits a done event — cleanest if available.
2. **Duration-based hold** — derive the Piper clip length (audio duration, or `Content-Length`/`HEAD` on the URI), hold the duck for `clip_len + margin`, then restore. Deterministic, observes no MA internals — **the robust primary/fallback given driver #3.**
3. **State-watch of the ceiling player** — fragile; **reject** except as a secondary sanity check.

## Analysis against the hard cases

| Case | Option A / H (resolver-owned) | Option B (HA watches ceiling) |
|---|---|---|
| **idle-before-`say`** | Handled: `idle` no longer restores; the duck persists until `say` restores (H: `idle` only arms grace G). | Broken: old `idle→restore` vs new watch — which fires first? Needs the idle trigger removed anyway → collapses toward A. |
| **Two restore paths racing** | One writer: `say` owns restore; idle path gone/advisory. | Two triggers (idle + ceiling-complete) → double restore / volume flap unless one is disabled. |
| **120 s dead-man** | Unchanged backstop; `say` cancels it on normal restore; H shortens the *failed-reply* wait via G. | Still needed; B's restore may also fire → contends with dead-man. |
| **Barge-in during reply** | New wake → duck re-fires (coalesce, keep baseline, re-arm); new `say` interrupts (MA replace) the in-flight announce; restore only after the latest reply — one component sequences it. | HA must reconcile "complete" of a *replaced* announcement → easily fires restore on the interrupted clip's end. |
| **Resolver restart mid-reply** | Same residual as S1a's known deferred-persistence gap (in-memory snapshot lost → strand until backstop/manual). **Not worse than S1a.** | Restore lives in HA, so slightly better here — but doesn't justify B given everything else. |
| **MA boost/auto-revert nesting** | Safe: duck (0.15) settled before `say`; MA boosts→reverts to 0.15; resolver restore to 0.40 strictly **after** MA's revert — fully sequential under one owner. | Ordering of MA-revert vs HA-restore uncontrolled → can restore to 0.40 before MA reverts, then MA reverts to a stale captured value → **wrong baseline**. |

Option B loses on the two things that matter most — **unreliable announce-complete observation** (driver #3) and **uncontrolled ordering vs MA's revert** (driver #4). Fixing B's idle-before-`say` race requires removing `idle→restore` anyway, at which point B *is* A with a worse detector.

## Decision — adopt Option H

The resolver `say` capability **owns the duck lifetime for reply turns**:
- `say` sets a **reply-active hold** on the zone when it starts the ceiling announce; it issues **restore itself** on playback-end.
- **Playback-end** = await MA completion if available, else **duration-based hold** (`clip_len + margin`); **never** rely on ceiling state-watch.
- **Remove `idle→restore` for this satellite.** Repurpose `idle` to **arm grace G (~2–3 s)**: if no `say` becomes active by then, restore (covers "URI never arrives").
- **120 s dead-man** stays as the ultimate backstop, unchanged.
- **Barge-in:** a new `say` interrupts (replaces) the in-flight announce; the hold persists and restore fires only after the newest reply ends. Duck re-fire coalesces on the original baseline (existing S1a behavior).

This keeps a single writer to ceiling volume, keys restore to the only signal that bounds the window
(ceiling playback), and sequences **duck → announce (boost/revert) → restore** deterministically.

## Consequences

- **S1b modifies S1a's live automation** (drops `idle→restore` for this satellite, repurposes `idle` to arm G). Expected — S1b builds on S1a — but it's a **behavior change to a live automation**, not additive; call it out in the plan.
- **The interaction capability gains a small `reply-active`/hold state** + a restore-on-playback-end path (correlate `say` with the active duck by zone; add a turn/duck id if barge-in correlation needs it). A real addition, not a config tweak.
- **Spike 2 must now prove three concrete things** (was one vague requirement): (1) does MA announce give a completion signal, or must we use duration-hold; (2) MA's auto-revert targets the **live (floor)** volume, not a stale capture; (3) the resolver-issued restore lands cleanly **after** MA revert. **Add:** the reply URI is fetchable by MA and **outlives the fetch** (internal-URL/LAN + TTS-cache-TTL concern, per S0 §5).
- **Resolver-restart-mid-reply** strand is unchanged from S1a (same deferred-persistence gap) — no new risk, but it now applies to reply turns too.

## Plan impact

This ADR is what makes **B1** safe to take into planning. Fold it into S1b §5/§7/§10, paired with the
slicing recommendation: **S1b-1 = resolver `say` + this duck-ownership mechanism + Spike 2**, validated over
`/command` with a **test URI (no firmware)**. That slice proves the entire duck/announce/restore choreography
— the whole of B1 — behind one resolver gate before any reflash. **S1b-2 = pipeline + firmware + Spike 1**
follows only once S1b-1 is green.

---

> **Rollback for this document:** `git revert` on `homebrain/s1b-satellite-ceiling-reply`, or delete this file.
