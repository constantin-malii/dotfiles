# HA-08 — Garage door: left-open alerts, checked remote close, read-only voice status

> **Status:** design, agreed section by section with the operator 2026-09-29; awaiting operator review of this
> written spec. **Track:** HA. **Live surface:** HA helpers, scripts, automations, and **one** exposure change
> (`script.garage_status` → `conversation`). No resolver, host, or MA change.
> **Device:** Meross MSG100 via HomeKit Controller (paired 2026-09-29 — see `CHANGELOG.md`), entity
> `cover.msg100_7982_garage_door` (device class `garage`), area Garage.

## 1. Intent (agreed with the operator, 2026-09-29)

- **Goal:** the garage door stops being left open by accident, and either of us can close it from the phone
  without walking out to check.
- **Who is alerted:** **both** household phones — `notify.mobile_app_sm_s948w_costea` and
  `notify.mobile_app_sm_s948w_vio`. Either person may use the *Close* button. (The old Huawei `clt_l04` is not a
  target.)
- **Left open:** alert after **15 minutes** open, then a reminder **every 15 minutes, at most 4 reminders**.
- **Working in the garage:** the alert carries **Snooze 1 h** and **Snooze 3 h**. While snoozed, no reminders; when
  the snooze ends and the door is still open, reminders resume.
- **Bedtime check:** **21:00 every day**, if the door is open, alert immediately. **The bedtime check ignores any
  snooze.**
- **Close button:** **one tap**, state-checked before moving and verified after (§4.2).
- **Also in scope:** a **read-only voice status** ("Okay Nabu, is the garage open?") and an **"opened while nobody
  is home"** alert.

### 1.1 Hard rules

1. **Nothing opens the door.** No script, automation, button or voice path in this design issues an open.
2. **Exactly one thing can move the door:** `script.garage_close_checked`, and it can only close.
3. **The cover entity is never exposed** to any assistant. The only new exposure is the read-only status script.
4. **No automatic closing.** A close happens only after a human taps *Close*.

### 1.2 Deferred / rejected (recorded so they are not lost)

| Idea | Decision | Why |
|---|---|---|
| "Okay Nabu, close the garage door" | **Deferred** (operator, 2026-09-29) | The satellite false-wakes on ordinary conversation (~8/20 runs, ONBOARDING §6). A false wake that starts the door moving is a physical hazard, not a nuisance. Revisit after the read-only voice status has run for a while; the preferred shape then is a fixed phrase in the local sentence layer (not an agent tool) with a phone confirmation of the result. |
| Voice **open** | **Never** | Physical entry to the house. |
| Presence-based auto-close | Rejected | Violates hard rule 4. |
| HA `alert:` integration for repeats | Rejected | YAML-only in `configuration.yaml` (no VM shell to edit it), and its acknowledge is indefinite, not a timed snooze. |
| Garage logic in the resolver | Rejected | Puts door control in the media service, adds a host deploy per change, and couples the door to the resolver's uptime. |

## 2. Approach

Native HA **helpers + scripts + automations**, managed under `ha/` like the existing house tools (exported by
`mass-resolver/tools/ha_export.py`, listed in `ha/MANIFEST.json`, reviewed as diffs). Actionable notifications go
through the Companion app; button taps return as `mobile_app_notification_action` events.

## 3. Components

### 3.1 Helpers (state only)

| Entity | Purpose | Notes |
|---|---|---|
| `timer.garage_snooze` | While `active`, left-open reminders are suppressed | `restore: true`; started with duration 1 h or 3 h |
| `counter.garage_reminders` | Caps repeat reminders at 4 | `restore: true`; reset when the door closes |

### 3.2 Scripts

| Entity | Role | Moves the door? | Exposed? |
|---|---|---|---|
| `script.garage_notify` | The **only** sender. Sends to both phones with `tag: garage` (a new alert replaces the old one), optional action buttons; mode `clear` sends `clear_notification` | No | No |
| `script.garage_close_checked` | Checked close (§4.2). Field `dry_run` (bool) runs every check and reports "would close" without calling the cover | **Yes — close only** | **No** |
| `script.garage_status` | Read-only status for voice (§5) | No | **Yes** (`conversation` only) |

### 3.3 Automations

| Entity | Trigger | Action |
|---|---|---|
| `automation.garage_left_open` | Door not `closed` for 15 min; then a 15-min time pattern while not closed | If `timer.garage_snooze` idle and `counter.garage_reminders` < 4 (the first alert does not count): notify with *Close* · *Snooze 1 h* · *Snooze 3 h*; increment the counter on reminders |
| `automation.garage_bedtime_check` | Time 21:00 | If door not `closed`: notify with *Close*. Ignores the snooze |
| `automation.garage_opened_while_away` | Door → `open`/`opening` | If `person.costea` **and** `person.vio` have both been `not_home` ≥ 5 min: notify immediately with *Close* |
| `automation.garage_notification_action` | `mobile_app_notification_action` with `action` ∈ {`GARAGE_CLOSE`, `GARAGE_SNOOZE_1H`, `GARAGE_SNOOZE_3H`} | *Close* → `script.garage_close_checked`; *Snooze* → start the timer. **This is the kill switch** (§6.4) |
| `automation.garage_closed_cleanup` | Door → `closed` | `garage_notify` mode `clear`; `timer.cancel` snooze; `counter.reset` reminders |
| `automation.garage_status_lost` | Door `unavailable`/`unknown` for 10 min | Notify "Garage status lost — last seen OPEN" **only if** the last known state was not `closed` |

Action identifiers are namespaced `GARAGE_*` so no other notification's buttons can reach the handler.

**Flow of a tap:** phone → `mobile_app_notification_action` → `automation.garage_notification_action` →
`script.garage_close_checked` → cover → result via `script.garage_notify`.

## 4. Behaviour and failure handling

### 4.1 "Not closed" is the alert condition

`opening`, `open` and `closing` all count as not closed, so a door stopped part-way still alerts after 15 minutes.

### 4.2 `script.garage_close_checked` (mode `single`)

1. Read the door state. Checks run **in this order**:
   - `closed` → reply **"Already closed ✓"**, stop.
   - `unavailable`/`unknown` → reply **"Can't reach the garage door — not closing"**, stop.
   - `opening` or `closing` unchanged for > 60 s → reply **"Garage is stuck (<state>) — check it"**, stop. No
     command is sent to a door that may be jammed. (Checked before the next rule so a door jammed while closing
     is reported as stuck, not as "already closing".)
   - `closing` → reply **"Already closing"**, stop.
   - `opening` → reply **"Door is opening — try again when it stops"**, stop.
   - `open` → continue.
2. If `dry_run`: reply **"Would close now (dry run)"**, stop.
3. `cover.close_cover`.
4. Wait up to **60 s** for `closed`.
   - Reached → **"Garage closed ✓"** (and the cleanup automation clears the alert).
   - Not reached → **"Garage did NOT close — it's <state>"**. **No automatic retry**: a reversing door usually
     means something is in the way.
5. Every reply goes to **both** phones, so each person knows what the other did.

A second tap while the script runs is dropped by mode `single`; the tapper sees no new alert, and the in-flight
run reports for both.

### 4.3 Snooze, repeats and closing

- Closing the door cancels the snooze and resets the counter; a fresh opening starts a fresh sequence.
- When the snooze ends and the door is still open, the next 15-min tick sends a reminder (counter permitting).
- A tap on a stale alert is caught by §4.2 step 1.

### 4.4 Meross offline

No left-open alert fires on `unavailable`/`unknown`. `automation.garage_status_lost` covers the one case that
matters (lost while not closed). Offline-while-closed is left to HA-06 device health.

### 4.5 HA restart

Helpers restore their state, so a snooze survives. The left-open trigger re-evaluates the real door state after
boot; one immediate alert right after a restart with the door open is acceptable. Note `INF-11`: an HA core
restart can leave Music Assistant down — garage alerts do not depend on MA.

### 4.6 Presence errors

The away alert requires both people `not_home` for ≥ 5 minutes, damping "arrived, opened the door before the
phone reported home". A false fire is an alert only; nothing moves.

## 5. Voice status and exposure

`script.garage_status` reads the cover and returns `{chat_text: …}` via `stop` + `response_variable` (the F1-R
return shape the agent already relays verbatim):

| Door | `chat_text` |
|---|---|
| `open` | "The garage door is open — it's been open for N minutes." |
| `closed` | "The garage door is closed." |
| `opening`/`closing` (< 60 s) | "The garage door is <state> right now." |
| `opening`/`closing` (≥ 60 s) | "The garage door has been <state> for N minutes — it may be stuck." |
| `unavailable`/`unknown` | "I can't reach the garage door right now — it was last seen <last state>." |

- **No actions** in the script — no `cover.*`, no other script calls, no TTS.
- Description (what the agent sees): *"Report whether the garage door is open or closed. This tool cannot open or
  close the door."*
- **Exposure:** `script.garage_status` → `conversation` only (14 → 15 exposed). Nothing else garage-related is
  exposed; `expose_new_entities` stays off. The knowledge agent ("Hey Mycroft") has no tools and is unaffected —
  the agent split holds.
- No local sentence triggers are added. "Close the garage" reaching the agent has no tool to act with, so the
  correct answer is "I can't do that".
- `assistant-capabilities.md` gains the tool (NL-02 lockstep).

## 6. Rollout, testing, rollback

### 6.1 Gate

The implementing PR claims **host-live / HA-live / exposure** in `BACKLOG.md` §10 and releases it on merge.

### 6.2 Stages (each live-verified before the next)

| Stage | Goes live | Verification | Door can move? |
|---|---|---|---|
| 1 | Helpers, `garage_notify`, `garage_status` (**not exposed**) | Run the status script in each real door state; one test notification to both phones | No |
| 2 | `garage_left_open`, `garage_bedtime_check`, `garage_opened_while_away`, `garage_closed_cleanup`, `garage_status_lost`, and the handler with **Snooze only** (no *Close* button offered) | Thresholds temporarily **1 min** (restored to 15 after); operator opens the door and checks alert, repeats, cap, snooze, clear-on-close; bedtime fired via a temporary time | No |
| 3 | `garage_close_checked` + *Close* button | `dry_run` first (every refusal case + "would close"); then **one real close with the operator at the garage**; then already-closed and double-tap refusals | **Yes — operator present** |
| 4 | Expose `script.garage_status`; update `assistant-capabilities.md` | "Okay Nabu, is the garage open?" with the door open and closed; pipeline debug trace shows the status tool was called | No |

### 6.3 Backups and managed state

- Before each live change: a **fresh timestamped backup** of anything existing that is touched (chiefly the
  exposure list), restore **only that exact path**, then the exporter check (the AN-01 G4b rule).
- All new entities are added to `ha/MANIFEST.json`; `ha_export.py` output is diff-reviewed and committed with the
  stage, so the repo matches live.

### 6.4 Rollback and kill switch

- Per stage, in reverse: un-expose `garage_status` → delete `garage_close_checked` and drop the *Close* action →
  disable/delete the garage automations → delete helpers and scripts.
- Only the exposure list is an existing object that changes, so rollback cannot disturb media or voice.
- **Kill switch:** disabling `automation.garage_notification_action` stops all remote closing at once; the alerts
  keep working.

### 6.5 Done when

All four stages pass their live checks, the export diff is committed, `CHANGELOG.md` and `ONBOARDING.md` are
updated, `HA-08` moves to `done` for this scope (with voice close recorded as a follow-up item), and the gate is
released.

## 7. Open items for the implementation plan

- Confirm the HomeKit Controller cover reports `opening`/`closing` (not just `open`/`closed`) during travel — the
  stuck-detection in §4.2 and the status table in §5 depend on it. Verify read-only in stage 1 by watching the
  entity during one normal open/close by the operator.
- Confirm the Companion app on both Samsungs delivers actionable buttons and the `tag` replace/clear behaviour
  (stage 1 test notification).
- DHCP reservation for the Meross (`192.168.1.64`) — not required by HomeKit Controller, but recommended before
  relying on alerts.
