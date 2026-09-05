# AU-01 — Interaction Audio Policy Design (media-zone pause / duck / resume)

> **Design / research only. No implementation, no resolver/HA/MA change, no exposure, no live gate.**
> Defines the deterministic policy for how the **ceiling media zone** behaves while the assistant is
> interacting (listening / speaking), and how it restores afterward. Design-only; the build is **AU-03**
> (ducking impl) + **AU-02** (resume-restore). Inputs: ONBOARDING §1/§4/§6, `local-music-architecture.md`
> (announce overlay/boost behavior; stop-wedge), `music-assistant-ceiling-zone.md`,
> `2026-06-27-assistant-tooling-design.md` (resolver = sole TTS owner), BACKLOG (AU / S boundary).
>
> Track: **AU** · Item: **AU-01** (`design`, P1) · Branch: `homebrain/au-01-audio-policy-design`.
> Single ceiling zone designed now; **multi-room / satellite-targeted behavior waits on `S0`** (Track S).
> Live gate (BACKLOG §10) left **FREE**.

---

## 1. Scope

**In scope:** the single-zone interaction-audio policy for `media_player.ceiling_speakers` — a
deterministic state model mapping each assistant-interaction phase to a media action (ignore / duck /
pause), plus exact **restore** semantics. Implemented in the **resolver** (sole media + TTS owner).

**Out of scope (Track S / S0):** *which* zone reacts when a conversation happens in a specific room, and
household announcement targeting — these need the satellite→zone map (`S0`) and `ResponseRoutingPolicy`
(`S1`–`S4`). Also out: PCL P0 mechanics (AU / S / PCL boundary, BACKLOG §6). This doc designs the
*mechanism* for one zone and the per-zone *policy interface*; routing is Track S.

## 2. Environment constraints that shape the policy (non-negotiable)

| Constraint | Source | Consequence for the policy |
|---|---|---|
| **Single zone**, MA Universal `upf8b156c25101` → Squeezelite → ceiling | ceiling-zone doc §1/§6 | One zone to manage today; multi-zone is S-gated. |
| **No mute toggle** (`volume_mute` → HTTP error on the Universal player) | `local-music-architecture.md` validation | Ducking must use **`volume_set`**, not mute. |
| **Stop-wedge**: `media_stop` of a live stream wedges the protocol player (RQ-01/RQ-02) | ONBOARDING §6/§10 | **NEVER `media_stop` for an interaction.** `pause` is **lock-free/safe** (~0.4 s); `resume` ~0.4 s. Duck (volume) and pause are the only levers. |
| **Resolver = sole TTS owner**; no second TTS path | tooling design §6/§10 | The policy lives in the resolver; it already holds MA+HA WS + `tts`/`announce`. |
| **Today's announce = overlay + volume *boost*** (e.g. 24%→44%, auto-revert) | `local-music-architecture.md` Inc0 notes | AU-03 should **duck the music under the TTS** instead of boosting everything over it (§5). |
| **Phone conversation**: STT on the phone; TTS replies are **text on phone** (Piper pipeline off + NAT-unreachable) | ONBOARDING §5/§6/§12 | A phone conversation needs **no** ceiling duck for its mic, and produces **no** ceiling TTS → **ignore**. Ceiling TTS today = only the resolver's own announcements. |
| **No satellites yet** (`S0` blocked; reSpeaker incoming) | BACKLOG §2 | The "duck so an in-room mic can hear" case arrives with satellites → design now, wire on S0. |

## 3. Interaction state model (single zone)

An "interaction" is one assistant turn. The policy maps each phase to a media action:

| Phase | What's happening | Media-zone action |
|---|---|---|
| **IDLE** | No interaction. | Normal playback. |
| **LISTENING** | Wake word → capturing a command. | **Future (in-room satellite):** duck to a **listen-floor** so the mic hears, or **pause** if barge-in accuracy needs it. **Today (phone mic):** **ignore** (mic not near the ceiling). |
| **THINKING** | STT/LLM/resolver processing. | Hold the LISTENING action (no change). |
| **SPEAKING** | A TTS response/announcement plays **on the ceiling**. | **Duck** music to a **speak-floor** for the clip (overlay), then restore. For a **long** spoken response, **pause** instead. |
| **DONE** | Interaction ends. | **Restore** exact prior volume; **resume** if paused (§6). |

## 4. Decision rules — ignore vs duck vs pause (never stop)

Evaluated in order:

1. **Nothing playing** (zone `idle`/`paused`) → **IGNORE** (nothing to duck; don't start/alter playback).
2. **Interaction I/O is on a different device than the ceiling** (e.g. phone: mic on phone, reply is
   phone text) **and** no ceiling TTS is emitted → **IGNORE**.
3. **Short ceiling TTS while music plays** (the common case today: no-match feedback, status, a short news
   line) → **DUCK** to the speak-floor for the clip, then restore. Overlay, not stop.
4. **Long spoken response on the ceiling**, or **an in-room satellite needs a clean mic** (barge-in,
   future) → **PAUSE**, then resume on DONE.
5. **Never `media_stop`** as an interaction action — it wedges the stream (RQ-01/RQ-02). Stop stays a
   deliberate user command only.

**Rationale:** duck is the least-disruptive default for short speech; pause is reserved for long speech or
mic-contention; ignore avoids touching a zone that isn't involved; stop is categorically excluded.

## 5. Ducking behavior (replaces today's volume-boost)

- **Duck = lower the music, let TTS ride at normal level** — not the current MA behavior of boosting the
  announcement volume above the music. Cleaner and less startling.
- Mechanism (no mute available): snapshot `volume_level` → `volume_set` to the **speak-floor** (a fraction
  of current, or an absolute floor) → play the announcement (overlay) → **restore the snapshot** on DONE.
- Optional short **fade** on duck-down and restore-up if abrupt steps are jarring (tunable).

## 6. Restore / resume semantics (feeds AU-02)

At interaction **start**, snapshot the zone state: `volume_level`, `state` (playing/paused/idle), and
enough queue context to resume. At **DONE**, restore exactly. Edge cases the AU-02 impl must handle:

- **User changed volume mid-interaction** → do not clobber a deliberate change; treat the newest explicit
  user `volume_set` as authoritative (last-writer-wins over the auto-restore).
- **Playback ended naturally during a pause** → do **not** resume a finished/empty queue.
- **A new interaction starts before the previous restore** → coalesce; a single "restore to the original
  pre-interaction snapshot" wins (don't stack ducks or lose the baseline).
- **Resolver restart / dropped WS mid-interaction** → on reconnect, if a duck was applied and no restore
  ran, restore to a safe baseline (don't leave the zone stuck at the floor).

## 7. Tunable parameters (config-driven, `config.json` — no code change to adjust)

`listen_floor` (%), `speak_floor` (%), `fade_ms`, `long_response_threshold` (→ pause vs duck),
`interaction_ignore_when_idle` (bool). Defaults chosen conservatively at AU-03 impl; all live in
`config.json` per the resolver's config-driven design (tooling §5).

## 8. Single zone now, multi-room later (AU / S boundary)

- **Now:** the mechanism + rules above apply to the one ceiling zone.
- **S0-gated:** *which* zone ducks/pauses when a conversation happens in room X requires the
  satellite→zone inventory (`S0`) and `ResponseRoutingPolicy` (`S1`–`S4`). AU-01 defines the **per-zone
  policy interface** so Track S can call it per target zone; AU-01 does **not** decide routing.

## 9. How this feeds AU-02 / AU-03

| Design section | Implemented by |
|---|---|
| §3–§5 state model, decision rules, duck-not-boost | **AU-03** (ducking implementation — resolver) |
| §6 restore/resume + edge cases | **AU-02** (explicit resume-restore behavior — resolver) |
| §7 tunables | AU-03 (config keys) |
| §8 per-zone interface | consumed by Track S (`S1`–`S4`) once `S0` lands |

Both AU-02 and AU-03 are resolver changes (media path) → they claim the single live gate under approval;
this design claims none.

## 10. What this document does NOT do

- **No resolver/HA/MA change** — no `config.json` edit, no automation/script, no exposure; gpt-4o-mini
  unchanged.
- **No live gate** — design-only; BACKLOG §10 left **FREE**.
- **No routing / multi-zone decision** — that is Track S (`S0`–`S4`).
- **No new TTS path** — the resolver stays the sole TTS owner.
- **No BACKLOG status change beyond a next-action/status note** (INF-owned board, §9) — proposed via this
  track's change, INF reconciles.

---

> **Rollback for this document:** `git revert` on `homebrain/au-01-audio-policy-design`, or delete this
> file. No secrets, no implementation, no exposure, no live gate.
