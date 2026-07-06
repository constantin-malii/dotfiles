# HA-06 — Device Health / Battery / Offline Read-Model Design (read-only)

> **Design / research only. No implementation, no resolver/HA change, no exposure, no live gate.**
> Designs the reusable **device-health read-model** — the *supplier* of health signals (battery,
> offline, staleness, updates, backup) that **DV-02** ("what needs attention?") and other consumers read.
> This doc defines the **data model + detection rules**; DV-02 owns *presentation/ranking*. Inputs:
> `ha-device-inventory.md` (HA-01 §7 health data), DV-01/02 design (the consumer), SA-01/02 (the strict
> safety-supervision overlap), ONBOARDING.
>
> Track: **HA** · Item: **HA-06** (`design→repo-code`, P2) · Branch: `homebrain/ha-06-device-health-readmodel`.
> Live gate (BACKLOG §10) left **FREE**.

---

## 1. Scope & relationship to DV-02 / SA

- **HA-06 = the supplier.** A read-only model that turns raw HA entity state into per-entity **health
  records** (battery/offline/stale/update). Reusable; no presentation, no control.
- **DV-02 = the consumer/presenter.** It ranks HA-06 records into a "needs attention" answer (DV-01/02
  design §4). HA-06 defines *what a health signal is*; DV-02 defines *how it's spoken*.
- **SA supervision is separate and stricter.** Smoke/CO/leak low-battery/offline/heartbeat live in the
  **life-safety** SA path (SA-01 §3.2, SA-02 §4.2) with non-suppressible FAULT semantics. HA-06 is the
  **general/property** health model; it may *also* observe safety-sensor batteries once they exist, but
  the **authoritative safety FAULT path stays in SA** — HA-06 never downgrades or masks an SA signal.

## 2. Health record (the data model)

Each observed entity maps to a health record:

```
{ entity_id, kind, status, severity, value?, since?, observable }
```
- **kind:** `battery` | `availability` | `staleness` | `update` | `backup`.
- **status:** `ok` | `low` | `critical` | `offline` | `stale` | `update_available` | `unknown_expected`.
- **severity:** `info` | `attention` | `high` (safety-supervision, when present) | `none`.
- **observable:** `true` for real signals; `false` where a category has **no** entities (Present/Absent/
  Unknown honesty — §5).

## 3. Signal-detection rules

Derived from HA-01 §7 (the live surface today):

| Signal | Detection rule | Today's data (HA-01 §7) |
|---|---|---|
| **Battery** | `device_class=battery` numeric %; `low` < `warn_pct`, `critical` < `crit_pct` (config, §4) | 3 phones: Costea 96 % (ok), Vio 29 % (low), Huawei 16 % (low/critical by threshold). **No non-phone batteries yet.** |
| **Availability / offline** | entity `unavailable` **that is expected to carry state** → `offline` | `media_player.samsung_soundbar_q930c` = unavailable → the **one real fault today** (+ its child button). |
| **Stateless-`unknown` (exclude)** | entity whose `unknown` is normal (notify/stt/MA "favorite" buttons) → `unknown_expected`, **severity none** | notify×3, `stt.faster_whisper`, 4 MA favorite buttons → **never** flagged as faults (HA-01 §7). |
| **Staleness / heartbeat** | `last_updated` older than an expected cadence (per-kind) → `stale` | Not actionable today (no periodic sensors that warrant it); designed for future Z-Wave sensors. |
| **Update available** | `update` entity `state=on` | 9 `update` entities (Core/OS/Supervisor/add-ons) → `info`. |
| **Backup health** | backup `sensor`s + `event.backup_automatic_backup` → `stale`/`failed` if last run old/failed | backup manager entities present (HA-01 §2). |

**Core rule — offline-as-fault, absence-as-unobservable:** an entity that *should* report but is
`unavailable` is `offline` (attention); a category with **no entities** is `observable:false` (report
"can't see", never "healthy"). Legitimately-stateless entities are `unknown_expected` (never a fault).

## 4. Thresholds & config (config-driven)

`battery_warn_pct` (e.g. 30), `battery_crit_pct` (e.g. 15), per-kind `staleness_max`, `backup_stale_days`,
and an **exclusion list** for legitimately-stateless entity patterns (notify/stt/MA buttons). All live in
`config.json` (resolver's config-driven design) — thresholds tunable without code.

## 5. Honest reporting (shared with DV / SA)

Same Present/Absent/Unknown discipline: HA-06 reports only observable health; a category with no entities
is explicitly **not observable**, never "healthy". This is what lets DV-02 answer *"nothing needs
attention"* truthfully — it means "nothing **observable** needs attention", and HA-06 carries the
`observable` flags so DV-02 can qualify that honestly.

## 6. Delivery & consumers

- **Implementation (later, gated):** a resolver read function producing health records from a fresh HA
  read (like `status`), read-only. Optionally surfaced as its own "device health" query via the
  `media_status`/F1-R hard-return pattern — **exposure gated**, not in this design.
- **Consumers:** **DV-02** (ranked needs-attention), a future "is everything OK?" query, and DV-01
  (to report e.g. "soundbar offline"). SA keeps its own strict supervision path.

## 7. Dependencies & scope notes

- **HA-01** ✅ — the inventory + §7 health snapshot (the data surface). Done.
- **Thin today, built to grow:** the only genuine fault today is the offline soundbar; batteries are
  phones-only. HA-06's value grows sharply once battery-powered Z-Wave sensors (SA smoke/CO/leak, HA-02+
  devices) exist — it becomes the supervision backbone for **property**-tier health while SA owns
  **life-safety**.
- **No room-scoping** until the area map is populated (HA-01 §4) — health is reported per-entity/house-wide.

## 8. What this document does NOT do

- **No implementation** — no resolver/HA change, no `config.json` edit, no script.
- **No exposure**, **no control**, **no live gate** — read-model design only; BACKLOG §10 left **FREE**.
- **No live HA read for this doc** — derived from the merged HA-01 inventory (offline).
- **Does not alter the SA safety-supervision path** — SA remains the authoritative life-safety FAULT owner.
- **No BACKLOG status change beyond a next-action note** (INF-owned board, §9).

---

> **Rollback for this document:** `git revert` on `homebrain/ha-06-device-health-readmodel`, or delete
> this file. No secrets, no implementation, no exposure, no live gate.
