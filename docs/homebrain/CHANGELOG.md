# Homebrain Change Log

Operational/administrative changes to the homebrain setup. (Architecture and feature
design live in the per-topic docs; this log is for discrete operational changes.)

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
