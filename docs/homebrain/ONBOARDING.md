# Homebrain / Home Assistant — Agent Onboarding

> **START HERE.** This is the primary entry point for any agent working on the homebrain Home Assistant / Music Assistant / ceiling-speaker stack. Read §1–§7 to be productive in ~15 minutes; read §8–§13 before touching the Music-Assistant playback problem (it has a long investigation history — don't re-run dead ends). Authoritative deep doc: [`music-assistant-audio-architecture.md`](./music-assistant-audio-architecture.md). **The current production architecture (resolver + Inc 0–1 + F1-R) is summarized in the _Resolver / Inc 0–1 / F1-R current state_ section immediately below — read that first; §8–§13 are YTM-playback history, not today's exposed capabilities.** Latest running status lives in the agent memory log (see §14).

---

## Resolver / Inc 0–1 / F1-R current state

> **Current production reality — read before the YTM/playback-lock history in §8–§13.** That history is about **YTM track** playback (still unexposed); it does **not** describe today's exposed capabilities.

A host-side **`mass-resolver`** service (Python 3.5, on the host `costea@192.168.1.68`) is the brain behind the ChatGPT-exposed media tools. It reaches Music Assistant + HA over the host↔VM NAT network and exposes an **authenticated HTTP `/command`** endpoint on the internal interface the HA VM can reach (`192.168.122.1:8770`; `X-Resolver-Key` shared secret in a 0600 file — never logged/committed). HA calls it via `rest_command.resolver_command`.

- **Increments:** Inc 0 (local music play) ✅, Inc 1 (radio play + station find) ✅, and **Foundation F1 + F1-R** (synchronous results) ✅ — all complete.
- **Contract:** every capability returns a **`CommandResult`** (`ok` / `spoken_text` / `chat_text` / `metadata` / `error{code,reason}`) via a **`resolve → validate → execute`** interface.
- **Exposed ChatGPT tools (all synchronous — F1-R "hard tool return"):**
  - `script.play_music` — play from the **local** music library (MA `filesystem_smb`).
  - `script.play_radio` — radio (favorites-first → RadioBrowser; by station/genre/country/language).
  - `script.find_stations` — list stations (genre/country).
  - Each calls `rest_command.resolver_command`, captures `response_variable`, and **returns `{chat_text: r.content.chat_text}` via `stop` + `response_variable`** so the OpenAI agent relays the real outcome. The agent carries one instruction: *"When a tool returns a chat_text field, relay that text verbatim."*
- **TTS ownership:** the **resolver is the sole TTS owner** (Piper speaks `spoken_text`). The scripts do **NOT** call `tts.speak` and do **NOT** use `set_conversation_response` (proven ignored by the OpenAI agent for tool-called scripts — see the F1-R addendum). Play success is silent (the stream is the confirmation); no-match and find speak once.
- **Dual-path kept:** the **event adapter** (`mass_play_request` / `mass_radio_request`) remains live as a fallback; **`mass_sync_request`** (Lidarr) is **untouched**.
- **Rollback:** per-script backups at `~/script_backups/*.preF1R.json`; restoring one reverts just that script to its event path while `/command` and the event path stay available. `gpt-4o-mini` unchanged; no new tools beyond the three above.

Authoritative F1 / F1-R / capabilities / local-music / CHANGELOG docs: see §14.

---

## 1. The system at a glance

- **Host:** `homebrain`, Ubuntu 16.04.7, `costea@192.168.1.68`. Runs **Plex** + a legacy **HA Core 0.57.2** venv (both untouched — do not modify) and a **KVM/libvirt VM**.
- **HAOS VM:** libvirt domain **`haos`** (qemu:///system), HAOS 18.0 / **HA Core 2026.6.4**, 4 GiB / 3 vCPU, autostart on. The **primary** Home Assistant.
  - **macvtap NIC → `192.168.1.104`** (the LAN IP you reach HA on).
  - **NAT NIC → `192.168.122.10`** (host↔VM only; see networking gotcha).
- **Music Assistant:** add-on `d5369777_music_assistant` **v2.9.3**, UI/API at `http://192.168.1.104:8095`. Plays to **ceiling speakers** via a **Squeezelite** systemd service on the host (`squeezelite-ceiling.service`, ALSA `hw:1,0`).
- **Audio path:** MA (VM) → SlimProto/HTTP stream over NAT `192.168.122.10` → Squeezelite (host) → ceiling speakers.
- **Voice satellite (2026-07-14):** `reSpeaker Living Room` — Seeed **reSpeaker XVF3800 + XIAO ESP32-S3**,
  ESPHome (formatBCE firmware), on-device wake word **"Okay Nabu"**, LAN Wi-Fi. Entities
  `assist_satellite.respeaker_living_room_assist_satellite` + `media_player.respeaker_living_room_media_player`.
  Uses a dedicated **"Living Room Voice"** pipeline (Whisper STT + Piper TTS). **No built-in speaker** (3.5mm /
  JST). See `CHANGELOG.md` 2026-07-14. (Not yet assigned to an HA area.)
- **HA Internal URL:** `http://192.168.1.104:8123` (LAN) — set 2026-07-14. Previously auto-detected to the NAT
  IP `192.168.122.10:8123`, which LAN devices (phone/satellite) can't reach.

---

## 2. Connectivity (how to actually reach things)

| Target | From your machine | Notes |
|---|---|---|
| **HA REST/WS** | `http://192.168.1.104:8123` ✅ | LAN-reachable. Needs an HA token (below). |
| **MA API** | `http://192.168.1.104:8095` ✅ | `/info` open; `/ws` needs an **MA account token** (HA token is rejected). |
| **SSH to host** | `ssh costea@192.168.1.68` ✅ | **Must use ssh-agent:** `ssh-add ~/.ssh/id_homebrain` first — direct `-i` fails ("we did not send a packet"). |
| **NAT IP `192.168.122.10`** | ❌ from your machine/LAN | Reachable **only from the host**. The MA→Squeezelite audio **stream** uses this IP. (HA's **TTS/media base URL moved off this to the LAN IP** on 2026-07-14 — Internal URL fix; see §1/§12.) |
| **Into the HAOS VM shell / its Docker** | ❌ | No SSH into the VM. You only have the host shell + HA/MA APIs. |

**Tokens (secrets — never commit):**
- **HA long-lived token:** a temporary diagnostic token has been used throughout (kept active per the user). Not stored in any file/repo. Ask the user for it, or create a fresh one in HA → Profile → Long-Lived Access Tokens (revoke when done).
- **MA token:** the MA API `/ws` needs the MA account token. Ask the user; they write it to `scratchpad/.ma_auth` as `token:<value>` for the session and delete after. HA tokens do **not** authenticate to MA.

**sudo on host:** requires a password + TTY (not NOPASSWD). Can't run non-interactively — have the **user** run it via `! ssh -t costea@192.168.1.68 'sudo ...'`. Read-only host commands run fine over agent SSH.

---

## 3. Tooling / how to drive it

- **No CLI helpers** — interact via APIs from Python (raw-socket WebSocket clients; no extra libs):
  - **HA REST:** `/api/states`, `/api/services/<domain>/<svc>` (`?return_response=true` for response data), `/api/config`, `/api/conversation/process`, `/api/hassio/addons/<slug>/logs`.
  - **HA WS:** `ws://192.168.1.104:8123/api/websocket`. **Large messages span multiple frames** — accumulate continuation frames (opcode 0) until FIN or JSON parse fails.
  - **MA WS:** `ws://192.168.1.104:8095/ws`. `{"command":..., "message_id":"N", "args":{...}}`; first msg is server-info; **send `{"command":"auth","args":{"token":...}}` first**. Useful: `players/all`, `players/get`, `config/players/get`, `config/players/save`, `player_queues/get`, `players/cmd/stop`.
    - **Auth without a user handoff:** the resolver's own MA account token lives on-host at **`~/mass-resolver/.ma_token`** (0600) — read it into a shell var on-host and auth with it (never echo it). No need to ask the user for the MA token for host-run WS work. Unauthenticated commands return `error_code 20` "Authentication required". From the host, target the NAT base `http://192.168.122.10:8095/ws` (aiohttp WS is available on the host's Python 3.5).
    - **Provider config management (verified 2026-07-17):** `config/providers` (list all `ProviderConfig`), `config/providers/get {instance_id}`, `config/providers/save {provider_domain, instance_id, values}` (admin), `config/providers/remove {instance_id}`, `config/providers/reload {instance_id}`. **Disable a provider** = `config/providers/save` with `values:{"enabled":false}` → MA `unload_provider` (does NOT re-mount); re-enable with `{"enabled":true}`. Used to disable the mis-pathed `filesystem_smb--yYrXcamj` (see CHANGELOG 2026-07-17). **Deep DEBUG/VERBOSE tracing is NOT reachable** via the HA `/logs` proxy (INFO-only) and there is no VM/Docker shell for the MA container — so SlimProto `strm`/`STM` traces can't be captured through current access.
- **Long ops:** Bash tool **times out at 2 min** and **foreground `sleep` is blocked**. Run multi-minute tests with `run_in_background: true`, write results to a scratchpad file, then read it. (MA plays take 90–150 s.)
- **Windows console:** emit **ASCII only** — non-ASCII throws `UnicodeEncodeError`. Wrap with `.encode("ascii","replace")`.
- **MA `/logs` proxy is inconsistent/stale** — sometimes a cached/short buffer; before/after diffs can return empty. Re-fetch fresh tail.
- **Supervisor API mostly blocked** via Core proxy: `/api/hassio/<slug>/logs` works; `/info`, `/stats`, `/options`, `resolution`, `host`, `network` → **401**. `/hassio` frontend panel **404** (known, parked).
- **Commits:** repo **`D:\repos\dotfiles`** (docs under `docs/homebrain/`). **Secret-scan before committing**; **omit Claude/AI attribution**; commit only when asked; keep doc commits separate from config/implementation changes.

---

## 4. Key IDs & entities

- **Player:** `media_player.ceiling_speakers` = MA **Universal player** `upf8b156c25101`. Child **Squeezelite protocol player** `f8:b1:56:c2:51:01` (type=protocol, provider=squeezelite) — **no queue, not an HA entity**; you cannot play to it directly / bypass the Universal player.
- **Config entries:** Music Assistant `01KVPNW1JFHJG30NANAPVARHY8`; OpenAI Conversation `01KVRQW1ERJGJDRPC4MEF7206A`.
- **Assist pipelines:** default/preferred **"Home Assistant"** `01kvpdchwfeh0wa8p7d4bcywj4` (deterministic, STT=faster-whisper, TTS off); **"ChatGPT"** `01kvs55xvmsz0yy27hj7bkaygg` (OpenAI, opt-in).
- **Conversation agents:** `conversation.home_assistant`, `conversation.openai_conversation` (gpt-4o-mini).
- **ChatGPT-exposed media tools (resolver-backed — F1-R hard tool return):** `script.play_music` (local library), `script.play_radio` (radio), `script.find_stations` (station list). See the **Resolver / Inc 0–1 / F1-R current state** section.
- **Local ceiling control / fast-phrase layer (`script.ceiling_*`):** `pause`, `resume`, `stop`, `set_volume`, `volume_up`, `volume_down`, `announce` (TTS primitive, **not** LLM-exposed), plus the legacy `ceiling_play_radio` (kept for the deterministic sentence-trigger layer; **un-exposed** to ChatGPT).
- **Automations:** `automation.voice_ceiling_speakers` (phone voice handler — don't modify casually); `automation.ma_auto_reload_integration_after_restart` (A1); `automation.ma_health_probe_auto_reload` (A2a).

---

## 5. What works (reliable)

- ✅ **Ceiling speaker zone** — radio plays instantly and reliably.
- ✅ **Local music + radio via the resolver (synchronous, F1-R)** — `script.play_music` (local library), `script.play_radio`, `script.find_stations`; ChatGPT relays the real `chat_text`. See the **Resolver / Inc 0–1 / F1-R current state** section.
- ✅ **Phone voice control (Phase 2)** — Companion app → Whisper STT → `automation.voice_ceiling_speakers` → ceiling. **Text replies only** (Piper TTS disabled in pipeline). Generic spoken-number volume parsing.
- ✅ **ChatGPT/OpenAI assistant** — separate "ChatGPT" pipeline; runs the exposed resolver media tools (`play_music`/`play_radio`/`find_stations`) and the ceiling control scripts, and reads `weather.forecast_home` only. `expose_new_entities` off. Deterministic assistant stays default.
- ✅ **Ceiling TTS announcements** — `tts.speak` (tts.piper) → `media_player.ceiling_speakers` (`script.ceiling_announce`). MA announcements **resume prior playback** afterward (so no "stop" confirmation).
- ✅ **A1 + A2a self-healing** — HA↔MA connection drops intermittently (internal Docker DNS); these auto-reload the config entry to recover (validated).
- ✅ **YTM auth + search** — after refreshing the cookie via the **incognito method** (extract from a private window, close it without logging out). Search resolves `ytmusic://` URIs for track/artist/album/playlist. Artist/album/playlist queries reliable; multi-word **track-name** queries often return 0 (use simpler terms or artist).

---

## 6. What's broken / limited (with status)

- ⚠️ **YTM track *playback* is not LLM-grade and NOT exposed to the LLM.** See the full investigation in §8–§13. Summary: **stop-wedge** (Squeezelite stuck `playing` after stop; HTTP/1.0 root cause) + **cold-start latency ~95–150 s**.
- ⚠️ **YTM cookie rotates** — re-extract via incognito when YTM returns nothing.
- ⚠️ **Piper TTS** crashes the Assist pipeline → TTS **off** in pipelines; only explicit `tts.speak` to ceiling works. Whisper STT fine (model `auto`/sherpa-parakeet; couldn't pin tiny-int8). **Update 2026-07-14:** Piper TTS **runs fine in the new "Living Room Voice" satellite pipeline** (spoken replies confirmed on the reSpeaker) — the old crash may be version-stale; the shared HA/phone pipelines still keep TTS off pending a re-test.
- ⚠️ **HA↔MA connection** drops after MA restarts / intermittently (internal DNS). Recover: `POST /api/config/config_entries/entry/01KVPNW1JFHJG30NANAPVARHY8/reload`. A1/A2a automate this.
- ⚠️ **MA stuck playback lock** ("previous holder appears stuck") — consequence of the stop-wedge; clears on MA restart; `players/cmd/stop` does **not** reliably clear it.

---

## 7. Reliable recipes / cheatsheet

> ⚡ **After a reboot / "ChatGPT can't reach music/radio" → [`runbooks/quick-connect-and-health-check.md`](runbooks/quick-connect-and-health-check.md).** It has the SSH connect pattern (key `~/.ssh/id_homebrain` via ssh-agent + `timeout`/keepalive), a one-shot **read-only** stack health check (VM · resolver · `/command` bind + 200/401 · MA · HA · event path — using the resolver's own on-host secret, no token needed), and the cold-boot `/command` bind-race triage. Recovery steps there need user approval.

- **Play YTM reliably:** `music_assistant.search` → top result's `uri` → `music_assistant.play_media(media_id=uri)` → nudge `media_player.media_play`. (Free-text `play_media` unreliable; cold-start latency still applies.)
- **Recover HA↔MA:** reload the MA config entry (above), wait ~15 s.
- **After a power outage / host reboot (ChatGPT "can't reach music/radio"):** the `mass-resolver` `/command` server can lose its startup bind race with the libvirt bridge (`OSError 99, Cannot assign requested address` → logs "continuing event-only"; the event path still works but the three `/command` tools return the fallback). Fix: once the VM is up, `sudo systemctl restart mass-resolver`, then confirm `SERVICE: /command HTTP server on 192.168.122.1:8770` in `~/mass-resolver/resolver.log` and `/command` returns 200 (good key) / 401 (no key). Durable self-heal is planned — see `plans/2026-07-01-command-bind-retry-bugfix.md`.
- **Clean MA state for a test:** `POST /api/services/hassio/addon_restart {"addon":"d5369777_music_assistant"}`, then **wait ~130–140 s** for providers (esp. YouTube Music) to load — early plays fail with "No playable items found."
- **VM management from host:** `ssh-add ~/.ssh/id_homebrain` then `ssh costea@192.168.1.68 'virsh -c qemu:///system <dominfo|start|shutdown|reboot> haos'`.
- **Host/VM CPU:** host `top -bn1 | grep %Cpu`; VM CPU% from `virsh -c qemu:///system domstats haos --cpu-total` (`cpu.time` ns delta ÷ wall ÷ 3 vCPUs). MA **container** CPU/mem **unavailable** (stats proxy 401, no VM shell).
- **Testing discipline:** always test from a **clean state** (restart + wait); wait until a track is **genuinely `playing` with the right title** (not just `state==playing`, which can be stale); avoid rapid back-to-back plays (trigger the lock cascade).

---

## 8. Investigation Timeline

Chronological summary of major investigations. Status: ✅ resolved · 🟡 partially resolved · 🔴 open.

| Phase | Problem | Root cause found | Fix implemented | Status |
|---|---|---|---|---|
| **Voice "Oops" failures** | Assist returned "Oops, an error has occurred" on voice commands | (a) Built-in intents on **exposed** media_players called unsupported `media_player.turn_off` (`ServiceNotSupported`); (b) Piper TTS crashed the pipeline | Un-exposed the media_players (the conversation-trigger automation is the sole handler); set pipeline **TTS = off** | ✅ resolved |
| **Whisper / Piper** | Suspected STT/TTS as the failure cause; Whisper model couldn't be pinned | Whisper was **not** the cause (exonerated by log correlation). Piper **does** crash the pipeline. Whisper model stuck on `auto` (sherpa-parakeet) — add-on options unwritable (no `ha apps options`, `/hassio` panel missing, Supervisor options API 401) | STT left on faster-whisper (works); Piper TTS disabled in pipeline; ceiling TTS done via explicit `tts.speak` instead | 🟡 partial (STT works; Piper-in-pipeline still broken, model not pinned) |
| **HA ↔ MA connection instability** | `music_assistant.search`/`play_media` intermittently hang/time out; integration reports `loaded` but is silently dead | Integration's connection to `ws://d5369777-music-assistant:8094` drops (internal Docker DNS) and **does not auto-reconnect**. Two drop types: **restart drops** (player → `unavailable`) and **silent drops** (player stays `idle`). Connection is rock-solid once established (20/20 probes <30 ms / 10 min) | **A1** `ma_auto_reload_integration_after_restart` (reload on HA start + 120 s after MA returns from restart) + **A2a** `ma_health_probe_auto_reload` (3-min active search probe → reload on failure; no token). Both validated | ✅ resolved (self-heals) |
| **OpenAI assistant integration** | Add a ChatGPT assistant without breaking the deterministic one or over-exposing entities | n/a (greenfield) | Separate **OpenAI Conversation** integration (gpt-4o-mini) + separate **"ChatGPT" pipeline**; deterministic "Home Assistant" stays default; exposure locked to 7 ceiling scripts + weather; `expose_new_entities` off; removed auto-created stt/tts/ai_task subentries | ✅ resolved (text-tested; phone-mic test pending) |
| **YouTube Music authentication** | YTM provider failed to load / returned no results ("cookies no longer valid", "does not have Premium") | YouTube **rotates/invalidates** the login cookie; plain-browser cookies degrade fast | Re-extract the cookie from an **incognito/private window closed without logging out** (user does this in MA UI). PO token generator is healthy and not the issue | 🟡 partial (works after refresh; **cookie rotation recurs** — periodic re-extraction needed) |
| **Playback lock investigation** | `play_media` hangs ~90 s+; "previous holder appears stuck"; track never starts | The **stop-wedge**: `media_stop` of any live stream (radio **or** YTM) leaves the **Squeezelite protocol player stuck `state=playing`** while the Universal player goes `idle`. The stuck stream holds the lock → 30 s lock timeouts → aborts. Trigger isolated to **stop on a live stream** (not YTM-specific, not switch/pause/next/announce). `players/cmd/stop` doesn't release it | None that fully works (see HTTP-profile row). Workarounds: avoid rapid plays; MA restart clears it | 🔴 open |
| **HTTP profile experiments** | Can a Squeezelite `http_profile` value stop the wedge? | Squeezelite client speaks **HTTP/1.0**. `chunked` clears the wedge (terminating chunk = clean end-of-stream) **but breaks playback** — MA's `serve_queue_flow_stream` returns **HTTP 500** ("chunked encoding forbidden for HTTP/1.0"). `forced_content_length` avoids the 500 (plays) **but still wedges on stop**. `no_content_length` plays but wedges | **Reverted to `no_content_length`** (baseline). No single value fixes both | 🔴 open (root constraint = HTTP/1.0) |
| **YTM latency breakdown** | Why ~150 s to start a track? | Resolution is **fast (~14 s)** and **not CPU-bound** (VM ~5 %, host idle). The ~80 s gap is **post-resolution lock/stream-setup wait** (not deno/CPU). **Cached replay ~2 s** | n/a (diagnostic) — start latency is dominated by the stop-wedge lock contention on cold plays | 🟡 understood (tied to the open stop-wedge) |

---

## 9. Current Hypotheses (ranked)

For the **open** stop-wedge / playback-lock problem. See [`research-playback-lock.md`](./research-playback-lock.md) (source-traced tree **+ the 2026-06-24 empirical refutation**).

> ⚠️ **REFUTED, then ROOT CAUSE FOUND (2026-06-24).** (1) A VERBOSE trace of **6/6 clean radio play→stop cycles** showed every stop returns to `idle` via **`STMf`** → the `power(False)` / "only STMu" hypotheses (H1/H1b below, kept for history) are **wrong**; the clean stop path works. (2) An **interrupted-state experiment** (6 conditions) found the **real, reproducible defect: the slow YTM stream-resolution holds the player playback lock for its entire ~14–150 s duration.** Any command overlapping that window (stop / 2nd play / radio / announce / clear) blocks 30 s → **"previous holder appears stuck"** (reproduced in all 6 conditions; worst c4=11 timeouts). The lock is **held-during-resolution, not dead** — it releases when resolution finishes; **no persistent state mismatch reproduced** (states converge). So the earlier "permanent wedge" was this transient ≤30–60 s lock-contention window. **This is also the cold-start latency.** Full detail + suggested upstream fix (resolve the stream *outside* the lock) in [`research-playback-lock.md`](./research-playback-lock.md) §7.

### H1 — MA-side stop path for PROTOCOL players (`power(False)` no-op) (REFUTED — see box above)
- **Confidence:** ~~High~~ → **refuted** (live trace: 6/6 clean stops via STMf).
- **Supporting:** MA's `providers/squeezelite/player.py` issues **`client.power(False)`** (not `client.stop()`) to stop a PROTOCOL child. aioslimproto `power()` early-returns when `powered` is unchanged; protocol-player power forwarding was removed (PR #3659). With power managed at the Universal/group level, the child's `powered` can already be False → `power(False)` is a no-op → `strm "q"` never sent → `SlimClient.state` never reaches STOPPED → MA's `STATE_MAP` keeps reporting `playing` → the Universal stop coroutine never returns → the PLAYBACK lock (PR #4024) is never released → "previous holder appears stuck".
- **Contradicting:** None yet; needs the §11 debug trace to confirm `strm "q"` is absent at stop.
- **Next validation:** the debug-log trace in §11 step 1.
- **⚠️ Correction:** the earlier idea here ("Squeezelite speaks HTTP/1.0 → run it with HTTP/1.1 so `chunked` works") is a **DEAD END** — the HTTP version is dictated by aioslimproto's hardcoded server-side request line, **not** the Squeezelite client; no Squeezelite build/flag changes it (see §10).

### H1b — aioslimproto has no connection-close→STOPPED transition (only STMu→STOPPED) (High mechanism / Medium as sole cause)
- **Supporting:** aioslimproto maps only STMu→STOPPED; Squeezelite detects EOF only via `recv()==0`; the `chunked`-only clean-stop result corroborates that EOF/STMu signaling governs reaching STOPPED. Must combine with H1 to wedge.

### H2 — Universal Player lock-release bug (Medium-High)
- **Confidence:** Medium-High.
- **Supporting:** The lock ("previous holder appears stuck") is on the Universal player `upf8b156c25101`; it sets/clears the output protocol and aborts. Even direct `players/cmd/stop` to the protocol player doesn't release the wedge — only an MA restart does. Universal=idle while protocol=playing is a state-tracking mismatch in the Universal layer.
- **Contradicting:** The actual stuck *state* lives in the Squeezelite protocol player (H1) — the Universal lock may be a **symptom** of H1, not an independent bug.
- **Next validation:** Inspect MA's Universal-player/SlimProto stop handling (source/upstream issues). Check whether the lock is released when the underlying stream is forcibly closed.

### H3 — Music Assistant playback-lock defect generally (Medium)
- **Confidence:** Medium.
- **Supporting:** The "previous holder appears stuck" + 30 s timeout pattern looks like a lock not released on an error/abort path.
- **Contradicting:** Likely downstream of H1/H2 rather than a separate defect.
- **Next validation:** Search MA issues for "previous holder appears stuck" / playback lock; reproduce against a non-Squeezelite player to see if the lock wedges there too (would indicate a general MA defect vs Squeezelite-specific).

### H4 — Already fixed upstream in a newer MA / Squeezelite (Medium, high value)
- **Confidence:** Medium.
- **Supporting:** MA is on **2.9.3** (latest in its current repo channel, but the project moves fast); SlimProto/HTTP handling and lock logic are actively maintained.
- **Contradicting:** Unknown until release notes/issues are reviewed.
- **Next validation:** Review MA release notes/changelog since 2.9.3 and Squeezelite changes for stop/lock/HTTP fixes. **This is the cheapest high-value step.**

---

## 10. Things Already Ruled Out (do not re-investigate without new evidence)

| Ruled out | Evidence it's NOT the cause |
|---|---|
| **DNS as the root cause of the wedge** | CoreDNS responds fast (NXDOMAIN <1 ms, authoritative); Supervisor healthy. DNS *does* cause the separate HA↔MA connection drops (handled by A1/A2a), but **not** the playback stop-wedge. |
| **CPU starvation / needs more vCPU** | During resolution & the cold-start gap, VM CPU is **~5–9 %** and host is **idle**. The latency is waiting, not computing. Adding vCPU won't help. |
| **PO token issues** | PO-token generator is healthy, auto-refreshing (12 h TTL), and MA requests tokens for real video IDs. |
| **YouTube Music search failures** | Search works and resolves `ytmusic://` URIs for track/artist/album/playlist (cookie valid). Some multi-word track-name queries return 0 — that's query specificity, not a provider failure. |
| **Basic connectivity / OOM** | HA/MA reachable; MA `exit code 137` events are **restart SIGKILLs** (preceded by "Stopping addon"), not OOM. |
| **`flow_mode` as the primary fix** | `flow_mode` enabled on the Ceiling player — harmless, did **not** resolve the wedge. |
| **Direct protocol-player playback path** | The Squeezelite protocol player has **no queue** (`player_queues/get` empty) and is not an HA entity; MA routes all playback through the Universal player. You **cannot** bypass it. |
| **Cookie / auth as the *playback* blocker** | Auth works after incognito-cookie refresh; search + resolution succeed. The stop-wedge happens with **radio** too (no YTM auth involved). |
| **YTM-specific trigger** | The wedge reproduces on **radio** stop as well — it's a stop-of-any-live-stream problem, not YTM. |
| **"Run Squeezelite with HTTP/1.1 to make `chunked` usable"** | DEAD END (upstream research). The stream's HTTP version is dictated by **aioslimproto's hardcoded server-side request line** (`GET … HTTP/1.0`), not by the Squeezelite client — no Squeezelite build/flag changes it. So `chunked` cannot be made usable that way. |
| **"Upgrade MA to get a fix"** | No fix exists: MA 2.9.3 is current; the 2.10.0 beta/nightly changelogs (through 2026-06-24) contain **no** squeezelite/slimproto/lock/stop/state entries. The relevant code is identical across 2.9.3 and main. |
| **Re-testing `chunked` for streaming** | It returns HTTP 500 on HTTP/1.0 (aiohttp forbids chunked) → breaks playback. Only revisit if the stop path is reworked upstream. |

---

## 11. Recommended Next Investigations (ranked by expected value)

0. ✅ **DONE — upstream GitHub/Squeezelite research** (2026-06-24) → [`research-playback-lock.md`](./research-playback-lock.md). Outcome: no upstream issue matches our exact repro; root cause traced in MA source to the PROTOCOL-player stop path (`power(False)`); the "HTTP/1.1 Squeezelite" and "upgrade MA" ideas are dead ends (§10).
1. ✅ **DONE — live debug trace (2026-06-24): REFUTED H1/H1b.** VERBOSE SlimProto trace of 6/6 clean radio play→stop cycles: every stop → `idle` via `STMf`. The clean stop path works; the wedge is NOT here.
2. ✅ **DONE — interrupted-state experiment (2026-06-24): ROOT CAUSE FOUND.** All 6 interrupt-during-resolution conditions reproduced "previous holder appears stuck"; **no** persistent state mismatch. Root = **slow YTM resolution holds the playback lock for its full duration**; overlapping commands block 30 s. See `research-playback-lock.md` §7.
3. **Upstream issue — DRAFTED, awaiting review/submit (2026-06-24).** No matching upstream issue exists (confirmed). Code path confirmed in source (`@handle_play_action` wraps `play_index`→`_load_item`→`get_stream_details` in the PLAYBACK lock). Draft ready: [`upstream-issue-draft.md`](./upstream-issue-draft.md). **Do not submit without user approval.** Suggested fix: resolve the stream **outside** the lock (lock only the hand-off) or fast-reject/cancel an in-progress lock holder.
4. **Local workaround — SHELVED (2026-06-24).** Built `ytm_guard.py` (single-flight serializer + pause-interject, 7/7 unit tests) but the **live HA/MA test FAILED** (19 new "stuck"). Root cause (`research-playback-lock.md` §8b): for YTM the **PLAYBACK lock is held for the ENTIRE `play_media` call** (never returns in bounded time; held past audio-start), so **no safe moment exists to stop/switch during YTM startup**. Senior re-analysis raised a single-track lever (smaller critical section → bounded lock-hold); the narrow test (§8c) could not confirm it — `play_media` for one track didn't return in 150 s and the track never played (YTM degraded/rate-limited). Per decision rule → **shelved**. Single-track lock hypothesis is *unproven, not refuted*; revisit only if YTM playback reliability is first restored, then re-run `scratchpad/narrow_single_track.py`. Validated facts still hold: `pause` lock-free, `stop` wedges during resolution (§8a). **RADIO is healthy and needs no guard.** YTM stays unexposed to the LLM (today's degradation reinforces it). Artifacts kept (rollback = delete `ytm_guard.py`, `test_ytm_guard.py`).
3. **Universal Player lock internals** — read MA's `controllers/players/controller.py` stop path + `providers/squeezelite/player.py` to confirm the lock is only released in `finally` when the child converges, and why `players/cmd/stop` doesn't clear a wedged child.
4. **Alternate player backend (lower priority)** — a different transport could sidestep the SlimProto stop quirk, but note the **macvtap/NAT constraint**: only the host can fetch the NAT-IP stream, so a LAN fetch-player (Cast/DLNA) hits the publish-IP conflict.

### Do Not Repeat Unless New Evidence Appears
- Re-running local DNS / CPU / PO-token / search / basic-connectivity diagnostics (all ruled out — §10).
- Re-testing `flow_mode` as a wedge fix.
- Trying to bypass the Universal player by playing to the protocol player.
- Re-testing `chunked` for streaming (it breaks playback on HTTP/1.0) **unless** Squeezelite gains HTTP/1.1.
- Blaming the cookie/auth/YTM for the *stop-wedge* (it happens on radio too).

---

## 12. Architecture Decision Log

| Decision | Rationale |
|---|---|
| **YTM not exposed to the LLM** | Playback isn't reliable (stop-wedge + cold-start latency). Exposing it would let the assistant hang the speakers. Gate: only expose once playback is proven reliable. |
| **Exposed playback = local library + radio (resolver / F1-R)** | `play_music` (local files via MA `filesystem_smb`), `play_radio`, and `find_stations` are exposed through the synchronous resolver `/command` path. **YTM track playback stays unexposed** (stop-wedge + cold-start latency — §8–§13). |
| **Phone-pipeline TTS disabled** | Piper crashes the pipeline, and TTS proxy URLs resolve to the NAT IP `192.168.122.10` which the **phone can't reach** (macvtap split). Spoken replies on the phone would fail; text replies are reliable. **Update 2026-07-14:** the NAT-IP reachability half is fixed (Internal URL → LAN `192.168.1.104`) and Piper TTS works in the reSpeaker's dedicated pipeline — so **phone TTS is worth re-testing**; kept off until verified. |
| **LLM exposure restricted to helper scripts (+ weather)** | Entity exposure is shared by all conversation agents; exposing raw `media_player`/TV/etc. would re-enable broken built-in intents and widen the LLM's reach. Purpose-built `script.ceiling_*` are a safe, minimal, bounded action surface. `expose_new_entities` turned off. |
| **Ceiling TTS via explicit `tts.speak`, not the pipeline** | The pipeline TTS is off (Piper); explicit `tts.speak` to `media_player.ceiling_speakers` works because the **host** can fetch the NAT-IP TTS URL. `script.ceiling_announce` is the reusable primitive (kept un-exposed to the LLM). |
| **Auto-reload automations (A1 + A2a) exist** | The HA↔MA integration drops its connection (internal DNS) and doesn't auto-reconnect — it sits silently dead until a config-entry reload. A1 covers restart drops; A2a's active probe covers silent drops. Both reload the entry to self-heal, with debounce/cooldown to avoid loops. |
| **`http_profile` left at `no_content_length`** | No value fixes both play and stop: `chunked` breaks streaming on HTTP/1.0; `forced_content_length` still wedges. `no_content_length` is the baseline that at least plays. |
| **NAT NIC + host Squeezelite for the ceiling zone** | macvtap isolates host↔VM; a reversible second NAT NIC (`192.168.122.10`) lets the host reach MA's stream server. Host Squeezelite drives the analog `hw:1,0` ceiling speakers (no desktop/PulseAudio, exclusive ALSA). |

---

## 13. Research Brief: Playback Lock Investigation

Hand this to a deep-research agent. **Read-only research; do not change config, restart services, or expose anything to the LLM.**

### Environment
- **HA Core:** 2026.6.4 · **HAOS:** 18.0 (VM under libvirt/QEMU 2.5 on Ubuntu 16.04 host).
- **Music Assistant:** server/add-on **v2.9.3** (`d5369777_music_assistant`), schema 31.
- **Squeezelite:** runs on the **host** (Ubuntu 16.04) as `squeezelite-ceiling.service`, output ALSA `hw:1,0`, server = MA stream on `192.168.122.10`. Client connects to MA's stream server over **HTTP/1.0** (per `aioslimproto` error). Exact Squeezelite version: **TBD — read-only host check pending** (`squeezelite --version` / package version).
- **Player model:** MA **Universal player** `upf8b156c25101` wrapping a **Squeezelite protocol player** `f8:b1:56:c2:51:01` (the protocol player has no independent queue). Player config of note: `http_profile=no_content_length` (default), `output_codec=flac`, `flow_mode=true`, `output_channels=stereo`.

### Proven facts (local, reproduced)
- Search works; YTM auth works; cookie currently valid (after incognito refresh).
- HA↔MA connection self-heals via auto-reload automations (drops are internal-DNS, not the wedge).
- **Stop causes the wedge:** `media_stop` of any actively-playing stream (radio or YTM) → Universal player `idle` but **protocol player stays `playing`** (state mismatch). Confirmed clean A/B from a restarted baseline.
- The wedged protocol stream holds the playback lock → next plays hit "Timed out (30s) acquiring playback lock for player … previous holder appears stuck".
- **`chunked`** → MA stream server returns HTTP 500 `RuntimeError: Using chunked encoding is forbidden for HTTP/1.0`; clears the wedge but breaks playback.
- **`no_content_length`** → plays fine; **wedges on stop**.
- **`forced_content_length`** → plays fine (no 500); **still wedges on stop**.
- Resolution is fast (~14 s) and not CPU-bound; cold-start "latency" is the post-resolution lock wait; cached replay ~2 s.

### Open questions
1. **Why does the Squeezelite protocol player never transition to `idle` after stop** (with content-length/no-length streams)? Is this a missing end-of-stream signal over HTTP/1.0, or an MA/SlimProto stop-handling gap?
2. **Is this known upstream** (MA or Squeezelite issues/PRs)?
3. **Do newer MA / Squeezelite versions contain a fix** for the stop/lock/HTTP behavior?
4. **Would HTTP/1.1 support change behavior** (making `chunked` usable and the stop clean)?

### Desired outcome
Reliable playback of **track, artist, album, playlist, genre** from YouTube Music through Home Assistant, and eventually through the ChatGPT assistant — i.e., clean stop (protocol returns idle, no stuck lock) and acceptable start latency.

### Search terms / focus
`"previous holder appears stuck"` · playback lock · Universal Player · Squeezelite · SlimProto · HTTP/1.0 · `no_content_length` · `chunked` · `forced_content_length` · stream termination · stop behavior · "protocol player" remaining in `playing`. Sources: Music Assistant GitHub (issues/discussions/releases), Squeezelite GitHub, SlimProto docs.

### Deliverables expected
1. Root-cause tree. 2. Ranked hypotheses (reconcile with §9). 3. Relevant upstream issues/PRs (links). 4. Existing fixes/workarounds. 5. Recommended next experiment.

> ✅ **First research pass complete (2026-06-24): [`research-playback-lock.md`](./research-playback-lock.md).** Root cause traced to MA's PROTOCOL-player stop (`power(False)` no-op) → SlimClient never reaches STOPPED → lock never released. No upstream fix; HTTP/1.1-Squeezelite and MA-upgrade are dead ends. Next: the live debug trace (§11 step 1) to confirm, then file upstream.

---

## 14. Where things live

- **Deep docs (authoritative):** `D:\repos\dotfiles\docs\homebrain\`
  - `music-assistant-audio-architecture.md` — master (architecture, voice, LLM, TTS, YTM investigation, http_profile, A1/A2a, change log).
  - **Resolver / Inc / F1-R:** `2026-06-28-F1-synchronous-command-result-design.md` (F1 design), `2026-06-28-F1-R-chatgpt-tool-result-relay-design.md` (F1-R addendum), `plans/2026-06-28-F1-R-music-remigration.md` (music migration), `plans/2026-06-29-F1-R-radio-find-migration.md` (radio/find migration), `assistant-capabilities.md`, `local-music-architecture.md`, `CHANGELOG.md`.
  - `haos-vm-deployment.md`, `homebrain-architecture.md`, `migration-inventory.md`, **this `ONBOARDING.md`**.
  - **Runbooks:** `runbooks/quick-connect-and-health-check.md` — SSH connect + read-only stack health check + "ChatGPT can't play" triage.
- **Agent memory (running project log, latest status):** `~/.claude/projects/C--Users-ConstantinMalii/memory/homebrain-ha-vm-project.md` — detailed chronology + every finding.
- **Scratchpad (test outputs, config snapshots):** session scratchpad dir; e.g. `ma_cfg_before_*.json`, `phase3_exposure_snapshot_*.json`.

---

## 15. Working norms (user preferences)

- **Ask before sudo / impactful changes.** Don't touch Plex, old HA Core, host LAN networking (eno1), or macvtap. Don't upgrade the host OS.
- **Diagnostics before fixes** — correlate exact log timestamps; provide evidence for the failing stage before proposing a change. Rigor over speed.
- **Scope discipline** — change only what's asked; snapshot before changing settings; roll back if a change doesn't deliver.
- **Don't expose YTM (or broad entities) to the LLM** until playback is proven reliable. Keep exposure minimal.
- **Git:** secret-scan first; **no Claude attribution** in commits/PRs; commit only when asked; keep documentation commits separate from implementation.
- **No service restarts without explicit approval** — resolver / MA / HA / Squeezelite restarts are user-run; never restart unprompted.
- **No HA script changes without explicit approval** — don't edit or migrate `script.*` configs unless asked.
- **No new ChatGPT exposure without explicit approval** — entity/tool exposure is shared across agents; don't expose anything new unprompted.
- **Don't stage unrelated files** — commit only the files for the change at hand; leave pre-existing/unrelated working-tree changes (and others' in-progress files) alone.
- **Secrets:** never write tokens/cookies to repo, docs, memory, logs, or artifacts.
