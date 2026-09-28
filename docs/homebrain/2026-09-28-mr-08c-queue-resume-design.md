# MR-08c — The queue survives a spoken reply (and "resume") — Design

**Status:** draft for operator review (2026-09-28). Bundles `MR-08e` (log the query on a music miss) into
the same deploy; MR-08e's design was approved in chat and is recorded in §9.
**Backlog:** `MR-08c` (next), `MR-08e`. **Not in scope:** `MR-08b` (shuffle), `MR-08d` (agent knows playlist
names), `MR-08f` (STT/wake settings — separately gated).

## 1. Intent

A question asked while the ceiling plays a playlist, album or `.m3u` must not cost the rest of the queue.
After Nabu answers, the interrupted song continues **where it was**, and the queue carries on as before.
Radio keeps working exactly as today from the listener's point of view. "Pause" then "resume" by voice must
also keep the queue.

Success, observed live: play "Costea mix", ask "what time is it?", hear the answer, and the same song resumes
at about the same position; the MA queue still holds all 8 songs and no reply clip; the next song follows.

## 2. Problem today (verified 2026-09-28)

`interaction.py` delivers every reply through HA `music_assistant.play_media` **without an `enqueue`
option**, which MA treats as *replace*:

- `_play_clip_and_wait` (line 1193): `play_media {entity_id, media_id: <clip>}` — the queue is discarded.
- `_say` step 9 (line 1713) and the `finally` abort path (line 1754): replay **only** `source_id`, the
  single `media_content_id` captured at step 1, again with replace, from position 0.
- `_resume` (line 408): replays `_last_source` by URI with replace, even when the player is merely paused.

Observed: after one question the queue was `[reply clip, current song]`; with repeat=all it wrapped to the
stale `.flac` clip and stopped. No test models a multi-item queue (16 replay tests assert "the captured URI
was replayed once").

## 3. Live spike findings (2026-09-28, throwaway scripts, operator-approved)

On this player (ceiling Universal Player, MA `player_queues/*` over the resolver's websocket):

| Step | Observed |
|---|---|
| HA `music_assistant.play_media` with `enqueue: "play"` | clip inserted **after** the current item (idx+1), current song stopped, clip played; **queue kept all 8 songs** |
| clip ended | queue went **`idle` on the clip** — MA did **not** advance to the next song |
| `player_queues/delete_item` on the **current** item | silently did nothing (no error) |
| `player_queues/play_index(index=<queue_item_id>)` | interrupted song played, from 0 |
| `player_queues/seek(position=14)` | position restored |
| `delete_item(<clip queue_item_id>)` once not current | clip removed; queue back to the original 8 |
| Piper `tts_get_url` | `.mp3` this time (the `.flac` failure mode is AN-01's, still open) |

So: **enqueue-play keeps the queue; the resolver must resume explicitly; the clip can be deleted only after
the resume.**

## 4. Design

### 4.1 Invariants (operator-stated, binding)

1. **Capture before enqueue.** The interrupted item's `queue_item_id`, its position (`elapsed_time`) and its
   seekability are captured **before** any reply clip is enqueued.
2. **Exact clip identity.** Each enqueued reply clip's own `queue_item_id` is identified by **exact**
   URI or name equality with exactly one candidate (§4.3 step 4) and recorded; deletion targets **only**
   those recorded ids. An ambiguous or unmatched clip stays unidentified and is never deleted.
3. **Resume by queue id; seek only when seekable.** Resume is `play_index(<captured queue_item_id>)`; `seek`
   runs only for seekable media and only after the resume is confirmed.
4. **Phase-aware fallback.** Never replay by URI after the queue resume has succeeded (or may have
   succeeded) — that would duplicate or disrupt playback. The fallback depends on the phase reached (§4.4).
5. **URI replay is the final safety path.** When queue ids or resume operations fail, log the failure and
   use the existing replay-by-URI behaviour, unchanged.

### 4.2 New MA queue helpers (`maconn.py`)

Thin wrappers returning MA's raw reply (callers check `error_code`), unit-tested with a fake socket:

- `queue_state(queue_id)` → `player_queues/get` result dict (`state`, `current_index`, `elapsed_time`,
  `current_item{queue_item_id, name, media_item{media_type, uri}, duration}`).
- `queue_items(queue_id, limit=50)` → `player_queues/items`.
- `play_index(queue_id, queue_item_id)`, `seek(queue_id, position)`, `delete_item(queue_id, queue_item_id)`.

`interaction` reaches MA through `ctx.ma_factory()` (as `music` does), opening one connection per turn and
closing it in the turn's `finally`.

### 4.3 The reply turn (`_say`) with queue mode

Queue mode is used when `settings.say_queue_resume` is true (default **true**; the kill switch — set false +
restart = exactly today's behaviour) **and** the capture succeeds.

1. **Capture (new, before step 4):** `queue_state`. Queue mode needs `current_item.queue_item_id`. Record
   `resume_id`, `resume_pos = elapsed_time`, `seekable = media_type in ("track",) and duration > 0`
   (radio/streams: not seekable). Capture failure, no current item, or a MA error → **legacy mode** for the
   whole turn, logged `SAY req=… queue capture unavailable (<why>); legacy replay`.
2. **Pause + volume raise:** unchanged.
3. **Play each clip with `enqueue: "play"`** (queue mode only; legacy passes no enqueue as today).
   `_play_clip_and_wait` gains an `enqueue` argument; start/finish polling is unchanged (the spike showed
   the clip ending in `idle`, which the existing finish rule already observes).
4. **Identify each clip's queue id by exact identity** right after its play call. The play call (HA REST
   `music_assistant.play_media`) returns no queue item or URI, so identity comes from `queue_items`:
   - **Primary — exact URI:** an item whose `media_item.uri` (or `uri`), after removing only MA's known
     wrapper prefix `builtin://radio/`, is **equal** to the clip's normalised URI. Equality, never
     containment or prefix matching.
   - **Secondary — exact name:** only if no item matched by URI, an item whose `name` is **equal** to the
     clip's TTS id (the URL's last path segment without its extension — the name MA gave the clip in §3).
   - **Exactly one candidate** across the rule that matched. Zero, or two or more (including an item that
     matches by URI and another by name) → record the clip as **unidentified**, log it, and never delete
     anything for that clip.
5. **Volume restore:** unchanged.
6. **Resume (replaces step 9 in queue mode)**, only if `was_playing` and not superseded:
   - `play_index(resume_id)`. Success = no `error_code` **and** a confirming `queue_state` read shows
     `current_item.queue_item_id == resume_id`. An exception or unconfirmed result is *ambiguous*: read
     `queue_state` once; if it shows `resume_id` current → treat as resumed; otherwise → URI fallback (§4.4).
   - If resumed and `seekable` and `resume_pos` ≥ 2s: `seek(resume_pos)`; failure → log only (the song plays
     from the start — never a URI replay).
7. **Delete the recorded clip ids** (after the resume, when they are no longer current). Failure → log only.
   If the turn did not resume (zone was idle, or the turn stopped/paused playback), the last clip is still
   the *current* item and MA will not delete it (§3) — the other recorded clips are deleted, the current one
   is left and logged (`clip left as current item: no resume`). That is no worse than today (today the
   clip *is* the whole queue); the next play replaces it, and `_resume` already refuses to replay a spent
   reply clip (`_is_reply_uri`).
8. Result metadata gains `"resume": "queue" | "legacy" | "fallback_uri" | "none"`, `"seeked"`,
   `"clips_deleted"`, `"clips_unidentified"`; `replayed` stays (true for queue or URI resume) for callers.

### 4.4 Phase-aware fallback (the `finally` path included)

| Phase reached when something fails | Action |
|---|---|
| capture failed | legacy mode for the whole turn (today's code path, unchanged) |
| clip enqueue raised / clip never started | queue is intact (enqueue-play never replaces) → still resume by `play_index`; delete any recorded clip |
| `play_index` raised or returned an error, and the confirming read does **not** show `resume_id` current | **URI replay** of `source_id` (final safety), logged `resume by queue failed (<why>); URI fallback` |
| `play_index` confirmed (or read shows `resume_id` current) | **no URI replay anywhere**, including `finally`; seek/delete failures are logged only |
| turn superseded | unchanged: the superseding turn owns the zone; no resume, no delete |
| aborted (exception) before step 6 in queue mode | `finally` resumes by `play_index` (phase-aware), falls back to URI replay only per the rows above; un-pause rules unchanged for legacy mode |

A single `resume_state` (`none` → `attempted` → `confirmed`) replaces the implicit use of
`queue_may_be_replaced`/`replay_done` in queue mode, so the `finally` block can decide from one value.

### 4.5 Voice "resume" (`_resume`)

Before replaying `_last_source` by URI: if the MA queue for the zone is `paused` with a current item, un-pause
in place (`media_player.media_play`) — the queue is intact after a voice "pause". Otherwise the current logic
is unchanged (replay remembered source, un-pause a paused HA state, replay loaded source, or "nothing to
resume"). A MA read failure → current logic.

### 4.6 What does not change

Duck/restore, volume ownership, mic/announce gating (AN-01, still disabled), barge-in generations, the
fresh-playback skip, the stopped-turn guard, music/radio initial play (`maconn.play`, replace).

## 5. Radio and live streams

Same path: the radio queue is `[station]`; the clip is inserted after it; resume is `play_index(<station
item>)`; `seekable` is false, so no seek. Listener-visible result equals today's (the station comes back),
with the clip removed from the queue afterwards.

## 6. Logging

- `SAY req=… queue capture: item=<id> pos=<s> seekable=<bool>` / `queue capture unavailable (<why>)`.
- `SAY req=… clip=<clip> queue_item=<id>` / `clip=<clip> queue_item UNIDENTIFIED (<n> matches)`.
- `SAY req=… resumed by queue item=<id> seek=<s|skipped> clips_deleted=<n>`.
- `SAY req=… resume by queue failed (<why>); URI fallback` / `seek failed (<why>)` / `delete failed (<why>)`.
- The existing final `reply_started=… replayed=…` line gains `resume=<mode>`.

## 7. Testing (TDD; `tests/test_interaction.py` + `tests/test_maconn.py`)

A `FakeQueue` models MA's queue as observed in §3 (enqueue-play inserts after current and stops it; clip end
→ idle on the clip; delete of the current item is a no-op; play_index/seek/delete by id). The fake HA's
`music_assistant.play_media` and the fake MA helpers act on the same `FakeQueue`.

Required cases (operator-stated), each asserting queue contents and calls, not only flags:

- **Multi-item queue:** 8-song queue, question mid-song 3 → afterwards queue == original 8, current == song
  3, no clip left, **no** URI replay, one `play_index`.
- **Seek restoration:** track at 47s → `seek(47)` after the confirmed resume; `resume_pos` < 2s → no seek.
- **Radio/live stream:** `[station]`, media_type radio → `play_index(station)`, **no** seek, clip deleted.
- **Clip deletion:** exactly the recorded clip id deleted. Exact identity: an item whose URI merely
  *contains* the clip URL (e.g. a longer URL, or the clip URL with a query suffix) is **not** a match; a
  wrapped `builtin://radio/<clip url>` **is**; name fallback matches only an identical name. Ambiguous
  cases stay unidentified and delete nothing: two URI matches; a URI match plus a different name match; two
  name matches; no match. Each is logged.
- **Multi-clip turn** (chime + message): both clip ids recorded and deleted; one resume.
- **Failure at each step:** capture fails → legacy (today's calls exactly); enqueue raises → still
  `play_index`; clip never starts → still resume; `play_index` error with confirming read ≠ resume_id →
  URI replay once; `play_index` raises but read shows resume_id current → **no** URI replay; seek fails →
  no URI replay, logged; delete fails → logged, result still ok; exception after `play_index` confirmed →
  `finally` does **not** replay by URI.
- **Unchanged guards:** superseded turn → no resume/delete; stopped turn → no resume, the current clip
  left in place and logged, any earlier clips deleted;
  fresh-playback skip unchanged; kill switch `say_queue_resume=false` → today's exact call sequence.
- **`_resume`:** paused MA queue → `media_play`, no URI replay; MA read fails → current logic.
- All 16 existing replay tests keep passing in legacy mode; queue-mode equivalents replace "replayed the URI
  once" with "resumed the queue item once". Mutation check on: the enqueue option, the confirming read, the
  seekable gate, the delete-only-recorded rule, and the `finally` no-replay-after-confirmed rule.

## 8. Deploy and verification (operator-gated, as MR-08)

Gate claim via its own small PR; backup with sha256; staged host tests (all host modules) on Python 3.5.2;
sha256-verified promote; operator restart; then live, with the operator present:

1. Play "Costea mix", ask "what time is it?" → same song resumes near its position; MA queue = 8 songs, no
   clip; next song follows (let it roll over once).
2. Play a radio favourite, ask a question → station returns; queue `[station]`, no clip.
3. "Pause", then "resume" → same song continues; queue intact.
Stop-and-rollback on any failure: restore `.bak/<ts>` or set `say_queue_resume=false` + restart (kill switch).

## 9. Bundled: MR-08e — log the query on a music miss

`MusicCapability.resolve` keeps `rid` and the searched type list in its result; `validate`, on not-found,
logs `req=… MISS query=<q> types=[…] alias=<key|None>` (no-local-tracks/not-curated keep their own lines).
Test: `assertLogs` sees the query on a miss and no `MISS` line on a hit. No sensitive data (the query is
what was spoken).

## 10. Open points to confirm during implementation

- `current_item.media_item.media_type` for a radio queue item is `"radio"` (expected; assert in the probe of
  the plan's first task, read-only).
- The exact form in which `queue_items` exposes the clip's URL (`media_item.uri` / `uri`, and whether it
  is wrapped as `builtin://radio/<url>`) — confirm read-only before coding the exact-URI rule; the spike
  showed the clip's *name* is its TTS id, which is the exact-name fallback. If MA's form differs from the
  single known wrapper, the plan records it and the rule stays equality after removing only that form.
