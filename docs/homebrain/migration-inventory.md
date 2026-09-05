# Legacy Home Assistant Core — Migration Inventory & Plan

**Host:** `homebrain` (`costea@192.168.1.68`)
**Source:** legacy HA **Core 0.57.2** (Nov 2017), Python 3.5.2 — config at `/home/costea/.homeassistant`, live at `192.168.1.68:8123`
**Target:** new **HAOS 18.0 / HA Core 2026.6.4** VM (`haos`, `192.168.1.104`) — see `haos-vm-deployment.md`
**Produced:** 2026-06-21 · **Method:** read-only inspection. **Neither installation was modified.**

> ⚠️ **Secret values are masked here** (this file lives in a git repo). Real values remain only in the host files noted. See §11 — rotate/replace, don't copy.

---

## 0. Headline

The legacy instance is **~8.5 years old (Core 0.57.2, Nov 2017, Python 3.5)**. There is **no supported upgrade path** from 0.57.2 to **2026.6.4** — and none is needed: the real configuration is a **single 2 KB `configuration.yaml` with zero automations, scripts, scenes, dashboards, or custom components**. Migration = **re-adding ~6 integrations through the new HAOS UI**. The 14 GB of databases are disposable history.

---

## 1. Environment & versions

| Item | Value |
|---|---|
| HA Core version | **0.57.2** (`/.HA_VERSION`, `hass --version`) |
| Python | 3.5.2 (system) — EOL |
| Install type | **Core in a venv** (`/usr/local/bin/hass`) — **not** Supervised/HAOS → **no Supervisor, no add-ons** |
| Service | systemd `home-assistant@costea.service`, user `costea` |
| Listen / auth | `192.168.1.68:8123`, legacy `api_password` (no user accounts) |
| Config dir | `/home/costea/.homeassistant` (14 GB total) |

---

## 2. `configuration.yaml` structure

- **One file**, 2,095 bytes, last modified Nov 2017. No `!include`, no `packages:`, no `!secret` references.
- Predates the `.storage`/UI config-entries era → **no `.storage/` directory**; everything is YAML, nothing configured via UI.

### Active top-level keys
```yaml
homeassistant:   # name: HomeBrain; latitude 50, longitude 114 (⚠ likely should be -114 for Calgary); TZ Canada/Mountain; unit_system metric
history:         # enables recorder+history (default SQLite) -> source of the 12 GB DB
conversation:
discovery:       # zeroconf/netdisco LAN auto-discovery
sun:
sensor:  { platform: yr }                 # Norwegian weather
frontend:
logbook:
updater:
http:    { api_password: <REDACTED> }     # legacy password auth
camera:  { platform: foscam, ip 192.168.1.71, user camera1_mark, password <REDACTED>, name mark_cam }
"camera 1": { platform: foscam, ip 192.168.1.72, user eliza, password <REDACTED>, name eliza_cam }   # ⚠ malformed key "camera 1" -> NOT loaded
```

### Commented-out / inactive (won't migrate; noted for completeness)
`cpuspeed` sensor · `google_travel_time` (Google Maps API key, redacted) · `gtfs` Calgary transit (data dir `gtfs/`, e.g. `calgary.zip`) · `orvibo` switch (192.168.1.65) · `water_tank` group · one example time-trigger automation · `generic` IP camera.

---

## 3. Included YAML files

**None.** The following do **not** exist: `automations.yaml`, `scripts.yaml`, `scenes.yaml`, `groups.yaml`, `customize.yaml`, `known_devices.yaml`. The only `*.yaml` in the config dir is `configuration.yaml`.

---

## 4. secrets.yaml usage

**No `secrets.yaml` exists.** No `!secret` tags are used. **All secrets are stored inline in plaintext** (see §11).

---

## 5. Installed integrations

### Active (YAML)
| Integration | Detail | Target on Core 2026.6.4 |
|---|---|---|
| `history`, `logbook`, `conversation`, `discovery`, `sun`, `frontend`, `updater` | core | Built-in defaults — nothing to do (`updater` is obsolete/removed) |
| `http` + `api_password` | legacy auth | **Removed** — use user accounts; do **not** migrate |
| `sensor: yr` | weather | `yr` removed → add **Met.no** |
| `camera: foscam` `mark_cam` (192.168.1.71) | IP camera | Add via **Foscam**/ONVIF integration |
| `camera 1: foscam` `eliza_cam` (192.168.1.72) | ⚠ malformed key → not active | Re-add if still wanted |

### Auto-discovered / token-based (from `deps/` + `plex.conf`)
| Integration | Evidence | Target |
|---|---|---|
| **Plex** | `plex.conf` (server `192.168.1.68:32400`, token redacted) | **Plex** UI integration (re-auth) |
| **Google Cast / Chromecast** | `pychromecast` dep | **Google Cast** (auto-discovered) |
| **Samsung TV** | `samsungctl` dep | **Samsung TV** UI integration |
| **Wake-on-LAN** | `wakeonlan` dep | **Wake on LAN** |

---

## 6. Automations · Scripts · Scenes

- **Automations: NONE** (only one *commented-out* example in `configuration.yaml`).
- **Scripts: NONE.**  **Scenes: NONE.**  **Groups: NONE.**
- → Nothing to port; rebuild in the new UI as desired.

---

## 7. Dashboards

- **None to migrate.** Core 0.57.2 predates **Lovelace** (introduced 0.86, Dec 2018). The UI was the **auto-generated states view**; there is no `ui-lovelace.yaml` and no `.storage/lovelace*`. The new HAOS auto-generates dashboards; build custom ones fresh.

---

## 8. custom_components / HACS

- **`custom_components/`: does not exist.**
- **HACS: not present.** No custom or community integrations. Clean slate.

---

## 9. Recorder / database configuration

- **No explicit `recorder:` block** — only `history:` is enabled, so the recorder runs with **all defaults**: SQLite at `home-assistant_v2.db`, **no `purge_keep_days`, no `exclude` filters** → unbounded growth.

| File | Size | Notes |
|---|---|---|
| `home-assistant_v2.db` | **12 GB** | Active recorder (SQLite), ~8 yrs of unpurged history |
| `home-assistant.db` | 2.1 GB | Orphaned legacy-schema DB from 2017 |

- **Do not migrate the DBs** — history only, schema incompatible with the 2026 recorder; HAOS starts fresh. If specific long-term history matters, export those series before decommissioning.

---

## 10. Add-ons / external dependencies

- **Add-ons: N/A.** This is a **Core venv** install with **no Supervisor**, so the add-on concept does not exist here. (Add-ons are a HAOS/Supervised feature — they begin fresh on the new VM.)
- **External services it talks to:** Plex (same host `:32400`), Foscam cameras (`192.168.1.71/.72`), Chromecast/Samsung TV on the LAN, met/yr weather API.
- **Python deps (`deps/`, 49 pkgs)** — auto-managed; **none need manual porting**. Notable: `plexapi`, `pychromecast`, `samsungctl`, `wakeonlan`, `libpyfoscam`, `zeroconf`, `netdisco`, `sqlalchemy`, `home_assistant_frontend (20171105.0)`.

---

## 11. Secrets (⚠ all plaintext; no `secrets.yaml`)

| # | Secret | Location (host) | Action |
|---|---|---|---|
| 1 | `http` API password | `configuration.yaml` → `http.api_password` | **Drop** — `api_password` removed; use user accounts |
| 2 | Foscam `mark_cam` pw (user `camera1_mark`) | `configuration.yaml` | Rotate on camera; store via `!secret` |
| 3 | Foscam `eliza_cam` pw (user `eliza`) | `configuration.yaml` | Rotate; re-add only if still used |
| 4 | Plex server token | `plex.conf` | Re-auth in new Plex integration (reissues token) |
| 5 | Google Maps API key | `configuration.yaml` (commented `google_travel_time`) | Rotate/restrict in Google Cloud if re-enabled |

Treat all five as **exposed** (plaintext for years). Rotate, and in the new instance keep them in `secrets.yaml` referenced with `!secret`.

---

## 12. Migration risks & incompatibilities (vs HAOS 18.0 / Core 2026.6.4)

| Risk / incompatibility | Impact | Mitigation |
|---|---|---|
| **0.57.2 → 2026.6.4 spans ~8.5 yrs of breaking changes** | No config or DB is forward-compatible; in-place upgrade impossible | **Re-configure fresh** on the new VM (config is tiny) |
| **`http: api_password` removed** (since 0.77/0.90 era) | Old auth model gone; copying it breaks startup | Use HA **user accounts** (new instance already onboarded with one) |
| **`updater` integration removed** | Invalid key if copied | Omit; updates are built-in |
| **`sensor: yr` removed/renamed** | Weather won't load if copied | Use **Met.no** |
| **Legacy YAML platform style** (`camera:`/`sensor:` inline platforms) | Many old YAML integrations are now UI-only config entries | Add via **Settings → Devices & Services** |
| **Malformed `camera 1:` key** | `eliza_cam` silently never loaded (latent bug) | Re-add intentionally if needed |
| **DB schema (12 GB) incompatible** | Cannot import; would bloat new VM (only ~39 GB free SSD) | Start fresh; set `recorder` retention |
| **Plaintext secrets / weak creds** | Exposed camera/Plex/Google credentials | Rotate; use `!secret` (see §11) |
| **Location longitude `114`** (should be `-114`) | Wrong sun/weather/location data | Fix during `core_config` |
| **Recorder with no purge** | Repeat of multi-GB DB growth | Configure `recorder: purge_keep_days: N` + excludes |

---

## 13. Recommended migration plan

1. **Do not** copy config/DB or attempt an upgrade — incompatible across the version gap.
2. On the new HAOS (`http://192.168.1.104:8123`), add integrations via **Settings → Devices & Services**:
   **Plex** (re-auth) · **Google Cast** (auto) · **Samsung TV** · **Wake on LAN** · **Foscam** camera(s) · **Met.no** weather.
3. Verify location during onboarding/`core_config` — **longitude = -114** for Calgary; TZ `Canada/Mountain`; metric.
4. Auth: rely on **user accounts** (already set). Keep secrets in `secrets.yaml` (`!secret`); rotate the §11 credentials.
5. Configure the **recorder** with retention, e.g.:
   ```yaml
   recorder:
     purge_keep_days: 14
     # optional: exclude noisy domains/entities
   ```
6. Build dashboards/automations fresh in the UI as needed (none exist to port).
7. Run **both instances in parallel** (old `192.168.1.68:8123`, new `192.168.1.104:8123`) until verified.
8. **Decommission** the legacy service only when satisfied:
   `sudo systemctl disable --now home-assistant@costea`  *(left running until you decide).*

---

## 14. Source files inspected (read-only)

`/.HA_VERSION` · `configuration.yaml` · `plex.conf` · `deps/lib/python3.5/site-packages/` · `home-assistant.log` · directory listing of `/home/costea/.homeassistant` (confirming absence of `.storage/`, `custom_components/`, `ui-lovelace.yaml`, `secrets.yaml`, and all split YAML files). **No files were modified on either installation.**
