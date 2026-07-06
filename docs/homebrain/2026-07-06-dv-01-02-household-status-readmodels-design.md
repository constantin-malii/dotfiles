# DV-01 + DV-02 — Household Status Read-Models Design (read-only)

> **Design / research only. No implementation, no resolver/HA change, no exposure, no live gate.**
> Designs two **read-only** household read-models: **DV-01** "what's on / running / open?" (current
> status) and **DV-02** "what needs attention?" (health / faults / supervision). Both are *observers* —
> they read HA state and report; they never control anything. Inputs: `ha-device-inventory.md` (HA-01, the
> read surface), SA-01/02 design (supervision signals), ONBOARDING §4/§7, `2026-06-29-inc4a-...` (the
> `media_status` / F1-R hard-return precedent), BACKLOG.
>
> Track: **DV** · Items: **DV-01**, **DV-02** (`design`, P2) · Branch: `homebrain/dv-01-02-status-readmodels`.
> Live gate (BACKLOG §10) left **FREE**.

---

## 1. Scope

- **DV-01 — current status:** answer "what's playing / on / running / who's home / what's the weather".
- **DV-02 — needs attention:** answer "what's wrong / low / offline / stale / needs an update".
- **Both read-only.** No control, no state change; they compose over HA state the resolver already reads.
- **Out of scope:** DV-03 (Lovelace dashboards, HA-live), DV-04 (energy — no metering hardware), any
  control action (that's HA-02/03/NL-01), room-scoped status (needs the area map — §6).

## 2. The honest-reporting principle (backbone)

Mirroring HA-01's **Present / Absent / Unknown** discipline and the project's "honest speaker" value: a
read-model must **only report what is genuinely observable** and must **distinguish "nothing to report"
from "cannot observe."**

- ✅ *"Music is playing on the ceiling; everyone's home; it's 3 °C and clear."*
- ✅ *"I can't see doors or windows — there are no door/window sensors."* (Absent → say so.)
- ❌ **Never** *"All doors are closed"* when no door sensors exist. Absence of a sensor is **not** "all
  clear" (same rule SA-01 §3.2 applies to safety). Fabricated reassurance is the failure mode to prevent.

Every reportable fact carries a provenance: a real entity state, or an explicit "not observable."

## 3. DV-01 — current-status read surface (today vs future)

Derived from HA-01 §2/§7. **Today's honest surface is thin** and grows only as device categories arrive.

| Facet | Observable today? | Source | Notes |
|---|---|---|---|
| **Now-playing (ceiling)** | ✅ | `media_player.ceiling_speakers` | Already served by `script.media_status` — DV-01 reuses it, doesn't duplicate. |
| **TV / other media** | ⚠ partial | `media_player.samsung_q82ca_75` (idle/playing), soundbar (**unavailable**) | Report state honestly incl. "soundbar offline". |
| **Presence (who's home)** | ✅ | 2 `person` + 3 `device_tracker` | home/away per person. |
| **Weather** | ✅ | `weather.forecast_home` (already exposed) | Temp/condition/forecast. |
| **Sun / daylight** | ✅ | `sun.sun` | above/below horizon, next event. |
| **Printer** | ✅ (niche) | printer `sensor` | rarely asked; include on request. |
| **Shopping list** | ✅ | `todo.shopping_list` | count/items. |
| **Doors / windows "open"** | ❌ **Absent** | — | No `cover`/door `binary_sensor` (HA-01 §8) → **must say "not observable"**. |
| **Lights / plugs "on"** | ❌ **Absent** | — | No `light`/physical `switch` (HA-01 §8) → grows with HA-02. |
| **Thermostat / temp** | ❌ **Absent as climate** | — | ecobee is only a MA `media_player`, **no `climate`** (HA-01 §8). |

**Design consequence:** DV-01 is a **composable summary** whose honest answer today is essentially
*media + presence + weather*, explicitly flagging the large "not observable" set. It is built to **grow**:
each future category (HA-02 plugs, HA-04 cameras, a `cover`/`climate`) registers as a new facet.

## 4. DV-02 — needs-attention read surface

Aggregates **supervision / health** signals into a ranked "attention" list. Consumes the **HA-06**
device-health read-model (its formal supplier) plus other observable health facets.

| Signal | Observable today? | Source | Severity |
|---|---|---|---|
| **Device offline / `unavailable`** | ✅ | e.g. `media_player.samsung_soundbar_q930c` = unavailable (HA-01 §7 — the one real fault today) | attention |
| **Low battery** | ✅ | 3 phone batteries (Vio 29 %, Huawei 16 % at snapshot) | info→attention by threshold |
| **Updates available** | ✅ | 9 `update` entities (Core/OS/Supervisor/add-ons) | info |
| **Backup status / staleness** | ✅ | backup `sensor`s + `event.backup_automatic_backup` | attention if stale/failed |
| **Safety-sensor FAULT/WARNING** | ⏳ future | SA-01/02 supervision (smoke/CO/leak offline, low-batt, heartbeat) | **high** when present (life-safety/property) |
| **Stateless "unknown" entities** | ✅ (filter out) | `notify`/`stt`/MA favorite buttons | **not** faults — exclude (HA-01 §7) |

**Design rules:**
- **Rank by severity**, safety-supervision (future) at the top, then genuine faults (offline), then
  low-battery/backup, then info (updates).
- **Suppress non-faults:** stateless `unknown` (notify/stt/MA buttons) are normal — never list them
  (HA-01 §7 explicitly separates these from the one real fault).
- **Offline-as-fault:** an entity that *should* report but is `unavailable` is attention-worthy, not
  "fine" (same principle as SA supervision).
- **Empty is a valid, honest answer:** *"Nothing needs attention"* — but only after actually checking the
  observable set, and it must not imply unobservable things are fine.

## 5. Delivery (how it's surfaced) — reuse the proven pattern

- Implement each as a **resolver read capability** returning a `CommandResult` with `chat_text`, surfaced
  to ChatGPT as a **hard tool return** via `stop` + `response_variable` — exactly the **`script.media_status`
  / F1-R** pattern (`2026-06-29-inc4a-...`; ONBOARDING). **Read-only, silent** (no TTS unless the user
  asks it aloud), no `set_conversation_response`.
- Reads via the resolver's existing HA REST/WS access (fresh per call, like `status`), not the shared
  event socket. No new HA entities required beyond the (gated) exposed script.
- **Exposure is gated** (shared conversation surface) — not part of this design; a later, approval-gated
  step, one script each, like `media_status`/`news`.

## 6. Dependencies & the area-map gap

- **HA-01** ✅ — the inventory (the read surface). Done.
- **HA-06** — the device-health read-model that DV-02 leans on for battery/offline/health. DV-02 defines
  the signals it needs (offline, low-batt, update, backup); **HA-06 formalizes the reusable model** — build
  HA-06 alongside/before DV-02's impl.
- **SA-01/02 supervision** — feeds DV-02's top-severity band once smoke/CO/leak sensors exist (SA design §9).
- **Area map gap (HA-01 §4):** only 1 of 23 devices is area-assigned; media players are unassigned. So
  **room-scoped status** ("what's on upstairs?") is **not** possible until areas/floors are populated —
  DV reports **house-wide** until then. (Same gap SA-01 §8 and AU-01 §8 flag.)

## 7. How this feeds downstream

| Design | Implemented by / consumed by |
|---|---|
| DV-01 current-status capability | resolver read capability (gated exposure); reuses `media_status` |
| DV-02 needs-attention capability | resolver read capability consuming **HA-06** + (future) SA supervision |
| Ranking / honest-reporting rules | both impls |
| Room-scoping | blocked on area-map population (HA-01 §4) |

## 8. What this document does NOT do

- **No implementation** — no resolver capability built, no `config.json`/script/HA change.
- **No exposure** — nothing exposed to `conversation`; gpt-4o-mini unchanged.
- **No control** — DV read-models are read-only observers; control stays with HA-02/03/NL-01.
- **No live gate** — design-only; BACKLOG §10 left **FREE**.
- **No BACKLOG status change beyond a next-action note** (INF-owned board, §9).
- **No live HA read performed for this doc** — surface derived from the merged HA-01 inventory (offline).

---

> **Rollback for this document:** `git revert` on `homebrain/dv-01-02-status-readmodels`, or delete this
> file. No secrets, no implementation, no exposure, no live gate.
