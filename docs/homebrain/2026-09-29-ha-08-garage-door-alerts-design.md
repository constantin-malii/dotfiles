# HA-08 — Garage door: left-open alerts, checked remote close, read-only voice status

> **Status:** design, agreed section by section with the operator 2026-09-29; revised after two reviews
> (2026-09-29: a peer review's five required edits + notes, then a second review's five points, aligned with the
> peer before editing); awaiting operator review of this written spec.
> **Merge order:** after the pairing PR (`homebrain/ha-08-meross-pairing`), whose `CHANGELOG.md` entry this spec
> cites.
> **Track:** HA. **Live surface:** HA helpers, scripts, automations, and **one** exposure change
> (`script.garage_status` → `conversation`). No resolver, host, or MA change.
> **Device:** Meross MSG100 via HomeKit Controller (paired 2026-09-29 — see `CHANGELOG.md`), entity
> `cover.msg100_7982_garage_door` (device class `garage`), area Garage.

## 1. Intent (agreed with the operator, 2026-09-29)

- **Goal:** the garage door stops being left open by accident, and either of us can close it from the phone
  without walking out to check.
- **Who is alerted:** **both** household phones — `notify.mobile_app_sm_s948w_costea` and
  `notify.mobile_app_sm_s948w_vio`. Either person may use the *Close* button. (The old Huawei `clt_l04` is not a
  target.)
  **These are the legacy notify *services* on purpose.** `ha-device-inventory.md` lists the phones as the
  `notify.sm_s948w_*` *entities*; do not "correct" to those. Only the legacy `notify.mobile_app_*` service carries
  `data: {actions, tag}` and `clear_notification`; the `notify.send_message` entity path does not. Stage 1's test
  notification verifies both service ids exist.
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
2. **Exactly one HA path can move the door:** `script.garage_close_checked`, and it can only close. The wall
   control and the Meross app are outside HA and out of scope. A preflight audit (§6.2, before stage 3) proves no
   other HA path exists.
3. **The cover entity is never exposed** to any assistant. The only new exposure is the read-only status script.
4. **No automatic closing.** A close happens only after a human taps *Close*.
5. **Never close a door that has not been stably open.** `script.garage_close_checked` refuses unless the door has
   been `open` for at least **T** seconds (§4.2), whatever the device reports about `opening`.

### 1.2 Deferred / rejected (recorded so they are not lost)

| Idea | Decision | Why |
|---|---|---|
| "Okay Nabu, close the garage door" | **Deferred** (operator, 2026-09-29) | The satellite false-wakes on ordinary conversation (~8/20 runs, ONBOARDING §6). A false wake that starts the door moving is a physical hazard, not a nuisance. Revisit after the read-only voice status has run for a while; the preferred shape then is a fixed phrase in the local sentence layer (not an agent tool) with a phone confirmation of the result. |
| Voice **open** | **Never** | Physical entry to the house. |
| Presence-based auto-close | Rejected | Violates hard rule 4. |
| HA `alert:` integration for repeats | Rejected | YAML-only in `configuration.yaml` (no VM shell to edit it), and its acknowledge is indefinite, not a timed snooze. |
| Garage logic in the resolver | Rejected | Puts door control in the media service, adds a host deploy per change, and couples the door to the resolver's uptime. |
| Restrict button taps to the two household users (`trigger.event.context.user_id`) | Rejected (pre-live review, 2026-09-29) | Firing `mobile_app_notification_action` needs an HA token, and a token holder can call `cover.close_cover` on the unexposed cover directly, so the filter doesn't shrink the surface that matters. It would also break the stage-2 REST-fired test events. Don't re-propose it without a new threat. |

### 1.3 Known behaviour, accepted (pre-live review, 2026-09-29)

- **Snooze vs. a re-armed first alert.** If a snoozed door goes `open` → `closing` → `open` without reaching `closed`,
  the 15-min trigger re-arms and its first alert fires even while snoozed (it also resets the reminder counter).
  Accepted: the same "first alert ignores stale state" rule is what lets the next episode alert after a close that
  HA missed while down.
- **The away alert's 5 minutes count time in the current zone,** not total time away: moving Work → `not_home`
  resets it. This can only suppress an alert, never cause a false one.
- **`garage_status_lost` never fires on a flapping door.** After `unknown` → `unavailable`, the `from` state is no
  longer one of the alert states, so a door flapping between `unavailable` and `unknown` doesn't trigger it.
  HomeKit Controller normally goes `unavailable` and stays; offline detection in general is HA-06's job.
- **A phone whose Companion registration disappears** doesn't silence the other phone (each call is guarded
  separately); the send path raises a persistent notification naming the missing phone.

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
| `script.garage_notify` | The **only** sender. Sends to both phones; field `tag` (default `garage`) so a new message replaces the previous one under the same tag; optional action buttons; mode `clear` sends `clear_notification` for the given tag. **Two tags:** `garage` = actionable alerts only; `garage_result` = close outcomes, **never with buttons**, so a stale result can never be tapped into a close | No | No |
| `script.garage_close_checked` | Checked close (§4.2). Field `dry_run` (bool) runs every check and reports "would close" without calling the cover | **Yes — close only** | **No** |
| `script.garage_status` | Read-only status for voice (§5) | No | **Yes** (`conversation` only) |

### 3.3 Automations

| Entity | Trigger | Action |
|---|---|---|
| `automation.garage_left_open` | State trigger `to: [open, opening, closing]`, `for: 15 min`; then a `/15` time pattern whose condition checks the door is in one of the **same three states** (never `unavailable`/`unknown` — §4.4) | If `timer.garage_snooze` idle and `counter.garage_reminders` < 4 (the first alert does not count): notify (tag `garage`) with *Close* · *Snooze 1 h* · *Snooze 3 h*; increment the counter on reminders |
| `automation.garage_bedtime_check` | Time 21:00 | If door not `closed`: notify with *Close*. Ignores the snooze |
| `automation.garage_opened_while_away` | Door → `open`/`opening` | If `person.costea` **and** `person.vio` have both been `not_home` ≥ 5 min: notify immediately with *Close* |
| `automation.garage_notification_action` | `mobile_app_notification_action` with `action` ∈ {`GARAGE_CLOSE`, `GARAGE_SNOOZE_1H`, `GARAGE_SNOOZE_3H`} | *Close* → `script.garage_close_checked`; *Snooze* → start the timer. **`mode: parallel`** (max 10) — the close call blocks a run for up to 60 s (§4.2 step 4); under the default `single` a *Snooze* tap from the other phone in that window would be dropped silently, and under `queued` a duplicate *Close* would run ~15 s later and report "already closed". Parallel runs each tap at once: a duplicate *Close* hits the script's `mode: single` and is dropped silently. (Corrected from `queued` in plan review, 2026-09-29.) **This is the kill switch** (§6.4) |
| `automation.garage_closed_cleanup` | Door → `closed` | `garage_notify` mode `clear` for tag **`garage` only** (the `garage_result` message survives, so the close outcome is not erased); `timer.cancel` snooze; `counter.reset` reminders |
| `automation.garage_status_lost` | State trigger `from: [open, opening, closing]` → `to: [unavailable, unknown]`, `for: 10 min` | Notify "Garage status lost — last seen OPEN". The "last seen not closed" condition lives **in the trigger**, so no helper stores the last state, and `unavailable`↔`unknown` flapping cannot make `trigger.from_state` read `unavailable` |

Action identifiers are namespaced `GARAGE_*` so no other notification's buttons can reach the handler.

**Flow of a tap:** phone → `mobile_app_notification_action` → `automation.garage_notification_action` →
`script.garage_close_checked` → cover → result via `script.garage_notify` (tag `garage_result`).

## 4. Behaviour and failure handling

### 4.1 "Not closed" is the alert condition

`opening`, `open` and `closing` count as not closed, so a door stopped part-way still alerts after 15 minutes.
`unavailable` and `unknown` do **not** count (§4.4).

**The 15 minutes count from the last transition between the listed states.** HA's state trigger compares each new
state with the exact state that armed the `for` timer, so `opening` → `open` cancels the pending count and re-arms
a fresh 15 minutes on `open` (`not_to: [...]` goes through the same code path and behaves the same). In practice the
count starts when the door settles, a few seconds late, and a door bouncing `opening` ↔ `open` at an obstruction
keeps resetting. Both are acceptable: the rule only needs a door **stable** part-way to alert. Stage 2 confirms this
with the 1-min threshold: the alert should fire about 1 min after `open`, not after `opening`.

### 4.2 `script.garage_close_checked` (mode `single`, `max_exceeded: silent`)

1. Read the door state. Checks run **in this order**:
   - `closed` → reply **"Already closed ✓"**, stop.
   - `unavailable`/`unknown` → reply **"Can't reach the garage door — not closing"**, stop.
   - `opening` or `closing` unchanged for > 60 s → reply **"Garage is stuck (<state>) — check it"**, stop. No
     command is sent to a door that may be jammed. (Checked before the next rule so a door jammed while closing
     is reported as stuck, not as "already closing".)
   - `closing` → reply **"Already closing"**, stop.
   - `opening` → reply **"Door is opening — try again when it stops"**, stop.
   - `open` for **less than T seconds** → reply **"Door just opened — try again in a moment"**, stop.
     (**Stable-open guard, unconditional** — hard rule 5.)
   - `open` for at least T seconds → continue.
2. If `dry_run`: reply **"Would close now (dry run)"**, stop.
3. `cover.close_cover`.
4. Wait up to **60 s** for `closed`.
   - Reached → **"Garage closed ✓"**. The cleanup automation clears the `garage` alert; this result, under
     `garage_result`, stays.
   - Not reached → **"Garage did NOT close — it's <state>"**. **No automatic retry**: a reversing door usually
     means something is in the way.
5. Every reply goes to **both** phones under tag **`garage_result`**, **without buttons**, so each person knows what
   the other did.

**Why the guard is unconditional.** It is what actually prevents a close sent to a door still travelling up. If the
cover never reports `opening` (the MSG100 senses closed / not-closed only), a door in motion reads `open`, and the
`opening` refusal above never triggers. The case that needs it is `automation.garage_opened_while_away`: it alerts
the moment the door starts moving, so its *Close* can be tapped within seconds. Left-open (≥ 15 min) and bedtime
alerts cannot. **T** = the measured full travel time plus a margin, **30 s by default** until stage 1 measures it.
Refusing a close in the first ~30 s after opening is a trivial cost. `opening` detection, where the device provides
it, is a bonus that enables stuck-on-opening; it is not what safety rests on.

A second tap while the script runs is dropped by mode `single` (`max_exceeded: silent`, so no log warning); the
tapper sees no new alert, and the in-flight run reports for both. The handler's `mode: parallel` means the dropped
duplicate is a *close* only — a *Snooze* tap in the same window still runs.

⚠️ **Stuck-on-opening is not promised until measured.** The cover may flip from `opening` to `open` within
seconds, in which case the > 60 s stuck rule can only ever fire on `closing`. Stage 1 measures the transitional
states over **3 open/close cycles** (§6.2). That measurement decides only two things: whether stuck-on-opening (here
and in §5) is promised, and the value of T. It is **not** a safety go/no-go for stage 3, because the guard above
protects regardless of what the device reports.

### 4.3 Snooze, repeats and closing

- Closing the door cancels the snooze and resets the counter; a fresh opening starts a fresh sequence.
- When the snooze ends and the door is still open, the next 15-min tick sends a reminder (counter permitting).
- A tap on a stale alert is caught by §4.2 step 1.
- **Cadence, accepted:** the reminder trigger is a `/15` time pattern (:00/:15/:30/:45), so the **first reminder
  lands 0–15 min after the initial alert**, not exactly 15. Restarting a 15-min timer after each send would be
  exact, but adds another helper outside the managed export (§6.3); not worth it.

### 4.4 Meross offline

No left-open alert fires on `unavailable`/`unknown`. `automation.garage_status_lost` covers the one case that
matters (lost while not closed). **Offline-while-closed is unhandled until HA-06 ships** — HA-06 is a design, not
built, so today that case is silent.

### 4.5 HA restart

Helpers restore their state, so a snooze survives. With a `for: 15 min` trigger, an open door is re-alerted
**15 minutes after boot**, not immediately. The cover's `last_changed` resets at boot, so §5's "open for N minutes"
counts from the restart, not from when the door actually opened. §5 words it "at least N minutes" in that case.
The same reset applies to T in §4.2: after a restart the door counts as freshly open for T seconds, which only
delays a close. Note `INF-11`: an HA core restart can leave Music
Assistant down — garage alerts do not depend on MA.

### 4.6 Presence errors

The away alert requires both people `not_home` for ≥ 5 minutes, damping "arrived, opened the door before the
phone reported home". A false fire is an alert only; nothing moves.

## 5. Voice status and exposure

`script.garage_status` reads the cover and returns `{chat_text: …}` via `stop` + `response_variable` (the F1-R
return shape the agent already relays verbatim):

| Door | `chat_text` |
|---|---|
| `open` | "The garage door is open — it's been open for N minutes." ("…for **at least** N minutes." when `last_changed` is within 2 min of HA start — §4.5) |
| `closed` | "The garage door is closed." |
| `opening`/`closing` (< 60 s) | "The garage door is <state> right now." |
| `opening`/`closing` (≥ 60 s) | "The garage door has been <state> for N minutes — it may be stuck." (for `opening`, only once stage 1 shows the state can last that long — §4.2) |
| `unavailable`/`unknown` | "I can't reach the garage door right now." |

**Timing:** N = now − the cover's `last_changed`, in whole minutes. **No "last seen" state for voice:** once the
entity is `unavailable`, nothing in HA keeps its previous state, and an `input_text` helper to hold it would be a
third helper outside the managed export, for a nicety. (`automation.garage_status_lost` can still say "last seen
OPEN", because its trigger encodes the previous state.)

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

The implementing PR claims the **HA-live / exposure** gate in `BACKLOG.md` §10 — **not host-live**: nothing here
touches the host (the DHCP reservation is on the router). Claim it at the start of stage 1 (the helpers are the
first live object), hold it through stage 4, and release it on merge (§6.5).

### 6.2 Stages (each live-verified before the next)

| Stage | Goes live | Verification | Door can move? |
|---|---|---|---|
| 1 | Helpers, `garage_notify`, `garage_status` (**not exposed**) | Run the status script in each real door state; test notifications to both phones under **both tags**, checking replace and clear per tag; **3 operator open/close cycles** watched read-only to record whether `opening`/`closing` appear and how long each state and the full travel last (sets T — §4.2). Then the operator turns HA's temporary debug logging off (§7) | No |
| 2 | `garage_left_open`, `garage_bedtime_check`, `garage_opened_while_away`, `garage_closed_cleanup`, `garage_status_lost`, and the handler with **Snooze only** (no *Close* button offered) | Thresholds temporarily **1 min** (restored to 15 after); operator opens the door and checks alert, repeats, cap, snooze, clear-on-close; the trace shows the alert fired about 1 min after `open`, not after `opening` (§4.1); bedtime fired via a temporary time | No |
| 3 | `garage_close_checked` + *Close* button | **Preflight audit first** (below). Then `dry_run` (every refusal case, including "Door just opened", plus "would close"); then **one real close with the operator at the garage**, checking that the `garage_result` message survives the cleanup; then already-closed and double-tap refusals | **Yes — operator present** |
| 4 | Expose `script.garage_status`; update `assistant-capabilities.md` | "Okay Nabu, is the garage open?" with the door open and closed; pipeline debug trace shows the status tool was called | No |

**Preflight audit (before stage 3, read-only).** It proves hard rule 2 before any HA path can move the door:

1. No automation or script other than `script.garage_close_checked` references `cover.msg100_7982_garage_door`.
2. No `cover.*` service call in any automation or script targets it, including by area or device.
3. The cover is **not exposed** to any assistant (the exporter's exposure diff shows it). This closes the built-in
   `HassOpenCover` / `HassCloseCover` intents, the one path that bypasses scripts entirely.

(A read-only sweep on 2026-09-29, right after pairing, found 0 references and the cover unexposed. The audit
repeats it against the live state at stage 3.)

### 6.3 Backups and managed state

- Before each live change: a **fresh timestamped backup** of anything existing that is touched (chiefly the
  exposure list), restore **only that exact path**, then the exporter check (the AN-01 G4b rule).
- The new **scripts and automations** are added to `ha/MANIFEST.json`; `ha_export.py` output is diff-reviewed and
  committed with the stage, so the repo matches live for those.
- ⚠️ **The two helpers are outside the managed export.** The manifest only knows `scripts`, `automations`,
  `pipelines`, `satellite_entities` and `exposure_assistants` (`MANIFEST_COLLECTIONS`,
  `mass-resolver/tools/ha_export.py`). `timer.garage_snooze` and `counter.garage_reminders` are therefore recorded
  **by name and full config in the stage-1 `CHANGELOG.md` entry**. Adding a `helpers` collection to the exporter is
  a separate repo-code item, not part of HA-08.

### 6.4 Rollback and kill switch

- Per stage, in reverse: un-expose `garage_status` → delete `garage_close_checked` and drop the *Close* action →
  disable/delete the garage automations → delete helpers and scripts.
- Only the exposure list is an existing object that changes, so rollback cannot disturb media or voice.
- **Kill switch:** disabling `automation.garage_notification_action` stops all **new** remote closes at once; the
  alerts keep working. It does not stop a close already in flight (at most 60 s).

### 6.5 Done when

All four stages pass their live checks, the export diff is committed, `CHANGELOG.md` and `ONBOARDING.md` are
updated, `HA-08` moves to `done` for this scope (with voice close recorded as a follow-up item), and the gate is
released.

## 7. Open items for the implementation plan

- Confirm whether the HomeKit Controller cover reports `opening`/`closing` during travel, and **measure how long
  each state and the full travel last**, over 3 cycles in stage 1. This sets T (§4.2) and decides whether
  stuck-on-opening is promised (§4.2, §5). It does not gate stage 3 (the stable-open guard is unconditional).
- Confirm the legacy notify service ids `notify.mobile_app_sm_s948w_costea` / `…_vio` exist and deliver (§1).
- Confirm the Companion app on both Samsungs delivers actionable buttons, and that replace/clear works **per tag**
  (`garage` and `garage_result` independently).
- **Turn off HA's temporary debug logging** (left on from the 2026-09-29 discovery work) once stage 1's traces are
  captured: `logger.set_level` → `warning` for `zeroconf`, `homeassistant.components.zeroconf`,
  `homeassistant.components.homekit_controller`, `aiohomekit`. This is a live HA call, so it's an operator action.
- DHCP reservation for the Meross (`192.168.1.64`) on the router. Recommended before relying on alerts; not a
  blocker (HomeKit Controller follows the device by mDNS).
