# DRAFT upstream issue — Music Assistant (`music-assistant/server`) — FOR REVIEW, NOT SUBMITTED

> Prepared 2026-06-24. No matching upstream issue exists (searched issues/PRs/discussions/releases). Line numbers are from MA **2.9.3** and are approximate — maintainers should confirm. Submit only after review.

---

**Title:** Playback lock held during slow stream resolution causes overlapping commands to time out ("previous holder appears stuck")

### Environment
- Music Assistant server **2.9.3** (add-on), Home Assistant Core 2026.6.4 (HAOS VM).
- Player: **Squeezelite** (via `aioslimproto`, HTTP/1.0) wrapped by the **Universal Player**.
- Music provider: **YouTube Music** (yt-dlp extraction; resolution is slow — see below).
- `flow_mode` enabled; player `http_profile = no_content_length`.

### Summary
When a track with **slow stream resolution** (YouTube Music: ~14–150 s for yt-dlp/PO-token extraction) is started, the player **playback lock is held for the entire resolution duration**. Any *other* command issued during that window (stop, a second play, switch to radio, an announcement, clear queue) is a different asyncio task, so it blocks on the same lock, waits the full **30 s timeout**, and logs `previous holder appears stuck; proceeding without lock`. With several overlapping commands during one long resolution, the timeouts stack (we observed up to 11). After resolution completes the lock releases and state converges — this is **not** a permanent deadlock, but it makes any concurrent control during start-up unresponsive for ~30 s, and it is the dominant component of YTM start latency.

### Reproduction
1. Use a provider with slow stream resolution (YouTube Music) on a Squeezelite/Universal player.
2. Issue `play_media` for a track (resolution begins; lock acquired).
3. Within a few seconds (before playback starts), issue any second command: `media_stop`, another `play_media`, play a radio station, an announcement (`tts.speak`), or `clear_playlist`.
4. Observe the second command does not take effect for ~30 s; the log shows the lock timeout / "previous holder appears stuck".

### Expected behavior
A control command issued while a track is still resolving should take effect promptly (cancel/replace the in-progress start), not block ~30 s on the playback lock.

### Actual behavior
The second command blocks ~30 s, logs `Timed out (30s) acquiring … lock … previous holder appears stuck; proceeding without lock`, then proceeds unsynchronized. Multiple overlapping commands → multiple stacked 30 s timeouts.

### Relevant logs (representative)
```
WARNING [music_assistant.players] Timed out (30s) acquiring playback lock for player <id> — previous holder appears stuck; proceeding without lock
INFO    [music_assistant.Universal Player] Setting active output protocol on <player> to Squeezelite
DEBUG   [aioslimproto.client.<player>] play url (enqueue: False): http://.../single/.../<id>/...
DEBUG   [aioslimproto.client.<player>] STMf received - connection closed.
```
(A clean, *non-overlapping* play→stop is healthy: `media_stop` → `STMf (connection closed)` → "Clearing active output protocol" → idle, in ~3 s. The problem is strictly overlapping commands during slow resolution.)

### Timing data
- YTM stream resolution: ~14 s typical, up to ~150 s cold.
- Resolution is **not CPU-bound** (host idle, VM CPU ~5 % during the wait) and **not** a network/auth failure — it's serialized behind the held lock.
- Lock timeout: 30 s per blocked command (5 s soft warn + 25 s).

### Ruled out (verified locally)
- **Not** a Squeezelite/SlimProto clean-stop bug — clean play→stop works 6/6 (stop handled via `STMf`).
- **Not** auth/cookie/PO-token — YTM auth + search work; resolution succeeds, just slowly.
- **Not** CPU starvation (VM ~5 % during the wait), **not** DNS.
- **Not** fixable via `http_profile`: `chunked` returns HTTP 500 `Using chunked encoding is forbidden for HTTP/1.0` (Squeezelite is HTTP/1.0); `no_content_length` and `forced_content_length` both keep the contention.

### Hypothesis / apparent code path (please confirm)
The playback lock appears to wrap the slow resolution:
- `controllers/player_queues/controller.py`: the `@handle_play_action` decorator (~L124–158) wraps the **entire** decorated method in `async with players.get_player_lock(queue_id, PLAYBACK)`.
- `play_index()` (~L936, `@handle_play_action`) calls `_load_item(...)` **while holding the lock**, which calls `streams.audio.get_stream_details(...)` (~L1693) → `music_prov.get_stream_details(...)` (the slow YTM/yt-dlp extraction) and `AudioBuffer.get_buffer(..., wait_ready=True)` (~L1710).
- `controllers/players/controller.py` `get_player_lock()` (~L173–232): 5 s soft + 25 s hard; at 30 s logs "previous holder appears stuck; proceeding without lock". Re-entrant per asyncio task, so the *same* play task is fine but a *different* command task blocks.
- Other commands (`stop` ~L677, etc.) are also `@handle_play_action`-decorated → they contend on the same lock.
The 30 s timeout/message itself was introduced in PR #4024 ("Drop redundant per-player throttler and harden the command lock").

### Suggested fix direction
Don't hold the playback lock across slow network I/O. Either:
1. **Resolve outside the lock:** perform `_load_item` (stream resolution + buffer pre-fill) **before** acquiring the playback lock in `play_index`/`_handle_play_media`; take the lock only for the quick player hand-off (`players.play_media`). Add a cancellation check after resolution so a stop/skip that arrived during resolution wins. (Proper fix; needs care around track-transition serialization.)
2. **Or** make `get_player_lock` fast-reject / cancel an in-progress holder for a new user command instead of waiting 30 s (so overlapping commands are responsive).

Happy to provide full VERBOSE SlimProto traces and the per-condition reproduction matrix.
