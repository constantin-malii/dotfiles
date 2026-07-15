# HomeBrain Backlog

> **Single source of truth for *future work* and the *parallel-agent operating model*.**
> `ONBOARDING.md` and `CHANGELOG.md` remain authoritative for **current running state** — this
> file points to them and never duplicates them. When an item ships, mark it Done here and record
> the operational detail in `CHANGELOG.md`.

**Last refined:** 2026-07-01. Taxonomy = 10 tracks (locked). Item schema = 14 fields (locked).

**Layout:** §2 is the **compact board** (navigation only). §5 is the **extended item index** — the
working backlog, every item with all 14 fields as explicit columns.

---

## 1. How to use this file

- Every backlog item lives in exactly one **track** (§3) and carries the full **14-field schema** (§4),
  shown explicitly in the **extended index** (§5).
- The **compact board** (§2) is for navigation; the **extended index** (§5) is the working detail.
- Work happens **one branch/worktree per track** (§8), off protected `main`.
- **At most one live-system gate is active at a time** — see the **gate register** (§10).
- Items marked `Done` link to `CHANGELOG.md` for the operational record.

---

## 2. Compact board (navigation)

### 🟢 Active
- `INF-01` Adopt parallel-agent operating model + maintain this `BACKLOG.md` *(INF)*

### 🔵 Ready / Next *(all read-only / design / decision; no live gate)*
- `RQ-03` Music-source / Inc 3 direction decision *(RQ)*
- `RQ-06` Z-Wave coordinator adoption decision *(RQ)*
- `P0` PCL notes-only MVP — Ready, **not** Active *(P)*
- `NL-02` Prompt / `assistant-capabilities.md` lockstep discipline *(NL)*
- `MR-05` Tidy verbose RadioBrowser station names *(MR)*

### 🟡 Later
- `MR-Inc3` acquire (Lidarr, guarded — unblocked by RQ-03 2026-07-06) · `MR-Inc2B` · `MR-Inc4B` · `MR-04` · `MR-06` · `MR-07`
- `P1` reminders · `P2` decisions/referents · `P3` HA delivery · `P4` drafting/recall · `P5` receipts · `P6` multi-user · `P7` semantic memory
- `HA-02` plugs/switches · `HA-03` vacuum · `HA-04` cameras · `HA-05` routines · `HA-06` device health · `HA-08` garage door (Meross) · `HA-09` ecobee climate
- `SA-03` smoke/CO alerting · `SA-04` water/leak alerting · `SA-05` security/camera detection
- `DV-01` home status · `DV-02` needs-attention · `DV-03` dashboards · `DV-04` energy
- `NL-01` NL device control · `NL-03` gpt-4o eval
- `INF-03` soundbar · `INF-04` `/hassio` panel · `INF-06` Lidarr/Beets/Plex · `INF-07` backup target · `INF-08` UPS + NUT resilience
- `S1b`–`S4` satellite routing *(after S1a)* · `RQ-04` hardware volume buttons

### 🔴 Blocked
- `RQ-02` upstream MA lock issue — YTM reliability + approval
- `INF-05` HAOS upgrade / host modernization — backups + risk plan

### ✅ Done *(detail in `CHANGELOG.md`)*
- `MR-Inc0` foundation · `MR-Inc1` radio · `F1`/`F1-R` CommandResult + relay · `BUG-Speaker` reconnect fix · `MR-Inc4A` status · **`MR-Inc2A` News (deployed + exposed + validated)**
- `HA-01` device & entity inventory · `SA-01` smoke/CO design · `SA-02` water/leak design · `HA-07` device integration roadmap · `RQ-05` purchase-gap *(fulfilled by `HA-07`)* · `AU-01` audio-policy design · `S0` satellite inventory (reSpeaker Living Room)
- **`AU-02`+`AU-03` interaction duck/restore** (`InteractionCapability`, deployed + live-validated 2026-07-15)
- **`S1a`** satellite→ceiling duck/restore trigger (HA automation, installed + live-validated 2026-07-15)

### 🔬 Research / Purchasing
- `RQ-01` YTM reliability · `RQ-03` music-source decision *(also Ready)* · `INF-02` HA↔MA reconnect root-cause · `MR-06` semantic match

---

## 3. Track definitions

Each track = one branch/worktree prefix `homebrain/<track-code>-<slug>`. Established labels
(`Inc N`, `P#`, `S#`) are preserved inside their tracks.

| Code | Track | Owner component | Scope |
|---|---|---|---|
| **MR** | Media / Resolver | resolver | Media execution + media TTS: music, radio, news, status, transport, volume, acquire. Keeps `Inc 2A/2B/3/4A/4B`. |
| **P** | PCL / `homebrain-companion` | PCL | Notes, reminders, decisions, household memory, drafts, family logistics, receipts, personal context. Keeps `P0–P7`. |
| **HA** | Home Assistant Devices | HA / device | Devices, entities, rooms/areas, integrations, sensors, device health. |
| **NL** | Natural-Language Control Surface | resolver + HA | Thin routing layer + prompt/tool-description discipline over deterministic caps. |
| **SA** | Safety / Alerts | HA / device + PCL escalation | Smoke/CO, water/leak, security. **Stricter gates** (§4, §8). |
| **DV** | Dashboards / Value Features | HA + PCL read models | Household status read-models, dashboards, energy. |
| **S** | Satellites / Room Routing | HA + PCL | Satellite endpoints + `InteractionContext`/`ResponseRoutingPolicy`. Design/inventory-first. Keeps `S0–S4`. |
| **AU** | Interaction Audio Policy | resolver + HA | Pause/duck/resume during conversation; resume-restore. **AU / Track S boundary — not PCL P0 mechanics.** |
| **INF** | Infrastructure / Operating Model | process / host | Operating model, host/VM, MA/HA reconnect, deploy/backup, upstream issues. |
| **RQ** | Backlog / Research / Purchasing | research / device-purchase | Decisions, research spikes, hardware buy-lists. |

---

## 4. Item schema (14 fields)

Every item in the extended index (§5) carries all 14 fields as explicit columns:

`id` · `title` · `track` · `status` · `type` · `priority` · `owner` · `dependency` ·
`risk/blast-radius` · `likely-files` · `live-gates` · `rollback` · `next-action` · `source-ref`

- **status:** `active` | `ready` | `later` | `blocked` | `done` | `research`
- **type:** `design` | `repo-code` | `HA-live` | `host-live` | `device-purchase` | `research` | `documentation`
- **priority:** `P0` | `P1` | `P2` | `later`
- **owner:** `resolver` | `PCL` | `HA` | `device` | `process`

**Default-fill conventions** (so cells stay terse; a cell may override):
- **rollback** — repo-code → `git revert` on branch; resolver-live → restore `~/mass-resolver/.bak/<ts>/`
  + approval-gated restart; HA-script → delete script + reload (per-script `*.pre<X>.json` backup);
  exposure → un-expose via `homeassistant/expose_entity`; design/research → n/a.
- **likely-files** — MR repo-code → `mass-resolver/<module>.py` + `tests/test_<module>.py` + design/plan doc;
  HA-live → none + `CHANGELOG.md`; PCL → new `homebrain-companion` repo; design/research → a new doc.
- **risk/blast-radius** — read-only/design/research = none; repo-code = branch-isolated; resolver-live =
  media path (single gate); HA-live/exposure = shared conversation surface; **SA-live = life-safety/property (strictest)**.

---

## 5. Extended item index (working backlog — full 14-field schema)

> All 14 fields are explicit columns. Wide tables scroll horizontally.

### MR — Media / Resolver
| ID | Title | Track | Status | Type | Pri | Owner | Dependency | Risk / blast radius | Likely files | Live gates | Rollback | Next action | Source ref |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `MR-Inc2A` | News headlines | MR | done | repo-code→HA-live | — | resolver | — | shipped (media path) | `news.py`,`newsfeed.py`,`news.json`,tests | (closed) | restore `.inc2-bak/` + un-expose `script.news` | CHANGELOG 2026-06-29 |
| `MR-Inc2B` | News-station playback | MR | later | repo-code | P2 | resolver | MR-Inc2A | branch-isolated | `radio.py`/`news.py`+tests | none (build); exposure if surfaced | `git revert` | inc2a design |
| `MR-Inc3` | Acquire via Lidarr (guarded) | MR | later | repo-code→HA-live | P1 | resolver | RQ-03 ✅ (decided 2026-07-06) | guarded write to Lidarr | `acquire.py`+tests; `.lidarr` secret | host deploy + exposure | restore `.bak/` + un-expose | design `acquire` = guarded Lidarr add+search across both routes (Usenet + Soulseek); see 2026-07-06-rq-03 §7 | tooling §7 |
| `MR-Inc4B` | Sleep timer + shuffle/repeat + queue | MR | later | repo-code→HA-live | P2 | resolver | MR-Inc4A | media path | `status.py`/`core.py`+tests | exposure | restore `.bak/` + un-expose | inc4a design |
| `MR-04` | Status aspect enum / per-aspect text | MR | later | repo-code | P2 | resolver | MR-Inc4A | branch-isolated | `status.py`+tests | exposure | `git revert` | inc4a design |
| `MR-05` | Tidy verbose RadioBrowser names | MR | ready | repo-code | P2 | resolver | — | branch-isolated (cosmetic) | `radio.py`+tests | none | `git revert` | tooling §10 |
| `MR-06` | Semantic / translation match hints | MR | research | repo-code | later | resolver | — | none (spike) | `match.py`+tests | none | `git revert` | tooling §10 |
| `MR-07` | Provider/metadata/Plex cleanup | MR | later | host-live | P2 | resolver | — | host data edit | none (host/MA) | host change | restore prior MA config | local-music; tooling §10 |

### P — PCL / homebrain-companion
> **Phase renumber (this backlog):** `P0`=notes-only · `P1`=reminders · `P2`=decisions/referents. More
> granular than the design doc's combined P0 MVP (`personal-assistant-layer-brainstorm.md` C§6) and aligned
> with the PCL critique branch's notes-only narrowing. **Reconcile the design doc when the P-track activates.**
> Both P0 entry gates met (F1-R music stable ✅, Speaker reconnect ✅). P0 is Ready, deliberately **not** Active.

| ID | Title | Track | Status | Type | Pri | Owner | Dependency | Risk / blast radius | Likely files | Live gates | Rollback | Next action | Source ref |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `P0` | Notes-only MVP (create/recall/forget + audit, SQLite) | P | ready | repo-code | P1 | PCL | gates met | new isolated service (no media risk) | new `homebrain-companion` repo | none (build); exposure later | delete container/repo; nothing live touched | PCL §14, C§6 |
| `P1` | Durable reminders (record + confirmed `due_at`) | P | later | repo-code | P2 | PCL | P0 | branch-isolated | `homebrain-companion` repo | none | `git revert` | PCL §9 |
| `P2` | Light decisions + short-term referents | P | later | repo-code | later | PCL | P0 | branch-isolated | `homebrain-companion` repo | none | `git revert` | PCL §8/§10 |
| `P3` | HA delivery wiring (reminder firing, privacy-gated) | P | later | HA-live | later | PCL | P1 | shared conversation surface | HA script + repo | new tool + exposure | delete script + un-expose | PCL §15 (was design-P1) |
| `P4` | Drafting (human sends) + richer recall | P | later | repo-code | later | PCL | P1 | branch-isolated | `homebrain-companion` repo | none | `git revert` | PCL §15 (was design-P2) |
| `P5` | Receipts: meta → images → OCR | P | later | repo-code | later | PCL | P4 + privacy review | high-sensitivity (financial PII) | `homebrain-companion` repo + blob dir | none | `git revert` + purge blobs | PCL §15 (was design-P3/4) |
| `P6` | Multi-user / family | P | later | repo-code | later | PCL | privacy review | security boundary (cross-user leak) | `homebrain-companion` repo | none | `git revert` | PCL §15 (was design-P5) |
| `P7` | Semantic / smart memory (opt-in) | P | later | repo-code | later | PCL | evidence of need | trust/privacy (silent memory) | `homebrain-companion` repo | none | `git revert` | PCL §15 (was design-P6) |

### HA — Home Assistant Devices
| ID | Title | Track | Status | Type | Pri | Owner | Dependency | Risk / blast radius | Likely files | Live gates | Rollback | Next action | Source ref |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `HA-01` | **Device & entity inventory** | HA | done | documentation/research | P1 | HA | — | none (read-only) | new inventory doc | none (read-only HA queries) | n/a | done | ha-device-inventory.md |
| `HA-02` | Smart plugs / switches control | HA | later | repo-code→HA-live | P2 | device | HA-07 + NL-01 · Kasa HS220 dimmer (`light`, no energy) | shared conversation surface | resolver/HA cap + script | exposure | delete script + un-expose | new |
| `HA-03` | Vacuum control | HA | later | repo-code→HA-live | later | device | HA-07 · iRobot Roomba Combo (`roomba` local push, no maps) | shared conversation surface | resolver/HA cap + script | exposure | delete script + un-expose | new |
| `HA-04` | Cameras (view / snapshot) | HA | later | design→HA-live | later | device | HA-07; privacy · Reolink (local path) | privacy-sensitive surface | design doc → HA script | exposure (strict) | delete script + un-expose | new |
| `HA-05` | Routines / automations exposure | HA | later | design | later | HA | HA-01 | HA-config surface | design doc | HA change | revert HA change | new |
| `HA-06` | Device health / battery / offline read-model | HA | later | design→repo-code | P2 | HA | HA-01 ✅ | none (read-only model) | design doc → cap | read-only | `git revert` | **design DELIVERED 2026-07-06**; impl = resolver health read fn (fresh HA read, like status); supplies DV-02; SA keeps its own strict path | 2026-07-06-ha-06 |
| `HA-07` | Existing device integration architecture | HA | done | documentation/research | P1 | HA | HA-01, SA-01/02 | none (research) | device-integration roadmap doc | none | n/a | done | device-integration-architecture-roadmap.md |
| `HA-08` | Garage door (Meross MSG100) — access-sensitive | HA | later | design→HA-live | later | device | HA-07 | access/security-sensitive surface | design doc → HA script | exposure (strict) | delete script + un-expose | design local HomeKit-Controller `cover` path (strict, state-checked/confirmation-gated) | device-integration-architecture-roadmap.md |
| `HA-09` | ecobee climate entity — cloud-dependent | HA | later | design→HA-live | later | device | HA-07 | cloud dependency | design doc → HA config | exposure | revert HA config | add `climate` via cloud `ecobee` (HA-01 saw ecobee only as MA `media_player`, no `climate`) | device-integration-architecture-roadmap.md |

### NL — Natural-Language Control Surface
| ID | Title | Track | Status | Type | Pri | Owner | Dependency | Risk / blast radius | Likely files | Live gates | Rollback | Next action | Source ref |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `NL-01` | NL device control = thin routing over deterministic caps | NL | later | design | P2 | resolver/HA | HA-01 | shared conversation surface | design doc | exposure | revert prompt/exposure | new |
| `NL-02` | Prompt / `assistant-capabilities.md` lockstep discipline | NL | ready | documentation | P2 | process | — | exposure-adjacent (truthfulness) | `assistant-capabilities.md` (locked, §9) | exposure-adjacent | revert doc/prompt | assistant-capabilities |
| `NL-03` | gpt-4o model evaluation (gated) | NL | later | research | later | resolver | persistent tool-selection declines | one-field model change | none | model flag | revert model field | tooling §10 |

### SA — Safety / Alerts *(stricter gates — §8)*
| ID | Title | Track | Status | Type | Pri | Owner | Dependency | Risk / blast radius | Likely files | Live gates | Rollback | Next action | Source ref |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `SA-01` | **Smoke/CO** inventory + escalation design (life-safety) | SA | done | research/design | P1 | HA/device | HA-01 | none (design) | new design doc | none | n/a | done | 2026-06-30-sa-01-02-safety-alerts-design.md |
| `SA-02` | **Water/leak** inventory + escalation design (property) | SA | done | research/design | P1 | HA/device | HA-01 | none (design) | new design doc | none | n/a | done | 2026-06-30-sa-01-02-safety-alerts-design.md |
| `SA-03` | Smoke/CO alerting + escalation (impl) | SA | later | design→HA-live | later | HA/device | SA-01 + HA-07 + Z-Wave coordinator (RQ-06, ZWA-2 on order) | **life-safety (strictest)** | HA automations/scripts | **exposure (strictest)** | **disable switch + one-step disable/rollback (mandatory)** | plan ready (`plans/2026-07-06-sa-03-smoke-co-alerting-plan.md`); await coordinator → enable (Path A), pair ZEN55, build per SA-01 §3, pass §3.9 gate. Confirm Q3 (ZEN55 wired) + critical-push | 2026-06-30-sa-01-02-safety-alerts-design.md · plans/2026-07-06-sa-03 |
| `SA-04` | Water/leak alerting + escalation (impl) | SA | later | design→HA-live | later | HA/device | SA-02 + HA-07 + leak-sensor ownership/purchase + likely Z-Wave coordinator | **property (strict)** | HA automations/scripts | **exposure (strict)** | **disable switch + one-step disable/rollback (mandatory)** | new |
| `SA-05` | Security alerts / camera person-detection | SA | later | design | later | HA/device | HA-04, SA-01/02 | privacy + safety | design doc | exposure (strict) | revert exposure | new |

> **SA gate (all SA-live items):** disable switch + tested false-pos/false-neg validation + confirmation
> flow + documented one-step disable/rollback **before** exposure. **Smoke/CO = life-safety (strictest);
> water/leak = property (strict).**

### DV — Dashboards / Value Features
| ID | Title | Track | Status | Type | Pri | Owner | Dependency | Risk / blast radius | Likely files | Live gates | Rollback | Next action | Source ref |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `DV-01` | "What's on / running / open?" home status | DV | later | design→repo-code | P2 | HA | HA-01 ✅ | none (read-only) | design doc → resolver read cap | read-only (exposure gated) | n/a | **design DELIVERED 2026-07-06**; impl = resolver read capability (reuse `media_status`, F1-R hard return), gated exposure | 2026-07-06-dv-01-02 |
| `DV-02` | "What needs attention?" household status | DV | later | design→repo-code | P2 | HA | HA-01 ✅, HA-06 | none (read-only) | design doc → resolver read cap | read-only (exposure gated) | n/a | **design DELIVERED 2026-07-06**; impl consumes HA-06 + (future) SA supervision; ranked, honest-reporting | 2026-07-06-dv-01-02 |
| `DV-03` | Dashboards (household view) | DV | later | HA-live | later | HA | HA-01 | HA-config surface | HA Lovelace config | HA change | revert dashboard | new |
| `DV-04` | Energy monitoring | DV | later | design | later | HA | metering hardware (HS220 has no energy monitoring) | none (read-only) | design doc | read-only | n/a | research | new |

### S — Satellites / Room Routing *(design/inventory-first; build only when approved + installed)*
| ID | Title | Track | Status | Type | Pri | Owner | Dependency | Risk / blast radius | Likely files | Live gates | Rollback | Next action | Source ref |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `S0` | Inventory satellites (entities/rooms/pipelines/TTS-reach/identity) | S | done | research | P2 | HA | hardware installed ✅ (reSpeaker Living Room, 2026-07-14) | none (read-only) | `s0-satellite-inventory.md` | read-only | n/a | **DELIVERED 2026-07-14** (`s0-satellite-inventory.md`): 1 satellite, `Living Room Voice` pipeline (Whisper+Piper), local TTS ✅; **gaps → S1**: area unassigned + no satellite→ceiling route | PCL §6A.8 · CHANGELOG 2026-07-14 · s0-satellite-inventory |
| `S1a` | Satellite→ceiling interaction duck/restore **trigger** (HA automation → resolver `interaction` intent) | S | done | HA-live | P2 | HA | S0 ✅ · AU-02/AU-03 ✅ | one HA automation | HA automation | HA-live (claimed+released 2026-07-15) | disable/delete automation | **DONE 2026-07-15** — `automation.s1a_satellite_ceiling_duck_restore` installed + live-validated (duck 0.32→0.15 on wake, coalesced re-ducks, restore→0.32, silent). See `CHANGELOG.md` 2026-07-15 · `plans/2026-07-15-s1a-satellite-ceiling-trigger.md` | 2026-07-14-s1a design |
| `S1b`–`S4` | reply-on-ceiling relay (`S1b`) → `ResponseRoutingPolicy` → privacy gating → household announce/targeting | S | later | design→repo-code | later | PCL/HA | S1a ✅ | privacy + delivery surface | design docs → `homebrain-companion` repo + HA | per-phase | `git revert` / revert HA delivery | **S1b next** = universal resolver TTS relay so replies play on the ceiling (F1/F1-R-grade, no double-speak) | PCL §6A, C§7 · 2026-07-14-s1a §2 |

### AU — Interaction Audio Policy *(AU / Track S boundary — not PCL P0 mechanics)*
| ID | Title | Track | Status | Type | Pri | Owner | Dependency | Risk / blast radius | Likely files | Live gates | Rollback | Next action | Source ref |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `AU-01` | Audio policy design (media-zone ducking) | AU | done | design | P1 | resolver/HA | HA-07 ✅; S0 (multi-room only) | none (design) | design doc | none | n/a | **DELIVERED 2026-07-06** — single-zone pause/duck/ignore policy + restore semantics; feeds AU-02/AU-03; multi-room waits on S0. See `2026-07-06-au-01-interaction-audio-policy-design.md` | 2026-07-06-au-01 |
| `AU-02` | Explicit "resume music" restore behavior | AU | done | design→repo-code | P2 | resolver/HA | AU-01 ✅ | media path | `interaction.py`/`core.py`/`config.py`+tests | resolver + HA | restore `.bak/` | **DONE 2026-07-15** — shipped with AU-03 as one `InteractionCapability`; deployed + live-validated (duck 0.43→0.15, restore→0.43). See `CHANGELOG.md` 2026-07-15 · `plans/2026-07-14-au-02-03-interaction-duck-restore-plan.md` | 2026-07-06-au-01 §6 |
| `AU-03` | Ducking implementation | AU | done | repo-code→HA-live | later | resolver/HA | AU-01 ✅ / AU-02 | media path + HA | resolver modules + HA | host + HA | restore `.bak/` + revert HA | **DONE 2026-07-15** — merged with AU-02: verified fresh-REST duck/restore, 120s dead-man, silent intent; deployed + live-validated. See `CHANGELOG.md` 2026-07-15 | 2026-07-06-au-01 §3–§5 |

### INF — Infrastructure / Operating Model
| ID | Title | Track | Status | Type | Pri | Owner | Dependency | Risk / blast radius | Likely files | Live gates | Rollback | Next action | Source ref |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `INF-01` | Operating model + maintain `BACKLOG.md` | INF | active | documentation | P0 | process | — | none | `BACKLOG.md` | none | `git revert` | adopt §8/§9; keep board current | this doc |
| `INF-02` | HA↔MA reconnect root-cause | INF | research | research | P2 | process | — | none (read-only) | research notes | read-only | n/a | upstream/source dig | audio-arch §13 |
| `INF-03` | Samsung soundbar AirPlay-2 / Sendspin | INF | later | host-live | later | process | hardware | host/MA config | none (host/MA) | host change | revert MA player config | ceiling-zone §10 |
| `INF-04` | Supervisor `/hassio` panel | INF | later | HA-live | later | process | — | HA surface | none (HA) | HA change | revert HA change | audio-arch §13 |
| `INF-05` | HAOS upgrade / host modernization | INF | blocked | host-live | later | process | backups | **high (VM/host)** | none (host/VM) | host change (high risk) | restore VM snapshot/backup | haos-vm §12 |
| `INF-06` | Lidarr auto-sync · Beets · Plex Music add | INF | later | host-live | P2 | process | — | host data/services | none (host) | host change | revert host config | local-music §7 |
| `INF-07` | Companion backup target (local-only) | INF | later | process | P2 | process | P0 | none (local-only) | backup script/config | none | revert config | PCL Q5 |
| `INF-08` | UPS + NUT resilience (host + router/network + future coordinator) | INF | later | design→host-live | later | process | device roadmap; UPS ownership unknown | none (design) | design doc → NUT config | none (host-live at impl) | revert doc/config | confirm UPS ownership + design NUT approach | device-integration-architecture-roadmap.md |

### RQ — Backlog / Research / Purchasing
| ID | Title | Track | Status | Type | Pri | Owner | Dependency | Risk / blast radius | Likely files | Live gates | Rollback | Next action | Source ref |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `RQ-01` | YTM playback reliability / shelved guard | RQ | research | research | later | resolver | upstream fix | none | research notes | none | n/a | revisit only if YTM restored | research-playback-lock |
| `RQ-02` | File upstream MA lock issue | RQ | blocked | research | later | process | YTM reliability + approval | none (external) | `upstream-issue-draft.md` | none | retract issue if needed | upstream-issue-draft |
| `RQ-03` | **Music-source decision** (local/Tidal/Qobuz/Soulseek/YTM) | RQ | research | research | P2 | resolver | — | none (decision) | decision record | none | n/a | **DECIDED 2026-07-06: local-first** — add Soulseek (Soularr+slskd) alongside Lidarr+Usenet; defer streaming (Deezer/Tidal if ever, not Qobuz); keep YTM shelved. **Unblocks MR-Inc3.** See `2026-07-06-rq-03-music-source-decision.md` | tooling §10 · 2026-07-06-rq-03 |
| `RQ-04` | Hardware volume buttons → ceiling (Tasker) | RQ | later | research→repo-code | later | device | resolver HTTP (exists) | phone-side only | Tasker profile + resolver HTTP | phone-side | remove Tasker profile | tooling §11 |
| `RQ-05` | Device purchasing list | RQ | done | device-purchase | P2 | device | HA-01, SA-01/02 | none (procurement) | buy-list doc | none | n/a | done — purchase-gap analysis now lives in the `HA-07` roadmap (§11; gaps derived after existing-device mapping) | device-integration-architecture-roadmap.md |
| `RQ-06` | Z-Wave coordinator adoption decision | RQ | ready | research→device-purchase | P2 | device/process | — | none (decision) | decision record | none | n/a | **DECIDED 2026-07-06: HA Connect ZWA-2** (single worldwide SKU, 908.42 MHz auto-set; see `2026-07-01-rq-06-z-wave-coordinator-decision.md` §12); **coordinator on order**. Enablement = Path A USB passthrough (`runbooks/zwave-coordinator-enablement-path-a.md`), alerting impl = SA-03. Purchase/enablement still gated | device-integration-architecture-roadmap.md · 2026-07-01-rq-06 §12 |

---

## 6. Items that are natural-language triggered but **not PCL**

The misclassification risk is putting everything a user *says* under the companion. These are
NL-triggered but owned elsewhere:

| Item | Correct owner | Why not PCL |
|---|---|---|
| "Turn on/off the plug / lamp / switch" | **HA (device)** + **NL routing** | Deterministic entity action; PCL holds no device state. |
| "Start/stop the vacuum" | **HA (device)** | Deterministic entity command. |
| "What's playing / play the second one / volume" | **MR (resolver)** | Resolver-owned (`status`, `play_*`); PCL may cache referents, execution + TTS stay in resolver. |
| "Read the news / headlines" | **MR (resolver)** | Inc 2A content capability; deterministic feed + TTS. |
| "Pause the music while I talk / resume" | **AU + resolver/HA** | Deterministic media-interaction policy; no second TTS path in PCL. |
| "What's on / open / needs attention" | **DV read-model over HA** | Deterministic read across HA entities; truthfulness belongs to an HA-backed read-model. |
| "Is the door/leak/smoke OK / alert me" | **SA over HA** | Stricter gates, escalation, confirmation — separate track, never companion memory. |
| "Say it in the kitchen / tell everyone" | **S routing + HA delivery** | Output destination = deterministic `ResponseRoutingPolicy` (companion decides, HA delivers) — Track S. |
| Reminder **firing/delivery** | **HA** | PCL owns record + when; HA owns the firing channel, gated by routing policy. |
| Media **sleep timer** | **MR (Inc 4B)** | Locked C§5: media sleep timer = resolver; only *personal* reminders/timers = PCL. |

**PCL keeps only:** notes, durable personal reminders, light decisions, household memory/recall,
drafts, family logistics, receipts, personal context, and the *routing decision* computation.

---

## 7. Recommended first active / ready tracks

Biased to **reduce uncertainty and unblock** — all read-only / design / decision; **no implementation
stream, no live gate held**:

| # | Track | Why first | Type |
|---|---|---|---|
| 1 | `INF-01` Operating model + this `BACKLOG.md` | Establishes the rules everything runs under. | documentation |
| 2 | `HA-01` **Device & entity inventory** — ✅ done | Biggest uncertainty-reducer; **unblocked HA-02/03/04, SA-01/02, DV-01/02, AU-01, RQ-05** (RQ-05 now fulfilled by `HA-07`). Pure read-only. | documentation/research |
| 3 | `SA-01` + `SA-02` **Safety inventory + escalation design** — ✅ done | Life-safety + property; one read-only inventory yields both designs; strict gates defined up front. | research/design |
| 4 | `AU-01` **Audio policy design** (media-zone) | Daily voice usability; deterministic; design-only (multi-room waits on S0). | design |
| 5 | `RQ-03` **Music-source / Inc 3 decision** | Ends YTM-vs-local-vs-streaming ambiguity; **unblocks MR-Inc3**. | research/decision |

`P0` (notes-only PCL) stays **Ready** — deliberately **not** started, to avoid a second
implementation stream.

---

## 8. Parallel-agent operating rules

**Branching (protected `main`):**
- **One branch/worktree per track**, prefix `homebrain/<track-code>-<slug>`
  (e.g. `homebrain/ha-device-inventory`, `homebrain/au-audio-policy`).
- **No implementation on `main`.** Every track → feature branch → PR (remote `main` is protected).
- **Default merge, not rebase** when syncing from `main`.

**Live-system gate (hard rule):**
- **At most one** branch may hold an active **host-live / HA-live / exposure** gate at any time.
  The **gate register** (§10) names the current holder; others stay `ready` until it frees.
- All live actions stay **approval-gated** per `CLAUDE.md`: no host/SSH/HA/restart/exposure without
  explicit approval.

**Safety track (SA) — additional gates:**
- SA-live items require a **disable switch**, tested **false-positive/false-negative validation**, a
  **confirmation flow**, and a one-step **disable/rollback** documented *before* any exposure.
- Severity: **smoke/CO = life-safety (strictest)**, **water/leak = property (strict)**.

**Merge / PR strategy:**
- Small, reversible PRs per increment. **Doc / code / runtime-config commits kept separate**
  (`CLAUDE.md`). **Secret-scan before every commit. No Claude/AI attribution.**
- PR description states the **live-gate status** and the **rollback pointer**.

---

## 9. Shared-file lock rules

Serialize edits to these conflict-and-truth magnets — at most one track edits each at a time:

| File | Rule |
|---|---|
| `CHANGELOG.md` | Append-only; **one writer**; entry added **at merge**, not mid-branch. |
| `assistant-capabilities.md` | Locked to the track currently changing exposure (must stay in lockstep with the live OpenAI prompt). |
| `ONBOARDING.md` | Locked; update only when current-state truth changes (post-merge). |
| `mass-resolver/*.py` (resolver runtime) | MR track only; one deploy at a time (single live gate). |
| HA scripts / exposure docs | Locked to the track holding the exposure gate. |
| `BACKLOG.md` (this file) | INF track owns; other tracks propose status changes via their PR, INF reconciles the board. |

---

## 10. Live-system gate register

> **The single source of truth for who may take live action right now.**

| Gate | Holder | Status |
|---|---|---|
| **host-live / HA-live / exposure** | *(none)* | **FREE** — `S1a` claimed it to install the satellite duck/restore automation and released it on completion (2026-07-15). |

**To claim the gate:** record the track ID + branch here in the claiming PR; release it on merge or
abandonment. The first recommended tracks (§7) are all read-only/design/decision and **do not claim
the gate** — it remains free for the next live increment (likely `MR-Inc3` once `RQ-03` settles).

---

## 11. Prompt generation queue

Ready-to-dispatch per-track agent prompts. Each runs **read-only / design** unless it claims the gate
(§10). Standard report format = §12.

- **`HA-01` — Device & entity inventory** (read-only) — ✅ dispatched & complete (`ha-device-inventory.md`):
  > "Read-only HA inventory. Do not change/expose/restart anything. Enumerate via HA REST/WS: all
  > entities (by domain), which entities are exposed to `conversation`, all areas/rooms and
  > device→area mapping, all integrations/config-entries, and every entity reporting battery level or
  > `unavailable`/offline. Produce a structured inventory doc + a candidate device-gap list. Output a
  > Markdown report; touch no files outside a new inventory doc draft."

- **`SA-01` + `SA-02` — Safety inventory + escalation design** (design/research) — ✅ dispatched & complete (`2026-06-30-sa-01-02-safety-alerts-design.md`):
  > "Read-only. Using HA-01's inventory, identify existing smoke/CO and water/leak sensors (or their
  > absence). Design alert + escalation flows separately for smoke/CO (life-safety) and water/leak
  > (property): triggers, severity, confirmation, delivery channels, and a mandatory disable/rollback
  > plan + false-pos/neg validation approach. No live changes; design doc only."

- **`AU-01` — Audio policy design** (design):
  > "Design the deterministic interaction-audio policy for the media zone: when/how to pause vs duck
  > vs ignore during a conversation, and how to resume. Depends on HA-01 (rooms/media-zone map);
  > note what multi-room/satellite behavior must wait on S0. Keep the resolver as sole media-TTS
  > owner; no second TTS path. Design doc only — no resolver/HA changes."

- **`RQ-03` — Music-source / Inc 3 decision** (research/decision):
  > "Read-only research. Summarize the trade-offs for the music-source direction (local-only vs
  > Tidal/Qobuz vs Soulseek vs reviving YTM), referencing the YTM playback-lock findings. Produce a
  > recommendation + decision record that unblocks MR-Inc3 (Lidarr/acquire). No implementation."

- **`P0` — PCL notes-only MVP** *(queued, not dispatched — stays Ready; do not start a 2nd stream)*.

---

## 12. Standard agent report format

Every track agent returns:

```
Track / item ID · branch · status change (old → new)
What changed (repo only) · tests (command + result)
Live actions taken (or "none — gated") · gate held? (y/n)
Shared files touched (§9) · rollback pointer
Next action · blockers
```

---

## 13. Change discipline

- Items move status only via their track PR; INF reconciles the **board (§2)** and **gate register (§10)** on merge.
- Keep doc / code / runtime-config commits **separate**; **secret-scan** first; **no Claude/AI attribution**.
- `BACKLOG.md` records *future work + operating model only* — current running state lives in
  `ONBOARDING.md` / `CHANGELOG.md`. Don't duplicate them here.
