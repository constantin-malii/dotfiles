# Existing Device Integration Architecture & Roadmap

> Architecture/research only. No implementation, no purchases, no HA changes. Inputs:
> user-provided existing-device intake + HA-01 (ha-device-inventory.md) + SA-01/02
> (2026-06-30-sa-01-02-safety-alerts-design.md). HA-01 shows HA-VISIBILITY, not physical
> ownership. Locale: CA / Edmonton (120 V). Live gate (BACKLOG §10) left FREE.
>
> Track: provisional **HA-07 candidate** (or RQ-05 reframe — see §12) · Type: research/architecture
> · Branch: `homebrain/ha-device-integration-roadmap`. This doc maps existing devices to HA
> integration paths and derives true purchase gaps last; it does **not** build, buy, or configure
> anything.
>
> **Intake maturity:** FOLLOW-UP ROUND 1 + PHASE-4 RESEARCH COMPLETE (2026-06-30). Nine model
> screenshots confirmed a concrete roster (§3); a **read-only, HA-docs-first web research pass**
> (user-approved) resolved the per-model integration paths (§4, §13.b). Still **UNKNOWN**: UPS,
> standalone siren, leak sensors, satellite quantity/rooms, fiber-ONT model, and non-listed ecosystem
> accounts (§13.a). Per user instruction, model-specific facts are cited to their source (official HA
> docs first) with an access date; uncertainty is flagged, not guessed. **Device secrets/identifiers
> (serials, camera UID, MAC, full SSID, gateway IP) are deliberately omitted from this doc.**

---

## 0. Scope & method

**What this IS:** a single architecture/research roadmap that (1) intakes the user's *existing
physical* devices (by asking the user), (2) classifies each into five ownership buckets, (3) maps
each device/category to its HA integration path and architecture (local vs cloud, coordinator/
bridge/account needs, privacy/reliability), (4) applies the life-safety-primary / HA-secondary
posture from SA-01/02, (5) covers camera/vacuum/plug/UPS/area architecture, (6) derives **true
purchase gaps only after** existing-device mapping, and (7) *recommends* (without applying)
BACKLOG.md changes.

**What this is NOT:** not an implementation (no HA automation/script/entity/exposure, no code, no
resolver change, no device pairing/config), not a purchase (no cart/checkout/order), not a
running-state narrative (that lives in `ONBOARDING.md` / `CHANGELOG.md`, referenced not duplicated),
and not an edit to `BACKLOG.md` (INF-owned — §12 proposes only).

**Method / phasing:**
- **Phase 1 (offline):** read the source docs; scaffold; fill §1 (sources) + §2 (HA-visible
  baseline). No HA/host/web access.
- **Phase 2 (interactive):** existing-device **intake** — ask the *user*. Rough pass + nine model
  screenshots received (§3). Ownership truth is the user's.
- **Phase 3 (offline):** architecture mapping (§4–§11) as decision paths.
- **Phase 4 (approval-gated, DONE 2026-06-30):** user-approved **read-only** web research to resolve
  §13.b, **official HA docs first → vendor → forums (secondary)**. No shopping/price/login/checkout;
  scoped to the listed devices only. Findings cited with source + access date (§4, §13.b).

**Live-system posture:** live HA access = **NO** (this doc runs off HA-01's inventory). No host
access, no service restarts, no exposure/unexposure changes, no resolver changes. **This doc claims
no live-system gate — BACKLOG §10 left FREE.**

**Ownership truth rule (governs the whole doc):** *absence from Home Assistant ≠ absence from the
home.* HA-01 proves only what HA can see. The user owns a substantial device fleet HA cannot see,
plus one device HA sees only partially (the ecobee, as a speaker). Ownership is established by
**user intake (§3)**, never inferred from HA.

---

## 1. Source documents read

Read read-only from the worktree base (`origin/main` @ `fde0766`). HA-01 (PR #5) and SA-01/02
(PR #6) are both merged on `main` — no "pending merge" caveat applies.

| Doc | Item / role | Key sections used |
|---|---|---|
| `docs/homebrain/ha-device-inventory.md` | **HA-01** — HA-visible inventory (2026-06-30) | §2 entities, §4 areas, §5 devices, §6 integrations, §7 battery/health, §8 gaps, §10 feeds |
| `docs/homebrain/2026-06-30-sa-01-02-safety-alerts-design.md` | **SA-01/02** — safety design | §1 inventory, §2 channels, §3 smoke/CO, §4 water/leak, §6 buy-list + coordinator prereq, §8 open Qs |
| `docs/homebrain/ONBOARDING.md` | System map / connectivity / norms | §1 host+VM+network, §2 connectivity, §4 IDs, §12 exposure/TTS, §15 norms |
| `docs/homebrain/CHANGELOG.md` | Latest operational state | Inc 2A/4A exposed; exposure=13; no coordinator |
| `docs/homebrain/BACKLOG.md` | Track defs + operating model | §3 tracks, §5 items, §8 rules, §9 shared-file lock, §10 gate register, §12 report format |
| `CLAUDE.md` (repo) | Worktree + live-system rules | Worktree rule, operating rules, commit/PR norms |

---

## 2. Known HA-visible devices (from HA-01)

> **HA *visibility*, not ownership.** Only what HA can see today (HA-01 §2/§5/§6). Actual hardware is
> §3. "Absent from HA" (HA-01 §8) = *not integrated*, not *not owned*.

| Category | HA-visible entity/device | Integration | State / note |
|---|---|---|---|
| Media — ceiling zone | `media_player.ceiling_speakers` (MA → host Squeezelite) | `music_assistant` | `idle`; the one reliable audible channel |
| Media — soundbar | `media_player.samsung_soundbar_q930c` | `music_assistant` | **offline/unavailable** (INF-03) |
| Media — TV | `media_player.samsung_q82ca_75` | `music_assistant` | `idle` |
| Media — thermostat-as-speaker | `media_player.upperthermostat` | `music_assistant` | **= the ecobee SmartThermostat (§3/§4.9).** Speaker only; **no `climate`** |
| Phones ×3 | Costea / Vio / Huawei | `mobile_app` | `device_tracker` + battery + `notify.*` |
| Printer | HP LaserJet 1320 | `ipp` | only area-assigned device → **Furnace** |
| Weather / sun / backup | Met.no / sun / backup | `met`/`sun`/`backup` | weather is the only entity exposed to `conversation` |
| Voice pipeline | Piper/Google TTS, Whisper STT, 2 agents | `wyoming`/… | Piper reaches ceiling only (NAT-IP); phones get push |
| Lists | `todo.shopping_list` | `shopping_list` | — |

**Integrations present (HA-01 §6 — 17, all loaded):** `mobile_app` ×3, `hassio`, `music_assistant`,
`sun`, `backup`, `ipp`, `met`, `google_translate`, `openai_conversation`, `wyoming` ×2,
`shopping_list`, `radio_browser`, `analytics`, `go2rtc`.

**Decisive absences in HA today (HA-01 §6/§8) — visibility gaps, not ownership claims:** no
`zwave_js`/`zha`/`matter`/`thread` coordinator (yet the user owns a **Z-Wave** device); no `camera`
entities (`go2rtc` + `camera` loaded, plumbing ready; the user owns two cameras); no
`vacuum`/`cover`/`switch`/`light`/`climate` control, no smoke/CO/moisture `binary_sensor`, no
`siren`, no `assist_satellite` — though the user owns/has-incoming devices in every one of those
classes. Area map effectively empty (only printer→Furnace; HA-01 §4). Only the 3 phones report
battery (HA-01 §7).

---

## 3. User-owned devices intake table

> **FOLLOW-UP ROUND 1 (2026-06-30).** Ownership by the *user*. Confirmed-owned devices are **not
> `VISIBLE IN HA`** (except the ecobee, partially). Model-specific HA behaviour confirmed via §13.b.
> Unconfirmed categories stay **UNKNOWN**, never "absent". Secrets/identifiers omitted.

**Legend:** `CONFIRMED OWNED` · `VISIBLE IN HA` · `OWNED BUT NOT INTEGRATED` · `UNKNOWN
MODEL/PROTOCOL` · `NOT OWNED (TRUE GAP)`.

| Category | Device / model | Ownership class | Protocol / app / cloud | Notes |
|---|---|---|---|---|
| Smoke/CO alarm | **First Alert SC7010BA** (hardwired smoke + CO) | **CONFIRMED OWNED** | Analog / hardwired-interconnected | Life-safety PRIMARY (SA-01); its own sounder is the primary alarm; has 9 V battery backup. |
| Smoke → HA bridge | **Zooz ZEN55 LR** (800-series Z-Wave LR DC Signal Sensor) | **CONFIRMED OWNED** (2026-05-11) | **Z-Wave** — hub required | **Stranded: no Z-Wave coordinator (HA-01 §6).** Non-invasive bridge (§4.1/§5.1). |
| Camera 1 | **Reolink RLC-820A** (PoE, garage) | **CONFIRMED OWNED** | Reolink; PoE; local RTSP/ONVIF | Storage "Not Formatted". `go2rtc` ready (§6). |
| Camera 2 | **Reolink 2K Wired Video Doorbell** (Wi-Fi) | **CONFIRMED OWNED** | Reolink; Wi-Fi; local RTSP/ONVIF | Doorbell = camera + press event + chime (§6). |
| Vacuum | **iRobot Roomba Combo** (SKU c755020) | **CONFIRMED OWNED** | Wi-Fi; iRobot | Local-push path (§4.3/§7). |
| Switch/plug | **TP-Link Kasa HS220** (in-wall dimmer, Wi-Fi) | **CONFIRMED OWNED** | Kasa; local + optional cloud | A **dimmer** (`light`), not a plug; no energy monitoring (§8). |
| Garage door | **Meross MSG100** (Wi-Fi; "Works with HomeKit") | **CONFIRMED OWNED** | Meross cloud + HomeKit (local) | `cover`; **access/safety-sensitive** (§4.8). |
| Thermostat | **ecobee SmartThermostat with Voice Control** | **CONFIRMED OWNED** + partially **VISIBLE IN HA** (speaker only) | ecobee cloud; Alexa built-in | No `climate` in HA yet (§4.9). "Upper" → ≥2 levels. |
| Router / network | **TELUS Wi-Fi Hub** (Arcadyan) + upstream **fiber ONT** (UNKNOWN) | **CONFIRMED OWNED** | ISP = TELUS (fiber) | ONT → hub → LAN. Guest-SSID only, no native VLAN (§4.5). |
| Hubs / coordinators | **none** (Z-Wave hub the ZEN55 needs is absent) | **NOT OWNED (TRUE GAP)** — near-certain | — | No local radio coordinator. §4.7 keystone. |
| Voice satellite | **reSpeaker XMOS XVF3800 + XIAO ESP32-S3 (Case)** — INCOMING (on order) | **CONFIRMED OWNED (incoming)** | ESP32-S3 → ESPHome / Wyoming (local) | **Unblocks `S0`** (§4.10). Needs an external speaker for TTS. |
| Leak / water sensors | not confirmed | **UNKNOWN MODEL/PROTOCOL** | UNKNOWN | Confirm before calling a gap. SA-02 (§5.2). |
| Sirens / sounders | not confirmed | **UNKNOWN MODEL/PROTOCOL** | UNKNOWN | SC7010BA sounder is primary; ZEN55 relay can drive a local siren (§5.3). |
| UPS / battery backup | not confirmed | **UNKNOWN MODEL/PROTOCOL** | UNKNOWN | Infrastructure-resilience (§9); not life-safety-primary. |
| Mobile apps / clouds | partly revealed | **partially known** | Reolink, iRobot, Meross, Kasa, ecobee, Apple HomeKit; Google/Alexa/SmartThings TBD | §13.a. |

**Reading of this intake.** The home is **device-rich but HA-poor** — eight owned smart devices, only
the ecobee partially in HA. Today's de-facto architecture is **cloud-heavy** (both Reolinks, Roomba,
Kasa, Meross, ecobee are Wi-Fi/cloud; Meross is also HomeKit-local), and **one device is Z-Wave but
non-functional for lack of a coordinator** (ZEN55). Standout fact: the user **already bought the
local-radio path (a Z-Wave ZEN55) without the coordinator that makes it work** — so a Z-Wave
coordinator is a *confirmed* gap that unlocks a sunk purchase and serves SA-01 (smoke telemetry) +
future SA-02 (leak).

---

## 4. Integration architecture by category

Each subsection: the architectural class + the **confirmed integration path** from the Phase-4
research (official HA docs first; full findings + source URLs in §13.b, accessed 2026-06-30).
Local-first is preferred for privacy/reliability; cloud is flagged.

### 4.0 Decision framework

**Paths:** native HA · vendor **cloud** · **local LAN** · **Zigbee** / **Z-Wave** (coordinator) ·
**Matter/Thread** (controller + border router) · **MQTT** · **ONVIF**/**RTSP** · **HomeKit
Controller** (local) · **ESPHome** · **NUT** · **bridge/hub** · unsupported.
**Two axes:** (1) LOCAL-FIRST vs CLOUD-DEPENDENT (local = survives outages, private, may need a
coordinator/bridge/firmware; cloud = internet+vendor-dependent, discouraged for life-safety and a
privacy concern for cameras + garage); (2) coordinator/bridge/account requirement (what turns a
single-device integration into an infrastructure decision). **Keystone:** no coordinator exists
(HA-01 §6) and the user owns a **Z-Wave** device → §4.7 (adopt Z-Wave).

### 4.1 Smoke/CO — First Alert SC7010BA + Zooz ZEN55 LR (life-safety, see §5)

- **Detector:** SC7010BA — hardwired interconnected smoke + CO alarm with its **own interconnected
  sounder** (SA-01 PRIMARY) and 9 V battery backup.
- **Bridge:** ZEN55 LR — a **Z-Wave** signal sensor that reads the analog detectors' interconnect
  line **without altering the certified device** (the SA-01-endorsed non-invasive listener).
- **✅ Confirmed (Z-Wave JS; §13.b):** the ZEN55 is supported by **Z-Wave JS** (local; no cloud) and
  **distinguishes smoke vs CO** from the signal pattern → exposes **TWO separate `binary_sensor`s**
  (`device_class: smoke` and `carbon_monoxide`). It is **mains-powered (no battery of its own → no
  battery entity)**, and provides a **relay endpoint** (a `switch`) that can drive a local 120 V
  siren/light on alarm (parameter P2/P8). Sensor entities may be **disabled by default** on pairing.
  **Blocking fact:** it needs a **Z-Wave coordinator, which is absent (HA-01 §6)** → today it cannot
  report. Z-Wave Long Range needs an LR-capable 800-series controller + ZEN55 fw ≥ 1.20.
- **Do not replace the detector for smart integration (SA-01).** Full safety treatment in §5.

### 4.2 Cameras — Reolink RLC-820A + Reolink Video Doorbell (see §6)

- **✅ Confirmed (native `reolink`; §13.b):** both are supported by the **local `reolink`
  integration** — **fully local, no cloud subscription/account**; RTSP + ONVIF available; go2rtc is
  **built into HA since 2024.11** and restreams them. RLC-820A exposes 40+ entities incl.
  motion/AI-person/vehicle detection. The doorbell adds a **`Visitor` press `binary_sensor`** + chime
  controls (`reolink.play_chime`); **native integration has NO two-way audio/TTS**. Privacy rules §6.

### 4.3 Vacuum — iRobot Roomba Combo (see §7)

- **✅ Confirmed (`roomba`; §13.b):** the core **`roomba` integration is LOCAL push** (on-device
  MQTT; BLID + password, sometimes obtained via a one-time cloud step). Provides a **`vacuum`** entity
  (start/stop/dock/state) + sensors (battery, bin, mission stats). **No room/zone selection or maps**
  in the core integration. **Caveat:** it does **not** support the newest **x05** Wi-Fi line
  (105/405/505); this exact SKU (c755020) is **unconfirmed** — verify at integration time.

### 4.4 Switch/plug — TP-Link Kasa HS220 dimmer (see §8)

- **✅ Confirmed (`tplink`; §13.b):** HS220 is supported; control is **LOCAL** on older firmware, but
  **newer firmware requires a TP-Link (Kasa) account at setup** (KLAP auth; polling still local).
  It's a **`light`** (dimmer/brightness). **No energy monitoring** (confirmed — dimmers don't report
  power). A community-reported brightness-exposure quirk exists on some firmware (verify).

### 4.5 Router / network — TELUS Wi-Fi Hub + fiber ONT (enabler; §9/§10)

- Internet path: **fiber ONT → TELUS Wi-Fi Hub → LAN** (ONT model UNKNOWN — §13.a).
- **✅ Confirmed (§13.b, MED — secondary sources):** the TELUS Wi-Fi Hub offers **primary + a single
  Guest SSID only** (guest is isolated from the main LAN but historically **cannot be
  password-protected**), and **no native VLAN** segmentation. For real IoT/camera VLAN isolation, use
  **LAN1 Bridge Mode** with a **downstream VLAN-capable router/AP**. (HA has no router integration.)
- Resilience: every Wi-Fi/cloud device + all push alerting depends on this chain → §9.

### 4.6 Hubs / bridges behind the owned devices

No local radio hub. Bridges/clouds: Reolink (local + app), iRobot (cloud-assisted, runtime local),
Meross (cloud **+ HomeKit local**), Kasa (local + optional cloud), ecobee (cloud + built-in Alexa).
Remaining ecosystem accounts (Google/Alexa/SmartThings) → §13.a.

### 4.7 Radio coordinator strategy — THE keystone (adopt Z-Wave)

The owned ZEN55 (Z-Wave 800 LR) decides the radio in favour of **Z-Wave** (Zigbee/Matter don't help
it; "no coordinator" leaves it useless and blocks SA-01 telemetry).
- **✅ Confirmed (HA docs; §13.b):** HA officially recommends the **Home Assistant Connect ZWA-2**
  (800-series, runs Z-Wave classic **and** Long Range simultaneously, local, no subscription);
  **HomeSeer SmartStick G8** and the **Zooz ZST39 LR** are listed as reported-working 800-series
  alternatives (controller firmware ≥ 7.23.2 recommended). *(Reported as the HA-docs list — not a
  purchase pick.)* Record the choice as a decision (§12 R5).

### 4.8 Garage door opener — Meross MSG100 (NEW category)

- `cover`; **access/safety-sensitive** (physical entry). Treat like cameras: **no voice-assistant
  exposure**, no broad automation without a dedicated, explicitly-approved, state-checked/
  confirmation-gated design (ONBOARDING §12 minimal-surface + SA gating philosophy).
- **✅ Confirmed (§13.b):** best **local** path is **HomeKit Controller** (this is the HomeKit
  edition) → a fully-local `cover`; the device **must be removed from Apple Home first** (pairing is
  exclusive). Community **`meross_lan`** offers local **HTTP polling** (needs the Meross *device key*,
  ~30 s state lag); its fully-local **MQTT** mode is **likely blocked on HomeKit-edition hardware**.
  Meross cloud is the fallback. Prefer HomeKit-local for an access-control device.

### 4.9 Thermostat — ecobee SmartThermostat with Voice Control (NEW category)

- **Today in HA:** only `media_player.upperthermostat` (speaker), **no `climate`** (HA-01 §8).
- **✅ Confirmed (`ecobee`; §13.b):** the official **`ecobee` integration (CLOUD polling)** adds a
  real **`climate`** entity (setpoints, mode, temp/humidity) + SmartSensor temperature/occupancy
  sensors + a `set_mic_mode` action. **HA 2026.3+ authenticates with the ecobee email/password (no
  developer API key needed);** older HA used an API key + PIN. **No real local option** (a Matter
  climate exposure is limited). The built-in **Alexa is a separate cloud voice feature, not an HA
  integration.** Cloud-dependent. (Adding this `climate` entity resolves HA-01 §8's "climate absent
  as control".)

### 4.10 Voice satellite — reSpeaker XVF3800 + XIAO ESP32-S3 (INCOMING; NEW category)

- A **4-mic reSpeaker XMOS XVF3800 with XIAO ESP32-S3 (Case Version)** is on order — ESP32-S3-class,
  local, with on-chip beamforming/AEC/noise suppression.
- **✅ Confirmed (§13.b):** integrates as an HA **voice satellite via ESPHome** (a Seeed-linked
  community config ports the HA Voice PE firmware), with **on-device micro-wake-word** and the
  **local Assist pipeline** (Whisper STT / Piper TTS — no cloud required). **Key constraint: the Case
  version has NO built-in loudspeaker** — it has a codec + 3.5 mm + JST speaker connector, so a
  **separate speaker is required for spoken TTS**. Requires **flashing ESPHome** (I2S mode). Exposes
  an `assist_satellite`-class entity (very likely; MED on the exact entity name).
- **Pipeline caveat (ONBOARDING §6/§12):** pipeline **Piper TTS is disabled** (crashes) and NAT/phone
  TTS URLs are unreachable — a satellite's *spoken* responses must be re-validated by the S-track;
  text/chime may be interim.
- **Backlog:** this is the hardware **`S0`** was blocked on (§12 R7); per-room routing = Track **S**.

---

## 5. Safety architecture (smoke/CO life-safety + water/leak property)

**Posture (SA-01/02):** smoke/CO = life-safety (strictest) — **physical interconnected sounder is
PRIMARY, HA is SECONDARY telemetry, never the sole alarm.** Water/leak = property (strict).

### 5.1 Smoke/CO — the owned SC7010BA + ZEN55 (life-safety)

- **Primary alarm = the SC7010BA's interconnected sounder** (independent of HA; not to be replaced).
- **HA telemetry = the ZEN55** → **two `binary_sensor`s (smoke + CO, distinct)** via Z-Wave JS once a
  coordinator exists. So SA-03 can fire the **distinct smoke vs CO messages** SA-01 §3.2 requires —
  the earlier "can HA tell smoke from CO?" question is **resolved: yes**.
- **Location limitation (SA-03 design input):** the ZEN55 reads the *shared* interconnect line, so HA
  learns the hazard **type** but **not which room** — a smoke/CO alert is **house-wide**, not
  room-labelled (unlike per-sensor leak location, SA-02 §4.5). Per-room would need per-detector
  sensing — **not** a reason to replace certified alarms (SA-01).
- **Power/supervision:** the ZEN55 is **mains-powered (no battery)** → offline/heartbeat-loss is the
  supervision signal (SA-01 §3.2 "offline = FAULT, never all-clear"); the SC7010BA's own 9 V backup
  covers detector power. HA supervision watches ZEN55 availability, not a ZEN55 battery.
- **Local siren option:** the ZEN55's **relay output** can drive a 120 V siren/light on alarm
  independently — a candidate for the SA-01 §6D "credible HA-adjacent alarm" without a separate
  Z-Wave siren.
- **Blocker = the coordinator, not the sensors.** The detector + bridge are already owned; only the
  Z-Wave coordinator (absent) stands between now and SA-01-grade telemetry → **required-for-safety**
  purchase (§11).
- **Independence (confirms SA-01):** if HA or Z-Wave fails, the detectors still sound; HA only gains
  awareness. Fire/CO **response automations** (lights/locks/notify/camera/CO→furnace-shutoff) are
  **SA-03** under the SA gate — out of scope here; CO→furnace additionally needs the ecobee `climate`
  entity (R6 HA-09).

### 5.2 Water/leak (property)

- Ownership **UNKNOWN** — confirm before calling it a gap (§13.a).
- **Synergy:** §4.7 → **Z-Wave** coordinator; future leak sensors should be **Z-Wave** so one
  coordinator serves smoke telemetry *and* leak sensors (strengthens the coordinator case).
- If bought: `binary_sensor device_class: moisture`, battery + offline supervision (SA-02 §4.2),
  placement by risk area (SA-02 §4.1). If not: a **required-for-safety (property)** gap (§11).

### 5.3 Sirens / sounders

The SC7010BA sounder is primary (SA-01). Two HA-adjacent options without buying a siren: the ZEN55
**relay output** (§5.1) and the ceiling-TTS. A dedicated **Z-Wave siren** (on the same coordinator)
remains optional (SA-01 §6D). Standalone-siren ownership is UNKNOWN (§13.a).

---

## 6. Camera architecture

Two **Reolink** cameras (RLC-820A garage + 2K wired doorbell). `go2rtc` + `camera` are loaded
(HA-01 §6) and built-in since HA 2024.11 → local path plumbed.

- **✅ Confirmed path (§13.b):** native **`reolink`** integration — **fully local, no cloud
  subscription** — with RTSP/ONVIF also available; go2rtc restreams. RLC-820A → stream + motion/AI
  person/vehicle binary_sensors + config controls. Doorbell → stream + **`Visitor` press
  binary_sensor** + chime controls (`reolink.play_chime`); **no native two-way audio**.
- **Recording:** RLC-820A storage "Not Formatted", no NVR reported → decide later (camera SD / NVR /
  HA). Out of scope here.
- **Privacy constraints (hard):** **no raw camera exposure to the voice assistant** (HA-04 strict
  gate + ONBOARDING §12); keep footage local; if any camera must stay cloud-reliant, isolate on an
  IoT VLAN (needs a downstream router — §4.5). Person-detection/security alerts = **SA-05** (dep
  HA-04 + SA-01/02), noted only.
- **No implementation** — paths + constraints only.

---

## 7. Vacuum architecture

**iRobot Roomba Combo**, Wi-Fi.
- **✅ Confirmed (§13.b):** core **`roomba`** integration = **LOCAL push** (BLID+password; one-time
  cloud step possible on some models). `vacuum` (start/stop/dock/state) + sensors. **No room/zone/map
  in the core integration.** **x05** models unsupported; c755020 SKU unconfirmed — verify.
- **Reliability:** local runtime is good, but the on-robot MQTT allows **one connection** — the iRobot
  app and HA can conflict. Convenience-grade; low consequence.
- **No implementation** — HA-03 later.

---

## 8. Plug/switch architecture

**TP-Link Kasa HS220** in-wall **dimmer**.
- **✅ Confirmed (§13.b):** **`tplink`** integration; **local** on older firmware, **newer firmware
  requires a TP-Link account at setup** (KLAP; polling still local). Domain **`light`** (brightness;
  a firmware-dependent brightness quirk is community-reported — verify). **No energy monitoring**
  (confirmed) → energy (DV-04) needs different hardware (a metering plug).
- **Safety caveat (120 V / 15 A NA):** a dimmer drives **lighting loads only** — never a motor/
  high-load appliance. Any *plug* used with a heavy load must be **within its rated amperage**; this
  roadmap endorses no device for high-load use.

---

## 9. UPS / resilience architecture

**Ownership UNKNOWN** (§3) — *infrastructure-resilience*, **distinct from life-safety** (the SC7010BA
carries its own power + battery backup; the ZEN55 relay/telemetry is a bonus, not the alarm).

- **Protect (priority):** (1) **HA host** (Ubuntu host running the libvirt `haos` VM — ONBOARDING §1);
  (2) **Fiber ONT + TELUS Wi-Fi Hub** — *without both powered, internet + all push/cloud alerting is
  dead even if HA is up*, and the whole Wi-Fi/cloud fleet drops offline; (3) **(future) Z-Wave
  coordinator** (§4.7) so the ZEN55 smoke bridge + future leak sensors keep reporting.
- **Topology:** USB UPS → **host** runs the **NUT server**; the HAOS VM runs the **NUT client** over
  the host↔VM network (or a network-card UPS over LAN). HA's native **NUT** integration is the local,
  cloud-free path (charge %, load, runtime, on-battery).
- **Runtime goal:** short-outage bridge + **graceful HAOS-VM/host shutdown** before battery death
  (avoids VM/disk corruption; cf. INF-05).
- **Honest limit:** a UPS does **not** survive an **ISP (TELUS uplink) outage** — push still needs the
  internet; ceiling-TTS needs host + speaker power. (Consistent with SA §2 channel-honesty.)
- **NUT appropriateness:** yes if a UPS is acquired — feeds DV-02 / HA-06 device-health.

---

## 10. Area / room mapping implications

HA-01 §4: area map effectively empty (only printer→Furnace). The §3 devices seed real locations:
**Garage** (RLC-820A + likely the Meross door), a **Main Floor** (Roomba "MainFloor…"), and an
**Upper** level (ecobee "UpperThermostat") → **≥2 levels** (matters for per-level smoke coverage +
floors).

- **Strategy (design-only):** define **floors** (Main/Upper) + real rooms; populate the empty areas;
  **assign every integrated device to an area at integration time** (the gap SA-01 §8 flags for alert
  labels); use room-based names.

| Category | Needs area for | Downstream |
|---|---|---|
| Media players | media-zone map (ducking / room audio) | **AU-01**, Track **S** |
| Leak sensors (per-sensor) | **per-sensor location label** | **SA-04** (SA-02 §4.5) |
| Voice satellite (reSpeaker) | **per-room routing** | **S0 → S1–S4** |
| Cameras (garage + doorbell) | location context; per-area privacy | **HA-04 / SA-05** |
| Garage door (Meross) | location + access context | new HA item (§12) |
| Thermostat (ecobee) | per-zone climate ("Upper") | new HA item (§12) |
| Switch (Kasa) | room-scoped control + grouping | **HA-02**, **DV-04** |
| All device-health | per-room "what needs attention" | **DV-01/02**, **HA-06** |

- **Smoke location caveat:** the ZEN55 gives a **house-wide** signal — HA knows smoke-vs-CO (§5.1) but
  **not which room**; a smoke alert can't carry a room label unless per-detector sensing is added (do
  not replace certified alarms for this, SA-01). Leak sensors are per-sensor and *can* carry a room.
- **Media zones** still can't be derived from HA areas (HA-01 §4); AU-01 populates areas or carries
  its own map; multi-room routing waits on **S0** (now incoming, §4.10).

---

## 11. Purchase-gap analysis

> **Derived LAST.** Most owned categories are **not** gaps — they need integration work, not
> purchases. **No product picks, carts, or checkout.**

| Gap candidate | Category | Certainty | Rationale |
|---|---|---|---|
| **Z-Wave coordinator** (800-series LR; HA docs list ZWA-2 / HomeSeer G8 / Zooz ZST39 LR) | **required-for-integration-architecture + required-for-safety** | **CONFIRMED / HIGHEST** | HA-01 §6: none. Owned **ZEN55 is non-functional without it**; enables SA-01 smoke telemetry + future SA-02 leak. Unlocks a sunk purchase. §4.7. |
| **External speaker for the reSpeaker satellite** | **required-for-integration** (voice) | **CONFIRMED (small)** | The Case version has no built-in loudspeaker → a speaker is required for spoken TTS (§4.10). |
| **Water/leak sensors** (prefer Z-Wave) | **required-for-safety** (property) | MEDIUM (ownership UNKNOWN) | If not owned (§5.2); share the coordinator. Confirm ownership first. |
| **UPS + USB/NIC for NUT** | **infrastructure-resilience** | MEDIUM (ownership UNKNOWN) | §9. Protects host + ONT + hub (+ coordinator). |
| **Downstream VLAN router/AP (via LAN1 bridge)** | **infrastructure-resilience** (privacy) | CONDITIONAL → now supported rationale | The TELUS hub has **no native VLAN** (§4.5); real IoT/camera isolation needs a downstream router in LAN1 bridge mode. Only if segmentation is wanted. |
| **Dedicated Z-Wave siren** | **optional-convenience** (safety-adjacent) | LOW | Optional (SA-01 §6D); the ZEN55 relay (§5.3) may already suffice. |
| **Smoke/CO detector, cameras, vacuum, switch, garage opener, thermostat, voice satellite** | **NOT gaps** | — | **All owned/incoming.** Integration-path work only. **Do not replace the SC7010BA** (SA-01). |

**Sequencing (if buying):** **Z-Wave coordinator first** (unlocks the ZEN55 + gates leak/smoke
telemetry), then leak sensors, UPS in parallel, satellite speaker with the incoming reSpeaker, VLAN
router + siren conditional/optional. Mirrors SA-01 §6 `A → (B,C) → optional D`.

---

## 12. Backlog impact recommendations (PROPOSE only — do NOT edit BACKLOG.md)

> `BACKLOG.md` is **INF-owned (BACKLOG §9)**. Recommendations only; INF applies via its own PR after
> separate approval.

**R1 — create `HA-07 — Existing device integration architecture`** (this doc). HA track,
`research/architecture`, deps **HA-01 + SA-01/02**, gate none.

**R2 — reframe `RQ-05`** → **"device integration roadmap / purchase-gap analysis"**, consuming
**HA-07 + SA-01/02**; the buy-list is the *derived* §11 output (headed by the Z-Wave coordinator).
*(If INF prefers one item, HA-07 can absorb §11 and RQ-05 closes as reframed — INF decides.)*

**R3 — dependency updates:**
- **HA-02 (plugs/switches):** dep HA-07 — device is a **Kasa HS220 dimmer** (`light`, local `tplink`,
  no energy).
- **HA-03 (vacuum):** dep HA-07 — **Roomba Combo** (`roomba` local push, no maps; x05 caveat).
- **HA-04 (cameras):** dep HA-07 — **two Reolink** (native local `reolink`, doorbell Visitor/chime;
  strict no-voice-exposure).
- **SA-03 (smoke/CO impl):** **Z-Wave-coordinator-gated** (owned SC7010BA + ZEN55; two smoke/CO
  sensors + relay; house-wide location; §5.1) — not just SA-01.
- **SA-04 (water/leak impl):** dep §5.2 ownership + the Z-Wave coordinator.
- **DV-04 (energy):** dep HA-07 §8 — HS220 reports **no** energy → needs metering hardware.
- **AU-01 (audio policy):** use the §10 Main/Upper floor/area strategy as room input.

**R4 — add `INF-08 — UPS + NUT resilience` (host + fiber ONT + TELUS hub + coordinator).** §9.
Infrastructure, not life-safety.

**R5 — record the coordinator decision: adopt Z-Wave.** HA docs list ZWA-2 (recommended) /
HomeSeer G8 / Zooz ZST39 LR (§4.7). Decision record (like RQ-03); gates SA-03/04 + leak.

**R6 — two new device items to consider:**
- **`HA-08 — Garage door (Meross MSG100)`** — `cover`, access/safety-sensitive, **local via HomeKit
  Controller** (§4.8); strict exposure.
- **`HA-09 — Thermostat climate entity (ecobee)`** — real `climate` via the cloud `ecobee`
  integration (HA 2026.3+ email/password); resolves HA-01 §8 (§4.9). Cloud-dependent.

**R7 — `S0` hardware is INCOMING (reSpeaker XVF3800 + XIAO ESP32-S3).** Local ESP32/ESPHome/Wyoming
satellite (§4.10; needs an external speaker). `S0` (currently `blocked` on hardware) becomes
actionable on arrival — recommend INF move it toward `ready`/active once installed. Feeds Track **S**
(§10) + uses the existing Whisper STT (mind the Piper-in-pipeline TTS caveat, ONBOARDING §6).

---

## 13. Unknowns / questions for the user + resolved web lookups

### 13.a User follow-up (remaining ownership/config questions)

| # | Question |
|---|---|
| 1 | **UPS** — own one? (model, USB/network, what's plugged in) |
| 2 | **Leak/water sensors** — own any? (brand/model) |
| 3 | **Standalone siren** — any, separate from the smoke alarm? |
| 4 | **Voice satellites** — how many reSpeakers, which rooms? A speaker for TTS? Any existing Echo/Google/HomePod? |
| 5 | **Smoke system extent** — how many detectors, how many levels, interconnected confirmed? Is the ZEN55 already wired to a detector or still boxed? |
| 6 | **More of the same?** — additional Kasa devices, additional Reolink cameras, more than one thermostat? |
| 7 | **Network** — the **fiber ONT** make/model? Any router/AP downstream of the TELUS hub, or is it the only router? Any existing IoT SSID/VLAN? |
| 8 | **Ecosystem accounts** — beyond Reolink/iRobot/Meross/Kasa/ecobee/Apple HomeKit: Google Home, Alexa, or SmartThings? |

### 13.b Model-specific web lookups — RESOLVED (Phase 4, read-only, HA-docs-first; accessed 2026-06-30)

| Device | Finding (condensed) | Local/cloud | Confidence | Source (HA docs first) |
|---|---|---|---|---|
| **Zooz ZEN55 LR** | Supported by **Z-Wave JS**; **two** `binary_sensor`s (`smoke` + `carbon_monoxide`, distinguished from signal pattern); **mains-only, no battery**; **relay** endpoint (switch) for a local siren/light; sensors may be disabled-by-default; LR needs 800-series LR stick + fw ≥1.20 | **Local** (Z-Wave) | HIGH (entity names MED — community) | Z-Wave JS device DB `zen55.json`; getzooz.com FAQ/settings; HA `zwave_js` |
| **Z-Wave coordinator** | HA recommends **Home Assistant Connect ZWA-2** (800, classic+LR); **HomeSeer SmartStick G8**, **Zooz ZST39 LR** reported-working; ctrl fw ≥7.23.2 | **Local** | HIGH | home-assistant.io/docs/z-wave/controllers/ ; /connect/zwa-2/ |
| **Reolink RLC-820A** | Native **`reolink`** (local, no subscription); RTSP/ONVIF; 40+ entities incl. motion/AI person/vehicle | **Local** | HIGH | home-assistant.io/integrations/reolink/ ; Reolink specs |
| **Reolink Video Doorbell** | Native `reolink`; **`Visitor` press binary_sensor** + chime controls (`reolink.play_chime`); local, no subscription; **no native two-way audio**; exact "2K wired" SKU label MED | **Local** | HIGH (SKU MED) | home-assistant.io/integrations/reolink/ ; /actions/reolink.play_chime/ |
| **go2rtc** | Built into HA since **2024.11**; restreams Reolink RTSP as WebRTC | Local | HIGH | home-assistant.io/integrations/go2rtc/ |
| **iRobot Roomba Combo (c755020)** | `roomba` = **local push** (BLID+password; one-time cloud step possible); `vacuum` + sensors; **no room/map** in core; **x05 unsupported**; this SKU unconfirmed | **Local** (runtime) | MED (SKU LOW) | home-assistant.io/integrations/roomba/ |
| **TP-Link Kasa HS220** | `tplink`; **local** (older fw), **newer fw needs TP-Link account** at setup; `light`; **no energy monitoring** | **Local** (may need account) | HIGH (brightness quirk MED) | home-assistant.io/integrations/tplink/ |
| **Meross MSG100** | Best **local** = **HomeKit Controller** `cover` (remove from Apple Home first); `meross_lan` HTTP local-poll (device key, ~30 s lag); local-MQTT likely blocked on HomeKit edition; cloud fallback | **Local** (HomeKit) | HIGH (MQTT-blocked MED) | home-assistant.io/integrations/homekit_controller/ ; meross_lan (community) |
| **ecobee SmartThermostat w/ Voice Control** | `ecobee` **cloud polling**; **HA 2026.3+ email/password (no API key)**; `climate` + SmartSensors + occupancy + `set_mic_mode`; Alexa = separate cloud; no real local | **Cloud** | HIGH | home-assistant.io/integrations/ecobee/ |
| **reSpeaker XVF3800 + XIAO ESP32-S3 (Case)** | HA voice satellite via **ESPHome** (Seeed community config ports HA Voice PE fw); on-device wake word; local pipeline (Whisper/Piper); **no built-in speaker → external speaker needed for TTS**; needs flashing | **Local** | HIGH (`assist_satellite` name MED) | wiki.seeedstudio.com (reSpeaker XVF3800 + HA) ; HA `assist_satellite` |
| **TELUS Wi-Fi Hub** | Primary + **Guest SSID only** (guest historically un-passwordable), **no native VLAN**; **LAN1 Bridge Mode** → downstream router for real VLAN | Local (network) | MED (secondary sources) | telus.com support + forum (secondary) |

### 13.c Open architecture decisions (user)

- **Adopt Z-Wave coordinator?** (strongly indicated; gates SA-03/04 + leak). HA-recommended class = ZWA-2.
- **Cloud tolerance** per device: Reolink (local ✅), Meross (HomeKit-local ✅), Kasa (local ✅) vs
  **Roomba** (local runtime ✅) and **ecobee** (cloud-bound). Accept ecobee cloud for a `climate`
  entity?
- **Network segmentation?** IoT VLAN needs a **downstream router via LAN1 bridge** (TELUS hub can't).
- **UPS scope** — short bridge + graceful shutdown; put the **fiber ONT + hub** on it too, or HA has no uplink.

---

## 14. Next actions

1. **User follow-up (§13.a)** — UPS, leak sensors, siren, satellite count/speaker, smoke-system
   extent + ZEN55 install state, extra devices, fiber-ONT model + downstream router, ecosystem
   accounts.
2. **Decisions (§13.c)** — confirm **adopt Z-Wave** (ZWA-2 class); cloud tolerance for ecobee;
   segmentation intent; UPS scope.
3. **Backlog (§12)** — INF decides R1–R7; INF applies changes to `BACKLOG.md` separately (not here).
4. **PR** — one doc on branch `homebrain/ha-device-integration-roadmap`; gate FREE; commit only when
   approved.

*(Phase-4 web research is complete — §13.b resolved. No further browsing needed unless new models
surface from §13.a.)*

---

> Rollback for this document: `git revert` on `homebrain/ha-device-integration-roadmap`, or delete
> this file. No secrets, no implementation, no exposure, no purchase; live gate left FREE.
