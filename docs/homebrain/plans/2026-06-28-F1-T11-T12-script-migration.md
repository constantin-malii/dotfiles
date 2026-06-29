# F1 T11/T12 — HA Script Migration to Synchronous `/command` (Plan)

> **Design only — do NOT implement. Stop for approval before modifying any production script.**
> Parent: `2026-06-28-F1-synchronous-command-result-design.md` + `plans/2026-06-28-F1-synchronous-command-result.md`.

## Goal
Migrate the three exposed HA scripts from fire-and-forget events to the synchronous resolver
`/command` endpoint, so ChatGPT relays the real `CommandResult.chat_text`. Resolver stays the **sole
TTS owner**; scripts never call `tts.speak`. Additive/reversible; event adapter + `ceiling_play_radio`
stay live.

- **T11:** migrate `script.play_music`.
- **T12:** migrate `script.play_radio`, then `script.find_stations`.
- **Step P (separate):** deploy the already-committed music `PLAYING`-log fix (`11a53cc`). Kept clearly
  apart from the script-migration steps.

## Latency (measured 2026-06-28, drives the timeout)
- music play `/command`: 0.06–0.44 s · no-match: 0.03 s
- **radio favorite: median ~2 s** (1.1–3.8 s) · **RadioBrowser fallback: median ~3 s** (2.1–4.5 s)
- One earlier **27 s** radio case is treated as an **outlier** (momentary MA/stream startup), not the norm.
- **Decision:** keep a **30 s** `rest_command` timeout as safety margin; do not change `execute`
  semantics (synchronous play is fine at these latencies).

## TTS ownership in context (why there is no duplicate speech)
The voice pipeline is configured for **text-only replies** (reply-TTS disabled; see
`music-assistant-audio-architecture.md`/ONBOARDING). So:
- The **resolver `Speaker` (Piper)** speaks `spoken_text` during the `/command` call — the **only**
  audible output, exactly once.
- `chat_text` is surfaced to ChatGPT/the user as **text** (not re-spoken by the pipeline).
Validation therefore checks: **one** audible utterance (resolver) + `chat_text` as text. Scripts must
**not** call `tts.speak` (a second utterance) — that's the rule this migration enforces.

## Prerequisite (manual HA YAML — you do this once, like T9)
The existing `rest_command.resolver_command` (added in T9) uses the **default 10 s** timeout. Add a
30 s timeout and reload:
```yaml
rest_command:
  resolver_command:
    url: "http://192.168.122.1:8770/command"
    method: POST
    timeout: 30            # <-- add this (safety margin for the rare radio spike)
    content_type: "application/json"
    headers:
      X-Resolver-Key: !secret resolver_http_secret
    payload: >-
      {"intent": "{{ intent }}", "params": {{ params | default({}) | tojson }}}
```
Reload: Developer Tools → YAML → "RESTful Command". (No resolver restart needed for this.)

## ⚠️ Primary risk → T11 Gate G1 (must pass before any further migration)
It is **not yet proven** that a script *tool* call from the **OpenAI agent** surfaces
`set_conversation_response` (i.e., that ChatGPT actually relays `chat_text`). T9 proved a *script* can
**capture** the rest_command response; it did **not** prove the captured text reaches **ChatGPT** when
ChatGPT invokes the script as a tool. **Gate G1** (first T11 conversational test) confirms this. If
ChatGPT does **not** relay `chat_text`, **STOP and escalate** for a design addendum (e.g., return the
text as the script's tool *response* rather than `set_conversation_response`) — per the project rule,
do **not** speculatively build alternative mechanisms.

---

## Step P — Deploy the music `PLAYING`-log fix (separate from migration)
Repo commit `11a53cc` re-added `PLAYING`/dry-run/failed log lines in `music.py`. This is a **resolver**
change (needs a restart), independent of the HA-script migration.
- [ ] Back up host `music.py` → `~/mass-resolver/.f1bak/music.py.plog.bak` (or confirm `.f1bak/music.py` Inc-1 backup exists; the F1 `music.py` is already live).
- [ ] Deploy: `cat music.py | ssh costea@192.168.1.68 "cat > ~/mass-resolver/music.py"`; `python3 -c "import music"` parse/import check.
- [ ] You run: `sudo systemctl restart mass-resolver`; confirm `SERVICE: connected …` + `/command HTTP server …` in the log.
- [ ] Verify a music play now logs a `PLAYING` line (fire `mass_play_request` or `/command` music; grep log).
- **Rollback:** redeploy the previous `music.py` (from `.f1bak`) + restart.
- Do this **before T11** (so migration validation has the logs) but as its own gated step.

---

## T11 — Migrate `script.play_music`

### Steps
- [ ] **Backup:** `GET /api/config/script/config/play_music` → save to `~/script_backups/play_music.json` (host) AND note it for rollback. Preserve the current `alias`, `description`, `fields` (query, media_type), `icon` — change ONLY the `sequence`.
- [ ] **Edit:** `POST /api/config/script/config/play_music` with the same config but this `sequence`:
```json
[
  {"action": "rest_command.resolver_command",
   "data": {"intent": "music",
            "params": {"query": "{{ query | default('', true) }}",
                       "media_type": "{{ media_type | default('', true) }}"}},
   "response_variable": "r", "continue_on_error": true},
  {"set_conversation_response": "{{ r.content.chat_text if (r is defined and r.content is defined and r.content.chat_text is defined) else 'Sorry, I could not reach the music system.' }}"}
]
```
(No `tts.speak`. `continue_on_error` so a timeout/failure still yields a graceful spoken-by-resolver + text reply.)
- [ ] **Read back:** `GET` the config; confirm the sequence is the rest_command version and fields/alias/description are intact.
- [ ] **Controlled test (no ChatGPT):** call `POST /api/services/script/play_music` with `{query:"Du Hast", media_type:"track"}`; confirm it plays + the resolver speaks per `/command`; capture/restore station+volume.
- [ ] **Conversational validation matrix** (`/api/conversation/process` → `conversation.openai_conversation`), capture/restore baseline:

| Test | Expect |
|---|---|
| **G1: `play Rammstein`** | plays Rammstein; **ChatGPT reply conveys `chat_text` ("Playing Rammstein.")** ← *the gate* |
| `play My Way` | no local match; ChatGPT reply conveys "isn't in your local library" (matches `chat_text`); resolver Piper says the honest line **once** |
| confirm ChatGPT text matches `chat_text` | reply == the `/command` `chat_text` (or faithfully conveys it) |
| confirm resolver speaks exactly once | exactly one `ANNOUNCE` per command in the log; no second utterance |
| confirm no duplicate TTS | only the resolver speaks (pipeline reply is text-only); script has no `tts.speak` |
| confirm event-path fallback still exists | fire `mass_play_request` directly via `/api/events` → still plays (event adapter alive); backup restores event-firing |

- [ ] **If G1 fails** (ChatGPT doesn't relay `chat_text`): **STOP, roll back, escalate** (investigate returning text as the script tool *response*). Do not proceed to T12.
- [ ] **Rollback (T11):** `POST /api/config/script/config/play_music` with `~/script_backups/play_music.json` (restores event-firing). `/command`, the event adapter, `mass_sync_request`, and `ceiling_play_radio` all remain untouched.
- [ ] **Stop & report** before T12 if anything is abnormal.

---

## T12 — Migrate `script.play_radio`, then `script.find_stations` (one at a time)

### T12a — `script.play_radio`
- [ ] **Backup** → `~/script_backups/play_radio.json`. Preserve alias/description/fields (station, country, genre, language)/icon; change only `sequence`:
```json
[
  {"action": "rest_command.resolver_command",
   "data": {"intent": "radio",
            "params": {"mode": "play",
                       "station": "{{ station | default('', true) }}",
                       "country": "{{ country | default('', true) }}",
                       "genre": "{{ genre | default('', true) }}",
                       "language": "{{ language | default('', true) }}"}},
   "response_variable": "r", "continue_on_error": true},
  {"set_conversation_response": "{{ r.content.chat_text if (r is defined and r.content is defined and r.content.chat_text is defined) else 'Sorry, I could not reach the radio system.' }}"}
]
```
(Empty-string params are treated as absent by the resolver's radio capability — it picks the non-empty target.)
- [ ] **Read back**; **controlled test** (`script.play_radio` with `{station:"noroc"}`) + capture/restore.
- [ ] **Conversational matrix** (capture/restore each):

| Test | Expect |
|---|---|
| `play Hit FM` | favorite by name → Hit FM (`library://radio/1`); ChatGPT conveys `chat_text` |
| `play Romanian radio` | country/language → a RO favorite; chat_text conveyed |
| `play jazz` | genre → 101 Smooth Jazz (favorite); chat_text conveyed |
| `play country radio` | RadioBrowser fallback (genre, no favorite) → a country-music station; chat_text conveyed |
| invalid station name (e.g. `play Wackadoodle FM`) | no match; resolver Piper says honest line once; ChatGPT conveys "couldn't find …" |

- [ ] **Rollback (T12a):** restore `play_radio.json`. **Stop & report** before find_stations if abnormal.

### T12b — `script.find_stations`
- [ ] **Backup** → `~/script_backups/find_stations.json`. Preserve alias/description/fields (genre, country)/icon; change only `sequence`:
```json
[
  {"action": "rest_command.resolver_command",
   "data": {"intent": "radio",
            "params": {"mode": "find",
                       "genre": "{{ genre | default('', true) }}",
                       "country": "{{ country | default('', true) }}"}},
   "response_variable": "r", "continue_on_error": true},
  {"set_conversation_response": "{{ r.content.chat_text if (r is defined and r.content is defined and r.content.chat_text is defined) else 'Sorry, I could not reach the radio system.' }}"}
]
```
- [ ] **Read back**; **controlled test** (`script.find_stations` with `{genre:"jazz"}`).
- [ ] **Conversational validation:**

| Test | Expect |
|---|---|
| `find jazz stations` | resolver Piper speaks the top-3 list **once**; **ChatGPT relays the actual station list** (the `chat_text`, e.g. "Here are some stations: …") |
| confirm ChatGPT relays the actual list | reply contains the real station names from `metadata.stations`/`chat_text` |
| confirm resolver speaks once | exactly one `ANNOUNCE` (the find list) per command |
| confirm no duplicate station list | only the resolver speaks the list; ChatGPT shows it as text; no second spoken list |

- [ ] **Rollback (T12b):** restore `find_stations.json`.

---

## Global rollback (any time)
- Restore the relevant `~/script_backups/<name>.json` via `POST /api/config/script/config/<name>` → script reverts to firing its event.
- **Keep live throughout:** `/command` HTTP server, the **event adapter** (`mass_play_request`/`mass_radio_request`), **`mass_sync_request`** (Lidarr — untouched), and **`ceiling_play_radio`** (legacy fallback — untouched, not exposed).
- Resolver code rollback (if ever needed): `~/mass-resolver/.f1bak/*` + remove the 4 F1 modules + restart → Inc 1; `resolver.py.orig` monolith remains.

## Out of scope (explicit)
- No new tools exposed to ChatGPT (same three scripts, same fields/descriptions).
- No GPT model change (gpt-4o eval stays gated behind F1 completion, only if tool-selection issues remain).
- Do not start Inc 2.

## Close-out (after T11+T12 pass)
- Update `assistant-capabilities.md` (play/find now synchronous; ChatGPT relays `chat_text`), `local-music-architecture.md` (the `/command` migration), and mark **F1 DONE** in the umbrella spec §7. Commit (docs-only). Retire the music/radio event-path triggers only if desired (optional; keeping them is harmless and is the rollback).

---

## Self-review
- Constraints covered: resolver sole TTS owner + no script `tts.speak` (sequences contain none; only `set_conversation_response`) ✓; `rest_command.resolver_command` + `response_variable` + 30 s + `X-Resolver-Key` ✓ (timeout prerequisite called out); per-script backup→edit→readback→controlled→conversational→rollback, one at a time with stop/report ✓; validation matrices included verbatim ✓; rollback preserves `/command`+event adapter+`mass_sync_request`+`ceiling_play_radio` ✓; no new tools/model change/Inc 2 ✓; latency documented (fav ~2 s, RB ~3 s, 27 s outlier, 30 s margin) ✓; PLAYING-log deploy included but separated (Step P) ✓.
- **Primary risk gated:** G1 verifies `chat_text` actually reaches ChatGPT for a script-tool call before committing to T12. If it fails → stop & escalate (no speculative fallback).
- **No implementation performed** — this document is design only.

---

## Outcome — T11 EXECUTED, Gate G1 FAILED, ROLLED BACK (2026-06-28)

Step P (PLAYING-log) and T11 (`script.play_music` migration) were executed on the host;
T12 was **not** started. Result:

- **Mechanically successful** — backup saved to `~/script_backups/play_music.json`; sequence
  replaced with `rest_command.resolver_command` (intent=music) + `response_variable r` +
  `set_conversation_response` from `chat_text`; alias/fields preserved; **no `tts.speak`**.
- **Resolver behavior correct** — `play Rammstein` → `/command` → played (restored `PLAYING` line
  present); `play My Way` → `/command` returned **HTTP 200** with the honest
  `chat_text="My Way isn't in your local library yet."`, `ok:false`, **no playback**, honest Piper line.
- **HA `response_variable` capture correct** — the script captured `r.content.chat_text` exactly
  (already proven in T9; reconfirmed here).
- **Gate G1 FAILED — the OpenAI Conversation agent ignores `set_conversation_response` for a
  script invoked as a tool.** Evidence:
  - `play My Way` → ChatGPT said `Playing "My Way."` (not the honest `chat_text`).
  - **Sentinel test (decisive):** forced the script's `set_conversation_response` to a unique string
    (`"Pineapple seven four one zero."`) and asked ChatGPT to play a guaranteed no-match. Resolver log
    confirms the tool **was** invoked, yet ChatGPT replied `Playing Zzzqqx Nonexistent Track.` — it did
    **not** echo the sentinel. ⟹ The G1 "pass" (`Playing Rammstein.`) was a **false positive**:
    ChatGPT composes its own generic `"Playing <query>."` reply and never surfaces the tool's returned
    conversation text. `set_conversation_response` is honored for the **Assist/sentence-trigger** agent,
    **not** for an OpenAI tool-call return.
- **Rolled back** — `script.play_music` restored from `~/script_backups/play_music.json` to the
  original event-firing version (`mass_play_request`; no `rest_command`/`set_conversation_response`/
  `tts.speak`). Verified: event path plays, direct `mass_play_request` plays, honest Piper feedback
  intact, `/command` live + authenticated (200/401), event adapter live, `mass_sync_request` /
  `play_radio` / `find_stations` untouched.
- **Follow-up to watch (not a regression of this work):** the no-match Piper announce hit an
  intermittent `BrokenPipeError` on the speaker socket twice on 2026-06-28 (it succeeded earlier the
  same day). The `Speaker` reconnect-once path should heal it; monitor.

**Conclusion:** the synchronous `/command` path and `CommandResult` are sound, but the **relay leg**
(getting `chat_text` into ChatGPT's mouth via `set_conversation_response`) is **proven insufficient**
on this HA + OpenAI integration. T12 is **not** attempted. Next step is the **F1-R** design addendum
(`2026-06-28-F1-R-chatgpt-tool-result-relay-design.md`): deliver `chat_text` as the actual **tool
result** rather than a conversation-response side effect.
