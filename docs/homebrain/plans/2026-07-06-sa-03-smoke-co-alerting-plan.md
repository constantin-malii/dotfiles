# SA-03 — Smoke/CO Alerting Implementation Plan (life-safety, strictest)

> **Plan / design only. No implementation, no HA/host change, no exposure, no live gate claimed.**
> This operationalizes the SA-01 design (`2026-06-30-sa-01-02-safety-alerts-design.md` §3) into a
> concrete, phased build for the **owned** hardware, and turns the SA-01 §3.9 gate into an execution
> checklist. Building/arming any of this is a separate, **approval-gated** step that claims the single
> SA live/exposure gate (BACKLOG §8/§10, currently FREE).
>
> Track: **SA** · Item: **SA-03** (`design→HA-live`, life-safety strictest) · Locale: CA / Edmonton.
> Prereqs read: SA-01/02 design, RQ-06 decision (+ §12 addendum), HA-07 §4.1/§5.1, ONBOARDING, HA-01.

---

## 1. Where SA-03 sits (dependencies)

| Dependency | State (2026-07-06) |
|---|---|
| **SA-01 design** (trigger/severity/confirmation/escalation/gate) | ✅ done — this plan implements §3. |
| **Z-Wave coordinator** (RQ-06) | **Decided: HA Connect ZWA-2; on order.** Not yet live. Gates all HA-native detector telemetry. |
| **Coordinator live-enablement** | Path A (USB passthrough) preferred — see `runbooks/zwave-coordinator-enablement-path-a.md`. Approval-gated. |
| **ZEN55 wired to the SC7010BA** (Q3) | **OPEN** — must confirm the owned Zooz ZEN55 LR is wired to the First Alert SC7010BA interconnect (SA-01 telemetry depends on it). |
| **Critical-push capability** (SA-01 §8) | **UNKNOWN** — must verify the phones deliver CRITICAL/DND-bypass push before relying on "wake the household". |
| **Area/floor map** (HA-01 §4) | Near-empty; smoke signal is house-wide (HA-07 §5.1), so room labelling is a nice-to-have, not a blocker for smoke/CO. |

**Owned hardware maps cleanly onto the SA-01 design:**
- **Primary physical alarm = the First Alert SC7010BA** (hardwired, interconnected smoke/CO). This
  satisfies SA-01 §3.9 precondition #5 (*primary sounder installed*) — HA is the **secondary** layer,
  exactly as SA-01 mandates. Contingent on the detector being installed/wired (Q3).
- **HA telemetry bridge = Zooz ZEN55 LR**, reading the SC7010BA interconnect line non-invasively and
  exposing to Z-Wave JS (HA-07 §5.1): `binary_sensor` **`device_class: smoke`** + **`carbon_monoxide`**
  (distinct signals, per SA-01 §3.2), mains-powered (no battery entity), plus a **relay endpoint**
  (available for a future local siren — SA-01 §6D, out of scope here).

---

## 2. Phased build (each phase gated; nothing armed until Phase 4 passes)

### Phase 0 — Prep now (no device, no live change, no gate)
Everything here is design/authoring only and can be done while the coordinator ships:
- Finalize **helper + entity ids**: `input_boolean.sa_smoke_alert_disabled` (disable switch), the alert
  automation id(s), the ack `input_button`/push-action id, the FAULT nag automation id.
- Draft the **alert messages** verbatim (distinct smoke vs CO wording, SA-01 §3.2/§3.5): e.g.
  *"Smoke detected — leave the house"* vs *"Carbon monoxide detected — leave the house and get fresh air"*.
- Pre-write the **one-step disable / rollback pointer** (SA-01 §3.8): exact entity ids + the revert
  commit target — required to exist *before* arming.
- Draft the **area/floor labels** (HA-01 §4 gap) so any location text is meaningful (house-wide for smoke).

### Phase 1 — Coordinator live + ZEN55 paired (gated; needs the device)
- Enable the ZWA-2 live via the **Path A runbook** (approval-gated; claims the live gate).
- Pair the ZEN55; confirm it appears in Z-Wave JS and exposes the **two `binary_sensor`s** with the
  correct `device_class` (smoke + carbon_monoxide) and the relay endpoint. Confirm Q3 (wired) in reality.

### Phase 2 — Build the alert path (repo/HA authoring; arm later)
Implement SA-01 §3 as **server-side HA automations** (fire `notify.*` + `script.ceiling_announce`
directly — no `conversation` exposure needed; SA-01 §8 assumption):
- **CRITICAL (smoke/CO `on`)** — immediate, non-suppressible (SA-01 §3.4): ceiling TTS (max volume,
  looped, hazard-specific wording) + **all 3 phones** critical push + persistent HA notification;
  **repeat every ~20–30 s** until acked or the sensor clears. Only a ≤1–2 s glitch de-bounce, no
  confirmation delay.
- **Ack** = human action that stops the repeat for the current event only; does **not** disarm; a new
  trip restarts the ladder; auto-clear when the sensor returns to `off`.
- **FAULT (supervision)** — offline/`unavailable` beyond grace, low-battery, heartbeat loss, tamper →
  high-priority push + persistent notification, **nag** (not the CRITICAL blast). *Absence of signal is
  a fault, never "all clear"* (SA-01 §3.2).
- **Disable switch** — `input_boolean.sa_smoke_alert_disabled`, default **armed**, **time-boxed
  auto-re-arm** (≤15–30 min), every disable/re-arm logged + persistent notification + all-phone push
  (SA-01 §3.7). Disabling the HA path never silences the SC7010BA sounder.

### Phase 3 — FP/FN validation (SA-01 §3.6, from a clean armed state)
Execute and capture evidence for each: smoke trip → full ladder; CO trip → distinct CO wording;
**per-unit** coverage; **offline-as-fault** (power down a detector → FAULT, not silence); low-battery /
heartbeat → FAULT; ack stops repeat / new trip restarts / auto-clear on `off`; **no-suppression proof**
(trigger while the assistant is active); FP characterisation (cooking/shower steam — document, do **not**
add suppression).

### Phase 4 — Gate review → arm live
Verify **all** SA-01 §3.9 items (below) pass with evidence, then arm. SA-03 holds the **single** SA live
gate alone (life-safety precedence over SA-04).

---

## 3. SA-01 §3.9 gate — execution checklist (all mandatory before arming)

| # | Gate item | Concrete deliverable | Verified? |
|---|---|---|---|
| 1 | **Disable switch** | `input_boolean.sa_smoke_alert_disabled`, guarded, time-boxed, auto-re-arm, logged (Phase 2). | ☐ |
| 2 | **Tested FP/FN validation** | Phase 3 evidence: every unit trips; offline/low-batt → FAULT; no suppression; FP documented. | ☐ |
| 3 | **Confirmation flow** | Life-safety model: no suppression delay; ack stops repeat only; auto-clear on sensor `off`. | ☐ |
| 4 | **One-step disable / rollback** | Written pre-arm: exact entity ids + revert pointer (SA-01 §3.8). | ☐ |
| 5 | **Primary physical alarm installed** | SC7010BA installed + interconnected sounder verified (independent of HA). | ☐ |
| 6 | **Critical-push confirmed** | Each phone verified to deliver CRITICAL/DND-bypass push (SA-01 §8 TODO). | ☐ |
| 7 | **Single SA live gate** | SA-03 claims the one SA gate alone (BACKLOG §10); life-safety precedence. | ☐ |

## 4. Open items to resolve before/at arming

- **Q3 — ZEN55 wired?** Confirm the ZEN55 is wired to the SC7010BA interconnect (still boxed ⇒ no smoke
  telemetry regardless of coordinator).
- **Critical-push (§6)** — verify per phone; if unsupported, the SC7010BA sounder (and an optional
  Z-Wave siren via the ZEN55 relay or a dedicated unit) carries the audible load.
- **Off-site / away escalation** — no designed path today (SA-01 §8); decide whether to add one.
- **Optional dedicated siren** — decide whether to drive a loud whole-home alarm (ZEN55 relay endpoint
  or a Z-Wave siren) beyond ceiling TTS.

## 5. Live gate + rollback

- **Live gate:** Phases 1–2 (enablement) and Phase 4 (arming) are **HA-live / exposure** actions →
  claim the single gate (BACKLOG §10) under explicit approval; release on completion. This **plan doc**
  claims **no** gate.
- **Rollback:** one-step disable = `input_boolean.sa_smoke_alert_disabled → on` (SC7010BA unaffected).
  Full removal = delete SA-03 automations/helpers, un-expose any helper, `git revert` on the SA-03
  branch → HA returns to pre-SA-03 state; the detector keeps working stand-alone.

> Rollback for this document: `git revert` on its branch, or delete the file. No secrets, no
> implementation, no exposure, no live gate.
