# RQ-06 — Z-Wave Coordinator Adoption Decision

> **Decision record / research only. No implementation, no purchase, no live-system change.**
> Formalizes the provisional "adopt Z-Wave" position already reached in HA-07
> (`device-integration-architecture-roadmap.md` §4.7, §13.b) into a standalone decision, verified
> against current **official Home Assistant Z-Wave guidance** (accessed 2026-07-01). Inputs: HA-07,
> SA-01/02 (`2026-06-30-sa-01-02-safety-alerts-design.md`), HA-01 (`ha-device-inventory.md`),
> ONBOARDING.md, `haos-vm-deployment.md`, CHANGELOG.md, BACKLOG.md.
>
> Track: **RQ** · Item: **RQ-06** (`research → device-purchase`) · Branch:
> `homebrain/rq-06-zwave-coordinator-decision` · Locale: **CA / Edmonton (120 V)**. Live gate
> (BACKLOG §10) left **FREE** — this doc claims no gate and changes nothing live.
>
> **This decision does not contradict SA-01/02 or HA-07.** It confirms their coordinator prerequisite
> with current sourced guidance and names a single recommended controller + runner-up. Sources are
> cited inline (HA docs first); community/vendor facts are marked with confidence.

---

## 1. Context — why now

Home Assistant has **no radio coordinator today** (HA-01 §6: 17 config entries, none of them
`zwave_js`/`zha`/`matter`/`thread`; CHANGELOG confirms "no coordinator"). Yet the user **already
owns a Z-Wave device** — the **Zooz ZEN55 LR** 800-series Z-Wave Long Range DC Signal Sensor
(CONFIRMED OWNED 2026-05-11; HA-07 §3). Without a coordinator it is **stranded**: it cannot join HA
and cannot report (HA-07 §4.1, §5.1).

This is not a hypothetical purchase — it **unlocks a sunk cost** and **gates a life-safety feature**:

- The ZEN55 is the **SA-01-endorsed non-invasive bridge** that reads the owned First Alert SC7010BA
  hardwired smoke/CO detector's interconnect line without altering the certified device, exposing
  **two distinct `binary_sensor`s** (`device_class: smoke` + `carbon_monoxide`) via Z-Wave JS
  (HA-07 §5.1). SA-01 requires distinct smoke-vs-CO messaging — the ZEN55 provides exactly that.
- **`SA-03` (smoke/CO alerting impl) is explicitly Z-Wave-coordinator-gated** (BACKLOG §5 SA row;
  HA-07 R3/§12). No coordinator → no HA smoke/CO telemetry → SA-03 cannot proceed.
- **`SA-04` (water/leak impl)** will "likely" need the same coordinator: SA-02 §6A names a radio
  coordinator as the foundational prerequisite for *any* HA-native battery safety sensor, and SA-02
  §5.2/§4.7 recommend future leak sensors be **Z-Wave** so **one coordinator serves both** smoke
  telemetry and leak sensors.

**In short:** a coordinator is the single missing keystone (HA-07 §4.7) between the current state and
SA-01-grade smoke/CO telemetry, and it is the shared prerequisite for future leak protection.

## 2. Decision framework / criteria

The radio choice is already settled by the owned hardware: the ZEN55 is **Z-Wave**, and Zigbee /
Matter / Thread coordinators do nothing for it (HA-07 §4.7). So this decision is **not** "which
radio" — it is **"which Z-Wave 800-series controller."** Criteria, weighted for a life-safety-gating
role on an old libvirt host:

| # | Criterion | Why it matters here |
|---|---|---|
| C1 | **Official HA support / recommendation** | The coordinator gates a life-safety path — prefer the controller HA itself endorses and maintains. |
| C2 | **800-series chipset + Z-Wave classic *and* Long Range** | Future-proof RF; matches the ZEN55's 800-LR class (HA-07 §4.1). |
| C3 | **Controller firmware / SDK in HA's preferred band** | HA gives explicit SDK guidance (§3); avoids known-bad SDK ranges. |
| C4 | **Local, no subscription** | Life-safety telemetry must not depend on a cloud (SA-01 §3.1: avoid cloud in the alarm path). |
| C5 | **Fits the HAOS-VM / libvirt USB-passthrough topology** | The device plugs into the Ubuntu host and must reach Z-Wave JS inside the `haos` VM (§6). |
| C6 | **RF placement quality** | The ZEN55 and future leak sensors must reach the coordinator through household walls. |
| C7 | **Canadian availability (CA frequency, 908.42 MHz)** | Locale is Edmonton; Z-Wave frequency is region-locked (§7). Secondary. |
| C8 | **Price** | All candidates are ~CA$65–95; not a differentiator. |

Out of scope (per dispatch): buying anything, opening carts/checkout, quoting live order prices,
touching the host/VM/HA, changing USB passthrough or libvirt config, pairing devices.

## 3. Official HA guidance summary (verified 2026-07-01)

From the official HA Z-Wave adapters documentation and the Connect ZWA-2 product page:

- **HA officially recommends the Home Assistant Connect ZWA-2**, "an 800 series Z-Wave adapter
  specifically developed to work with Home Assistant," designed by "the team driving forward Home
  Assistant and Z-Wave JS." [HA docs]
- **800-series is preferred** — "the most future-proof and offer the best RF performance."
  **700-series is discouraged** ("not recommended"). [HA docs]
- **Controller SDK/firmware guidance (verbatim intent):** *prefer SDK 7.23.x and newer*; acceptable
  fallbacks **7.22.x** or **7.17.2–7.19.x**; **avoid** SDK **< 7.17.2** and **7.20–7.21.3**. Caveat:
  "The SDK version does not have to match the firmware version" — confirm with the vendor if unsure.
  [HA docs]
- **Three 800-series controllers are listed as working** with recommended SDK/firmware:
  1. **Home Assistant Connect ZWA-2** (officially recommended)
  2. **HomeSeer SmartStick G8**
  3. **Zooz 800 Series Z-Wave Long Range S2 Stick (ZST39 LR)**

This **corrects and confirms HA-07 §13.b**: HA-07 recorded "ctrl fw ≥ 7.23.2 recommended"; the
current HA doc phrases it as **"prefer SDK 7.23.x and newer"** with the acceptable/avoid bands above.
Same intent, more precise. The three-candidate list is unchanged.

Sources: [HA — Z-Wave adapters](https://www.home-assistant.io/docs/z-wave/controllers/) ·
[HA — Connect ZWA-2](https://www.home-assistant.io/connect/zwa-2/) ·
[HA blog — Connect ZWA-2 launch](https://www.home-assistant.io/blog/2025/08/13/home-assistant-connect-zwa-2/).

## 4. Candidate comparison — ZWA-2 vs Zooz ZST39 LR vs HomeSeer SmartStick G8

| Attribute | **HA Connect ZWA-2** | **Zooz ZST39 LR** | **HomeSeer SmartStick G8** |
|---|---|---|---|
| HA status (C1) | **Officially recommended** [HA docs] | Listed reported-working [HA docs] | Listed reported-working [HA docs] |
| Chipset / series (C2) | Silicon Labs ZG23, **800-series** [HA] | **800-series** [vendor] | **800-series**, Z-Wave Plus V2 [vendor] |
| Classic + LR (C2) | **Both, simultaneously** — "Run both your Z-Wave and Z-Wave Long Range networks simultaneously" [HA] | Classic + **LR** (US/CA/MX 908.42 MHz) [vendor] | Classic + **LR** (mesh + Long Range) [vendor] |
| Ships-with firmware/SDK (C3) | HA-native, **one-click firmware updates** + start-up wizard [HA] | **SDK 7.18** out of box [vendor spec] → in the *acceptable* 7.17.2–7.19.x band, **below preferred 7.23.x**; updatable | **ZDK 7.22.2** (as of 2024-10) [vendor] → *acceptable* 7.22.x band, near-preferred |
| Local / no subscription (C4) | **Yes**, open-source firmware [HA] | **Yes** [vendor] | **Yes** [vendor] |
| Form factor (C5/C6) | **Not a USB stick** — upright base unit **125×125×315 mm, 350 g**, external antenna; connects by **USB-C cable (1.5 m, 5 V/1 A)** [HA] | **Compact USB stick** (~2″ × 0.8″) [vendor] | **USB stick**, CH9102 VCP (virtual COM) chip [vendor] |
| Networked option (C5) | **Yes (indirect):** run Z-Wave JS on another machine, plug ZWA-2 in by USB, connect over network — though HA notes **direct USB is most reliable** (latency) [HA] | USB-only (host-side Z-Wave JS + network is a generic option) | USB-only (same generic option) |
| RF placement (C6) | **Best** — external upright antenna on a cable, sited away from the chassis [HA] | Stick at the port → **USB extension cable strongly advised** for placement | Stick at the port → **USB extension cable advised** |
| Security (C4) | S2 / SmartStart (Z-Wave Plus LR certified) [HA] | **S2 + SmartStart** [vendor] | **S2 + Secure Vault + SmartStart** [vendor] |
| Price (C8) | **US$69 / €59** MSRP [HA]; ~CA$95 retail [retail, MED] | ~US$50 [retail, MED] | ~US$55–65 [retail, MED] |
| Canada availability (C7) | **Amazon.ca** (3rd-party seller) + US DDP shippers [retail, MED] | US retailers (TheSmartestHouse, ameriDroid, Amazon.com); **CA-frequency SKU exists**; Amazon.ca varies [retail, MED] | **aartech.ca** (Canadian retailer) + Amazon [retail, MED] |

Confidence: HA-docs rows = **HIGH**; vendor-spec rows = **HIGH**; retail price/availability rows =
**MEDIUM** (secondary sources, and per dispatch not verified via any cart/checkout).

Sources (vendor/retail, secondary): [Zooz ZST39 LR specs](https://www.support.getzooz.com/kb/article/1377-zst39-800-long-range-z-wave-stick-specs/) ·
[HomeSeer SmartStick G8](https://homeseer.com/hs-products/hubs-interfaces/smartstick-g8/) ·
[SmartStick G8 quick-start (firmware)](https://docs.homeseer.com/products/smartstick-g8-quick-start-guide) ·
[aartech.ca — SmartStick G8](https://www.aartech.ca/smartstick-g8) ·
[Amazon.ca — Connect ZWA-2](https://www.amazon.ca/Assistant-Connect-devices-Official-Hardware/dp/B0FL858V4Q).

## 5. ZEN55 LR / Z-Wave Long Range compatibility

- **All three candidates can drive the owned ZEN55** over standard (classic) Z-Wave — they are all
  800-series controllers, and the ZEN55 is supported by **Z-Wave JS** (local; two distinct
  smoke + CO `binary_sensor`s; mains-powered so no battery entity; a relay endpoint for a local
  siren) per HA-07 §4.1/§13.b. **Classic Z-Wave is fully sufficient** for a single smoke bridge sited
  within normal mesh range — **Long Range is not required** to get SA-01 telemetry working.
- **To use Z-Wave Long Range specifically**, two conditions must both hold (vendor guidance, MED):
  1. an **LR-capable 800-series controller** (all three qualify — each advertises LR), **and**
  2. the **ZEN55 on firmware ≥ 1.20** (the LR-supporting ZEN55 build), per HA-07 §4.1.
  Both the controller/software side and the end device must support LR for it to engage; otherwise
  the ZEN55 simply joins as a classic Z-Wave node (still fully functional for smoke/CO telemetry).
- **Frequency (C7):** Z-Wave and Z-Wave LR are **region-locked**. For Canada, the correct band is
  **908.42 MHz (US/CA/MX)** — confirm the CA/US-frequency SKU at acquisition for whichever
  controller is chosen. (The ZWA-2 is sold in a region-appropriate variant; the Zooz ZST39 LR
  explicitly lists a US/CA/MX SKU.)
- **Practical read:** LR is a *range bonus*, not a functional requirement for the ZEN55 smoke bridge.
  Choose the controller on C1–C6; treat LR + ZEN55 fw ≥ 1.20 as an optional later optimization if the
  detector's location turns out to be at the edge of classic mesh range.

Sources: [HA — Z-Wave adapters](https://www.home-assistant.io/docs/z-wave/controllers/) ·
[Zooz — Add ZEN55 to Home Assistant](https://www.support.getzooz.com/kb/article/1266-how-to-add-your-zen55-smoke-co-detector-bridge-to-home-assistant/) ·
[Zooz — ZEN55 FAQ (LR / fw)](https://www.support.getzooz.com/kb/article/1414-zen55-smoke-co-detector-bridge-faqs/) · HA-07 §4.1/§5.1.

## 6. HAOS VM / libvirt USB-passthrough implications (describe only — no config change)

**Topology (from `haos-vm-deployment.md` + ONBOARDING §1):** Home Assistant runs as HAOS 18.0 inside
a **libvirt/QEMU** domain **`haos`** (`qemu:///system`) on the **Ubuntu 16.04 host** (`homebrain`,
**QEMU 2.5 / libvirt 1.3.1**). Any Z-Wave controller physically plugs into the **host**, but Z-Wave JS
runs as an **add-on inside the VM** — so the controller must be made reachable to the guest. Two paths:

**Path A — USB passthrough into the VM (the standard HAOS approach).**
- Requires adding a libvirt **`<hostdev>` USB passthrough** entry to the `haos` domain XML so the
  guest sees the controller as a serial device. This is a **libvirt/VM configuration change — OUT OF
  SCOPE here** (dispatch: no USB-passthrough / libvirt changes). Described as an implication only.
- **Stable device path:** pin the passthrough by **USB vendor:product ID** (and/or a fixed
  bus/port), and inside HAOS reference the controller via its `/dev/serial/by-id/...` symlink rather
  than `/dev/ttyUSB*`, so a reboot/re-enumeration doesn't move it. This matters for **all three**
  candidates (the ZWA-2 presents as a USB-C serial device; the sticks as USB serial).
- **Old-stack caveat:** on **QEMU 2.5 / libvirt 1.3.1**, USB device passthrough is supported but is
  older than most current HAOS USB-Z-Wave guidance assumes — expect to verify hot-plug behavior and
  device-address stability at implementation time (not now). Cross-reference **INF-05** (HAOS/host
  modernization) and the general "old QEMU/UEFI" cautions already documented in the VM doc.

**Path B — host-side Z-Wave JS + network (avoids VM passthrough).**
- Run a standalone Z-Wave JS on the **host** with the controller plugged in locally, and point HA's
  Z-Wave JS integration at it over the existing **host↔VM NAT network** (`192.168.122.x`). This
  sidesteps `<hostdev>` passthrough entirely — useful if passthrough proves fiddly on libvirt 1.3.1.
- The **ZWA-2 documents exactly this remote pattern** ("run Z-Wave JS on another machine, plug the
  ZWA-2 in via USB, connect that machine to Home Assistant over the network"), though HA notes
  **direct USB is the most reliable** option (network adds latency). Any USB stick could be driven the
  same way with a host-side Z-Wave JS, but only the ZWA-2 blesses the pattern as a first-class option.
- Trade-off: Path B adds a **host-side service to maintain** (against ONBOARDING's "keep the host
  minimal" posture) but keeps the VM XML untouched.

**Interference / placement.** Z-Wave is **sub-GHz (908.42 MHz)**, so USB-3 / 2.4 GHz interference is
**far less of a concern than for Zigbee** — but best practice still applies: get the radio off the
metal host chassis. A **short USB extension cable** is **strongly advised for the two sticks**
(ZST39 LR, G8) to improve placement; the **ZWA-2's external upright antenna on a 1.5 m USB-C cable
already solves this** by design, a genuine advantage for this rack/desk-mounted host.

**Net:** whichever controller is chosen, the live enablement (Path A passthrough *or* Path B
host-side Z-Wave JS) is an **INF/HA implementation task under approval**, not part of this decision.
The ZWA-2 is the only candidate that offers Path B as a documented, first-class fallback.

Sources: `haos-vm-deployment.md` §1/§4/§7 · ONBOARDING §1 · [HA — Connect ZWA-2 (USB-C, remote-network note)](https://www.home-assistant.io/connect/zwa-2/).

## 7. Canadian availability (secondary note only)

No carts, checkout, or live-order pricing were used — this is a sourcing sanity check only.

| Controller | Canada sourcing read | Confidence |
|---|---|---|
| **HA Connect ZWA-2** | **Generally available** — listed on **Amazon.ca** (3rd-party seller) plus US retailers offering duty-paid (DDP) shipping to Canada. | MED |
| **HomeSeer SmartStick G8** | **Generally available** — carried by Canadian retailer **aartech.ca** and via Amazon; strongest *domestic* Canadian sourcing of the three. | MED |
| **Zooz ZST39 LR** | **Likely available** — primarily US retailers (TheSmartestHouse, ameriDroid, Amazon.com); a **US/CA/MX (908.42 MHz) SKU exists**, so region-correct, but Canadian-domestic stock is thinner/cross-border. | MED |

All three ship in a Canada-appropriate 908.42 MHz frequency; confirm the exact CA/US-frequency
variant at acquisition. Availability is **not** a decisive differentiator, but if same-country
shipping/returns are valued, the **G8 (aartech.ca)** and **ZWA-2 (Amazon.ca)** edge out the Zooz.

## 8. Recommendation + rationale

**Adopt Z-Wave. Recommended controller: Home Assistant Connect ZWA-2.
Runner-up: HomeSeer SmartStick G8.**

**Why the ZWA-2 (primary):**
- **C1 — HA's own recommended controller**, built and maintained by the Z-Wave JS team; for a
  controller that will gate a **life-safety** feature (SA-03), aligning with the officially endorsed,
  first-party-maintained device is the conservative, defensible choice.
- **C3 — firmware currency handled natively:** one-click firmware updates + a start-up wizard keep it
  in HA's **preferred SDK band** without manual flashing (the Zooz ships on the older 7.18 SDK; the
  G8 on 7.22.2).
- **C6 — best RF:** external upright antenna on a 1.5 m USB-C cable → superior placement away from the
  metal host chassis, which matters for reaching a wall-mounted smoke bridge and future leak sensors.
- **C5 — best fit for this old libvirt host:** it is the **only** candidate that documents a
  **host-side Z-Wave JS + network** fallback (Path B, §6), a real escape hatch if `<hostdev>` USB
  passthrough proves fiddly on **QEMU 2.5 / libvirt 1.3.1**.
- **C4/C7 —** fully local, no subscription; available on Amazon.ca.
- Consistent with HA-07 §4.7/§13.b's provisional pick — this decision **confirms**, not overturns it.

**Why HomeSeer SmartStick G8 (runner-up):**
- Ships in HA's **acceptable 7.22.x SDK band** (closest-to-preferred of the two sticks), full
  800-series classic + LR, S2 + Secure Vault, and has the **strongest Canadian-domestic sourcing**
  (aartech.ca). Choose it if a **compact USB stick** is preferred over the ZWA-2's base-unit form
  factor, or if same-country purchase/returns are a priority. Requires a USB extension cable for good
  placement.

**Third, viable option — Zooz ZST39 LR:** fully supported and appealing for **vendor cohesion** with
the owned Zooz ZEN55 (Zooz documents the ZEN55 + HA path directly). Marked third only because it
ships on the **older 7.18 SDK** (in-band but below preferred → best updated before relying on it) and
has thinner Canadian-domestic stock. Not a wrong choice — simply the least-preferred of three good
ones.

## 9. Consequences — what this unblocks

**Unblocks (once a coordinator is acquired *and* separately enabled under approval):**
- **The owned ZEN55 stops being stranded** — it can join Z-Wave JS and expose its two distinct
  smoke + CO `binary_sensor`s + relay endpoint (HA-07 §5.1).
- **`SA-03` (smoke/CO alerting impl)** — its Z-Wave-coordinator gate is satisfied. SA-03 can then
  proceed through its own life-safety gate (SA-01 §3.9): disable switch, FP/FN validation,
  confirmation flow, one-step disable/rollback, primary sounder installed, critical-push confirmed.
- **`SA-04` (water/leak impl) — likely** — the same coordinator serves future **Z-Wave leak
  sensors** (SA-02 §5.2), so adopting Z-Wave here pre-satisfies SA-04's coordinator prerequisite.
- Establishes the **local radio backbone** for any future Z-Wave safety hardware (e.g. a dedicated
  Z-Wave siren, SA-01 §6D / HA-07 §5.3), keeping the life-safety path **off the cloud** (SA-01 §3.1).

**Remaining prerequisites before SA-03 can actually arm (NOT delivered by this decision):**
1. **Acquire** the chosen controller (a purchase — separate, gated; this doc is not an order).
2. **Enable it live** — Path A (libvirt USB passthrough) *or* Path B (host-side Z-Wave JS + network)
   — an **INF/HA implementation task under explicit approval**, holding the single live gate
   (BACKLOG §10, currently FREE).
3. **Pair the ZEN55** and confirm the two smoke/CO `binary_sensor`s appear (device pairing — gated).
4. **Verify the ZEN55 install state** — HA-07 §13.a open question #5 (is the ZEN55 already wired to a
   detector, or still boxed?). SA-01 telemetry needs it wired to the SC7010BA interconnect.
5. **Populate HA areas/floors** so alerts can carry meaningful labels (SA-01 §8; HA-01 §4 area map is
   near-empty). Note the smoke signal is **house-wide**, not room-labelled (HA-07 §5.1).
6. **Satisfy the full SA-03 life-safety gate** (SA-01 §3.9) — coordinator adoption clears *one*
   prerequisite; it does **not** open the SA gate.

## 10. Open questions / follow-ups (need user input before SA-03 proceeds)

- **Q1 — Controller choice:** confirm **ZWA-2** (recommended) vs **HomeSeer G8** (runner-up) vs
  **Zooz ZST39 LR** (viable third). Any preference for a compact stick, same-country (CA) purchase, or
  Zooz vendor-cohesion changes the pick.
- **Q2 — Enablement path (§6):** prefer **Path A** (USB passthrough into the `haos` VM — standard, but
  a libvirt XML change on old QEMU 2.5/libvirt 1.3.1) or **Path B** (host-side Z-Wave JS + NAT
  network — keeps the VM XML untouched, adds a host service)? Decision needed before the (gated)
  implementation task.
- **Q3 — ZEN55 install state (HA-07 §13.a #5):** is the ZEN55 already wired to the SC7010BA
  interconnect, or still boxed? SA-01 smoke telemetry depends on it being wired.
- **Q4 — Long Range:** engage Z-Wave LR (needs ZEN55 fw ≥ 1.20) or run the ZEN55 as a classic Z-Wave
  node? Only relevant if the detector is at the edge of classic mesh range (§5).
- **Q5 — Leak sensors (SA-04 / SA-02 §5.2, HA-07 §13.a #2):** confirm whether any leak sensors are
  owned, and commit to **Z-Wave** for future ones so the single coordinator serves both — this firms
  up the SA-04 dependency and the "one coordinator, two safety features" rationale.
- **Q6 — CA frequency SKU (§7):** confirm the 908.42 MHz (US/CA/MX) variant at acquisition.
- **Q7 — INF-08 tie-in:** if a UPS is later added (INF-08), the coordinator should be on protected
  power so smoke telemetry survives a short outage (HA-07 §9). Not a blocker for SA-03.

## 11. What this document does NOT do

- **No Home Assistant change** — no entity/exposure/automation/script edit, no reload, no HA API call,
  no live HA state read (this doc is repo-docs + public-web research only).
- **No host access** — no SSH, no host command, no service restart.
- **No USB-passthrough or libvirt/HAOS-VM configuration change** — §6 describes implications only.
- **No device pairing** — the ZEN55 is not joined; nothing is added to any network.
- **No purchase** — no cart, checkout, order, product widget, or live-order pricing; Canadian
  availability (§7) is a secondary sourcing note only.
- **No gate opened or closed** — RQ-06 is a decision record; it claims **no** live gate (BACKLOG §10
  left FREE) and asserts no SA gate is satisfied beyond clearing SA-03's *coordinator* prerequisite.
- **No BACKLOG.md edit** — the RQ-06 row / gate register are INF-owned (BACKLOG §9); any status change
  is proposed to INF separately, not made here.
- **No staging, commit, or push** — the doc is left uncommitted in the worktree pending approval.

---

> **Rollback for this document:** `git revert` on `homebrain/rq-06-zwave-coordinator-decision`, or
> delete this file. No secrets, no implementation, no exposure, no purchase; live gate left FREE.
