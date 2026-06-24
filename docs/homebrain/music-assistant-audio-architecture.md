# Homebrain — Music Assistant & Audio Architecture (Master Reference)

> ### ▶ Start Here
> **New to this system (human or agent)? Read [`ONBOARDING.md`](./ONBOARDING.md) first** — it's the primary entry point: connectivity, tooling, what works, the full investigation timeline, ranked hypotheses, things already ruled out, recommended next steps, the architecture decision log, and the playback-lock research brief. This document is the deep technical reference behind it.

> Written for an engineer with **no prior context** who must understand, operate, troubleshoot, upgrade, and rebuild this environment.
> Companion docs in this folder: **`ONBOARDING.md` (START HERE — agent/operator entry point)**, `homebrain-architecture.md` (host/VM inventory + SSH quirk), `haos-vm-deployment.md` (VM/KVM detail + full XML), `music-assistant-ceiling-zone.md` (focused ceiling-zone runbook), `migration-inventory.md` (legacy HA Core).

**Generated:** 2026-06-22 · **Maintainer context:** personal home media server.

---

## 1. Executive Summary

**Purpose.** Turn the `homebrain` media server into a whole-home music system. A modern **Home Assistant OS (HAOS)** VM runs **Music Assistant (MA)**, which streams music (YouTube Music, internet radio, …) to speakers around the house. The first production zone is the **ceiling speakers**, driven by the host's own analog audio output via a **Squeezelite** player.

**Current architecture (one line).** HAOS VM (KVM/libvirt) runs MA; MA reaches LAN speakers directly over a macvtap NIC, and reaches the **host** (for the ceiling zone) over a **second NAT NIC**; a host-side Squeezelite service plays MA audio out the analog jack to the ceiling-speaker amp.

**Operational status (2026-06-22):**
- ✅ HAOS VM running (HA Core 2026.6.4), autostart on.
- ✅ Music Assistant 2.9.3 installed and running; HA integration loaded.
- ✅ **Ceiling-speaker zone working** — verified by playing internet radio through the ceiling speakers.
- ⚠️ YouTube Music plumbing healthy (auth + PO token confirmed), but a YTMusic *search-track*-through-a-speaker play has not been audibly confirmed yet (failures so far were stale-playlist/AirPlay artifacts).
- ⚠️ Samsung soundbar (AirPlay) not yet working via MA's legacy AirPlay client.
- ⚠️ Supervisor `/hassio` frontend panel does not register (backend healthy; managed via `ha` CLI / direct URLs).
- ➖ Legacy HA Core 0.57.2 and Plex untouched and still running.

**Key capabilities:** multi-source music library (YouTube Music + Radio Browser), playback to networked players (AirPlay/Cast/DLNA/Squeezelite), and a permanent always-on ceiling-speaker zone controllable from the MA UI and the Home Assistant integration.

---

## 2. Architecture Overview

### Host architecture
`homebrain` is an Ubuntu 16.04 desktop/server (Intel i7-4770). It runs **Plex**, a **legacy HA Core 0.57.2** (venv), **KVM/libvirt** (hosting the HAOS VM), and now a **Squeezelite** systemd service for the ceiling zone. Its analog audio output (`hw:1,0`) feeds the ceiling-speaker amplifier.

### VM architecture
A single libvirt domain `haos` (q35 + UEFI/OVMF, host-passthrough CPU) runs **Home Assistant OS 18.0**. Disk is a 32 GiB qcow2 on the host SSD. It has **two** NICs (see networking). Music Assistant runs *inside* this VM as a Supervisor add-on (Docker container managed by HAOS Supervisor).

### Network architecture
```
                 LAN 192.168.1.0/24 (router .254)
  ┌───────────────┬───────────────────────────┬───────────────────────┐
  │ workstation   │ homebrain HOST            │ HAOS VM (macvtap)      │
  │ .77           │ eno1 .68 (static)         │ emp2s1 .104 (DHCP)     │
  └───────────────┴───────────────────────────┴───────────────────────┘
        host eno1 ──macvtap── VM macvtap0 (.104)   [HOST↔VM BLOCKED by macvtap]
        host virbr0 .122.1 ──NAT── VM vnet0 (.122.10)  [HOST↔VM WORKS via NAT]
```
- VM↔**other LAN devices** (soundbar, etc.): works over macvtap.
- VM↔**host**: works **only** over the NAT link (`192.168.122.0/24`).

### Audio architecture
- **Ceiling speakers:** host analog `hw:1,0` → amp → ceiling speakers. Player = Squeezelite on the host.
- **Samsung soundbar:** AirPlay-2 device on the LAN; MA reaches it directly over macvtap (playback path still being sorted — see §6).
- **MA stream server** (port 8097) serves PCM/encoded audio to *fetch*-type players (Squeezelite, Cast, DLNA). **Publish IP must be the address the player can reach** (here: the NAT IP `192.168.122.10`, because the ceiling player is on the host).

### Control & streaming paths
```
Ceiling zone (Squeezelite):
  control:  Squeezelite(host) ──TCP 3483 SlimProto──▶ MA(VM .122.10)
  stream:   Squeezelite(host) ──HTTP 8097 fetch──────▶ MA streamserver (publish IP .122.10)
  output:   Squeezelite ──ALSA hw:1,0──▶ amp ──▶ ceiling speakers

AirPlay players (soundbar):
  MA(VM) ──RTSP/RTP push over LAN (macvtap)──▶ speaker   (no fetch URL involved)

Home Assistant control of MA:
  HA Core(VM) ──ws://d5369777-music-assistant:8094 (internal Docker)──▶ MA server
  → exposes media_player.* entities; services (music_assistant.play_media, media_player.*)
```

### Dependency diagram (high level)
```
ceiling speakers ─needs─ Squeezelite(host) ─needs─ MA streamserver(.122.10:8097) + SlimProto(.122.10:3483)
                                                  └─needs─ NAT NIC link (host↔VM)
MA server ─needs─ HAOS Supervisor ─needs─ HAOS VM ─needs─ libvirt/KVM ─needs─ host
HA integration ─needs─ MA server (internal Docker DNS) 
YouTube Music ─needs─ login cookie + PO-token generator add-on(:4416) + internet (via NAT→eno1)
```

---

## 3. Environment Inventory Snapshot

**Date generated:** 2026-06-22.

| Item | Value |
|---|---|
| Host OS | Ubuntu 16.04.7 LTS, kernel 4.4.0-210-generic (EOL) |
| Host hardware | Intel Core i7-4770 (4c/8t, VT-x), 7.7 GiB RAM, swap 7.9 GiB (`/dev/sdb5`) |
| Host disks | `sda` 1.8 TB HDD ext3 `/media/MediaServerData` (94% full); `sdb` 119 GB SSD: `sdb1` ext4 `/` (~39 GB free) |
| Host audio devices | card0 `[HDMI]` HDA Intel HDMI; **card1 `[PCH]` HDA Intel PCH analog → `hw:1,0` (ceiling speakers)** |
| Host networking | NIC `eno1` static `192.168.1.68/24`, gw `.254`, DNS 8.8.8.8 (ifupdown); NM present, `eno1` unmanaged; `virbr0` NAT `192.168.122.1/24` |
| Virt stack | QEMU 2.5.0, libvirt 1.3.1, virtinst 1.3.2, OVMF `0~20160408` |
| VM name / UUID | `haos` / `295a0ee7-0bb0-4e5f-aff2-148a7837c174` |
| VM config | q35 (`pc-q35-2.5`), UEFI pflash (`/usr/share/OVMF/OVMF_CODE.fd` + nvram `/home/costea/haos_VARS.fd`), CPU host-passthrough |
| VM disk | `/var/lib/libvirt/images/haos.qcow2` (qcow2, 32 GiB) |
| VM CPU/RAM | **3 vCPU / 4 GiB** (raised from 2/2 GiB on 2026-06-22) |
| VM NIC 1 (macvtap) | MAC `52:54:00:ab:cd:10`, LAN **`192.168.1.104`** (guest iface `emp2s1`) |
| VM NIC 2 (NAT) | MAC `52:54:00:ab:cd:20`, NAT **`192.168.122.10`** (static reservation) |
| VM definition file | `/home/costea/haos.xml`; autostart enabled |
| Home Assistant | Core **2026.6.4**, HAOS **18.0** |
| Music Assistant | add-on `d5369777_music_assistant` **v2.9.3**; PO-token add-on `d5369777_ytm_po_token_generator` **v1.3.1** |
| MA HA integration | config entry `01KVPNW1JFHJG30NANAPVARHY8` |
| MA music providers | **YouTube Music**, **Radio Browser** (Last.fm = metadata) |
| MA player providers | Squeezelite (SlimProto), AirPlay, Sendspin (AirPlay-2), Chromecast, DLNA, Local Audio Out, Party |
| MA players | `media_player.ceiling_speakers` (Squeezelite, universal `upf8b156c25101`), `media_player.samsung_soundbar_q930c` (AirPlay), `media_player.upperthermostat` (AirPlay), Web (Chrome) ephemeral |
| MA ports | UI/API 8095, stream server 8097 (publish IP `192.168.122.10`), SlimProto 3483, ingress 8094, Sendspin 8927, PO-token 4416 |
| Preserved services | Plex `plexmediaserver` 1.18.8.2527; legacy HA Core `home-assistant@costea` 0.57.2 (`:8123`) |

**SSH access:** `ssh-add ~/.ssh/id_homebrain` then `ssh costea@192.168.1.68` (agent-only; direct `-i` fails on the new OpenSSH client — see `homebrain-architecture.md` §9).

---

## 4. Design Decisions and Rationale

**HAOS VM deployment (KVM/libvirt).** *Alternatives:* HA Container/Supervised on the host; bare-metal. *Chosen:* HAOS in a KVM VM. *Benefits:* full Supervisor/add-on ecosystem; isolation from the EOL host; preserves Plex + legacy HA. *Risks:* old QEMU 2.5/OVMF 2016 may struggle with future HAOS. *Rollback:* `virsh destroy/undefine haos`; host untouched.

**macvtap networking (VM primary NIC).** *Alternatives:* libvirt NAT only; host bridge `br0`. *Chosen:* macvtap on `eno1`. *Benefits:* VM gets a real LAN IP for mDNS/discovery with **zero host-network changes** (single-NIC, remote, no console). *Risks:* **host↔VM isolation** (the whole reason the NAT NIC exists). *Rollback:* detach/replace the interface in the domain XML.

**Secondary NAT NIC.** *Alternatives:* bridge `eno1`; host macvlan shim. *Chosen:* add a 2nd VM NIC on libvirt `default` NAT. *Benefits:* restores host↔VM connectivity **reversibly, VM-only, no SSH risk**. *Risks:* MA stream publish-IP conflict (host needs `.10`, LAN fetch-players would need `.104`). *Rollback:* §14.

**Why host bridge networking was rejected.** Bridging `eno1`→`br0` reconfigures the host's **only** NIC remotely; a failure drops host SSH with **no console** (recoverable only by physically attaching a keyboard to homebrain). Too risky vs. the reversible NAT NIC. (A host **macvlan shim** is the documented escalation if a single publish IP ever becomes insufficient.)

**Music Assistant selection.** *Alternatives:* HA media_player integrations alone; Mopidy; Logitech Media Server. *Chosen:* Music Assistant. *Benefits:* unified multi-source library, broad player support (AirPlay/Cast/DLNA/Squeezelite/Sonos), native HA integration. *Risks:* unofficial YTMusic provider can break with Google changes. *Rollback:* uninstall add-on + integration.

**Squeezelite vs Snapcast.** *Chosen:* **Squeezelite**. *Benefits:* single lightweight always-on player, native MA SlimProto, direct ALSA, one package. *Snapcast* only adds value for *synchronized multi-room* across multiple snapclient-capable endpoints — the soundbar can't be a snapclient, so Snapcast couldn't even unify the two outputs; pure overhead for one zone. *Rollback:* §14.

**Ceiling-speaker zone architecture.** *Chosen:* Squeezelite on host → ALSA `hw:1,0`, server = MA over NAT `.10`, MA stream publish IP = `.10`. *Benefits:* reliable TCP-based path (none of AirPlay's timing fragility), survives reboots, decoupled from any desktop login. *Risks:* depends on the NAT NIC + the `.10` publish IP. *Rollback:* §14.

**Samsung soundbar handling.** *Chosen (interim):* leave on AirPlay; MA's legacy `CLIRaop` client fails (it's an AirPlay-2 device). *Next:* use MA's AirPlay-2/**Sendspin** protocol/player. Not yet resolved (see §6/§15).

---

## 5. Networking

**Original layout.** Single NIC `eno1` static `192.168.1.68/24` via classic `ifupdown`; NetworkManager installed but `eno1` is **unmanaged**; libvirt `default` NAT network on `virbr0` (`192.168.122.1/24`).

**macvtap host↔VM limitation.** The VM's primary NIC is macvtap (`type='direct'`, `mode='bridge'`) on `eno1` → LAN `192.168.1.104`. macvtap **prevents the parent host and its guest from communicating in either direction**; all other LAN devices can reach the VM.

**Discovery process (how we proved it).** From the host, `192.168.1.104:8123` → `000` (unreachable); from the workstation, `192.168.1.104:8123` → `200`. Confirmed the isolation is host-specific and by design.

**NAT NIC implementation.** Added a 2nd VM NIC on libvirt `default` (NAT). The host is the gateway (`192.168.122.1`) for `virbr0`, so it can reach VMs on that network.
```bash
virsh -c qemu:///system net-update default add ip-dhcp-host \
  "<host mac='52:54:00:ab:cd:20' name='haos-nat' ip='192.168.122.10'/>" --live --config
virsh -c qemu:///system attach-interface haos network default --model virtio \
  --mac 52:54:00:ab:cd:20 --live --config
# HAOS did NOT auto-configure the hot-plugged NIC → a VM reboot activated it (see §8).
```

**Static DHCP reservation.** MAC `52:54:00:ab:cd:20` → `192.168.122.10` (so the ceiling zone target never drifts; Squeezelite's `-s` and MA's publish IP both point at it).

**Port usage.**
| Port | Service | Reachable from |
|---|---|---|
| 8123 | Home Assistant | LAN (`.104`) + host (`.10`) |
| 8095 | MA web UI / API | LAN (`.104`) + host (`.10`) |
| 8097 | MA **stream server** (publish IP `.10`) | host (`.10`) |
| 3483 | SlimProto (Squeezelite control) | host (`.10`) |
| 8094 | MA ingress (HA integration → MA, internal Docker) | inside VM |
| 8927 | Sendspin (AirPlay-2) | LAN |
| 4416 | PO-token generator (bgutil) | inside VM / host (`.10`) |

**Host↔VM communication path.** Host `192.168.122.1` ⇄ VM `192.168.122.10` over `virbr0` (NAT). This carries SlimProto control + the audio stream fetch for the ceiling zone.

**Validation performed.** From the host: `curl http://192.168.122.10:8095/info` → 200; TCP connect to `:8123/:8095/:8097/:3483` → all OPEN. LAN `.104:8123/:8095` → 200 from the workstation.

---

## 6. Music Assistant

**Installation.** Repository `github.com/music-assistant/home-assistant-addon` (slug `d5369777`) was already present (restore leftover). Installed via the **`ha` CLI** (the Supervisor panel is missing — see §8):
```
ha apps install d5369777_music_assistant
ha apps start   d5369777_music_assistant      # boot=auto, state=started, v2.9.3
```
HA **Music Assistant integration** added via Settings → Devices & Services (auto-discovered). First setup hit *"addon discovery not completed yet"*; fixed by `hassio.addon_restart` + reload of the config entry.

**Configuration.** MA web UI at `http://192.168.1.104:8095` (use this directly; "Open Web UI" panel is unavailable). Stream server **publish IP set to `192.168.122.10`** (Settings → System → Streams) — *the* fix that let the host fetch audio.

**Providers.** Music: **YouTube Music**, **Radio Browser**. Players: **Squeezelite (SlimProto)**, AirPlay, Sendspin, Chromecast, DLNA, Local Audio Out. Metadata: Last.fm. Plugin: Party, Home Assistant.

**Player inventory.**
- `media_player.ceiling_speakers` — Squeezelite (universal player `upf8b156c25101`, host MAC `f8:b1:56:c2:51:01`). **Working.**
- `media_player.samsung_soundbar_q930c` — AirPlay. Discovered; playback fails via legacy client.
- `media_player.upperthermostat` — AirPlay (a speaker despite the name).
- Web (Chrome) — ephemeral browser player.

**YouTube Music configuration.** Provider fields: **Username** (account), **Login Cookie** (raw `cookie:` header from a logged-in `music.youtube.com` session), **PO Token Server URL** = `http://127.0.0.1:4416`. Requires the **PO Token Generator** add-on (`d5369777_ytm_po_token_generator`, port 4416) — **confirmed working** (mints valid tokens for real video IDs in <0.5 s). Account has Premium.

**Known YouTube Music issues.** Observed `music/tracks/get_track: ytmusic--7MLPoF6b is not available`. Root cause: that's a **malformed/stale track ref** (`ytmusic--7MLPoF6b` — double dash, 8 chars; real IDs are 11) from **empty restored library playlists** (`my-relax`, `500 Random tracks (from library)`, etc.), **not** a provider fault. **Play via Search**, not the stale playlists. A clean YTMusic-through-a-speaker confirmation is still pending.

**Known Samsung soundbar issues.** AirPlay playback fails: `CLIRaop process stopped unexpectedly … write error` → `Playback failed to start`. The Q930C is AirPlay-2; MA used the legacy RAOP client. Next: switch the player to the AirPlay-2/Sendspin protocol.

**Chrome player findings.** The MA web player (Sendspin) fails over plain HTTP: `[Opus] Running in insecure context, falling back to FLAC/PCM`, autoplay blocked (`play() interrupted by pause()`), `Playback failed to start`. This is a browser/insecure-context limitation, not a server fault — don't use the browser tab as a test player.

**Stream server behavior.** Logs its publish IP at start: `Starting streamserver on 192.168.122.10:8097` and warns *"This is the IP address that is communicated to players. If incorrect, audio will not play."* Players **fetch** audio from this IP — so it must be host-reachable for the ceiling zone.

---

## 7. Ceiling Speaker Zone

**Audio path.** MA(VM) → SlimProto control (3483) + HTTP stream (8097) over NAT `.10` → Squeezelite(host) → ALSA `hw:1,0` → amp → ceiling speakers.

**ALSA device selection.** Card 1 `[PCH]` analog (`hw:1,0`). Chosen over HDMI (card 0 = displays). No PulseAudio/desktop session runs, so Squeezelite owns the device exclusively.

**Verification methodology.** (1) Hardware: `sudo aplay -D hw:1,0 …Front_Center.wav` → sound out the ceiling speakers. (2) Path: host→VM ports OPEN. (3) End-to-end: play an **internet-radio** station (no-auth source) to `Ceiling Speakers`.

**Test results.** ✅ ALSA test produced sound; ✅ all NAT ports reachable; ✅ **internet radio played through the ceiling speakers** (the definitive pass). The earlier silent attempts were caused by (a) MA publishing the stream on the unreachable `.104` (fixed → `.10`), (b) a stuck playback lock from failed soundbar AirPlay sessions (cleared by MA restart), and (c) resource starvation at 2 GB (fixed → 4 GB).

**Squeezelite configuration.** systemd unit (see §13): `squeezelite -o hw:1,0 -n "Ceiling Speakers" -s 192.168.122.10 -C 5`, `User=root`, `Restart=always`, enabled on boot.

**Service architecture.** A standalone systemd **system** service (`squeezelite-ceiling.service`) independent of any login — the packaged default `squeezelite.service` is disabled to avoid device contention.

**Startup behavior.** Starts at host boot; connects to MA's SlimProto server; auto-reconnects (`Restart=always`) if MA restarts. `-C 5` releases the ALSA device after 5 s idle.

**Operational status.** ✅ Running and verified.

### Voice control (Phase 2 — phone microphone)

**Status (2026-06-22): ✅ operational by voice** from the Android Companion App. Full path verified end-to-end: phone mic → **Whisper STT** → Home Assistant **conversation agent** → **conversation-trigger automation** → service action on the Ceiling Speakers. Confirmations are returned as **text** (see limitation).

**How it works / architecture:**
- The three `media_player.*` entities are **un-exposed** from the Assist conversation agent. (When exposed, HA's *built-in* intents intercepted spoken phrases and called services the MA player doesn't support — e.g. `media_player.turn_off` → `ServiceNotSupported` → "Oops, an error has occurred." Un-exposing removes that interception.)
- A single **conversation-trigger automation, `automation.voice_ceiling_speakers`**, is the **sole handler** — it matches the sentences and calls only supported services on `media_player.ceiling_speakers`. Created/maintained via the automation API (`POST /api/config/automation/config/voice_ceiling_speakers`).
- Pipeline ("Home Assistant", preferred): **STT = `stt.faster_whisper`**, **Conversation = `conversation.home_assistant`**, **TTS = off** (see limitation).
- Spoken numbers are converted **generically** (digits *or* English words, 0–100) via a `{percent}` wildcard + a word→number template — no per-value hardcoding.

**Supported voice command set** (all target the Ceiling Speakers by default; verified via `conversation.process`):

| Intent | Phrases |
|---|---|
| Set volume (absolute) | `volume {N} percent` · `set [the] volume to {N} [percent]` · `set [the] ceiling speakers to {N} [percent]` — `{N}` = digits or words (`5`/`five`, `30`/`thirty`, `75`/`seventy five`, `100`/`one hundred`), clamped 0–100 |
| Volume up | `turn the music/volume/it up` · `make it louder` · `volume up` · `louder` |
| Volume down | `turn the music/volume/it down` · `make it quieter` · `volume down` · `quieter` |
| Play radio | `play [the] radio` · `play radio on [the] ceiling speakers` (station `Radio Paradise`, editable in the automation) |
| Resume / play | `play music` · `resume [the music]` · `continue [playing\|music]` · `start playing again` · `unpause` |
| Pause | `pause [the music]` |
| Stop | `stop [the music]` |

**Known limitations:**
- **TTS spoken replies are intentionally disabled because Piper currently causes errors.** Voice commands execute successfully, but confirmations are shown as text only. (Re-enabling Piper TTS is a separate future task.)
- **Whisper model is `auto`** (= sherpa-onnx Parakeet on amd64); it could **not** be pinned to `tiny-int8` because add-on options can't be written on this instance — no `ha apps options` subcommand, the Supervisor `/hassio` panel is missing, and the Supervisor-API options write is blocked (`401`) through the Core proxy. STT works regardless.
- The **HA↔MA integration connection** occasionally drops (`ws://d5369777-music-assistant:8094` DNS timeout); recover by reloading the Music Assistant config entry.

**Rollback:**
- Automation: `DELETE /api/config/automation/config/voice_ceiling_speakers` (or Settings → Automations → ⋮ → Delete / edit).
- Re-expose players (if you want built-in intents back): Settings → Voice assistants → Expose, or WS `homeassistant/expose_entity … should_expose: true`.
- Re-enable spoken replies (after Piper is fixed): set the "Home Assistant" pipeline `tts_engine` back to `tts.piper`.
- Nothing in Whisper/Piper/Wyoming/MA/Squeezelite/networking/VM was modified for any of this.

### LLM conversation assistant (Phase 3 — OpenAI/ChatGPT)

**Status (2026-06-22): ✅ operational from Assist text.** A second, **separate** conversation agent (`conversation.openai_conversation`, OpenAI **gpt-4o-mini**) was added **alongside** the deterministic assistant — it does **not** replace it. The deterministic "Home Assistant" pipeline + `automation.voice_ceiling_speakers` are unchanged and remain the **preferred/default**. The LLM is opt-in via the assistant dropdown ("ChatGPT" pipeline).

**Design principle — the LLM acts only through a small allow-list, never on raw devices.** Entity exposure in HA is shared by all conversation agents, so instead of exposing `media_player.ceiling_speakers` (which would also re-enable the broken built-in intents on the deterministic side), the LLM is given **purpose-built helper scripts** as its sole action surface.

**Helper scripts created** (`POST /api/config/script/config/<id>`; see §13), all targeting `media_player.ceiling_speakers` only:

| Script | Action | LLM args |
|---|---|---|
| `script.ceiling_play_radio` | `music_assistant.play_media` (radio) | `station` (optional, default Radio Paradise) |
| `script.ceiling_pause` / `_resume` / `_stop` | `media_player.media_pause` / `media_play` / `media_stop` | — |
| `script.ceiling_set_volume` | `media_player.volume_set` (clamped 0–100) | `volume` (0–100) |
| `script.ceiling_volume_up` / `_down` | `media_player.volume_up` / `_down` | — |

**Exposure (tightened for this phase).** Effective Assist exposure is now **exactly 8 entities**: the 7 `script.ceiling_*` above + `weather.forecast_home` (read-only). `expose_new_entities` was turned **off** (was on), and the previously default/explicitly-exposed entities — incl. `media_player.samsung_q82ca_75` (TV), `todo.shopping_list`, `update.music_assistant_update` — were **un-exposed**. Before/after exposure snapshots were captured for exact rollback. No raw media_player, TV, phone, update, button, notify, person, or device_tracker is exposed.

**OpenAI agent configuration** (subentry of the `openai_conversation` config entry):
- Model **gpt-4o-mini**, temperature 0.3, max tokens 200, `recommended=off`.
- **Control Home Assistant = Assist** (`llm_hass_api: ["assist"]`) — this is what lets it call the exposed scripts; it is hard-limited to the 8 exposed entities.
- Scoped system prompt: "control ONLY the ceiling speakers via the provided scripts; can read weather; no access to any other device; refuse other device control."
- **web search / code interpreter / response-storage / user-location all OFF**.
- The auto-created **stt / tts / ai_task** subentries were **deleted** (we use local Whisper STT and no TTS) to keep the cloud surface minimal.
- "ChatGPT" Assist pipeline: conversation = `conversation.openai_conversation`, **STT = local `stt.faster_whisper`**, **TTS = off**.

**Test results (Assist text, gpt-4o-mini):**
- ✅ "Set the ceiling speakers volume to 18 percent" → volume → 0.18.
- ✅ "What's the weather right now?" → answered from `weather.forecast_home` (16.9 °C, 77%).
- ✅ "Pause the ceiling music" → paused.
- ✅ Negative — "Turn off the Samsung TV" / "Set the soundbar volume to 60" / "Turn on the upper thermostat speaker" → all refused with *"I can only control the ceiling speakers"* and **zero state change** on the TV/soundbar.

**Privacy / what is sent to OpenAI:** the typed/transcribed text, the system prompt, the **state of the 8 exposed entities only**, and the 7 script tool-schemas; within one conversation session prior turns are resent. **Microphone audio is transcribed locally by Whisper first** — raw audio is never sent. Unexposed entities and broader HA history are not sent.

**Cost:** gpt-4o-mini ≈ $0.0004–$0.0006 per command (~2–2.5k input + ~150 output tokens; only 8 entities/7 tools). ≈ **$1.50–$2/mo at 100 req/day**, ≈ **$7–$9/mo at 500 req/day**. Set a hard cap in the OpenAI billing dashboard. Account must be funded (gpt-4o-mini is not free-tier).

**Security notes:** least-privilege via the allow-list (LLM cannot reach anything but the 7 scripts + weather); `expose_new` off prevents future entities from leaking in; the API key is stored only in HA's encrypted `.storage` (never in repo/docs/logs); the deterministic assistant stays the default so reliable local voice commands are unaffected by the cloud agent.

**Rollback:** see §14.

### Spoken announcements (ceiling TTS via Piper)

**Status (2026-06-22): ✅ working.** Spoken audio is delivered to the ceiling speakers by **explicit `tts.speak` calls** (Piper → `media_player.ceiling_speakers`), **not** by the Assist pipeline. HA generates the audio with `tts.piper`; **Music Assistant performs playback** (it owns the Squeezelite player) — the host Squeezelite fetches the TTS proxy URL on the reachable NAT IP `192.168.122.10`, the same path radio uses.

**Why this path (root cause of the earlier "Piper crash"):** Piper itself was never broken — it generates valid audio (verified: 31 KB MP3, 22.05 kHz mono, fetched successfully from the host). The earlier pipeline "Oops" was the now-fixed exposed-media_player built-in intents plus a likely first-run voice-download race, not a Piper defect. The one real constraint is that HA auto-derives the TTS proxy URL as `192.168.122.10` (because `internal_url`/`external_url` are unset) — reachable by the **host/ceiling speakers** but **not** by the phone, which is why phone-pipeline TTS stays off.

**Scripts (see §13):**
- **`script.ceiling_announce`** (field `message`) — reusable announcement primitive; speaks arbitrary text on the ceiling speakers. **Intended for future automations** (doorbell, timers, reminders, weather, alerts). **Not exposed to the LLM** (`expose_new_entities` is off, so it was not auto-exposed) — the ChatGPT agent cannot make the speakers talk arbitrarily.
- **`script.ceiling_play_radio`** — plays radio **with a spoken confirmation** ("Playing {station}."), announced over the stream (MA ducks, speaks, resumes — exactly the desired behavior).
- **`script.ceiling_stop`** — **no spoken confirmation.** MA announcements **always resume the prior stream afterward** (confirmed: even after `media_stop` + `clear_playlist`, announcing re-started the radio), so a "stopped" confirmation is self-defeating; stop is kept clean/instant.
- volume / pause / resume scripts — intentionally **no** spoken confirmations (avoids per-volume-change chatter).

**Not changed by this:** the Assist pipeline TTS remains **off** for the phone (text replies only); **no `internal_url`/`external_url`** change; no networking, Whisper, Music Assistant, Squeezelite, or LLM-exposure changes.

**Rollback:** delete `script.ceiling_announce` and revert `script.ceiling_play_radio` to its no-confirmation form (`DELETE`/`POST /api/config/script/config/<id>`); nothing else is affected.

---

## 8. Lessons Learned

- **macvtap blocks host↔VM both ways** — the single most consequential discovery; it forced the NAT NIC for the host-as-player design.
- **Hot-plugged NIC isn't auto-configured by HAOS** — `attach-interface --live` added the device but HAOS didn't DHCP it; a **VM reboot** was required to enumerate/configure it.
- **HAOS reboot requirement** — RAM/vCPU changes and NIC activation need a graceful reboot; after each reboot/MA-restart, the **HA↔MA integration** often drops (`ws://d5369777-music-assistant:8094` internal-DNS hiccup) and must be **reloaded**.
- **Stream server port behavior** — MA publishes the stream URL on its *primary* IP by default (`.104`); fetch-players must reach that IP, so the **publish IP had to be set to `.10`** for the host player. A `404` on `:8097/` is normal (server up, empty root).
- **Player discovery** — MA created the Squeezelite player as a **Universal player** wrapping the protocol player; AirPlay devices got both a legacy (CLIRaop) and a Sendspin (AirPlay-2) variant.
- **Chrome playback findings** — the browser web player can't be trusted over HTTP (insecure context → no Opus, autoplay blocked).
- **Samsung playback findings** — legacy AirPlay (CLIRaop) crashes on the AirPlay-2 soundbar.
- **YTMusic "not available"** — was stale-library-playlist track refs, not a broken provider (PO token + cookie verified healthy).
- **Resource starvation** — 2 GB caused 30 s playback-lock timeouts; 4 GB resolved it (MA recommends ≥4 GB).
- **Troubleshooting dead ends:** suspected the VM definition / OVMF / publish-IP / PO-token as the YTMusic cause — each ruled out by evidence. The Supervisor `/hassio` panel-missing root cause was **not** found (backend loads, panel doesn't register, persists across reboots) — parked.
- **SSH quirk** — the new OpenSSH client fails direct `-i` key auth (`we did not send a packet`); must use ssh-agent.

---

## 9. Dependency Map

| Component | Purpose | Depends on | Failure impact | Verify | Recovery |
|---|---|---|---|---|---|
| Host (homebrain) | Runs everything | hardware, power | Total outage (Plex+HA+MA+ceiling) | `ssh costea@192.168.1.68 uptime` | boot host |
| libvirt/KVM | Hosts VM | host, `/dev/kvm` | VM can't run | `virsh list --all` | restart `libvirt-bin` |
| HAOS VM `haos` | Runs HA+MA | libvirt, qcow2, OVMF, nvram | No HA/MA | `virsh domstate haos` | `virsh start haos` |
| NAT NIC `.10` | host↔VM link | libvirt `default` net | Ceiling zone dead (no control/stream) | host `curl .122.10:8095/info` | re-attach NIC (§5) |
| MA add-on | Music engine | Supervisor, internet | No music | `ha apps info d5369777_music_assistant` | `ha apps restart …` |
| MA stream server | Serves audio to players | MA, publish IP `.10` | Players silent | host `curl .122.10:8097/` (404 ok) | set publish IP; restart MA |
| PO-token add-on | YTMusic tokens | MA config URL `:4416` | YTMusic "not available" | host `curl -XPOST .122.10:4416/get_pot` | `ha apps restart …ytm_po…` |
| HA↔MA integration | HA control of MA | internal Docker DNS | No HA media_player control | entry state `loaded` | reload config entry |
| Squeezelite (host) | Ceiling player | MA SlimProto `.10`, `hw:1,0` | Ceiling silent | `systemctl status squeezelite-ceiling` | `systemctl restart …` |
| MA HA integration token | API automation | HA user | scripts fail | `curl -H Bearer …/api/` | mint new token |

---

## 10. Operational Runbook

> Prefix sessions with `ssh-add ~/.ssh/id_homebrain`. `virsh` needs no sudo (libvirtd group); host service ops need sudo via `ssh -t … sudo …`.

**Daily/health checks**
```bash
ssh costea@192.168.1.68 'virsh -c qemu:///system list --all'                 # VM running?
ssh costea@192.168.1.68 'curl -s -m5 http://192.168.122.10:8095/info'        # MA alive (host↔VM)?
ssh costea@192.168.1.68 'systemctl is-active squeezelite-ceiling'            # ceiling player up?
ssh costea@192.168.1.68 'df -h /'                                            # SSD free space
```
**Verify a player / play (best via MA UI: select player → Search → Play).** API (needs a long-lived token):
```bash
curl -s -H "Authorization: Bearer <TOKEN>" http://192.168.1.104:8123/api/states/media_player.ceiling_speakers
```
**Restart procedures**
```bash
ssh costea@192.168.1.68 'virsh -c qemu:///system reboot haos'                # whole VM (graceful)
# MA add-on (via HA service, needs token):  POST /api/services/hassio/addon_restart {"addon":"d5369777_music_assistant"}
ssh -t costea@192.168.1.68 'sudo systemctl restart squeezelite-ceiling'      # ceiling player
```
**Log locations**
- Squeezelite: `journalctl -u squeezelite-ceiling` (host; `costea` is in `adm` → no sudo to read).
- MA add-on: `GET /api/hassio/addons/d5369777_music_assistant/logs` (token) **or** `ha apps logs d5369777_music_assistant` (console).
- HA Core errors: WebSocket `system_log/list` (token); the legacy `/api/error_log` REST endpoint is **removed** in 2026.x.
- Supervisor/Core: `ha supervisor logs`, `ha core logs` (HAOS console via `virsh console haos` — needs host sudo for the console pty).

**Troubleshooting workflow**
1. No music anywhere → is MA up? (`/info` over `.10`). 2. Ceiling silent → `systemctl status squeezelite-ceiling` + `journalctl`; confirm MA stream publish IP = `.10`. 3. HA can't control MA → reload the MA config entry (DNS-hiccup). 4. "Playback failed to start" on a speaker → check the MA add-on log for `CLIRaop`/stream errors. 5. 30 s lock timeouts → resource pressure (check RAM).

**Validation after changes** — after any VM reboot/MA restart: VM running → MA `/info` 200 → MA integration `loaded` (reload if not) → `media_player.ceiling_speakers` idle → quick radio play.

---

## 11. Disaster Recovery

- **VM definition lost (disk intact):** `virsh define /home/costea/haos.xml && virsh autostart haos && virsh start haos`. Re-seed nvram first if missing: `cp /usr/share/OVMF/OVMF_VARS.fd /home/costea/haos_VARS.fd`. Re-add the NAT NIC + reservation (§5) if absent.
- **VM rebuild (full):** see `haos-vm-deployment.md` §11 (install OVMF, fetch HAOS image, `vol-create-as`+`vol-upload` to the pool, seed nvram, define from `haos.xml`). Then redo §5 (NAT NIC) and §6/§7 (MA + Squeezelite).
- **VM disk corruption:** restore a qcow2 backup to `/var/lib/libvirt/images/haos.qcow2` (cold copy; MA data lives inside the VM, so prefer **MA/HA built-in backups**).
- **Host failure:** rebuild host (do **not** upgrade OS per project constraint), reinstall KVM stack, restore the VM, reinstall Squeezelite (§13), re-point at `.10`.
- **Music Assistant corruption:** restore a HA backup that includes the MA add-on, or reinstall the add-on and re-add providers (YTMusic cookie + PO-token URL, Radio Browser, Squeezelite); set stream publish IP `.10`.
- **Home Assistant recovery:** HA UI backups (Settings → System → Backups) restored into a fresh HAOS.
- **Network recovery:** if the NAT link is lost, re-run §5; **never** touch `eno1`. If host↔VM still fails, last resort is the macvlan shim (documented escalation), not a bridge.

---

## 12. Upgrade Strategy

- **HAOS upgrades:** update in-place from the HA UI (Settings → System → Updates). ⚠️ The **2016-era QEMU 2.5 / OVMF / libvirt 1.3.1** stack may eventually fail to boot a newer HAOS. Mitigation: snapshot/backup before upgrading; if a major HAOS jump worries you, do a **disposable boot test** of the new image first (see `haos-vm-deployment.md` §8). Host OS is **not** to be upgraded (project rule).
- **Music Assistant upgrades:** update the add-on from the (UI if panel restored, else) `ha apps update d5369777_music_assistant`. Re-verify the stream publish IP (`.10`) and providers afterward.
- **Validation checklist after any upgrade:** VM boots → HA Core reachable → MA `/info` 200 → integration `loaded` → publish IP still `.10` → Squeezelite reconnects → radio plays on ceiling.
- **Age risk:** the whole VM substrate is EOL (Ubuntu 16.04, QEMU 2.5). Treat boots/upgrades as fragile; keep backups; the long-term fix is **host modernization** (§15).

---

## 13. Custom Files and Scripts

**`/etc/systemd/system/squeezelite-ceiling.service` (host):**
```ini
[Unit]
Description=Squeezelite - Music Assistant ceiling zone
After=network-online.target sound.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/bin/squeezelite -o hw:1,0 -n "Ceiling Speakers" -s 192.168.122.10 -C 5
Restart=always
RestartSec=5
User=root

[Install]
WantedBy=multi-user.target
```
**Manual configuration changes (not in any file):**
- MA → Settings → System → Streams → **publish IP = `192.168.122.10`**.
- MA → Settings → Providers → **YouTube Music** (Username + Login Cookie + PO Token URL `http://127.0.0.1:4416`), **Radio Browser**, **Squeezelite/SlimProto**.
- libvirt `default` network: `ip-dhcp-host` reservation MAC `52:54:00:ab:cd:20` → `192.168.122.10`.
- VM domain: 2nd NIC (NAT), RAM 4 GiB, 3 vCPU (in `/home/costea/haos.xml` / live config).

**Helper scripts staged in `/home/costea/`** (diagnostic/setup, removable): `setup-squeezelite.sh`, `test-ceiling-audio.sh`, `haos-console-diag.sh`. **Secrets:** none stored in any doc/script; the YTMusic login cookie lives only in MA; the diagnostic long-lived HA token used during setup is **still active** (kept for ongoing admin) and is to be **revoked at session end** — it is never written to any doc/repo/log.

**Home Assistant scripts** (stored in HA `.storage`, created via `POST /api/config/script/config/<id>`; all target `media_player.ceiling_speakers`):

| Script | Purpose | LLM-exposed |
|---|---|---|
| `ceiling_play_radio` (`station?`) | play radio + spoken confirmation | yes |
| `ceiling_pause` / `ceiling_resume` / `ceiling_stop` | pause / resume / stop (stop is silent) | yes |
| `ceiling_set_volume` (`volume` 0–100) | set volume (clamped) | yes |
| `ceiling_volume_up` / `ceiling_volume_down` | step volume | yes |
| `ceiling_announce` (`message`) | speak arbitrary text via Piper (reusable announcement primitive) | **no** |

**Home Assistant automations:**

| Automation | Purpose |
|---|---|
| `automation.voice_ceiling_speakers` | conversation-trigger voice-command handler (Phase 2) |
| `automation.ma_auto_reload_integration_after_restart` | **HA↔MA reconnect fix — A1 (validated 2026-06-23 — keep).** Reloads the Music Assistant config entry on HA start and ~120 s after MA returns from a restart (trigger: `media_player.ceiling_speakers` leaves `unavailable`), with a 10-min cooldown to prevent reload-flap loops. Catches **restart-induced** drops. |
| `automation.ma_health_probe_auto_reload` | **HA↔MA silent-drop watchdog — A2a (validated 2026-06-23 — keep).** Every 3 min probes the connection with a tiny `music_assistant.search`; if it errors/times out/returns no valid response, logs a warning and reloads the config entry. Catches **silent** drops A1 can't (player stays `idle`, not `unavailable`). No token; `mode: single` + 3-min interval = debounce. Validated via fault injection. |

**Why the auto-reload is needed:** the HA Music Assistant integration's connection to the add-on (`ws://d5369777-music-assistant:8094`) drops during MA/VM restart windows (internal Docker DNS) and does **not** auto-reconnect — it sits silently dead (search/play time out while the config entry still reports `loaded`; entities stay `idle`, not `unavailable`) until a manual config-entry reload. Diagnostics ruled out DNS-config faults, OOM (the `exit code 137` events are restart SIGKILLs, not memory), and version mismatch. The connection is otherwise rock-solid (20/20 search probes, <30 ms, over 10 min). The automation makes recovery automatic. **Rollback:** delete the automation. (The integration is `source: hassio`, `supports_reconfigure: false`, so pointing it at a stable URL is not possible without delete/recreate — hence the reload approach.)

### YouTube Music — final investigation result (2026-06-23)

A deep investigation into making YouTube Music playable via the assistant. **Conclusion: the infrastructure works, but playback execution is unreliable, so YTM stays unexposed to the LLM and is used from the MA app for now.**

| Layer | Result |
|---|---|
| **Auth (cookie + PO token)** | ✅ **Works.** PO-token generator healthy (auto-refresh). YTM login cookie works when extracted from a **private/incognito window closed without logging out** (plain cookies get rotated/invalidated by YouTube → MA logs *"cookies are no longer valid … rotated as a security measure"* → *"does not have Youtube Music Premium"*). |
| **Search / resolution** | ✅ **Works, fast & reliable.** `music_assistant.search` resolves `ytmusic://` URIs for track/artist/album/playlist/genre. |
| **HA↔MA connection** | ✅ **Solved** by the A1 + A2a automations above (self-healing). |
| **Playback (MA → Squeezelite)** | ❌ **Unreliable.** `music_assistant.play_media` frequently blocks 90 s+ and the track never starts. Root causes: a **stuck playback lock** on the Universal/Squeezelite player (`"Timed out (30s) acquiring playback lock … previous holder appears stuck"`) and **slow/looping per-track YTM stream resolution** (yt-dlp deno JS-challenge, ~30–60 s). Some albums/playlists start sometimes; single tracks often hang. `play_media` also queues-but-idle (needs a `media_player.media_play` nudge). |

**Decision:** YTM is **not** exposed to the LLM. The ChatGPT/Assist assistant is limited to **radio, weather, and the ceiling-speaker control scripts**. For YouTube Music, **use the Music Assistant app** (`http://192.168.1.104:8095`), where playback works. Local library + radio via the assistant are unaffected and reliable.

**Reliable play recipe (for reference, app/automation use):** `music_assistant.search` → take the top result's `uri` → `music_assistant.play_media` (media_id = uri) → `media_player.media_play` nudge. Free-text `play_media` (no URI) is unreliable; URIs are better but still subject to the stuck-lock/slow-resolution issues above.

**Possible future fixes (unverified, deferred):** play to the Squeezelite **protocol** player rather than the Universal-player wrapper; check VM **CPU starvation** during deno stream resolution (add vCPU); MA upstream improvements. `flow_mode` is enabled on the Ceiling player (harmless; did not resolve the lock).

### Stop-wedge investigation — Squeezelite `http_profile` (2026-06-24, CORRECTED)

> **Correction:** an earlier revision of this doc claimed `http_profile = chunked` fixed the wedge. That was wrong — `chunked` fixes the stop-wedge but **breaks playback** on this player (see below). Setting is **reverted to `no_content_length`**; the wedge remains unsolved at the `http_profile` layer.

The playback-lock / stuck-stream wedge was root-caused, but none of the three `http_profile` options fixes both playback and the stop-wedge.

**Trigger (identified via clean step-by-step trace):** `media_stop` of **any actively-playing stream** (radio *or* YTM — not YTM-specific). On stop, the Universal player went `idle` but the **Squeezelite protocol player stayed stuck `playing`** (it never detected end-of-stream). That stuck stream is the "previous holder appears stuck" that blocked every subsequent play with two 30 s lock timeouts.

**Root cause:** the Squeezelite output setting **`http_profile = no_content_length`** — with no content-length and no clean end signal, Squeezelite can't tell the stream ended on stop.

**Why `chunked` is not usable:** the Squeezelite client (aioslimproto) connects over **HTTP/1.0**, where chunked transfer-encoding is forbidden. With `chunked`, MA's `serve_queue_flow_stream` raises `RuntimeError: Using chunked encoding is forbidden for HTTP/1.0` → returns **HTTP 500** to Squeezelite on every stream → MA re-resolves and retries (lock timeouts, "Clearing active output protocol" aborts), so playback fails or limps in only after ~80–140 s of retries.

**Evidence (clean A/B per profile — both play and stop):**

| `http_profile` | Play (HTTP 500 / "chunked forbidden") | Stop → protocol returns idle? |
|---|---|---|
| **`no_content_length`** (current/baseline) | ✅ no 500 — plays | ❌ **WEDGE** (protocol stuck `playing`) |
| `chunked` | ❌ **HTTP 500** every stream (HTTP/1.0) → breaks/limps play | ✅ clean (terminating chunk) |
| `forced_content_length` | ✅ no 500 (0/0) — plays | ❌ **WEDGE** (same as no_content_length) |

**Net:** only `chunked` clears the stop-wedge, but it breaks streaming to the HTTP/1.0 client; the two HTTP/1.0-compatible profiles both wedge on stop. **No `http_profile` value fixes both.** Reverted to `no_content_length`.

**Impact of the wedge (with `no_content_length`):** audio *does* stop on stop, but the protocol player's internal state stays `playing`, holding the lock — so the *next* play after a stop incurs the ~30–60 s lock-timeout delay. First play from a truly clean state is unaffected.

**Real root constraint:** the Squeezelite player speaks **HTTP/1.0** and doesn't detect end-of-stream on a content-length/connection-close stop. Promising future directions (untested): run Squeezelite with HTTP/1.1 (newer build / flags) so `chunked` becomes usable; or an MA-upstream fix to the stop handling for SlimProto.

**Separate issue:** YTM **track start latency** — cold first play ~95–150 s (post-resolution lock/stream-setup, not CPU: VM ~5 %); resolution itself is ~14 s; **cached replay ~2 s**.

**Rollback (current = `no_content_length`, the baseline):** to change, MA UI → Settings → Players → Ceiling Speakers → HTTP profile; or MA API `config/players/save` on `upf8b156c25101` with `{"f8:b1:56:c2:51:01||protocol||http_profile":"<value>"}`. Config snapshots: `scratchpad/ma_cfg_before_chunked_retest.json`, `ma_cfg_before_fcl.json`.

---

## 14. Rollback Procedures (copy-paste)

```bash
# --- Squeezelite (host) ---
ssh -t costea@192.168.1.68 'sudo systemctl disable --now squeezelite-ceiling'
ssh -t costea@192.168.1.68 'sudo rm -f /etc/systemd/system/squeezelite-ceiling.service && sudo systemctl daemon-reload'
ssh -t costea@192.168.1.68 'sudo apt-get remove -y squeezelite'         # optional

# --- NAT NIC (VM, via virsh; no sudo) ---
ssh costea@192.168.1.68 "virsh -c qemu:///system detach-interface haos network --mac 52:54:00:ab:cd:20 --live --config"
ssh costea@192.168.1.68 "virsh -c qemu:///system net-update default delete ip-dhcp-host \"<host mac='52:54:00:ab:cd:20' name='haos-nat' ip='192.168.122.10'/>\" --live --config"

# --- VM resources back to 2 GiB / 2 vCPU (then reboot) ---
ssh costea@192.168.1.68 "virsh -c qemu:///system setmaxmem haos 2097152 --config; virsh -c qemu:///system setmem haos 2097152 --config; virsh -c qemu:///system setvcpus haos 2 --config; virsh -c qemu:///system reboot haos"

# --- Music Assistant rollback ---
# Remove integration: Settings → Devices & Services → Music Assistant → Delete
ssh costea@192.168.1.68 "ha apps stop d5369777_music_assistant; ha apps uninstall d5369777_music_assistant"   # via HAOS console
# (also uninstall d5369777_ytm_po_token_generator if desired)

# --- LLM assistant rollback (Phase 3 — OpenAI/ChatGPT), all via UI or WS/REST API ---
# 1. Delete the "ChatGPT" Assist pipeline:  Settings → Voice assistants → ChatGPT → Delete
#    (WS: assist_pipeline/pipeline/delete {pipeline_id: <chatgpt id>})
# 2. Delete the OpenAI Conversation integration (removes the agent AND the stored API key):
#    Settings → Devices & Services → OpenAI Conversation ("ChatGPT") → Delete
# 3. (Optional) delete the 7 helper scripts: DELETE /api/config/script/config/ceiling_<...>
#    (harmless if kept; they only control the ceiling speakers)
# 4. Restore exposure from phase3_exposure_snapshot_before.json:
#    - homeassistant/expose_new_entities/set {assistant: conversation, expose_new: true}
#    - re-expose todo.shopping_list, update.music_assistant_update, media_player.samsung_q82ca_75
#    - un-expose the 7 scripts + weather.forecast_home (or leave; harmless)
# Note: automation.voice_ceiling_speakers and the preferred "Home Assistant" pipeline are NOT touched by any of this.

# --- Recovery to previous state ---
# Old HA Core 0.57.2 + Plex were never modified; they remain on the host independently.
```

---

## 15. Future Roadmap

- **Samsung soundbar:** drive it via MA's **AirPlay-2 / Sendspin** player instead of legacy CLIRaop; or via a different transport.
- **YouTube Music:** confirm a search-track plays audibly; clean up stale restored playlists; consider periodic cookie refresh.
- **Voice assistant / microphone / GPT voice:** add HA Assist + a wake-word/mic satellite; pipe TTS to the ceiling zone; optionally an LLM conversation agent. (HAOS already has Whisper/Piper/openWakeWord add-ons available.)
- **Additional audio zones:** more Squeezelite/AirPlay/Cast endpoints; each new fetch-player on the LAN would reintroduce the single-publish-IP conflict → revisit networking (macvlan shim) at that point.
- **Snapcast re-evaluation:** only if synchronized multi-room across multiple snapclient-capable zones becomes a goal.
- **Host modernization:** the EOL Ubuntu 16.04 / QEMU 2.5 substrate is the biggest long-term risk; a host OS/hypervisor refresh would also unlock a clean **bridge** (eliminating the NAT-NIC/publish-IP gymnastics) and fix the Supervisor-panel oddity.

---

## 16. Change Log

| Date | Event |
|---|---|
| 2026-06-21 | **HAOS VM deployment**: inventory; installed OVMF; defined SSD storage pool; disposable HAOS 18.0 boot test (passed on QEMU 2.5/OVMF 2016); production VM `haos` (q35/UEFI/host-passthrough, macvtap, autostart). |
| 2026-06-21 | **Migration analysis**: documented legacy HA Core 0.57.2 (see `migration-inventory.md`); decided no in-place upgrade — rebuild integrations in HAOS. |
| 2026-06-21 | **Music Assistant install**: `ha apps install d5369777_music_assistant` (v2.9.3); integration added (fixed "addon discovery" race via addon_restart + reload). |
| 2026-06-21 | **YouTube Music**: provider added (cookie + PO Token Generator `:4416`); discovery diagnostics (Supervisor `/hassio` panel found missing — parked). |
| 2026-06-22 | **NAT NIC addition**: 2nd VM NIC on `default` NAT, static `192.168.122.10`; VM reboot to activate; host↔VM verified. |
| 2026-06-22 | **Squeezelite deployment**: installed on host; `squeezelite-ceiling.service` → `hw:1,0`, server `.10`; MA SlimProto provider enabled; **stream publish IP set to `.10`**. |
| 2026-06-22 | **Resource bump**: VM 2→**4 GiB RAM**, 2→**3 vCPU** (resolved 30 s playback-lock timeouts). |
| 2026-06-22 | **Ceiling speaker validation**: internet radio played through the ceiling speakers — zone confirmed working. |
| 2026-06-22 | **Voice control Phase 1**: diagnosed entity not exposed to Assist; created `automation.voice_ceiling_speakers` (conversation-trigger, no infra); verified all 6 commands (play radio / pause / resume / stop / volume 25 / volume 50) via the conversation API. |
| 2026-06-22 | **Voice control Phase 2 (phone mic)**: installed Whisper + Piper add-ons; created Wyoming integrations (faster-whisper, piper) via config-flow API; set pipeline STT=Whisper. Diagnosed "Oops": built-in intents intercepting the *exposed* player (called unsupported `media_player.turn_off`) **and** Piper TTS crashing the pipeline. Fix: un-exposed the media players (automation = sole handler), disabled TTS, and expanded the automation to natural-language phrasings with **generic digit/spoken-number volume capture** (0–100) + relative volume. Voice confirmed working end-to-end (text replies; Piper TTS parked). |
| 2026-06-22 | **LLM assistant Phase 3 (OpenAI/ChatGPT)**: added a **separate** `conversation.openai_conversation` agent (gpt-4o-mini, Control-HA=Assist) + a "ChatGPT" pipeline (local Whisper STT, TTS off) **alongside** the unchanged deterministic assistant (still preferred). Created 7 `script.ceiling_*` helper scripts as the LLM's sole action surface; **tightened exposure** to exactly those 7 + `weather.forecast_home`, turned `expose_new_entities` off, and un-exposed the TV/todo/MA-update (before/after snapshots saved). Disabled web-search/code-interpreter/response-storage/location; removed auto-created stt/tts/ai_task subentries. Verified from Assist text: ceiling control + weather work; TV/soundbar/thermostat refused with zero state change. |
| 2026-06-22 | **Ceiling TTS announcements**: investigated the parked Piper "crash" — Piper generates valid audio (31 KB MP3 fetched from host); root cause was the fixed exposed-intent issue + first-run voice race, not Piper. Added spoken output via explicit `tts.speak` (Piper → `media_player.ceiling_speakers`, played by MA/Squeezelite over NAT `.122.10`). New `script.ceiling_announce` (reusable, **not LLM-exposed**); `script.ceiling_play_radio` now gives a spoken confirmation; `script.ceiling_stop` stays silent (MA announcements resume prior playback, so a stop confirmation un-stops the music). Phone pipeline TTS still off; no `internal_url`/networking changes. |
| 2026-06-23 | **HA↔MA reconnect fix (A1)**: diagnosed YTM-via-assistant unreliability to the MA integration not auto-reconnecting after restart windows (ruled out DNS-config, OOM, version mismatch; connection is stable once established — 20/20 probes <30 ms/10 min). Added `automation.ma_auto_reload_integration_after_restart` (reload config entry on HA start + 120 s after MA returns from restart; 10-min cooldown) — **validated, keep it.** Enabled MA `flow_mode` on the Ceiling player (harmless). **Open:** YouTube Music **cookie rotation** keeps invalidating auth → YTM provider fails to load; assistant stays radio-only, YTM **not** exposed to the LLM. |
| 2026-06-23 | **YTM investigation closed (option 1 — lock in wins).** Cookie fixed via incognito extraction; auth + search confirmed working. Added A2a `automation.ma_health_probe_auto_reload` (3-min health probe → reload on failure; no token; fault-injection validated) alongside A1 — HA↔MA connection now self-heals (restart + silent drops). **Playback via MA→Squeezelite remains unreliable** (stuck playback lock + slow per-track stream resolution), so **YTM stays unexposed to the LLM**; use the MA app for YTM. Assistant scope = radio + weather + ceiling control scripts. |
| 2026-06-24 | **Stop-wedge FIXED.** Root-caused the playback-lock wedge: `media_stop` of any live stream (radio or YTM) left the Squeezelite protocol player stuck `playing` (no end-of-stream detection) due to `http_profile = no_content_length`. Changed Ceiling player `http_profile` → **`chunked`**; clean A/B confirms stop now returns both Universal + protocol to `idle` in ~3 s (was: stuck/WEDGE). Eliminates the "previous holder appears stuck" lock cascade. **Open:** YTM track start latency ~150 s (separate slow-resolution issue). YTM still not exposed to the LLM. |
| 2026-06-24 | **CORRECTION — `chunked` is NOT the fix; reverted to `no_content_length`.** Cold-start gap capture showed `chunked` makes MA's stream server return **HTTP 500 ("chunked encoding forbidden for HTTP/1.0")** to the Squeezelite client (HTTP/1.0) → breaks/limps playback. Tested `forced_content_length`: no 500s but **still wedges on stop** (like no_content_length). So no `http_profile` value fixes both play and stop-wedge; only `chunked` clears the wedge but it breaks streaming. **Reverted to `no_content_length`** (baseline). Root constraint = Squeezelite HTTP/1.0 + no end-of-stream detection on stop. Wedge impact: audio stops, but the stuck protocol state delays the *next* play by ~30–60 s (lock). YTM still not exposed to the LLM. |
| 2026-06-24 | **Onboarding + upstream research.** Added [`ONBOARDING.md`](./ONBOARDING.md) as the primary entry point (investigation timeline, ranked hypotheses, ruled-out dead-ends, next steps, architecture decision log, research brief). Completed read-only upstream research → [`research-playback-lock.md`](./research-playback-lock.md): stop-wedge root cause traced in MA source to the PROTOCOL-player stop path (`client.power(False)` no-op → SlimClient never reaches STOPPED → Universal stop coroutine never returns → playback lock never released). **Corrections:** "run Squeezelite with HTTP/1.1" is a dead end (HTTP version is server-dictated by aioslimproto, not the client); no fix in MA 2.10 beta changelogs. Next: live `aioslimproto`/squeezelite debug trace (check `strm "q"` + STMu) to confirm, then file upstream. |
