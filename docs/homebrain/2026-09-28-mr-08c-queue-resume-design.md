# MR-08c — The queue survives a spoken reply (and "resume") — Design

**Status:** v2 draft for operator review (2026-09-28). v1 direction approved by the operator; v2 folds in the
peer review of v1 (`dotfiles-61`: confirmation lag, late-landing enqueue, barge-in, pause→question→resume,
position-anchored identity, and six unestablished assumptions). Three open facts need a short live spike
(§3.2) **before** implementation. Bundles `MR-08e` (§9).
**Backlog:** `MR-08c` (next), `MR-08e`. **Not in scope:** `MR-08b` (shuffle), `MR-08d` (agent knows playlist
names), `MR-08f` (STT/wake settings — separately gated).

## 1. Intent

A question asked while the ceiling plays a playlist, album or `.m3u` must not cost the rest of the queue.
After Nabu answers, the interrupted song continues **where it was**, and the queue carries on as before.
Radio keeps working exactly as today from the listener's point of view. "Pause" then "resume" by voice —
with or without a question in between — must also keep the queue.

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

## 3. What the live spikes established

### 3.1 Spikes 1–2 (2026-09-28, throwaway scripts, operator-approved)

On this player (ceiling Universal Player, **`flow_mode=true`** — ONBOARDING §13; MA `player_queues/*` over the
resolver's websocket), against a **playing** queue:

| Step | Observed |
|---|---|
| HA `music_assistant.play_media` with `enqueue: "play"` | clip inserted **after** the current item (idx+1), current song stopped, clip played; **queue kept all 8 songs** |
| clip (`.mp3`) ended | queue went **`idle` on the clip** — MA did **not** advance to the next song |
| `player_queues/delete_item` on the **current** item | silently did nothing (no error) |
| `player_queues/play_index(index=<queue_item_id>)` | interrupted song played, from 0 |
| `player_queues/seek(position=14)` | position restored |
| `delete_item(<clip queue_item_id>)` once not current | clip removed; queue back to the original 8 |
| queue item for a TTS clip (seen earlier the same day) | `name` = TTS id; `media_item.uri` = `builtin://radio/http://192.168.122.10:8123/api/tts_proxy/<id>.<ext>` |

### 3.2 Not established — spike 3 required before coding (operator-gated, ~40 s of sound)

1. **Enqueue on a PAUSED queue.** Production keeps `say_pause_before_reply`, so the enqueue hits a paused
   queue. Does `enqueue: "play"` still insert after current and play the clip?
2. **Position freshness.** MA throttles `elapsed_time` (a healthy stream showed a frozen position for 20 s —
   code comment ~1278). Is `elapsed_time` fresh right after a `media_pause`? Does the queue expose
   `elapsed_time_last_updated` to extrapolate from?
3. **`play_index` with `seek_position`.** If MA's `player_queues/play_index` accepts `seek_position`, one call
   replaces play-from-0-then-seek and removes the audible restart blip.

The plan's first task runs spike 3 and records the answers; §4 names the behaviour for each outcome.

## 4. Design

### 4.1 Invariants (operator-stated, binding)

1. **Capture before pause and enqueue.** The interrupted item's `queue_item_id`, its seekability and its
   duration are captured **before** the pause and before any reply clip is enqueued. (Position: §4.3-1.)
2. **Exact, position-anchored clip identity.** A reply clip's `queue_item_id` is recorded only when exactly
   one item sits at the expected position (§4.3-4) **and** matches exactly by URI or name. Deletion targets
   **only** recorded ids. Ambiguous or unmatched → unidentified, never deleted.
3. **Resume by queue id; seek only when seekable.** Resume is `play_index(<captured id>)` (with
   `seek_position` if spike 3 confirms it; otherwise `seek` after confirmation), only for seekable media.
4. **Phase-aware fallback.** Never replay by URI after the queue resume has succeeded **or may have
   succeeded** (§4.4).
5. **URI replay is the final safety path**, used only when failure is positively known; always logged.

### 4.2 New MA queue helpers (`maconn.py`) and connections

Thin wrappers returning MA's raw reply (callers check `error_code`), unit-tested with a fake socket:
`queue_state(queue_id)` (`player_queues/get`), `queue_items(queue_id, offset, limit)`,
`play_index(queue_id, queue_item_id, seek_position=None)`, `seek(queue_id, position)`,
`delete_item(queue_id, queue_item_id)`.

**One MA connection per phase, not per turn.** A reply can run up to `say_reply_timeout` with the socket idle,
and the raw client answers no heartbeat, so a turn-long connection could be dead by the resume. `interaction`
opens a fresh `ctx.ma_factory()` connection for (a) the capture and (b) the post-clip phase (identify, resume,
delete), closing each in its own `finally`. `_resume` does the same.

### 4.3 The reply turn (`_say`) in queue mode

Queue mode is used when `settings.say_queue_resume` is true (default **true**; kill switch — false + restart
= exactly today's behaviour), `ctx.ma_factory` and `settings.queue_id` exist, **and** the capture succeeds.

1. **Capture** (before the pause): `queue_state`. Needs `current_item.queue_item_id`. Record `resume_id`,
   `current_index`, `media_type`, `duration`, `seekable = media_type == "track" and duration > 0`, and the
   position:
   - if spike 3 shows `elapsed_time` is fresh after a pause: re-read `queue_state` **after** the pause and
     take `elapsed_time` from that read (same item required, else keep the first);
   - else, if `elapsed_time_last_updated` exists and the queue was playing: extrapolate
     `pos = elapsed_time + (now - last_updated)`, capped at `duration`;
   - else take `elapsed_time` as is (worst case: resume a little early).
   Also log `stale reply clips near current: N` (items within the read window whose URI is a reply clip) so
   leftovers are visible. Barge-in inheritance (§4.5) applies if the current item is a reply clip.
   Capture failure → **legacy mode** for the whole turn, logged `queue capture unavailable (<why>)`.
2. **Pause + volume raise:** unchanged.
3. **Play each clip with `enqueue: "play"`** (queue mode only). `_play_clip_and_wait` gains `enqueue`. Finish
   detection is unchanged; note two exits: an `.mp3` clip ends `idle` (spike), while a
   `builtin://radio/`-wrapped clip may never reach idle (code comment ~1658) and exit on budget still
   "playing" — the resume then stops it, which is correct after the full budget.
4. **Identify each clip (exact + position-anchored).** Read `queue_items(offset=<anchor>, limit=5)` where the
   anchor is the captured `current_index` for the first clip and the previous clip's index for later clips.
   The candidate is the item at **anchor + 1**, and it must match exactly:
   - URI: `media_item.uri` (or `uri`) with only the `builtin://radio/` prefix removed **equals** the clip's
     played (normalised) URI — for announce clips this is the already-resolved chime/message URL `_say`
     played, so equality holds without a name rule;
   - or, if the URI is absent, `name` **equals** the clip's TTS id.
   Anything else (no item there, item there but not an exact match) → unidentified, logged, not deleted.
   Anchoring by position makes earlier identical leftovers (HA's TTS cache reuses URLs; the chime URL never
   changes) irrelevant, and reading around the anchor works at any queue length.
5. **Enqueue that raised** (REST timeout — MA "regularly outruns" it and may still start the clip): before
   resuming, read the queue at the anchor. If the clip landed and is current → run the finish-wait for it;
   if it landed and is not current → record it for deletion; if absent → continue.
6. **Volume restore:** unchanged.
7. **Resume** (replaces step 9 in queue mode), only if `was_playing` and not superseded — per the decision
   table in §4.4. After a confirmed/unconfirmed resume, **settle check** once after one poll interval: if the
   current item is now a reply clip (a late-landing enqueue displaced the song), `play_index` again **once**.
   Seek (when not done via `seek_position`): only if seekable, `pos ≥ 2 s` and `pos ≤ duration − 5 s` (seeking
   to the end would skip the song).
8. **Delete recorded clip ids** that are not current. When the turn resumed, all are non-current. When it did
   not resume (zone was idle, turn stopped/paused playback), the last clip is current and cannot be deleted
   (§3.1): it stays, logged, and a **pending resume** is recorded (§4.6).
9. Result metadata gains `"resume": "queue" | "unconfirmed" | "legacy" | "fallback_uri" | "unknown" |
   "none"`, `"seeked"`, `"clips_deleted"`, `"clips_unidentified"`; `replayed` stays for callers (true for
   queue, unconfirmed or URI resume).

### 4.4 Resume decision table and phase-aware fallback

After `play_index`, poll `queue_state` for confirmation for up to **4 s** (`say_poll_ms` apart) until the
captured item is current — MA updates queue state asynchronously.

| `play_index` | bounded poll | outcome |
|---|---|---|
| any result | shows the captured item current | **confirmed** — seek if needed; no URI replay |
| no error | never shows it (other item, or reads failed) | **unconfirmed** — MA accepted it and may be late: **no URI replay**, logged `resume unconfirmed` |
| `error_code` or raised | reads succeeded and never show it | **failed** → URI replay of `source_id`, logged `resume by queue failed (<why>); URI fallback` |
| `error_code` | reads all failed | **failed** (MA refused) → URI fallback |
| raised | reads all failed | **unknown** — it may have landed: **no URI replay**, logged as an error |

For **unconfirmed** and **unknown** the turn also records a `pending_resume` (§4.6), so a later voice "resume"
takes the queue path when the zone is sitting on a reply clip, not the URI replay.

Phases:

| Phase reached when something fails | Action |
|---|---|
| capture failed | legacy mode for the whole turn (today's code, unchanged) |
| enqueue raised | §4.3-5, then resume per the table |
| clip never started | queue intact → resume per the table |
| after `play_index` was issued (any outcome) | the table decides; the `finally` path never re-decides |
| exception before `play_index` was issued | `finally` resumes per the table (fresh MA connection) |
| superseded | no resume by this turn; its target and recorded clips pass to the superseding turn (§4.5) |

One `resume_state` per turn (`none` → `attempted` → one of the outcomes) replaces the implicit use of
`queue_may_be_replaced`/`replay_done` in queue mode; the legacy path keeps them unchanged.

### 4.5 Barge-in (turn B supersedes turn A mid-reply)

A publishes its resume target (`resume_id`, position, `seekable`, `duration`) and its recorded clip ids in
the zone's reply marker (`self._replies[zone]`, under `_lock`), updating the clip list as it records them.
B's capture sees A's clip as the current item: B **inherits** A's target when its captured current item is
one of A's recorded clip ids (exact), or — if A recorded none — when its URI is a reply clip
(`_is_reply_uri`). A identifies its clips only in its post-clip phase, so a B that supersedes A mid-clip
usually finds none recorded: in that case B **records its captured current item itself as A's clip**. That id
is exact and sits at A's anchor + 1, so it satisfies the same exact + position rule (§4.3-4). B resumes A's
target and deletes A's clips (recorded by A or by B) with its own.

### 4.6 Pending resume and voice "resume" (`_resume`)

When a queue-mode turn does not resume but captured a real item — or its resume ended **unconfirmed** or
**unknown** (§4.4) — record per zone `pending_resume = {resume_id, pos, seekable, duration, clip_ids}`.

- A later turn whose captured current item is one of `pending_resume.clip_ids` **inherits** it (same rule as
  barge-in: carry the target, add that turn's own clip to `clip_ids`) rather than clearing it — so
  "pause → question → question → resume" still finds the song.
- It is **cleared** only when used, when a turn captures a real (non-reply) current item, or by
  `note_playback` (new media started).

`_resume`, with a fresh MA connection, **before** the current logic:
1. If the queue's current item is one of `pending_resume.clip_ids` → `play_index(resume_id)` (+ position per
   §4.3-7), delete the clips, clear it.
2. Else if the queue is `paused` with a current item that is **not** a reply clip → un-pause in place
   (`media_player.media_play`).
3. Else, or on any MA failure → the current logic unchanged.

### 4.7 What does not change

Duck/restore, volume ownership, mic/announce gating (AN-01, still disabled), barge-in generations, the
fresh-playback skip, the stopped-turn guard, music/radio initial play (`maconn.play`, replace), and the entire
legacy path.

## 5. Radio and live streams

Same path: the radio queue is `[station]`; the clip is inserted after it; resume is `play_index(<station
item>)`; not seekable, so no seek. Listener-visible result equals today's, with the clip removed afterwards.

## 6. Logging

- `SAY req=… queue capture: item=<id> idx=<n> pos=<s> seekable=<bool> stale_reply_clips=<n>` /
  `queue capture unavailable (<why>)` / `inherited resume target from req=<rid>`.
- `SAY req=… clip=<clip> queue_item=<id>` / `clip=<clip> queue_item UNIDENTIFIED (<why>)`.
- `SAY req=… resumed by queue item=<id> outcome=<confirmed|unconfirmed> seek=<s|skipped> clips_deleted=<n>`.
- `resume by queue failed (<why>); URI fallback` / `resume unknown (<why>); not replaying` /
  `settle: reply clip displaced item <id>; resumed again` / `pending resume recorded` / `seek failed` /
  `delete failed`.
- The final `reply_started=… replayed=…` line gains `resume=<outcome>`.

## 7. Testing (TDD; new `tests/test_queue_resume.py`, plus `tests/test_maconn.py`)

A `FakeQueue` models MA as observed in §3 and is configurable: enqueue-play inserts after current and plays it
(also on a paused queue — or not, per spike 3); clip end → idle on the clip, or never idle; delete of the
current item is a no-op; play_index/seek/delete by id; **confirmation lag** (N reads before the new current
item shows); **late landing** (a raised enqueue whose clip appears after K reads); failure injection per call.
The fake HA's `music_assistant.play_media` and the fake MA act on the same `FakeQueue`. Existing tests stay
untouched: their context has no `ma_factory`, so they run the legacy path.

Required cases, each asserting queue contents and calls, not only flags:

- **Multi-item queue:** 8 songs, question mid-song 3 → queue == original 8, current == song 3, no clip,
  **no** URI replay, one resume.
- **Long queue:** 60 items, current index 55 → clip identified at 56 and deleted.
- **Repeated identical clip URIs:** a stale leftover clip with the same URL earlier in the queue → the new
  clip is still identified by position; the leftover is untouched and counted in the log.
- **Seek restoration:** track at 47 s → resumed at 47 s (seek_position or seek); `pos < 2 s` → no seek;
  `pos > duration − 5 s` → no seek.
- **Radio/live stream:** `[station]`, media_type radio → resume station, **no** seek, clip deleted.
- **Clip deletion / identity:** only the anchored exact match is deleted; a containment-only URI at the
  anchor → unidentified; nothing at the anchor → unidentified; each logged.
- **Multi-clip turn** (chime + message): both identified by chained anchors and deleted; one resume.
- **Confirmation lag:** play_index ok, current shows after 3 reads → confirmed, no URI replay; lag beyond
  4 s → unconfirmed, **no** URI replay.
- **Failures:** capture fails → legacy (today's calls exactly); play_index error + reads show another item →
  one URI replay; play_index error + reads fail → one URI replay; play_index raises + reads fail → **no**
  replay (unknown); seek fails → no URI replay; delete fails → logged, result ok; exception after play_index
  issued → `finally` does not re-decide.
- **Late landing:** enqueue raises, clip lands current → finish-wait then resume; clip lands after the
  resume → settle check resumes once more and the clip is deleted.
- **Clip never reaches idle:** finish exits on budget → resume, clip deleted.
- **Paused queue at enqueue** (per spike 3 outcome).
- **Barge-in:** B supersedes A mid-clip → queue == original, song resumed once (by B), both turns' clips
  deleted; B supersedes A **before A's post-clip phase** (A recorded nothing) → B records A's clip from its
  own capture and deletes it.
- **Pause → question → resume:** the reply turn records a pending resume; `_resume` resumes the song and
  deletes the clip; **pause → two questions → resume** → the second turn inherits the pending resume, queue
  intact, both clips deleted; plain pause → resume un-pauses in place; a paused reply clip is never
  un-paused; an **unconfirmed/unknown** resume leaves a pending resume that `_resume` uses.
- **Guards and kill switch:** superseded A does not resume; stopped turn → pending resume; fresh-playback
  skip unchanged; `say_queue_resume=false` → today's exact call sequence.
- All existing interaction tests pass unchanged (legacy path). Mutation check on: the enqueue option, the
  bounded confirmation (URI replay on unconfirmed), the position anchor, the delete-only-recorded rule, the
  settle check, barge-in inheritance, the pending resume, and the seek gates.

## 8. Deploy and verification (operator-gated, as MR-08)

Gate claim via its own small PR; backup with sha256; staged host tests (all host modules) on Python 3.5.2;
sha256-verified promote; operator restart; then live, with the operator present:

1. Play "Costea mix", ask "what time is it?" → same song resumes near its position; MA queue = 8 songs, no
   clip; next song follows (let it roll over once).
2. Play a radio favourite, ask a question → station returns; queue `[station]`, no clip.
3. "Pause", then "resume" → same song continues; queue intact.
4. "Pause", ask a question, then "resume" → same song continues; queue intact, no clip.
Stop-and-rollback on any failure: restore `.bak/<ts>` or set `say_queue_resume=false` + restart (kill switch).

## 9. Bundled: MR-08e — log the query on a music miss

`MusicCapability.resolve` keeps `rid` and the requested media type in its result; `validate`, on not-found
(no match), logs `req=… MISS query=<q> media_type=<t> alias=<key|None>` (no-local-tracks and not-curated
keep their own lines). Test: `assertLogs` sees the query on a miss and no `MISS` line on a hit. No sensitive
data (the query is what was spoken).

## 10. Open points

- Spike 3 (§3.2) — answers recorded in the plan's first task and reflected in §4.3-1, §4.3-3, §4.3-7.
- The announce chime's MA queue form: covered by exact equality against the URL `_say` actually played
  (resolved before `_say`); confirm when AN-01 is re-enabled (announcements are disabled today).
