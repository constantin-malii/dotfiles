# Homebrain Change Log

Operational/administrative changes to the homebrain setup. (Architecture and feature
design live in the per-topic docs; this log is for discrete operational changes.)

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

## 2026-06-28 — Follow-up: Speaker WebSocket reconnect bug (found, recovered, fix planned)

- **Symptom:** after an HA restart mid-session, every resolver Piper announcement failed with
  `BrokenPipeError(32)`; successful music playback was unaffected (that path is Music Assistant, not the
  Speaker).
- **Root cause:** `haconn.HA.announce()` catches and **swallows** the send exception, so
  `Speaker.speak()`'s reconnect-once logic never fires and the dead WebSocket persists.
- **Immediate recovery:** `sudo systemctl restart mass-resolver` re-established the socket; a no-match
  announce was verified speaking again (`ANNOUNCE via tts.speak`).
- **Permanent fix (planned, not yet implemented):** make `announce()` log **and re-raise** send/
  connection failures so the reconnect-once heals automatically; tests for propagation, reconnect-once,
  and no-infinite-loop. Plan: `plans/2026-06-28-speaker-reconnect-bugfix.md`.

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
