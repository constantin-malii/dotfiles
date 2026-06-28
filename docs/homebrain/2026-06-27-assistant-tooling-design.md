# Homebrain Assistant Tooling — Design Spec

**Date:** 2026-06-27
**Status:** Approved design (pre-implementation)
**Related:** [local-music-architecture.md](local-music-architecture.md) (living architecture doc), [homebrain-architecture.md](homebrain-architecture.md)

## 1. Purpose

Define the tool surface and backend architecture that lets the ChatGPT voice assistant
control a **local-first music + radio + news experience** on the ceiling speakers, in a
way that is **maintainable** (config-driven, no tool sprawl), **honest** (the speaker
tells the truth when something can't be found), and **extensible** (clean function
boundaries that can later be exposed over MCP).

This spec is the umbrella design. Each capability ships as its own increment with its own
implementation plan (see §6). It is explicitly **additive and reversible**: nothing that
works today is removed or capped — see §7.

## 2. Goals & non-goals

**Goals**
- A small, well-described set of *content* tools ChatGPT can call reliably.
- A single backend "brain" (the resolver) that owns provider knowledge and decisions.
- Config-driven extensibility: new countries, feeds, providers = data edits, not code.
- Honest spoken feedback on failure (end the "says playing when nothing matched" problem).
- A boundary clean enough to wrap as MCP later, without committing to MCP now.

**Non-goals (for this design)**
- Switching to MCP now (future option only; §5).
- Re-enabling YouTube Music (separate, later roadmap item).
- Touching Plex, the old HA Core, networking, or video libraries.
- Adding transport (play/pause/volume) as LLM tools — transport stays in the fast local
  sentence-trigger layer (§3).

## 3. Tool surface (what ChatGPT sees)

Two layers, unchanged in principle from today:

1. **Local sentence-trigger layer (no LLM)** — `automation.voice_ceiling_speakers`.
   Handles bare transport phrases deterministically and fast: play/pause/resume/stop,
   relative volume ±%, absolute "set volume to N". **Stays as-is.** Transport is NOT
   exposed as ChatGPT tools.

2. **ChatGPT content tools (LLM fallback)** — a small, stable set, each backed by an HA
   script that fires a `mass_<x>_request` event to the resolver:

   | Tool        | Intent                                              | Status |
   |-------------|-----------------------------------------------------|--------|
   | `play_music`| Play local artist/album/track/playlist              | exists |
   | `play_radio`| Play a station — by name, **country**, or **genre**  | extend |
   | `find`      | Discovery queries (list stations by country/genre…) | new    |
   | `news`      | Headlines (TTS) or a news station, by country/topic | new    |
   | `acquire`   | Request a song/artist via Lidarr (guarded)          | new    |
   | `status`    | What's playing / queue / now-playing info           | new    |

   ~6 content tools total. The set is deliberately small; breadth comes from *parameters*
   (country, genre, topic, mode) and *config*, not from more tools.

## 4. Backend architecture (the resolver "brain")

The resolver becomes modular. Each module is one clear purpose with a clean capability
function, decoupled from the HA-event transport so it can be unit-reasoned and later
wrapped as MCP:

```
resolver/
  core      — WS clients (MA + HA), event dispatch, matcher, failure-feedback TTS
  music     — resolve_music(query, media_type) -> play local
  radio     — resolve_radio(name|country|genre) -> play; list_stations(...)
  news      — get_news(country, topic, mode) -> headlines TTS | play station
  acquire   — acquire(query) -> Lidarr add+search (guarded)
  status    — status() -> now-playing / queue
```

**Transport boundary:** the capability functions (`resolve_music`, `resolve_radio`,
`get_news`, `acquire`, `status`) take plain arguments and return plain results. The
HA-event subscription (`serve()`) is a thin adapter that parses an event and calls the
matching function. An MCP server would be a *second* adapter over the same functions —
no rewrite. We are not building that adapter now.

**Flow:** `ChatGPT tool → HA script fires mass_<x>_request{params} → core dispatch →
module function → action (play via MA / TTS / Lidarr) → optional spoken result.`

## 5. Config-driven extensibility

All tunables live in data files in `~costea/mass-resolver/` — adding a country alias, a
news feed, or a streaming provider is a data edit, not a code change.

- `config.json` (non-secret) — MA/HA hosts, ceiling player id, **music provider
  preference** (`["filesystem_smb"]` today; append providers later), event names.
- `radio.json` — favorites/aliases, per-country/genre defaults, **country-name→code
  aliases** (Romania→ro, Russia→ru).
- `news.json` — **feeds per country/topic** (`{"romania":[rss…], "world":[…]}`) and/or
  preferred news-station names.
- secrets (`0600`, costea-owned, never in repo) — `.ma_token`, `.ha_token`, `.lidarr`
  (url + API key).

## 6. Failure feedback (honest speaker)

On no-match / failure, the resolver **TTS-announces the truth** ("Couldn't find X
locally") via its HA connection. Built into `core`, so every capability inherits honest
spoken feedback. This fixes the current behavior where ChatGPT's fire-and-forget reply
says "playing" while nothing actually matched.

## 7. Build order (each = its own spec → plan → build, validated, docs updated)

- **Inc 0 — Foundation. ✅ DONE (2026-06-27).** Refactored the monolith into modules
  (`wsutil`/`match`/`config`/`maconn`/`haconn`/`music`/`core` + `radio`/`news`/`acquire`/
  `status` stubs) with the MCP-ready capability boundary, config scaffolds
  (`radio.json`/`news.json`), and the honest failure-feedback path (wired to local
  `tts.piper`). 49 unit tests; validated live on the host (Python 3.5.2) — music play
  (`filesystem_smb`, ~0.2–0.4 s), `music/sync`, and spoken no-match all confirmed via
  one-shot CLI and end-to-end HA events. Original preserved as `resolver.py.orig` (+ git
  baseline `2e2bec7`). Plan: `plans/2026-06-27-inc0-resolver-foundation.md`.
- **Inc 1 — Radio. ✅ DONE (2026-06-28).** Resolver-controlled radio: play by
  name/country/genre/language + `find`/list (favorites-first → RadioBrowser), config-driven via
  `radio.json`, dry-run mode, honest feedback, name-dedupe. 90 unit tests; deployed + dry-run + audible
  validated; exposed to ChatGPT (`play_radio`/`find_stations`; legacy `ceiling_play_radio` un-exposed
  from ChatGPT but kept for the local sentence-trigger layer). Plan:
  `plans/2026-06-27-inc1-radio.md`. Residual (deferred, see §10): gpt-4o-mini sometimes declines a
  genre-play or mis-states results — addressed by synchronous play-result + a gated model eval.
- **Inc 2 — News.** `news.json` sources; stations + headlines/TTS.
- **Inc 3 — Acquisition.** `acquire` via Lidarr, guarded.
- **Inc 4 — Status + household.** now-playing/status + sleep timer + shuffle favorites.

Each increment: small, validated with real playback, additive/reversible, docs updated,
and **not exposed to ChatGPT until validated**.

## 8. No-loss guarantee (explicit)

The tool surface is a **superset**, not a replacement. Everything that works today is
preserved:

- Local music resolver playback → becomes `core` + `music` (same logic, reorganized).
- Radio (`ceiling_play_radio`, favorites + arbitrary stations) → becomes `radio`, **gains**
  country/genre/list on top.
- Transport (play/pause/stop, volume ±% — including the **validated & locked** relative/absolute
  volume fix, COMPLETE 2026-06-28; see local-music-architecture.md "Voice volume control — STABLE") →
  **untouched**, stays in the fast local sentence-trigger layer.
- Lidarr→MA auto-sync webhook → **untouched**; `acquire` adds a manual path alongside it.

Two deliberate, reversible notes:
1. `ceiling_set_volume` was un-exposed from ChatGPT to fix the "volume up 10%" → "sets to
   10%" confusion. Absolute set still works via the local sentence-trigger ("set volume to
   40"). Re-exposable to ChatGPT with one flag if desired.
2. MCP is a future option behind the clean function boundary — nothing is removed to allow
   it; the door is simply open later.

## 9. Constraints (carried from project rules)

- Secrets/tokens NEVER in repo/docs/logs; store in `0600` costea-owned files; never echo
  tokens in commands (use stdin pipes); document token rotation.
- Don't touch Plex / old HA Core / networking / video libraries.
- Ask before `sudo` (no passwordless sudo; user runs sudo). Don't restart services unless
  needed (user restarts systemd).
- Keep changes additive/reversible. Do NOT expose new functionality to ChatGPT until
  validated. No Claude/AI attribution in commits & PRs. Secret-scan before commits.

## 10. Open items / backlog (tracked, not in scope of a specific increment yet)

- Semantic match gap (e.g. "Angel" → German "Engel"): ChatGPT should map; resolver may add
  alias/translation hints.
- Music breadth decision (streaming Tidal/Qobuz vs Soulseek) — informs `acquire` and the
  music provider preference list.
- Remove redundant empty host provider `filesystem_smb--yYrXcamj`.
- Metadata cleanup; Plex Music library browsing.
- **Synchronous play result (accepted Inc-0 caveat, 2026-06-27):** `play_music` is fire-and-forget, so
  ChatGPT's text can optimistically say "Playing X" for a genuinely-missing local item while the
  speaker (Piper) honestly announces "couldn't find X". The speaker is authoritative. A future
  increment can make the play path return a found/not-found result so ChatGPT's text is also exact.
  Do not block other increments on this.
- **Assistant model evaluation (gated, 2026-06-28):** gpt-4o-mini occasionally fails tool-selection
  (declines a genre-play; mis-states results). Keep gpt-4o-mini for now. Evaluate gpt-4o (or
  gpt-4.1-mini) **only after** the synchronous play-result work above is complete **and only if**
  tool-selection failures still persist. Model is a one-field change; do not change it preemptively.
- **Hardware volume buttons → ceiling speakers (Home Mode)** — see §11. Deferred until the
  resolver, ChatGPT integration, and the local-music workflow are complete/stable.

## 11. Deferred feature — Hardware volume buttons → ceiling speakers (Home Mode)

> **Status: backlog only. Do not implement** until (1) the resolver architecture is complete,
> (2) ChatGPT integration is complete, and (3) the local-music workflow is stable.

### Background
The HA Media Player widget works well, but Android hardware volume buttons currently only
adjust the phone's media volume. The desired future behavior: while at home, the phone's
hardware Volume Up/Down buttons control the **ceiling speakers** instead of (or in preference
to) the phone.

### Goal
When connected to the home environment (preferably home Wi-Fi), pressing the Galaxy S26 Ultra
hardware Volume Up/Down should increase/decrease the ceiling speaker volume.

### Preferred architecture
- Investigate **Tasker** as the primary implementation on the phone.
- Keep playback/transport logic inside the **resolver**; the resolver stays the single
  orchestration point (control plane).
- Tasker should call a **small resolver HTTP API** (e.g. `POST /volume/up`, `/volume/down`)
  rather than calling Home Assistant services directly. **Prerequisite:** the resolver has no
  HTTP ingress today (it is HA-WebSocket-event driven, with MCP as a future option). This
  feature therefore depends on adding a tiny LAN-bound HTTP endpoint to the resolver that maps
  to the same capability layer (a third adapter alongside the HA-event adapter and future MCP).
  Bind to the LAN interface only; consider a shared-secret/token; keep it additive.
- Map the endpoints to the existing relative-volume logic (the validated ±% step), so phone
  buttons and voice/widget all converge on one volume implementation.

### Future capabilities to investigate
- Home Wi-Fi (SSID) detection; auto enable/disable on home/away.
- Short press = volume up/down. Long press (optional) = next/previous. Double press (optional)
  = play/pause. Haptic feedback if appropriate.
- Guaranteed normal phone-volume behavior when away from home.

### Acceptance criteria
- **Zero impact outside the home.**
- Does **not** interfere with phone calls or Bluetooth headphone volume.
- Resolver remains the system's control plane.
- Modular enough to support future devices (other Android phones/tablets).

### Android / Tasker limitations & risks (investigate before committing)
- **Intercepting/suppressing hardware volume keys is the hard part.** Modern Android (12–15)
  does not give background apps a clean, global way to capture volume keys and *suppress* the
  phone's own volume change. Tasker's volume-key events generally need an active media session,
  the screen on, or its Accessibility service; reliably overriding the system volume panel from
  the background is not guaranteed. A likely-viable pattern is a dummy/foreground media session
  that owns the volume keys while home, with Tasker mapping its volume deltas to resolver calls
  — needs prototyping.
- **Samsung One UI specifics:** the One UI volume panel, Good Lock/Routines, and Bixby Routines
  may conflict or offer an alternative trigger path; Adaptive Battery / Doze can kill Tasker in
  the background (whitelist required).
- **Permissions:** Tasker likely needs Accessibility service, notification access, "modify
  system settings," and on Android 8.1+ **location permission** to read the Wi-Fi SSID
  (precise/"always" location on newer versions). May need the AutoInput plugin.
- **Conflict states to detect and defer to the OS:** in-call (volume = call volume) and BT
  headphones connected (volume = AVRCP device volume). The feature must bow out cleanly in both.
- **Reliability:** background profile survival under Doze/One UI battery management; debounce of
  rapid presses; latency of the LAN round-trip to the resolver vs. the perceived button feel.
