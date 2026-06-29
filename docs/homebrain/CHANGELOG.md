# Homebrain Change Log

Operational/administrative changes to the homebrain setup. (Architecture and feature
design live in the per-topic docs; this log is for discrete operational changes.)

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
