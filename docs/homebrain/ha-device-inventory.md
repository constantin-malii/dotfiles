# HA-01 — Home Assistant Device & Entity Inventory (read-only)

> Point-in-time snapshot. Source of running-state truth = `ONBOARDING.md` / `CHANGELOG.md`.
> Captured: 2026-06-30 · HA Core 2026.6.4 · HAOS 18.0 (Supervisor 2026.06.2) · method: read-only REST + WS.
> Branch: `homebrain/ha-device-inventory` · Track: HA-01.

---

## 0. Scope & method

**What this IS:** a single, point-in-time, read-only inventory of the live Home Assistant instance
at `http://192.168.1.104:8123` — entities by domain, the set exposed to the `conversation`
assistant, areas/rooms, devices and device→area mapping, integrations/config entries, battery &
availability health, and a candidate device-gap list.

**What this is NOT:** not a running-state narrative (that lives in `ONBOARDING.md` / `CHANGELOG.md`,
referenced here, never duplicated); not an implementation; not a mutation.

**Read-only confirmation:** Phase 2 issued only HTTP `GET` (REST) and WebSocket `*/list` / `*/get`
(read) commands. The exposure **setter** `homeassistant/expose_entity` was **never** called; exposure
was read via the confirmed read command `homeassistant/expose_entity/list`. No exposure change, no
service restart, no host/SSH, no script/automation edit occurred.

**Method (as executed):**
- REST: `GET /api/config`, `GET /api/states` (75 entities).
- WS (single authenticated read session): `config/area_registry/list`, `config/device_registry/list`,
  `config/entity_registry/list` (463 entries), `config_entries/get` (17), `homeassistant/expose_entity/list`.
- Driver: Python 3 stdlib only (raw-socket WebSocket client + `urllib`), ASCII-only console, multi-frame
  WS reassembly — per `ONBOARDING.md` §3. Token supplied at runtime, held in memory only, never written
  or logged (requests shown as `Authorization: Bearer ***`). Full plan in Appendix A.

**Gate:** HA-01 is read-only and does **NOT** claim the live-system gate (`BACKLOG.md` §10). Left **FREE**.

---

## 1. Instance summary

From `GET /api/config` (+ device-registry `sw_version` for OS/Supervisor). Confirms `ONBOARDING.md` §1.

| Field | Value |
|---|---|
| HA Core version | **2026.6.4** (`/api/config` `version`; WS `auth_ok` `ha_version` agrees) |
| HAOS / OS version | **18.0** (device "Home Assistant Operating System" `sw_version`) |
| Supervisor version | **2026.06.2** (device "Home Assistant Supervisor" `sw_version`) |
| Location name | **Home** |
| Country / language | **CA** / **en** |
| Time zone | **America/Edmonton** |
| Unit system | metric (length km, temp °C, mass g, pressure Pa, volume L, wind m/s) |
| State | **RUNNING** · `config_source=storage` · `safe_mode=false` · `recovery_mode=false` |
| Components loaded | **165** |
| Entities (live / `/api/states`) | **75** |
| Entities (registry / all incl. disabled) | **463** (388 disabled — see §2) |

---

## 2. Entities by domain

Two counts matter: **live** = present in `/api/states` (75, actively loaded); **registry** = all
registered entities incl. disabled (463). The gap is almost entirely **disabled mobile-app + add-on
housekeeping entities** (314 disabled `sensor`, 71 disabled `binary_sensor`, 6 disabled `switch`).

**Summary (live domains):**

| Domain | Live count | Exposed to `conversation` | Notes |
|---|---|---|---|
| `sensor` | 20 | 0 | + 314 disabled in registry (334 total); enabled = backup/sun/3×phone-battery/print |
| `script` | 16 | 12 | 11 `ceiling_*` + 5 resolver scripts; exposure detail in §3 |
| `update` | 9 | 0 | Core/OS/Supervisor + add-on update entities |
| `media_player` | 4 | 0 | all MA-provided; see per-domain below |
| `button` | 4 | 0 | MA "favorite current song" buttons (3 unknown, 1 unavailable) |
| `automation` | 4 | 0 | voice handler + A1/A2a self-heal + Lidarr→MA sync |
| `device_tracker` | 3 | 0 | 3 phones (all `home`) |
| `notify` | 3 | 0 | per-phone notify targets (stateless → `unknown`) |
| `conversation` | 2 | 0 | `home_assistant` (default) + `openai_conversation` (ChatGPT) |
| `tts` | 2 | 0 | `piper`, `google_translate_en_com` |
| `person` | 2 | 0 | costea, Vio (both `home`) |
| `weather` | 1 | 1 | `weather.forecast_home` (Met.no) — the only non-script exposed entity |
| `stt` | 1 | 0 | `faster_whisper` (stateless → `unknown`) |
| `todo` | 1 | 0 | `todo.shopping_list` |
| `zone` | 1 | 0 | `zone.home` |
| `sun` | 1 | 0 | `sun.sun` |
| `event` | 1 | 0 | `event.backup_automatic_backup` |
| **Total** | **75** | **13** | |

**Registry-only (all disabled, 0 live) domains** — relevant to §8:
`binary_sensor` 71 (all disabled), `switch` 6 (all disabled). No `light`, `camera`, `vacuum`, `cover`,
`climate`, `lock`, `alarm_control_panel`, `fan`, `assist_satellite`, `siren`, `valve` entities exist at
all (registry or live).

**Per-domain lists (live, notable domains):**

- **`media_player` (4)** — all via Music Assistant, all `device_class=speaker`:
  - `media_player.ceiling_speakers` — `idle` — MA Universal player (squeezelite; the ceiling zone).
  - `media_player.samsung_soundbar_q930c` — **`unavailable`** — Samsung HW-Q930C soundbar (INF-03).
  - `media_player.upperthermostat` — `idle` — ecobee EB-STATE5 surfaced by MA as a speaker target
    (there is **no `climate` entity** for it — see §8 note).
  - `media_player.samsung_q82ca_75` — `idle` — Samsung TV (model QCQ80D).
- **`script` (16)** — 11 `ceiling_*` (`play_radio`, `pause`, `resume`, `stop`, `set_volume`,
  `volume_up`, `volume_down`, `announce`, `play_music`, `next`, `previous`) + 5 resolver scripts
  (`play_music`, `play_radio`, `find_stations`, `media_status`, `news`). Exposure in §3.
- **`automation` (4)** — `voice_ceiling_speakers`, `ma_auto_reload_integration_after_restart` (A1),
  `ma_health_probe_auto_reload` (A2a), `lidarr_import_ma_sync` — all `on`.
- **`sensor` (20 live)** — backup manager/scheduling (4), sun times (6), 3×phone battery + 3×battery-state
  + 3×charger-type, printer state (1).
- **`conversation` / `tts` / `stt`** — agents `conversation.home_assistant` + `conversation.openai_conversation`;
  TTS `piper` + `google_translate_en_com`; STT `faster_whisper`.
- **Full whitelisted per-domain dump:** scratchpad `states_domains.json` (not committed).

---

## 3. Exposure to `conversation`

**Read path (confirmed, read-only):** WS `homeassistant/expose_entity/list` →
`conversation.should_expose == true`. (Entity registry also carries the `options` blob, confirming the
same; the setter was never called.)

**Exposed set = 13** (matches the documented baseline in `CHANGELOG.md` after Inc 2A — **delta = 0**):

| # | Entity | Kind |
|---|---|---|
| 1 | `weather.forecast_home` | weather (read) |
| 2 | `script.play_music` | resolver: local library |
| 3 | `script.play_radio` | resolver: radio |
| 4 | `script.find_stations` | resolver: station list |
| 5 | `script.media_status` | resolver: now-playing |
| 6 | `script.news` | resolver: news headlines |
| 7 | `script.ceiling_pause` | ceiling transport |
| 8 | `script.ceiling_resume` | ceiling transport |
| 9 | `script.ceiling_stop` | ceiling transport |
| 10 | `script.ceiling_next` | ceiling transport |
| 11 | `script.ceiling_previous` | ceiling transport |
| 12 | `script.ceiling_volume_up` | ceiling volume |
| 13 | `script.ceiling_volume_down` | ceiling volume |

**Present but NOT exposed** (confirming minimal-surface policy, `ONBOARDING.md` §12): `script.ceiling_play_radio`,
`script.ceiling_set_volume`, `script.ceiling_announce`, `script.ceiling_play_music`, and **all**
`media_player.*` (incl. `media_player.ceiling_speakers`). No raw media_player is exposed.

---

## 4. Areas / rooms

**Areas (4):**

| area_id | Name | #devices | #entities |
|---|---|---|---|
| `living_room` | Living Room | 0 | 0 |
| `kitchen` | Kitchen | 0 | 0 |
| `bedroom` | Bedroom | 0 | 0 |
| `furnace` | Furnace | 1 | 2 |

**Membership:** only the HP LaserJet printer (device `ed4fc2…`, 2 entities) is assigned — to **Furnace**.
Living Room / Kitchen / Bedroom exist but are **empty**.

**Unassigned (no area):** the other **22 devices** and effectively all live non-printer entities —
including all 4 media players, all 3 phones, and every add-on device. No floors defined.

> **Downstream flag (AU-01 / DV):** there is essentially **no HA-level room→device map**. The
> media-zone map cannot be derived from HA areas today; media players are area-unassigned.

---

## 5. Devices and device → area mapping

**23 devices.** (`config_entries` linked to integration; entity counts from the entity registry —
these include disabled entities, e.g. the mobile apps.)

| Device | Manufacturer / model | Integration | Area | Entity count |
|---|---|---|---|---|
| SM-S948W-Costea | samsung / SM-S948W | `mobile_app` | — | 134 |
| SM-S948W-Vio | samsung / SM-S948W | `mobile_app` | — | 128 |
| Huawei-Costea-CLT-L04 | HUAWEI / CLT-L04 | `mobile_app` | — | 93 |
| Ceiling Speakers | squeezeplay / SqueezeLite | `music_assistant` | — | 2 |
| Samsung Soundbar Q930C | Samsung / HW-Q930C | `music_assistant` | — | 2 |
| UpperThermostat | ecobee Inc. / EB-STATE5 | `music_assistant` | — | 2 |
| Samsung Q82CA 75 | Samsung / QCQ80D | `music_assistant` | — | 2 |
| Music Assistant | Music Assistant / HA App | `hassio` (add-on) | — | 7 |
| YT Music PO Token Generator | Music Assistant / HA App | `hassio` (add-on) | — | 7 |
| Whisper | Official apps / HA App | `hassio` (add-on) | — | 7 |
| Piper | Official apps / HA App | `hassio` (add-on) | — | 7 |
| Studio Code Server | HA Community Apps / HA App | `hassio` (add-on) | — | 7 |
| File editor | Official apps / HA App | `hassio` (add-on) | — | 7 |
| HP LaserJet 1320 …v5.2.11 | Hewlett-Packard / hp LaserJet 1320 series | `ipp` | **Furnace** | 2 |
| HA Core | Home Assistant / HA Core | `hassio` | — | 3 |
| HA Supervisor | Home Assistant / HA Supervisor | `hassio` | — | 3 |
| HA Host | Home Assistant / HA Host | `hassio` | — | 5 |
| HA Operating System | Home Assistant / HAOS | `hassio` | — | 3 |
| Backup | Home Assistant / HA Backup | `backup` | — | 5 |
| Sun | — | `sun` | — | 9 |
| Forecast | Met.no / Forecast | `met` | — | 1 |
| Google Translate en com | Google / Google Translate TTS | `google_translate` | — | 1 |
| OpenAI Conversation | OpenAI / gpt-4o-mini | `openai_conversation` | — | 1 |

> Note (confirms `ONBOARDING.md` §4): the ceiling zone is `media_player.ceiling_speakers` (device
> "Ceiling Speakers", model SqueezeLite). The Squeezelite **protocol** player `f8:b1:56:c2:51:01` is
> **not** an HA entity/device — correctly absent here. The host-side `mass-resolver` service is not an
> HA entity either (it is reached via `rest_command`), so it does not appear in this inventory.

---

## 6. Integrations / config entries

**17 config entries** (WS `config_entries/get`); all `state=loaded`.

| Integration (domain) | Title | Source | #devices | #entities |
|---|---|---|---|---|
| `mobile_app` | SM-S948W-Costea | registration | 1 | 134 |
| `mobile_app` | SM-S948W-Vio | registration | 1 | 128 |
| `mobile_app` | Huawei-Costea-CLT-L04 | registration | 1 | 93 |
| `hassio` | Supervisor | system | 10 | 56 |
| `music_assistant` | Music Assistant | hassio | 4 | 8 |
| `sun` | Sun | import | 1 | 9 |
| `backup` | Backup | system | 1 | 5 |
| `ipp` | HP LaserJet 1320 series @ homebrain | zeroconf | 1 | 2 |
| `met` | Home | onboarding | 1 | 1 |
| `google_translate` | Google Translate TTS | onboarding | 1 | 1 |
| `openai_conversation` | ChatGPT | user | 1 | 1 |
| `wyoming` | faster-whisper | user | 0 | 1 |
| `wyoming` | piper | user | 0 | 1 |
| `shopping_list` | Shopping list | onboarding | 0 | 1 |
| `radio_browser` | Radio Browser | onboarding | 0 | 0 |
| `analytics` | Analytics | system | 0 | 0 |
| `go2rtc` | go2rtc | system | 0 | 0 |

> Matches `ONBOARDING.md` §4: Music Assistant + OpenAI Conversation (gpt-4o-mini) present. `radio_browser`
> backs `script.play_radio`/`find_stations`; `wyoming` provides STT (faster-whisper) + TTS (piper);
> `go2rtc` is loaded (camera streaming plumbing) but there are **no camera entities**.

---

## 7. Battery & availability health

**Battery-reporting entities (3)** — all phone batteries (`device_class=battery`, %):

| entity_id | Level | Source |
|---|---|---|
| `sensor.sm_s948w_costea_battery_level` | 96% | device_class |
| `sensor.sm_s948w_vio_battery_level` | 29% | device_class |
| `sensor.huawei_costea_clt_l04_battery_level` | 16% | device_class |

> No non-phone battery devices (no sensor/lock/remote batteries) — **absent**, confirmed via `/api/states`.

**Unavailable / unknown (9 live):**

| entity_id | State | Note |
|---|---|---|
| `media_player.samsung_soundbar_q930c` | **unavailable** | Samsung soundbar genuinely offline/unreachable (INF-03) |
| `button.samsung_soundbar_q930c_favorite_current_song` | unavailable | child of the offline soundbar |
| `notify.huawei_costea_clt_l04` | unknown | notify targets are stateless (expected) |
| `notify.sm_s948w_costea` | unknown | expected (stateless) |
| `notify.sm_s948w_vio` | unknown | expected (stateless) |
| `stt.faster_whisper` | unknown | STT entity stateless (expected) |
| `button.upperthermostat_favorite_current_song` | unknown | MA favorite button, no state until used |
| `button.ceiling_speakers_favorite_current_song` | unknown | MA favorite button, no state until used |
| `button.samsung_q82ca_75_favorite_current_song` | unknown | MA favorite button, no state until used |

> **Genuinely degraded:** only the **Samsung Soundbar Q930C** (and its child button). The `notify`/`stt`
> `unknown` and the MA "favorite" `unknown` buttons are normal stateless entities, not faults.

---

## 8. Candidate device-gap list

Classification: **Present** / **Absent** (confirmed 0 entities in registry+states) / **Unknown**
(not queryable). Everything below was fully queried — nothing is "unknown".

| Category | Backlog need | Status | Evidence |
|---|---|---|---|
| Smart plugs / switches | HA-02 | **ABSENT** | 0 `light`; the only 6 `switch` are **disabled add-on** on/off switches (music_assistant, whisper, piper, …) — no physical plugs/switches |
| Vacuum | HA-03 | **ABSENT** | 0 `vacuum` entities (registry + live) |
| Cameras | HA-04 | **ABSENT** | 0 `camera` entities (`camera`/`go2rtc` components loaded, but no camera devices) |
| Smoke / CO | SA-01 | **ABSENT** | 0 `binary_sensor` with device_class smoke/CO/gas; all 71 `binary_sensor` are disabled mobile-app/add-on sensors |
| Water / leak | SA-02 | **ABSENT** | 0 `binary_sensor` with device_class `moisture`; none in registry |
| Voice satellites | S0 | **ABSENT** | 0 `assist_satellite` entities (consistent with S0 blocked on hardware). Wyoming STT/TTS exist but no satellite endpoints |
| Climate / thermostat control | (future) | **ABSENT as control** | ecobee EB-STATE5 exists **only** as a MA `media_player` (`upperthermostat`); **no `climate` entity** → not controllable/readable as a thermostat |

**Present controllable/observable surface today:** 4 media players (ceiling zone + soundbar[offline] +
Samsung TV + ecobee-as-speaker, all MA), 3 phones (trackers/battery/notify), 1 networked printer,
weather, sun, shopping-list todo, backup, TTS/STT, 2 conversation agents.

**Gaps for purchasing (RQ-05):** smart plugs/switches, robot vacuum, cameras, **smoke/CO detectors
(life-safety, SA-01)**, **water/leak sensors (property, SA-02)**, and voice satellites (S0, pending
install). All are net-new categories — no existing devices to reuse.

---

## 9. Unknowns / TODO

All Phase-1 endpoint uncertainties resolved in Phase 2 (config entries, exposure read path, HAOS
version, entity `options` all confirmed). Remaining notes:

- `TODO:` **No HA-level room map.** Only 1 of 23 devices is area-assigned (printer→Furnace); Living
  Room/Kitchen/Bedroom are empty and media players are unassigned. AU-01/DV work needs the media-zone
  map built elsewhere (or areas populated) — not derivable from HA areas as-is.
- `TODO:` **HAOS/OS version source.** `/api/config` exposes Core only; HAOS 18.0 / Supervisor 2026.06.2
  were read from the **device registry `sw_version`** (Supervisor stats/host APIs remain 401 read-only
  per `ONBOARDING.md` §3 — not needed here).
- Note (not a defect): entity counts in §5/§6 are **registry** counts (include disabled entities); live
  loaded entities total 75 (§2). Both are reported deliberately.
- Note: this inventory omits the host-side `mass-resolver` and the Squeezelite protocol player by
  design — neither is an HA entity.

---

## 10. Downstream feeds

| Downstream track | Consumes | Headline from this inventory |
|---|---|---|
| HA-02 smart plugs / switches | §2, §5, §8 | **No plugs/switches exist** → purchase-first (RQ-05) |
| HA-03 vacuum control | §2, §5, §8 | **No vacuum** → purchase-first |
| HA-04 cameras | §2, §3, §8 | **No cameras** (go2rtc ready) → purchase-first |
| HA-05 routines / automations exposure | §2, §6 | 4 automations present; none exposed |
| HA-06 device health / battery read-model | §7 | 3 phone batteries; soundbar offline is the one real fault |
| SA-01 smoke/CO | §2, §8 | **Absent** → inventory = none; design + buy-list |
| SA-02 water/leak | §2, §8 | **Absent** → inventory = none; design + buy-list |
| AU-01 interaction audio policy | §4 | **No HA room map**; media players area-unassigned → single-zone (ceiling) design |
| DV-01/02/04 dashboards/status/energy | §2, §7 | thin read surface; no energy/plug data yet |
| NL-01 NL device control | §2, §3 | controllable surface = resolver scripts only (no raw devices) |
| RQ-05 device purchasing list | §8 | plugs, vacuum, cameras, smoke/CO, water/leak, satellites |
| S0 satellites | §2, §5 | **0 satellites** (as expected; hardware pending) |

---
---

# Appendices (planning + provenance)

## Appendix A — Phase-2 read-only query plan (as executed)

**Targets.** REST `http://192.168.1.104:8123`; WS `ws://192.168.1.104:8123/api/websocket`.
**Auth (secret — runtime only, never written/logged/committed; echoed as `Bearer ***`):** REST header
`Authorization: Bearer <token>`; WS `{"type":"auth","access_token":"<token>"}` after `auth_required`.
**Driver:** Python 3 stdlib (`socket`, `base64`, `struct`, `json`, `urllib`) — raw-socket WS client,
multi-frame reassembly (accumulate continuation frames until FIN); ASCII-only console.

Executed calls (all read-only, all succeeded):

| Call | Populated | Result |
|---|---|---|
| REST `GET /api/config` | §1 | Core 2026.6.4, 165 components, RUNNING |
| REST `GET /api/states` | §2, §7 | 75 entities → 17 live domains; 3 battery; 9 unavailable/unknown |
| WS `config/area_registry/list` | §4 | 4 areas |
| WS `config/device_registry/list` | §5 | 23 devices |
| WS `config/entity_registry/list` | §2, §3, §5 | 463 entries (has `options`); 388 disabled |
| WS `config_entries/get` | §6 | 17 config entries |
| WS `homeassistant/expose_entity/list` | §3 | 13 exposed to `conversation` |

Join/derivation done in-script (no extra HA calls). Whitelisted-field extraction only (no wholesale
attribute dumps → no secret leakage). Scrubbed JSON outputs stayed in the session scratchpad (not
committed): `report_summary.json`, `states_domains.json`, `areas.json`, `devices_processed.json`,
`integrations.json`, `config_entries.json`, `entity_registry_slim.json`, `expose_raw.json`.

## Appendix B — Uncertain endpoints: resolution

| Datum | Candidate tried | Outcome |
|---|---|---|
| Config entries (§6) | `config_entries/get` | **confirmed** on Core 2026.6.4 (fallback `config_entries/list` not needed) |
| Conversation exposure (§3) | `homeassistant/expose_entity/list` (read) | **confirmed**; setter never called |
| Entity `options`/exposure blob | `config/entity_registry/list` | **confirmed** to carry `options` (corroborates §3) |
| HAOS / OS version (§1) | `/api/config` (no HAOS field) → device-registry `sw_version` | **resolved** via device registry (Supervisor host APIs untouched) |

## Appendix C — Read-only & secret-handling confirmation

- Only HTTP `GET` + WS `*/list`/`get` were issued. **No** POST/PUT/DELETE/call_service, **no**
  `homeassistant/expose_entity` (set), **no** reload/restart, **no** host/SSH, **no** registry/script/
  automation/exposure mutation.
- Token: read into an in-memory variable from a scratchpad file, never echoed/written/committed; the
  deliverable was secret-scanned (clean). Captured responses were field-whitelisted before saving.
- Gate (`BACKLOG.md` §10) left **FREE**; HA-01 does not claim it.
