# Homebrain Change Log

Operational/administrative changes to the homebrain setup. (Architecture and feature
design live in the per-topic docs; this log is for discrete operational changes.)

## 2026-09-27 — AN-01 resolver redeploy #2: bounded in-lock HA calls, honest chime metadata

> Announcements remain **disabled**; the only live path affected is the satellite reply.
> Rollback: `~/mass-resolver/.bak/20260927-190834/`.

`interaction.py 84cc1f78` + its test module, from `main` at `fcbda6b`. `config.py`, `config.json`,
`wsutil.py`, `haconn.py` unchanged and not copied. **Host parity, Python 3.5.2: 493 tests OK**
(was 487), `COMPILE OK`. Operator restart at **19:12:23**, after the 19:08:35 file write; clean
startup lines, `key=200`/`nokey=401`, no tracebacks, satellite `idle`, microphone `off`.

Pre-change: `interaction.py 1b63edeb`, `tests/test_interaction.py 61b14157`.

**What changed.** The four HA calls made while `_lock` is held — a read and a `volume_set` in each
of `_duck` and `_restore` — now carry `LOCK_HELD_CALL_TIMEOUT` instead of the client default. That
lock also gates `_claim_gen`, `interaction_in_flight` (called on every dispatch result) and the
volume-recovery timer, with the microphone dead-man queued behind it, so a hung Home Assistant used
to stall far more than its caller. The chime also stops being judged by `started` alone: it now
carries `end_observed` and an `end_unobserved` reason, though it remains decorative and still cannot
fail a turn.

### Live-gate handling for this deploy — stated rather than skipped

The gate was **not claimed in a separate published commit beforehand**. Pushes to `main` now require
a pull request, and recording claim-then-release as two merges costs two PRs for a ten-minute
window. The gate was free throughout, one operator was present for the restart, and this entry
records both the claim and the release. Noted here because the register is only worth anything if
its gaps are visible; if the two-step is wanted even at that cost, say so and it resumes.

### N3 — the microphone mute window: DECIDED, no change

The 2026-09-27 failure held the microphone **52 s**: a 6 s chime plus a message that gave up at its
full 45 s `announce_message_finish_timeout_ms`. Shortening that budget was considered and
**rejected for now**.

| `announce_message_finish_timeout_ms` | worst-case mute |
|---|---|
| **45 s (current)** | **52 s** |
| 25 s | ~32 s |
| 15 s | ~22 s |

Giving up does not merely stop waiting: `_say` then restores the volume and replays the captured
source **over the clip**. A budget shorter than a legitimate announcement therefore truncates real
speech. `announce_max_chars` is 300 — roughly 50 words, about 20 s of Piper speech — so 45 s is a
~2x margin and 25 s has almost none.

If the window is ever worth shortening, the lever is **both** values: halving `announce_max_chars`
to ~150 (≈10 s of speech) would let the budget drop to 25 s while keeping the margin. One without
the other buys a cut-off announcement.

Neither is changed now, because announcements are disabled and the window costs nothing today, and
because the right time to set these is when G4b is re-enabled, **from measured clip durations**.
Choosing a threshold from arithmetic is exactly what produced the silence detector that had to be
removed the same afternoon.

**Live gate: FREE. G4b remains halted, `automation.voice_ceiling_announce` remains `off`.**

## 2026-09-27 — AN-01 resolver redeploy is LIVE: honest reporting, safe microphone handover, and the TTS url in the log

> **Announcements remain DISABLED**, so the only live path this touches is the satellite reply
> (`say`/`say_text`). Rollback: `~/mass-resolver/.bak/20260927-181921/`.

### What was deployed

`interaction.py` and its test module only, from `main` at `7ee00be` (PR #50 plus the tts-url
commit). `config.py`, `config.json`, `wsutil.py` and `haconn.py` are unchanged by these commits and
were **not** copied; their checksums are unchanged from the 2026-09-10 record.

- **Backup:** `BACKUP_TS=20260927-181921`, covering both files the copy touches. Pre-change:
  `interaction.py bd98a05f`, `tests/test_interaction.py d6368321`.
- **Deployed:** `interaction.py 1b63edeb`, `tests/test_interaction.py 61b14157`, verified by sha256
  end to end rather than by `scp`'s exit code.
- **Host parity, Python 3.5.2:** `COMPILE OK`; **487 tests OK** (was 449) — `test_interaction` 406,
  `test_py35_compat` 7, `test_haconn` 42, `test_config` 23, `test_wsutil` 9.
- Restart was the operator's at **18:23:37**, after the 18:19:23 file write; fresh
  `SERVICE: /command HTTP server…` and `connected; subscribed…`, no tracebacks.
- Post-restart: `key=200`/`nokey=401`, satellite `idle`, microphone `off`,
  `automation.voice_ceiling_announce` **off**, ceiling untouched.

### What changed in behaviour

**An announcement no longer claims success it cannot support.** `_play_clip_and_wait` returns
`ended` and `gave_up` instead of discarding them, and the announce path now has three outcomes for
three states of knowledge: a clip watched failing to start is a certain failure
("I couldn't play the announcement."), an observed end is "Announced.", and a clip that started but
whose end was never seen reports "Announced, but I couldn't confirm it finished." The previous
behaviour reported a flat "Announced." for a clip nobody heard — and an intermediate version
reported a flat failure for the 2026-09-08 announcement, which was heard in full.

**A read that did not happen is no longer an observation.** Both poll loops count unreadable reads
and exit as `unreadable`; two consecutive failed reads used to manufacture an observed ending.

**The microphone handover is serialised.** A dedicated `_mic_lock` spans claim's mute-and-publish
and release's validate-and-unmute. Previously an older turn could unmute a microphone a newer
announcement had just muted, broadcasting through a live satellite mic.

**The turn deadline covers the `play_media` call cost** it always spent inside itself — 70s of
window for work that can need 100s. Widening a bound only.

**The resolved TTS url is logged whole and redacted**, extension included. This is the operationally
important one: see below.

### Why the url line matters

The 2026-09-27 failure was diagnosed a day late, by reading Music Assistant's log. The resolver
could not show the cause because it logged only `engine=` and `chars=` at resolve time, and the
finish poll truncates the `media_content_id` at 80 characters — landing just short of the file
extension, which was the whole answer. A failing url is now visible in `resolver.log` at the moment
it is resolved, and `curl -I` against it settles 404-or-200 immediately.

### What this does NOT do

**It does not make announcements work.** The defect is that some TTS urls are not fetchable — see
the correction document's retraction section. This deploy makes failures honest, legible and safe;
the fix is a separate increment. `automation.voice_ceiling_announce` stays disabled.

## 2026-09-27 — AN-01 G4b: the sentences are live but DISABLED — step 4 failed and the completion defect reproduced

> **The announcement automation exists and is switched off.** The first phone announcement muted the
> microphone for 52 s, produced **no audible message**, and told the phone "Announced." anyway.
> Kill switch already applied: `automation.voice_ceiling_announce` is `off`.

### What was created

`automation.voice_ceiling_announce` (config id `1790544577824`), a **new, separate automation** rather
than a 9th branch of `automation.voice_ceiling_speakers`. **Deliberate deviation from Task 26.** That
automation is `mode: queued` and a `rest_command` call is synchronous, so an announcement placed in it
would block all 82 existing ceiling sentences for its duration — including the "pause" and "stop"
commands an operator would reach for if an announcement misbehaved. A separate automation gets its own
queue and a one-toggle kill switch.

- Sentences: `announce {message}`, `broadcast {message}`. `mode: queued`, `max: 2`.
- Condition `{{ trigger.satellite_id | default(none) is none }}` — admits phone and web Assist,
  blocks the satellite, per D12.
- Action `rest_command.resolver_command_announce` with `response_variable: r` and
  `continue_on_error: true`, then a `choose` with the two failure branches and the default relay.
- Every shape copied from the live automation read at 11:13 (new-style `triggers`/`conditions`/
  `actions`), not from the plan's skeleton.
- Backup taken first: `.bak/automation-voice_ceiling_speakers-20260927-111309.json`, sha256
  `b8c6cd48`, 7686 bytes, JSON validated.

### Verified before any test

`automation.voice_ceiling_speakers` **byte-identical** to its backup (`b8c6cd483844d6d5` both sides).
All 82 existing sentences scanned: **0** begin with announce or broadcast, so no shadowing. Resolver
`active`, `auth=200`, no tracebacks.

### Step 4 FAILED — req `f864d0ff`, 16:01:50

The operator said *"Announce dinner is ready."* from the phone. The chime played. Nothing else did.

```
16:01:56  chime 8a266f28  finish-poll exit after 5.5s: state=idle
16:02:42  WARNING clip 414d2b19 finish-poll gave up after 45.0s without observing
          the clip end (budget 45.0s, reason=finish_timeout)
16:02:42  restored -> 0.3 (owns_restore=True) ; mic restored
```

**Microphone muted 52 s.** The clip sat at `state=playing, media_position=0, media_duration=None` and
never advanced — it was still holding the zone minutes later and had to be stopped manually.

**This is a fourth distinct exit behaviour**, not the 2026-09-08 failure: that one was **audible** and
only its completion went unobserved. Per the design decision's stop criteria, no remedy is proposed.

It also **falsifies yesterday's "not reproducible" conclusion**, on the first attempt through the
phone path.

### 6a proved itself in production

The `finish-poll gave up after 45.0s ... reason=finish_timeout` warning is the budget-exit logging
from PR #49. The identical failure on 2026-09-08 logged **nothing**, which is what made it expensive
to investigate. The observability work is now demonstrably worth what it cost.

### A second, independent defect: a false success

The automation trace took `choice=default`, i.e. `r.content.ok` was true, so the phone displayed
**"Announced."** Metadata carried `likely_silent: False` and both clips `issued`/`started`. The
resolver believes a play that was *accepted* and produced *silence* succeeded. Design 5.2's
honest-failure mapping covers refusals, not silent successes. This would survive a fix to the
completion defect and needs its own design work.

### D7, partially settled

`chars=15` — `trigger.slots.message` carried `dinner is ready`, **the trailing full stop stripped**.
That is the opposite of SPIKE-AN-3's finding for `trigger.sentence`, which preserves punctuation, so
**the slot and the sentence normalise differently**. First-letter capitalisation remains unconfirmed.

### Recovery and current state

Mic back to `off`, volume restored to 0.3, dead-man armed at 184 s and not needed, no tracebacks. The
stuck TTS clip was cleared and `library://radio/4` restored at 0.3. The other seven automations were
untouched.

**`automation.voice_ceiling_announce` is disabled.** With no caller, `mode=announce` is inert.
**G4b is halted at step 4**; steps 5-8 assume a working announcement and would measure nothing.

**This entry is the sole record** — the automation is live HA config and is not in the repo.

## 2026-09-26 — AN-01 G4a: the dedicated announcement REST command is LIVE

> `rest_command.resolver_command_announce` exists, is reloaded, and has made one verified round trip.
> **Nothing calls it yet** — it is an unused definition until G4b's sentence triggers land, which is
> also what makes its blast radius zero. Rollback: `/config/configuration.yaml.bak-20260926`.

### D13b is now a fact, not an inference

Checkpoint A passed D13b by inference from nine working callers. The live template was read for this
task, as Task 25 step 3a requires:

```yaml
payload: >-
  {"intent": "{{ intent }}", "params": {{ params | default({}) | tojson }}}
```

Proper JSON serialisation — the **go** row of step 3a's classification table. Had it been raw
`{{ params }}` interpolation, the body would have been a Python `dict` repr with single quotes and
the failure would have surfaced at G4b as an announcement that silently does nothing.

Two further facts from the same read:

- **`resolver_command`'s own `timeout: 30`** makes D13's dedicated shape **required**, not merely
  preferred. An announcement runs 10–60 s; the shared command would truncate it.
- **`content_type` is a top-level key in the live block, not a header** — unlike the skeleton in the
  implementation plan. The plan says to copy the live block verbatim, which is what was done; the
  skeleton is wrong and Task 27 should correct it.

### What was added

```yaml
  resolver_command_announce:
    url: "http://192.168.122.1:8770/command"
    method: POST
    content_type: "application/json"
    timeout: 200
    headers:
      X-Resolver-Key: !secret resolver_http_secret
    payload: >-
      {"intent": "{{ intent }}", "params": {{ params | default({}) | tojson }}}
```

Reloaded via **Developer Tools → YAML → Reload REST commands**; no HA restart was needed.

### Step 6 — no existing caller moved

`script.play_radio`, `script.play_music`, `script.find_stations`, `script.news` and
`script.media_status` all still reference `rest_command.resolver_command` with its original 30 s
timeout. **0 scripts** reference the new command, which is correct until G4b.

### Step 5 — one round trip through HA's template, 12.66 s

Called as `rest_command.resolver_command_announce` through the HA API, so the payload template itself
was exercised, not just the resolver's endpoint. `status: 200`, `ok: true`,
`chat_text: "Announced."`, both clips `issued` + `started`, `mic {muted, confirmed}`,
`chime {played}`, `volume_restore: "restored"`, `superseded: false`.

| | |
|---|---|
| Start state | **`playing`** — the configuration the spike matrix never covered |
| Chime `cea57224` | finish-poll exit after 7.0 s, `state=idle` |
| Message `b9909fe8` | finish-poll exit after 2.0 s, `state=idle` |
| Microphone | leased, confirmed after 2 polls, **restored to `off`** — held 11.5 s |
| Volume | 0.36 → 0.8 → **0.36** |
| Music | **`replayed: true`** — the resolver resumed `library://radio/4` itself; the harness's safety-net restore was not needed |
| 6a budget-exit warnings | **0** |

The playing start is the case that produced the blank-cid grace exit on 2026-09-08. Here it took the
pause-and-replay path cleanly, and a transient blank `media_content_id` appeared at t=11.6 s during
the handover back to the radio without affecting the outcome.

### Discovered, and it needs a decision at G4b

**`script.ceiling_announce` already exists and bypasses the resolver entirely.** It calls `tts.speak`
straight at `media_player.ceiling_speakers` via Piper — no microphone mute, no chime, no volume duck
or restore, no turn lock, no dead-man. It is the pre-AN-01 way of doing what AN-01 now does safely,
and the implementation plan does not mention it.

Per the managed exposure baseline it is **not exposed to any assistant**, so it is reachable from a
dashboard or a manual service call but not from a spoken sentence. That baseline is a stored snapshot;
re-confirm with an exporter run before G4b.

**G4b must decide:** repoint it at the new command, delete it, or keep it and document why two
announcement paths exist. Leaving an unsafe duplicate beside the safe one is how the wrong one gets
called later.

## 2026-09-26 — AN-01 observability redeploy is LIVE, and the spike matrix completed: the 2026-09-08 completion-detection failure DID NOT REPRODUCE

> **The defect is not fixed — it is not currently observable.** All four matrix cells ended cleanly,
> including a same-build control re-run of the exact configuration that failed on 2026-09-08. Cause
> unknown. Rollback pointer: `~/mass-resolver/.bak/20260910-131220/`.

### What was deployed

`interaction.py` only, plus its test module, from `main` at `52d03d8` (PR #49) — the two
mechanism-independent observability fixes: a warning when a clip's finish poll gives up without
observing the end (6a), and one normalised clip fingerprint per clip instead of two (6b). **Neither
changes behaviour on any success path.** Files were staged 2026-09-10 and sat unrestarted for 16 days.

- **Backup / rollback pointer:** `OBS_BACKUP_TS=20260910-131220`, covering **both** files the copy
  touches. Pre-change: `interaction.py ff03c969`, `tests/test_interaction.py 7ba49361`.
- **Deployed:** `interaction.py bd98a05f`, `tests/test_interaction.py d6368321`, verified by sha256
  against `main`. Untouched and unchanged across the 16 days: `config.py b978ce0a`,
  `config.json 2ea59677`, `wsutil.py 42391477`, `haconn.py e1bb6a5d`.
- **Host parity run, Python 3.5.2:** `COMPILE OK`; **449 tests OK** — `test_py35_compat` 7,
  `test_interaction` 368, `test_haconn` 42, `test_config` 23, `test_wsutil` 9.
- Restart was the operator's `sudo systemctl restart mass-resolver` at **11:31:45**; fresh
  `SERVICE: /command HTTP server on 192.168.122.1:8770` + `connected; subscribed …`, no tracebacks.
- Re-verified before the restart that the 16-day-old staging was still intact: checksums unchanged,
  host uptime 12 weeks with no intervening reboot, backup directory present.

### The attended spike matrix

Three live turns on the ceiling, each capturing and restoring the operator's music.

| Cell | Clips | Ceiling before | Result |
|---|---|---|---|
| B | 1 (`say_text`) | paused | **ended, 3.14 s** — `finish-poll exit after 1.0s: state=idle` |
| C | 2 (`announce`) | idle | **ended, 11.35 s** — chime 6.5 s, message 2.0 s, both `state=idle` |
| D | 2 (`announce`) | paused | **ended, 9.50 s** — same configuration that took **52.7 s** on 2026-09-08 |

Cell D was not in the plan. It was added as a **same-build control**, because B and C passing is
ambiguous between an interaction effect and the failure having stopped occurring — and the design's
own rule that a claim needs a same-build control applies to claiming a failure still exists, not just
to claiming a fix.

### What passed

- **Recovery paths, three for three:** microphone leased → mute confirmed after 2 polls → restored to
  `off`; volume `0.2 → 0.8 → 0.2` (cell B `→ 0.7 →`), always back to the captured baseline;
  dead-man armed at 184 s and never fired. Cell D held the microphone **8.4 s**, not ~53 s.
- **Health:** `/command` bound, `key=200`/`nokey=401`, VM `running`, satellite `idle` throughout,
  **zero tracebacks**.
- **The 6a warning fired 0 times**, correct when no poll exhausts its budget, and the positive control
  that a silent budget exit would now be visible.
- Operator confirmed both announcements audibly.

### What this does and does not establish

**It does not establish a fix.** PR #49 cannot explain cell D passing: `clip` at `interaction.py:1251`
feeds only `LOG` calls and `_warn_if_double_speak`, and 6a is a `LOG.warning`. What changed between
2026-09-08 and 2026-09-26 is uncharacterised — the resolver had run since 2026-09-09 16:27 and was
restarted today, the host has 12 weeks' uptime, and HAOS/Music Assistant may have moved. Nothing
measured distinguishes these.

Two hypotheses were falsified by measurement over this investigation: the `media_type` wrapper story
(2026-09-09) and the clip-sequence story (cell C). No remedy is proposed, per the design decision's
stop/go criteria.

**G4a and G4b are unblocked** — not because the defect is understood, but because it cannot presently
be observed, its worst case is bounded by the dead-man, and a recurrence will now log
`finish-poll gave up after … reason=`. The live gate is released.

## 2026-09-08 — AN-01 resolver deploy is LIVE, and G3 validation FAILED at step 4: a TTS clip wrapped as `builtin://radio/` never reports completion, so an announcement holds the microphone for ~53 s

> **The deploy itself is sound; the validation is not complete and G4 is blocked.** Every asserted
> behaviour passed. The defect is a **timing** one, and it lands on requirement 7 (mute the satellite
> microphone for the announcement), so it is recorded as a **failure**, not a caveat. **No rollback:**
> the deployed code is correct on every behaviour it asserts, and reverting would lose a clean deploy
> to fix a wait. Rollback pointer kept regardless: `~/mass-resolver/.bak/20260908-163353/`.

### What was deployed

`interaction.py`, `haconn.py`, `wsutil.py`, `config.py`, `config.json` plus five test modules
(`test_interaction.py`, `test_haconn.py`, `test_config.py`, `test_wsutil.py`, `test_py35_compat.py`),
from `main` at `4cb2869` (PR #48). Copies verified by **sha256 end to end**, not by `scp`'s exit code.

- **Backup / rollback pointer:** `BACKUP_TS=20260908-163353`. All five backed-up files' checksums
  matched the pre-change record exactly.
- **Pre-change deployed state:** `interaction.py 570de080`, `haconn.py 2928f60e`, `wsutil.py 2553f72b`,
  `config.py ec681f19`, `config.json 1f247941`. Confirmed pre-AN-01: `_mic_claim`, `_volume_recovery`,
  `_play_clip_and_wait`, `_redact_uri`, `announce_volume` all absent.
- **Host parity run, Python 3.5.2:** `COMPILE OK`; **435 tests OK** — `test_py35_compat` 7,
  `test_interaction` 354, `test_haconn` 42, `test_config` 23, `test_wsutil` 9. `JSON OK 0.8 0.7`,
  `CONFIG SANE`.
- Restart was the operator's `sudo systemctl restart mass-resolver` at **16:41:49**; fresh
  `SERVICE: /command HTTP server on 192.168.122.1:8770` + `connected; subscribed …`, no tracebacks.

### What passed

- **Health checks:** VM `running`, resolver `active`, `/command` bound, MA/HA `200`.
- **Auth:** `with-key:200`. The bad-key `401` was sampled **45 times** on the host (30 no-key, 15
  wrong-key) — **45/45 clean `401`s, zero resets.** This settles the recorded Windows socket-reset
  flake: it is a **client artifact of the dev machine**, not the server's unauthorized path, so the
  health check's `401` assertion is reliable here. The `http_server.py` body-drain fix drops to
  unscheduled cleanup.
- **Task 24 step 3, `say_text` regression:** `ok=True said=True likely_silent=False replayed=True`,
  volume restored `0.4`, `library://radio/4` replayed, mic `off`. Operator heard it.
- **Task 24 step 4, announce with the ceiling paused:** `ok True`, `chat Announced.`,
  `announced True`, `chime {played: True}`, `mic {muted: True, confirmed: True}`,
  `volume_restore restored`, both clips `started`/`issued`. Mic mute **confirmed after 2 polls**
  (consistent with the 255 ms measured at AN-2); mic dead-man armed at **184 s** and correctly did
  **not** fire; volume returned to `0.4`; `resume` replayed the captured station.
- **The signed-URL redaction works live.** The chime's finish-poll line reads
  `…timer_chime.wav?authSig=R` — that is `authSig=REDACTED` cut by the 80-char truncation. The
  credential never reached the log, which is exactly what the post-G1 correction required.

### The failure — requirement 7

Step 4's `/command` call took **52.7 s** for a 17-character sentence. From the log:

```
17:10:18.433  SAY start … reply_volume=0.8
17:10:25.060  clip=f3ff7804 finish-poll exit after 6.0s: state=idle      <- the chime, clean
              … 45.8 s with no log line at all …
17:11:10.907  restored -> 0.4
17:11:10.908  mic restored
```

**Cause.** MA wraps by media type. The chime is `builtin://track/…` and reaches `state=idle` when it
ends. The Piper clip is wrapped **`builtin://radio/…`** — a *stream*, which never reports an end, so
the player stays `state=playing` on that cid indefinitely. A read taken 4 s **after** the call
returned still showed
`playing | 0.4 | builtin://radio/http://192.168.122.10:8123/api/tts_proxy/H65P50….mp3`.

`_play_clip_and_wait`'s finish poll can exit three ways: two consecutive `ended` observations (never
happens for a stream-wrapped clip), the blank-cid grace (`say_blank_cid_grace_ms`, 8 s — what
`say_text` actually relies on; step 3 logged `cid stayed empty for 8.0s`), or the budget. Here the cid
never blanked, so the budget was the only exit. **`announce_message_finish_timeout_ms` (45 s) is not a
cap on a detected end; for the message clip it *is* the duration.**

**Why this is a requirement-7 failure rather than slowness.** The mute is released in `_announce`'s
`finally`, after `_say` returns. So:

- the satellite microphone was muted **~53 s** for ~2 s of speech;
- the ceiling was held at announce volume **0.8 for ~45 s after the speech ended**;
- anyone talking to the satellite in that window is **not heard, with no indication why**.

A fail-safe 25× wider than what it protects is not calibrated.

**Observability gap, separately.** A finish poll that exhausts its budget **logs nothing** — only the
ended-twice and blank-grace exits log. The operator sees `SAY start`, a 45 s hole, then `restored`.
This was diagnosable only by subtracting timestamps. The budget exit needs a warning line carrying the
clip and the elapsed time, whatever else is decided.

### Not run, and why

Task 24 steps 5–8 (announce over music, two-announcement supersession, the timed 300-char
announcement, the self-wake pipeline trace) were **not run**. Each would incur the same 45 s, and step
6 would compound it. Validation stopped at step 4 by the operator's instruction to stop on failure.

A hypothesis for whoever resumes, untested: over *music* `was_playing` is true, so the source is
replayed and the cid changes — the poll may exit properly, which would make this specific to the
not-playing case.

### State left behind

Ceiling `playing library://radio/4` at `0.4`, satellite `idle`, mic mute `off`, resolver `active`, no
tracebacks. The operator's station was captured before the test and restored after. Nothing stranded.
**Live lane released.**

**G4a/G4b remain blocked.** Sentence triggers would expose a 53 s mute to the household. A fix
proposal (reliable completion detection via `media_duration`/`media_position`, versus the current
budget fallback, with focused tests and a redeploy plan) is prepared and awaiting review; nothing is
implemented.

### Process notes worth keeping

- **`scp`'s exit code proved nothing** — a `grep -v` in the pipeline masked it entirely, reporting
  `exit=1` on two successful copies. Compare sha256 end to end.
- **Do not spawn an `ssh-agent` per call.** 21 orphaned agents accumulated and held the tool's stdout
  pipe open, wedging four consecutive calls after the ssh had already finished. One detached agent
  writing to a file, killed on exit, works. Direct `ssh -i` still fails as the runbook records, and the
  Windows `ssh-agent` service is Disabled.
- `test_py35_compat.py` was deployed alongside the four planned test modules; running the
  compatibility guard on the real 3.5.2 target is worth more than running it on the dev machine's 3.12.

## 2026-09-07 — normalise the legacy `platform:` trigger key across the remaining six automations

> Eight `"platform"` → `"trigger"` renames in six managed automations. **No behaviour change of any
> kind** — the point is that the *next* automation edit produces a readable diff.

- **Live gate.** Claimed for this migration on `homebrain/automation-trigger-key-migration` after the
  AN-01 owner confirmed G1 complete and released it; released again on merge. Recorded here rather
  than in `BACKLOG.md` by deliberate choice. The work is disjoint from AN-01: its only Home Assistant
  write target is `automation.voice_ceiling_speakers`, which this change does **not** touch.
- **Why now.** PR #46 established that saving *any* automation through the HA UI rewrites the whole
  config to the current schema, so a one-line intended edit arrived with eight unrequested rename
  hunks attached. Every remaining managed automation carried the same latent cost. Doing them
  deliberately, in isolation, means the renames are reviewed once on their own terms instead of
  ambushing an unrelated review later.
- **Method: save-only.** Each automation was opened in the UI's YAML editor and saved with **no text
  edited**. The save alone triggers the normalisation; that *is* the migration.
- **Scope, and one deliberate exclusion.** `automation.voice_ceiling_speakers` was normalised in
  PR #46 and is untouched here — it is the target of AN-01's Task 26 and the subject of its G4b
  rollback, so it stays out of any unrelated change.

| Automation | Renames | Trigger platform values |
|---|---|---|
| `1784146586` (S1a - Satellite Ceiling Duck/Restore) | 2 | `state`, `state` |
| `ma_auto_reload` (MA: auto-reload after restart) | 2 | `homeassistant`, `state` |
| `1784200731` (S1b-2 - Satellite Reply on Ceiling) | 1 | `event` |
| `lidarr_ma_sync` (Lidarr import -> MA sync) | 1 | `webhook` |
| `ma_health_probe` (MA: health probe auto-reload) | 1 | `time_pattern` |
| `satellite_timer_announce` (Satellite timer - announce) | 1 | `state` |

- **These are not all `conversation` triggers.** PR #46's audit restricted the rename to values equal
  to `"conversation"`; that rule would have been wrong here. The eight span five platform values, so
  the audit had to accept any value and separately assert the value was **preserved**.
- **Twenty-two changed lines, not sixteen.** Canonical output sorts keys and `trigger` sorts after
  `to`, where `platform` sorted before it. In `1784146586` (both triggers) and
  `satellite_timer_announce` the key therefore moves position and the adjacent line's trailing comma
  moves with it. Predicted in advance precisely so it would not read as an anomaly in review.

### Verification: the expected output was computed before Home Assistant was touched

- **Byte-exact prediction, offline.** The exporter's `render()` (`sort_keys=True`,
  `ensure_ascii=False`, `indent=2`, trailing newline) was replicated locally and applied to the
  committed files with the rename as the only transform, producing six predicted digests **before any
  UI save**. All six exports matched them exactly. A prediction made before the change cannot be
  retro-fitted to agree with a mistake — this is the guard that a fixture written after the fact does
  not give.
- **Pre-change gate.** `--strict-inventory`, exit 0, 37 files, zero diff against `main` at `d520da7`.
- **Post-change audit, four independent checks.** (A) exactly 6 of 37 files differ; (B) each is one of
  the six intended; (C) each matches its offline-predicted digest; (D) transforming each committed
  file by the rename alone reproduces the exported file exactly, with 0 `platform` keys left. 8/8
  renames, 0 failures.
- **Line counts unchanged in all six; −8 bytes total**, one per rename (`"platform"` is 8 characters,
  `"trigger"` is 7).
- **Checked for other legacy keys and found none** — all six already used the modern `action:`,
  `triggers:` and `actions:` spellings, so `platform:` was the only thing HA rewrote. The `webhook`
  trigger in `lidarr_ma_sync` was watched specifically in case saving re-registered it; it did not.

## 2026-09-07 — `play_radio` routes through the resolver; the other half of drift detection is now tested

> The bare "play the radio" branch stopped bypassing the resolver. It was the last hardcoded station
> in the automation layer, and fixing it doubled as the first real test of *change something in HA,
> re-export, and see exactly that change* — the half of INF-09 that had never been exercised.

- **The defect was routing, not a wrong default.** Every other branch of
  `automation.voice_ceiling_speakers` calls the resolver; `play_radio` alone called
  `music_assistant.play_media` directly with a literal `"Radio Paradise"` and an explicit
  `media_player.ceiling_speakers` target. Meanwhile `radio.py:130-133` carries a comment written for
  exactly this case — *"A bare 'play radio' has no station: fall back to the configured default"* —
  and it was unreachable from the automation. Swapping the literal to `101 SMOOTH JAZZ` would have
  reset the drift, not removed it, so the branch now calls `script.play_radio` with no fields and
  lets `default_station` answer. The speaker is unchanged: the resolver takes the zone from
  `ceiling_entity`, which is the same entity the explicit target named.
- **Exporter redeployed first.** The host was still on `8d1d030a…` (commit `8f6a003`) while the repo
  had moved to `21ee0ab0…` (commit `e1a155f`, the `/api/states` row guard merged in PR #44). Running
  a drift test on a superseded build would have proved nothing about the build under review. Backup
  `~/mass-resolver/.bak/20260907-224131/tools/ha_export.py` (digest verified equal to the file it
  replaced), deploy, digests compared with `tr -d ''` on both sides, `py_compile` OK on Python
  3.5.2. **The `/api/states` guard was previously untested against live data; it accepts the
  instance.** The hardened build also reproduced the baseline byte-for-byte, so the guard changed no
  output.
- **Gated on a clean pre-change export.** `--strict-inventory`, exit 0, 37 files, **zero diff against
  the committed blobs**. Without that, a post-change diff cannot be attributed to the change.
- **Result: exactly one canonical file changed**, `automations/voice_ceiling_speakers.json`
  (`4b52bcf9…` → `8fda1446…`, 347 → 340 lines). 36 of 37 byte-identical. The drift-detection premise
  holds in both directions now.

### Home Assistant rewrites the schema on every UI save

- **The one intended edit produced nine hunks, not one.** Eight of them are
  `"platform": "conversation"` → `"trigger": "conversation"` on every conversation trigger in the
  file. Nothing typed by hand touched those lines: saving an automation through the UI normalises the
  whole config to the current schema, and HA renamed the trigger key some versions back.
- **Audited rather than assumed.** The before-file was transformed programmatically by only those two
  changes (the action replacement, and `platform`→`trigger` restricted to values equal to
  `"conversation"`) and compared to the exported after-file: **exact equality**. 1 replacement, 8
  renames, 0 `platform` keys left, 8 `trigger` keys present. The diff provably contains nothing else.
  The byte arithmetic agrees independently — the prediction for the intended change alone was 11,622
  bytes, the actual file is 11,614, and 8 bytes is precisely 8 renames of an 8-character key to a
  7-character one.
- **Behaviourally inert, but scope-relevant.** `trigger:` is the modern spelling HA itself emitted for
  2026.6.4; sentence triggers, IDs and ordering are unchanged. Accepted deliberately: the baseline
  must match what the instance actually contains.
- **The other six automations were deliberately NOT migrated.** They still carry **8 legacy
  `platform:` occurrences** between them (`1784146586` 2, `ma_auto_reload` 2, and one each in
  `1784200731`, `lidarr_ma_sync`, `ma_health_probe`, `satellite_timer_announce`). Consequence worth
  remembering: **a UI save on any managed automation is never a one-hunk diff** until those are
  migrated. That is now a known property of the workflow rather than a surprise mid-review.

### Live verification

- Spoken *"play radio"*. `req=c4dc0bc8`: `radio mode=play target='101 SMOOTH JAZZ' candidates=1` →
  `RADIO PLAY ACCEPTED by MA … uri=library://radio/2 source=favorite` → **`RADIO CONFIRM … is
  playing`** eight seconds later. Confirmed playing, not merely accepted.
- Two guards fired correctly and are visible in the same trace: the duck was skipped
  (*"this turn started library://radio/2"*) and the spoken reply suppressed (*"the reply would replace
  it"*), so the music starts without a confirmation talking over it.
- Resolver log lines appear for this phrase **for the first time** — the old branch never reached the
  resolver at all, which is the clearest evidence the routing changed.

## 2026-09-07 — INF-09 idempotency PROVEN: a fresh re-export is byte-identical to the committed baseline

> The hardened exporter deployed and re-exported to fresh paths. **Zero diff against the committed
> 37-file baseline.** This is the first time the drift-detection premise has actually been tested —
> everything before it only proved the exporter could *create* a snapshot.

- **Why this matters more than the exports that preceded it.** A baseline is only useful if
  re-running the exporter against an unchanged instance reproduces it exactly. Until now that was
  assumed. A zero diff establishes three things at once: the baseline is **reproducible**, there is
  **no churn** (no timestamps, no ordering instability, no runtime metadata leaking through), and the
  security hardening **changed no output** — the same bytes come out of a materially different build.
- **Sequence, each step gated and verified:**
  1. Host confirmed still on the pre-hardening exporter `25fc208e…` — which independently corroborates
     that the hardening was never deployed before this point.
  2. Backup `~/mass-resolver/.bak/20260907-124713/tools/ha_export.py` (digest verified equal to the
     file it replaced), then deploy `8d1d030a67a7a18e…` from commit `8f6a003`. Local and host digests
     compared explicitly; `py_compile` OK on Python 3.5.2.
  3. **A fresh `--probe-only` BEFORE any export** — the hardened validator is stricter and the
     deployed manifest was unchanged, so this separates *"the new build still accepts the manifest"*
     from *"the output is unchanged"*. Exit 0, nothing written.
  4. `--strict-inventory` export to `staging-managed-idem` / `staging-raw-idem`. Exit 0, 37 files.
- **Comparison was made against the committed blobs** (`git show HEAD:<path>`), not the working tree
  or the earlier staging directory — the baseline that actually matters is the one in the repository.
  **37/37 byte-identical.**
- **Everything else verified unchanged:** raw tree `0700` with all 32 files `0600`; the two earlier
  staging trees byte-identical *and* mtime-identical (`staging-managed` 2026-09-06 20:04,
  `staging-managed-expanded` 2026-09-07 07:50); no `.tmp-*` or `*.prev-*` residue; the baseline output
  paths `~/ha-state/managed` and `~/ha-state/raw` still absent.
- **Still untested:** the other half of drift detection — *change something in HA, re-export, and see
  exactly that change and nothing else*. That test should ride on the `play_radio` fix rather than a
  synthetic edit.

## 2026-09-07 — INF-09 exporter hardened after a post-baseline code review (deployed later the same day)

> Security and fail-closed hardening found by reviewing the committed exporter, plus the review
> fixes applied on top. **Offline only — Home Assistant was not contacted and nothing was
> deployed.** The repo and host exporters now disagree, so a redeploy and a fresh `--probe-only`
> must precede the planned idempotent re-export.

**Hardening (`a764ee8`)**

- **Manifest entries are validated as safe identifiers.** They become *filenames* —
  `scripts/<object_id>.json`, `satellite/<entity_id>.json`, `pipelines/<id>.json` — so a manifest
  entry of `../outside` would have written outside the output tree. `.`/`..`/`/`/`\`/NUL/control
  characters are now rejected with exit 1. This is the same lesson `url2pdf` already carries, where
  state names are restricted *"precisely because the name becomes a filename, and a `..` in it would
  write credentials outside that gitignore."*
- **`_note` is validated at runtime**, not merely pinned by a repo test. The type hole the earlier
  review identified is now closed by the tool refusing, rather than by the test suite knowing.
- **`write_tree` contains every output path** under its root — defence in depth behind the
  identifier check.
- **Malformed payloads fail closed:** a non-object script `fields`, or a non-object pipeline row,
  now exits **4** naming the resource instead of raising `AttributeError` into the generic
  unexpected-error path.
- **`/api/states` rows are guarded too** (added while drafting the PR, when the claim that this
  already existed turned out to be false). The hardening had covered pipeline rows and script
  `fields` but left the *first* payload the exporter touches unchecked, where a non-dict row raised
  `AttributeError` and surfaced as exit 7 "unexpected" — naming nothing. It now exits **4** with the
  offending index, `/api/states[<n>]`. Validation-only: no live re-export was needed, since the
  change cannot alter the output of a well-formed response.

**Review fixes applied on top**

- **Removed a duplicated pipeline-row check.** The same validation had been added in both
  `collect()` and `build_canonical()`, with two different messages for one condition — the pattern
  this workstream deliberately moved away from when exposure unwrapping was consolidated to a single
  boundary. Row shape is now validated **once, at ingestion**, and the canonical builder trusts it.
- **A path-containment failure is no longer `EXIT_USAGE`.** Every filename component has already
  passed `validate_identifier` by the time anything is written, so an escape there is a broken
  internal invariant, not something the operator typed. Reporting it as a usage error would send
  someone to check their command line for a bug in the exporter. It now raises a plain exception
  down `main()`'s unexpected-error path, with a regression test asserting it is **not** an
  `ExportError`, plus a guard-rail test that ordinary nested paths still work.
- **Documented a deliberate choice that was previously unstated:** pipeline row validation covers
  **every** row, including pipelines the manifest does not manage. A malformed row we would not
  export still means the endpoint returned a shape we do not understand, and a snapshot taken
  against a half-understood response is not one to trust — so the whole export fails rather than
  quietly skipping the row.

**Verification:** exporter suite **114 tests**, full suite **490**, true exit status captured. The
committed 37-file baseline is untouched by any of this. `ONBOARDING.md` now points at the runbook,
the exporter, the manifest and the `ha/` baseline from both §5 and §14 — the runbook had been
undiscoverable from the doc operators are told to read first.

## 2026-09-07 — INF-09 BASELINE established: the Home Assistant app-layer surface is now under version control

> **The Home Assistant half of HomeBrain is no longer untracked.** 37 canonical JSON files,
> **41,604 bytes**, committed under `docs/homebrain/ha/`. Every one is byte-identical to the reviewed
> `staging-managed-expanded` tree, which was produced by a `--strict-inventory` export that exited 0.
> **Raw snapshots were not copied and never will be**; the staging trees stay on the host.

- **What is now diffable:** 16 scripts (including the `fields` descriptions that *are* the LLM tool
  schema), 7 automations with their sentence triggers, 5 Assist pipelines plus `_preferred`, 6
  satellite `select` settings, the conversation exposure set, and `meta.json` recording HA
  **2026.6.4**. A live change to any of these now produces a reviewable diff instead of vanishing.
- **`--strict-inventory` exited 0**, which is positive evidence rather than an absence of complaints:
  strict mode fails on any undeclared member of the four discoverable inventories, so a clean run
  confirms all 34 collection entries are declared.
- **Reviewed before committing, not after.** All 37 files read — verbatim for the five largest and
  the structural ones, per-file signature pass over the rest. All parse, **CR=0 everywhere**, trailing
  LF everywhere, byte-identical to staging, and the exporter's own secret scanner returned **0
  findings** across all 38 files.
- **`1784146586` and `1784200731` are `S1a - Satellite Ceiling Duck/Restore` and `S1b-2 - Satellite
  Reply on Ceiling`.** Opaque numeric ids that HA assigns to UI-created automations; the baseline
  makes them legible. Their descriptions — and `satellite_timer_announce`'s, which records the 180 ms
  wake-sound race and why its idle condition is load-bearing — are now version-controlled rather than
  living only in this changelog.

### Four findings the baseline surfaced immediately — recorded, deliberately NOT fixed

1. **`play_radio` branch vs resolver default disagree.** The `play_radio` *branch* of
   `automation.voice_ceiling_speakers` hardcodes `media_id: "Radio Paradise"` straight to
   `music_assistant.play_media`, bypassing the resolver — while `radio.json` sets
   `default_station: "101 SMOOTH JAZZ"`. So *"play the radio"* and the resolver's own default point at
   different stations.
2. **Two dead `tts.speak` paths.** `script.ceiling_announce` (its only step) and
   `script.ceiling_play_radio` (step 2) both call `tts.speak`, which is recorded as *proven broken*
   on this player (MA `play_announcement` needs correct state/elapsed reporting; Universal→Squeezelite
   does not provide it). Neither script is exposed to the assistant, so nothing calls them — but they
   are dead on arrival and the baseline now shows it.
3. **Exposure surface is 14 entities** — 13 scripts plus `weather.forecast_home`, and **no
   `media_player.*` entity is exposed.** That is exactly the assertion `assistant-capabilities.md`
   §NL-02 step 5 asks an operator to verify by hand; it is now recorded as data. The three unexposed
   scripts are `ceiling_announce`, `ceiling_play_music`, `ceiling_play_radio`, consistent with the
   resolver routes having superseded them.
4. **Pipeline `tts_voice` is captured for the first time:** `en_US-amy-low` on all three Living Room
   pipelines, `null` on `Home Assistant` and `ChatGPT`. This is the missing datum for the open
   "unify the assistant voice" item — the resolver's `say_text` passes an *engine* only and therefore
   gets Piper's default, which this shows is not necessarily `amy-low`.

> **Not a problem, recorded so nobody "fixes" it:** the `voice_ceiling_speakers` alias renders as
> `Voice ? Ceiling Speakers` in a cp1252 console. The file is correct — it contains the UTF-8 em dash
> (`e2 80 94`), no replacement characters, and decodes as strict UTF-8.

## 2026-09-07 — INF-09 strict expanded STAGING export: exit 0, 37 files, 41 KB (not yet the baseline)

> Second staging export, at the full operational boundary and with **`--strict-inventory`**. Written
> to new paths (`staging-managed-expanded` / `staging-raw-expanded`); **the 2026-09-06 17-file
> staging result was left untouched**. Nothing copied into the repository — the baseline is a
> separate gate.

- **Result:** exit **0**, `HA 2026.6.4  exported 37 files`, empty stderr, **no unmanaged output**.
- **`--strict-inventory` passing is itself the proof that nothing is unmanaged.** Strict mode exits 5
  if any of the four discoverable inventories has an undeclared member, so a clean run confirms all
  34 collection entries are declared — and independently confirms the `cloud.alexa` correction: had a
  real unmanaged assistant existed, this run would have failed.
- **37 canonical files, 41,604 bytes**, exactly the predicted shape:

  | Area | Files | |
  |---|---|---|
  | `scripts/` | 16 | |
  | `automations/` | 7 | |
  | `pipelines/` | 6 | 5 pipelines + `_preferred.json` |
  | `satellite/` | 6 | |
  | `exposure/assistants.json` | 1 | |
  | `meta.json` | 1 | |
  | **total** | **37** | 0 non-JSON files |

  All parse; **CR=0 everywhere; trailing LF everywhere.**
- **Size, and a corrected estimate.** 41,604 bytes — I had estimated 60–100 KB and was roughly
  double the truth. Doubling the resource count roughly doubled the export (21,114 → 41,604), and the
  distribution improved: `voice_ceiling_speakers.json` fell from **56% to 28.5%** of the total, so a
  single automation no longer dominates every diff. Largest five: `voice_ceiling_speakers` 11,860 B,
  `satellite_timer_announce` 3,242 B, `play_radio` 2,517 B, `ceiling_play_music` 2,054 B,
  `1784146586` 1,713 B.
- **Raw snapshot:** root and run directory `drwx------ 700`, **32 files all mode `600`**, one run
  directory. Contents neither read nor copied. No `.tmp-*` or `*.prev-*` residue.
- **The earlier staging result is provably untouched:** `staging-managed` still 17 files / 21,114
  bytes, `staging-raw` still 1 run dir / 15 files, and **every mtime in both still reads
  `2026-09-06 20:04`**. Both deployed digests unchanged (`4113f173…`, `25fc208e…`).

## 2026-09-07 — INF-09 expanded probe passes: all 34 collection entries validate, nothing unmanaged remains

> Single `--probe-only`, exit **0**, read-only, wrote nothing. No `--strict-inventory`.
> **No full export at the expanded scope yet** — that is a separate gate.

- **Result:** `HA 2026.6.4  PROBE OK (nothing written)`, empty stderr, and — new — **no unmanaged
  lines at all**. Every one of the four discoverable inventories is now fully declared.
- **What this validated for the first time:** the **20 newly managed** envelopes (11 scripts, 6
  automations, 3 pipelines) through `check_envelope`, and the secret scan across the whole expanded
  surface rather than the original 6 resources. The schema pre-recording predicted every key would
  already be inside the allowlists, and the probe confirms it: **no exit 4**.
- **Secret scan: no findings across all 34 entries.** Stated precisely: that establishes only that
  **nothing in the currently captured state tripped any detector**. `lidarr_ma_sync` and
  `ma_health_probe` were the resources most likely to carry an API key or webhook URL; neither did.
- **`cloud.alexa` does not exist on this instance — it is a TEST FIXTURE, not live data.** The
  Gate 3 structural probe recorded exactly **one** assistant key in the live exposure response
  (`conversation`, across 14 entities). `cloud.alexa` appears only in `test_ha_export.py`, where it
  was added deliberately so the assistant-filtering and strict-mode isolation tests would have a
  second assistant to filter *out*. Consequence: there are **no unmanaged exposure assistants**
  live, and `--strict-inventory` would now pass cleanly on all four inventories.
- **Post-conditions verified:** `~/ha-state/managed` and `~/ha-state/raw` still absent; the
  2026-09-06 staging trees byte-identical (`staging-managed` 17 files / 21,114 bytes, mtime still
  `2026-09-06 20:04`; `staging-raw` 1 run dir / 15 files); no `.tmp-*` residue; both deployed
  digests unchanged (`4113f173…`, `25fc208e…`).

## 2026-09-07 — INF-09 expanded manifest deployed (manifest only; exporter untouched, not invoked)

> Gate 1, manifest-only. **`ha_export.py` was neither rebuilt nor recopied** — the read-only schema
> probes showed every observed key across all 16 scripts and 7 automations already sat inside its
> existing allowlists, so the expansion needed no code change. **No exporter invocation in this
> gate**, and the staging trees from 2026-09-06 were left exactly as they were.

- **Scope now deployed:** the complete HomeBrain operational boundary — **34 collection entries**
  (16 scripts, 7 automations, 5 pipelines, 6 satellite selects), of which **20 were newly managed**:
  11 scripts, 6 automations, 3 pipelines. All 6 satellite entities were already declared.
- **Pre-check:** the host manifest still had digest `c2e72f99…`, the value recorded at first
  bootstrap — no drift in between.
- **Digests**, `sha256` with `tr -d '\r'` on both sides, source commit
  `431f80b87689d6e864aa33dc8621a43356f25721`:

  ```
  old (replaced)  c2e72f998cd3bd8daf701e62d21260f86020101c137a5825e5c4d1b1fe76255a  ha-state/MANIFEST.json
  new (deployed)  4113f173ca9de9e4ee0bee0b35c7c9ed5aee99acde72501840fb3ac72bd29254  ha-state/MANIFEST.json
  unchanged       25fc208e081028bf0ee4aa3ebf49094bce223bca4f95367a721c67aec430efb7  tools/ha_export.py
  ```

  **Local and host digests were compared explicitly and matched.**
- **Backup:** `~/mass-resolver/.bak/20260907-073248/ha-state/MANIFEST.json`, digest verified equal to
  the file it replaced. Rollback pointer.
- **Verified under host Python 3.5.2:** parses, 16/7/5/6 entries all unique, `_note` is a `str`,
  `include_preferred_pipeline=True`, `exposure_assistants=['conversation']`, pin `'2026.6.4'`.
- **Staging trees untouched:** `staging-managed` still 17 JSON files, `staging-raw` still 1 run
  directory.
- **Transport was verified before writing**, per the lesson recorded on 2026-09-06: three fresh
  publickey-only connections each returning a unique marker with exit 0, multiplexing disabled. A
  write is not attempted over a link that cannot reliably return command status.

## 2026-09-06 — INF-09 first STAGING export (exit 0, 17 files, 21 KB) — explicitly NOT the baseline

> **A staging export, not the authoritative baseline.** The manifest is intentionally
> under-inclusive, so this output is for review and sizing only. Written to dedicated,
> previously-absent paths — `~/ha-state/staging-managed` and `~/ha-state/staging-raw` — and
> **nothing was copied into the repository.** Both staging trees are left in place deliberately.

- **Result:** exit **0**, `HA 2026.6.4  exported 17 files`, empty stderr. Both staging paths were
  confirmed absent beforehand, and the deployed exporter (`25fc208e…`) and manifest (`c2e72f99…`)
  digests were re-verified against their recorded values first.
- **Canonical output: 17 JSON files, 0 non-JSON, 21,114 bytes total.** Every file parses as JSON,
  every file has **CR=0** and a trailing LF — so the scoped `eol=lf` rule and the LF-only writer both
  work end to end, and a repo↔host comparison will not report phantom differences.

  | Area | Files | Notable |
  |---|---|---|
  | `automations/` | 1 | `voice_ceiling_speakers.json` at **11,860 B — 56% of the whole export** |
  | `scripts/` | 5 | `play_radio.json` 2,517 B (the tool-schema surface), `find_stations` 1,351 B |
  | `satellite/` | 6 | 239–308 B each |
  | `pipelines/` | 3 | 2 pipelines + `_preferred.json` |
  | `exposure/` | 1 | `assistants.json` 929 B |
  | `meta.json` | 1 | 58 B |

- **Plan assumption #7 is answered: ~21 KB total.** That is a genuinely reviewable diff, not a dump —
  which was the open question. The one automation is over half of it, so a change there will dominate
  any future diff; that is correct, since it is also where the behaviour lives.
- **Raw snapshot permissions verified:** root and run directory both `drwx------ 700`, all 15 raw
  files `-rw------- 600`, one run directory. **Raw contents were neither read nor copied** — only
  names and modes were inspected. No `.tmp-*` residue anywhere.
- **Unmanaged, reported not exported:** 11 scripts, 6 automations, 3 pipelines (unchanged from the
  probe). **The next decision is which of the load-bearing ones belong under change control** —
  `satellite_timer_announce`, the `ma_auto_reload`/`ma_health_probe` self-healing pair, and the
  exposed `news`/`play_music` tools are the obvious candidates.
- **Capacity note, not implicated in anything here:** host `/` is at **86% used, 15 GB free**. Ample
  for an export of this size; recorded for monitoring, no cleanup taken.

## 2026-09-06 — SSH hangs traced to a lost agent key, not the host: a fallback that blocks instead of failing

> Read-only diagnosis. No host change, no service restart, no configuration edit.

- **Symptom:** remote commands intermittently returned nothing and `timeout` killed them
  (`exit 124`), while other attempts succeeded. One earlier compound step died with a bare `exit 1`
  after its output vanished, leaving it genuinely unclear whether a `cp` had run.
- **The host was never the problem.** `load 0.06 0.08 0.06`, uptime 68 d, 2.6 GB memory available,
  **zero `D`-state processes**, `sshd` accepting TCP on :22 instantly, and the HA VM answering
  **HTTP 200 in 21 ms** — which also proves host networking and KVM were healthy, since that VM runs
  on this host.
- **Root cause:** the ssh-agent had lost `id_homebrain`, so **publickey authentication failed and
  SSH fell back to password**, which in a non-interactive shell **blocks trying to open `/dev/tty`**
  to prompt. That presents as a hang, not a denial — the single most misleading failure shape
  available. Intermittent successes were most consistent with a lingering multiplexed connection.
- **The diagnostic that made it visible instantly:**
  `ssh -o BatchMode=yes` → `Permission denied (publickey,password)`, 4/4, immediately. **Use that
  before suspecting the network:** with prompting disabled an auth failure fails fast and says so.
  `ssh -vvv` corroborated it with `Next authentication method: password`.
- **Fix (client-side only):** `ssh-add ~/.ssh/id_homebrain` into the **existing** agent. Do **not**
  wrap it in `eval "$(ssh-agent -s)"` — doing that earlier in this workstream leaked 13 agent
  processes and made `ssh-add` itself begin hanging.
- **Verification that should gate any write over SSH:** three *fresh* connections, each returning a
  unique marker with exit 0, using `BatchMode=yes -o PasswordAuthentication=no
  -o KbdInteractiveAuthentication=no -o PreferredAuthentications=publickey -o ControlPath=none`.
  Multiplexing off matters — otherwise a reused master connection hides a broken authentication path.
- **Lesson:** a write was correctly *not* attempted while the transport could not reliably return
  command status. An intermittent transport is more dangerous than an outage: an outage stops you,
  whereas an intermittent one invites a retry that appears to work and leaves the previous attempt's
  effect unknown.

## 2026-09-06 — INF-09 probe passes: the managed HA surface validates end to end (still no export)

> Third `--probe-only`, exit **0**. Read-only, wrote nothing. **No full export has ever run**; that
> remains a separate gate.

- **Result:** `HA 2026.6.4  PROBE OK (nothing written)`, empty stderr, `~/ha-state/managed` and
  `~/ha-state/raw` both absent afterwards. No version warning (the instance matches the manifest
  pin) and no exposure warning.
- **Validated live:** both undocumented config routes for all 5 declared scripts and the 1 declared
  automation; every resource envelope (scripts, automation, 2 pipelines, 6 satellite selects); the
  pipeline-list wrapper; and the exposure wrapper with its boolean leaves. Plan assumptions #1–#4
  are resolved — the two earlier probes each failed on one of them (#3 exposure shape → exit 5,
  #2 pipeline `language` → exit 4).
- **The secret scan executed and found nothing.** Stated precisely: that establishes only that
  **nothing in the currently captured state tripped any detector**. It does not establish that a
  managed resource cannot embed a secret, nor that a differently-shaped secret would be caught.
- **Unmanaged resources reported** — present in HA, deliberately not exported, manifest
  under-inclusive by design until extended:
  - **11 scripts:** `ceiling_announce`, `ceiling_next`, `ceiling_play_music`, `ceiling_play_radio`,
    `ceiling_previous`, `ceiling_resume`, `ceiling_set_volume`, `ceiling_volume_down`,
    `ceiling_volume_up`, `news`, `play_music`
  - **6 automations:** `1784146586`, `1784200731`, `lidarr_ma_sync`, `ma_auto_reload`,
    `ma_health_probe`, `satellite_timer_announce`
  - **3 pipelines**
  Several matter to this workstream — `satellite_timer_announce` is the timer automation,
  `ma_auto_reload`/`ma_health_probe` are the A1/A2a self-healing pair, and `news`/`play_music` are
  exposed resolver tools. Whether to bring them under change control is a separate decision.
- **Still unresolved:** satellite `select.*` id **stability** across a firmware or integration update
  (they exist now; durability is a future-time property no probe can test), and total sanitized
  output size (nothing has been written yet).

## 2026-09-06 — INF-09 exporter re-deployed after the pipeline-schema remediation (one file; no invocation in this gate)

> Gate 1, third pass. **Only `ha_export.py` copied; `MANIFEST.json` deliberately not recopied.**
> **No exporter invocation occurred during this deployment gate** — no Home Assistant access, no
> restart. (**Correction, applied 2026-09-06:** this entry originally read "the exporter has still
> never been executed", which was false — two `--probe-only` runs had already happened by this
> point. They wrote nothing, but they did run and did contact Home Assistant. **No full export has
> ever run.**)

- **Why:** the second `--probe-only` exited 4 on an unknown pipeline envelope key. A read-only
  structural probe recorded the complete 13-key pipeline schema (see the plan §11.2) rather than just
  the one key the error named — which also proved no 14th key was waiting behind it. `language` was
  added, all 13 fields preserved including nullable `tts_*`, and pipelines gained an unmanaged
  reporting path.
- **Pre-check before replacing anything:** the deployed digest was confirmed to still equal
  `b9dc29781f325ca1…`, the value recorded at the previous deployment. No drift on the host.
- **Digests**, `sha256` with `tr -d '\r'` on both sides, source commit
  `e884f48c69913106aa27eb932765df0cab075629`:

  ```
  old (replaced)  b9dc29781f325ca1e16ab9dddc35209519adea5a4fde3d9757665f6115ee48e7  tools/ha_export.py
  new (deployed)  25fc208e081028bf0ee4aa3ebf49094bce223bca4f95367a721c67aec430efb7  tools/ha_export.py
  unchanged       c2e72f998cd3bd8daf701e62d21260f86020101c137a5825e5c4d1b1fe76255a  ha-state/MANIFEST.json
  ```

  **Local and host digests were compared explicitly and matched.**
- **Backup:** `~/mass-resolver/.bak/20260906-192243/tools/ha_export.py`, digest verified identical to
  the file it replaced. Rollback pointer.
- **Host verification:** Python **3.5.2**, `py_compile` → `COMPILE_OK` (compiles, does not execute).
  `~/ha-state/managed` and `~/ha-state/raw` both still absent.
- **Operational note:** the first attempt at the combined pre-check-and-backup step died with a bare
  exit 1 and no output — an SSH transport failure, not a host problem. **Nothing partial had
  happened:** re-checking read-only showed the digest unchanged and no new backup directory created.
  The step was then re-run split into smaller calls. Worth recording because a bare exit 1 from a
  compound remote command tells you nothing about how far it got — verify state before retrying.

## 2026-09-06 — INF-09 exporter re-deployed after the exposure-shape remediation (one file; no invocation in this gate)

> Gate 1, second pass. **Only `ha_export.py` was copied; `MANIFEST.json` was deliberately not
> recopied** because it is unchanged. **No exporter invocation occurred during this deployment
> gate** — no Home Assistant access, no restart or reload. (**Correction, applied 2026-09-06:** this
> entry originally read "the exporter has still never been executed", which was false — one
> `--probe-only` run had already happened, exiting 5. It wrote nothing, but it ran and contacted
> Home Assistant. **No full export has ever run.**)

- **Why:** the first `--probe-only` exited 5 claiming the declared exposure assistant was absent.
  A read-only structural probe established the live shape and proved the exporter, not the manifest,
  was wrong — it assumed the result *was* the entity map with `{"should_expose": bool}` leaves, when
  2026.6.4 returns `{"exposed_entities": {<entity_id>: {<assistant>: bool}}}`. See
  `plans/2026-09-06-inf-09-ha-managed-state-exporter-plan.md` §11.3 for the recorded shape.
- **Digests**, `sha256` with `tr -d '\r'` applied on both sides, source commit
  `cc4ac86664bb26d961ad0f98c4af45a993643ac8`:

  ```
  old (replaced)  63d0a92ba1ad3deba62af959f547bf231487c500189820e67a383a1935fcd593  tools/ha_export.py
  new (deployed)  b9dc29781f325ca1e16ab9dddc35209519adea5a4fde3d9757665f6115ee48e7  tools/ha_export.py
  unchanged       c2e72f998cd3bd8daf701e62d21260f86020101c137a5825e5c4d1b1fe76255a  ha-state/MANIFEST.json
  ```

  **Local and host digests were compared explicitly and matched.** The old deployed digest was
  verified to still equal the value recorded at first bootstrap, so nothing had drifted on the host
  in between.
- **Backup:** `~/mass-resolver/.bak/20260906-184938/tools/ha_export.py`, confirmed byte-identical to
  the file it replaced. That is the rollback pointer.
- **Host verification:** `python3 -V` → **3.5.2**; `python3 -m py_compile tools/ha_export.py` →
  `COMPILE_OK` (compiles to bytecode, does not execute). `~/ha-state/managed` and `~/ha-state/raw`
  both still absent, confirming the exporter has produced no output. `tools/__pycache__` exists as
  the ordinary byproduct of `py_compile`.

## 2026-09-06 — INF-09 exporter bootstrapped to the host (deployment only; NOT yet run)

> Gate 1 of INF-09. Two files placed by hand and digest-verified. **The exporter has not been
> executed — no probe, no export, no Home Assistant access, no restart or reload.** Gate 2 (the first
> `--probe-only`) is a separate approval.

- **Why by hand:** the manifest-based resolver deploy does not exist yet, and `tools/` had never been
  deployed at all (`snapshot.py` is repo-only). Both destination directories were created first —
  `mkdir -p ~/mass-resolver/tools ~/ha-state` — because `scp` into a missing directory fails.
- **Deployed artefacts and their recorded identity.** `sha256`, computed on both sides with
  `tr -d '\r'` applied (mandatory: files authored from the Windows checkout carry CRLF, and a naive
  digest never matches), from branch `homebrain/inf-09-ha-export-plan` at `6801ce7`:

  ```
  63d0a92ba1ad3deba62af959f547bf231487c500189820e67a383a1935fcd593  tools/ha_export.py
  c2e72f998cd3bd8daf701e62d21260f86020101c137a5825e5c4d1b1fe76255a  ha-state/MANIFEST.json
  ```

  **Local and host digests were compared explicitly and matched on both files.** Until the
  manifest-based deploy subsumes this, that pair is the only recorded identity these artefacts have.
- **Host verification:** `python3 -V` → **3.5.2**; `python3 -m py_compile tools/ha_export.py` →
  `COMPILE_OK` (compiles to bytecode, does not execute); `MANIFEST.json` parses. Both directories
  contained exactly the one expected file and nothing else.
- **The manifest is seeded, not confirmed.** It names 5 scripts, 1 automation, 2 pipelines, 6
  satellite selects, `exposure_assistants: ["conversation"]` and `include_preferred_pipeline: true`,
  drawn from resources observed on 2026-09-06. Several were only ever seen as entity ids. If a name
  is wrong the first probe exits 5 — which is the designed way to find out.
- **Re-copy the manifest whenever it changes in the repo.** A stale host copy silently exports a
  different surface from the one under review.

## 2026-09-06 — Two voice defects fixed in live config: STT returning nothing, and "play russian songs" resolving to the wrong station

> **Live HA config only — none of this is in the repo**, so this entry is the record. Three changes:
> a satellite setting, a tool-schema rewording, and a new sentence trigger. No resolver code, no
> restart. Backups in `~/mass-resolver/.bak/` (`script-play_radio-*`,
> `automation-voice_ceiling_speakers-20260906-110846.json`).

**1. `finished_speaking_detection` `aggressive` → `default` — speech was not being transcribed at all.**

- **Symptom:** "play russian songs" did nothing. `resolver.log` showed a turn that ducked and
  restored with no command in between, and the ceiling never switched.
- **Diagnosis came from the pipeline trace, not the resolver log** (as §4 of ONBOARDING says it must):

  ```
  ts=2026-09-06T16:48:50  events: run-start,stt-start,stt-vad-start,stt-vad-end,error,run-end
  agent: ''   STT: ''   REPLY: ''
  ```

  No `stt-end`, no agent, no intent — the speech was never transcribed, so nothing downstream ran.
  Second occurrence the same hour (`16:15:18`, identical shape).
- **`aggressive` was set on 2026-09-05 as a false-wake mitigation, was measured then NOT to shorten
  captures, and was recorded at the time as the prime suspect for exactly this failure.** It ends the
  capture the moment it thinks you stopped, so a pause mid-phrase cuts it before enough speech is
  captured. Reverted to `default`; STT has worked on every turn since.
- **Lesson:** a mitigation that was measured to do nothing should have been reverted then, not left
  in place. It cost a day of confusing symptoms attributed to other layers.

**2 + 3. "play russian songs" played Радио Родных Дорог, not Радио Русские Песни.**

- **Cause:** the model was sending `country='Russia'` and dropping "songs". `russian songs` has been
  a favourite handle all along (`say_as`, added 2026-09-05) — the resolver would have matched it
  exactly; the phrase just never reached it intact.
- **First fix, insufficient on its own: the tool schema was steering it wrong.** `script.play_radio`
  offered *"Country or nationality, e.g. Romania or **Russian**"* as the `country` example, while
  `station` said only *"Station name (optional)."* Reworded: `station` now lists all 17 handles and
  states that `russian songs` and `russian radio` are two different stations; `country` no longer
  uses "Russian" as its example. **The model still chose `country`** on the next attempt
  (`11:02:48 target='Russia'`) — it can see `station` and uses it routinely (`'101 SMOOTH JAZZ'`,
  `'hit fm'`, `'noroc'` all appear in the log), but "russian **songs**" reads as a nationality to it.
  The rewording was kept: it is still an improvement for phrasings outside the 17.
- **Second fix, decisive: take the model out of the loop.** `favorites.resolve_alias` matches on a
  substring, not whole-string equality, so the *entire sentence* resolves correctly — verified
  offline before changing anything:

  ```
  play russian songs             -> Радио Русские Песни
  play the russian songs station -> Радио Русские Песни
  jazz                           -> jazz            (genre path untouched)
  romanian radio                 -> romanian radio  (country path untouched)
  ```

  So a new `play_favorite` conversation trigger on `automation.voice_ceiling_speakers` carries 34
  sentences (`play [the] X` / `put on [the] X` for each of the 17 handles) and hands
  `trigger.sentence` verbatim to `script.play_radio`. With `prefer_local=True` this wins before the
  LLM is consulted. The 17 favourites are now deterministic and skip the model round-trip entirely.
- **Verified live:**

  ```
  11:13:02  radio mode=play target='Play Russian songs.' candidates=1
  11:13:04  RADIO PLAY ACCEPTED 'Радио Русские Песни' uri=library://radio/4
  11:13:12  RADIO CONFIRM 'Радио Русские Песни' is playing
  ```

  Three independent signals: the sentence arrives **verbatim** (so the trigger fired, not the model),
  `candidates=1` instead of 5 (exact alias hit, not a country shortlist), and `cid` moved
  `library://radio/17` → `library://radio/4`.

## 2026-09-06 — Starting a station ducked it for seconds: the fresh-playback guard covered the reply but never the duck

> Resolver code + tests. Found from an operator report that a requested station "starts playing
> something else briefly, then stops, then a few seconds later the correct radio starts."

- **Symptom:** "play russian songs" — audio starts, seems to stop, then comes back properly several
  seconds later. Reproduced in the log on two different stations in the same minute.
- **Evidence** (`resolver.log`, the "russian songs" turn):

  ```
  10:37:32,323 RADIO PLAY ACCEPTED 'Радио Родных Дорог' uri=library://radio/17
  10:37:33,605 DUCK req=240ce63a 0.36 -> 0.15
  10:37:33,609 SAY  req=187ea1d5 SKIPPED: this turn started library://radio/17
  10:37:38,584 RESTORE req=848e2355 -> 0.36
  ```

  The station is ducked to 0.15 **1.3 s after it starts** and stays there **5.0 s**. Jazz at
  `10:38:21` did the same for 2.7 s.
- **Root cause:** the duck is making room for a reply that the very next line proves is skipped.
  `say_skip_on_fresh_playback` (decision (e), 2026-08) taught `_say` that a media command is
  confirmed by the action — but the guard was only ever applied to the **say** half. `_duck` can test
  the identical condition (`turn["playback"]`) and never did, so every media command paid for a reply
  that was never going to be spoken.
- **Fix:** `_duck` returns `ducked=False reason=fresh_playback` when this turn already started
  playback. No volume write, and no snapshot/dead-man timer left behind for the later restore to
  unwind. Kill switch: `duck_skip_on_fresh_playback`.
- **Tests:** 365 local (362 before), including a flag-off test that reproduces the blip on demand and
  a guard rail that an ordinary question over music still ducks. The fixture is shaped like the live
  turn — zone **idle** when the turn opens, which is what the two `no-op (not_playing)` ducks show;
  an earlier version of the test opened over a playing zone and asserted the wrong thing.
- **Verified live** on the turn that finally switched stations:
  `11:13:04 DUCK skipped: this turn started library://radio/4 (the reply is skipped too, so there is
  nothing to duck under)`.
- **The "something else" half of the report is explained, and it was not a defect.** 101 SMOOTH JAZZ
  is a Live365 stream that serves advertisements — the ceiling was observed reporting
  `title=Live365 - Advertisement  artist=Advert:`. The suspected buffered-reply-clip fragment was
  never real; no change was made for it.
- **A residual remains, deliberately not fixed.** The guard suppresses a *second* duck but does not
  release the *first*. When a turn opens over playing music, the turn-start duck (correct: the
  operator is speaking over music) survives until the restore, so a newly started station plays at
  0.15 for several seconds: `10:54:53 DUCK 0.36 -> 0.15` … `10:55:00 station starts` …
  `10:55:06 RESTORE -> 0.36`. The complete fix is for `note_playback` to restore the baseline
  immediately when a turn starts media and no reply is in flight. Offered and declined as good
  enough for now — **the six seconds are still there.**

## 2026-09-05 — "Stop the music" was undone by its own spoken confirmation: the reply replayed the stream the stop had just paused

> Resolver code + tests + the HA voice automation. **The interim mitigation is LIVE; the resolver fix
> is committed but NOT yet deployed.** `automation.voice_ceiling_speakers` lives only on the live
> system — this entry records its shape, the repo does not hold its YAML.

- **Symptom:** "Stop the music" (and "pause the music") answered *"Stopped."* while the radio kept
  playing. Reproduced three times — `17:57:37`, `17:57:57`, `18:03:00` — the last one *after* a
  resolver restart, which ruled out a stale process.
- **`resolver.log` looked innocent, and that was the clue.** The whole stop turn was two lines:

  ```
  18:03:00,220 INFO TURN start req=3ecfd695 zone=media_player.ceiling_speakers (duck requested)
  18:03:00,230 INFO DUCK  req=3ecfd695 zone=media_player.ceiling_speakers 0.36 -> 0.15
  ```

  No `MEDIA`, no `PAUSE` — because **stop never went through the resolver.** It is a sentence trigger
  on `automation.voice_ceiling_speakers`, whose `stop` branch called `media_player.media_pause`
  directly. Confirmed from the automation's own config and `last_triggered=2026-09-06T00:03:08.558Z`.
- **Root cause — a race that cannot be won on timing.** The pause is issued at `18:03:08.558`;
  `_say` captures the zone at `18:03:08.586`, **28 ms later**, before HA has propagated `paused`:

  ```python
  was_playing = before.get("state") == "playing"        # stale reading: "playing"
  ...
  if was_playing and source_id and not superseded():    # step 9
      music_assistant.play_media(media_id=source_id)    # the resurrection
  ```

  and the turn ends `replayed=True`. **The confirmation restarted the stream it was confirming.**
- **The guard for the opposite direction already existed.** `say_skip_on_fresh_playback` stops a reply
  from replacing a stream the same turn just STARTED, by reading `turn["playback"]` — which only the
  resolver ever sets. A pause issued straight from HA leaves no trace in the turn, so the mirror case
  had no guard at all. That asymmetry is the real defect: **`resume` routed through the resolver,
  `pause`/`stop` did not**, and the resolver owns the duck/replay state machine.
- **Interim mitigation (LIVE, applied 18:14).** The `pause` and `stop` branches lost their
  `set_conversation_response`, leaving a bare `media_player.media_pause`. With no reply, `_say` never
  runs and nothing replays. Cost: no spoken confirmation — the music stopping *is* the confirmation.
  Backup: `~/mass-resolver/.bak/automation-voice_ceiling_speakers-20260905-181421.json`.
- **Proper fix (COMMITTED, NOT YET DEPLOYED).** New `interaction` mode **`pause`**: it remembers the
  current source (so `resume` can bring the station back), marks the turn via `note_stopped()`, then
  issues the pause. `_say` then trusts the turn's recorded intent over its own capture and skips the
  replay — **while still speaking the confirmation.** Mirror of `note_playback`, including its
  "never invent a turn" rule for non-satellite callers. Kill switch: `say_skip_replay_on_stop`.
- **Tests:** 362 local (354 before). The regression proof is a pair, not a single assertion: the same
  stale `playing` capture with `say_skip_replay_on_stop` on vs off produces opposite outcomes.
- **To finish, in this order:** deploy the resolver modules → operator-run
  `sudo systemctl restart mass-resolver` → repoint the automation's `pause`/`stop` branches at
  `rest_command.resolver_command` with `params: {mode: pause}` and restore their spoken responses.

## 2026-09-05 — Voice timers are now audible AND repeat until dismissed: resolver `say_text` (text → clip → `play_media`) · `tts.speak` on the ceiling PROVEN BROKEN · 2 self-inflicted defects found and fixed

> Resolver code + a new HA automation. Deployed and **operator-eared**. Corrects two `ONBOARDING.md`
> claims that were the opposite of the truth.

- **Symptom:** "set a timer" worked, but when it finished there was only the LED ring — no sound.
- **Why:** the reSpeaker has **no speaker**, so HA's voice-timer chime plays into nothing. That part
  was expected. What was not expected is that there is **no way to hook it**: subscribing to the
  *entire* HA event bus during a timer showed **no timer event of any kind** — the only observable
  signal is the satellite's own `media_player` going `playing`.
- **First attempt was silent, and the docs had warned us.** An automation calling
  `script.ceiling_announce` (→ `tts.speak` → MA `play_announcement`) fired correctly and produced
  nothing audible. HA's log gives the reason:
  `Ceiling: Announce: Error executing script ... Failed to stream audio` /
  `Error streaming tts: Cannot write to closing transport`, with the traceback in
  `music_assistant/media_player.py:499 _async_handle_play_announcement`.
  **Music Assistant's own documentation states the precondition:** *"The MA announcement feature will
  ONLY work reliably if the player reports the state (e.g. playing, paused, idle) and the progress
  report (elapsed time) correctly."* Universal→Squeezelite does **not** — that is the same state-
  reporting defect behind the long-running stop-wedge. So announcements cannot be made to work here;
  the precondition is unmeetable, not a bug to fix.
  The `2026-07-15` reply design (§13) already recorded `tts.speak` as deterministically silent on this
  player. `ONBOARDING.md` §5 and §12 claimed the opposite. **Both corrected.**
- **Fix — new `interaction` mode `say_text`.** Text → HA `/api/tts_get_url` → clip URL → the existing
  `_say`, i.e. the **`play_media` route every reply already uses**. It inherits internal-base
  normalisation (HA returns the *external* base `192.168.1.104`, which MA cannot fetch — `_say`
  rewrites it), reply volume, poll-to-completion, restore, source replay, barge-in and the
  reply-started guard. `haconn` gains `tts_get_url()` plus a `_post_json()` that, unlike
  `call_service_rest`, returns the response body.
- **Guard added after a test caught it:** if the URL resolves empty, `_say` would play nothing and
  still report success — the exact "claimed success, did nothing" class this stack keeps producing.
  `say_text` now fails honestly instead.
- **New automation `satellite_timer_announce_on_ceiling`** — triggers on satellite local playback,
  **conditioned on `assist_satellite` being `idle` for 5 s**. That condition is load-bearing: the
  satellite's media_player plays on **every** wake and reply (~107 state changes in 20 minutes), so
  without it the automation would announce a timer on every turn. Consequences, accepted: a timer
  finishing **during** a conversation is missed by design, and if HA ever changes how the chime is
  delivered this stops working **silently**.
- **VERIFIED live, voice-initiated, operator-eared.** The decisive run was a real one: the operator
  said *"set a one minute timer"* to Nabu and heard the completion announcement. Log:
  `15:05:57 SAY clip=2e697283` (the "timer set" reply) then, **exactly 60 s later**,
  `15:06:57 SAY_TEXT req=36ac6346 engine=tts.piper chars=23` -> `finish-poll exit after 2.0s:
  state=idle` -> `restored -> 0.36`, `reply_started=True`. `chars=23` is "Your timer is finished."
  Dismissal works too: *"stop the timer"* was confirmed aloud and cleared the LEDs.
  The earlier agent-run test (below) drove the timer through the API; this one used the real path.
- **Agent-run test, same result:**
  `45.1s satellite media_player -> playing` → `AUTOMATION TRIGGERED` → `volume_set 0.7` →
  `cid -> .../tts_proxy/yx7` → `46.0s ceiling playing` → `48.8s volume_set 0.36`. Resolver:
  `SAY_TEXT req=242f7e3a engine=tts.piper chars=23` → `finish-poll exit after 2.5s: state=idle` →
  `restored -> 0.36`, `reply_started=True likely_silent=False`. **1.5 s from chime to speech.**
  The failed announce attempt, by contrast, left the ceiling reporting a **stale** cid from hours
  earlier — nothing ever loaded.
- **Repeats until dismissed** (added after the first cut announced once, which is easy to miss from
  another room). The loop announces, waits 25 s, and re-checks; dismissing the timer ends it. Capped
  at 8 rounds so a stuck state cannot announce forever. **VERIFIED live:** `15:38:13` / `15:38:41` /
  `15:39:10` `SAY_TEXT`, evenly spaced, stopping when the operator said "stop the timer".
- **Two defects were shipped and fixed in the same session. Both came from testing the path I was
  thinking about rather than the ordinary next thing an operator would do.**
  1. **The loop could be sustained by its own announcements.** The ceiling audio false-wakes the
     satellite — it hears *"Your timer is finished."* and transcribes it as **"The pipeline is
     finished."** / **"The point is finished."** (pipeline traces, 21:05 and 21:14). A conversation
     also makes the satellite's media_player play, which was the loop's continue condition, so:
     announce → self-wake → player plays → announce again. Fixed by requiring `assist_satellite`
     **idle** in the `while` as well, so a self-wake now *ends* the loop. Fail-safe direction: worst
     case is fewer reminders, never a runaway.
  2. **Every wake word announced a false timer.** The satellite's **wake sound** makes its
     media_player `playing` ~**180 ms before** HA marks the satellite `listening`
     (measured: `21:26:47.680 playing` → `21:26:47.862 listening`), so the entry condition
     ("idle for 5 s") was still true and the automation fired on every *"Okay Nabu"*. A state
     condition cannot win a 180 ms race, so the automation now **waits 3 s and re-checks** that the
     satellite is still idle. **VERIFIED by the operator:** asking Nabu a question no longer
     produces a timer announcement.
- **The satellite's `media_player` is a SHARED, UNRELIABLE signal — treat it as such.** It plays for
  wake sounds, the local copy of every reply, and timer chimes alike, and it returns to `idle`
  **while the alarm is still ringing** (which is why the first loop stopped after one round). Any
  automation keyed to it must confirm conversation state *after* things settle, and must not treat
  `playing` as "still ringing".
- **A real chime is NOT possible yet — blocked, diagnosed.** MA rejects `media-source://` URIs
  (`HomeAssistantError: Only URLs are supported for announcements`) and cannot fetch HA's media
  files, which need auth (`/media/local/... -> 401`; `/local/... -> 404`, nothing in `/config/www`
  and no VM shell to put anything there). A 4 s two-note bell WAV was synthesised with stdlib and
  uploaded to HA local media (`media-source://media_source/local/./timer_chime.wav`) and is waiting.
  **Next step:** have the resolver resolve the media-source URI to a *signed* URL via HA and play it
  through the existing `_say` — same shape and size as the `say_text` change. The alternative
  (serving the file from the resolver's own HTTP server) needs a static-file route plus a
  normalisation bypass, and adds surface for no real gain.
- **Still true:** the announcement cannot say WHICH timer finished — no event payload exists. HA
  itself supports multiple concurrent timers and named ones (`"create a timer for 8 minutes named
  pizza"` works; `"set a pizza timer for 9 minutes"` does not), and if two finish close together the
  media_player is already `playing`, so the second gets no separate announcement.

### Proposed BACKLOG notes (not applied)

> **1. Unify and choose the assistant voice.** Pipeline replies and resolver-spoken text (commands,
> news, timer announcements) use different Piper voices: the Assist pipeline sets a voice, while
> `tts_get_url` is called with an engine only and gets Piper's default. Add a `tts_voice` setting to
> the resolver and pass it through, then pick one voice deliberately — needs a listening session.

> **2. Ceiling audio can wake the satellite.** First hard evidence 2026-09-05: the timer announcement
> played on the ceiling was transcribed back as *"The pipeline is finished."* This is a plausible
> contributor to the false-wake problem otherwise attributed to wake words, and it applies to
> **replies**, not just timers. Worth measuring before more wake-word tuning.

> **3. Named timer announcements.** Needs the firmware `on_timer_finished` trigger and its payload —
> the OTA gate. Only worth opening alongside other firmware work (e.g. a wake-model fix).

- **Deploy (gated, user-run restart):** `haconn.py`, `interaction.py`; backup
  **`~/mass-resolver/.bak/20260905-144136/`**; host **3.5.2** `py_compile` OK, host
  `test_interaction.py` OK; restart **14:42:36**; `/command` bound, zero tracebacks.
- **Tests:** **344 local** (was 337; +7).

### Also surfaced by the HA error log, not acted on

- **`Can't connect to ESPHome API for respeaker-living-room @ 192.168.1.132` (Errno 113)** — the
  satellite drops its API connection. A plausible contributor to the `stt-no-text-recognized`
  failures currently blamed on wake-word settings. **Investigate before more wake tuning.**
- **`S1b-2 - Satellite Reply on Ceiling: Timeout when calling resource ".../command"`** — the reply
  automation has timed out at least once. It has `continue_on_error`, so it fails quietly; the
  symptom would be a reply that never reaches the ceiling.
- **MA DNS drops still recurring** (`Failed to connect to ws://d5369777-music-assistant:8094/ws`) —
  A1/A2a self-heal, still earning their keep.

## 2026-09-05 — Radio favourites: spoken handles (`say_as`), a favourites listing, and a default station

> Resolver code + `radio.json` data. Deployed and verified live. **No HA change** — the remaining
> "play russian songs" mis-routing is an upstream slot problem and is NOT fixed here (below).

- **"List my favourite stations" answered nothing.** `_candidates()` only filtered by station /
  country / language / genre; with no filter it fell through to `return [], ""`, so `find` produced
  `radio mode=find target='' candidates=0` and the assistant said *"I couldn't find a station for
  that."* Reproduced live at 2026-09-05 11:48:56 before the fix. It now lists the favourites.
- **Seven favourites were unsayable.** `Русское Радио`, `Радио Родных Дорог`, `Спокойное радио`,
  `Люкс FM 103.1` and `Наше Радио` had no alias, so STT could never reach them — the Noroc problem,
  seven times over. Worse, the alias `nashe` pointed at **`Nashe Radio` (radio/13)**, leaving
  **`Наше Радио` (radio/9)** — a different station — unreachable by voice entirely.
- **Fix — one `say_as` field per favourite, doing two jobs.** It is what the listing reads out AND
  what the user can say back: folded into the alias map at lookup time, so there is no second list
  to drift. Explicit `aliases` still win over handles, keeping the hand-tuned Noroc repairs
  authoritative. Both Nashe stations now have distinct handles (`nashe nine` / `nashe thirteen`) so
  the operator can pick a winner before one of them takes the plain `nashe` alias.
- **`jazz` is deliberately NOT a handle** — it is a live genre synonym, and aliasing it would hijack
  every genuine "play some jazz" request. Same reasoning that keeps `rock` unaliased (2026-08-02).
  The station's handle is `smooth jazz`.
- **Listing format:** count first, then five handles — 17 names read aloud would be unusable.
  *"You have 17 favourites. The first 5 are: mega hits, native roads, russian songs, russian radio
  and retro fm."* The first five are operator-chosen and are simply the first five entries in
  `radio.json`; listing order **is** file order, so re-ranking needs no code.
- **Default station added.** `defaults.default_station = "101 SMOOTH JAZZ"`, used when a play request
  arrives with no station. **Caveat, unfixed:** the sentence-trigger path does NOT use it —
  `script.ceiling_play_radio` carries its own hardcoded `{{ station | default('Radio Paradise') }}`
  and bypasses the resolver entirely, so a bare "play radio" through the prefer-local layer still
  plays **Radio Paradise**. That script also still calls `tts.speak` (the deterministically-silent
  overlay path). Rerouting it through the resolver is proposed, not applied — the both-paths lesson
  from 2026-08-02 applies.
- **NOT fixed — "play russian songs" plays the wrong station.** The model collapses the phrase to
  `country='Russia'` before the resolver sees it (`radio mode=play target='Russia'`), so the
  `russian songs` handle is never consulted. The information is destroyed upstream and no
  resolver-side change can recover it. The fix is deterministic sentence triggers for the handles —
  designed, approved in principle, **not built**. Note the symptom has *changed*, not gone: the
  reorder means `country=russia` now returns **Радио Родных Дорог** instead of Europa Plus.
- **VERIFIED live** over `/command` after the restart (dry-run, so nothing played):
  `russian radio -> Русское Радио` · `russian songs -> Радио Русские Песни` ·
  `native roads -> Радио Родных Дорог` · `nashe nine -> Наше Радио` ·
  `nashe thirteen -> Nashe Radio` · `calm radio -> Спокойное радио` · `lux fm -> Люкс FМ 103.1` ·
  no station -> `101 SMOOTH JAZZ` · `genre=jazz -> 101 SMOOTH JAZZ` (genre path intact, not hijacked).
- **Deploy (gated, user-run restart):** `favorites.py`, `radio.py`, `radio.json`; backup
  **`~/mass-resolver/.bak/20260905-120255/`**; host **3.5.2** `py_compile` OK, `JSON OK 17 favorites`,
  host `test_radio.py` OK; restart **12:08:02**, `/command` bound, `200/401`, zero tracebacks.
  **Deploy note (still true):** multi-file `scp` hangs on this host — copy one file at a time.
- **Tests:** **337 local** (was 326; +11). The listing test failed with the exact live symptom
  (`I couldn't find a station for that`) before the fix existed, and one test pins that **no
  non-ASCII character can reach the spoken text** — a list that reads Cyrillic aloud is useless.

## 2026-09-05 — S1b-2 Slice 5: reply route PASSES, **sign-off WITHHELD** (wake-word false accepts) · both pending fixes applied · 3 wake words tried, 2 confirmed misfiring, 3rd under observation

> **Verdict: Slice 5 is NOT signed off.** The reply route itself is proven — four weeks of unattended
> production plus a live operator run. What blocks sign-off sits upstream of it: the satellite wakes on
> ordinary conversation, so the assistant is certified to reply correctly **when correctly addressed**,
> and being correctly addressed is not currently reliable.

### Pending fixes from Slice 4 — both closed

- **(a) Knowledge-agent instructions — were already applied**, confirmed by reading the prompt (HA's
  WS API exposes subentry ids but not their data, so this needed the operator). Behaviour verified
  independently: no markdown, no bullets, no URLs, metric unprompted, one-to-two sentences by default.
  Its `stay under about 150 words` also means the knowledge agent **cannot** hit the 180 s reply
  ceiling — that exposure sits entirely on the control agent.
- **(b) Volume phrasings — APPLIED.** `/tmp/new_vcs2.json` POSTed (200 `{"result":"ok"}`, first try;
  the endpoint that kept timing out behaved). Diffed against live first: the only delta was 4 added
  "up" and 5 added "down" sentences, with the Slice-4 reroute intact (7 triggers, 0 `media_stop`,
  0 direct `volume_set`, 4 `rest_command.resolver_command`). **VERIFIED live:**
  `lower the volume` → `VOLUME volume_down: -> 0.3` · `turn down the volume` → `0.2` ·
  `decrease the volume` → `0.1`, restored to 0.4. Rollback `/tmp/vcs_SNAPSHOT.json`;
  pre-POST live copy saved to `/tmp/live_vcs_now.json`.

### Slice 5 steps

| Step | Result |
|---|---|
| 1 · audible reply over radio | **pass** — operator-eared, `replayed=True` |
| 1 · over local music | **pass** — Rammstein "Dicke Titten" turn |
| 2 · restore to pre-duck baseline | **pass** — `restored -> 0.46` / `0.36` / `0.27` / `0.25`, exact, every turn |
| 3 · source replay | **pass** — `replayed=True`; `RESUME replaying library://radio/2` |
| 4 · dropped-reply guard + chirp | **NOT DONE** — the chirp needs the firmware step S1b-2 deliberately skipped; the resolver half (unfetchable URI → `reply_started=false`) was never run |
| 5 · latency + cost | **not measured** |
| 6 · barge-in | **not exercised** |
| 7 · no regressions | **partial** — music, radio, news, status and volume were each exercised without fault during the operator run, but no systematic regression pass was made |
| media command silent-on-success | **pass** — `SAY SKIPPED: this turn started library://radio/3` → `RADIO CONFIRM ... is playing` |
| volume persists into next turn | **pass** — `VOLUME volume_up: baseline 0.25 -> 0.35`, then the next turn ducked **from 0.35** |
| both wake words exercised | **pass** — slot 1 "Okay Nabu"; slot 2 as "Hey Jarvis"/"Kenobi" before the rename to "Hey Mycroft" |
| tool isolation | **pass, with a caveat** — see the hallucinated action below |

### The agent split needed three fixes, all found in traces rather than logs

- **The control agent was answering general questions by explicit instruction.** Its prompt carried
  `For other, non-home questions, answer briefly from general knowledge`, written before the split
  existed; post-split that contradicts the ADR. It also answered *time-sensitive* questions from stale
  training data with full confidence (*"the most recent Formula 1 race ... October 8, 2023"* — wrong by
  three years). **It never had web access:** asked the same question, it could not get Tokyo's
  temperature while the knowledge agent could. The live headlines it *did* produce came from the
  resolver's own `news` tool (`NEWS bucket=world`), by design. **The ADR's tool/web separation held
  throughout** — which is not the same as saying the split is without risk; see the room-audio
  exposure below, which the ADR did not anticipate.
  Fixed by prompt: defer to the knowledge agent, never state time-varying facts from memory, one or two
  sentences capped at ~60 words (which also makes a 180 s overrun structurally impossible), and stay
  silent when not clearly addressed. **VERIFIED in production 2026-09-02:** *"Who flew first on the moon
  and in what year?"* → *"I can't answer that yet."*
- **The knowledge agent claimed an action it cannot perform.** *"Um turn the volume up."* →
  **"Turning the volume up."** It did **nothing** — no `VOLUME` line, `script.ceiling_volume_up` last
  fired two minutes earlier, and the baseline stayed 0.46 across every following turn. Tool isolation
  held, but the reply is indistinguishable from success. Its old wording said it had no *control*, which
  the model read as a preference; hardened to "you have NO tools ... never say you are doing, have done,
  or will do any of those things".
- **Knowledge weather answered for the whole United States** — `home location` is off on the web search
  (ADR), so it has no idea where the house is. Fixed in the prompt (`The user is in Calgary, Alberta,
  Canada`) rather than by enabling the setting, which would leak coordinates.
- **A wake-word rename broke a cross-reference — twice.** The control prompt named "Jarvis"; renaming slot 2 left
  it directing the user to a wake word that no longer existed. The knowledge prompt, written
  wake-word-agnostically ("the main assistant"), survived for free — **prefer generic cross-references
  between agents.**

### Wake-word false accepts — the reason sign-off is withheld

Assist pipeline traces (`resolver.log` cannot see this — it only records turns that *reached* the
resolver) show the satellite answering ordinary household conversation. Roughly **8 of 20** stored runs
were false wakes, including a work call transcribed and answered with automation advice, and a private
medical conversation. Because slot 2 carries **web search**, room audio can leave the house — an
exposure the ADR's threat model (injection flowing *in*) did not anticipate.

**Three mitigations tried, all failed:**

1. `finished_speaking_detection` `relaxed` → `aggressive` — predicted to shorten captures; measured
   afterwards, it did not meaningfully (a 20-word capture after the change vs ~45 before). It also became
   the prime suspect for `stt-no-text-recognized` failures on slot 2. Operator chose to keep it for now.
2. Wake word `Hey Jarvis` → `Kenobi`, on the theory that "Jarvis" was phonetically weak. **Wrong, and
   backwards:** the detector matches an acoustic pattern, not the word, and a single unprefixed
   three-syllable word matches *more* loosely. Three false wakes in five minutes followed.
3. Wake word `Kenobi` → `Hey Mycroft` (2026-09-05, operator's choice over disarming) — the last
   available option and the one with the most phonetic material. **Under observation**; if slot 2 keeps
   false-waking on a two-word four-syllable wake phrase at minimum sensitivity, the word is exonerated
   and the wake model is the only remaining explanation.
4. `wake_word_sensitivity` is already at its floor (`Slightly sensitive`) — **no lever remains.**

**Three wake words tried on the same slot; two confirmed misfiring.** `Hey Jarvis` and `Kenobi` both
false-woke repeatedly; `Hey Mycroft` is the third and is **live and under observation** — the operator
reports it working so far, which is encouraging but not yet a measured result. If it also misfires,
that points at the wake model rather than the word. The
real fix is firmware (a better model, or a confidence threshold the UI does not expose), which is the OTA
gate this workstream has deliberately kept shut. **Recommendation: treat slot 2 as unfit for always-on
use** until `Hey Mycroft` has been observed for a few days — arm it to ask something, disarm it otherwise.

### Also found and FIXED here

- **`ONBOARDING.md` understated the exposed surface** — §1 and §4 named three ChatGPT tools when there are
  at least five (`script.news` and `script.media_status` are both exposed and were both observed firing
  within 24 h), and the `script.ceiling_*` list omitted `next` / `previous` / `play_music`. Both sections
  corrected.
- **`ONBOARDING.md` still claimed "turn **down the volume**" does not work** — disproved by fix (b) above,
  which verified that phrasing reaching the resolver. Replaced with the extended phrasing list.
- **`ONBOARDING.md` §6 said nothing about the slot-2 exposure** — a reader onboarding from the
  authoritative current-state doc would have armed the web-search wake word unwarned. Added.

### Also found, not fixed

- **`status` reports the duck floor as the user's volume.** *"Playing 'Dicke Titten' by Rammstein at 15%
  volume"* — 15% is the duck floor mid-turn, not the listening level. Same class as the `reply_volume`
  misreport fixed 2026-08-02; the floor case was missed.
- **`ANNOUNCE send failed (BrokenPipeError)`** on 2026-08-26 and 2026-08-31 — retried and succeeded via
  `tts.speak` both times. Self-healing, twice-seen, not chased.
- **Runbook correction, not applied:** `quick-connect-and-health-check.md` §1 says to run
  `eval "$(ssh-agent -s)"` each call. Followed literally that spawns a fresh agent per call; after ~13 of
  them `ssh-add` began hanging and SSH calls timed out at two minutes. A persistent agent already exists —
  the preamble should be `ssh-add` alone. The runbook is outside this branch's allowed files.

### Carried-over items — observed, not fixed

- **0.04 crater:** repeated volume-down steps are a fixed **absolute 0.10**, so 0.44 minus four steps lands
  exactly on 0.04; from 0.40 the walk is 0.30/0.20/0.10. Corroborates the stepping route. The second,
  unidentified source is untouched and still open.
- **MA transient `code=2`**, **two-Assist-turns**, **`_restore` sub-second stale read**, **Calgary alias**,
  **S1a grace-G** — no recurrence observed, no action taken. The two-Assist-turns item is now better
  explained by repeated false wakes during continuous conversation than by one event firing twice.

### Runtime config

- `reply_volume` 0.60 → **0.70** at the operator's request (global — there is no per-agent reply volume).
  Backup taken **2026-09-04** (`~/mass-resolver/.bak/20260904-114909/`) when the change was staged;
  the operator-run restart that made it live was **2026-09-05 10:57:01**. The date gap is expected,
  not a typo — the staging and the restart happened on different days.

### Proposed BACKLOG note (not applied)

> `S1b-2` row · **proposed**: Slice 5 **partially complete** — reply route, duck/restore/replay,
> stop/resume/volume and both wake words verified live; steps 4 (dropped-reply guard), 5 (latency) and
> 6 (barge-in) outstanding. **Sign-off withheld** pending wake-word false accepts, which are a
> firmware-level problem and warrant their own item (`S1c — satellite wake reliability`) rather than more
> config tuning. Slot 2 recommended off by default until then.

### Verification

- Tests **326 local, unchanged** — this branch contains no code or test changes (the 337 count belongs
  to `homebrain/radio-favorites-listing`). Health check green after each restart: resolver `active`, `/command`
  bound, `200/401`, **zero tracebacks** across the whole log.
- No firmware touched. Every restart operator-run. Live changes: the `voice_ceiling_speakers` POST, two
  agent prompts, two satellite `select` values, and `reply_volume` — each with a rollback pointer.

## 2026-08-03 — Assist SPLIT into control + knowledge agents (2nd wake word, web search, tool-isolated) · long replies allowed · pre-announcement bump fixed

> **ADR:** [`2026-08-03-agent-split-routing-adr.md`](./2026-08-03-agent-split-routing-adr.md). Config only —
> **no firmware**, no resolver code for the split itself. Slot 2 was already wired in the running firmware
> (`wake_word_2` / `assistant_2` existed), so the OTA gate stayed closed.

- **Why:** the single agent could not answer live-data questions (*"I can't check the weather for Calgary right
  now"*) while happily answering *"100 EUR in CAD"* from training knowledge — static knowledge vs live data,
  not a defect. Enabling web search on **that** agent would have put untrusted web text in the same agent that
  **controls the house**, which is the combination that makes prompt injection actually dangerous.
- **Shipped:**

  | | Control | Knowledge |
  |---|---|---|
  | Wake word | **Okay Nabu** | **Hey Jarvis** (slot 2) |
  | Pipeline | `Living Room ChatGPT` `01kxygpr39jas5hgsf28cph108` | `Living Room Knowledge` `01kz45tkgbnsn57gpyj25vyfd0` |
  | Agent | `conversation.openai_conversation` (gpt-4o-mini) | `conversation.openai_conversation_2` (gpt-4o) |
  | prefer-local | true | **false** (wake word alone picks the layer) |
  | House tools | **yes** (Assist) | **none** |
  | Web search | off | **on** · Medium · links **off** · home location **off** |

- **VERIFIED live — tool isolation is the load-bearing check.** Same question to both:
  `KNOWLEDGE → "I can't check what's playing on the ceiling speakers… ask the main assistant"` ·
  `CONTROL → "Nothing is playing right now."` And the knowledge agent returned **today's** Calgary forecast,
  so web search genuinely works. **No new exposure**; `expose_new_entities` still off; the knowledge agent has
  no LLM API at all, so `assistant-capabilities.md` needs no change.
- **`gpt-4o-mini` cannot do web search** — HA hides the option for it. The knowledge agent runs **gpt-4o**;
  the control agent stays on mini, so the expensive model only serves the rare question.
- **Spoken-output caveat (prompt, not code):** the first live web answer came back as markdown headings + an
  hourly bullet list in Fahrenheit — unusable through a speaker. The knowledge agent's instructions must forbid
  markdown/lists/URLs and prefer metric.
- **Long replies now allowed (resolver):** `say_reply_timeout_ms` 30000 → **180000** (~400 spoken words) and
  `say_blank_cid_grace_ms` 4000 → **8000**. At 30 s the poll truncated a long answer and replayed the music
  over its tail. The reply-marker staleness budget and the deferred restore derive from this value, so they
  widened automatically.
- **Pre-announcement volume "bump" fixed (resolver):** `_say` raised the volume to `reply_volume` **before**
  the clip replaced the stream, so the ~1 s of still-playing *ducked music* was played at 0.60 — the jump the
  operator heard. `_say` now pauses the zone first (when something was playing), so the raise is inaudible; if
  the clip then never goes out, the `finally` un-pauses. Reversible via `say_pause_before_reply=false`.
  **Not fixed (inherent):** the short gap before music returns is the source **replay** — a radio stream must
  reconnect. Removing it needs an *overlay* reply, and the overlay path is deterministically silent on this
  player (CHANGELOG 2026-07-17).
- **The 0.04 crater — PARTIALLY explained, NOT closed** (correction: an earlier draft of this entry claimed it
  was closed). Repeated 10 % volume-down steps from ~0.44 land exactly on 0.04, then 0.0 — reproduced by an
  agent probe that fired five "down" phrasings in a row at a live speaker. **But that cannot be the whole
  story:** the 2026-08-01 troubleshooting notes below record craters to **0.04 / 0.15** long before any such
  probe, and a `DUCK 0.04 -> 0.04` line appears on 2026-08-02 at 15:55 with no volume command near it. So
  repeated stepping is *one* route to 0.04, not the only one. The duck-ownership fix means the zone now
  self-heals from it either way, but the second source is still unidentified — **keep this open.**
- **`weather.forecast_home` is Calgary.** Home is lat 50.8898 / lon −114.0179; the entity is merely *named*
  "Forecast Home", which is why "weather in Calgary" found no device. An **alias** "Calgary" on that entity
  would answer it locally, deterministically, with no egress — **proposed, not applied** (exposure-adjacent).
- **Still pending (not applied):** the extra volume phrasings (`lower the volume`, `turn down the volume`,
  `decrease the volume`) — generated and validated at `/tmp/new_vcs2.json` on the host, blocked on HA's
  automation-config endpoint timing out repeatedly. Until applied, use **"volume down" / "turn it down" /
  "quieter" / "turn the volume down"**, which all work.
- **Restart DONE (10:28:25) — everything above is live.** Post-restart verified: resolver `active`, `/command`
  bound, `200/401`, **zero tracebacks**, and the running `config.json` carries `say_reply_timeout_ms=180000`,
  `say_blank_cid_grace_ms=8000`, `say_pause_before_reply=true`.
- **Tests:** 326 local / 229 host.
- **Integrated:** PR **#35** merged → `main` `3c23575`; worktree removed, branch deleted. The merge pulled in
  PR #34 (the 2026-08-01 troubleshooting notes below) — both changelog sides were kept, and reading them forced
  the 0.04 correction above.
- **Live gates RELEASED → FREE.** This work claimed **HA-live** (6 ceiling scripts + `automation.voice_ceiling_
  speakers` + the agent split) and the **resolver deploy**. All of it is merged, deployed and verified live, so
  the gate is free for the next item. *(Say otherwise if you'd rather hold it.)*

### Handoff — where Slice 5 should start

**Do first (small, both known):**
1. **Knowledge-agent instructions** — currently unconstrained, so live web answers come back as markdown
   headings + hourly bullet lists in Fahrenheit, which Piper reads aloud verbatim. Needs: no markdown/lists,
   no URLs, metric, 1–2 sentences by default. Prompt-only change on `conversation.openai_conversation_2`.
2. **Volume phrasings** — `lower the volume` / `turn down the volume` / `decrease the volume` reach nothing
   (the first is swallowed by an HA **built-in** intent looking for a device named "volume"). Generated and
   validated at `/tmp/new_vcs2.json` on the host; blocked purely on HA's automation-config endpoint timing out.
   Working today: **"volume down" / "turn it down" / "quieter" / "turn the volume down"**.

**Open, none blocking:**
- **0.04 crater — partially explained only** (see above). Second source unidentified; the zone self-heals now.
- **MA transient `RADIO PLAY FAILED code=2`** after an ~11 s stall — the documented playback-lock family.
  `RADIO CONFIRM` + the new `details=` logging will now name it when it recurs.
- **Two Assist turns ~1 s apart** ("multiple voices") — different clip fingerprints, so two genuine turns, not
  one event twice. Upstream wake-retrigger / pipeline re-listen. Satellite ruled out (single slot at the time,
  no speaker attached).
- **LLM tool mis-selection** (e.g. volume requests landing on `ceiling_pause`). `openai_conversation` debug
  logging is **on**; use the assist-pipeline traces, not `resolver.log`. Lowering the control agent's
  **temperature from 1 → ~0.2** is the obvious untried lever for determinism (NL-01).
- **`_restore` stale-read** — a sub-second duck→restore reads the pre-duck value, calls it `user_override` and
  pops the snapshot, leaving the zone at the floor **with no dead-man**. Only reproducible by an agent probe;
  real turns are seconds apart. Fix would be to treat "already at baseline" as *already restored*.
- **Proposed, not applied:** alias **"Calgary"** on `weather.forecast_home` (home *is* Calgary — lat 50.8898 /
  lon −114.0179), so "weather in Calgary" answers locally with no egress. Exposure-adjacent → needs approval.
- **S1a grace-G never applied.** Slice 4 specified repurposing `idle→restore` into a grace-G backstop; making
  the resolver the single writer achieved decision (b) without touching the automation, so it was deliberately
  skipped. Revisit only if `say_owns_restore` is ever set false.
- **Slice 5 scope grew:** E2E sign-off should now cover the **agent split** (both wake words, tool isolation)
  and the rerouted stop/resume/volume paths — not just the reply route.

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

## 2026-08-01 — S1b-2 early-use troubleshooting notes (satellite live on ChatGPT + ceiling replies)

Live-use troubleshooting of the S1b-2 satellite→ceiling assistant (Slices 1-3 shipped 2026-07-19/20).
Findings + the fixes applied, for future reference. Dates preserved.

- **Observability (where to look — no change needed):**
  - `~/mass-resolver/resolver.log` (INFO): resolver-backed commands (`play_music/radio/find/news/media_status`)
    + the reply/duck flow (`DUCK`/`SAY reply_started=…/RESTORE`). Note: pure-HA ceiling scripts
    (`volume_up/down`, `pause/resume/stop/next/previous`) do **not** hit the resolver — they are **not** in
    `resolver.log`; use the HA side for those.
  - **HA assist-pipeline debug traces** (per-turn STT text → tool/agent → TTS → errors), via WS
    `assist_pipeline/pipeline_debug/list` + `…/get` for pipeline `01kxygpr39jas5hgsf28cph108` — the best
    "what did Nabu hear + do" record; always captured (~last 20 runs).
  - **MA add-on log** `GET /api/hassio/addons/d5369777_music_assistant/logs` — playback errors.
  - HA log level raised to **DEBUG** at runtime (2026-08-01) for `conversation` / `assist_pipeline` /
    `openai_conversation` via `logger.set_level` (no restart; reverts on restart or set back to `info`).
    Those DEBUG lines go to `home-assistant.log` — viewable in the HA UI (Settings → System → Logs);
    `/api/error_log` is **404** on this HA and there is no VM shell, so an agent cannot read that file.
- **Request cut off / misheard (STT side) — one fix applied.** STT was ending capture too early
  ("Play radio and or", "Give the volume a bit up. So we go.") and mis-hearing foreign station names
  ("Moldova"→"Moved Over", "norok" garbled → LLM returns "couldn't find a station"). **Fix (2026-08-01):**
  set `select.respeaker_living_room_finished_speaking_detection` → **`relaxed`** (waits longer before ending
  capture). Reversible (→ `default`). The foreign-name mis-hearing is a Whisper accuracy limit (revisit STT
  model separately if needed).
- **Latency profile (measured 2026-08-01, from the pipeline traces):** wake → ready-to-listen ≈ **1-1.5 s**
  (device wake ~0.3 s + pipeline spin-up + a short "waiting for command" window; inherent). The dominant
  delay is the **LLM answer: ~3-13 s** (gpt-4o-mini). Total turn up to ~22 s on long answers. Lever to reduce
  it: constrain answer length via the OpenAI agent instructions (decision (e) — not yet applied; gated prompt
  change).
- **Wake cue gap (no satellite speaker).** Audio is **ceiling-only** now (no speaker on the reSpeaker jack),
  so the on-device **wake chime is inaudible** — the only "start talking" cue is the **LED ring** (beam
  animation on `on_listening`). An audible ceiling "ready" chime is possible (the firmware already fires
  `esphome.wake_word_detected`, same pattern as the reply) but adds another actor to the ceiling/volume flow —
  **deferred to Slice 4/5** so it doesn't compound the volume bug.
- **Volume churn / crater (the Slice-4 bug, actively degrading use).** Each satellite turn strands the ceiling
  volume at a wrong level — observed bouncing 0.15 ↔ 0.25 ↔ 0.46 ↔ 0.70 and **cratering to 0.04 / 0.15**
  (near-silent → "no music heard"). Root cause per the diagnostic subagent: S1a's `idle→restore` reads a
  stale/racy volume, calls it `user_override`, and **discards the duck-snapshot baseline**; the next `_say`
  then finds no snapshot and falls back to its own already-ducked `prev_volume`. Also seen: an
  `interaction … timed out` error on a reply (`_say` blocking + streaming-TTS). **All of this is Slice 4**
  (duck-ownership fix). **Interim workaround:** manual volume set — including by voice now (see below).
- **`script.ceiling_set_volume` exposed (2026-08-01).** Added it to the conversation assistant exposure
  (12→**14** exposed entities: also confirmed `ceiling_volume_up/down`, `media_status`, transport scripts were
  already exposed). It sets an **absolute** level (`media_player.volume_set`, direct — immune to the duck
  bug), so "set volume to 50 percent" now works and doubles as the **voice recovery** when the volume craters.
  Rollback: un-expose `script.ceiling_set_volume`.
- **Radio-stream failures (external, not our stack).** `play_media library://radio/2` (101 SMOOTH JAZZ) and
  Moldova stations returned MA **`Playback failed … no more tracks available`** (500) — the station streams
  were dead/unreachable at the time. **MA/ceiling/Squeezelite are healthy** — local SMB music (`play_music`)
  plays fine; only specific RadioBrowser station streams failed. Likely transient / station-side; re-check the
  station or refresh RadioBrowser if it persists.
- **What's assistant-usable today (13→14 exposed):** `play_music`, `play_radio`, `find_stations`, `news`,
  `media_status`, `ceiling_pause/resume/stop/next/previous`, `ceiling_volume_up/down`, **`ceiling_set_volume`**,
  weather. Reliable: commands (audible via ceiling) + status readout. Degraded pending Slice 4: reply/duck
  volume behaviour.
- **Live changes made this session (all reversible, HA-live/exposure only — no resolver code / no firmware /
  no restart):** `finished_speaking_detection`→`relaxed`; exposed `script.ceiling_set_volume`; HA runtime
  DEBUG logging; several manual `volume_set` recoveries; started local music. Live gate FREE.
- **Next:** **Slice 4** (duck-ownership fix — clears the volume churn, the long-reply cut, and the reply
  timeout) then Slice 5 E2E; optional: constrain LLM answer length (latency) and a ceiling wake-chime.
  Slice-4 kickoff prompt prepared this session. Plan: `plans/2026-07-16-s1b-2-satellite-full-assistant.md`.

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
