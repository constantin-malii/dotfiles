# S0 — Voice Satellite Inventory (read-only)

> Point-in-time snapshot. Source of running-state truth = `ONBOARDING.md` / `CHANGELOG.md`.
> Captured: 2026-07-14 · method: read-only HA REST (`/api/states`, `/api/config`) + WS registries
> (`device`/`entity`/`area`) + `assist_pipeline/pipeline/list`. No mutations.

> **Scope:** the first (and currently only) voice satellite — `reSpeaker Living Room` — onboarded
> 2026-07-14 (see `CHANGELOG.md`). This is the satellite-side mirror of the HA-01 device inventory,
> covering the five S0 dimensions: **entities · rooms/zones · pipelines · TTS-reach · identity**.
> Read-only; no exposure/pipeline/registry/area changes were made.

---

## 0. Scope & method

- **What this is:** a read-only inventory of the voice-satellite endpoint(s) and the facts the
  Track-S routing work (`S1`–`S4`) and the AU multi-room policy need: which entities exist, room/zone
  assignment, the assigned Assist pipeline (STT/TTS/conversation), whether/where the satellite can
  emit TTS, and stable identity.
- **What it is not:** not a routing design (that's `S1`), not an exposure change, not a full HA
  inventory (that's `HA-01`).
- **Method:** HA REST `GET /api/states` + `/api/config`; WS `config/{device,entity,area}_registry/list`
  and `assist_pipeline/pipeline/list`. Token used in-memory only; nothing written/logged/committed.
- **Count:** **1 satellite** (`reSpeaker Living Room`).

---

## 1. Identity

| Field | Value |
|---|---|
| Device name | `reSpeaker Living Room` |
| Manufacturer / model | `formatbce` / **Respeaker XVF3800 Satellite** |
| Firmware | ESPHome **2026.6.5** (project version 2026.6.0) · XMOS DSP **1.0.7** |
| MAC | `68:ee:8f:51:e4:0c` (registry `connections`) |
| Platform / integration | ESPHome (formatBCE config) |
| Network | Wi-Fi SSID `telus3185` (LAN `192.168.1.x`). IP not surfaced read-only (`configuration_url=None` in registry) — `TODO:` capture IP if needed |
| Hardware audio | **No built-in speaker** — external speaker via 3.5mm jack (JST 5W also available) |

---

## 2. Entities

All ESPHome-platform entities on the device (enabled unless noted). Total on device: 24 (5 disabled-by-integration).

**Voice core**
| entity_id | state | notes |
|---|---|---|
| `assist_satellite.respeaker_living_room_assist_satellite` | idle | the satellite endpoint (supported_features=3) |
| `media_player.respeaker_living_room_media_player` | idle | `device_class=speaker`, volume 0.5 — the satellite's local audio out |

**Wake word / assistant selection**
| entity_id | state | options |
|---|---|---|
| `select.…_wake_word` | **Okay Nabu** | no_wake_word, Hey Jarvis, Hey Mycroft, Kenobi, Okay Nabu |
| `select.…_wake_word_2` | no_wake_word | (2nd on-device wake-word slot — currently unused) |
| `select.…_assistant` | **Living Room Voice** | preferred, ChatGPT, Home Assistant, Living Room Voice |
| `select.…_assistant_2` | preferred | (2nd assistant slot — currently unused) |
| `select.…_wake_word_sensitivity` | Slightly sensitive | |
| `select.…_finished_speaking_detection` | default | |

**Controls / feedback**
`number.…_led_ring_brightness` (0.8) · `select.…_led_ring_color_preset` (Custom) · `select.…_alarm_action`
(Play sound) · `switch.…_wake_sound` (on) · `switch.…_mute_unmute_sound` (on) · `switch.…_beam_lock`
(off) · `switch.…_microphone_mute` (off) · `switch.…_alarm_on` (off) · `time.…_alarm_time` (00:00) ·
`sensor.…_current_device_time` · `sensor.…_firmware_version` (1.0.7).

**Disabled-by-integration** (present but off): `button.…_restart`, `select.…_logger_level`,
`sensor.…_next_timer`, `sensor.…_next_timer_name`, `update.…_firmware`.

> **Dual-slot note:** the firmware exposes a **second wake-word and second assistant slot** — so a
> future "second wake word → ChatGPT pipeline" is possible on this hardware without changes here.

---

## 3. Rooms / zones

| Field | Value |
|---|---|
| Satellite HA **area** | **None — unassigned** ⚠️ |
| Available areas (from `HA-01`) | Living Room, Kitchen, Bedroom, Furnace (all but Furnace empty) |
| Satellite → media-zone map | **Not established** — the satellite has no route to the ceiling zone (`media_player.ceiling_speakers`); that is `S1` + AU-01 interface |

> **Gap (blocks room-aware routing):** the satellite is not assigned to an HA area. Assigning it to
> **Living Room** is the prerequisite for `InteractionContext`/`ResponseRoutingPolicy` (`S1`) and the
> AU-01 multi-room per-zone policy to resolve "which zone reacts." Small live UI change; **not done
> here** (S0 is read-only).

---

## 4. Pipelines (STT / TTS / conversation)

All Assist pipelines (`assist_pipeline/pipeline/list`); `*` = HA preferred:

| Pipeline | STT | TTS | Conversation | Used by |
|---|---|---|---|---|
| `*` Home Assistant | `stt.faster_whisper` | **None** | `conversation.home_assistant` | phone / default (shared) |
| ChatGPT | `stt.faster_whisper` | **None** | `conversation.openai_conversation` | opt-in (shared) |
| **Living Room Voice** | `stt.faster_whisper` | **`tts.piper`** | `conversation.home_assistant` | **this satellite** |

- The satellite runs the **dedicated "Living Room Voice"** pipeline (`id 01kxhm0a1vcdjwkrbp40a6cs43`) —
  Whisper STT + **Piper TTS** + the local HA conversation agent. Wake word is **on-device** (pipeline
  `wake=None` is expected).
- This **isolates Piper TTS to the satellite**; the shared Home Assistant / ChatGPT pipelines keep
  `tts=None` (phone/default untouched). Spoken replies verified working (see `CHANGELOG.md` 2026-07-14).

---

## 5. TTS-reach (where the satellite can be heard)

| Path | Status |
|---|---|
| **Local** (satellite's own `media_player` → external 3.5mm speaker) | ✅ Working — spoken replies confirmed. Requires the HA **Internal URL = LAN** fix (2026-07-14). |
| **Ceiling zone** (`media_player.ceiling_speakers`) | ❌ Not wired — no satellite→ceiling output route yet. Design/impl = `S1` using the AU-01 per-zone interface. |
| **Other rooms / satellites** | n/a — only one satellite exists. |

---

## 6. Gaps / TODO

- ⚠️ **Area unassigned** — assign `reSpeaker Living Room` to the **Living Room** area (prereq for S1/AU routing). Live UI change; not done here.
- **No satellite→ceiling output route** — `S1` + AU-01 interface (the "duck the music, reply on the ceiling" behavior).
- `TODO:` device **IP** not captured read-only (`configuration_url=None`); grab from ESPHome logs if needed.
- Second **wake-word / assistant slots** unused — available for a future ChatGPT-on-second-wake setup.
- Whole-home coverage = **1 room only** (Living Room). Additional satellites → repeat this inventory per unit.

---

## 7. Downstream feeds

| Consumer | Consumes |
|---|---|
| `S1`–`S4` (InteractionContext / ResponseRoutingPolicy / privacy / announce-targeting) | §1 identity, §3 area/zone map, §4 pipeline, §5 TTS-reach |
| `AU-01` multi-room (per-zone policy interface, S0-gated) | §3 satellite→zone map, §5 TTS-reach |
| `AU-02`/`AU-03` (resume-restore, ducking impl) | §5 (ceiling zone is their target; satellite is the trigger source) |
| Future satellites / whole-home voice | this doc as the per-satellite inventory template |

---

## 8. Unknowns

- Device **IP address** — not exposed via the registry read; `TODO:` from ESPHome logs if a direct
  address is needed (mDNS/name works today).
- Exact **XVF3800 beamforming / AEC behavior** with a connected speaker — not inventoried here
  (functional; `beam_lock=off`). Out of scope for S0.
