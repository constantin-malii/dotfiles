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

## 7. Interrupted-state experiment — REAL reproducible defect = lock held during resolution (2026-06-24)

Ran 6 interrupted-state conditions (squeezelite VERBOSE), each from clean idle: (1) YTM play→stop during resolution; (2) 2nd YTM play before 1st starts; (3) YTM→radio before YTM starts; (4) radio playing→YTM→stop during setup; (5) YTM→announcement during setup; (6) YTM→clear queue during setup.

**Results:**
- **Persistent Universal/protocol state mismatch: NOT reproduced** in any condition — states always converged and ended idle. So "protocol stuck `playing` while Universal `idle`" is **not** permanent corruption from these transitions.
- **Retained lock ("previous holder appears stuck"): reproduced in ALL 6** (lock timeouts: c1=1, c2=1, c3=2, **c4=11**, c5=4, c6=1).

**Root cause (reproducible):** the **slow YTM stream-resolution holds the player playback lock for its full ~14–150 s duration.** Any command issued during that window collides with the held lock → 30 s timeout → "previous holder appears stuck" → "proceeds without lock." The lock is **held-during-resolution, not dead** — it releases when resolution completes/aborts, and state converges (finals were idle). This **supersedes** the §2 H1 `power(False)` theory (refuted by §empirical, and not needed — the lock contention fully explains "previous holder appears stuck" + the cold-start latency).

**Revised root-cause statement for an upstream issue:** *MA holds the player's playback lock for the entire duration of (slow) stream resolution, so any concurrent/overlapping command (stop, new play, announcement, clear) blocks for the 30 s lock timeout and logs "previous holder appears stuck."* **Suggested fix:** resolve the stream OUTSIDE the playback lock; acquire the lock only to start/stop the player. This also removes the cold-start latency penalty for overlapping commands.

**Note:** the earlier-observed "permanent" wedge was almost certainly this **transient ≤30–60 s lock-contention window** caught mid-flight during chaotic multi-op sessions — a clean spaced stop is fine (6/6).

## 8. Code-path CONFIRMED + existing-issue scan + workaround feasibility (2026-06-24)

Source-confirmed from MA 2.9.3 (architecture unchanged on `main`). Draft upstream issue: [`upstream-issue-draft.md`](./upstream-issue-draft.md).

**Code path (CONFIRMED — lock IS held across resolution):**
- `controllers/player_queues/controller.py` — `@handle_play_action` (~L124–158) wraps the **whole** method in `async with players.get_player_lock(queue_id, PLAYBACK)`.
- `play_index()` (~L936, decorated) → `_load_item(...)` **inside the lock** → `streams.audio.get_stream_details()` (~L1693) → `music_prov.get_stream_details()` (the slow YTM yt-dlp extraction) + `AudioBuffer.get_buffer(wait_ready=True)` (~L1710). Player hand-off (`players.play_media`) happens only after.
- `controllers/players/controller.py` `get_player_lock()` (~L173–232): 5 s soft + 25 s hard; at 30 s logs "previous holder appears stuck; proceeding without lock". Re-entrant **per asyncio task** → same play task fine; a *different* command task blocks. Other commands (`stop` ~L677, etc.) are also `@handle_play_action`-decorated → contend.
- The 30 s timeout/message came from **PR #4024** (merged 2026-05-29); **no follow-up** refines the lock scope.
- **Fix spot:** move `_load_item` resolution **before** the lock in `play_index`/`_handle_play_media` (lock only the hand-off, add a post-resolution cancellation check); or make `get_player_lock` fast-reject/cancel an in-progress holder.

**Existing-issue scan — NO exact match (novel, fileable):**
- Discussion **#5333** "youtube music slow when selecting music" — confirms slow YTM start (~10 s), maintainer blames hardware; does NOT mention the lock/timeouts. https://github.com/orgs/music-assistant/discussions/5333
- **#5056** (yt-dlp BotGuard/GVS token), **#4000** (needs newer yt-dlp) — explain *why* resolution is slow. **#4896 / #3023** — adjacent slow/failed YTM start, no lock analysis.
- **PR #4024** — introduced the lock timeout + "previous holder appears stuck". https://github.com/music-assistant/server/pull/4024
- Nobody has connected slow-resolution + the lock contention, or reported the overlapping-command 30 s timeout.

**Workaround feasibility (from code):**
- **(A) Pre-resolve / warm-cache → NOT FEASIBLE.** No command resolves a stream without playing; `search`/`get_item`/library-add do NOT warm `get_stream_details`. The streamdetails cache is per-QueueItem, populated only by a prior play/load, and YTM signed URLs expire quickly. Only helps an *immediate* re-play of the same item.
- **(C) pause vs stop → VIABLE.** `player_queues.stop()` is `@handle_play_action`-decorated (takes the lock → 30 s wait mid-resolution). `player_queues.pause()` is **NOT** decorated and calls the internal unlocked pause → returns immediately. **`media_pause` is the lowest-friction interrupt that avoids the 30 s lock wait.** Caveat: a paused queue auto-converts to (locked) `stop()` after ~30 s.
- **(E) Local patch → feasible, deferred.** Smallest/low-risk: shorten the 30 s hard timeout in `get_player_lock` (the "proceed without lock" fallback already runs unsynchronized). Most-correct/medium-risk: move `_load_item` outside the lock in `play_index` (needs a cancellation check). Maintenance burden across add-on updates → prefer upstream.
- **(B) HA-script-level serialization** (not MA code): a helper that rejects/queues overlapping commands while a YTM play is starting ("starting music, please wait") — would avoid the contention at our layer and is the realistic path to safe ChatGPT exposure. To be designed if/when we pursue assistant YTM.

### 8a. Workaround C — EMPIRICALLY VALIDATED (2026-06-24)

Live test from a clean state, with a guard confirming resolution was genuinely in progress (the `play_media` worker thread was still blocking at the +3 s mark before the interrupt was issued):

| Command issued DURING YTM resolution | Returned in | Result | New "previous holder appears stuck" |
|---|---|---|---|
| `media_pause` (Pink Floyd, lock-free path) | **0.0 s** | ok | **0** |
| `media_stop` (Queen, locked path) | **45.0 s** | client-timeout (≥45 s) | **3** |

Matches the code prediction exactly: `pause()` is **not** `@handle_play_action`-decorated → skips the PLAYBACK lock → instant. `stop()` **is** decorated → blocks for the full resolution and stacks 30 s "stuck holder" timeouts. Test harness: `scratchpad/pause_test2.py`; raw log: `scratchpad/pause_test.txt`.

**Important caveat (from code, not yet load-tested):** a paused MA queue **auto-converts to a (locked) `stop()` after ~30 s**. So `pause` buys a ~30 s window of lock-free responsiveness, *not* a durable hold. ⇒ In the assistant design, **the serializer (B) is the load-bearing guard; `pause` (C) is only the fast-feedback / interject primitive.** Design: [`ytm-guarded-assistant.md`](./ytm-guarded-assistant.md).

### 8b. Live integration test of the serializer FAILED — deeper root cause (2026-06-24)

The `ytm_guard.py` serializer passed 7/7 local unit tests but **FAILED the live HA/MA integration test** (`scratchpad/live_guard_test.*`): 19 new "previous holder appears stuck" across the stop/switch scenarios. Root-cause diagnostics (`scratchpad/diag_timing.*`, `diag2.*`) then established the real timing, which invalidates a core assumption:

| Source | `play_media` returns | audio (`state=playing`) | `media_stop` after that |
|---|---|---|---|
| **radio** (control) | **+4.3 s** (ok) | +6.1 s | **0.0 s, clean, 0 stuck** |
| **YTM artist** | **did NOT return in 240 s** | +10 s (diag1) / never (diag2, degraded) | wedges: 45 s, +3 stuck |

**Corrected root cause:** for YTM the MA PLAYBACK lock is held for the **entire `play_media` call**, which does **not return within any practical window** — it stays held *long after audio starts* (a stop at +14 s, 4 s after `playing`, still wedged). So:
- `state==playing` does **NOT** mean the lock is free.
- There is **no safe moment to issue `media_stop`/switch during YTM playback startup** (not at audio-start, not at any tested time before 240 s).
- The serializer premise "defer the real stop until the in-flight play *exits*" fails: the play does not exit in time. The original wrapper made it worse by **forcing a `media_stop` at its 180 s ceiling while the lock was still held** — directly causing the wedges.

**Untested lever — SINGLE-TRACK plays (senior re-analysis, 2026-06-24):** every YTM lock measurement to date used an **artist** URI (`ytmusic://artist/...`), which enqueues many items and (with `flow_mode`) muxes a continuous flow — so `play_index`/`_load_item` may resolve/pre-buffer **multiple items inside the lock** before `play_media` returns. The lock-hold scales with the size of the play operation. **Hypothesis: a single-TRACK play is the smallest critical section** — its `play_media` should return after that one track resolves (~14 s, like radio's ~4 s), releasing the lock so a subsequent `media_stop`/switch is clean. If true, the corrected serializer (never issue stop/play while in-flight; resolve every request to ONE track URI; pause for interim feedback) becomes viable. **Could NOT be tested 2026-06-24: YTM degraded to unplayable** (diag1 artist played @+10 s → diag2 never @240 s → diag3 never @90 s; track search returned None) — almost certainly Google-side rate-limiting from the day's repeated plays. Re-run `scratchpad/diag3.py` after a cool-down to confirm/refute single-track bounded return. Also still unfixed: the wrapper's ceiling-forced-stop bug (must change to never stop while a play worker is alive).

### 8c. Single-track narrow test + DECISION: SHELVED (2026-06-24)

After a ~30 min cool-down, ran the narrow single-track test (`scratchpad/narrow_single_track.{py,txt}`): resolve one concrete track URI → `play_media` → measure return + time-to-playback → `media_stop` after return → check no new "stuck" and BOTH Universal+protocol states sane.

- **TRACK 1 (Bohemian Rhapsody, `ytmusic://track/utwMHfDZ6SA`): `play_media` did NOT return within 150 s, and the player never reached `playing` (uni/prot stayed idle).** 0/1 clean. Per the agreed decision rule ("if play_media does not return → shelve"), **the YTM client-side workaround is SHELVED.**
- **Nuance (kept for honesty):** the track never reached playback (degradation signature), so the single-track *lock* hypothesis is **unproven, not strictly refuted** — a clean test needs a YTM that can actually play. But (a) `play_media` has never returned in bounded time for ANY YTM play all day (only radio returns, ~4 s), leaning against bounded single-track return; and (b) a source that can't play one track in 150 s after a cool-down is too unreliable to expose regardless of the lock. Revisit ONLY if YTM playback reliability is first restored (e.g., a yt-dlp / PO-token / add-on update), then re-run `narrow_single_track.py`.

### 8d. Source-alternatives investigation (2026-06-25)

To "get music working" beyond fighting the YTM lock, checked what else MA could use:
- **MA configured music providers (only 3):** `ytmusic` (problematic), `radiobrowser` (healthy), `builtin`. No Plex/local/Spotify connected. MA *supports* adding `plex`, `filesystem_local/smb/nfs`, `spotify`, `tidal`, `qobuz`, `apple_music`, `jellyfin`, `subsonic`, etc. (provider manifests confirmed via WS `providers/manifests`). Adding a provider is **additive, reversible, and needs no add-on restart** (config save only).
- **Plex/local pivot is BLOCKED — no music files exist.** SSH to host (read-only): Plex is running but serves **video/photo only** (`/media/MediaServerData` = Movies, TV Shows, Video, Photo, ProgrammingTutorials; 0 mp3, 0 flac, 3 stray m4a). `/home/costea` has no music; `/mnt/nas` not mounted. So a Plex/filesystem provider would have nothing to serve.
- **MA add-on / yt-dlp version:** can't read programmatically (HA supervisor API → 401). MA server = **2.9.3** (schema 31). Updating the add-on (newer bundled yt-dlp) must be done in the HA UI.
- **Self-inflicted load:** MA runs a full **YTM library sync every ~2 h** (artists/albums/tracks/playlists/podcasts) — a heavy recurring YTM workload that likely feeds the rate-limiting/degradation. Disabling it is a low-risk config lever.

**Implication:** reliable assistant-controllable music needs a *well-behaved source* (radio already is; a streaming sub like **Spotify/Tidal/Qobuz/Apple** would resolve fast + stop clean like radio; or build a local library). YTM hardening (add-on update + disable sync) is possible but YTM stays inherently fragile. Awaiting user choice of source.

**Final status:** workaround C/serializer is **NOT validated and is shelved.** Radio remains healthy and needs no guard. Still-true validated facts: `pause` is lock-free during resolution; `stop` during resolution wedges (§8a); for YTM the lock is held for the entire `play_media` call (§8b). YTM stays **unexposed to the LLM** — today's degradation reinforces that. Artifacts kept for a future attempt: `ytm_guard.py` (+ `test_ytm_guard.py`, has a known ceiling-forced-stop bug), `ytm-guarded-assistant.md`; rollback = delete those files.
