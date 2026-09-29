# MR-08c — The queue survives a spoken reply (and "resume") — Design

**Status:** v2 draft for operator review (2026-09-28). v1 direction approved by the operator; v2 folds in the
peer review of v1 (`dotfiles-61`: confirmation lag, late-landing enqueue, barge-in, pause→question→resume,
position-anchored identity, and six unestablished assumptions). Spike 3 (§3.2) settled the three open facts. Bundles `MR-08e` (§9).
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

### 3.2 Spike 3 (2026-09-28, operator-approved live playback experiment, throwaway)

Queue before: 8 songs, idle. Queue after: the same 8 songs, clip deleted, left paused.

1. **Enqueue on a PAUSED queue: works.** After HA `media_pause`, `enqueue: "play"` inserted the clip at
   current+1 and played it (`paused → playing`), then the queue went idle on the clip — same as a playing
   queue.
2. **Position: capture before the pause.** While playing, `elapsed_time` + (`now − elapsed_time_last_updated`)
   was accurate. After the pause MA moved `elapsed_time_last_updated` but **did not refresh `elapsed_time`**,
   so a post-pause read (raw or extrapolated) is wrong.
3. **`play_index` accepts `seek_position`:** `play_index(index=<id>, seek_position=18)` resumed at ~18 s in
   one call (no restart blip).
4. The clip's queue item stores the **exact URL that was played**, wrapped: the spike played the raw LAN URL
   and read back `builtin://radio/http://192.168.1.104:8123/api/tts_proxy/<id>.mp3`. The resolver plays
   the normalised internal URL, so exact equality is against the URL `_say` played.

### 3.3 Spike 4 (2026-09-28, operator-approved live experiment after live checks 3–4 failed, throwaway)

Queue state sampled every 250 ms from HA and MA while a short reply clip was inserted with `enqueue: "play"`.
Player restored afterwards (idle, volume 0.46, costa mix, no clips). Queue settings at the time: shuffle on,
repeat `all`; `flow_mode` was observed both false and true on the same day (MA switches it itself).

1. **Flip (playlist, both paused-settled and not):** ~1.3 s after the clip started, **both** HA and MA reported
   the interrupted song as current (HA even `playing`) for ~0.75 s, then the clip again. Waiting for MA to
   confirm the pause before enqueueing did not prevent it. Two consecutive "other item" readings plus the MA
   cross-check both read this flip as the clip's end — the live 18:32 early resume.
2. **True end of a clip in a playlist:** HA goes `idle` with the clip as the media id, then MA goes `idle` with
   the clip current. The song does **not** restart by itself.
3. **Paused station:** MA reported the queue `paused` for the whole (audible) clip, then ~1 s after the clip
   **restarted the station by itself** — live check 4's "resumed by itself".
4. **Deletes:** succeeded right after `play_index(T)` while the queue was still idle; returned success but
   **did nothing** for the current item and for the clip sitting next behind the playing station.
5. MA 2.9 exposes `index_in_buffer` in `player_queues/get`; its delete guard ignores items at or below it
   (reporting success). This explains every observation in 4 (the current item is always within the buffer;
   `play_index` resets the buffer to T). The spike did not log the value, so the implementation logs it at
   every cleanup step and never relies on it alone (§4.8).

## 4. Design

### 4.1 Invariants (operator-stated, binding)

1. **Capture before pause and enqueue.** The interrupted item's `queue_item_id`, its seekability and its
   duration are captured **before** the pause and before any reply clip is enqueued. (Position: §4.3-1.)
2. **Exact, position-anchored clip identity.** A reply clip's `queue_item_id` is recorded only when exactly
   one item sits at the expected position (§4.3-4) **and** matches exactly by URI or name. Deletion targets
   **only** recorded ids. Ambiguous or unmatched → unidentified, never deleted.
3. **Resume by queue id; seek only when seekable.** Resume is one `play_index(<captured id>,
   seek_position=<p>)` call (§3.2-3); `p` is the captured position only for seekable media within the seek
   gates (§4.3-7), else 0.
4. **Phase-aware fallback.** Never replay by URI after the queue resume has succeeded **or may have
   succeeded** (§4.4).
5. **URI replay is the final safety path**, used only when failure is positively known; always logged.

### 4.2 New MA queue helpers (`maconn.py`) and connections

Thin wrappers returning MA's raw reply (callers check `error_code`), unit-tested with a fake socket:
`queue_state(queue_id)` (`player_queues/get`), `queue_items(queue_id, offset, limit)`,
`play_index(queue_id, queue_item_id, seek_position=0)`,
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
   position, from this pre-pause read only (§3.2-2): if the queue is `playing` and
   `elapsed_time_last_updated` is present, `pos = elapsed_time + (now − elapsed_time_last_updated)`, capped at
   `duration`; otherwise `pos = elapsed_time`. Never re-read the position after the pause.
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
   - URI: `media_item.uri` (or `uri`) with only one of MA's two measured wrappers removed
     (`builtin://radio/` for TTS, `builtin://track/` for the announce chime — see `_is_reply_uri`) **equals** the clip's
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
   Seek gates for `seek_position`: seekable, `pos ≥ 2 s` and `pos ≤ duration − 5 s` (seeking to the end
   would skip the song); otherwise `seek_position=0`.
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

### 4.8 Amendment A1 — finish rule, buffer-aware cleanup, paused-at-start (operator-approved 2026-09-28)

Supersedes the finish-detection note in §4.3-3, the MA finish cross-check added after live check 2, the
deletion rule in §4.3-8, and §4.6 step 1–2 where they conflict. Queue mode only; the legacy path is unchanged.
Evidence: §3.3.

**Terms.** T = the interrupted (target) queue item, C = a recorded reply clip, both by `queue_item_id`. A
*read* = one `queue_state` (state, `current_item.queue_item_id`, `current_index`, `index_in_buffer`) plus the
item list around the positions involved.

**A1.1 Finish rule (queue mode).**
- HA `state` not `playing` (idle, paused, off, …) → the clip has ended, immediately (existing two-reading rule).
- HA `playing` with a **different, non-empty** media id → counts as the end only after it has persisted
  **≥ 1.5 s continuously** (`say_queue_other_item_ms`, default 1500, matching the other `say_*_ms` settings); any reading back on the clip resets it.
- The empty-media-id grace, the finish timeout and the turn deadline are unchanged.
- The MA cross-check (`clip_still_current`) is removed.

**A1.2 When a delete is permitted.** C may be deleted only when one read shows all of: C is in the item list;
C is not the current item; `index_in_buffer` is an integer consistent with the snapshot
(`0 ≤ index_in_buffer < items`, and `index_in_buffer ≥ current_index` when both are known); and C's index
**> `index_in_buffer`**. **Fail closed:** if `index_in_buffer` is missing, non-numeric, or inconsistent with
the item-list snapshot, do not delete — log the reason and keep C recorded for the next sweep.

**A1.3 Deletes are verified, never trusted.** After every delete call, whatever it returned, re-read the item
list. C counts as deleted only if it is absent; otherwise it stays recorded. A reply that says "error" while
the item is gone counts as deleted.

**A1.4 Resume path** (queue was playing at capture):
1. Clip end detected per A1.1.
2. `play_index(T, seek)` per §4.4 (this resets MA's buffer to T).
3. Immediately: read; delete each C that A1.2 permits; verify per A1.3.
4. **Retry trigger:** a C is still present after verification **and** the read has not yet shown MA applying
   the jump (current ≠ T, or `index_in_buffer` ≠ T's index). Re-read at **+1 s and +2 s** after `play_index`;
   delete whenever A1.2 permits; verify. No retries once every C is gone or MA shows current = T with the
   buffer at T. Retries stop if the turn is superseded.
5. **Buffer-reset retry (once):** if after +2 s a C is still present, lies **after** T, and is **within** the
   buffer (index ≤ `index_in_buffer`), it would play when T ends. Issue one more `play_index(T, seek =
   T's current position)` and immediately delete + verify. If C still survives: log WARNING `clip <id> will
   play after the current item`, keep it recorded, no further attempts. A C lying **before** T's position is
   left recorded for the next sweep.

**A1.5 Queue not playing at capture** (the reply to "pause", or a question while paused). After the clip ends,
one read decides:
- current item **is exactly T** and the queue is `playing` (MA restarted it, §3.3-3) → `media_pause`; C
  (inside the buffer) stays in the pending-resume record;
- current item **is C** (idle on the clip, §3.3-2) → no pause; C stays in the pending-resume record;
- anything else (newer user playback) → no pause, no `play_index`; only delete a C that A1.2 permits in that
  read, verified.
The re-pause is issued only by the turn that owns the zone (not superseded) and only on that exact-T check.

**A1.6 Resume from a pending record.** A voice "resume" with a pending record whose clips are still present
uses A1.4 steps 2–5 (`play_index(T, seek)` then delete), instead of un-pausing in place, so C is deleted in the
window MA allows. With no clips left, §4.6 is unchanged.

**A1.7 Next-turn sweep.** At the next turn's capture, every recorded clip that A1.2 permits in that read is
deleted and verified; the rest stay recorded.

**A1.8 Logging.** Every cleanup read logs `current_index`, `index_in_buffer` and each C's index, so live checks
confirm or refute the buffer rule.

**A1.9 Tests** (fake queue models MA: delete of an item ≤ `index_in_buffer` or of the current item returns
success and does nothing; `play_index` sets current = T and the buffer to T's index, optionally a few reads
late; once playback starts the buffer advances to the next item): the 0.75 s flip ends only at idle; ≥ 1.5 s
persistence ends; delete no-op not counted, retries while the buffer reset lags; loaded-as-next → exactly one
buffer-reset retry, with a still-failing variant (WARNING, recorded, no second attempt); paused-at-start
station restart → pause + record, resume via `play_index` deletes C; paused-at-start newer playback → no pause,
no `play_index`; paused-at-start idle on C → no pause, pending record; reply/reality mismatch both ways;
`index_in_buffer` missing / non-numeric / out of range / below `current_index` → no delete, reason logged,
clip kept.

**A2 — review amendment (operator-approved 2026-09-28).** Supersedes the conflicting parts of A1.2, A1.5 and A1.6.

- **A2.1 Two kinds of read.** The *permission* read (A1.2) is `queue_state` plus a small item window starting at
  T's index (limit = number of recorded clips + 5); it is what the first delete waits on. The *verification*
  read (A1.3) is the whole-queue read. The first permitted delete after `play_index` must be sent before any
  whole-queue read and before the confirmation poll.
- **A2.2 Re-pause watch (replaces A1.5's single read).** After the clip ends, watch for up to **3 s** at
  `say_poll_ms`. Pause (`media_pause`) only when the **exact original item T is current and `playing`**. Stop
  immediately, without pausing, when the turn is superseded or when any item other than T or a recorded clip
  becomes current. When the watch ends with nothing to pause, the A1.5 outcomes apply to the last read (idle on
  C → pending record; other item → only permitted deletes, verified).
- **A2.2a "A newer turn takes over"** (re-review) means any of: the reply generation advanced (a newer
  `_say`/announce), **or** the zone's queue record is no longer this turn's (a voice "resume" or new playback
  via `note_playback` cleared or replaced it). Checked every watch iteration and immediately before the pause.
  A current item whose URI is one of our reply clips (`is_reply_clip_uri`) but was not identified does not end
  the watch — it is still ours, and the station restart can follow it.
- **A2.3 Fresh position.** Whenever a pending resume is created or refreshed from a read in which T is the
  current item, its position is taken from that read (extrapolated per §4.3-1). On voice "resume", when T is
  current, the seek comes from the live read, never from the stored position.
- **A2.4 Tests added:** first delete precedes the buffer advance (SAY path and pending-resume path, with the
  buffer advancing right after the first post-`play_index` read); the watch pauses when the restart arrives
  N reads late, never pauses when another item becomes current, stops on supersede; resume after the user
  un-paused/re-paused T seeks from the live position; superseded check directly before the buffer-reset
  `play_index`; a predecessor clip positioned before the successor's current item is not deleted and stays
  recorded; the re-pause requires `playing`.

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
(also on a paused queue, §3.2-1); clip end → idle on the clip, or never idle; delete of the
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
- **Paused queue at enqueue** (§3.2-1): paused queue → clip inserted and played the same way.
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

- The announce chime's MA queue form: covered by exact equality against the URL `_say` actually played
  (resolved before `_say`); confirm when AN-01 is re-enabled (announcements are disabled today).
