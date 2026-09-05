# S1a — Satellite→Ceiling Interaction Duck + Restore (design)

> **Design / research only. No implementation, no resolver/HA/MA change, no exposure, no live gate.**
> Defines how the **ceiling media zone** ducks its music while the user is talking to the **reSpeaker
> Living Room** voice satellite, and restores afterward. The satellite's spoken reply stays on **its own
> speaker** in this stage; moving replies onto the ceiling is the separate **S1b**.
> Inputs: `s0-satellite-inventory.md` (satellite facts), `2026-07-06-au-01-interaction-audio-policy-design.md`
> (duck/restore mechanism + per-zone interface), ONBOARDING §1/§4/§6/§12, BACKLOG (S / AU boundary).
>
> Track: **S** · Item: **S1a** (`design`, first slice of `S1`) · Branch: `homebrain/s1a-satellite-ceiling-duck`.
> Live gate (BACKLOG §10) left **FREE**.

---

## 1. Scope

**In scope:** the deterministic binding that makes an assistant interaction **on the reSpeaker Living
Room** duck (then restore) the **ceiling zone** (`media_player.ceiling_speakers`) — i.e. the S-track
"*which zone reacts*" decision for the single satellite, wired to AU-01's duck/restore mechanism.

**Out of scope:**
- **Reply on the ceiling** (universal resolver TTS relay, no-double-speak) → **S1b**.
- The duck/restore *mechanism itself* (volume snapshot/`volume_set`/restore + edge cases) → **AU-02/AU-03**
  (resolver); S1a **consumes** it, does not reimplement it.
- Privacy gating, multi-room, household announcement targeting, multiple satellites → **S2–S4**.

## 2. Why staged (S1a before S1b)

`S1` ("talk to the satellite, reply on the ceiling, duck the music") splits into two pieces with very
different risk:

| Stage | Behavior | Risk | Value |
|---|---|---|---|
| **S1a** (this doc) | Wake→duck ceiling→restore; reply on the **satellite's own speaker** | **Low** — no new TTS path, no double-speak, reuses AU-01 | High — 90% of "talk over my music" daily value |
| **S1b** (next) | Move all replies onto the **ceiling** via a resolver TTS relay | Higher — response-capture hook + one-utterance/no-double-speak (F1/F1-R-grade choreography) | Completes the "reply overhead" goal |

S1a ships the useful behavior fast using only what's already wired; S1b isolates the risky relay.

## 3. Constraints that shape it (from S0 / AU-01 / ONBOARDING)

| Constraint | Source | Consequence |
|---|---|---|
| Exactly **one satellite**, in the **Living Room**; **one** media zone (ceiling) | `s0-satellite-inventory.md` §1/§3 | Routing is trivial: satellite interaction → the ceiling zone. No map/lookup needed yet. |
| Satellite has its **own speaker** (3.5mm) and its pipeline speaks locally (Piper) | S0 §5 | S1a leaves replies on the satellite; nothing to route to the ceiling this stage. |
| Ducking uses **`volume_set`** (no mute) and **never `media_stop`** (stop-wedge) | AU-01 §2/§4 | Duck = snapshot + `volume_set` to a floor; restore on done. Pause only if ever needed (not here). |
| Duck/restore is **resolver-owned** (sole media + TTS owner) | AU-01 §2/§9 | The HA side only **triggers**; the resolver performs the duck/restore (AU-02/AU-03). |
| Satellite exposes an `assist_satellite` **state** (idle/listening/processing/responding) | S0 §2 | That state is the interaction **trigger** for duck (leaving idle) and restore (returning to idle). |

> **Not blocked by S0's area gap:** S0 flagged the satellite's HA **area = unassigned** as blocking
> *area-based* routing. S1a does **not** need it — the route is a fixed single-zone binding (the one Living
> Room satellite → the one ceiling zone). Area assignment matters for **S2+** (multi-zone / room-aware),
> not here.

## 4. Interaction flow (single zone)

```
"Okay Nabu"                → assist_satellite: idle → listening
   └─ trigger: leaving idle → resolver DUCK ceiling (snapshot vol, volume_set → listen/​speak floor)
(user speaks; STT; agent)   → processing / responding   [ceiling stays ducked]
reply on SATELLITE speaker  → (S1a: local; ceiling remains ducked so the reply is audible)
interaction ends            → assist_satellite: → idle
   └─ trigger: back to idle → resolver RESTORE ceiling (restore snapshot; AU-01 §6 edge cases)
```

- **One duck for the whole turn** (listen + think + speak), restored once at DONE — no per-phase churn.
  **Single floor by construction:** AU-01 splits `listen_floor`/`speak_floor` because there the SPEAK
  phase overlays TTS *on the ceiling* (duck-under-TTS is a different acoustic goal than duck-for-mic). In
  S1a the reply is on the **satellite's** speaker — the ceiling **never carries TTS** — so the only
  requirement across the whole turn is "quiet enough that the in-room mic and the satellite speaker win."
  That is one floor. (The divergence from AU-01 is therefore deliberate, not an oversight.)
- If the ceiling is **not playing** at wake (`idle`/`paused`) → **IGNORE** (nothing to duck), per AU-01 §4.1.

**Reconciliation with AU-01 §4 decision rules.** Two AU-01 rules both point at a satellite and disagree:
rule 2 (I/O on a different device + no ceiling TTS → **IGNORE**, written for the acoustically-isolated
phone) and rule 4 (in-room satellite needs a clean mic → **PAUSE**). S1a deliberately chooses a third
action — **near-quiet DUCK** — refining both: rule 2's real predicate is *acoustic isolation*, which an
**in-room** satellite breaks (so IGNORE is wrong here); and near-quiet duck is preferred over PAUSE because
pause carries stop-wedge-adjacent risk and empty-queue/resume edge cases, while duck keeps the music going.
**PAUSE is the explicit fallback** if validation (§10) shows even near-quiet residual music defeats Whisper.

## 5. Trigger mechanism

- **HA automation** on `assist_satellite.respeaker_living_room_assist_satellite`:
  - `idle → (listening|processing|responding)` (interaction start) → call resolver **duck** for the
    ceiling zone.
  - `→ idle` (interaction end) → call resolver **restore**.
- The automation calls the resolver via the existing `rest_command.resolver_command` path (a new
  **thin/lightweight `interaction` intent** — note it is a **write**: it mutates ceiling volume — e.g.
  `{mode: duck|restore, zone: ceiling}`) so the duck/restore stays **resolver-owned** (AU-01). No
  `volume_set` from the automation directly.
- Debounce: ignore transient flaps; a new interaction starting before restore **coalesces** to the
  original snapshot (AU-01 §6).
- **Dead-man refresh (AU-02/AU-03 handshake).** The resolver arms a **dead-man timeout** (default 120 s,
  `max_duck_timeout`) that auto-restores if the `→ idle` restore trigger never arrives. A single reply can
  outrun that window, so S1a's automation should **re-fire `duck` on each intermediate transition**
  (`listening → processing → responding`), not only on leaving idle. Re-ducks **coalesce** (keep the
  original baseline) and **re-arm** the dead-man, keeping it alive for the whole turn. See the AU-02/AU-03
  plan (`plans/2026-07-14-au-02-03-interaction-duck-restore-plan.md`, Round-2 invariants).
- **Dead-man's-switch (HA-side gap, distinct from AU-01 §6):** if the satellite aborts / times out / drops
  and **never emits the `→ idle` transition**, the duck fired but restore never will → ceiling stranded at
  the floor. Require a **resolver-side max-duck timeout → auto-restore** (belt-and-suspenders: an HA
  automation timeout too) so a lost turn self-heals. AU-01 §6 covers *resolver restart*; this covers
  *"the restore trigger never arrives."*

## 6. Duck + restore semantics

Delegated to **AU-02/AU-03** (resolver), per AU-01 §5/§6: snapshot `volume_level` at start, `volume_set`
to the interaction floor, restore exactly at DONE; handle user-changed-volume (last-writer-wins), natural
end (don't resume a finished queue — n/a here since S1a doesn't pause), coalesced interactions, and
resolver-restart safety (never leave the zone stuck at the floor).

## 7. Tunables (AU-01 §7, `config.json`)

- `interaction_floor` (%) — single ceiling floor while interacting. **Default: low/near-quiet** so the
  in-room mic and the satellite reply win. Raising it later depends on the XVF3800's **beamforming +
  noise suppression** (directional pickup / uncorrelated-noise rejection) — **not AEC**: the echo canceller
  only cancels the *device's own* playback (it needs that as a reference), and the ceiling is a separate
  device with no reference into the satellite, so AEC cannot reject ceiling music. That is precisely *why*
  near-quiet is the correct conservative default (validate — §10). (AEC only becomes relevant in **S1b**,
  where the satellite's own reply plays while it is still listening — that reply *is* its own reference.)
- `fade_ms` — optional fade on duck-down/restore-up.
- `interaction_ignore_when_idle` (bool) — ceiling not playing → ignore.

## 8. What S1a does NOT do

- **No reply on the ceiling** — replies stay on the satellite speaker (that is **S1b**).
- **No new TTS path / no double-speak surface** — resolver's existing TTS behavior is untouched.
- **No duck/restore reimplementation** — consumes AU-02/AU-03.
- **No privacy/multi-room/targeting** — S2–S4.
- **No exposure change, no `media_stop`, no gpt-4o-mini change.**

## 9. Dependencies, build order, ownership

| Piece | Track / item | Notes |
|---|---|---|
| Duck/restore mechanism (resolver) | **AU-02** (restore) → **AU-03** (duck) | Prerequisite for S1a's build; S1a calls it. Order per BACKLOG §5 (AU-03's dependency is AU-02). |
| Resolver `interaction` intent (`duck`/`restore`, zone) | **S1a** build (resolver) | Thin wrapper over AU-02/03 for the ceiling zone. |
| HA automation (satellite state → resolver interaction) | **S1a** build (HA-live) | The trigger. |
| Satellite reply on ceiling (universal relay) | **S1b** | Follows S1a. |

- **Serialized gate chain (the real scheduling constraint):** AU-02, AU-03, and S1a are **three separate
  live-gate-claiming builds** (resolver / HA). The live gate (BACKLOG §10) admits **one at a time**, so they
  run **AU-02 → AU-03 → S1a**, each claiming and releasing the single gate under approval — a stronger
  constraint than "AU first." **This design claims no gate.**
- **BACKLOG note (INF to reconcile, per §9 shared-file rule):** this doc **decomposes `S1`** into **S1a**
  (duck/restore) + **S1b** (reply-on-ceiling relay); the board currently carries `S1`–`S4` as one row.
- **Feeds:** proves the satellite→zone trigger that S1b (reply-on-ceiling) and S2–S4 (multi-zone) build on.

## 10. Open questions / validation (before build)

- `TODO:` Confirm `assist_satellite` emits **reliable, ordered** state transitions (idle→listening→…→idle)
  usable as duck/restore triggers, and that a barge-in / re-trigger mid-turn coalesces cleanly.
- `TODO:` Tune `interaction_floor` against the XVF3800's **beamforming + noise suppression** (not AEC — see
  §7): can the mic tolerate a higher floor (less disruptive duck), or is near-quiet required? If even
  near-quiet residual music defeats Whisper STT, fall back to **PAUSE** (§4).
- `TODO:` Sequence **AU-02 → AU-03** before S1a's build (serialized gate chain, §9).
- *(Conversation agent is **not** an S1a question: S0 §4 fixes the satellite on "Living Room Voice" —
  local HA + Piper — and a state-keyed duck is agent-independent. Deferred wholly to **S1b**.)*

---

> **Rollback for this document:** `git revert` on `homebrain/s1a-satellite-ceiling-duck`, or delete this
> file. No secrets, no implementation, no exposure, no live gate.
