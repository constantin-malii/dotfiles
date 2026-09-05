# SA-01 + SA-02 — Safety Sensor Inventory & Alert/Escalation Design

> Design/research only. No implementation. Source of running-state truth =
> ONBOARDING.md / CHANGELOG.md; sensor inventory input = HA-01
> (ha-device-inventory.md). Smoke/CO = life-safety (strictest); water/leak = property (strict).
>
> Track: SA (Safety / Alerts) · Items: SA-01 (smoke/CO), SA-02 (water/leak) · Type:
> research/design · Branch: `homebrain/sa-safety-alerts`. This doc designs the alert +
> escalation flows and the pre-exposure gate; it does **not** build them (that is SA-03 /
> SA-04, separate gated tracks). Live gate (BACKLOG §10) left **FREE** — this design does
> not claim it.

---

## 0. Scope & method

**What this IS:** a single, offline, design-only document that (1) confirms the current
smoke/CO and water/leak sensor inventory from HA-01, (2) designs — *separately* — the
trigger model, severity ladder, confirmation flow, delivery/escalation channels, FP/FN
validation approach, disable switch, and one-step disable/rollback for smoke/CO
(life-safety) and water/leak (property), (3) states the exact pre-exposure gate criteria
SA-03/SA-04 must satisfy, and (4) produces a purchase/device-gap list feeding RQ-05.

**What this is NOT:** not an implementation (no HA automation/script/helper, no
entity/exposure change, no siren/notification wiring, no code, no resolver change, no live
test); not a running-state narrative (that lives in ONBOARDING.md / CHANGELOG.md,
referenced here, never duplicated).

**Method — fully OFFLINE.** Unlike HA-01, this task performs **no** live HA / MA / host /
API access of any kind (no REST, no WS, no SSH, no token use). Every fact is sourced from
the merged HA-01 inventory (`ha-device-inventory.md`) plus the repo docs (ONBOARDING.md,
CHANGELOG.md, BACKLOG.md). Inventory input reconciled against HA-01 as merged on `main`
(commit history: HA-01 merged via PR #5). No "pending HA-01 merge" caveat applies.

**Gate:** design-only; does **NOT** claim the live-system gate (BACKLOG §10). Left **FREE**.

---

## 1. Current safety-sensor inventory (from HA-01)

Classification per HA-01 §8: **Present** / **Absent** (confirmed 0 entities in registry +
states) / **Unknown** (not queryable). HA-01 fully queried both categories — neither is
"unknown"; both are a confirmed, hard **Absent**.

| Category | Backlog item | Status | Evidence (HA-01) |
|---|---|---|---|
| Smoke / CO | SA-01 | **ABSENT** | §8: 0 `binary_sensor` with `device_class` smoke / carbon_monoxide / gas. All 71 registered `binary_sensor` are **disabled** mobile-app / add-on housekeeping entities (§2). |
| Water / leak | SA-02 | **ABSENT** | §8: 0 `binary_sensor` with `device_class` `moisture`; none in registry or live states. |
| Siren / audible alarm | (enabler) | **ABSENT** | §2: no `siren` entities exist (registry or live). |
| Alarm panel | (enabler) | **ABSENT** | §2: no `alarm_control_panel` entities exist. |
| Z-Wave / Zigbee radio | (enabler) | **ABSENT** | §6: 17 config entries; **no `zwave_js` / `zha` / `zigbee` / `matter` / `thread` integration** is present. There is no radio coordinator through which HA-native battery safety sensors could join today. |
| Non-phone battery devices | (supervision) | **ABSENT** | §7: the only 3 `device_class=battery` entities are the three phones; "No non-phone battery devices … absent, confirmed via `/api/states`." |

**Consequence.** Both alert systems are **hardware-contingent**: nothing to alert on exists
today. This document is therefore a **device-agnostic paper design plus a buy-list** — it
defines the trigger/severity/escalation/gate model that SA-03/SA-04 will implement *once the
sensors (and a radio coordinator) are purchased and installed*. A key second-order finding:
because **no Z-Wave/Zigbee coordinator exists** (row 5), a coordinator is a prerequisite
purchase gating *every* HA-native battery safety sensor (see §6).

---

## 2. Available alert/escalation surface today (constraints)

The delivery surface is the set of channels SA-03/SA-04 can *actually* reach. HA-01 + the
ONBOARDING notes bound it tightly.

**Channels that EXIST now:**

| Channel | Entity / mechanism | Reachability / caveat |
|---|---|---|
| Mobile push ×3 | `notify.sm_s948w_costea`, `notify.sm_s948w_vio`, `notify.huawei_costea_clt_l04` | HA Companion app push. Stateless (`unknown`) is normal (HA-01 §7). **Reliability caveat:** depends on each phone being online, charged, and having notifications un-throttled. HA-01 §7 battery snapshot: Costea 96%, Vio **29%**, Huawei **16%** — an overnight-dead or DND-silenced phone is a silent failure of this channel. |
| In-home audible (TTS) | `script.ceiling_announce` → `tts.speak` (Piper) → `media_player.ceiling_speakers` | The **only reliable audible channel** today. Works because the **host** fetches the NAT-IP (`192.168.122.10`) TTS URL (ONBOARDING §12). `script.ceiling_announce` is a kept-un-exposed HA primitive (HA-01 §3) — an automation may call it server-side without exposing it to the assistant. |
| Presence / routing | 2 persons (`costea`, `Vio`) + 3 `device_tracker` phones | Enables home/away routing (HA-01 §2). At snapshot all show `home`. |

**What is MISSING (must be honest about this):**

- **No siren / alarm panel** — no `siren`, no `alarm_control_panel` (HA-01 §2). HA cannot
  sound a dedicated alarm; the loudest thing it can do is speak over the ceiling speakers.
- **No HA-level room targeting** — the area map is effectively empty (only printer→Furnace;
  all media players area-unassigned; HA-01 §4). An alert cannot be routed "to the bedroom"
  at the HA layer. Announcements go to the single ceiling zone only.
- **Phone TTS is unreachable** — the pipeline Piper TTS is disabled and phone TTS URLs
  resolve to the NAT IP the phones cannot reach (ONBOARDING §6/§12). Phones get **push**,
  not spoken audio. So a spoken alert reaches only the ceiling zone.
- **Soundbar offline** — `media_player.samsung_soundbar_q930c` is `unavailable` (HA-01 §7):
  not a dependable audible channel. The Samsung TV is `idle` but not wired for announcements.

**Honest limitation (governs the whole SA-01 design).** *Ceiling-TTS + phone push is a WEAK
life-safety channel.* A sleeping household will not reliably wake to a spoken announcement
from one room's speakers, and push can be silenced/dead. Therefore **HA must not be the
primary life-safety alarm.** The primary alarm for smoke/CO must be the detectors' own
**interconnected physical sounder** (every detector sounds when any one trips); the HA path
is a *secondary* notification/telemetry layer. Closing the audible gap for a credible
HA-driven alarm requires **new hardware** (interconnected certified detectors, and
optionally a Z-Wave/Zigbee siren) — see §6.

---

## 3. SA-01 — Smoke/CO alert & escalation design (LIFE-SAFETY — STRICTEST)

**Posture:** life-safety. Bias hard toward alerting. Minimal-to-no suppression. A false
negative (a real fire/CO event not alerted) is **unacceptable**; a false positive is a
tolerable nuisance. HA is a *secondary* layer behind the physical interconnected sounder.

### 3.1 Sensor requirements & candidate devices

| Requirement | Design decision | Rationale |
|---|---|---|
| Detection type | **Combination smoke + CO** detectors (photoelectric smoke + electrochemical CO), sited per code (each sleeping area, each level, outside bedrooms; CO near sleeping areas / fuel appliances). | Covers both hazards; smoke and CO are **distinct signals** (§3.2). |
| Interconnected | **Yes — physically/RF interconnected** so any unit tripping sounds **all** units. | This is the *primary* life-safety alarm. HA reliability limits (§2) mean HA cannot be trusted as the sole audible alarm. |
| HA-native | Report to HA as `binary_sensor` `device_class: smoke` and `device_class: carbon_monoxide` (and `gas` if applicable). Prefer **Z-Wave (Z-Wave Plus)**; Zigbee acceptable. **Avoid cloud-only Wi-Fi** for life-safety (adds a cloud dependency in the alarm path). | Native `device_class` gives HA correct semantics + supervision (§3.2). Z-Wave/Zigbee gives local, mains-independent telemetry with supervision/heartbeat. |
| Power | **Mains-powered with battery backup**, or long-life sealed battery with mandatory low-battery reporting. | A detector that dies silently is a false-negative source. |
| Certification | Listed to the applicable standard (e.g. UL 217 smoke / UL 2034 CO or the Canadian equivalent, per the CA/Edmonton locale in HA-01 §1). | Life-safety devices must be certified; HA integration does not replace certification. |
| Coordinator | Requires a **Z-Wave/Zigbee coordinator** (ABSENT today — §1). | Prerequisite purchase; gates all HA-native detectors. |

### 3.2 Triggers & signals (what fires)

| Signal | Source | Treated as |
|---|---|---|
| **Smoke detected** | `binary_sensor.<x>_smoke` → `on` | CRITICAL (fire) — fire immediately. |
| **CO detected** | `binary_sensor.<x>_carbon_monoxide` → `on` | CRITICAL (CO) — fire immediately, with a **distinct message** ("Carbon monoxide detected" vs "Smoke detected"). CO is invisible/odourless → wording must not imply fire. |
| **Gas detected** (if a combustible-gas unit is added) | `binary_sensor.<x>_gas` → `on` | CRITICAL (gas). |
| **Low battery** | detector battery entity below threshold | FAULT (supervision) — high-priority notify, **not** the CRITICAL alarm. |
| **Offline / `unavailable`** | entity `unavailable` beyond a grace window | FAULT — **offline-as-fault**: a detector that stops reporting is treated as a supervision failure, never as "all clear". |
| **Tamper** | tamper attribute/entity (if supported) | FAULT. |
| **Heartbeat loss** | no state report within the expected heartbeat interval | FAULT — heartbeat-loss-as-fault (same treatment as offline). |

Principle: **absence of signal is a fault, not safety.** The supervision signals never
suppress; they raise their own FAULT alert so a degraded detector is fixed promptly.

### 3.3 Severity levels

| Level | Meaning | Behaviour |
|---|---|---|
| **CRITICAL (life-safety)** | Confirmed smoke / CO / gas. | **Immediate, non-suppressible.** All channels at once (§3.5); repeat until acked *or* the sensor clears. Cannot be debounced away or silenced by the assistant. |
| **FAULT (supervision)** | Low battery, offline, heartbeat loss, tamper. | High-priority push + persistent HA notification; **no** siren/ceiling blast. Escalates by *nagging* (daily until resolved), not by alarming. |
| **DISABLED (armed-state telemetry)** | The HA alert path is intentionally disabled (§3.7). | Not an alarm, but a **loud, visible state** — a persistent notification + logbook entry so a disabled life-safety path is never forgotten. |

### 3.4 Confirmation flow (LIFE-SAFETY POSTURE)

- **No suppression / no confirmation delay on the CRITICAL signal.** Smoke/CO fires the
  full escalation the instant the sensor reports `on`. The design deliberately declines any
  "wait N seconds to confirm" window for the primary hazard — **fail loud**.
- The only filtering permitted is a **≤1–2 s hardware de-bounce** to reject a single-frame
  state glitch (electrical noise), and only if it demonstrably does not delay a real trip.
  This is a glitch filter, **not** a confirmation window.
- **Acknowledgement** is a human action (an "Acknowledge" push action / a guarded input) that
  **stops the repeat cadence** for the current event. Ack does **not** disarm the system and
  does **not** suppress a *new* trip — if the sensor re-asserts or another unit trips, the
  ladder restarts. Auto-clear only when the sensor itself returns to `off`.
- Cross-check (defence in depth): the physical interconnected sounder is independent of HA,
  so even if the HA confirmation/ack logic misbehaves, the audible alarm still sounds.

### 3.5 Delivery channels & escalation ladder

Mapped **only** to channels that can exist (§2), plus the recommended hardware to close the
audible gap.

| Step | Timing | Action |
|---|---|---|
| **T0 (immediate)** | 0 s | (a) **Ceiling TTS** via `script.ceiling_announce` — max volume, explicit hazard wording ("Smoke detected" / "Carbon monoxide detected — leave the house"), looped. (b) **All 3 phones** push simultaneously, **CRITICAL priority** (Android high-importance channel; request DND-bypass / critical-alert delivery — capability to be verified, §8). (c) **Persistent HA notification** (dashboard/logbook). |
| **T0 (physical)** | 0 s | The detectors' **interconnected sounder** sounds independently of HA — this is the *primary* life-safety alarm; HA T0(a)–(c) is secondary. |
| **Repeat** | every ~20–30 s | Re-announce on ceiling + re-push until **acked** or the **sensor clears**. Non-suppressible by the assistant. |
| **Home/away routing** | at trigger | Read `device_tracker` / `person`. **Everyone away** → push still fires to all phones; ceiling TTS still fires (occupants unaware, pets, responders); (future) escalate to an off-site contact/neighbour — UNKNOWN today (§8). **Someone home** → ceiling TTS is the wake channel; keep pushing in case they're asleep. **Note:** away-routing must never *reduce* CRITICAL delivery — it only *adds* recipients. |
| **Recommended hardware** | — | A **certified interconnected detector set** (primary sounder) is mandatory before arming. Optionally add a **Z-Wave/Zigbee siren** so HA can drive a loud, dedicated alarm rather than relying on one room's speech (§6). |

### 3.6 False-positive / false-negative validation plan

**Bias: false negatives are unacceptable → bias to alerting.** All tests run with the alert
path **armed** (disable switch OFF), from a clean state.

| Test | Method | Pass criterion |
|---|---|---|
| Smoke trip → alert | Detector self-test button; canned smoke on one unit. | HA sees `binary_sensor…smoke=on`; ceiling TTS + all-phone push + persistent notification fire within seconds; interconnected sounder sounds. |
| CO trip → alert | CO self-test (or canned CO where safe). | Distinct CO wording fires (not fire wording); full ladder. |
| Per-unit coverage | Repeat for **every** detector. | Every unit independently reaches HA and triggers the automation (no "one wired, rest assumed"). |
| Offline-as-fault (FN guard) | Power-down / remove one detector. | Within the grace window HA raises a **FAULT** (not silence). Confirms a dead detector cannot masquerade as "all clear". |
| Low-battery / heartbeat | Simulate low battery / stop heartbeat. | FAULT notification fires. |
| Repeat/ack behaviour | Trigger, then ack. | Repeat stops on ack; a fresh trip restarts the ladder; auto-clears when sensor `off`. |
| No-suppression proof | Trigger while assistant is active/announcing. | CRITICAL still fires immediately; assistant cannot suppress it. |
| False-positive characterisation | Cooking steam / shower steam near a unit (expected nuisance). | Document nuisance rate; **do not** add a suppression delay to reduce it (accept FP over FN). Placement/type is the mitigation, not software suppression. |

### 3.7 Disable switch (design only)

- **Control:** a dedicated guarded helper (e.g. `input_boolean.sa_smoke_alert_disabled`, or a
  disabled automation). Default **armed** (alerting ON) at all times.
- **Deliberate:** disabling requires an explicit action — never a side effect of another flow.
- **Time-boxed with auto-re-arm:** a disable **auto-expires** after a short, bounded window
  (e.g. 15–30 min max for life-safety) and the system **re-arms itself**. There is no
  indefinite disable for a life-safety path.
- **Logged + loud:** every disable/re-arm writes a logbook entry, raises a **persistent
  notification**, and pushes all phones ("Smoke/CO alerting DISABLED until HH:MM"). A disabled
  life-safety path must be impossible to forget.
- **Scope:** disabling the **HA alert path** does **not** silence the detectors' physical
  interconnected sounder (independent) — the house is never left with zero protection.

### 3.8 One-step disable / rollback plan (mandatory SA-gate item)

- **One-step disable (instant mute of the HA path):** flip **one** documented control —
  `input_boolean.sa_smoke_alert_disabled → on` (or disable the single alert automation). This
  instantly stops the HA ceiling/push escalation. **The physical interconnected sounder is
  unaffected** (still protects the house). SA-03 must document the exact entity id.
- **Full rollback (remove SA-03 entirely):** disable + delete the alert automation(s), remove
  the SA helpers (`input_boolean`/timers), and un-expose anything exposed to `conversation`
  via `homeassistant/expose_entity`. Repo/doc side: `git revert` on the SA-03 branch. Net
  effect: HA returns to its pre-SA-03 state; detectors keep working stand-alone.
- **Rollback pointer must be pre-written** in SA-03 before arming (names the exact entities +
  the revert commit target).

### 3.9 Pre-exposure gate criteria (BACKLOG SA gate — life-safety tier)

SA-03 **MUST** satisfy **all** of the following *before* any exposure / before the alert path
is armed live (the four BACKLOG SA-gate items in bold):

1. **Disable switch** — the guarded, time-boxed, auto-re-arming, logged control (§3.7) exists
   and is verified.
2. **Tested FP/FN validation** — the §3.6 plan executed with evidence: every detector trips
   the alert; offline/low-battery raise FAULT; no suppression; documented FP characterisation.
3. **Confirmation flow** — the life-safety confirmation/ack model (§3.4) implemented: no
   suppression delay, ack stops repeat only, auto-clear on sensor `off`.
4. **Documented one-step disable / rollback** (§3.8) — written, with exact entity ids + revert
   pointer, before arming.

Plus life-safety-specific preconditions:

5. **Primary physical alarm installed** — certified interconnected detectors installed and
   their own sounder verified **before** the HA path is armed (HA is secondary, never the sole
   alarm).
6. **Critical-push capability confirmed** — verify the phones actually deliver
   CRITICAL/DND-bypass push (else the "wake a sleeping household" claim is false — §8).
7. **Single SA live gate** — SA-03 claims the one SA live/exposure gate **alone** (BACKLOG
   §8/§10); life-safety takes precedence over SA-04.

---

## 4. SA-02 — Water/leak alert & escalation design (PROPERTY — STRICT)

**Posture:** property protection, high but **not** life-safety. A false negative (a real leak
missed) is costly (water damage) but not life-threatening; a **short confirmation/debounce
window is acceptable** to filter transient false positives. Escalation is aggressive-but-not-
non-suppressible, and there is no "wake the whole house" mandate.

### 4.1 Sensor requirements & candidate devices

| Requirement | Design decision | Rationale |
|---|---|---|
| Sensor types | **Spot leak sensors** (point puck) **and** **rope/cable sensors** (linear, for runs). | Spot for a defined point (drain pan); rope to guard a length (behind a washer, along a wall). |
| Placement (priority) | **Furnace** area, **water heater** base/pan, **under each sink** (kitchen + bathrooms), **behind/under the washing machine** & dishwasher, and any **sump / floor drain** low point. | These are the high-probability, high-damage leak points. |
| HA-native | Report as `binary_sensor` `device_class: moisture`. Prefer **Z-Wave/Zigbee** (local, battery, supervised). | Correct semantics + supervision; same coordinator prerequisite as §3. |
| Power / battery | Battery, with **mandatory low-battery reporting** and **offline supervision**. | A dead leak sensor is a silent gap; supervise it (§4.2). |
| Coordinator | Same Z-Wave/Zigbee coordinator as §3 (ABSENT today — §1). | Shared prerequisite purchase. |
| Auto-shutoff valve | **FUTURE — note only, OUT OF SCOPE.** A Z-Wave valve actuator could auto-close the main on a confirmed leak. | Flagged for a later item; SA-02 does not design or build it. |

### 4.2 Triggers & signals

| Signal | Source | Treated as |
|---|---|---|
| **Moisture detected** | `binary_sensor.<x>_moisture` → `on`, sustained past the debounce (§4.4) | HIGH (leak). |
| **Low battery** | sensor battery entity below threshold | WARNING (supervision). |
| **Offline / `unavailable`** | entity `unavailable` beyond a grace window | WARNING — offline-as-fault (a leak sensor that stops reporting is a gap, not "dry"). |
| **Heartbeat loss** | no report within heartbeat interval | WARNING. |

### 4.3 Severity levels

| Level | Meaning | Behaviour |
|---|---|---|
| **HIGH (property)** | Confirmed sustained moisture. | Aggressive notify + in-home announce; repeat until acked; escalate if unacked. **Not** non-suppressible; **no** mandatory siren. |
| **WARNING (supervision)** | Low battery, offline, heartbeat loss. | Notify + persistent HA notification; nag until resolved. |
| **DISABLED** | HA leak alerting intentionally disabled (§4.7). | Persistent notification + logbook so the disabled state is visible. |

### 4.4 Confirmation flow (PROPERTY POSTURE)

- **A short confirmation / debounce window IS acceptable.** Require moisture to remain `on`
  for a brief sustained period (e.g. **~5–30 s**, tunable) or require **two consecutive
  readings** before raising HIGH. This filters transient false positives (a splash, momentary
  condensation) that would otherwise cry wolf.
- The window must stay **short** — property damage scales with time-to-detect, so the debounce
  trades a few seconds of latency for far fewer nuisance alerts. Bias still leans to alerting;
  the window only removes obvious transients.
- **Acknowledgement:** a push action / guarded input stops the repeat for the current event;
  auto-clears when the sensor returns to `off` (dry).
- **Auto-shutoff valve:** if/when added (future), a confirmed HIGH could trigger valve
  closure — **explicitly deferred**, noted only.

### 4.5 Delivery channels & escalation ladder

| Step | Timing | Action |
|---|---|---|
| **T0** | on confirmed HIGH | **All 3 phones** push (HIGH priority) with the location ("Leak detected: water heater"); **persistent HA notification**. If **someone home**, also **ceiling TTS** via `script.ceiling_announce`. |
| **Repeat / escalate** | if unacked after ~N min | Re-push (and re-announce if home). Property tier tolerates a minutes-scale cadence (vs seconds for smoke). |
| **Home/away routing** | at trigger | **Home** → push + ceiling TTS. **Away** → push only (no one to hear TTS); (future) off-site contact / valve auto-shutoff. Away never reduces push delivery. |
| **Hardware** | — | No dedicated siren required (property tier). Ceiling TTS + push suffice; a valve actuator is the future upgrade, not an alarm. |

### 4.6 False-positive / false-negative validation plan

**Bias: still favours alerting, but a short debounce is acceptable to cut false positives.**
Tests run with the path armed, from a clean state.

| Test | Method | Pass criterion |
|---|---|---|
| Leak trip → alert | Bridge the sensor probes with a **damp cloth / few drops of water**. | After the debounce window, HA raises HIGH; push (+ TTS if home) + persistent notification fire; location text correct. |
| Debounce behaviour | Momentary touch shorter than the window. | Transient does **not** raise HIGH (false-positive filtered). Sustained wet **does** raise HIGH (no false negative). |
| Per-sensor coverage | Repeat for **every** placed sensor. | Each independently reaches HA and triggers with its correct location label. |
| Offline-as-fault (FN guard) | Remove battery / power down one sensor. | WARNING raised within grace window (a silent sensor ≠ dry). |
| Low-battery / heartbeat | Simulate. | WARNING fires. |
| Ack / auto-clear | Trigger, ack, then dry the sensor. | Repeat stops on ack; state auto-clears when `off`. |

### 4.7 Disable switch (design only)

- **Control:** guarded helper (e.g. `input_boolean.sa_leak_alert_disabled`) / disabled
  automation. Default **armed**.
- **Deliberate + logged:** explicit action; logbook entry + persistent notification on
  disable and re-arm.
- **Auto-re-arm / time-boxed:** disable auto-expires and re-arms. Property tier may allow a
  **longer** window than smoke/CO (e.g. hours, for maintenance) — but still bounded and
  logged, never silent/indefinite.

### 4.8 One-step disable / rollback plan (mandatory SA-gate item)

- **One-step disable:** flip **one** documented control —
  `input_boolean.sa_leak_alert_disabled → on` (or disable the single leak automation) — instantly
  stops the HA leak escalation. SA-04 documents the exact entity id.
- **Full rollback:** disable + delete the leak automation(s), remove SA helpers, un-expose any
  exposed entity via `homeassistant/expose_entity`; `git revert` on the SA-04 branch. HA
  returns to pre-SA-04 state.
- Rollback pointer pre-written in SA-04 before arming.

### 4.9 Pre-exposure gate criteria (BACKLOG SA gate — property tier)

SA-04 **MUST** satisfy **all** of the following before any exposure / before arming live:

1. **Disable switch** (§4.7) — guarded, time-boxed, auto-re-arming, logged.
2. **Tested FP/FN validation** (§4.6) — executed with evidence: every sensor trips; debounce
   filters transients but not sustained leaks; offline/low-battery raise WARNING.
3. **Confirmation flow** (§4.4) — the short-debounce property model implemented and verified.
4. **Documented one-step disable / rollback** (§4.8) — written with exact entity ids + revert
   pointer before arming.

Plus:

5. **Sensors placed & reporting** — every intended location covered and confirmed in HA.
6. **Gate serialization** — SA-04 may hold the single SA live/exposure gate **only when SA-03
   is not holding it** (BACKLOG §10); SA-03 (life-safety) has precedence.

---

## 5. Why smoke/CO and water/leak are treated separately

The two are deliberately designed under **different risk postures**. Collapsing them into one
"safety alert" system would either over-alert on leaks or under-alert on fire.

| Dimension | SA-01 Smoke/CO (life-safety) | SA-02 Water/leak (property) |
|---|---|---|
| **What's at risk** | Human life. | Property / water damage. |
| **Latency tolerance** | ~Zero. Fire/CO fires immediately. | Seconds. A short debounce is fine. |
| **Confirmation strictness** | **Fail loud** — no confirmation delay; only a ≤1–2 s glitch filter. | **Confirm first** — ~5–30 s sustained / 2 readings before HIGH. |
| **Escalation aggressiveness** | Maximum: all channels at once, non-suppressible, repeat until acked/clear, **plus** an independent physical interconnected sounder (+ optional dedicated siren). | High-but-bounded: push (+TTS if home), minute-scale repeat, no mandatory siren. |
| **FP/FN bias** | FN **unacceptable** → tolerate false positives. Never add software suppression to cut nuisance. | FN costly but survivable → a **short** debounce to cut false positives is acceptable and desirable. |
| **Disable window** | Very short (≤15–30 min), always auto-re-arm; physical sounder unaffected. | Longer allowed (hours, for maintenance) but still bounded/logged. |
| **Primary alarm** | The **physical interconnected detector sounder** — HA is secondary. | HA push/TTS is sufficient; valve auto-shutoff is a future upgrade. |
| **Gate precedence** | Holds the single SA live gate **first** (BACKLOG §10). | Waits for the gate to be free. |

**Justification.** Life-safety optimises to **never miss** at the cost of occasional nuisance
and refuses to trust a single soft channel. Property protection optimises to **detect fast
without crying wolf**, so a brief confirmation window is a feature, not a weakness. Different
objective functions → two designs.

---

## 6. Purchase / device-gap list (feeds RQ-05)

No specific SKUs are mandated; the **selection criteria** are the deliverable. Categories:

**A. Radio coordinator (foundational prerequisite — gates everything below).**
- **Need:** a **Z-Wave** or **Zigbee** coordinator (USB stick or equivalent) — none exists
  today (HA-01 §6: no `zwave_js`/`zha`). Without it, no HA-native battery safety sensor can
  join.
- **Criteria:** HA-supported (`zwave_js` / `zha` / Matter-Thread); local (no cloud); matches
  the chosen sensor radio; good range/mesh support for the detector locations.

**B. Smoke/CO detectors (SA-01 — life-safety).**
- **Criteria:** combination **smoke + CO** (photoelectric + electrochemical); **interconnected**
  (any-unit-trips-all physical sounder); reports to HA as `device_class` **smoke** +
  **carbon_monoxide** (+ `gas` if combined); **mains + battery backup** (or sealed long-life
  with low-battery reporting); **supervision** — low-battery, tamper, and heartbeat/offline
  reporting; **certified** to the applicable UL/CAN standard for the CA locale; **local radio**
  (Z-Wave/Zigbee) — **avoid cloud-only Wi-Fi** in the life-safety path. Quantity: one per
  sleeping area + per level + outside bedrooms, per code.

**C. Water/leak sensors (SA-02 — property).**
- **Criteria:** `device_class` **moisture**; **spot** pucks **and** **rope/cable** sensors as
  the location dictates; battery with **low-battery reporting** and **offline supervision**;
  long battery life; local radio (Z-Wave/Zigbee). Quantity: one per §4.1 location (furnace,
  water heater, each sink, washer, dishwasher, sump).
- **Future (note only):** a **Z-Wave/Zigbee auto-shutoff valve actuator** for the main — a
  later item, not part of SA-02/SA-04.

**D. Siren / alarm hardware (to make life-safety escalation credible).**
- **Finding:** today HA's loudest output is one room's ceiling TTS (§2) — inadequate as a
  life-safety alarm.
- **Criteria:** the **interconnected detector sounders (category B) are the primary alarm** and
  are mandatory. Optionally add a **Z-Wave/Zigbee siren** so HA can drive a loud, whole-home
  audible alarm independent of the ceiling speakers. Ceiling TTS is **not** a substitute for a
  certified alarm.

**Sequencing:** A → (B, C) → optional D. Because sensors are absent, **RQ-05 buy-list precedes
SA-03/SA-04 implementation** — the impl tracks are purchase-gated.

---

## 7. How this feeds SA-03 and SA-04

| Design section | Implemented by | Must satisfy before exposure |
|---|---|---|
| §3.1–§3.5 smoke/CO sensors, triggers, severity, confirmation, escalation | **SA-03** (smoke/CO alerting + escalation, life-safety, strictest) | — |
| §3.6–§3.9 FP/FN validation, disable switch, one-step disable/rollback, gate | **SA-03** | **All of §3.9** (the four SA-gate items + primary sounder installed + critical-push confirmed) **before any exposure** |
| §4.1–§4.5 water/leak sensors, triggers, severity, confirmation, escalation | **SA-04** (water/leak alerting + escalation, property, strict) | — |
| §4.6–§4.9 FP/FN validation, disable switch, one-step disable/rollback, gate | **SA-04** | **All of §4.9** before any exposure |

**Restated gates.** Both SA-03 and SA-04 must, before exposure, present: a **disable switch**,
**tested FP/FN validation**, a **confirmation flow**, and a **documented one-step
disable/rollback** (BACKLOG SA gate, §8). SA-03 additionally requires the physical
interconnected sounder installed and critical-push confirmed (life-safety preconditions).

**Purchase gate.** Both are **purchase-gated first** — no sensors (and no radio coordinator)
exist (§1). RQ-05's buy-list (§6) precedes implementation.

**Live-gate / exposure serialization (BACKLOG §8/§10).** At most **one** SA live/exposure gate
is active at a time. **SA-03 (life-safety) takes precedence** and holds it alone; SA-04
proceeds only when the gate is free. This design claims **no** gate — it leaves BACKLOG §10
**FREE**.

---

## 8. Open questions / assumptions / TODO

Distinguishing **absent** (confirmed 0 via HA-01) from **unknown** (not yet determined).

- `TODO:` **Radio coordinator choice** — Z-Wave vs Zigbee vs Matter/Thread. **ABSENT** today
  (HA-01 §6 confirms no coordinator integration). Decision needed in RQ-05; it constrains
  sensor selection.
- `TODO:` **Critical-push capability** — **UNKNOWN**. Whether the HA Companion app on these
  phones can deliver CRITICAL / DND-bypass / high-importance push (esp. overnight) is not
  verified. The "wake a sleeping household" claim in §3.5 depends on it. Verify per-phone
  before SA-03 arms; if unsupported, the physical sounder + a dedicated siren carry the
  life-safety load.
- `TODO:` **Phone reliability** — push depends on phones being online/charged (HA-01 §7: Vio
  29%, Huawei 16% at snapshot). A dead/silenced phone is a silent channel failure — do not
  count any single phone as a guaranteed life-safety path.
- `TODO:` **No HA room map** — the area registry is near-empty (HA-01 §4). Sensor→area
  assignment must be populated at install so alerts can carry a meaningful location label
  (esp. leak location text in §4.5). Depends on the HA-01/area-map gap being closed.
- `TODO:` **Dedicated HA siren?** — decide whether to buy a Z-Wave/Zigbee siren (§6D) or rely
  solely on interconnected detector sounders for the audible alarm. Recommended: buy one for a
  credible HA-driven whole-home alarm.
- `TODO:` **Off-site / away escalation** — **UNKNOWN**. There is no designed path to reach an
  off-site contact/neighbour when everyone is away. Decide whether to add one (e.g. a
  notify-to-contact, or future integration).
- `TODO:` **Auto-shutoff valve (water)** — **future, out of scope**. Decide later whether to
  add a Z-Wave valve actuator and let a confirmed HIGH leak close the main.
- `TODO:` **CO → HVAC/furnace shutoff** — **ABSENT as control**. The ecobee exists only as a MA
  `media_player` (HA-01 §8: no `climate` entity), so HA cannot cut the furnace on a CO event.
  Future item if thermostat control is added.
- **Assumption:** SA-03/SA-04 will implement the alert logic as **HA automations** that call
  `notify.*` and `script.ceiling_announce` **server-side** — these fire without exposing the
  entities to the `conversation` assistant. "Exposure" in the SA gate therefore means *arming
  the alert path live* (and exposing any user-facing helper), not conversation-tool exposure.
- **Assumption:** the CA/Edmonton locale (HA-01 §1) governs the applicable smoke/CO
  certification standard; confirm exact standard at purchase.

---

## 9. Downstream feeds / dependencies

| Downstream | Consumes from this design | Headline |
|---|---|---|
| **SA-03** smoke/CO alerting (impl) | §3 (all), §7 | Implements the life-safety alert path; must pass §3.9 before exposure; holds the single SA live gate first. |
| **SA-04** water/leak alerting (impl) | §4 (all), §7 | Implements the property alert path; must pass §4.9; waits for the gate. |
| **SA-05** security alerts / camera person-detection | §2 (surface), §3.5/§4.5 (escalation model), §5 (tiering) | Reuses the delivery surface + severity/escalation pattern; adds privacy tier (depends on HA-04 cameras). |
| **RQ-05** device purchasing list | §6 | Consumes the coordinator + smoke/CO + water/leak + siren criteria; sequences the buys; gates SA-03/SA-04. |
| **DV-02** "what needs attention?" household status | §3.2/§4.2 supervision signals | The FAULT/WARNING (low-battery, offline, heartbeat) telemetry feeds the needs-attention read-model. |
| **HA-01 / area map** | §2, §8 | Dependency: the empty area map (HA-01 §4) must be populated at install for room-aware alert labelling. |

---

> **End of SA-01 + SA-02 design.** Design-only; no HA/host access occurred; live gate left
> FREE. Rollback for this document: `git revert` on `homebrain/sa-safety-alerts`, or delete
> this file. No secrets, no implementation, no exposure.
