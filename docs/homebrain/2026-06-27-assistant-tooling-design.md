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

- **Inc 0 — Foundation.** Refactor resolver into modules + clean capability functions
  (the MCP-ready boundary) + config files + the tool set + failure-feedback path. Current
  `resolver.py` stays runnable until the modular version is validated. *(Mostly
  restructuring existing code + scaffolding.)*
- **Inc 1 — Radio.** country/genre play + `find`/list stations.
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
- Transport (play/pause/stop, volume ±% — including the validated relative-volume fix) →
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
