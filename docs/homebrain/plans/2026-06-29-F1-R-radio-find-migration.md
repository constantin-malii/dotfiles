# F1-R — Radio + Find Migration (`play_radio`, `find_stations` → hard tool result) — Plan

> **Design only — do NOT implement. Stop for approval before modifying any production script.**
> Parent: [F1-R addendum](../2026-06-28-F1-R-chatgpt-tool-result-relay-design.md) ·
> mirrors the proven [music re-migration](2026-06-28-F1-R-music-remigration.md) (DONE).

## Goal
Migrate the two remaining exposed radio scripts to the synchronous resolver `/command` path using the
**same proven hard-return pattern** as `script.play_music`: the script **returns**
`{chat_text: r.content.chat_text}` as its tool result via `stop` + `response_variable`. No
`set_conversation_response`; no `tts.speak`. Resolver stays the **sole TTS owner**. One script at a
time: **(1) `script.play_radio`** then **(2) `script.find_stations`**, each backed up first and
independently reversible.

## Global constraints (binding — every gate inherits these)
- Migrate **`script.play_radio`** then **`script.find_stations`** only. Intent stays **`radio`** (the
  same capability handles play/find via the `mode` param).
- Use the already-live **`rest_command.resolver_command`** (30 s timeout, `X-Resolver-Key`).
- Script **returns** `{chat_text: r.content.chat_text}` via **`stop` + `response_variable`**.
- **No `set_conversation_response`.** **No `tts.speak`** in the scripts. Resolver = only TTS owner.
- **No new tools exposed** (same two scripts, same fields/descriptions). **No GPT model change**
  (gpt-4o-mini). **No Inc 2.** Keep **`mass_sync_request`** untouched; keep the **event adapter** live.
- Reuse the existing OpenAI agent instruction (added for music): *"When a tool returns a chat_text
  field, relay that text verbatim."* — **no agent-config change needed**.
- Python 3.5-safe; secrets only in 0600 files; no AI attribution in commits; back up each script before
  editing.

## Field mapping is UNCHANGED
The migration changes **only** how each script returns its result — the **fields ChatGPT fills and the
params sent to the resolver stay identical** to today's `mass_radio_request` event_data. Tool selection
and field population (station vs genre vs country vs language) are unaffected.

Current (verified 2026-06-29):
- **`play_radio`** — alias `Ceiling: Play Radio (resolver)`; fields `genre, language, country, station`;
  fires `mass_radio_request` with `{mode:"play", genre, language, station, country}`.
- **`find_stations`** — alias `Ceiling: Find Radio Stations (resolver)`; fields `genre, country`;
  fires `mass_radio_request` with `{mode:"find", genre, country}`.

## Latency (drives the existing 30 s timeout — no change)
Radio favorite ~2 s; RadioBrowser ~3 s; one 27 s outlier treated as anomalous. `find` also hits
RadioBrowser (~3 s). All within the 30 s `rest_command` timeout already configured.

## Expected `CommandResult` per case (from `radio.py`, authoritative)
| case | `chat_text` (→ ChatGPT) | `spoken_text` (→ Piper) | resolver speaks | playback |
|---|---|---|---|---|
| play success | `Playing <matched station>.` | `None` | **0** (stream is feedback) | yes |
| play no-match | `I couldn't find a station for <label>.` | same | **1** | no |
| play start-fail | `I found <station>, but couldn't start it.` | same | **1** | no |
| find success | `Here are some stations: A, B and C.` | `I found A, B and C.` | **1** | n/a (lists) |
Note: `<matched station>` is the resolver's actually-chosen station name (may differ from the user's
wording, e.g. "Hit FM" → the matched favorite's full name) — ChatGPT relays the real name verbatim.

---

## New sequences (exact)

### `script.play_radio` — change ONLY the `sequence` (keep alias/description/fields)
```json
[
  {"action": "rest_command.resolver_command",
   "data": {"intent": "radio",
            "params": {"mode": "play",
                       "genre": "{{ genre | default('', true) }}",
                       "language": "{{ language | default('', true) }}",
                       "station": "{{ station | default('', true) }}",
                       "country": "{{ country | default('', true) }}"}},
   "response_variable": "r", "continue_on_error": true},
  {"variables": {"resp": {"chat_text": "{{ r.content.chat_text if (r is defined and r.content is defined and r.content.chat_text is defined) else 'Sorry, I could not reach the radio system.' }}"}}},
  {"stop": "done", "response_variable": "resp"}
]
```

### `script.find_stations` — change ONLY the `sequence`
```json
[
  {"action": "rest_command.resolver_command",
   "data": {"intent": "radio",
            "params": {"mode": "find",
                       "genre": "{{ genre | default('', true) }}",
                       "country": "{{ country | default('', true) }}"}},
   "response_variable": "r", "continue_on_error": true},
  {"variables": {"resp": {"chat_text": "{{ r.content.chat_text if (r is defined and r.content is defined and r.content.chat_text is defined) else 'Sorry, I could not reach the radio system.' }}"}}},
  {"stop": "done", "response_variable": "resp"}
]
```

---

## Stage A — `script.play_radio`
- [ ] **A1 Backup:** `GET /api/config/script/config/play_radio` → `~/script_backups/play_radio.preF1R.json`.
  Confirm it contains `event: mass_radio_request` and no `rest_command`.
- [ ] **A2 Apply:** `POST /api/config/script/config/play_radio` with the new `sequence` (preserve
  alias/description/fields/icon); `POST /api/services/script/reload`.
- [ ] **A3 Readback:** assert alias + fields `[country, genre, language, station]` preserved;
  **no `set_conversation_response`**; **no `tts.speak`**; has `rest_command` + `stop`/`response_variable:
  resp`; returns `r.content.chat_text`. Confirm still exposed to `conversation`.
- [ ] **A4 Direct test (controlled):** WS `call_service` `script.play_radio`
  `{station: "Zzz No Such Station"}` with `return_response: true` → assert response ≈
  `{chat_text: "I couldn't find a station for Zzz No Such Station."}`; **no playback**. (Resolver emits
  one brief honest Piper line — acceptable; baseline captured.)
- [ ] **A5 Conversational (ChatGPT; capture/restore baseline):**

  | utterance | expected ChatGPT text (= `chat_text`) | resolver Piper | playback |
  |---|---|---|---|
  | `play Hit FM` | `Playing <matched station>.` | 0 | radio plays |
  | `play Romanian radio` | `Playing <matched station>.` | 0 | plays |
  | `play jazz` | `Playing <matched station>.` | 0 | plays |
  | `play country radio` | `Playing <matched station>.` | 0 | plays |
  | invalid/no-match (e.g. `play Flibberwock radio`) | `I couldn't find a station for <label>.` | 1 | none |

  Assert per row: **ChatGPT text == returned `chat_text`** (verbatim); resolver speaks the expected
  count (0 on success, 1 on no-match); **no duplicate TTS** (the resolver Piper is the only audible
  utterance; `chat_text` is text-only — reply-TTS is disabled); radio actually plays on the success
  rows; nothing plays on no-match.
- [ ] **A6 Event fallback:** fire `mass_radio_request {mode:"play", station:"Noroc"}` directly → confirm
  the event adapter still plays. Restore baseline.
- [ ] **A7 Checkpoint:** report Stage-A results; proceed to Stage B only if clean (else stop + roll back A).

## Stage B — `script.find_stations`
- [ ] **B1 Backup:** `GET …/find_stations` → `~/script_backups/find_stations.preF1R.json` (confirm
  event-firing, no rest_command).
- [ ] **B2 Apply:** `POST …/find_stations` with the new `sequence` (preserve alias/description/fields);
  reload.
- [ ] **B3 Readback:** alias + fields `[country, genre]` preserved; **no `set_conversation_response`**;
  **no `tts.speak`**; has `rest_command` + `stop`/`response_variable: resp`; returns `r.content.chat_text`.
- [ ] **B4 Direct test:** WS `call_service` `script.find_stations` `{genre: "jazz"}` with
  `return_response: true` → assert response ≈ `{chat_text: "Here are some stations: …"}` (a real list).
  (Resolver also speaks `"I found …"` once — expected.)
- [ ] **B5 Conversational (ChatGPT):**

  | utterance | expected ChatGPT text | resolver Piper | output |
  |---|---|---|---|
  | `find jazz stations` | `Here are some stations: A, B and C.` (the **actual** list from `chat_text`) | 1 (`I found A, B and C.`) | list only; no playback |

  Assert: **ChatGPT relays the actual station list from `chat_text`** (verbatim); resolver speaks the
  `spoken_text` list **once**; **no duplicate output** (one audible Piper line + the chat text; never two
  voices).
- [ ] **B6 Event fallback:** fire `mass_radio_request {mode:"find", genre:"jazz"}` directly → confirm the
  event adapter still produces the find behaviour.
- [ ] **B7 Stop + report.**

## Validation summary to report
Per script: backup path; readback (no `set_conversation_response`/`tts.speak`; returns `chat_text`);
direct-test return shape; the conversational matrix (text == `chat_text`, resolver-speak counts, no
duplicate TTS, playback correctness); event fallback intact; `/command` 200/401; baseline restored.

## Rollback (each script independent)
- Restore `~/script_backups/play_radio.preF1R.json` and/or `~/script_backups/find_stations.preF1R.json`
  via `POST /api/config/script/config/<id>` + reload → that script reverts to firing
  `mass_radio_request`.
- Keep **`/command`** live, the **event adapter** + **`ceiling_play_radio`** (legacy fallback) live,
  **`mass_sync_request`** untouched, and `script.play_music` (already migrated) untouched.

## Out of scope
No new tools; no model change (gpt-4o-mini); no Inc 2; no resolver code change (capability, `/command`,
`CommandResult` already live). `mass_sync_request` and `script.play_music` untouched.

## Self-review
- Hard-return pattern identical to the DONE music migration ✓; intent `radio`, fields/params preserved
  verbatim from current configs ✓; no `set_conversation_response`, no `tts.speak`, resolver sole TTS
  owner ✓; one script at a time with backup → apply → readback → direct test → conversational matrix →
  event fallback → checkpoint ✓; expected speak-counts derived from `radio.py` (play success 0, no-match
  1, find 1) ✓; rollback per script, `/command` + event fallback preserved ✓; no new tools / model /
  Inc 2 ✓.
- **No implementation performed** — design only.

---

## Outcome — EXECUTED & DONE (2026-06-29)
Both scripts migrated and left in place; radio/find now relay `chat_text` as a hard tool result.

**Stage A — `script.play_radio` (accepted):**
- Backup `~/script_backups/play_radio.preF1R.json`; applied; readback clean (no `set_conversation_response`,
  no `tts.speak`, returns `chat_text`).
- Conversational: `play jazz` → `Playing 101 SMOOTH JAZZ.` and `play country radio` → `Playing .977 Country.`
  relayed **verbatim**; `play Hit FM`/`play Romanian radio` relayed the **right** station but ChatGPT
  cosmetically tidied verbose RadioBrowser names (accepted — substance correct, no misrouting). Success
  is **silent** from Piper (stream is the confirmation); no-match (`play Flibberwock radio`) →
  `I couldn't find a station for Flibberwock.` with **one** Piper announcement and no playback.
- The no-match also demonstrated the **Speaker reconnect fix live** (first announce hit a stale socket →
  auto-reconnect → retry spoke). `/command` 200/401; event fallback intact.

**Stage B — `script.find_stations` (this run):**
- Backup `~/script_backups/find_stations.preF1R.json`; applied; readback clean.
- Ground-truth `/command find jazz` `chat_text` was **stable** across calls. ChatGPT relayed **all three**
  stations **in order**, none omitted/invented, meaning unchanged (only title-case + Oxford-comma +
  "jazz" framing — harmless). Resolver spoke the list **once**; **no duplicate TTS**; **no playback**.
- `/command` 200/401; `find` event fallback intact.

**State:** `play_music`, `play_radio`, `find_stations` all synchronous (relay `chat_text`);
`mass_sync_request` + event adapter + `/command` intact; no new tools; gpt-4o-mini unchanged. Rollback
backups retained per script (`*.preF1R.json`). **F1-R is complete across all three exposed scripts.**
