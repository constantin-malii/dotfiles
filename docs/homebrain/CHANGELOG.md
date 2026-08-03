# Homebrain Change Log

Operational/administrative changes to the homebrain setup. (Architecture and feature
design live in the per-topic docs; this log is for discrete operational changes.)

## 2026-08-02 — THE reason voice `volume up` / `stop` kept failing: `automation.voice_ceiling_speakers` (prefer-local sentence layer) bypassed every script fix. Rerouted through the resolver (HA-live)

> **Read this before touching ceiling volume/stop/resume again.** Under **`prefer_local`**, the Phase-2
> sentence-trigger automation gets **first refusal** on these phrasings — so it, **not** the exposed
> `script.ceiling_*`, is what actually handled them by voice. Fixing the scripts (earlier today) had
> **no effect on the operator's actual commands**. Snapshot: `/tmp/vcs_SNAPSHOT.json` on the host.

- **Decisive evidence** (local agent, via `/api/conversation/process`):
  `'volume up'` → `action_done "Turning it up."` · `'turn it up'` → handled · `'louder'` → handled ·
  `'volume down'` → handled · **`'increase the volume'` → `error "couldn't understand"`**. So the
  sentence layer swallowed the phrasings that failed, while the one that *worked* was the one it did
  **not** match (it fell through to the LLM → `script.ceiling_volume_up` → resolver). Exactly the
  operator's report: *"volume up did not work, increase volume seems to have worked."*
- **What its branches did** — the same defects already fixed in the scripts, one layer up:
  `stop` → **`media_player.media_stop`** (the call `ONBOARDING.md` forbids: wedges the Squeezelite
  child, holds MA's lock) · `volume up/down/set` → `volume_set` computed from
  `state_attr(…,'volume_level')`, i.e. **the duck floor mid-turn**, so the step came off 0.15 and the
  restore then wiped it (`DUCK 0.25 -> 0.15` → *"up"* ending LOWER) · `resume` →
  `media_player.media_play`, which cannot restart a cleared radio queue.
- **Rerouted (5 branches):** `stop` → **`media_pause`** (equivalent, no wedge; a resolver `pause` mode
  would have been pure indirection) · `resume` → resolver `resume` · `volume_up`/`volume_down` →
  resolver modes with the existing `step` · `vol_set` → resolver with the mode chosen from the
  branch's own `dir` variable, preserving up/down/absolute. **Untouched:** all 7 triggers, every
  `set_conversation_response`, and the `variables` blocks doing HA's spoken-number parsing — the
  transform asserts these are intact, plus "no `media_stop`" and "no direct `volume_set`" remain.
- **VERIFIED live** through the real prefer-local path: `'volume up'` → `VOLUME volume_up: -> 0.64`,
  `'volume down'` → `-> 0.54`, `'set the volume to 40 percent'` → `set_volume: -> 0.4`, ceiling
  `playing 0.4`. Previously these produced **no resolver line at all**.
- **Lesson for the record:** the exposed `script.*` surface is **not** the only path to the ceiling.
  `prefer_local` means the sentence automation wins for any phrasing it matches, so a fix applied only
  to the scripts is invisible to voice. Any future ceiling-control change must cover **both**.
- **Same round, resolver-side** (deployed, restart 17:57:50, host suite 225 OK): `_resume` now marks
  the turn via `note_playback` — it started playback but did not, so the reply clip **replaced the
  station resume had just started** (`RESUME replaying library://radio/2` → `SAY start` 1 s later →
  zone left idle on a TTS clip: the operator's *"blipped but hearing nothing"*). The blank-`cid`
  tolerance is now bounded by **`say_blank_cid_grace_ms` (4000)** — unbounded, it held the zone at
  reply volume for the whole 30 s `say_reply_timeout_ms`, with wake words bouncing off
  `DUCK skipped: reply active`. And `status` no longer reports the assistant's own clip as the user's
  music at `reply_volume` (*"Something is playing at 60% volume"* → *"that is my own reply playing"*,
  volume suppressed).
- **Agent live side effects, disclosed:** the branch verification set the ceiling to **0.40**; an
  earlier direct script test left it at 0.45.
- **Tests:** 322 local / 225 host.

## 2026-08-02 — Reply CUT-OFFS root-caused (empty `media_content_id`) · stop/resume/volume rerouted off the wedging + ducked paths (5 HA scripts, HA-live) · all VERIFIED live

> **First HA-live changes in this branch.** Five exposed scripts edited via the HA config API
> (`ceiling_stop`, `ceiling_pause`, `ceiling_resume`, `ceiling_volume_up`, `ceiling_volume_down`,
> `ceiling_set_volume`). **No new exposure** — same scripts, same names, so `assistant-capabilities.md`
> stays in lockstep. Snapshots for rollback: `/tmp/snap_ceiling_*.json` on the host.

- **Reply cut-offs / volume "bumps" on almost every command — ROOT CAUSE.** Found by the poll-exit
  logging added the same day (it did not exist before, which is why this hid for so long):
  `finish-poll exit after 0.5s: state=playing cid=` — **MA transiently reports an EMPTY
  `media_content_id` while the clip is still playing.** The exit test was
  `norm_uri not in (cid or "")`, always true against `""`, so `_say` decided the reply had ended after
  0.5–1.0 s, **restored the volume and replayed the source OVER the still-playing reply**. One defect,
  both symptoms: the cut-off (replay landing on the clip) and the mid-clip volume bump (the restore).
  A genuine ending looks different: `state=idle`, or a cid naming something else. Fix: an empty cid is
  **not** an ending while the player still says `playing`, and an ending needs **two consecutive**
  observations so a single flicker cannot trigger it. **VERIFIED live:** every exit is now
  `state=idle` after 2.0–3.0 s. The guarding test asserts the poll *kept waiting* through the blank
  cids — **0 sleeps against pre-fix code**, i.e. the cut-off reproduced deterministically.
- **`script.ceiling_stop` used `media_player.media_stop`** — the call `ONBOARDING.md` forbids on this
  player (wedges the Squeezelite child, holds MA's playback lock). Now `media_pause` (recorded as
  lock-free). Fits the transient `RADIO PLAY FAILED code=2` that stalled 11.3 s, though the wedge was
  **never caught live** (every MA player read `idle` when probed) — so this is a documented-dangerous
  call that matches the evidence, not a reproduced wedge.
- **`resume` could never have worked**, regardless of the assistant understanding it: `media_play`
  cannot resume a radio stream whose queue was cleared, and after a reply turn the zone holds a
  **spent TTS clip**, so it would have replayed *that*. New resolver `resume` mode replays the last
  **real** source (remembered from `note_playback` and `_say`'s capture; reply clips recognised by
  `tts_proxy` / `builtin://radio/http` and never remembered). Also: the first cut blind-called
  `media_play` on an idle player → **HTTP 500** → the turn died with a bare `OSError`, which the
  assistant surfaced as *"there is nothing playing"*. It now inspects the zone: un-pause if paused,
  replay a loaded real source, else an honest "nothing to resume" with **no service call**.
  **VERIFIED:** `RESUME … replaying library://radio/2`.
- **Volume commands computed their step from the DUCKED value.** The scripts read
  `state_attr(…,'volume_level')` directly, so mid-turn "volume up" was `0.15 + 0.10 = 0.25` instead of
  `0.34 + 0.10`, **and the next re-duck pulled it straight back down** — "up" ended up LOWER:
  `DUCK 0.34 -> 0.15` → `DUCK 0.25 -> 0.15` → `SAY restored -> 0.25`. New `volume_up`/`volume_down`/
  `set_volume` modes retarget the **baseline** the turn will restore to and leave the floor alone, so
  the step comes off the listening level, survives re-ducks, and lands when the turn ends. Unducked
  they write the player as before. Values rounded to 3dp (`0.44-0.10` was writing
  `0.33999999999999997`). **VERIFIED live:** `VOLUME volume_down: baseline 0.44 -> 0.34 (ducked;
  applies when the turn ends)` → `SAY restored -> 0.34` → the **next** turn ducked *from* 0.34.
- **Agent-caused prompt regression, found and reverted.** While fixing `media_stop` the stop
  description was broadened to add *"silence"* / *"turn the music off"* — phrasing that competes with
  quieting requests. `last_triggered` then showed the assistant calling **`ceiling_stop`/`ceiling_pause`
  during volume turns** (`ceiling_volume_down` had not fired in a day), which is why "volume up/down
  paused playback". Reverted to the original wording plus an explicit *"NEVER use for volume
  requests"* guard on both stop and pause. The volume path itself was proven sound by a direct call:
  HTTP 200 → `VOLUME volume_up: -> 0.45 (live)`.
- **Not diagnosable from here:** the resolver sees only the tool that was called, never the
  transcription. If tool mis-selection recurs, Assist **pipeline traces** are the next instrument.
- **Two Assist turns ~1 s apart** (different clip fingerprints, `e2192ea3` then `ceea0c3c`) explain
  the "multiple voices, one understanding one not" — two genuine replies, not one event fired twice.
  **Zero** resolver announces since the suppression landed, and no `_say` ever superseded. Satellite
  ruled out: single assistant slot, single wake word, **no speaker attached**. Upstream (wake
  retrigger / pipeline re-listen) — a separate item.
- **Deploys (gated, user-run restarts):** resolver backups `.bak/20260802-152908`, `-155724`,
  `-160934`. Host 3.5.2 compile OK; host suite **185 OK**. Tests **317 local**.
- **Agent live side effects, disclosed:** a diagnostic probe started playback (Radio Noroc Moldova),
  and a direct `volume_up` test left the ceiling at 0.45.

## 2026-08-02 — `volume down` REGRESSION found + fixed (mine) · aliases now match inside noisy STT strings · MA play failures log their reason. All VERIFIED live

- **REGRESSION introduced by Slice 4 (mine), reported by the operator: "volume down" became a no-op**
  on the satellite while still working on the plain HA assistant. The old `user_override` check was doing
  **two** jobs — the false positive that caused the ratchet **and** honouring a genuine human volume change
  mid-turn. Making `_say` the single writer removed both, so the `script.ceiling_volume_*` scripts (which
  write the player **directly**, never through the resolver) were silently undone:
  `DUCK 0.47 -> 0.15` → `SAY start baseline=0.47 prev=0.15` → `SAY restored -> 0.47`. It still worked on the
  HA assistant because there is no reply clip there, so the old check still saw the change and kept it.
- **Fix — discriminate instead of discard.** The resolver knows the only two volumes **it** wrote (the duck
  floor and `reply_volume`); anything else is a third party and is **kept**. Applied at both ends of a turn:
  at capture (a volume moved during the duck **becomes** the baseline) and at restore (a volume moved during
  the reply is left alone and the snapshot retired). Comparing against the duck floor **as well as**
  `reply_volume` stops a stale HA read — which returns the pre-reply value — from being mistaken for a human
  change. `duck_floor` is captured at step 2 because step 4 overwrites `snap["target"]` with `reply_volume`;
  re-reading the snapshot there compared 0.15 against 0.70 and mis-fired (caught by the new tests).
- **VERIFIED live (12:14–12:18):** `SAY … volume moved to 0.34 during the duck (not ours, last wrote 0.15);
  adopting it as the baseline` → then `RESTORE -> 0.34`, `RESTORE -> 0.34`,
  `SAY restored -> 0.34 (baseline=0.34 prev=0.15)`. **The operator's volume change sticks and the ratchet has
  not returned.**
- **Aliases only matched whole-string equality**, but the assistant relays the transcription verbatim, so the
  station argument arrives noisy and over-long: `target='Radio Norok N O R O C'` → `candidates=0`, despite
  containing both "Norok" **and** a spelled-out "N O R O C". `resolve_alias` now looks for an alias key
  **inside** the query, **longest key first**, and also against a **compacted** form so "N O R O C" collapses
  to "noroc". Keys under 4 chars are skipped (they would fire on ordinary words) and **`rock` is deliberately
  never aliased**. Verified live: `radio alias 'norok' -> 'Radio Noroc Moldova'` → `candidates=1`.
- **MA play failures now log MA's own reason.** A live failure read only `RADIO PLAY FAILED code=2`, which
  cannot distinguish a dead stream from lock contention. The call had stalled **11.3 s** before failing (the
  lock signature), and a direct probe afterwards played the same station successfully over **both** provider
  mappings (`{"result": null}`, no error) — so it was **transient, not a broken station**. Radio/music
  failures now log `error_code` + `details`/`error`/`message` (+ station and uri for radio).
- **"Wrong station" is STT, definitively — not the resolver.** Two attempts, logged:
  `target='rock' candidates=5 → 'Наше Радио'` (Whisper renders "noroc" as **"rock"**, a real **genre**
  synonym, so that was the correct answer to the input) then `target='Radio Noro' candidates=2 → 'Radio Noroc
  Moldova'`, **`RADIO CONFIRM … is playing`**. **Workaround: say "Radio Noro…" / the full station name.**
  Adding more alias spellings cannot fix a word transcribed as a *different real word*; a real fix is STT
  vocabulary or a sentence trigger.
- **Deploys (gated, user-run restarts):** backups `~/mass-resolver/.bak/20260802-114746/` (interaction,
  favorites, radio.json) and `.bak/20260802-120249/` (radio, music). Host 3.5.2 compile OK; host suite
  **163 OK**. **Deploy note: multi-file `scp` hangs on this host — copy one file at a time.**
- **Agent-caused live side effects, disclosed:** a diagnostic probe **started playback** (Radio Noroc Moldova)
  and an earlier sub-second duck→restore probe left the zone at the floor once (restored by hand). Both were
  the agent's doing, not defects.
- **Tests:** 295 local / 163 host.

## 2026-08-02 — ROOT CAUSE of "media command reports success but is silent": the spoken confirmation REPLACED the media it confirmed. Fixed + verified live

- **Symptom:** "play radio noroc" → the assistant says "playing Radio Noroc Moldova" → **no sound**.
- **Root cause (caught by the new `RADIO CONFIRM` check, not by ear):** `_say` delivers the reply with
  `play_media`, which **replaces** the stream — so the spoken confirmation overwrote the station it was
  confirming. Compounding it, `_say` captured its before-state **1.2 s after** the play was accepted, while
  the station was still starting, so `was_playing` was false, **no source was captured**, `replayed=False`,
  and nothing brought the station back. The zone ended `idle` holding the TTS clip:
  `RADIO CONFIRM … NOT confirmed after 8s: state=idle cid=builtin://radio/…/tts_proxy/EJRj….flac
  requested=library://radio/18`. **Station-independent, and unrelated to stream health** (`available=True`
  was truthful) — it would hit any media command whose reply was spoken.
- **Fix — plan decision (e)** ("a pure media command is confirmed by the ACTION, not by speech"): `_say`
  declines to play a reply clip when the **current turn** already started playback on that zone. Keyed to
  **turn identity, not a timer** — a question asked seconds after a media command is a new turn and still
  gets its answer. **Failed** commands still speak (nothing started → nothing to protect), so "I couldn't
  find a station" stays audible. Reversible via `say_skip_on_fresh_playback=false`.
- **`note_playback` deliberately never creates a turn.** A play from a **non-satellite** caller (phone,
  ChatGPT text) must not open a *phantom* turn — that would suppress that caller's announce for the whole
  turn window and skip a later satellite reply. The first implementation did create one and **the test suite
  caught it** as four unrelated dispatch tests losing their announce.
- **VERIFIED live (11:23):** `RADIO PLAY ACCEPTED 'Наше Радио' uri=library://radio/9` →
  `SAY … SKIPPED: this turn started library://radio/9` → `RESTORE … -> 0.47` →
  **`RADIO CONFIRM 'Наше Радио' is playing (cid=library://radio/9)`**. The station survived its own
  confirmation and the volume returned to baseline (operator: *"volume is decent now"*).
- **Separate, still open — STT, not the resolver.** A "wrong station" report (`Наше Радио` instead of Noroc)
  traced to Whisper transcribing **"noroc" as "rock"**: `radio mode=play target='rock' candidates=5`, and
  `rock` is a legitimate **genre synonym**, so the rock station returned was correct for the input received.
  **`rock` is deliberately NOT aliased** — that would hijack every genuine rock request. Added only
  non-colliding renderings (`narok`, `no rock`, `noroc moldova`, `norok moldova`, `radio noroc moldova`).
  Reliable workaround: say the **full** name, "play Radio Noroc Moldova". A real fix belongs upstream (STT
  vocabulary / a sentence trigger), not in alias whack-a-mole.
- **Verified false alarm, recorded so it is not re-investigated:** an aliased query cannot mis-route through
  the local fuzzy matcher — `favorites.by_name(rc, "noroc")` returns **0** local hits and
  `match_rank("Radio Noroc Moldova", "Nashe Radio")` is **None**.
- **Deploy (gated):** `interaction.py`, `core.py`, `config.py`, `config.json` (+2 tests); backup
  **`~/mass-resolver/.bak/20260802-110938/`**; host 3.5.2 compile OK, host suite **140 OK**; user-run
  restart. `radio.json` alias additions land on the **next** restart.
- **Tests:** 281 local / 140 host.

## 2026-08-02 — Slice 4 VERIFIED live (7 turns, no ratchet) · radio `RADIO PLAYING` was an unverified success claim → now confirmed · station aliases now reach the MA search

- **Slice 4 verified end-to-end, operator-eared + log-confirmed.** Seven consecutive real satellite turns
  (15:53–15:56) each ended `SAY … restored -> 0.47` with `replayed=True`, and the ceiling finished
  `playing vol=0.47 src=library://radio/2` — **the volume it started at**. `baseline=0.47` was captured
  correctly on every turn *even while `prev` was the ducked floor* (`prev=0.15`, `prev=0.04`) — substituting
  `prev` for the baseline **was** the crater. **Zero `user_override` lines, zero `DOUBLE-SPEAK` warnings**,
  `RESTORE … deferred: reply active` on every overlapping turn, and `ANNOUNCE suppressed` on a real news
  turn. No ratchet across six turns.
- **The mystery `0.04` is an EXTERNAL writer, not the resolver.** `DUCK … 0.04 -> 0.04` at 15:55:43 with no
  resolver `volume_set` behind it: something outside the resolver drops the ceiling that low mid-turn.
  Previously that value became the "baseline" and stuck; now the true baseline survives and the turn
  self-heals. **Open item** — identify the writer (MA announce/overlay revert is the prime suspect).
- **`RADIO PLAYING` was a success claim the resolver never checked** (operator: *"this did not work"* about a
  turn the log called success). It was logged the instant MA's `play` returned without an `error_code` — i.e.
  **"MA accepted the request"**, never "audio is playing". Renamed to **`RADIO PLAY ACCEPTED`**, and a
  timer reads the zone back **`radio_confirm_after_ms` (8000)** later and logs the truth: `RADIO CONFIRM …
  is playing`, or a **WARNING** naming `state`, the requested `uri` and the `cid` actually loaded. Runs off
  the caller's thread (no added latency on the synchronous tool call), never alters the returned result,
  `0` disables.
- **Station aliases never reached the MA/RadioBrowser search** — they only gated the local `radio.json`
  favorites match, so an alias could not help any station that lives in **MA's library** rather than in
  `radio.json`. Live evidence: MA returns **2 available hits for `noroc`** (`library://radio/18` +
  a `radiobrowser://` mapping, both `available=True`) and **0 for `norok`**, which is what Whisper actually
  transcribes — so the turn honestly reported "couldn't find a station". `favorites.resolve_alias()` is now
  shared and the **canonical** name is what gets searched; aliases added for `norok` / `radio norok` /
  `noroc` / `radio noroc` → `Radio Noroc Moldova`. **Note:** that station is deliberately *not* added to
  `radio.json` favorites (it is an MA library favorite — duplicating the id here would rot).
- **Still open (playback, not resolution):** `noroc` resolves and is `available=True`, MA accepts the play,
  and **no audio** — that is the known degraded-stream/stop-wedge family, unchanged by this work. The new
  `RADIO CONFIRM` warning is what will now catch it in the log instead of a false success.
- **Deploy (gated):** `radio.py`, `favorites.py`, `config.py`, `config.json`, `radio.json` (+2 test files);
  backup **`~/mass-resolver/.bak/20260802-105506/`**; host **3.5.2** `py_compile` OK, host suite **134 OK**;
  user-run restart. **Deploy note:** multi-file `scp` hangs on this host — copy **one file at a time**.
- **Known latent (NOT fixed, deliberately):** `_restore` compares the live volume against the value it last
  wrote; on a **stale HA read** it instead sees the baseline, calls it `user_override`, and pops the snapshot
  → zone left at the floor **with no dead-man**. Only reproducible sub-second (an agent probe did it, and
  cleaned up after itself); real turns are seconds apart. Fix would be to treat "already at baseline" as
  *already restored* rather than as a human override.
- **Tests:** 275 local / 134 host.

## 2026-08-01 — DOUBLE-SPEAK root-caused: a satellite turn had TWO speech owners; resolver announce now stands down during a turn (+ `_say` call attribution, `play_media` timeout 5s→20s)

- **Symptom (operator, right after the Slice-4 deploy):** every reply heard **twice**, the two voices
  overlapping and "ducking one another".
- **Root cause — a Slice 2+3 collision, NOT a Slice-4 regression.** One utterance had two independent
  speech owners on the *same* ceiling zone: (1) the satellite's LLM calls an exposed tool, the resolver
  returns `spoken_text` **and** `chat_text`, and `core.dispatch` speaks `spoken_text` via `tts.speak` (the
  F1-R sole-TTS-owner rule); (2) the LLM then relays `chat_text` verbatim, Piper renders it, and the Slice-3
  automation routes that clip to the same ceiling through `_say`. Before Slice 3 the pipeline reply was
  **inaudible**, so only voice (1) was heard — Slice 3 made the second one audible. Live evidence at 13:09:
  `ANNOUNCE via tts.speak: I couldn't find a station for norok.` one second before the `DUCK` of the very
  turn that also spoke it.
- **Fix (operator-chosen, resolver-only, no HA edits):** `core.dispatch` **holds back its own announce while
  a satellite turn is in flight** on the ceiling zone — the pipeline owns the voice for that turn. "In
  flight" = a reply clip playing, **or** a duck snapshot held, **or** a duck *requested* within
  `interaction_turn_window_ms` (30 s). The third condition is load-bearing: the live turn ducked **nothing**
  (zone was idle), so a snapshot-only test would have missed it and announced anyway. Phone and
  ChatGPT-text callers never duck → unaffected, they keep their announce. Reversible via
  `suppress_announce_during_interaction=false` (config only, no code revert).
- **Second, independent defect fixed in the same trace:** `_say` inherited `call_service_rest`'s **5 s**
  default, and MA's `play_media` routinely outruns it → the turn **aborted** (`capability=interaction error:
  timeout`) while the clip still started server-side, so the reply was audible but **unsequenced** and the
  source was never replayed (also the 09:52 `replay failed (timeout)`). Reply + replay `play_media` now use
  **`say_call_timeout_ms` (20 s)**; `volume_set` keeps the 5 s default.
- **Visibility added** (the gaps that made this turn unreadable): a `SAY start` line with a **sha1[:8] clip
  fingerprint** (never the `tts_proxy` URL); every `_say` service call timed and attributed on failure
  (`music_assistant.play_media failed after 5.0s`) instead of a bare `error: timeout`; a **`DOUBLE-SPEAK`**
  warning when a reply clip lands within `say_double_speak_window_ms` (8 s) of the resolver's own announce;
  a **`TURN start`** line, and no-op ducks now log **why** (`no-op (not_playing)`) — previously a turn over
  an idle zone logged nothing at all, which is why the operator's wake could not be located.
- **New tunables:** `say_call_timeout_ms` (20000), `say_double_speak_window_ms` (8000),
  `suppress_announce_during_interaction` (true), `interaction_turn_window_ms` (30000).
- **Deploy (gated):** `interaction.py`, `core.py`, `speaker.py`, `config.py`, `config.json` (+ 4 test files)
  to `~/mass-resolver/`; backup **`~/mass-resolver/.bak/20260801-151634/`**; host **Python 3.5.2**
  `py_compile` OK, host suite **109 OK**; user-run `sudo systemctl restart mass-resolver`.
  Note: multi-file `scp` hung — copy files **one at a time** with individual `timeout`s.
- **Tests:** 17 new across `test_interaction.py` / `test_core.py` / `test_speaker.py` / `test_config.py`;
  suite **267 OK** locally (was 251).

## 2026-08-01 — S1b-2 Slice 4: reply-turn duck ownership fixed in the resolver (`_say` is sole restore owner); NO HA automation edit needed

- **Fixes the Slice-3 volume ratchet/crater** (the `RESTORE … user_override cur=0.7 (kept)` bug). Root
  cause, traced in code and reproduced offline: S1a's `idle→restore` fires **while `_say` is still polling
  the reply clip**, reads `_say`'s elevated reply volume, misreads it as a human change (`user_override`)
  and **discards the duck snapshot**; `_say`'s restore step then finds no snapshot and falls back to
  `prev_volume` — which is the **already-ducked floor** — so the ceiling **craters** (0.15/0.04). With no
  surviving baseline the next turn captures the inflated reply volume instead, so it also **ratchets**
  (0.3 → 0.7 → …). One defect, both symptoms.
- **Deterministic repro before any fix** (unit-level, no live system): duck 0.32→0.15 → `_say` sets 0.70 →
  interleaved `restore` returns `user_override`, snapshot becomes `None` → `_say` writes **0.15** instead of
  the 0.32 baseline.
- **Fix — decision (b), implemented entirely resolver-side** (`interaction.py`): the reply turn is owned
  end-to-end by `_say`. It publishes a per-zone reply marker and **resolves its restore baseline at its own
  capture step** (so a mid-reply snapshot discard can't strip it), retires the duck snapshot + dead-man
  after restoring, and always releases the marker (gen-guarded, so a barge-in keeps ownership). `_restore`
  **defers** while a reply is in flight — keeping the baseline instead of claiming `user_override` — and
  re-arms the dead-man since it declined to clear the snapshot. `_duck` also defers during a reply (plan
  decision (a): the clip *replaced* the music, so there is nothing to duck under).
- **⚠ Plan deviation — the S1a automation was NOT edited, and the grace-G change is no longer needed.**
  Slice 4 was planned as an **HA-live** edit to `automation.s1a_satellite_ceiling_duck_restore`
  (`id 1784146586`), repurposing `idle→restore` into a ~2–3 s grace-G backstop. Making the resolver the
  single writer achieves decision (b) with **no HA-live gate at all**: with no reply in flight
  `idle→restore` behaves exactly as before, so the "URI never arrives" case is covered **with no grace-G
  delay**. The S1a automation and the reply automation `S1b-2 - Satellite Reply on Ceiling`
  (`id 1784200731`) are both **untouched**. No firmware.
- **Hardening from code review** (two further strands, both reproduced then fixed): `_say` retires **only**
  the snapshot its baseline came from (ts-matched) — otherwise a wake landing between its restore write and
  its pop had its fresh snapshot + dead-man torn down, stranding the zone at the floor with no backstop;
  and a raise after the reply-volume write (e.g. MA `play_media` 500) now restores the baseline from a
  `finally` and keeps `snap["target"]` in step with what was actually written, so a later `_restore` can't
  claim `user_override` on the abandoned reply volume. The reply marker carries `ts`/`rid` and is treated as
  orphaned past the whole say budget, so a crashed/hung `_say` can't deafen duck/restore for a zone forever.
- **`say_owns_restore` remains a true rollback lever:** setting it `false` disables the whole ownership
  model — duck/restore behave exactly as pre-Slice-4 — so reverting decision (b) needs no code revert.
- **Tests:** 14 new (`DuckOwnershipSlice4Test`), suite **251 OK** (was 237). The three black-box ones were
  confirmed to **fail against pre-fix code** for behavioural reasons: `user_override != reply_active`, the
  next turn's snapshot destroyed, and a two-turn sequence ratcheting.
- **Not fixed here (separate, unconfirmed):** the *long-reply cut* is **not** explained by this defect — a
  re-duck lands before `_say` sets the reply volume, so it can't quiet the clip. Most likely a finish-poll
  false-negative (state/`media_content_id` flicker → `_say` restores + replays mid-sentence). The occasional
  `interaction … timed out` is the HA `rest_command` timeout on a blocking long `_say`, absorbed by
  `continue_on_error: true`. Both belong to Slice 5 observation. The poll loops also bound themselves by
  accumulated sleep rather than wall clock (pre-existing Slice-1 behaviour, not introduced here).
- **Live gate:** resolver deploy only (`runbooks/resolver-deploy.md`), restart **user-run**. Rollback:
  `cp ~/mass-resolver/.bak/<ts>/* ~/mass-resolver/ && sudo systemctl restart mass-resolver`.
- **Note:** the running resolver still holds `reply_volume=0.70`; the repo's `0.60` takes effect on this
  restart. That is a volume-level change only — it was never the ratchet.
- **Next: Slice 5** — E2E sign-off (audible reply both sources, convergence to baseline, source replay,
  never-started guard + chirp, latency, barge-in, no regressions).

## 2026-07-20 — S1b-2 Slice 3: satellite reply routed to the ceiling via HA automation (NO firmware); E2E works; volume-ratchet bug found → Slice 4

- **Milestone: "Okay Nabu, &lt;question&gt;" → spoken answer on the ceiling works end-to-end** — satellite →
  ChatGPT → Piper → `esphome.tts_uri` event → HA automation → resolver `_say` (`play_media`) → ceiling, with
  the source replayed after. **No firmware flash** (see Slice 0 finding).
- **Slice 0 (read-only) finding that de-risked Slice 3:** the reSpeaker's current ESPHome YAML (captured;
  rollback image lives in the ESPHome dashboard) **already emits the reply URI** — `voice_assistant.on_tts_end`
  runs `send_tts_uri_event` → HA event **`esphome.tts_uri {uri}`**. So the URI hand-off needs **no firmware
  edit**; the only thing firmware would add is suppressing the satellite's *local* TTS playback, which is moot
  while the satellite has no attached speaker (reply is ceiling-only). Brick-risk OTA **avoided**.
- **Installed (HA config API, HTTP 200):** automation **`S1b-2 - Satellite Reply on Ceiling`**
  (`id 1784200731`, mode `queued`/max 3): trigger `event: esphome.tts_uri` → action
  `rest_command.resolver_command {intent: interaction, params: {mode: say, uri: "{{ trigger.event.data.uri }}"}}`
  with `continue_on_error: true` (a long blocking reply must not fail the automation). Modeled on the S1a
  automation's `rest_command` pattern.
- **Validated live (operator):** "Okay Nabu, what time is it?" → answered on the ceiling. (First attempt
  "couldn't understand" when speaking immediately after the wake word — inherent wake→listen window on the
  ESPHome satellite, not a defect; pause ~0.5 s after "Okay Nabu", or tune wake sensitivity / finished-speaking
  later.)
- **KNOWN BUG (diagnosed) — ceiling volume RATCHETS up over conversations.** Resolver log:
  `RESTORE … user_override cur=0.7 (kept)`. `_say` raises the ceiling to the reply volume for the clip, then
  **S1a's `idle→restore` fires, sees a volume it didn't write, treats it as a user override, and keeps it** —
  the baseline is never restored and the next duck captures the inflated value (0.3 → 0.7 → …). This is the
  **S1a-vs-`_say` duck-ownership conflict** that **decision (b)/Slice 4** exists to fix (make `_say` the sole
  reply-turn restore owner; stop S1a's `idle→restore` fighting it). Today's real E2E **proves Slice 4 is
  required** (earlier flagged "may be unnecessary"). Minor contributors: the running resolver still holds
  `reply_volume=0.70` (the 0.60 config loads on next restart — a restart alone does NOT fix the ratchet, the
  conflict does); S1a's `user_override` guard misreads `_say`'s volume change as a human.
- **Interim state (operator choice): reply automation LEFT ON**, accepting the volume creep until Slice 4
  (turn the ceiling down manually as needed). Satellite stays on ChatGPT. Commands audible via ceiling; open
  Q&A audible on the ceiling too (with the ratchet caveat).
- **Live gate:** HA-live claimed for the automation install; **released → FREE**. No firmware/host change; the
  Slice-1 `_say` deploy is unchanged.
- **Rollback:** disable or delete automation `S1b-2 - Satellite Reply on Ceiling` (`id 1784200731`) in the HA
  UI / config API. Nothing else to undo (no firmware touched).
- **Next: Slice 4** — resolve the duck-ownership conflict (S1a `idle→restore` → grace-G / `_say`-owns-restore
  per decision (b)), then Slice 5 E2E sign-off. Plan: `plans/2026-07-16-s1b-2-satellite-full-assistant.md`.

## 2026-07-20 — S1b-2 Slice 2: "Living Room ChatGPT" pipeline created + assigned to the satellite; prefer-local determinism validated live

- **What:** shipped **Slice 2** of the S1b-2 plan — the reSpeaker satellite is now a **full LLM assistant**.
  Created a new HA Assist pipeline **"Living Room ChatGPT"** (`id 01kxygpr39jas5hgsf28cph108`) =
  `stt.faster_whisper` + **`conversation.openai_conversation`** (gpt-4o-mini) + **`tts.piper`**
  (`en_US-amy-low`), **`prefer_local_intents=true`** — modelled exactly on the working "Living Room Voice"
  pipeline but with the LLM agent. Assigned it to the satellite's primary slot
  (`select.respeaker_living_room_assistant`: "Living Room Voice" → **"Living Room ChatGPT"**).
- **Determinism validated live (operator-eared + log-confirmed) — the NL-01 check.** "Okay Nabu, play
  Ramstein" → the LLM agent (prefer-local) fired the exposed **`script.play_music`** tool, resolver matched
  `query='Ramstein'`→`Rammstein` (`decision=ACCEPTED`, `PLAYING …/artist/Rammstein`), ceiling switched to
  Rammstein. Command handled as a **deterministic tool-call, not paraphrased/dropped**. S1a duck/restore
  fired around the satellite turn as expected.
- **No new exposure:** creating/assigning a pipeline changes no entity/tool exposure; `expose_new_entities`
  stays off; the satellite's OpenAI agent shares the already-exposed tool set (no `assistant-capabilities.md`
  change needed — tool-set lockstep already holds).
- **Deferred to Slice 3 (firmware):** the satellite has **no speaker** (audio via its 3.5 mm/JST jack, none
  attached), so **open-Q&A spoken replies are currently inaudible** (the reply plays on the satellite, not
  the ceiling — that redirect is Slice 3). Commands are unaffected (their result plays on the ceiling).
  The audible-Q&A + Piper check is therefore deferred to Slice 3/E2E.
- **Decision — kept on ChatGPT (operator).** The satellite stays on the LLM pipeline (it's the long-term
  target and keeps commands working). Interim downsides accepted: inaudible open-Q&A until Slice 3, ~10 s
  command latency (STT→LLM→tool→play), small residual risk of an odd phrasing being LLM-paraphrased into a
  silent no-op, no audible failure feedback until Slice 3's local error cue, negligible gpt-4o-mini cost.
- **Live gate:** HA-live/exposure claimed for the assignment; **released → FREE**. No resolver/host change
  (Slice 1 `_say` remains deployed + dormant until Slice 3 wires `on_tts_end` → `say`).
- **Rollback:** set `select.respeaker_living_room_assistant` back to **"Living Room Voice"** (instant, local
  agent); optionally delete the "Living Room ChatGPT" pipeline. No other undo.
- **Next:** **Slice 3** — reSpeaker firmware redirect (`on_tts_end` → resolver `say`, suppress local TTS,
  local working/error cue) via OTA reflash (highest-risk, gated, last), preceded by Slice 0 (capture current
  YAML). Then Slice 5 E2E makes "Okay Nabu, <question>" audible on the ceiling. Plan:
  `plans/2026-07-16-s1b-2-satellite-full-assistant.md`.

## 2026-07-19 — S1b-2 Slice 1 deployed: resolver `_say` reworked to the `play_media` route; convergence spike PASSED live

- **What:** deployed **Slice 1** of the S1b-2 plan (`plans/2026-07-16-s1b-2-satellite-full-assistant.md`) —
  the resolver `interaction._say` capability reworked from the (silent) `music_assistant.play_announcement`
  overlay to the audible **`play_media`** route: capture source (state/`media_content_id`/volume) → per-zone
  barge-in gen-id → normalise reply URI to the internal base → set `reply_volume` → `play_media` → poll for
  START then FINISH (injected sleeper) → reply-started guard (`reply_started`/`likely_silent`) → restore the
  pre-duck baseline (`say_owns_restore`) → replay the captured source. New config tunables (`reply_volume`,
  `say_start_timeout_ms` 5000, `say_reply_timeout_ms` 30000, `say_poll_ms` 500, `say_internal_base`, 
  `say_owns_restore` true); `say_announce_timeout_ms` retired. Merged to `main` in PR #30 (237 unit tests).
- **Deploy (gated):** files `interaction.py`, `config.py`, `config.json` copied to `~/mass-resolver/`
  (backup `~/mass-resolver/.bak/20260719-154524/`); host **Python 3.5.2** `py_compile` + full suite **OK**;
  user-run `sudo systemctl restart mass-resolver`; post-restart healthy (`/command` bound, 200/401, fresh
  `SERVICE:` bind + `connected; subscribed`, no tracebacks).
- **Convergence spike — PASSED (operator-eared, live).** Over `/command`: `duck → say(test URI) → restore`
  with radio at baseline 0.30. Results:

  | Reply length | `say` block | Audible? | Volume convergence |
  |---|---|---|---|
  | short (~2 s clip) | 2.4 s | (state-confirmed) | duck 0.30→0.15 → **back to 0.30**, radio replayed |
  | long (counts 1→5) | 13.2 s | **YES — all five, not cut off, single reply** | duck→0.15 → **back to 0.30**, radio replayed |

  The block scaling **2.4 s → 13.2 s** with clip length confirms the poll waits for the *actual* clip end
  (not a fixed timeout); the operator heard the full reply (louder at `reply_volume` 0.70 during the test);
  the ceiling **converged to the pre-duck baseline** with radio re-played, and a follow-up `restore` was a
  clean no-op. **Decision (b) `say_owns_restore=true` is confirmed live** — `_say` owns the restore and lands
  at baseline with no strand. The URI was fed external-base and correctly normalised to the internal base.
- **`reply_volume` set to 0.60** (0.40 was too quiet; 0.70 tested well; 0.60 chosen). Applied on-host (takes
  effect on the resolver's next restart — inconsequential now since `_say` is **dormant**: nothing in
  production invokes it until the Slice-3 firmware redirect) and in the repo `config.json` (this change).
- **State:** `_say` is deployed but **dormant** (no caller yet). Live gate **released → FREE**. Operator's
  ceiling left playing radio at 0.30.
- **Rollback:** `cp ~/mass-resolver/.bak/20260719-154524/* ~/mass-resolver/ && sudo systemctl restart
  mass-resolver` (restores the pre-Slice-1 `_say`/config).
- **Next (S1b-2):** Slice 2 (new "Living Room ChatGPT" pipeline, prefer-local + Piper) → Slice 3 (firmware
  redirect, OTA — last) → Slice 4 (S1a `idle→restore`→grace-G — **may be unnecessary**: the spike showed the
  ceiling converges cleanly with S1a's plain `idle→restore` as a no-op after `_say`'s own restore) → Slice 5
  E2E. The announce/overlay-path silence remains a separate reliability item.

## 2026-07-17 — S1b announce silence ROOT-ISOLATED: it's the announce/OVERLAY path, not the ceiling — plain `play_media` of the same TTS clip is audible; source-independent; survives all restarts

> **Headline:** the ceiling speaker, MA transcode, and tts_proxy MP3 all work — a plain
> `media_player.play_media` of the exact TTS clip is **audible**. Only the **announce/overlay** mechanism
> (`music_assistant.play_announcement` **and** `tts.speak`) is **silent**. So S1b-2 is **not hard-blocked**:
> a working non-overlay route exists (play_media + capture/replay). Details below.

- **What:** live diagnostic (operator listening) targeting the previously-unexplained **source-independent**
  announce silence (the 07-16 `531187df` radio case). **Both open questions are now answered, and the
  prior "intermittent SMB/local stall" framing is superseded.**
- **(1) Source-independent — CONFIRMED live.** `music_assistant.play_announcement` (plain `tts_proxy` URL,
  internal base `192.168.122.10`, verified **200 `audio/mpeg`** each trial) was **silent over an
  audibly-healthy radio source AND audibly-healthy local music** — reproducing the 07-16 radio case that
  the SMB theory could not explain. Radio is **not** safe.
- **(2) NOT a transient degradation — it is persistent & deterministic.** The silence **survived every
  intervention** (each an operator-approved live action; block stayed ~13 s throughout vs the ~7 s healthy
  signature):

  | Trial | Source | State | Block | Announce audible? (operator) |
  |---|---|---|---|---|
  | A1 | radio (healthy) | baseline (broken SMB provider looping) | 13.4 s | **No** (radio paused, no speech) |
  | A3 | radio (healthy) | baseline | 13.3 s | **No** |
  | B1 | local FLAC (healthy) | baseline | 12.9 s | **No** |
  | C1 | radio (healthy) | after **disabling** broken SMB provider | 13.3 s | **No** |
  | C2/C3 | radio (healthy) | after **full MA add-on restart** | 13.3 s | **No** |
  | D1 | radio (healthy) | after **Squeezelite service restart** | 13.3 s | **No** |
  | E1 | radio (healthy) | **pre-announce chime OFF** (`use_pre_announce=false`) | 14.4 s | **No** |
  | G1 | (ceiling) | **`tts.speak`** via `script.ceiling_announce` (announce/overlay path) | 11.6 s | **No** |
  | **G2** | (ceiling) | **plain `media_player.play_media`** of the *same* TTS clip (no overlay) | **0.1 s** | **YES ✅** |

  (A2 void — TTS clip expired 404→500. F1/F3 were log-trace trials, also silent, ~13–17 s.)
- **Root isolation (G1/G2 — the decisive pair):** the **identical** tts_proxy MP3 that is **silent** through
  `play_announcement` and `tts.speak` is **audible** through plain `media_player.play_media`. `play_media`
  returned **instantly (0.1 s, non-blocking)** and played the clip as a normal track; the announce/overlay
  calls **block ~11–13 s and produce no audio**. So the ceiling output, the FLAC transcode, and the MP3
  fetch/decode are all **fine** — the fault is **specific to the announcement/overlay mechanism** (pause the
  current stream → play the announcement → resume) on this Universal→Squeezelite player. `tts.speak` is
  silent because on an ANNOUNCE-capable MA player it routes to the same overlay path.
- **Ruled out** (each tested, not assumed): source type · the broken SMB provider loop · MA process state ·
  Squeezelite client state · pre-announce chime · muted volume (`announce_volume=85%`) · URL form/reach
  (200 `audio/mpeg` every trial). Normal radio/local playback is **audible through the identical
  MA→Squeezelite path** — only `play_announcement` is silent.
- **The SMB provider loop was a coincidental correlate, now cleaned up.** MA had a **second, mis-pathed**
  `filesystem_smb` provider instance **`yYrXcamj`** (`host=192.168.122.1`, `share=Music`, empty subfolder)
  failing every ~2 min with **`mount error(2): No such file or directory`** on MainThread for 2+ hours —
  distinct from the working library provider `kd66vco4` (`host=192.168.1.83`, `share=media`,
  `subfolder=music`, mounts fine, plays local music). It never mounted and contributed nothing to playback;
  **it was disabled** (see live changes). Disabling it stopped the log-flood but **did not** restore audio.
- **MA logs the announce as accepted with NO error** at INFO (`players: Playback announcement to player
  Ceiling Speakers …`) and nothing further — a fully silent failure. **Deep tracing is blocked by the
  access model:** the HA add-on `/logs` proxy surfaces **INFO only** (0 SlimProto `strm`/`STM` lines even at
  DEBUG/VERBOSE — verified), and there is **no VM/Docker shell** to read the MA container's stdout. Host
  Squeezelite runs default logging (`-o hw:1,0 -s 192.168.122.10 -C 5`, no debug flags) so it shows no
  `strm` detail either. **To trace the announce stream we need direct MA container log access** (or
  squeezelite debug flags + restart) — a follow-up.
- **Ruled out** (each tested, not assumed): source type · the broken SMB provider loop · MA process state ·
  Squeezelite client state · pre-announce chime · muted volume (`announce_volume=85%`) · URL form/reach
  (200 `audio/mpeg` every trial) · **TTS clip fetch/decode/transcode and ceiling output** (G2 audible).
- **Verdict:** the ceiling silence is a **failure of MA 2.9.3's announcement/OVERLAY path specifically** on
  this Universal → Squeezelite player (`flow_mode=true`, `http_profile=no_content_length`,
  `output_codec=flac`) — **both** `play_announcement` and `tts.speak` (which routes to it). It is **not**
  a broken speaker, transcode, clip, or a transient stall: the same clip via plain `play_media` is audible,
  and the silence survived disabling the SMB provider + a full MA restart + a Squeezelite restart. The
  *exact* internal mechanism is unproven (deep SlimProto trace is access-blocked); leading candidates: the
  documented **HTTP/1.0 stream-termination / mid-stream-interruption family** for this SlimProto player, and
  squeezelite **`-C 5`** (close ALSA output after 5 s idle) racing the announce pause→play gap. Note the
  07-15/07-16 audible ~7 s `play_announcement` results mean the overlay path *has* worked before, so it
  flips on a longer timescale and is sticky across restarts once broken.
- **S1b-2 impact — NOT hard-blocked; use the working route.** Ceiling replies can ship via the audible path:
  - **Route replies via plain `media_player.play_media`** of the reply URI (audible), **not** the announce
    overlay. This is **replace-not-overlay** (music stops for the reply), so pair it with S1b's existing
    **capture→replay** (radio → re-play `library://radio/2`; local music → re-play the prior item). This is
    exactly the operator's "play the reply, then restore" instinct, and it sidesteps the broken overlay.
    (Trade-off vs the overlay design in §11: no auto-resume, but it's audible today.) **Avoid `media_stop`**
    on resume (stop-wedge) — use `play_media` replace + capture/replay.
    - **Validated live end-to-end (operator-confirmed):** radio playing → capture `library://radio/2` →
      `play_media` the reply clip (audible spoken sentence) → re-play `library://radio/2` → **radio resumed**.
      Heard as *music → reply → music*, clean. (`media_duration` is not populated for the clip, so the replay
      timing used a ~6 s fixed wait; S1b-2 should size the post-reply wait to the reply length or poll for the
      clip to reach `idle`/end before replaying.)
  - **Keep the block-duration guard:** if an announce/overlay path is used, block **> ~10 s ⇒ likely silent**
    (healthy ~7 s); **never trust `ok:true`** (MA reports success while silent).
  - **Radio is NOT safe** for the overlay path (deterministically silent here); the play_media route + replay
    handles radio uniformly.
  - Fixing the **overlay path itself** remains a **dedicated reliability item** (needs MA container log access
    to trace; candidates: MA upgrade, player-config change, squeezelite `-C`/flags, upstream MA issue) — but
    S1b-2 no longer depends on it.
- **Live changes made (operator-approved; live gate CLAIMED then released):**
  1. **Disabled** MA provider `filesystem_smb--yYrXcamj` via MA WS `config/providers/save {enabled:false}`
     (its config was snapshotted read-only during the session; not needed for rollback — MA retains the
     disabled provider's values). **Left disabled** (beneficial cleanup — ends the mount-error(2) loop).
     **Rollback:** re-enable in MA UI (*Settings → Music Providers → the "requires attention" Filesystem
     provider → enable*) or `config/providers/save {enabled:true}`.
  2. **Restarted** the MA add-on (HA supervisor `hassio/addon_restart`) and, separately, the operator ran
     `sudo systemctl restart squeezelite-ceiling`. Both transient; no lasting config change.
  3. Squeezelite provider `log_level` toggled DEBUG→VERBOSE for tracing, **reverted to `GLOBAL`** (as-found).
  4. Ceiling playback **restored** (radio playing, volume 0.47 — the pre-test level).
- **Scope / safety:** MA reached read-mostly via its **on-host account token** (`~/mass-resolver/.ma_token`,
  never echoed) over the MA WS API; HA reads via on-host `.ha_token`. No resolver code / HA-script /
  exposure / firmware change. The provider-disable + restarts were explicit operator-approved live actions.
  MA WS method captured in `ONBOARDING.md` §3 (auth + `config/providers/*`).

## 2026-07-16 — S1b announce-silence root-caused: URI form exonerated; silence tracks a degraded ceiling stream

- **What:** live diagnostic investigation of the 2026-07-16 finding that `music_assistant.play_announcement`
  renders **silent** on `media_player.ceiling_speakers`. **Result: the announce primitive and the URI form
  are fine.** With the operator listening, `play_announcement` fed a plain `tts_proxy` URL (rewritten to the
  internal base `192.168.122.10`) was **clearly audible over both radio and working local music**. The
  earlier "silent" result was a **confound**: the announces measured silent were fired while the ceiling's
  underlying queue was in a degraded **"produced no audio data"** state (intermittent SMB / local-music
  failure); `play_announcement` overlays the current stream and inherits that stall.
- **Evidence (operator-confirmed by ear, live):**

  | Source at announce | URI form (base) | Block | Audible |
  |---|---|---|---|
  | local FLAC, degraded (`produced no audio data`) | tts_proxy (internal `192.168.122.10`) | 12.9 s | **No** |
  | local FLAC, degraded | tts_proxy (external `192.168.1.104`, via `tts.speak`) | 12.9 s | **No** |
  | radio (audible) | tts_proxy (internal) | 7.2 s | **Yes** |
  | working local music (audible) | tts_proxy (internal) | 6.9 s | **Yes** |

  A raw `media-source://tts/…` URI to `play_announcement` is rejected (HTTP 500, MA log
  `players/cmd/play_announcement: Only URLs are supported for announcements`) — so "media-source vs
  tts_proxy" is a non-distinction: `play_announcement` only takes a resolvable URL, and resolving a
  media-source TTS URI yields the same `tts_proxy` URL.
- **Block-duration diagnostic:** ~7 s block = healthy announce (audible); ~12–13 s block = announce fired
  over a stalled/no-audio queue (silent). The 07-16 finding's ~13 s blocks are the degraded-stream
  signature; even MA's own pre-announce chime was silent in that state.
- **No infra regression:** host up since 2026-06-30 (no reboot), Squeezelite `v1.8` and MA `2.9.3` both
  unchanged since 2026-06-30. The 07-15 audible spike vs 07-16 silent is **not** a restart regression — it
  tracks the intermittent underlying-stream health at test time.
- **`say` decision:** **no `_say` change needed.** `_say` already uses the correct primitive
  (`music_assistant.play_announcement`) + the correct URI form (tts_proxy → internal base) + radio
  capture→replay. **Spike-3 re-confirmed live:** radio → `idle` after the announce → `music_assistant.play_media
  {media_id: library://radio/2}` restarts it. The 07-16 "hold S1b-2" blocker was a confound, not an
  announce/URI defect.
- **S1b-2 recommendation: GO** on the announce mechanism (audible over radio and healthy local music).
  **Caveat (corrected 2026-07-16):** an intermittent degradation silences replies, and the reproduced
  trigger — SMB / "produced no audio data" local-music stall — is **not the whole story**. The original
  07-16 silence includes announce **`531187df`**, fired over an **audibly-healthy radio** source with a
  **reachable internal-base URL**, yet silent (~13 s) — **not** explained by an SMB/local stall (radio
  isn't SMB), and **not reproduced** in this investigation (which only saw degraded-local→silent and
  healthy-radio→audible). So the true failure is likely a **source-independent, intermittent announce
  degradation** (it silenced radio *and* local on 07-16, including MA's own chime), of which the SMB stall
  is one confirmed instance. **Do NOT assume radio replies are safe** — treat announce silence as possible
  over any source until the degradation is characterized. Out of S1b scope; flagged for a separate
  reliability investigation, and S1b-2 should **detect a likely-silent announce** (block > ~10 s) and
  surface it rather than reporting success.
- **Scope / safety:** read-only host diagnostics + coordinated live audio tests only — **no** resolver / HA
  / firmware / exposure change, **no** service restart. Live gate left **FREE**. Operator's playback
  restored (radio playing, per operator's choice).

## 2026-07-16 — S1b-1′ resolver `say` (play_announcement) deployed — Spike-2 NOT passed (announce silent on ceiling)

- **What:** deployed the S1b-1′ resolver rework — `interaction` `say` mode via
  `music_assistant.play_announcement` (blocking) + capture/replay, reply-timer machinery removed,
  duck/restore reverted to the AU-02/AU-03 form. Files: `haconn.py`, `config.py`, `config.json`,
  `interaction.py` (+ changed tests). Backup `~/mass-resolver/.bak/20260716-171148/`. Host `py_compile`
  + tests **OK on Python 3.5.2**; clean restart (`SERVICE: /command HTTP server on 192.168.122.1:8770` +
  `connected; subscribed …`, no bind-race, no traceback). Deploy is healthy.
- **Spike-2 validation — NOT passed.** With music playing, `/command interaction {mode:say, uri}`
  runs the pause/resume choreography (~13 s) but the reply is **inaudible**, over **both radio and local
  music**. Reproduced via a **direct HA `music_assistant.play_announcement` call** (bypassing the
  resolver) → **not a resolver bug**. The **same Piper clip via plain `media_player.play_media` is
  clearly audible**, and normal music/radio play fine → it is the **announce primitive specifically**
  that is silent on the ceiling zone (MA **Universal → Squeezelite**). Contradicts the earlier spike
  (announcement was audible then); the spike's exact conditions were never recorded.
- **Secondary findings:** HA `tts_get_url` returns the **external** base (`192.168.1.104`, unreachable
  from the playback path) — had to rewrite to the internal `192.168.122.10`; the URI fed to `say` in
  S1b-2 must be MA-reachable. `play_announcement` blocks **~13 s for a ~3 s clip** (UX).
- **State:** deploy **retained** — harmless (nothing in production invokes `say`; duck/restore is the
  working AU-02/AU-03 form). No rollback. **Reply-on-ceiling is blocked** pending an audible-announce fix.
- **Rollback (if ever needed):** `cp ~/mass-resolver/.bak/20260716-171148/*.py ~/mass-resolver/ &&
  cp ~/mass-resolver/.bak/20260716-171148/config.json ~/mass-resolver/ && sudo systemctl restart mass-resolver`.
- **Next:** root-cause the announce silence — leading hypothesis: the resolver announces to the MA
  **Universal** player (`media_player.ceiling_speakers`), while the spike may have targeted the underlying
  **Squeezelite** player; also recover the spike's conditions and check the MA add-on log during an
  announce. Fallback: rework `_say` to pause → plain `play_media` → replay. **Hold S1b-2** until an
  audible ceiling reply is proven. Plan: `plans/2026-07-15-s1b-1p-say-announcement.md`.

## 2026-07-15 — S1a satellite→ceiling duck/restore trigger (HA automation)

- **What:** installed an HA automation (`automation.s1a_satellite_ceiling_duck_restore`) that fires the
  resolver's `interaction` intent when the **reSpeaker Living Room** satellite enters/leaves a conversation —
  ceiling music **auto-ducks** while you talk to the satellite and **restores** when it returns to idle.
  Completes **S1a**. The spoken reply still plays on the **satellite's own speaker** (reply-on-ceiling is the
  separate S1b). No resolver code change (AU-02/AU-03 already live); no new `rest_command`.
- **Trigger:** state automation on `assist_satellite.respeaker_living_room_assist_satellite` —
  `→ listening/processing/responding` calls `rest_command.resolver_command {intent: interaction, params:
  {mode: duck}}`; `→ idle` calls `{mode: restore}`. `mode: queued` so intermediate transitions each re-fire
  `duck` (coalesced, re-arming the resolver's 120 s dead-man). Observed transitions: `idle → listening →
  responding → idle` (this pipeline skips `processing`; kept in the trigger defensively).
- **Install:** HA config API (`POST /api/config/automation/config/<id>` → HTTP 200); manageable in the HA UI.
- **Validation (live):** music playing, "Okay Nabu, what time is it?" → resolver log `DUCK 0.32→0.15` (wake)
  → two coalesced re-ducks (`0.15→0.15`, baseline preserved) → `RESTORE →0.32` (idle). Ducked audibly and
  returned; the mic heard the query over the 0.15 floor (no tuning needed); silent (volume-only).
  Ignore-when-idle confirmed (idle ceiling → `not_playing`, no change).
- **Scope / safety:** one HA automation; **no** exposure change, **no** resolver/model change, **no**
  `media_stop`. HA-live gate claimed + released (BACKLOG §10).
- **Rollback:** disable/delete the `S1a - Satellite Ceiling Duck/Restore` automation (nothing else to undo).
- **Unblocks / next:** **S1b** — universal resolver TTS relay so replies play on the ceiling. Plan:
  `plans/2026-07-15-s1a-satellite-ceiling-trigger.md`.

## 2026-07-15 — AU-02/AU-03 interaction duck/restore deployed (resolver `InteractionCapability`)

- **What:** deployed the resolver **`InteractionCapability`** (`interaction` intent, modes `duck`/`restore`)
  that ducks the ceiling zone (`media_player.ceiling_speakers`) during an assistant interaction and restores
  it exactly afterward — **AU-02** (restore/resume) + **AU-03** (duck-not-boost) shipped as one unit. Silent
  (volume-only; no TTS, never `media_stop`/`pause`). Driven manually via `/command` today; the automatic
  satellite trigger is **S1a** (next).
- **Mechanism:** snapshot current volume → `volume_set` to a floor (`interaction_floor`, default 15%, never
  *upward* — `min(current, floor)`) → restore to the snapshot. Coalesced re-ducks, **last-writer-wins**
  (won't clobber a user's mid-turn volume change), and a **120 s dead-man** auto-restore if the restore
  trigger never arrives. Volume writes go via a **fresh, status-checked HA REST** call (never the shared
  event WebSocket); duck/restore are serialized under a lock; restore discards its baseline only after the
  write is confirmed (no stranded-quiet ceiling).
- **Files deployed** to `~/mass-resolver/`: `haconn.py` (added `call_service_rest`), `config.py` +
  `config.json` (4 tunables: `interaction_floor` 15, `fade_ms` 0, `max_duck_timeout` 120000,
  `interaction_ignore_when_idle` true), `interaction.py` (new), `core.py` (registered in `CAPS`). Backup at
  `~/mass-resolver/.bak/20260715-130644/`.
- **Validation (live):** host Python **3.5.2** `py_compile` + the changed unit tests pass on-host;
  post-restart `/command` bound, auth `200/401`, event path `connected; subscribed`, no regressions.
  **End-to-end with music playing:** `duck` took the ceiling `0.43 → 0.15` and `restore` returned it to
  exactly `0.43` (confirmed against HA state), music never stopped, no assistant speech.
- **Scope / safety:** resolver code only; **no exposure change**, no HA-script change, no `media_stop`. The
  single live action was the restart (user-run `sudo systemctl restart mass-resolver`).
- **Rollback:** `cp ~/mass-resolver/.bak/20260715-130644/* ~/mass-resolver/ && rm interaction.py`, then restart.
- **Unblocks:** **S1a** (satellite `assist_satellite` state → `interaction` intent trigger). Procedure:
  `runbooks/resolver-deploy.md`. Design/plan: `plans/2026-07-14-au-02-03-interaction-duck-restore-plan.md`.

## 2026-07-14 — reSpeaker XVF3800 voice satellite onboarded + HA Internal URL fixed (NAT→LAN)

- **What:** onboarded the first **voice satellite** — a Seeed **reSpeaker XVF3800 + XIAO ESP32-S3** — into HA
  as an ESPHome device **`reSpeaker Living Room`**, with on-device wake word "Okay Nabu", local Whisper STT,
  and working spoken (Piper) TTS. Also fixed HA's **Internal URL**, which was auto-resolving to the host-only
  NAT IP and blocking LAN media/TTS fetches.
- **Firmware / flash:** installed the **ESPHome Device Builder** add-on; used the formatBCE
  `Respeaker-XVF3800-ESPHome-integration` satellite config (board `esp32-s3-devkitc-1`; external components +
  XMOS DSP firmware pulled at build; **unencrypted API**; secrets = `wifi_ssid`/`wifi_password`/`ota_password`
  only). Compiled in-add-on (~745 s) and flashed over USB via **web.esphome.io** ("Open USB flasher", since the
  HA page is plain http). XMOS DSP firmware 1.0.7.
- **Adoption:** auto-discovered → **Added**. Device: mfr `formatbce`, model *Respeaker XVF3800 Satellite*,
  MAC `68:ee:8f:51:e4:0c`. Entities incl. `assist_satellite.respeaker_living_room_assist_satellite`,
  `media_player.respeaker_living_room_media_player`, wake-word/LED/mute/alarm/timer controls.
- **HA Internal URL fix (the enabler):** `Settings → System → Network → Local network` was auto-set to
  `http://192.168.122.10:8123` (NAT, host-only) → **changed to `http://192.168.1.104:8123` (LAN)**. Without it,
  LAN devices (satellite, phone) can't fetch TTS/media (the satellite's setup media test failed until this).
  Ceiling TTS still works (host is on the LAN and reaches `192.168.1.104`). **Phone TTS reachability likely
  restored too — worth re-testing.**
- **Dedicated satellite pipeline:** created **"Living Room Voice"** (`id 01kxhm0a1vcdjwkrbp40a6cs43`) =
  Whisper STT + **Piper TTS** + `conversation.home_assistant`, assigned to the satellite
  (`select.respeaker_living_room_assistant`). This **isolates Piper TTS to the satellite** — the shared
  **"Home Assistant"** and **"ChatGPT"** pipelines keep `tts=None` (phone/default untouched). Spoken replies
  confirmed working on the reSpeaker (contradicts the old "Piper crashes the pipeline" blanket note — see
  ONBOARDING §6/§12).
- **Hardware note:** the XVF3800 has **no built-in speaker** — audio via its **3.5mm jack** or **JST 5W**
  connector. Tested with an external speaker on the 3.5mm jack.
- **Scope / safety:** **no exposure changes**; **no** resolver/MA/host changes; **no** MA/resolver/HA restarts.
  Changes were: one new add-on (ESPHome Device Builder), one new ESPHome device, one dedicated pipeline, and one
  network-URL setting. Device not yet assigned to an HA **area**.
- **Rollback:** set Internal URL back to auto; delete/ignore the ESPHome device; delete the "Living Room Voice"
  pipeline (satellite falls back to "preferred"); the ESPHome Device Builder add-on can be uninstalled.
- **Unblocks:** **`S0`** (satellite inventory — hardware now live) and the **`AU`** audio-policy /
  satellite→ceiling output-routing work.

## 2026-06-29 — Inc 2A News headlines: deployed, `script.news` created + exposed, validated

- **What:** shipped **Inc 2A — spoken news headlines**. New resolver `news` capability fetches a curated
  public RSS feed (Python 3.5 stdlib `urllib`+`xml.etree`; no API key, no new deps), parses headlines,
  returns a synchronous `CommandResult`; the resolver speaks the headlines once via Piper and ChatGPT
  relays the `chat_text`. New HA `script.news` (hard return `{chat_text}`) **exposed to ChatGPT**.
- **Resolver (repo, branch `homebrain/inc2a-news-headlines`):** new `newsfeed.py` (RSS/Atom fetch+parse
  behind a mockable seam; `<!DOCTYPE`/`<!ENTITY` rejection + 2 MB read cap; never raises), new
  `NewsCapability` (`resolve→validate→execute`) in `news.py` (replaced the stub), wired into
  `core.CAPS["news"]`, removed from `_STUBS`; `news.json` seeded (defaults + `world`→BBC World). 189 unit
  tests pass; network fully mocked. Whole-branch review: ready to merge.
- **G3 host reachability (read-only):** host (Python 3.5.2) reached
  `http://feeds.bbci.co.uk/news/world/rss.xml`, 41 titles parsed, `<!DOCTYPE`/`<!ENTITY` guard clean.
- **G4 deploy (host):** deployed `core.py`,`news.py`,`newsfeed.py`,`news.json` to `~/mass-resolver/`
  (backup `.inc2-bak/20260630T034433Z/`; checksums match; `py_compile` clean; `news` in `CAPS`, not in
  `_STUBS`). Service restarted (user-run sudo), active, 0 tracebacks. `/command` 401/200. `intent=news` →
  `ok=true`, "Top world headlines: 1)…2)…3)", `count=3`, Piper spoke once; `country=romania` →
  `not_found`, `spoken_text=null` (silent). No-regression of music/radio/find/status.
- **G6 HA script:** `script.news` (alias `Ceiling: News Headlines (resolver)`, mode single, **no
  fields**) created; hard return `{chat_text}` via `stop`+`response_variable`; **no `tts.speak`**, **no
  `set_conversation_response`**, no `media_player`/MA. `return_response=true` → exactly `{chat_text}`,
  matching `/command`. Existing 4 scripts SHA-unchanged.
- **G8 exposure + validation (2026-06-29):** exposed **only** `script.news` to `conversation`
  (`homeassistant/expose_entity`); exposure delta **12 → 13**, added `script.news`, removed none, no
  `media_player.*`/MA exposed. OpenAI Instructions updated (News capability bullet + READING THE NEWS
  routing; removed the obsolete "cannot read the news" clause; verbatim-relay rule preserved; model
  unchanged). Conversational validation via `conversation.openai_conversation`: "What are the news
  headlines?" / "Read me the news." / "What's the world news?" each called `script.news` (3 NEWS
  dispatches; announce +3 → Piper once per prompt) and relayed the real BBC headlines (no fabrication;
  ChatGPT lightly reformats — accepted cosmetic behavior). No-regression: status/find/play-music/
  play-radio all routed correctly, **0** news mis-routes; restored to idle. Exposed set verified **13**.
- **Inc 2B (news-station playback): deferred** — `play_radio` already plays news stations by
  genre/country; no RadioBrowser duplication.
- **Rollback:** un-expose `script.news` + revert the News docs/Instructions additions; delete
  `script.news`+reload if the script is wrong; restore `.inc2-bak/20260630T034433Z/` + restart (gated) if
  `/command news` fails. `mass_sync_request`, event adapter, existing scripts, gpt-4o-mini unchanged.
- See `2026-06-29-inc2a-news-headlines-design.md` and `plans/2026-06-29-inc2a-news-headlines.md`.

## 2026-06-29 — Inc 4A Phase 9 §2a–§2b: `script.media_status` exposed to ChatGPT

- **What:** added a `description` to **`script.media_status`** and **exposed it to the `conversation`
  assistant** (WS `homeassistant/expose_entity`, `assistants:["conversation"]`, `should_expose:true`).
- **Description added:** "Reports what is currently playing on the ceiling speakers … Read-only. Use
  when the user asks what's playing, what song or station is on, whether anything is playing, or the
  current/how-loud volume." Structural readback unchanged otherwise (alias/mode/sequence intact, **no
  `tts.speak`**, **no `set_conversation_response`**, no fields); hard return still
  `{chat_text: "..."}`; silent (no announcement).
- **Exposure delta (verified):** baseline **11 → 12**; **added `script.media_status`**, **removed none**,
  **changed none**. `play_music`/`play_radio`/`find_stations` still exposed; raw
  `media_player.ceiling_speakers` and all MA/`media_player.*` entities **not** exposed; no unrelated
  scripts exposed.
- **§3–§4 DONE (2026-06-29):** appended the STATUS Instructions (WHAT YOU CAN DO bullet + CHECKING
  WHAT'S PLAYING block; verbatim-relay line preserved). Conversational validation via
  `conversation.openai_conversation`: all four status prompts called `script.media_status` and relayed
  the real state (exact `27%` volume in every reply → tool genuinely used; **no fabrication**); **silent**
  (no announcement). No-regression: play music / play radio / find stations all still route+work. Exposed
  set verified **exactly 12** (baseline + `media_status`); no `media_player`/MA exposed. Baseline restored.
  **Inc 4A Phase 9 COMPLETE.**
- See `plans/2026-06-29-inc4a-status-now-playing.md` (Execution outcome).

## 2026-06-29 — Inc 4A Status / Now-Playing: resolver capability + `script.media_status` DONE (validated-but-unexposed)

- **What:** built and deployed the **`status` capability** (now-playing read) and created the HA script
  **`script.media_status`** — **not exposed to ChatGPT** (Phase 9 exposure is a separate gate).
- **Resolver (committed `f110d67`):** HA-state-primary, summary-only `StatusCapability`
  (`resolve→validate→execute→CommandResult`); wired into `core.CAPS["status"]`, removed from `_STUBS`;
  read-only HA REST reader `haconn.HA.get_entity_state()` (fresh per-call, not the shared event socket);
  unconditionally silent (`spoken_text=None`). 160 unit tests pass.
- **Phase 5 deploy (host):** deployed `core.py`, `haconn.py`, `resolver.py`, `status.py` to
  `~/mass-resolver/` (backup `/home/costea/mass-resolver/.inc4a-bak/20260629T200033Z/`); checksums match,
  modes preserved (664/664/664/755), host Python 3.5.2 `py_compile` clean. Service restarted; 0 tracebacks.
  `/command` **401 without key / 200 with key**. Live validation: radio →
  `Playing 101 SMOOTH JAZZ at 27% volume.` (`content_kind=radio`, `spoken_text=null`); music →
  `Playing "Zeit" by Rammstein at 27% volume.` (`content_kind=track`). **No speaker announcement** for
  status. No-regression: `music`/`radio` play/`radio` find all OK; playback baseline restored.
- **Phase 7 (HA script):** `script.media_status`, alias `Ceiling: Media Status (resolver)`, mode
  `single`, **no fields**; returns **exactly `{chat_text: "..."}`** via `stop`+`response_variable`
  (validated by `return_response`); **no `tts.speak`**, **no `set_conversation_response`**. Existing
  scripts **unchanged by SHA** (`play_music`, `play_radio`, `find_stations`). **Not exposed to ChatGPT.**
- **State:** Inc 4A **validated-but-unexposed** — ChatGPT cannot call `script.media_status` yet.
- **Rollback:** resolver = restore four files from the backup above (restart approval-gated); HA script =
  delete `script.media_status` + reload (no resolver rollback needed for a script-only failure).
- See `plans/2026-06-29-inc4a-status-now-playing.md` (Execution outcome) and
  `2026-06-29-inc4a-status-now-playing-design.md`.

## 2026-06-28 — F1-R music-only migration DONE (`script.play_music` synchronous, ChatGPT relays chat_text)

- **What:** re-migrated **`script.play_music` only** to the resolver `/command` path using the
  Phase-0-proven relay — the script **returns** `{chat_text: r.content.chat_text}` via `stop` +
  `response_variable` (a hard tool result), with **no `set_conversation_response`** and **no
  `tts.speak`** (resolver stays sole TTS owner). One line added to the OpenAI agent Instructions:
  *"When a tool returns a chat_text field, relay that text verbatim."*
- **Validated (Gates 1–8):** `play Rammstein` → ChatGPT reply `Playing Rammstein.` = **exact `chat_text`**;
  music played; no duplicate TTS; restored PLAYING log present. `play My Way` → ChatGPT relayed the
  honest `"My Way" isn't in your local library yet.` with no playback (the T11 failure, now fixed).
  Direct `return_response` test returned the expected `chat_text`. Event fallback and `/command`
  (200/401) intact. Backup at `~/script_backups/play_music.preF1R.json`.
- **Left migrated** (not rolled back). **Radio/find untouched** (still event-path). No new tools; no
  model change (gpt-4o-mini kept).
- See `2026-06-28-F1-R-chatgpt-tool-result-relay-design.md` and
  `plans/2026-06-28-F1-R-music-remigration.md` (Outcome).

## 2026-07-01 — Power-outage recovery: `/command` bind race (fixed by restart; durable fix planned)

- **Incident:** after a power outage + host cold boot, ChatGPT reported it couldn't reach music/radio.
- **Root cause:** `mass-resolver` started before libvirt's bridge IP `192.168.122.1` was assigned, so the
  `/command` HTTP bind failed (`OSError 99`) and — being one-shot — the resolver ran **event-only**
  thereafter. MA/HA/VM/event path were all healthy; only `/command` (which all three ChatGPT tools use)
  was down.
- **Recovery:** `sudo systemctl restart mass-resolver` (bridge was up by then) → `/command` re-bound on
  `192.168.122.1:8770`; verified 200 (good key) / 401 (no key). Service restored.
- **Durable fix planned (not yet implemented):** retry the `/command` bind with backoff so it self-heals
  after a reboot (mirrors the event-connection reconnect). Plan:
  `plans/2026-07-01-command-bind-retry-bugfix.md`. Interim runbook added to `ONBOARDING.md` §7.

## 2026-06-29 — F1 / F1-R CLOSEOUT (accepted complete)

- **Marked F1/F1-R DONE** in the umbrella roadmap (`2026-06-27-assistant-tooling-design.md` §7) with a
  production-state / validation / rollback closeout in §10.
- **Final production state:** `play_music`, `play_radio`, `find_stations` all return
  `{chat_text: r.content.chat_text}` via `stop` + `response_variable` (hard tool result); none use
  `set_conversation_response`; none call `tts.speak`; resolver is sole TTS owner; `/command` live +
  authenticated; event adapter live; `mass_sync_request` untouched; gpt-4o-mini unchanged; no new tools.
- **Validation:** music success + no-match; radio play success + no-match; find stations — all validated;
  ChatGPT relays `chat_text` via the hard tool-return mechanism; Speaker reconnect bug fixed + deployed.
- **Rollback:** per-script `*.preF1R.json` backups retained; `/command` and the event path stay available
  even if a script is rolled back (independent).
- **Backlog added:** optionally tidy verbose RadioBrowser station names before they enter `chat_text`
  (UX only, no correctness impact).

## 2026-06-29 — F1-R radio/find migration DONE (`play_radio` + `find_stations` synchronous)

- **What:** migrated the two remaining exposed radio scripts to the resolver `/command` path using the
  proven hard-return pattern — each script **returns** `{chat_text: r.content.chat_text}` via `stop` +
  `response_variable` (intent `radio`, `mode: play`/`find`). **No `set_conversation_response`**, **no
  `tts.speak`**; resolver stays sole TTS owner. Existing fields/mapping preserved verbatim. Migrated one
  at a time with per-script backups (`play_radio.preF1R.json`, `find_stations.preF1R.json`).
- **`play_radio` (Stage A):** success plays + ChatGPT relays `Playing <station>.` (verbatim for clean
  names; cosmetic tidying of verbose RadioBrowser names — accepted, no misrouting); success silent from
  Piper; no-match → one honest Piper line + no playback. (Also exercised the Speaker reconnect fix live.)
- **`find_stations` (Stage B):** ChatGPT relayed the full station list **in order, none omitted/invented**
  (only harmless formatting); resolver spoke the same list once; no duplicate TTS; no playback.
- **State:** all three exposed scripts (`play_music`, `play_radio`, `find_stations`) now synchronous;
  `/command` 200/401, event adapter, and `mass_sync_request` intact; no new tools; gpt-4o-mini unchanged.
  **F1-R complete.** See `plans/2026-06-29-F1-R-radio-find-migration.md` (Outcome).

## 2026-06-28/29 — Speaker WebSocket reconnect bug FIXED & DEPLOYED

- **Symptom:** after an HA restart mid-session, every resolver Piper announcement failed with
  `BrokenPipeError(32)`; successful music playback was unaffected (that path is Music Assistant, not the
  Speaker).
- **Root cause:** `haconn.HA.announce()` caught and **swallowed** the send exception, so
  `Speaker.speak()`'s reconnect-once logic never fired and the dead WebSocket persisted.
- **Permanent fix (implemented + deployed 2026-06-29):** `haconn.HA.announce()` now logs **and
  re-raises** send/connection failures; `Speaker.speak()`'s existing reconnect-once then heals the
  socket (and stops after one retry — no loop). Commits `5617454` (fix + `test_haconn`),
  `41ecf01` (`test_speaker` reconnect/no-loop tests). Built subagent-driven (per-task + final review,
  all clean).
- **Validation:** unit/integration tests pass on the host's **Python 3.5.2** (`test_haconn` 5/5,
  `test_speaker` 6/6); post-restart live check shows `ANNOUNCE via tts.speak` succeeding again
  (0 failures), playback + `/command` (200/401) + event fallback all intact. Backup at
  `~/mass-resolver/.f1bak/haconn.py.bak`. Plan: `plans/2026-06-28-speaker-reconnect-bugfix.md`.

## 2026-06-28 — F1-R Phase-0 probe: hard tool-result relay PROVEN (PASS)

- **Why:** T11 proved `set_conversation_response` is ignored by the OpenAI Conversation agent for
  tool-invoked scripts. F1-R Phase-0 tested the alternative: a script that **returns** a value via
  `stop` + `response_variable` (a hard tool result).
- **Result — PASS.** A throwaway `script.f1r_probe` (calling `rest_command.resolver_command` with an
  unknown, no-TTS intent, then returning a sentinel via `stop`/`response_variable`) was invoked by
  ChatGPT. **Bare** return was surfaced faithfully (`The diagnostic code is Zphrqx-7741-Marmalade-Echo.`);
  with a **verbatim directive** the reply was the exact sentinel (`Vqwerty-2208-Saffron-Relay`). Resolver
  `/command` was confirmed invoked (`unknown intent 'f1rprobe'` logged twice). This is the clean inverse
  of T11.
- **Cleanup / safety:** throwaway script unexposed + deleted (GET → 404); helper artifacts removed. **No
  production script modified** (`play_music`/`play_radio`/`find_stations` untouched); no new tool exposed;
  no model change.
- **Next:** gated **music-only** re-migration using the proven `stop`/`response_variable` return (radio
  and find stay on the event path). See `2026-06-28-F1-R-chatgpt-tool-result-relay-design.md` and
  `plans/2026-06-28-F1-R-music-remigration.md`.

## 2026-06-28 — F1 T11 (`script.play_music` → `/command`) attempted and rolled back

- **What:** migrated `script.play_music` from the fire-and-forget `mass_play_request` event to the
  synchronous resolver `/command` endpoint (`rest_command.resolver_command` + `response_variable` +
  `set_conversation_response` from `CommandResult.chat_text`). Resolver remained the sole TTS owner;
  the script called no `tts.speak`.
- **Result — mechanically successful, but Gate G1 failed:** resolver behavior and HA
  `response_variable` capture were correct (`/command` returns HTTP 200 + honest `chat_text`), but the
  **OpenAI Conversation agent ignores `set_conversation_response` when a script is invoked as a tool** —
  it composes its own generic `"Playing <query>."` reply. Confirmed decisively with a sentinel string
  the agent declined to echo. The earlier "pass" (`Playing Rammstein.`) was a coincidental match.
- **Rollback:** `script.play_music` restored from `~/script_backups/play_music.json` to the original
  event-firing version. Verified: event path plays, direct `mass_play_request` plays, honest Piper
  feedback intact, `/command` live + authenticated (200/401), event adapter live; `mass_sync_request`,
  `script.play_radio`, `script.find_stations` untouched. No GPT model change; no new tools exposed.
- **Next:** design addendum **F1-R** (deliver `chat_text` as the actual tool result). No T12. See
  `2026-06-28-F1-R-chatgpt-tool-result-relay-design.md` and the T11 outcome in
  `plans/2026-06-28-F1-T11-T12-script-migration.md`.

## 2026-06-28 — Home Assistant user "Vio" created (standard / non-admin)

- Created a new Home Assistant user **Vio** via the HA UI (owner action).
- Type: **Standard user (non-administrator)**; login **enabled**.
- **No** long-lived access tokens created.
- **No** changes to existing users, groups, dashboards, automations, or integrations.
- **No** additional entities or scripts exposed to ChatGPT.
- Home Assistant was **not** restarted.
- An initial password was set during creation. The password is **not stored in this
  repository** (or anywhere in the repo); change/rotate it via the HA UI as needed.
- Verify: Settings → People → Users → "Vio" shows **no Administrator badge**.
