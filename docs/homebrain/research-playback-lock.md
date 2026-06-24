# Research: MA/Squeezelite Playback-Lock & Stop-Wedge (upstream)

**Read-only upstream research, 2026-06-24.** Goal: find the root cause / any existing fix for the stop-wedge where, after `media_stop`, the Squeezelite **protocol player stays `playing`** while the MA **Universal Player** goes `idle`, holding a playback lock ("previous holder appears stuck"). See [`ONBOARDING.md`](./ONBOARDING.md) §8–§13 for the local investigation that led here.

> **Caveat / calibration:** the exact log string `previous holder appears stuck` does **not** appear in any public MA issue or discussion — it is an internal MA log line. The findings below are traced from MA + aioslimproto **source** (tag 2.9.3 / main) and from related issues/PRs, not from a bug report describing this exact repro. Claims are labelled **CONFIRMED** (read in source / quoted) or **INFERRED** (mechanistic deduction). The one local experiment that would confirm vs. refute the leading hypothesis is in §5. **Our repro appears to be ahead of the public issue tracker.**

> ## ⚠️ EMPIRICAL UPDATE (2026-06-24) — the leading hypothesis was TESTED and REFUTED
> A VERBOSE SlimProto trace of **6 clean radio play→stop cycles (6/6 clean, 0 wedged)** contradicts §2 H1/H1b:
> - Every stop returned both Universal **and** protocol players to `idle`.
> - The stop is signaled and handled via **`STMf` (connection closed)**, NOT `STMu`. So the claim "only `STMu`→STOPPED; connection-close emits no state-changing STAT" is **wrong** — `STMf` drives a clean stop.
> - The `power(False)` no-op would make **every** stop wedge; none did → the deterministic-no-op hypothesis is **refuted**.
> - **No upstream bug report was filed** (evidence doesn't support it).
>
> **Revised understanding:** the normal stop path is fine. The wedge is **condition-dependent / intermittent** — it only appeared amid **contended, interrupted, or errored** states (rapid back-to-back plays, **stop during resolution/buffering before `STMs`**, source switching, or a stream that 500'd/disconnected — e.g. the `chunked` HTTP-500 path, or a YTM stream that dropped). The true trigger is in an **error/interrupt path**, not the clean stop. **Next validation:** reproduce a wedge under those conditions and trace which STAT is missing (likely no clean `STMf`/`STMs` on an interrupted/errored stream), before any upstream report. Expected clean-stop reference timeline: `media_stop` → `STMf` (connection closed) → "Clearing active output protocol" → idle.

## 1. Root-cause tree

```
media_stop on Universal Player (upf8b156c25101)
│
├─ Universal Player stop/play coroutine holds the PLAYBACK lock
│  (controllers/players/controller.py: @handle_player_command(lock=PLAYBACK);
│   5s warn / 30s hard timeout; lock released only in `finally` when the
│   decorated coroutine RETURNS)                                   [CONFIRMED, present in 2.9.3]
│
├─ Universal Player forwards stop to the Squeezelite PROTOCOL child
│  providers/squeezelite/player.py stop():
│     PlayerType.PROTOCOL  →  client.power(False)   (NOT client.stop())   [CONFIRMED]
│
├─ MA protocol-player state = STATE_MAP[SlimClient.state]
│  STOPPED→IDLE ; PLAYING/BUFFERING/BUFFER_READY→PLAYING          [CONFIRMED]
│  ⇒ MA reports `playing` while SlimClient.state ∈ {PLAYING, BUFFERING}
│
└─ ROOT: SlimClient never reaches STOPPED ⇒ MA never reports IDLE
   ├─ (a) aioslimproto state is driven by player STAT messages:
   │       only STMu (normal end-of-playback) → STOPPED; STMo (underrun) → BUFFERING;
   │       STMs → PLAYING. Connection-close / content-length-end emits NO
   │       state-changing STAT unless the player itself sends STMu.   [CONFIRMED]
   ├─ (b) Squeezelite (player) detects end-of-stream ONLY via socket recv()==0;
   │       it does NOT parse Content-Length or chunked. aioslimproto issues a
   │       hardcoded `GET … HTTP/1.0 … Connection: close` fetch.       [CONFIRMED]
   │       On a no_content_length/forced_content_length stop, MA stops feeding the
   │       generator but socket-close vs the player's STMu race; the player keeps
   │       draining its buffer (STMo/PLAYING) instead of a clean STMu.  [INFERRED]
   └─ (c) **power(False) no-op guard [STRONGEST mechanistic candidate]:**
           aioslimproto power() does `if self.powered == powered: return` BEFORE
           stop(). Universal players manage power at the group level, and protocol-
           player power forwarding was removed (PR #3659). If the child's `powered`
           is already False, `power(False)` is a no-op → `strm "q"` never sent →
           SlimClient.state never set to STOPPED.                       [INFERRED]

CONSEQUENCE: protocol child stuck PLAYING → the Universal stop/play coroutine
awaiting child convergence never returns → PLAYBACK lock never released in
`finally` → next play waits 5s+30s → "Timed out (30s) acquiring playback lock …
previous holder appears stuck; proceeding without lock" → often aborts
("Clearing active output protocol"). Only an add-on restart (new SlimClient) clears it.
```

**Why each `http_profile` behaves as observed (consistent with the tree):**
- `chunked` → MA calls `resp.enable_chunked_encoding()`, but the request is HTTP/1.0 → **aiohttp itself** raises `RuntimeError: Using chunked encoding is forbidden for HTTP/1.0` → HTTP 500 → playback breaks. BUT the hard teardown makes the player emit a clean STMu → STOPPED → IDLE (the only value that cleanly un-wedges stop).
- `no_content_length` (default) / `forced_content_length` → valid HTTP/1.0, play fine, but the player never gets the EOF→STMu signal in time on stop → stays PLAYING → wedge. **Matches our A/B exactly.**

## 2. Ranked hypotheses (reconciled with ONBOARDING §9)

- **H1 (NEW LEADER) — `power(False)` no-op skips the actual stop on the protocol child. [HIGH]**
  - Support: `squeezelite/player.py` uses `client.power(False)` for PROTOCOL stop (not `client.stop()`); aioslimproto `power()` early-returns when `powered` is unchanged; protocol-player power forwarding removed in **PR #3659** (2026-04-12; later partly re-added for standalone in #3755/#3721). With power managed at the group level, the child's `powered` can already be False → `power(False)` is a no-op → `strm "q"` never sent → state never STOPPED.
  - Contradiction: aioslimproto `stop()` (when actually reached) sets STOPPED optimistically; so the wedge requires the stop NOT to be reached — consistent with the no-op guard.
- **H2 — No connection-close→STOPPED transition; STMu never emitted on a content-length/close stop. [HIGH mechanism / MEDIUM as sole cause]**
  - Support: aioslimproto only maps STMu→STOPPED; Squeezelite relies on `recv()==0` for EOF; the `chunked`-only clean-stop result corroborates that EOF/STMu signaling governs reaching STOPPED. Needs to combine with H1 (stop not actually sent) to wedge.
- **H3 — Late STMo/STMs overwrites an optimistic STOPPED during buffer drain. [MEDIUM]**
  - Support: optimistic STOPPED on stop, but inbound STMo→BUFFERING(=PLAYING). flow_mode=true + flac → more buffered audio → wider race window (consistent with flow_mode NOT fixing it).
- **H4 — The lock fallback (PR #4024) is the bug. [LOW — it's the symptom handler]**
  - PR #4024 (merged 2026-05-29) introduced the 5s/30s "previous holder appears stuck; proceeding without lock". It *detects/works around* a hung holder; it doesn't create the hang.

**Reconciliation with prior local hypotheses:** the old ONBOARDING §9 H1 ("Squeezelite HTTP/1.0 → run HTTP/1.1 to make `chunked` usable") is now a **DEAD END** — the HTTP version is **server-dictated** by aioslimproto's hardcoded `HTTP/1.0` request line, **not** by the Squeezelite client; no Squeezelite build/flag changes it. The real leader is H1 above (MA-side stop path).

## 3. Relevant upstream issues / PRs / source

**Exact-match issues for the error strings / http_profile-Squeezelite behavior: NONE found** (searched "previous holder appears stuck", "acquiring playback lock", "Using chunked encoding is forbidden for HTTP/1.0", http_profile+squeezelite — all empty in the issue trackers).

Most load-bearing (source / PRs):
- **PR #4024** "Drop redundant per-player throttler and harden the command lock" — MERGED 2026-05-29; introduced the lock timeout + "previous holder appears stuck" message; lock released only in `finally`. https://github.com/music-assistant/server/pull/4024
- **PR #3659** "Remove protocol player power control forwarding" — MERGED 2026-04-12; plus **#3755 / #3721** re power control for squeezelite. Govern the `power(False)` stop path (H1). https://github.com/music-assistant/server/pull/3659
- MA source (tag 2.9.3): `controllers/players/controller.py` (lock + message), `providers/squeezelite/player.py` (`stop()`→`client.power(False)`, `STATE_MAP`), `controllers/streams/controller.py` (`http_profile` branches + `enable_chunked_encoding()`).
- aioslimproto source (`client.py`, main): `power()`/`stop()`/STAT handlers; hardcoded `GET … HTTP/1.0 … Connection: close`. https://github.com/music-assistant/aioslimproto

Behaviorally related (not exact matches):
- **Discussion #4198** — maintainer: "Universal groups do not support pause so **stop is used under the hood**" → the Universal Player issues `stop` (not pause) to the child; so this stop path runs on *pause* too. https://github.com/orgs/music-assistant/discussions/4198
- **Issue #5046** (closed, fix-to-be-confirmed) — Universal-Player wrapper introduced ~2.8.0b15 (the architecture this bug lives in). https://github.com/music-assistant/support/issues/5046
- **#5125** stop/pause when idle → error; **#5035** player "stays stuck", restart-to-clear; **#4426** AirPlay frozen on rapid skip (same state-desync class); **#4756** slimproto instability (stale); **#4353** squeezelite buffer params break status reporting.
- Player-support doc (the three `http_profile` values, "try each per player"). https://www.music-assistant.io/player-support/squeezelite/

## 4. Existing fixes / workarounds

- **No shipped fix.** 2.9.3 is current stable (2026-06-22); **2.10.0 beta/nightly** changelogs (through 2026-06-24) contain **no** squeezelite/slimproto/lock/stop/state entries → **upgrading MA is not a known fix.**
- **"Run Squeezelite with HTTP/1.1" is a DEAD END** — the HTTP version is set by aioslimproto's server-side request line, not the player; no Squeezelite flag changes it. (So `chunked` can't be made usable that way.)
- `http_profile=chunked` cleanly un-wedges stop but **500s playback** (unusable) — only useful as confirmation that a hard EOF→STMu un-wedges it.
- Maintainer design fact: Universal players use **stop**, not pause, under the hood (Discussion #4198) → the wedge path runs on pause too.
- **Only reliable clear today:** restart the MA add-on (re-instantiates SlimClient, resets state).

## 5. Recommended next experiment (single highest value)

**One debug trace to discriminate H1 vs H2/H3, then file a precise upstream issue (no fix exists; our repro is ahead of the tracker).**

- Enable debug logging for `aioslimproto` and `music_assistant.providers.squeezelite`, do a clean **play → media_stop**, and capture **in order**:
  1. Whether aioslimproto **sends `strm "q"`** at stop. **Absent ⇒ H1 confirmed** (the `power(False)` no-op skipped the actual stop).
  2. Which **STAT** messages arrive after stop — a **late STMo/STMs after STOPPED**, or the **absence of STMu** ⇒ H2/H3.
- That single trace tells maintainers exactly which path is broken. If H1, the upstream fix is likely a one-liner: call `client.stop()` for PROTOCOL stop (or drop the `powered`-unchanged early-return when a stop is required).
- Rationale: every candidate cause is in code identical across 2.9.3 and main → **no "upgrade to vX.Y" escape hatch** and **no Squeezelite flag** to flip. The bug is in how MA issues stop for PROTOCOL players + how aioslimproto reconciles state on a content-length/close stream end.
- **Marginal operational mitigation to try (not a root fix):** since Universal players issue `stop` for both stop and pause, test whether `media_pause` then `media_stop` (or play→pause) changes the STAT sequence enough to emit STMu — expect it to be marginal given flow_mode buffering.

## 6. Implications for our setup
- The stop-wedge is an **MA-side defect** (PROTOCOL stop via `power(False)`), not a Squeezelite/HTTP version problem and not fixable by config or by upgrading MA today.
- Practical impact remains bounded: audio stops; only the **next** play after a stop is delayed ~30–60 s by the stale lock; first play from a clean state is fine.
- Path to a real fix: capture the §5 debug trace → open an upstream MA (`music-assistant/server` + `aioslimproto`) issue with it → likely a small MA patch. Until then, keep YTM **unexposed to the LLM** and the assistant on radio.
