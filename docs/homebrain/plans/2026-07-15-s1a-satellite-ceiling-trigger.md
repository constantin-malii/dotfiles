# S1a — Satellite→Ceiling Interaction Trigger Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use `superpowers:subagent-driven-development` (recommended)
> or `superpowers:executing-plans`. Steps use `- [ ]` checkboxes.
>
> **Note on task shape:** this is an **HA-live config** change (one automation), not TDD code — there is no
> unit-test harness for HA YAML, so each task's "verification" is a **live observation** with an expected
> result. Tasks 1, 3, 4 touch the live Home Assistant and are **gate/approval-bound** (see Global Constraints).

**Goal:** an HA automation that fires the resolver's already-deployed `interaction` intent (`duck`/`restore`)
when the reSpeaker Living Room satellite enters/leaves a conversation, so ceiling music automatically ducks
while you talk and restores when you're done.

**Architecture:** a single HA automation triggers on `assist_satellite.respeaker_living_room_assist_satellite`
state and calls the **existing** `rest_command.resolver_command` with `{intent: interaction, params: {mode:
duck|restore}}`. No resolver code (AU-02/AU-03 shipped + live-validated 2026-07-15). No new `rest_command`
(the generic passthrough is proven — F1-R probe called it with arbitrary `{intent, params}`). The satellite's
spoken reply stays on **its own speaker** (reply-on-ceiling is the separate S1b).

**Tech Stack:** Home Assistant automation (YAML); existing `rest_command.resolver_command` → resolver
`/command` (`192.168.122.1:8770`, `X-Resolver-Key`); deployed `interaction` intent.

## Global Constraints

- **HA-live.** Installing the automation (Task 3) and live validation (Tasks 1, 4) touch the live Home
  Assistant → **claims the single live gate** (BACKLOG §10) and requires **explicit user approval** per
  `CLAUDE.md`. Tasks 1/3/4 do not run without it.
- **Scope:** one automation only. **No** resolver/`config.json` change (unless floor-tuning in Task 4
  proves necessary), **no** exposure change, **no** new ChatGPT tool, **no** `gpt-4o-mini` change, **no**
  other HA-script change. Reply stays on the satellite speaker (S1b is out of scope).
- **Entities (from S0 inventory):** satellite `assist_satellite.respeaker_living_room_assist_satellite`;
  media zone `media_player.ceiling_speakers` (the resolver's default zone — the automation does **not** pass
  `zone`, letting the resolver default apply).
- **`assist_satellite` states:** `idle` (no interaction) · `listening` · `processing` · `responding`
  (Task 1 confirms these empirically before install).
- **Secrets:** never print/log/commit. On-host `~/mass-resolver/.http_secret` and `.ha_token` are read into
  shell vars only (per `runbooks/resolver-deploy.md` / `quick-connect-and-health-check.md`).
- **Connect:** SSH `costea@192.168.1.68`, key `~/.ssh/id_homebrain`, via ssh-agent, every call bounded with
  `timeout`. HA REST at `http://192.168.122.10:8123`.

## File structure

- **Create (repo, ungated):** this plan + the automation YAML captured in it (Task 2). The authoritative
  copy of the automation lives in HA; the repo keeps the YAML for review/rollback reference.
- **Live (HA, gated):** one automation, alias `S1a — Satellite Ceiling Duck/Restore`, in Home Assistant.
- **No resolver files change.**

---

### Task 1: Capture the real `assist_satellite` state-transition sequence (read-only, GATED: live read)

**Why:** design §10's top open item — confirm the satellite emits **reliable, ordered** transitions usable
as triggers, and learn the exact state strings, before wiring an automation to them.

- [ ] **Step 1: Poll the state during one real interaction.** With music playing on the ceiling, run this
  on the host and, while it polls, say **"Okay Nabu, what time is it?"** to the satellite:

```bash
eval "$(ssh-agent -s)" >/dev/null; ssh-add ~/.ssh/id_homebrain >/dev/null
SSH='ssh -o ConnectTimeout=15 -o ServerAliveInterval=8 -o ServerAliveCountMax=3 costea@192.168.1.68'
timeout 40 $SSH '
HAT=$(cat ~/mass-resolver/.ha_token)
prev=""
for i in $(seq 1 120); do
  s=$(curl -s -m3 -H "Authorization: Bearer $HAT" http://192.168.122.10:8123/api/states/assist_satellite.respeaker_living_room_assist_satellite | python3 -c "import sys,json; print(json.load(sys.stdin).get(\"state\"))")
  if [ "$s" != "$prev" ]; then echo "$(date +%H:%M:%S.%N | cut -c1-12) $s"; prev="$s"; fi
  sleep 0.25
done'
```

- [ ] **Step 2: Verify.** Expect an ordered sequence like `idle → listening → processing → responding →
  idle`. Record the exact state strings and confirm it always ends back at `idle`. **If** the strings differ
  from `listening/processing/responding/idle`, update the trigger `to:` lists in Task 2 accordingly. **If**
  transitions are flaky/unordered, stop and reconsider the trigger model before Task 3.

**Observed (2026-07-15, music playing @ 0.32, two interactions):**
`idle → listening → responding → idle`, consistent and ordered, no flapping — trigger model confirmed
reliable (clears §10's top risk). **`processing` did not surface** (this pipeline goes `listening →
responding` directly; the ~3 s gap would have caught it at 0.25 s polling). Kept in the Task 2 trigger list
defensively — a never-firing state simply never matches. Short interaction ≈ 5 s (well under the 120 s
dead-man). Ceiling volume unchanged (0.32) throughout, as expected pre-install.

- [ ] **Step 3: Commit** (record the observed sequence in the plan / CHANGELOG note — no code):

```bash
git add docs/homebrain/plans/2026-07-15-s1a-satellite-ceiling-trigger.md
git commit -m "docs(homebrain): S1a - record observed assist_satellite transitions"
```

---

### Task 2: Author the automation YAML (repo, ungated)

**Files:** this plan (the YAML below is the authoritative reference for the HA install in Task 3).

**Interfaces — Consumes:** `rest_command.resolver_command` (existing; body `{intent, params}`), the deployed
`interaction` intent (`mode` ∈ `duck|restore`, `zone` defaults to ceiling). **Produces:** the automation
installed in Task 3.

- [ ] **Step 1: The automation.** Duck on any transition **into** a non-idle state (this also gives the
  dead-man refresh for free — every intermediate transition re-fires `duck`, which coalesces and re-arms the
  120 s timer); restore on the transition **back to** `idle`. `mode: queued` so rapid transitions each run
  (the resolver coalesces/serializes them).

```yaml
alias: S1a — Satellite Ceiling Duck/Restore
description: >-
  Ducks the ceiling media zone while the reSpeaker Living Room satellite is in a
  conversation, restores it when idle. Duck/restore are resolver-owned (AU-02/AU-03);
  this automation only triggers them. Reply stays on the satellite speaker (S1a).
mode: queued
max: 10
triggers:
  - trigger: state
    entity_id: assist_satellite.respeaker_living_room_assist_satellite
    to:
      - listening
      - processing
      - responding
    id: duck
  - trigger: state
    entity_id: assist_satellite.respeaker_living_room_assist_satellite
    to: idle
    id: restore
conditions: []
actions:
  - choose:
      - conditions:
          - condition: trigger
            id: duck
        sequence:
          - action: rest_command.resolver_command
            data:
              intent: interaction
              params:
                mode: duck
      - conditions:
          - condition: trigger
            id: restore
        sequence:
          - action: rest_command.resolver_command
            data:
              intent: interaction
              params:
                mode: restore
```

- [ ] **Step 2: Verify (static).** Confirm: (a) the `entity_id` matches Task 1's observed entity; (b) the
  `to:` state lists match Task 1's observed strings; (c) no `zone` is passed (resolver defaults to ceiling);
  (d) `mode: queued` (not `single` — `single` would drop the intermediate re-ducks that refresh the dead-man).

- [ ] **Step 3: Commit** (the YAML reference in this plan is committed with Task 1).

---

### Task 3: Install the automation in Home Assistant (HA-live, GATED — claims the live gate)

**Prerequisite:** user approval; record the gate claim in BACKLOG §10 (`S1a` / branch).

- [ ] **Step 1: Install.** Preferred — HA UI: **Settings → Automations & Scenes → Create Automation → Edit
  in YAML**, paste the Task 2 YAML, Save. (Alternative — HA REST: `POST /api/config/automation/config/<id>`
  with the JSON-equivalent body + bearer token; only if the UI isn't convenient.)

- [ ] **Step 2: Verify it registered (read-only).** Confirm the automation entity exists and is `on`:

```bash
timeout 30 $SSH 'HAT=$(cat ~/mass-resolver/.ha_token); curl -s -m6 -H "Authorization: Bearer $HAT" \
  http://192.168.122.10:8123/api/states/automation.s1a_satellite_ceiling_duck_restore \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(\"state=\", d.get(\"state\"))"'
```
Expected: `state= on`.

---

### Task 4: Live end-to-end validation + floor tuning (HA-live, GATED)

**Verification is behavioral — observe the ceiling and the resolver.** Reuse the volume-read technique from
the AU-02/03 deploy (`CHANGELOG.md` 2026-07-15): read `media_player.ceiling_speakers` volume via HA REST
(on-host `.ha_token`, never printed).

- [ ] **Step 1: Happy path.** Music playing on the ceiling. Read volume, then say **"Okay Nabu, what time is
  it?"**, watching the resolver log tail (`~/mass-resolver/resolver.log`) and re-reading volume during and
  after. Expected: volume **drops to the floor (0.15)** while the satellite is listening/answering, the reply
  plays **on the satellite's own speaker** (nothing on the ceiling), and volume **returns to the original**
  once the satellite is `idle`. Log shows `DUCK …` then `RESTORE …`, all silent (`spoken_text=None`).

- [ ] **Step 2: Barge-in / re-trigger (coalesce).** Start a second interaction **before** the first restores.
  Expected: the resolver coalesces — the baseline is the *original* pre-duck volume, and the final restore
  returns to it (not to the floor). Confirm no "stuck at floor".

- [ ] **Step 3: Abort / dead-man.** Trigger the satellite, then **abandon** the interaction (say nothing /
  walk away) so it may not cleanly reach `idle`. Expected: the resolver's **120 s dead-man** auto-restores
  the ceiling even though the `→ idle` restore trigger may not have fired. (This is the belt-and-suspenders
  in design §5; confirm the ceiling never stays stuck at the floor.)

- [ ] **Step 4: Ignore-when-idle.** With the ceiling **not** playing, trigger an interaction. Expected: no
  volume change, resolver returns `ducked:false, reason:not_playing` — the automation fires but the resolver
  correctly no-ops.

- [ ] **Step 5: Floor tuning (only if Step 1 shows a problem).** If the mic can't hear over the 0.15 floor,
  or the satellite reply is inaudible under it, adjust `interaction_floor` in `~/mass-resolver/config.json`
  and redeploy config per `runbooks/resolver-deploy.md` (config-only; restart required). Per design §7 the
  headroom to *raise* the floor depends on the XVF3800's **beamforming/noise-suppression**, not AEC — so
  treat near-quiet as the safe default and only raise it if validation supports it.

- [ ] **Step 6: No regression.** Confirm music/radio/news/status still work and the satellite's normal
  voice replies are unaffected.

---

## Close-out (after Task 4 passes)

- **CHANGELOG.md:** entry — the S1a automation, the validated auto-duck/restore behavior, floor value used.
- **BACKLOG.md:** S-track — mark `S1a` done; note **`S1b`** (reply-on-ceiling relay) as the next S item;
  release the live gate (§10 → FREE).
- **S1a design doc:** no change expected (the design already matches); note any deviation if the observed
  state strings differed.

## Rollback

Disable or delete the `S1a — Satellite Ceiling Duck/Restore` automation in HA (Settings → Automations →
toggle off / delete). No resolver change to revert (the `interaction` intent stays deployed and idle-safe —
nothing calls it once the automation is gone). If a floor change was made in Step 5, restore
`~/mass-resolver/config.json` from its `.bak/<ts>/` and restart.

## Self-review notes

- **Spec coverage:** design §5 trigger model → Tasks 1–3; §5 dead-man refresh (re-fire on intermediate
  transitions) → Task 2 `to:[listening,processing,responding]` + `mode: queued`; §5 HA-side dead-man gap →
  Task 4 Step 3 (relies on the resolver's deployed 120 s timeout); §4.1 ignore-when-idle → Task 4 Step 4;
  §7 floor tuning → Task 4 Step 5; §10 transition reliability → Task 1.
- **No new resolver code / rest_command:** confirmed — generic `rest_command.resolver_command` passthrough
  (F1-R probe) + deployed `interaction` intent.
- **Gated:** Tasks 1/3/4 are live; the automation install (Task 3) claims the single live gate.
