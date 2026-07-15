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

## 4. Interaction flow (single zone)

```
"Okay Nabu"                → assist_satellite: idle → listening
   └─ trigger: leaving idle → resolver DUCK ceiling (snapshot vol, volume_set → listen/​speak floor)
(user speaks; STT; agent)   → processing / responding   [ceiling stays ducked]
reply on SATELLITE speaker  → (S1a: local; ceiling remains ducked so the reply is audible)
interaction ends            → assist_satellite: → idle
   └─ trigger: back to idle → resolver RESTORE ceiling (restore snapshot; AU-01 §6 edge cases)
```

- **One duck for the whole turn** (listen + think + speak), restored once at DONE — no per-phase churn
  (simpler than AU-01's per-phase floors; S1a uses a single interaction floor).
- If the ceiling is **not playing** at wake (`idle`/`paused`) → **IGNORE** (nothing to duck), per AU-01 §4.1.

## 5. Trigger mechanism

- **HA automation** on `assist_satellite.respeaker_living_room_assist_satellite`:
  - `idle → (listening|processing|responding)` (interaction start) → call resolver **duck** for the
    ceiling zone.
  - `→ idle` (interaction end) → call resolver **restore**.
- The automation calls the resolver via the existing `rest_command.resolver_command` path (a new
  read/side-effect-light **`interaction` intent**, e.g. `{mode: duck|restore, zone: ceiling}`) so the
  duck/restore stays **resolver-owned** (AU-01). No `volume_set` from the automation directly.
- Debounce: ignore transient flaps; a new interaction starting before restore **coalesces** to the
  original snapshot (AU-01 §6).

## 6. Duck + restore semantics

Delegated to **AU-02/AU-03** (resolver), per AU-01 §5/§6: snapshot `volume_level` at start, `volume_set`
to the interaction floor, restore exactly at DONE; handle user-changed-volume (last-writer-wins), natural
end (don't resume a finished queue — n/a here since S1a doesn't pause), coalesced interactions, and
resolver-restart safety (never leave the zone stuck at the floor).

## 7. Tunables (AU-01 §7, `config.json`)

- `interaction_floor` (%) — single ceiling floor while interacting. **Default: low/near-quiet** so the
  mic hears and the satellite reply is audible. The XVF3800's hardware AEC/beamforming may allow raising
  this later (validate — §10).
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
| Duck/restore mechanism (resolver) | **AU-03** (duck) + **AU-02** (restore) | Prerequisite for S1a's build; S1a calls it. |
| Resolver `interaction` intent (`duck`/`restore`, zone) | **S1a** build (resolver) | Thin wrapper over AU-02/03 for the ceiling zone. |
| HA automation (satellite state → resolver interaction) | **S1a** build (HA-live) | The trigger. |
| Satellite reply on ceiling (universal relay) | **S1b** | Follows S1a. |

- **Build gate:** S1a's build is a **resolver change + HA automation** → claims the single live gate
  (host-live/HA) **under approval**, after AU-02/AU-03. **This design claims no gate.**
- **Feeds:** proves the satellite→zone trigger that S1b (reply-on-ceiling) and S2–S4 (multi-zone) build on.

## 10. Open questions / validation (before build)

- `TODO:` Confirm `assist_satellite` emits **reliable, ordered** state transitions (idle→listening→…→idle)
  usable as duck/restore triggers, and that a barge-in / re-trigger mid-turn coalesces cleanly.
- `TODO:` Tune `interaction_floor` against the **XVF3800 AEC** — can the mic hear at a higher floor (less
  disruptive duck), or is near-quiet needed?
- `TODO:` Confirm AU-02/AU-03 exist (or sequence them first) before S1a's build.
- `TODO:` Decide the satellite's conversation agent for the interaction (deterministic **Home Assistant**
  vs **ChatGPT**) — affects S1b more than S1a, but note it now.

---

> **Rollback for this document:** `git revert` on `homebrain/s1a-satellite-ceiling-duck`, or delete this
> file. No secrets, no implementation, no exposure, no live gate.
