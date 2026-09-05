# F1-R — Music-Only Re-Migration (`script.play_music` → hard tool result) — Plan

> **Design only — do NOT implement. Stop for approval before modifying `script.play_music`.**
> Parent: [F1-R addendum](../2026-06-28-F1-R-chatgpt-tool-result-relay-design.md) (Phase-0 **PASS**) ·
> supersedes the relay leg of [T11/T12 plan](2026-06-28-F1-T11-T12-script-migration.md).

## Goal
Re-migrate **`script.play_music` only** to the synchronous resolver `/command` path, this time using the
**Phase-0-proven** relay: the script **returns** `{chat_text: …}` as its **tool result** via
`stop` + `response_variable` (NOT `set_conversation_response`, which T11 proved the OpenAI agent
ignores). Resolver stays the **sole TTS owner**; the script calls no `tts.speak`. Additive/reversible.

## Global constraints (binding — every task inherits these)
- Re-migrate **`script.play_music` only**. **`script.play_radio`** and **`script.find_stations`** stay on
  the **event path** (untouched).
- Use the already-live **`rest_command.resolver_command`** (intent=music) with **`response_variable`**.
- Script **returns** `{chat_text: r.content.chat_text}` via **`stop` + `response_variable`**.
- **No `set_conversation_response`.** **No `tts.speak`** in the script. Resolver = only TTS owner.
- Add exactly one line to the OpenAI agent's Instructions:
  *"When a tool returns a `chat_text` field, relay that text verbatim."*
- Keep **gpt-4o-mini** (no model change). **No new tools exposed.** **No Inc 2.**
- Python 3.5-safe everywhere; secrets only in 0600 files; no AI attribution in commits; secret-scan
  before any commit.

## Prerequisites (manual — you do these once, like the T9/T11 YAML steps)
1. **Agent instruction.** Settings → Devices & Services → **OpenAI Conversation** → the ChatGPT agent →
   **Instructions**: append the single line
   `When a tool returns a chat_text field, relay that text verbatim.`
   (Reversible: delete the line. This is prompt config, **not** a model change.) Phase-0 showed the
   `chat_text` is surfaced faithfully even without it; the line guarantees **verbatim** fidelity.
2. **`rest_command.resolver_command`** already exists (T9/T11) with `timeout: 30`, `X-Resolver-Key`,
   bound to `http://192.168.122.1:8770/command`. No change needed. Confirm it still loads.

After you confirm both, I proceed with the gated migration below (one script, API + reload).

## The new `script.play_music` sequence (exact)
Same `alias`/`description`/`fields` (`media_type`, `query`); **only the `sequence` changes** to:
```json
[
  {"action": "rest_command.resolver_command",
   "data": {"intent": "music",
            "params": {"media_type": "{{ media_type | default('', true) }}",
                       "query": "{{ query | default('', true) }}"}},
   "response_variable": "r",
   "continue_on_error": true},
  {"variables": {"resp": {"chat_text": "{{ r.content.chat_text if (r is defined and r.content is defined and r.content.chat_text is defined) else 'Sorry, I could not reach the music system.' }}"}}},
  {"stop": "done", "response_variable": "resp"}
]
```
Notes: `continue_on_error` keeps the script returning a graceful `chat_text` if `/command` is briefly
unreachable. No `set_conversation_response`; no `tts.speak`. The resolver speaks `spoken_text` (only on
failures/announcements) during the `/command` call — exactly once, owned by the resolver.

---

## Gate 1 — Back up current `script.play_music`
- `GET /api/config/script/config/play_music` → save to **`~/script_backups/play_music.preF1R.json`**
  (new file; leaves the T11 backup `~/script_backups/play_music.json` intact). The current production
  script is the **original event-firing** version (rolled back after T11), so this backup == the
  event-path rollback target.
- Confirm the backup contains `event: mass_play_request` and **no** `rest_command`.

## Gate 2 — Apply the music-only script change
- `POST /api/config/script/config/play_music` with the same config but the new `sequence` above
  (preserve `alias`, `description`, `fields`, `icon`).
- `POST /api/services/script/reload`.

## Gate 3 — Read back script config
- `GET /api/config/script/config/play_music`; assert:
  - `alias == "Play Music"`, `fields == {media_type, query}` (preserved).
  - sequence contains `rest_command.resolver_command`, `response_variable: r`, a `stop` with
    `response_variable: resp`.
  - **`"set_conversation_response"` absent**; **`"tts.speak"` absent**.
- Confirm the script entity is still **exposed** to `conversation` (exposure persists across reload).

## Gate 4 — Controlled direct script test (no audio)
Validate the **return shape** independent of ChatGPT, using a guaranteed **no-match** so nothing plays:
- WS `call_service` `script.play_music` `{query: "Zzz Direct Test"}` with **`return_response: true`**.
- Assert the returned `response` ≈ `{chat_text: "Zzz Direct Test isn't in your local library yet."}`
  (i.e., the script returns the resolver's `chat_text` as its service response).
- Resolver log shows a music no-match for that query (honest path); **no playback** starts.

## Gate 5 — ChatGPT Gate G1 (audible; capture/restore baseline)
Capture baseline (current station + volume) first; restore at the end.
- Ask `conversation.openai_conversation`: **`play Rammstein`**.
- Assert:
  - **ChatGPT text matches the returned `chat_text`** (expect "Playing Rammstein." — *verbatim*, given the
    agent instruction).
  - **Music plays** (MA now-playing = Rammstein).
  - **No duplicate TTS** — resolver emits **0** Piper announces on success (success `spoken_text` is null
    by design); ChatGPT text is the only surfaced confirmation. (Voice pipeline reply-TTS is disabled.)
  - **Restored PLAYING log line appears**: `req=… PLAYING …/artist/Rammstein (provider=filesystem_smb)`.

## Gate 6 — No-match test (audible feedback; baseline still captured)
- Ask: **`play My Way`**.
- Assert:
  - **ChatGPT says it is not in the local library** (relays `chat_text` "My Way isn't in your local
    library yet." — the T11 failure mode is now fixed).
  - **Resolver/Piper gives honest feedback exactly once** (one ANNOUNCE for the no-match `spoken_text`).
  - **No incorrect playback** starts (no PLAYING line for "My Way").
- Restore baseline (station + volume) after Gates 5–6.

## Gate 7 — Event-path fallback still works
- Fire `POST /api/events/mass_play_request {query:"Du Hast", media_type:"track"}` directly.
- Assert the **event adapter** still dispatches + plays (`SERVICE: event=mass_play_request …` + PLAYING).
  Restore baseline.

## Gate 8 — Stop after music-only validation and report
Report: backup path, readback (no `set_conversation_response`/`tts.speak`), Gate-4 return shape, Gate-5
G1 (text==chat_text, plays, single/zero TTS, PLAYING line), Gate-6 no-match (honest text + one Piper +
no playback), Gate-7 event fallback, `/command` health (200/401), baseline restored. **Do not** migrate
radio/find. **Stop for review.**

### Validation matrix
| Check | Expected |
|---|---|
| readback: `set_conversation_response` | absent |
| readback: `tts.speak` | absent |
| Gate 4 direct return | `{chat_text: "…isn't in your local library yet."}`, no playback |
| G1 ChatGPT text | == resolver `chat_text` ("Playing Rammstein.") |
| G1 playback | Rammstein playing |
| G1 Piper announces | 0 (silent on success) |
| G1 PLAYING log | present |
| no-match ChatGPT text | "…isn't in your local library yet." (honest) |
| no-match Piper | exactly 1 announce |
| no-match playback | none |
| event fallback | `mass_play_request` still plays |
| `/command` auth | 200 (good key) / 401 (no key) |

## Rollback
- Restore `script.play_music` from **`~/script_backups/play_music.preF1R.json`** (or the equivalent
  `~/script_backups/play_music.json`) → reverts to firing `mass_play_request`.
- Keep **`/command`** live, the **event adapter** live, **`mass_sync_request`** untouched, and
  **`script.play_radio` / `script.find_stations`** untouched.
- The agent-instruction line is inert once rolled back (play_music returns no `chat_text`); leave it or
  remove it — either is safe.

## Out of scope (explicit)
- No radio/find migration. No new tools. No GPT model change (gpt-4o-mini kept). No Inc 2.
- No resolver code change (the `/command`, `CommandResult`, capability lifecycle, and PLAYING log are
  already live).

## Self-review
- Constraints covered: music-only ✓; proven `stop`/`response_variable` hard return ✓; no
  `set_conversation_response` ✓; no `tts.speak`, resolver sole TTS owner ✓; one-line agent instruction
  (config, not model) ✓; gpt-4o-mini kept ✓; no new tools / no Inc 2 ✓; radio/find untouched ✓.
- Gates map 1:1 to the approved sequence (backup → apply → readback → direct test → G1 → no-match →
  event fallback → stop). Rollback preserves `/command` + event adapter + `mass_sync_request` +
  radio/find ✓.
- **No implementation performed** — this document is design only.

---

## Outcome — EXECUTED & DONE (2026-06-28)
All gates ran on the host; `script.play_music` is **left in the migrated state** (not rolled back).

- **G1 backup:** `~/script_backups/play_music.preF1R.json` (original event version) ✅
- **Apply + readback:** new sequence live; **no `set_conversation_response`**, **no `tts.speak`**;
  returns `{chat_text: r.content.chat_text}` via `stop`/`response_variable` ✅
- **Direct test (no playback):** `call_service … return_response` →
  `{'chat_text': "Zzz Direct Test isn't in your local library yet."}` ✅
- **Gate G1 — `play Rammstein`:** ChatGPT reply `Playing Rammstein.` = **exact `chat_text`** (verbatim
  relay via the new agent instruction); music played; **0 duplicate TTS**; restored PLAYING log present ✅
- **No-match — `play My Way`:** ChatGPT relayed the honest `chat_text` (`"My Way" isn't in your local
  library yet.`); **no incorrect playback** ✅ — *this is the exact T11 failure, now fixed.*
- **Event fallback:** `mass_play_request` still dispatches + plays ✅ · **`/command`** 200/401 ✅
- **Separate issue found (not F1-R):** the resolver's **Piper announce** was failing with
  `BrokenPipeError` after the mid-session HA restart — root cause: `haconn.HA.announce()` swallows the
  send error so `Speaker.speak()`'s reconnect-once never fires. Recovered immediately by a resolver
  restart (announce verified working again). Permanent fix tracked separately:
  [plans/2026-06-28-speaker-reconnect-bugfix.md](2026-06-28-speaker-reconnect-bugfix.md).

**Verdict:** F1-R music-only migration **DONE** — ChatGPT now relays `CommandResult.chat_text` as the
hard tool result. Radio/find remain on the event path (not migrated).
