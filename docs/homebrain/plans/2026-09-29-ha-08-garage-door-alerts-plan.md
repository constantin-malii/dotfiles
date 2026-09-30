# HA-08 Garage Door Alerts — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the approved HA-08 behaviour for the Meross garage door: left-open alerts with a timed snooze, a 21:00
bedtime check, an opened-while-away alert, a checked one-tap remote close, and a read-only voice status. Nothing
opens the door, and exactly one HA path can close it.

**Architecture:** HA scripts and automations are **authored in the repo** as canonical JSON under
`docs/homebrain/ha/` and **pinned by offline policy tests** that encode the spec's hard rules. A small tested tool,
`ha_apply.py`, pushes a file to live HA, backs up whatever it overwrites, and reads the config back to confirm it
matches. The existing exporter round-trip then proves live equals repo. Rollout is four live stages under the
HA-live/exposure gate, each verified before the next.

**Tech Stack:** Home Assistant 2026.6.4 (config API `/api/config/{script,automation}/config/<id>`, WS
`timer/create`, `counter/create`, `homeassistant/expose_entity`), Companion-app actionable notifications, Python
stdlib + `unittest` (Python 3.5-safe, no f-strings), the existing `mass-resolver/tools/ha_export.py`.

**Spec:** `docs/homebrain/2026-09-29-ha-08-garage-door-alerts-design.md` (approved by the operator 2026-09-29). Read
it first; this plan argues from it.

## Global Constraints

- Door entity: `cover.msg100_7982_garage_door`. Notify services (legacy, on purpose — spec §1):
  `notify.mobile_app_sm_s948w_costea`, `notify.mobile_app_sm_s948w_vio`.
- Tags: `garage` = actionable alerts only; `garage_result` = close outcomes, **never with buttons**.
- Button action ids, exact: `GARAGE_CLOSE`, `GARAGE_SNOOZE_1H`, `GARAGE_SNOOZE_3H`.
- Alert states, exact: `open`, `opening`, `closing`. Never `unavailable`/`unknown`.
- Left open: first alert after **15 min**, reminders every `/15`, **max 4**. Bedtime: **21:00**, ignores snooze.
  Away: both `person.costea` and `person.vio` away **≥ 5 min**. Status lost: **10 min**.
- Close script: `mode: single`, `max_exceeded: silent`; stable-open guard **T = 30 s** until stage 1 measures it;
  stuck > **60 s**; wait for `closed` **60 s**; **no automatic retry**.
- Handler: `mode: parallel` (max 10) — corrected from the spec's original `queued` after plan review: under `queued`
  a second *Close* tap waits behind the first and then reports "already closed", whereas under `parallel` it hits the
  close script's `mode: single` and is dropped silently, and a *Snooze* tap is still never blocked. It is the
  **kill switch**.
- Exposure: **only** `script.garage_status` → `conversation`, in stage 4. Never the cover or any other garage entity.
- Gate: **HA-live / exposure** (not host-live), claimed at the start of stage 1 and released on merge.
- Python code and tests: **3.5-safe** (no f-strings, no variable annotations); run with the workstation's Python.
- Commits: no mention of Claude/AI, no `Co-Authored-By` (repo `CLAUDE.md`). Never commit the HA token.
- **Line endings differ by tree.** Everything under `docs/homebrain/ha/` is `eol=lf` (`git check-attr`), so JSON
  there is written as bytes, LF-only, via the canonicalizer or the manifest snippet — never with a text-mode write on
  Windows. The prose docs (`CHANGELOG.md`, `BACKLOG.md`, …) are CRLF in the working tree: detect and match, and run
  `git diff --numstat` after every doc edit (an append is `N 0`).

## Plan-level additions (beyond the spec — flag to the operator at handoff)

1. **Obstruction refusal.** The HomeKit cover exposes `obstruction-detected`. The close script refuses when it is
   true ("obstruction detected — not closing"). This is a refusal only, so it can only make closing safer.
2. **Unexpected-state refusal.** Any state other than the known ones refuses ("unexpected state (…) — not
   closing"), so the close call is reached only from `open`.
3. **Snooze ignored if the door is already closed** (Review Focus 1).
4. **Cleanup also runs at HA start** (Review Focus 2), covering a door that closed while HA was down. Separately,
   the voice status's "at least N minutes" (spec §5) needs an HA-start marker, and the instance has no uptime or
   boot sensor (checked 2026-09-29). The marker is **`states.automation.garage_closed_cleanup.last_changed`**: the
   entity is created fresh at boot and only changes again if someone toggles the automation, so it isn't coupled
   to the automation's triggers.
5. **`ha_apply.py`**, a small push/backup/read-back tool (Task 5), so each deploy is byte-for-byte the reviewed
   file rather than JSON pasted into a command.
6. **Automation aliases slugify to their ids** (pre-live review, 2026-09-29). HA names an automation's entity after
   its **alias** at creation, not its `id` (live evidence: `ma_health_probe` is `automation.ma_health_probe_auto_reload`).
   The aliases are therefore plain ("Garage notification action", …), so the entities are exactly
   `automation.garage_<id>`, which the kill switch and the status boot marker depend on. The implemented files
   carry these aliases; the JSON blocks in Task 3 show the earlier, descriptive ones. Pinned by
   `test_automation_entity_ids_will_equal_their_ids`. At stage 2, confirm each entity id after the first push.

## Review Focus

1. **Snooze tapped on a stale alert after the door closed.** Expected: nothing happens. If the timer started, the
   *next* opening within 3 h would get no reminders. → `test_snooze_refused_when_door_closed` (Task 3).
2. **The door closes while HA is down,** so the `to: closed` cleanup is missed and the counter or snooze stays set.
   Expected: the next episode alerts normally. → `test_cleanup_runs_at_boot_without_conditions` and
   `test_initial_alert_resets_counter` (Task 3).
3. **A person in a named zone (e.g. "Work"), or `unknown` at boot.** Expected: a named zone counts as away;
   `unknown`/`unavailable` does **not**. → `test_away_alert_requires_both_known_away_5min` (Task 3).
4. **The door reports an obstruction.** Expected: close refused. → `test_refusal_order` (Task 2).
5. **A button from another notification, or an id that merely starts with `GARAGE_`.** Expected: it never reaches the
   handler. → `test_handler_parallel_and_exact_action_ids` (Task 3).

---

## File Structure

| Path (under `docs/homebrain/`) | Responsibility |
|---|---|
| `ha/scripts/garage_notify.json` | The only sender: send or clear, per tag, both phones |
| `ha/scripts/garage_close_checked.json` | The only HA path that moves the door: checks, close, verify, report |
| `ha/scripts/garage_status.json` | Read-only voice status returning `chat_text` |
| `ha/automations/garage_left_open.json` | 15-min alert + `/15` reminders, snooze and cap |
| `ha/automations/garage_bedtime_check.json` | 21:00 check |
| `ha/automations/garage_opened_while_away.json` | Opened while both are away |
| `ha/automations/garage_notification_action.json` | Button handler (kill switch) |
| `ha/automations/garage_closed_cleanup.json` | Clear alert, cancel snooze, reset counter; also at HA start |
| `ha/automations/garage_status_lost.json` | Unreachable while not closed for 10 min |
| `ha/MANIFEST.json` | + 3 scripts, + 6 automations |
| `mass-resolver/tests/test_ha_garage_policy.py` | Offline policy tests (hard rules + behaviour shape) |
| `mass-resolver/tools/ha_apply.py` | Push repo JSON → HA with backup + read-back (workstation-run) |
| `mass-resolver/tests/test_ha_apply.py` | Tests for `ha_apply.py` with a fake client |
| `mass-resolver/tests/test_py35_compat.py` | + the three new Python files in its module lists |
| `BACKLOG.md`, `CHANGELOG.md`, `ONBOARDING.md`, `assistant-capabilities.md` | Gate, records, current state, tool docs |

All commands below run from `docs/homebrain/mass-resolver/` unless stated. `$W` = the worktree root
(`D:\repos\dotfiles\.claude\worktrees\ha-08-garage-design`).

**Canonicalizer** (used after every JSON edit; makes files byte-identical to what the exporter writes):

```bash
python - ../ha/scripts/garage_*.json ../ha/automations/garage_*.json <<'PY'
import json, os, sys
sys.path.insert(0, "tools")
import ha_export
for p in sys.argv[1:]:
    if not os.path.exists(p):          # an unmatched glob arrives literally; skip it
        continue
    with open(p, encoding="utf-8") as fh:
        obj = json.load(fh)            # read fully BEFORE opening for write
    with open(p, "wb") as fh:
        fh.write(ha_export.render(obj))
    print("canonical:", p)
PY
```

---

### Task 1: Policy test scaffold, `garage_notify`, `garage_status`

**Files:**
- Create: `mass-resolver/tests/test_ha_garage_policy.py`
- Create: `ha/scripts/garage_notify.json`, `ha/scripts/garage_status.json`
- Modify: `mass-resolver/tests/test_py35_compat.py` (`TEST_MODULES` list)

**Interfaces:**
- Produces: `script.garage_notify` with fields `message` (text), `tag` (default `garage`), `buttons` (list of
  `{action, title}`, default `[]`, **dropped unless tag is `garage`**), `clear` (bool, default `false`).
  `script.garage_status` returns `{chat_text}` via `stop` + `response_variable: resp`.
- Produces (test module): helpers `load(kind, name)`, `walk(node)`, `actions_in(obj)`, `notify_calls(obj)`,
  constants `DOOR`, `SCRIPTS`, `AUTOMATIONS`, `LEGACY_NOTIFY`, `ALERT_STATES`, `FORBIDDEN_MOVES`. Later tasks add
  test classes to this same file.

- [ ] **Step 1: Write the failing tests**

Create `mass-resolver/tests/test_ha_garage_policy.py`:

```python
#!/usr/bin/env python3
"""HA-08 garage-door policy: static checks over the repo-authored HA config in docs/homebrain/ha/.

They encode the hard rules of docs/homebrain/2026-09-29-ha-08-garage-door-alerts-design.md (section 1.1)
so an edit that breaks one fails here before it can reach live Home Assistant. They check the repo copy;
the plan's stage checks prove live equals repo through the exporter round-trip.

Python 3.5-safe. Skips when ha/ is absent (the host copy of mass-resolver has no ha/ tree).
Run: python tests/test_ha_garage_policy.py
"""
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
HA = os.path.normpath(os.path.join(ROOT, "..", "ha"))
sys.path.insert(0, os.path.join(ROOT, "tools"))

DOOR = "cover.msg100_7982_garage_door"
SCRIPTS = ["garage_notify", "garage_close_checked", "garage_status"]
AUTOMATIONS = ["garage_left_open", "garage_bedtime_check", "garage_opened_while_away",
               "garage_notification_action", "garage_closed_cleanup", "garage_status_lost"]
LEGACY_NOTIFY = set(["notify.mobile_app_sm_s948w_costea", "notify.mobile_app_sm_s948w_vio"])
ALERT_STATES = ["open", "opening", "closing"]
BUTTON_IDS = set(["GARAGE_CLOSE", "GARAGE_SNOOZE_1H", "GARAGE_SNOOZE_3H"])
FORBIDDEN_MOVES = set(["cover.open_cover", "cover.toggle", "cover.set_cover_position",
                       "cover.stop_cover", "cover.open_cover_tilt", "cover.close_cover_tilt",
                       "cover.set_cover_tilt_position", "cover.toggle_cover_tilt"])
GENERIC_MOVES = set(["homeassistant.turn_on", "homeassistant.turn_off", "homeassistant.toggle"])


def load(kind, name):
    with open(os.path.join(HA, kind, name + ".json"), "rb") as fh:
        raw = fh.read()
    return raw, json.loads(raw.decode("utf-8"))


def walk(node):
    """Every dict inside node, depth-first, in document order."""
    if isinstance(node, dict):
        yield node
        for key in sorted(node):
            for sub in walk(node[key]):
                yield sub
    elif isinstance(node, list):
        for item in node:
            for sub in walk(item):
                yield sub


def actions_in(obj):
    return [d for d in walk(obj) if isinstance(d.get("action"), str)]


def is_device_action(d):
    """A UI 'device action' has no "action" key: {device_id, domain, entity_id, type}. Device triggers and
    conditions share that shape but carry "trigger"/"platform" or "condition", so they are not actions."""
    return (isinstance(d, dict) and "device_id" in d and "domain" in d and "type" in d
            and "action" not in d and not any(k in d for k in ("condition", "trigger", "platform")))


def device_actions_in(obj):
    return [d for d in walk(obj) if is_device_action(d)]


def notify_calls(obj):
    return [d for d in actions_in(obj) if d["action"] == "script.garage_notify"]


def all_managed():
    """(label, obj) for EVERY script and automation file in ha/, garage or not."""
    out = []
    for kind in ("scripts", "automations"):
        folder = os.path.join(HA, kind)
        for fname in sorted(os.listdir(folder)):
            if fname.endswith(".json"):
                out.append(("%s/%s" % (kind, fname), load(kind, fname[:-5])[1]))
    return out


@unittest.skipUnless(os.path.isdir(HA), "ha/ tree not present")
class GarageFilesTest(unittest.TestCase):
    def test_script_files_exist_and_are_canonical(self):
        import ha_export
        for name in SCRIPTS[:1] + SCRIPTS[2:]:
            raw, obj = load("scripts", name)
            self.assertEqual(obj.get("object_id"), name)
            self.assertEqual(raw, ha_export.render(obj), "%s is not canonical" % name)


@unittest.skipUnless(os.path.isdir(HA), "ha/ tree not present")
class NotifyScriptTest(unittest.TestCase):
    def setUp(self):
        self.obj = load("scripts", "garage_notify")[1]

    def test_sends_only_via_both_legacy_services(self):
        used = set(d["action"] for d in actions_in(self.obj) if d["action"].startswith("notify."))
        self.assertEqual(used, LEGACY_NOTIFY)

    def test_every_notify_call_continues_on_error(self):
        for d in actions_in(self.obj):
            if d["action"].startswith("notify."):
                self.assertTrue(d.get("continue_on_error"), "one phone failing must not block the other")

    def test_buttons_dropped_unless_alert_tag(self):
        text = json.dumps(self.obj)
        self.assertIn("if (tag | default('garage')) == 'garage' else []", text)

    def test_clear_path_sends_clear_notification_for_the_given_tag(self):
        clears = [d for d in actions_in(self.obj) if d.get("data", {}).get("message") == "clear_notification"]
        self.assertEqual(len(clears), 2)
        for d in clears:
            self.assertEqual(d["data"]["data"]["tag"], "{{ t }}")

    def test_fields(self):
        self.assertEqual(sorted(self.obj["fields"]), ["buttons", "clear", "message", "tag"])
        self.assertEqual(self.obj["fields"]["tag"]["default"], "garage")


@unittest.skipUnless(os.path.isdir(HA), "ha/ tree not present")
class StatusScriptTest(unittest.TestCase):
    def setUp(self):
        self.obj = load("scripts", "garage_status")[1]

    def test_read_only_no_actions_at_all(self):
        self.assertEqual(actions_in(self.obj), [])

    def test_description_says_it_cannot_move_the_door(self):
        self.assertIn("This tool cannot open or close the door.", self.obj["description"])

    def test_returns_chat_text(self):
        last = self.obj["sequence"][-1]
        self.assertEqual(last, {"response_variable": "resp", "stop": "done"})
        self.assertIn("chat_text", json.dumps(self.obj["sequence"][-2]))

    def test_unreachable_wording_has_no_last_seen(self):
        self.assertIn("I can't reach the garage door right now.", json.dumps(self.obj, ensure_ascii=False))
        self.assertNotIn("last seen", json.dumps(self.obj))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify it fails**

Run: `python tests/test_ha_garage_policy.py -v`
Expected: ERROR/FAIL with `FileNotFoundError: ... ha/scripts/garage_notify.json`.

- [ ] **Step 3: Create `ha/scripts/garage_notify.json`**

```json
{
  "alias": "Garage: notify phones",
  "description": "HA-08, internal. Sends or clears a garage notification on both household phones. Tag 'garage' = actionable alerts (the only tag that may carry buttons); 'garage_result' = close outcomes. Not exposed.",
  "fields": {
    "buttons": {"default": [], "description": "List of {action, title} buttons. Ignored unless tag is 'garage'.", "selector": {"object": {}}},
    "clear": {"default": false, "description": "Clear the notification with this tag instead of sending.", "selector": {"boolean": {}}},
    "message": {"description": "Notification text.", "selector": {"text": {}}},
    "tag": {"default": "garage", "description": "'garage' (actionable alert) or 'garage_result' (close outcome).", "selector": {"text": {}}}
  },
  "max": 10,
  "mode": "parallel",
  "object_id": "garage_notify",
  "sequence": [
    {"variables": {
      "t": "{{ tag | default('garage') }}",
      "btns": "{{ buttons | default([]) if (tag | default('garage')) == 'garage' else [] }}",
      "is_clear": "{{ clear | default(false) | bool }}"
    }},
    {"if": [{"condition": "template", "value_template": "{{ is_clear }}"}],
     "then": [
       {"action": "notify.mobile_app_sm_s948w_costea", "continue_on_error": true, "data": {"message": "clear_notification", "data": {"tag": "{{ t }}"}}},
       {"action": "notify.mobile_app_sm_s948w_vio", "continue_on_error": true, "data": {"message": "clear_notification", "data": {"tag": "{{ t }}"}}}
     ],
     "else": [
       {"action": "notify.mobile_app_sm_s948w_costea", "continue_on_error": true, "data": {"title": "Garage", "message": "{{ message }}", "data": {"tag": "{{ t }}", "actions": "{{ btns }}", "priority": "high", "ttl": 0, "channel": "Garage"}}},
       {"action": "notify.mobile_app_sm_s948w_vio", "continue_on_error": true, "data": {"title": "Garage", "message": "{{ message }}", "data": {"tag": "{{ t }}", "actions": "{{ btns }}", "priority": "high", "ttl": 0, "channel": "Garage"}}}
     ]}
  ]
}
```

- [ ] **Step 4: Create `ha/scripts/garage_status.json`**

```json
{
  "alias": "Garage: door status (read-only)",
  "description": "Report whether the garage door is open or closed. This tool cannot open or close the door.",
  "max": 5,
  "mode": "parallel",
  "object_id": "garage_status",
  "sequence": [
    {"variables": {
      "st": "{{ states('cover.msg100_7982_garage_door') }}",
      "mins": "{% set s = states.cover.msg100_7982_garage_door %}{{ (((as_timestamp(now()) - as_timestamp(s.last_changed)) // 60) | int) if s else 0 }}",
      "near_boot": "{% set s = states.cover.msg100_7982_garage_door %}{% set b = states.automation.garage_closed_cleanup %}{{ s is not none and b is not none and ((as_timestamp(s.last_changed) - as_timestamp(b.last_changed)) | abs) < 120 }}"
    }},
    {"variables": {"resp": {"chat_text": "{% if st == 'open' %}The garage door is open — {% if mins < 1 %}it just opened{% else %}it's been open for {{ 'at least ' if near_boot else '' }}{{ mins }} minute{{ '' if mins == 1 else 's' }}{% endif %}.{% elif st == 'closed' %}The garage door is closed.{% elif st in ['opening', 'closing'] and mins >= 1 %}The garage door has been {{ st }} for {{ mins }} minute{{ '' if mins == 1 else 's' }} — it may be stuck.{% elif st in ['opening', 'closing'] %}The garage door is {{ st }} right now.{% else %}I can't reach the garage door right now.{% endif %}"}}},
    {"response_variable": "resp", "stop": "done"}
  ]
}
```

- [ ] **Step 5: Canonicalize, then run the tests**

Run the canonicalizer (see File Structure), then: `python tests/test_ha_garage_policy.py -v`
Expected: all tests in `GarageFilesTest`, `NotifyScriptTest`, `StatusScriptTest` PASS.

- [ ] **Step 6: Add the test module to the py3.5 sweep and run it**

In `mass-resolver/tests/test_py35_compat.py`, append `"tests/test_ha_garage_policy.py"` to the `TEST_MODULES` list.
Run: `python tests/test_py35_compat.py -v` → Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add ../ha/scripts/garage_notify.json ../ha/scripts/garage_status.json tests/test_ha_garage_policy.py tests/test_py35_compat.py
git commit -m "feat(homebrain): HA-08 notify and read-only status scripts, with policy tests"
```

---

### Task 2: `garage_close_checked` — the only HA path that moves the door

**Files:**
- Create: `ha/scripts/garage_close_checked.json`
- Modify: `mass-resolver/tests/test_ha_garage_policy.py` (add `CloseScriptTest`; extend the canonical-file test to all three scripts)

**Interfaces:**
- Consumes: `script.garage_notify` (`tag: garage_result`, `message`).
- Produces: `script.garage_close_checked` with field `dry_run` (bool, default `false`). Variables `stable_open_s`
  (30) and `stuck_s` (60). Replies go to both phones under `garage_result` with no buttons.

- [ ] **Step 1: Write the failing tests** — in `GarageFilesTest`, change `for name in SCRIPTS[:1] + SCRIPTS[2:]:`
  to `for name in SCRIPTS:`, then add this class above `if __name__`:

```python
@unittest.skipUnless(os.path.isdir(HA), "ha/ tree not present")
class CloseScriptTest(unittest.TestCase):
    def setUp(self):
        self.obj = load("scripts", "garage_close_checked")[1]
        self.seq = self.obj["sequence"]

    def test_mode_single_and_silent(self):
        self.assertEqual(self.obj["mode"], "single")
        self.assertEqual(self.obj["max_exceeded"], "silent")

    def test_only_cover_action_is_one_close_of_the_door(self):
        covers = [d for d in actions_in(self.obj) if d["action"].startswith("cover.")]
        self.assertEqual(len(covers), 1)
        self.assertEqual(covers[0]["action"], "cover.close_cover")
        self.assertEqual(covers[0]["target"], {"entity_id": DOOR})

    def test_stable_open_guard_constants(self):
        vars0 = self.seq[0]["variables"]
        self.assertEqual(vars0["stable_open_s"], 30)
        self.assertEqual(vars0["stuck_s"], 60)

    def test_refusal_order(self):
        options = self.seq[1]["choose"]
        messages = []
        for opt in options:
            self.assertEqual(list(opt["sequence"][-1].keys()), ["stop"], "every refusal must stop the script")
            messages.append(opt["sequence"][0]["data"]["message"])
        expected_prefixes = [
            "Garage: already closed",
            "Garage: can't reach the door",
            "Garage is stuck",
            "Garage: already closing",
            "Garage: door is opening",
            "Garage: unexpected state",
            "Garage: obstruction detected",
            "Garage: door just opened",
        ]
        self.assertEqual(len(messages), len(expected_prefixes))
        for got, want in zip(messages, expected_prefixes):
            self.assertTrue(got.startswith(want), "%r should start with %r" % (got, want))

    def test_every_refusal_and_result_uses_result_tag_without_buttons(self):
        calls = notify_calls(self.obj)
        self.assertGreaterEqual(len(calls), 11)
        for d in calls:
            self.assertEqual(d["data"].get("tag"), "garage_result")
            self.assertNotIn("buttons", d["data"])

    def test_guard_and_dry_run_come_before_the_close(self):
        kinds = []
        for step in self.seq:
            if "choose" in step:
                kinds.append("refusals")
            elif "if" in step and "dry_run" in json.dumps(step["if"]):
                kinds.append("dry_run")
            elif step.get("action") == "cover.close_cover":
                kinds.append("close")
            elif "wait_template" in step:
                kinds.append("wait")
        self.assertEqual(kinds, ["refusals", "dry_run", "close", "wait"])

    def test_waits_60s_and_reports_both_outcomes_without_retry(self):
        wait = [s for s in self.seq if "wait_template" in s][0]
        self.assertEqual(wait["timeout"], "00:01:00")
        self.assertTrue(wait["continue_on_timeout"])
        final = self.seq[-1]
        self.assertIn("wait.completed", json.dumps(final["if"]))
        self.assertTrue(final["then"][0]["data"]["message"].startswith("Garage closed"))
        self.assertTrue(final["else"][0]["data"]["message"].startswith("Garage did NOT close"))
        closes = [d for d in actions_in(self.obj) if d["action"] == "cover.close_cover"]
        self.assertEqual(len(closes), 1, "no automatic retry")
```

- [ ] **Step 2: Run to verify it fails**

Run: `python tests/test_ha_garage_policy.py -v`
Expected: FAIL/ERROR — `garage_close_checked.json` not found.

- [ ] **Step 3: Create `ha/scripts/garage_close_checked.json`**

```json
{
  "alias": "Garage: close (checked)",
  "description": "HA-08, internal. The ONLY Home Assistant path that moves the garage door, and it can only close. Refuses unless the door has been stably open; verifies the result and reports it to both phones. Not exposed; called only by automation.garage_notification_action.",
  "fields": {
    "dry_run": {"default": false, "description": "Run every check and report 'would close' without moving the door.", "selector": {"boolean": {}}}
  },
  "max_exceeded": "silent",
  "mode": "single",
  "object_id": "garage_close_checked",
  "sequence": [
    {"variables": {
      "stable_open_s": 30,
      "stuck_s": 60,
      "st": "{{ states('cover.msg100_7982_garage_door') }}",
      "age_s": "{% set s = states.cover.msg100_7982_garage_door %}{{ ((as_timestamp(now()) - as_timestamp(s.last_changed)) | int) if s else 0 }}",
      "obstructed": "{{ state_attr('cover.msg100_7982_garage_door', 'obstruction-detected') in [true, 'true', 'True', 'on'] }}"
    }},
    {"choose": [
      {"conditions": [{"condition": "template", "value_template": "{{ st == 'closed' }}"}],
       "sequence": [{"action": "script.garage_notify", "data": {"tag": "garage_result", "message": "Garage: already closed ✓"}}, {"stop": "already closed"}]},
      {"conditions": [{"condition": "template", "value_template": "{{ st in ['unavailable', 'unknown'] }}"}],
       "sequence": [{"action": "script.garage_notify", "data": {"tag": "garage_result", "message": "Garage: can't reach the door — not closing."}}, {"stop": "unreachable"}]},
      {"conditions": [{"condition": "template", "value_template": "{{ st in ['opening', 'closing'] and age_s > stuck_s }}"}],
       "sequence": [{"action": "script.garage_notify", "data": {"tag": "garage_result", "message": "Garage is stuck ({{ st }}) — check it."}}, {"stop": "stuck"}]},
      {"conditions": [{"condition": "template", "value_template": "{{ st == 'closing' }}"}],
       "sequence": [{"action": "script.garage_notify", "data": {"tag": "garage_result", "message": "Garage: already closing."}}, {"stop": "already closing"}]},
      {"conditions": [{"condition": "template", "value_template": "{{ st == 'opening' }}"}],
       "sequence": [{"action": "script.garage_notify", "data": {"tag": "garage_result", "message": "Garage: door is opening — try again when it stops."}}, {"stop": "opening"}]},
      {"conditions": [{"condition": "template", "value_template": "{{ st != 'open' }}"}],
       "sequence": [{"action": "script.garage_notify", "data": {"tag": "garage_result", "message": "Garage: unexpected state ({{ st }}) — not closing."}}, {"stop": "unexpected state"}]},
      {"conditions": [{"condition": "template", "value_template": "{{ obstructed }}"}],
       "sequence": [{"action": "script.garage_notify", "data": {"tag": "garage_result", "message": "Garage: obstruction detected — not closing."}}, {"stop": "obstructed"}]},
      {"conditions": [{"condition": "template", "value_template": "{{ age_s < stable_open_s }}"}],
       "sequence": [{"action": "script.garage_notify", "data": {"tag": "garage_result", "message": "Garage: door just opened — try again in a moment."}}, {"stop": "not stably open"}]}
    ]},
    {"if": [{"condition": "template", "value_template": "{{ dry_run | default(false) | bool }}"}],
     "then": [{"action": "script.garage_notify", "data": {"tag": "garage_result", "message": "Garage: would close now (dry run)."}}, {"stop": "dry run"}]},
    {"action": "cover.close_cover", "target": {"entity_id": "cover.msg100_7982_garage_door"}},
    {"continue_on_timeout": true, "timeout": "00:01:00", "wait_template": "{{ is_state('cover.msg100_7982_garage_door', 'closed') }}"},
    {"if": [{"condition": "template", "value_template": "{{ wait.completed }}"}],
     "then": [{"action": "script.garage_notify", "data": {"tag": "garage_result", "message": "Garage closed ✓"}}],
     "else": [{"action": "script.garage_notify", "data": {"tag": "garage_result", "message": "Garage did NOT close — it's {{ states('cover.msg100_7982_garage_door') }}."}}]}
  ]
}
```

- [ ] **Step 4: Canonicalize and run** → `python tests/test_ha_garage_policy.py -v` → Expected: all PASS.

- [ ] **Step 5: Mutation check (the test must fail against a broken script).** Temporarily change `"stable_open_s": 30`
  to `0` and move the `obstructed` option after the `age_s` option. Run the tests: expected **two FAILs**
  (`test_stable_open_guard_constants`, `test_refusal_order`). Revert with `git checkout -- ../ha/scripts/garage_close_checked.json`
  and re-run: PASS.

- [ ] **Step 6: Commit**

```bash
git add ../ha/scripts/garage_close_checked.json tests/test_ha_garage_policy.py
git commit -m "feat(homebrain): HA-08 checked close script (stable-open guard, verify, no retry)"
```

---

### Task 3: The six automations

**Files:**
- Create: `ha/automations/garage_left_open.json`, `garage_bedtime_check.json`, `garage_opened_while_away.json`,
  `garage_notification_action.json`, `garage_closed_cleanup.json`, `garage_status_lost.json`
- Modify: `mass-resolver/tests/test_ha_garage_policy.py` (add `AutomationsTest`, `NotifyUsageTest`)

**Interfaces:**
- Consumes: `script.garage_notify`, `script.garage_close_checked`, `timer.garage_snooze`, `counter.garage_reminders`.
- Produces: automation ids equal to file names. `automation.garage_notification_action` is the kill switch.
  The **entity** `automation.garage_closed_cleanup`'s `last_changed` is the HA-start marker read by `script.garage_status`.

- [ ] **Step 1: Write the failing tests** — add above `if __name__`:

```python
BUTTONS_ALL = [{"action": "GARAGE_CLOSE", "title": "Close"},
               {"action": "GARAGE_SNOOZE_1H", "title": "Snooze 1 h"},
               {"action": "GARAGE_SNOOZE_3H", "title": "Snooze 3 h"}]
BUTTONS_CLOSE = [{"action": "GARAGE_CLOSE", "title": "Close"}]


def auto(name):
    return load("automations", name)[1]


@unittest.skipUnless(os.path.isdir(HA), "ha/ tree not present")
class AutomationsTest(unittest.TestCase):
    def test_files_exist_canonical_and_ids_match(self):
        import ha_export
        for name in AUTOMATIONS:
            raw, obj = load("automations", name)
            self.assertEqual(obj["automation_id"], name)
            self.assertEqual(obj["id"], name)
            self.assertEqual(raw, ha_export.render(obj), "%s is not canonical" % name)

    def test_left_open_trigger_states_and_timing(self):
        a = auto("garage_left_open")
        initial = [t for t in a["triggers"] if t.get("id") == "initial"][0]
        tick = [t for t in a["triggers"] if t.get("id") == "tick"][0]
        self.assertEqual(initial["to"], ALERT_STATES)
        self.assertEqual(initial["for"], {"hours": 0, "minutes": 15, "seconds": 0})
        self.assertEqual(tick["minutes"], "/15")
        self.assertEqual(a["conditions"], [{"condition": "state", "entity_id": DOOR, "state": ALERT_STATES}])
        tick_branch = [o for o in a["actions"][0]["choose"] if o["conditions"][0].get("id") == "tick"][0]
        text = json.dumps(tick_branch["conditions"])
        self.assertIn('"state": "idle"', text)
        self.assertIn("timer.garage_snooze", text)
        self.assertIn("< 4", text)
        self.assertIn(">= 900", text)

    def test_initial_alert_resets_counter(self):
        a = auto("garage_left_open")
        initial_branch = [o for o in a["actions"][0]["choose"] if o["conditions"][0].get("id") == "initial"][0]
        self.assertEqual(initial_branch["sequence"][0]["action"], "counter.reset")

    def test_left_open_alerts_carry_all_three_buttons(self):
        for d in notify_calls(auto("garage_left_open")):
            self.assertEqual(d["data"]["buttons"], BUTTONS_ALL)

    def test_bedtime_at_2100_ignores_snooze(self):
        a = auto("garage_bedtime_check")
        self.assertEqual(a["triggers"], [{"at": "21:00:00", "trigger": "time"}])
        self.assertEqual(a["conditions"], [{"condition": "state", "entity_id": DOOR, "state": ALERT_STATES}])
        self.assertNotIn("garage_snooze", json.dumps(a))
        self.assertEqual(notify_calls(a)[0]["data"]["buttons"], BUTTONS_CLOSE)

    def test_away_alert_requires_both_known_away_5min(self):
        a = auto("garage_opened_while_away")
        self.assertEqual(a["triggers"], [{"entity_id": DOOR, "from": "closed", "to": ["opening", "open"], "trigger": "state"}])
        conds = json.dumps(a["conditions"])
        for person in ("person.costea", "person.vio"):
            self.assertIn(person, conds)
        self.assertIn("['home', 'unknown', 'unavailable']", conds)
        self.assertEqual(conds.count(">= 300"), 2)
        self.assertEqual(notify_calls(a)[0]["data"]["buttons"], BUTTONS_CLOSE)

    def test_handler_parallel_and_exact_action_ids(self):
        a = auto("garage_notification_action")
        self.assertEqual(a["mode"], "parallel", "queued would re-run a duplicate Close after the first finishes")
        self.assertEqual(len(a["triggers"]), 3)
        ids = set()
        for t in a["triggers"]:
            self.assertEqual(t["trigger"], "event")
            self.assertEqual(t["event_type"], "mobile_app_notification_action")
            self.assertEqual(sorted(t["event_data"]), ["action"])
            ids.add(t["event_data"]["action"])
        self.assertEqual(ids, BUTTON_IDS)

    def test_snooze_refused_when_door_closed(self):
        a = auto("garage_notification_action")
        snooze = [o for o in a["actions"][0]["choose"] if "snooze_1h" in json.dumps(o["conditions"])][0]
        self.assertIn({"condition": "not", "conditions": [{"condition": "state", "entity_id": DOOR, "state": "closed"}]},
                      snooze["conditions"])

    def test_cleanup_runs_at_boot_and_only_acts_when_closed(self):
        a = auto("garage_closed_cleanup")
        self.assertIn({"event": "start", "id": "boot", "trigger": "homeassistant"}, a["triggers"])
        self.assertEqual(a["actions"][0]["if"], [{"condition": "state", "entity_id": DOOR, "state": "closed"}])

    def test_cleanup_clears_only_the_alert_tag(self):
        calls = notify_calls(auto("garage_closed_cleanup"))
        self.assertEqual(calls, [{"action": "script.garage_notify", "data": {"clear": True, "tag": "garage"}}])

    def test_status_lost_trigger_and_no_buttons(self):
        a = auto("garage_status_lost")
        self.assertEqual(a["triggers"], [{"entity_id": DOOR, "for": {"hours": 0, "minutes": 10, "seconds": 0},
                                          "from": ALERT_STATES, "to": ["unavailable", "unknown"], "trigger": "state"}])
        for d in notify_calls(a):
            self.assertNotIn("buttons", d["data"])


@unittest.skipUnless(os.path.isdir(HA), "ha/ tree not present")
class NotifyUsageTest(unittest.TestCase):
    def garage_objs(self):
        return [load("scripts", n)[1] for n in SCRIPTS] + [auto(n) for n in AUTOMATIONS]

    def test_only_notify_script_calls_notify_services(self):
        for obj in self.garage_objs():
            if obj.get("object_id") == "garage_notify":
                continue
            for d in actions_in(obj):
                self.assertFalse(d["action"].startswith("notify."), "%s sends directly" % d["action"])

    def test_result_tag_never_carries_buttons_and_buttons_only_on_alert_tag(self):
        for obj in self.garage_objs():
            for d in notify_calls(obj):
                tag = d["data"].get("tag", "garage")
                if tag == "garage_result":
                    self.assertNotIn("buttons", d["data"])
                if "buttons" in d["data"]:
                    self.assertEqual(tag, "garage")
```

- [ ] **Step 2: Run to verify it fails** → `python tests/test_ha_garage_policy.py -v` → Expected: ERROR, automation files not found.

- [ ] **Step 3: Create `ha/automations/garage_left_open.json`**

```json
{
  "actions": [{"choose": [
    {"conditions": [{"condition": "trigger", "id": "initial"}],
     "sequence": [
       {"action": "counter.reset", "target": {"entity_id": "counter.garage_reminders"}},
       {"action": "script.garage_notify", "data": {"message": "The garage door has been open for 15 minutes.", "buttons": [{"action": "GARAGE_CLOSE", "title": "Close"}, {"action": "GARAGE_SNOOZE_1H", "title": "Snooze 1 h"}, {"action": "GARAGE_SNOOZE_3H", "title": "Snooze 3 h"}]}}
     ]},
    {"conditions": [
       {"condition": "trigger", "id": "tick"},
       {"condition": "state", "entity_id": "timer.garage_snooze", "state": "idle"},
       {"condition": "template", "value_template": "{{ states('counter.garage_reminders') | int(0) < 4 }}"},
       {"condition": "template", "value_template": "{% set s = states.cover.msg100_7982_garage_door %}{{ s is not none and (as_timestamp(now()) - as_timestamp(s.last_changed)) >= 900 }}"}
     ],
     "sequence": [
       {"action": "counter.increment", "target": {"entity_id": "counter.garage_reminders"}},
       {"action": "script.garage_notify", "data": {"message": "The garage door is still open ({{ ((as_timestamp(now()) - as_timestamp(states.cover.msg100_7982_garage_door.last_changed)) // 60) | int }} min).", "buttons": [{"action": "GARAGE_CLOSE", "title": "Close"}, {"action": "GARAGE_SNOOZE_1H", "title": "Snooze 1 h"}, {"action": "GARAGE_SNOOZE_3H", "title": "Snooze 3 h"}]}}
     ]}
  ]}],
  "alias": "Garage: left-open alert",
  "automation_id": "garage_left_open",
  "conditions": [{"condition": "state", "entity_id": "cover.msg100_7982_garage_door", "state": ["open", "opening", "closing"]}],
  "description": "HA-08. Alerts both phones when the garage door has been not closed (open/opening/closing) for 15 min, then every 15 min up to 4 reminders, unless timer.garage_snooze is active. Never moves the door.",
  "id": "garage_left_open",
  "max_exceeded": "silent",
  "mode": "single",
  "triggers": [
    {"entity_id": "cover.msg100_7982_garage_door", "for": {"hours": 0, "minutes": 15, "seconds": 0}, "id": "initial", "to": ["open", "opening", "closing"], "trigger": "state"},
    {"id": "tick", "minutes": "/15", "trigger": "time_pattern"}
  ]
}
```

- [ ] **Step 4: Create `ha/automations/garage_bedtime_check.json`**

```json
{
  "actions": [{"action": "script.garage_notify", "data": {"message": "Bedtime check: the garage door is {{ states('cover.msg100_7982_garage_door') }}.", "buttons": [{"action": "GARAGE_CLOSE", "title": "Close"}]}}],
  "alias": "Garage: bedtime check (21:00)",
  "automation_id": "garage_bedtime_check",
  "conditions": [{"condition": "state", "entity_id": "cover.msg100_7982_garage_door", "state": ["open", "opening", "closing"]}],
  "description": "HA-08. At 21:00, if the garage door is not closed, alerts both phones with a Close button. Ignores the snooze. Never moves the door.",
  "id": "garage_bedtime_check",
  "mode": "single",
  "triggers": [{"at": "21:00:00", "trigger": "time"}]
}
```

- [ ] **Step 5: Create `ha/automations/garage_opened_while_away.json`**

```json
{
  "actions": [{"action": "script.garage_notify", "data": {"message": "The garage door opened while nobody is home.", "buttons": [{"action": "GARAGE_CLOSE", "title": "Close"}]}}],
  "alias": "Garage: opened while nobody is home",
  "automation_id": "garage_opened_while_away",
  "conditions": [
    {"condition": "template", "value_template": "{% set p = states.person.costea %}{{ p is not none and p.state not in ['home', 'unknown', 'unavailable'] and (as_timestamp(now()) - as_timestamp(p.last_changed)) >= 300 }}"},
    {"condition": "template", "value_template": "{% set p = states.person.vio %}{{ p is not none and p.state not in ['home', 'unknown', 'unavailable'] and (as_timestamp(now()) - as_timestamp(p.last_changed)) >= 300 }}"}
  ],
  "description": "HA-08. When the garage door starts opening from closed while person.costea and person.vio have both been away (known, not home) for at least 5 minutes, alerts both phones with a Close button. Never moves the door.",
  "id": "garage_opened_while_away",
  "max_exceeded": "silent",
  "mode": "single",
  "triggers": [{"entity_id": "cover.msg100_7982_garage_door", "from": "closed", "to": ["opening", "open"], "trigger": "state"}]
}
```

- [ ] **Step 6: Create `ha/automations/garage_notification_action.json`**

```json
{
  "actions": [{"choose": [
    {"conditions": [{"condition": "trigger", "id": "close"}],
     "sequence": [{"action": "script.garage_close_checked", "data": {"dry_run": false}}]},
    {"conditions": [
       {"condition": "trigger", "id": ["snooze_1h", "snooze_3h"]},
       {"condition": "not", "conditions": [{"condition": "state", "entity_id": "cover.msg100_7982_garage_door", "state": "closed"}]}
     ],
     "sequence": [{"action": "timer.start", "data": {"duration": "{{ '01:00:00' if trigger.id == 'snooze_1h' else '03:00:00' }}"}, "target": {"entity_id": "timer.garage_snooze"}}]}
  ]}],
  "alias": "Garage: notification button handler",
  "automation_id": "garage_notification_action",
  "description": "HA-08. Handles GARAGE_CLOSE / GARAGE_SNOOZE_1H / GARAGE_SNOOZE_3H taps. KILL SWITCH: disable this automation to stop all new remote closes (a close already running finishes within 60 s). Parallel so a Snooze tap is never blocked behind a close; a duplicate Close is dropped silently by the close script's mode single. Snooze is ignored if the door is already closed.",
  "id": "garage_notification_action",
  "max": 10,
  "mode": "parallel",
  "triggers": [
    {"event_data": {"action": "GARAGE_CLOSE"}, "event_type": "mobile_app_notification_action", "id": "close", "trigger": "event"},
    {"event_data": {"action": "GARAGE_SNOOZE_1H"}, "event_type": "mobile_app_notification_action", "id": "snooze_1h", "trigger": "event"},
    {"event_data": {"action": "GARAGE_SNOOZE_3H"}, "event_type": "mobile_app_notification_action", "id": "snooze_3h", "trigger": "event"}
  ]
}
```

- [ ] **Step 7: Create `ha/automations/garage_closed_cleanup.json`**

```json
{
  "actions": [{"if": [{"condition": "state", "entity_id": "cover.msg100_7982_garage_door", "state": "closed"}],
    "then": [
      {"action": "script.garage_notify", "data": {"clear": true, "tag": "garage"}},
      {"action": "timer.cancel", "target": {"entity_id": "timer.garage_snooze"}},
      {"action": "counter.reset", "target": {"entity_id": "counter.garage_reminders"}}
    ]}],
  "alias": "Garage: cleanup when closed",
  "automation_id": "garage_closed_cleanup",
  "description": "HA-08. When the garage door closes, or at HA start with it closed (covers a close missed while HA was down), clears the actionable 'garage' alert (never 'garage_result'), cancels the snooze and resets the reminder counter. This entity's last_changed marks HA start for script.garage_status; do not toggle it casually.",
  "id": "garage_closed_cleanup",
  "max": 5,
  "mode": "queued",
  "triggers": [
    {"entity_id": "cover.msg100_7982_garage_door", "id": "closed", "to": "closed", "trigger": "state"},
    {"event": "start", "id": "boot", "trigger": "homeassistant"}
  ]
}
```

- [ ] **Step 8: Create `ha/automations/garage_status_lost.json`**

```json
{
  "actions": [{"action": "script.garage_notify", "data": {"message": "Garage status lost — the door was last seen {{ trigger.from_state.state }} (not closed). Check it."}}],
  "alias": "Garage: status lost while not closed",
  "automation_id": "garage_status_lost",
  "description": "HA-08. If the garage door goes unavailable/unknown from a not-closed state and stays so for 10 min, alerts both phones. No buttons: an unreachable door cannot be closed. Offline-while-closed is unhandled until HA-06 ships.",
  "id": "garage_status_lost",
  "mode": "single",
  "triggers": [{"entity_id": "cover.msg100_7982_garage_door", "for": {"hours": 0, "minutes": 10, "seconds": 0}, "from": ["open", "opening", "closing"], "to": ["unavailable", "unknown"], "trigger": "state"}]
}
```

- [ ] **Step 9: Canonicalize and run** → `python tests/test_ha_garage_policy.py -v` → Expected: all PASS.

- [ ] **Step 10: Mutation check.** Temporarily delete the `"not"` condition from the snooze branch in
  `garage_notification_action.json`, and add `"unknown"` to `garage_left_open`'s `initial.to` list. Run: expected
  FAILs in `test_snooze_refused_when_door_closed` and `test_left_open_trigger_states_and_timing`. Revert with
  `git checkout -- ../ha/automations/` and re-run: PASS.

- [ ] **Step 11: Commit**

```bash
git add ../ha/automations/garage_*.json tests/test_ha_garage_policy.py
git commit -m "feat(homebrain): HA-08 alert, bedtime, away, handler, cleanup and status-lost automations"
```

---

### Task 4: Hard rules across the whole managed tree, and the manifest

**Files:**
- Modify: `mass-resolver/tests/test_ha_garage_policy.py` (add `HardRulesTest`, `ManifestTest`)
- Modify: `ha/MANIFEST.json` (append 3 scripts, 6 automations, keeping each list alphabetical)
- Modify: `mass-resolver/tests/test_ha_export.py:1082-1087` (`test_declared_counts_match_the_live_inventory_recorded_2026_09_06`
  pins the manifest counts on purpose; HA-08 changes them)

**Interfaces:**
- Consumes: every file under `ha/scripts/` and `ha/automations/` (garage and non-garage), `ha/exposure/assistants.json`.

- [ ] **Step 1: Write the failing tests** — add above `if __name__`:

```python
NON_ENTITY_TARGETS = ("area_id", "device_id", "floor_id", "label_id")


def entity_targets(d):
    """(entity_ids, has_non_entity_target) for a service-call dict, merging top level, target and data."""
    ents, other = [], False
    for src in (d, d.get("target"), d.get("data")):
        if not isinstance(src, dict):
            continue
        e = src.get("entity_id")
        if isinstance(e, str):
            ents.append(e)
        elif isinstance(e, list):
            ents.extend(str(x) for x in e)
        other = other or any(k in src for k in NON_ENTITY_TARGETS)
    return ents, other


def could_move_door(d):
    """True if this action might move THE GARAGE DOOR. Scoped to the door, not every cover.
    Provably safe only when it is a service call with explicit, literal entity ids that are not the door.
    Area/device/floor/label targets, templated or missing entity ids, 'all', and cover device actions
    (offline their device id cannot be resolved) cannot be proven safe, so they count; stage 3's live
    audit resolves the door's device id and is exact for device actions."""
    if is_device_action(d):
        return d.get("domain") == "cover" or DOOR in json.dumps(d)
    act = d.get("action") if isinstance(d.get("action"), str) else ""
    if not (act.startswith("cover.") or act in GENERIC_MOVES):
        return False
    ents, other = entity_targets(d)
    # Substring, not equality: a legacy comma-separated string "cover.a, cover.msg100_..." is one element.
    # Generic turn_on/toggle falls through to the same tail: homeassistant.turn_on on a cover OPENS it,
    # so "all", a template or a missing entity target is as risky there as on cover.*.
    return (any(DOOR in e for e in ents) or other or not ents or "all" in ents
            or any("{{" in e or "{%" in e for e in ents))


def moving_actions(obj):
    return [d for d in actions_in(obj) + device_actions_in(obj) if could_move_door(d)]


@unittest.skipUnless(os.path.isdir(HA), "ha/ tree not present")
class HardRulesTest(unittest.TestCase):
    def test_rule1_nothing_anywhere_opens_the_door(self):
        for label, obj in all_managed():
            for d in moving_actions(obj):
                self.assertNotIn(d.get("action"), FORBIDDEN_MOVES, "%s: %s could open/move the door" % (label, d))

    def test_rule2_only_the_close_script_can_move_the_door(self):
        for label, obj in all_managed():
            if label == "scripts/garage_close_checked.json":
                continue
            self.assertEqual(moving_actions(obj), [], "%s has an action that could move the door" % label)

    def test_could_move_door_is_scoped_to_the_door(self):
        other = "cover.living_room_blinds"
        safe = [{"action": "cover.close_cover", "target": {"entity_id": other}},
                {"action": "cover.open_cover", "target": {"entity_id": [other, "cover.bedroom_blinds"]}},
                {"action": "homeassistant.turn_on", "target": {"entity_id": "light.porch"}},
                {"action": "light.turn_on", "target": {"area_id": "garage"}}]
        risky = [{"action": "cover.close_cover", "target": {"entity_id": DOOR}},
                 {"action": "cover.open_cover", "data": {"entity_id": [other, DOOR]}},
                 {"action": "cover.close_cover", "target": {"area_id": "garage"}},
                 {"action": "cover.close_cover", "target": {"entity_id": "all"}},
                 {"action": "cover.close_cover", "target": {"entity_id": "{{ door }}"}},
                 {"action": "cover.close_cover"},
                 {"action": "homeassistant.toggle", "target": {"area_id": "garage"}},
                 {"action": "homeassistant.turn_on", "target": {"entity_id": "all"}},
                 {"action": "homeassistant.turn_on", "target": {"entity_id": "{{ door }}"}},
                 {"action": "cover.close_cover", "target": {"entity_id": "cover.a, " + DOOR}},
                 {"device_id": "abc", "domain": "cover", "entity_id": "0123uuid", "type": "open"}]
        for d in safe:
            self.assertFalse(could_move_door(d), d)
        for d in risky:
            self.assertTrue(could_move_door(d), d)

    def test_device_action_detector_sees_the_ui_shape(self):
        ui = {"actions": [{"device_id": "abc", "domain": "cover", "entity_id": DOOR, "type": "close"}],
              "conditions": [{"condition": "device", "device_id": "abc", "domain": "cover", "type": "is_open"}],
              "triggers": [{"trigger": "device", "device_id": "abc", "domain": "cover", "type": "opened"}]}
        found = device_actions_in(ui)
        self.assertEqual(found, [ui["actions"][0]], "only the action, not the device trigger/condition")

    def test_rule2_rule4_only_the_handler_invokes_the_close_script(self):
        for label, obj in all_managed():
            if label == "automations/garage_notification_action.json":
                continue
            text = json.dumps(obj)
            self.assertNotIn("garage_close_checked", text.replace('"object_id": "garage_close_checked"', ""),
                             "%s references the close script" % label)

    def test_rule3_only_status_script_may_be_exposed(self):
        with open(os.path.join(HA, "exposure", "assistants.json"), encoding="utf-8") as fh:
            exposed = json.load(fh)["exposed_entities"]
        garage = sorted(k for k in exposed if "garage" in k or k == DOOR)
        self.assertIn(garage, ([], ["script.garage_status"]))


@unittest.skipUnless(os.path.isdir(HA), "ha/ tree not present")
class ManifestTest(unittest.TestCase):
    def test_manifest_lists_every_garage_resource(self):
        with open(os.path.join(HA, "MANIFEST.json"), encoding="utf-8") as fh:
            m = json.load(fh)
        for name in SCRIPTS:
            self.assertIn(name, m["scripts"])
        for name in AUTOMATIONS:
            self.assertIn(name, m["automations"])
        self.assertEqual(m["scripts"], sorted(m["scripts"]))
        self.assertEqual(m["automations"], sorted(m["automations"]))
```

- [ ] **Step 2: Run** → `python tests/test_ha_garage_policy.py -v` → Expected: `ManifestTest` FAILS (garage entries
  missing). `HardRulesTest` passes: that is correct, because the rules already hold, and Step 5 proves the tests can fail.

- [ ] **Step 3: Update `ha/MANIFEST.json`** — LF-only, key order preserved, nothing else touched:

```bash
python - <<'PY'
import json
p = "../ha/MANIFEST.json"
with open(p, "rb") as fh:
    m = json.loads(fh.read().decode("utf-8"))
m["scripts"] = sorted(set(m["scripts"]) | {"garage_close_checked", "garage_notify", "garage_status"})
m["automations"] = sorted(set(m["automations"]) | {"garage_bedtime_check", "garage_closed_cleanup", "garage_left_open",
                                                   "garage_notification_action", "garage_opened_while_away", "garage_status_lost"})
with open(p, "wb") as fh:
    fh.write((json.dumps(m, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
PY
git diff --numstat -- ../ha/MANIFEST.json
```

Expected: `9 0` (nine added lines, none removed). Anything else means the snippet reformatted the file. Revert
(`git checkout -- ../ha/MANIFEST.json`) and insert the nine names by hand, LF-only.

- [ ] **Step 4: Update the pinned inventory count.** In `tests/test_ha_export.py`, rename
  `test_declared_counts_match_the_live_inventory_recorded_2026_09_06` to
  `test_declared_counts_match_the_live_inventory_recorded_2026_09_06_plus_ha08`, and change its `expected` line to:

```python
        expected = {"scripts": 19, "automations": 13, "pipelines": 5, "satellite_entities": 6}  # 2026-09-06 + HA-08 (3 scripts, 6 automations)
```

- [ ] **Step 5: Run both suites**

Run: `python tests/test_ha_garage_policy.py -v` → Expected: all PASS.
Run: `python tests/test_ha_export.py -v` → Expected: PASS, including `test_manifest_is_lf_only_with_a_trailing_newline`
and the renamed count test.

- [ ] **Step 6: Mutation checks.**
  1. Temporarily add `{"action": "cover.open_cover", "target": {"entity_id": "cover.msg100_7982_garage_door"}}` as the
     second-to-last step of `ha/scripts/garage_status.json`'s `sequence` (before the `stop`). Run: expected FAILs in
     `test_rule1_nothing_anywhere_opens_the_door`, `test_rule2_only_the_close_script_can_move_the_door` and
     `StatusScriptTest.test_read_only_no_actions_at_all`. Revert with `git checkout -- ../ha/scripts/garage_status.json` → PASS.
  2. **Scoping:** temporarily add the same step, but targeting `cover.some_other_cover`, to a **non-garage**
     automation (e.g. `ha/automations/ma_health_probe.json`'s `actions`). Run: the two rule tests **PASS**, because an
     explicit other cover is not a door path. Revert with `git checkout -- ../ha/automations/ma_health_probe.json`.

- [ ] **Step 7: Commit**

```bash
git add ../ha/MANIFEST.json tests/test_ha_garage_policy.py tests/test_ha_export.py
git commit -m "feat(homebrain): HA-08 hard-rule tests across all managed HA config; manifest entries"
```

---

### Task 5: `ha_apply.py` — push repo JSON with backup and read-back

**Files:**
- Create: `mass-resolver/tools/ha_apply.py`
- Create: `mass-resolver/tests/test_ha_apply.py`
- Modify: `mass-resolver/tests/test_py35_compat.py` (add `tools/ha_apply.py` to `MODULES` and `tests/test_ha_apply.py` to `TEST_MODULES`)

**Interfaces:**
- Produces: `load_resource(path) -> (kind, rid, body)` where `kind` ∈ {`script`, `automation`}; `apply_one(client, path, backup_dir, stamp, dry_run=False, delete=False, out=print)`;
  `main(argv=None, client=None, out=print) -> int`. Exit codes: 0 ok, 1 usage/file, 2 transport/HTTP, 3 read-back mismatch.
  The client must provide `request(method, path, obj=None) -> (status, json_or_None)`.
- CLI: `python tools/ha_apply.py --token-file PATH --backup-dir DIR [--dry-run | --delete] FILE [FILE ...]`

- [ ] **Step 1: Write the failing tests** — create `mass-resolver/tests/test_ha_apply.py`:

```python
#!/usr/bin/env python3
"""HA-08: ha_apply pushes repo-authored HA config with a backup and a read-back check.
Python 3.5-safe. Run: python tests/test_ha_apply.py
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "tools"))
import ha_apply  # noqa: E402


class FakeClient(object):
    def __init__(self, store=None, mutate_on_post=False, fail_status=None):
        self.store = dict(store or {})
        self.calls = []
        self.mutate_on_post = mutate_on_post
        self.fail_status = fail_status

    def request(self, method, path, obj=None):
        self.calls.append((method, path))
        if self.fail_status and method == "POST":
            return self.fail_status, {"_error_body": '{"message": "Message malformed: extra keys not allowed"}'}
        if method == "GET":
            return (200, json.loads(json.dumps(self.store[path]))) if path in self.store else (404, None)
        if method == "POST":
            body = json.loads(json.dumps(obj))
            if self.mutate_on_post:
                body["alias"] = "changed by server"
            self.store[path] = body
            return 200, {"result": "ok"}
        if method == "DELETE":
            self.store.pop(path, None)
            return 200, {"result": "ok"}
        raise AssertionError(method)


class ApplyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.bak = os.path.join(self.tmp, "bak")
        self.lines = []

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def write(self, name, obj):
        p = os.path.join(self.tmp, name)
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(obj, fh)
        return p

    def run_main(self, args, client):
        return ha_apply.main(["--backup-dir", self.bak] + args, client=client, out=self.lines.append)

    def test_script_body_strips_object_id(self):
        p = self.write("s.json", {"object_id": "garage_status", "alias": "x", "sequence": []})
        self.assertEqual(ha_apply.load_resource(p), ("script", "garage_status", {"alias": "x", "sequence": []}))

    def test_automation_keeps_id_and_strips_automation_id(self):
        p = self.write("a.json", {"automation_id": "garage_left_open", "id": "garage_left_open", "alias": "x"})
        self.assertEqual(ha_apply.load_resource(p),
                         ("automation", "garage_left_open", {"id": "garage_left_open", "alias": "x"}))

    def test_rejects_ambiguous_or_mismatched_ids(self):
        for obj in ({"alias": "x"}, {"object_id": "a", "automation_id": "a", "id": "a"},
                    {"automation_id": "a", "id": "b"}, {"object_id": "a/b"}):
            p = self.write("bad.json", obj)
            with self.assertRaises(ha_apply.ApplyError) as cm:
                ha_apply.load_resource(p)
            self.assertEqual(cm.exception.code, 1)

    def test_new_resource_posted_and_read_back(self):
        p = self.write("s.json", {"object_id": "garage_notify", "alias": "n"})
        c = FakeClient()
        self.assertEqual(self.run_main([p], c), 0)
        self.assertEqual(c.store["/api/config/script/config/garage_notify"], {"alias": "n"})
        self.assertFalse(os.path.isdir(self.bak), "nothing to back up for a new resource")

    def test_existing_resource_backed_up_before_overwrite(self):
        path = "/api/config/automation/config/garage_left_open"
        c = FakeClient({path: {"id": "garage_left_open", "alias": "old"}})
        p = self.write("a.json", {"automation_id": "garage_left_open", "id": "garage_left_open", "alias": "new"})
        self.assertEqual(self.run_main([p], c), 0)
        files = os.listdir(self.bak)
        self.assertEqual(len(files), 1)
        self.assertTrue(files[0].startswith("automation-garage_left_open-"))
        with open(os.path.join(self.bak, files[0]), encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["alias"], "old")
        self.assertEqual(c.store[path]["alias"], "new")
        self.assertLess(c.calls.index(("GET", path)), c.calls.index(("POST", path)))

    def test_dry_run_sends_nothing(self):
        p = self.write("s.json", {"object_id": "garage_notify", "alias": "n"})
        c = FakeClient()
        self.assertEqual(self.run_main(["--dry-run", p], c), 0)
        self.assertEqual([m for m, _ in c.calls], ["GET"])

    def test_read_back_mismatch_is_exit_3(self):
        p = self.write("s.json", {"object_id": "garage_notify", "alias": "n"})
        self.assertEqual(self.run_main([p], FakeClient(mutate_on_post=True)), 3)

    def test_http_error_is_exit_2_and_reports_the_servers_reason(self):
        p = self.write("s.json", {"object_id": "garage_notify", "alias": "n"})
        self.assertEqual(self.run_main([p], FakeClient(fail_status=400)), 2)
        self.assertIn("extra keys not allowed", self.lines[-1])

    def test_delete_backs_up_removes_and_verifies(self):
        path = "/api/config/script/config/garage_status"
        c = FakeClient({path: {"alias": "s"}})
        p = self.write("s.json", {"object_id": "garage_status", "alias": "s"})
        self.assertEqual(self.run_main(["--delete", p], c), 0)
        self.assertNotIn(path, c.store)
        self.assertEqual(len(os.listdir(self.bak)), 1)

    def test_delete_of_absent_resource_is_a_no_op(self):
        p = self.write("s.json", {"object_id": "garage_status", "alias": "s"})
        c = FakeClient()
        self.assertEqual(self.run_main(["--delete", p], c), 0)
        self.assertNotIn("DELETE", [m for m, _ in c.calls])

    def test_dry_run_and_delete_are_exclusive(self):
        p = self.write("s.json", {"object_id": "garage_status"})
        self.assertEqual(self.run_main(["--dry-run", "--delete", p], FakeClient()), 1)

    def test_read_token_accepts_prefix_and_rejects_empty(self):
        p = os.path.join(self.tmp, "tok")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write("token: abc123\n")
        self.assertEqual(ha_apply.read_token(p), "abc123")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write("\n")
        with self.assertRaises(ha_apply.ApplyError):
            ha_apply.read_token(p)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify it fails** → `python tests/test_ha_apply.py -v` → Expected: `ImportError: No module named 'ha_apply'`.

- [ ] **Step 3: Create `mass-resolver/tools/ha_apply.py`**

```python
#!/usr/bin/env python3
"""HA-08: push repo-authored Home Assistant scripts/automations (canonical JSON under docs/homebrain/ha/)
to the live instance, backing up whatever is overwritten and reading the result back.

Runs from the operator workstation, not the host. Python 3.5-safe (no f-strings).

  python tools/ha_apply.py --token-file PATH --backup-dir DIR [--dry-run | --delete] FILE [FILE ...]

Exit codes: 0 ok, 1 usage or file error, 2 transport or HTTP error, 3 read-back mismatch.
The token is never printed.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

DEFAULT_BASE = "http://192.168.1.104:8123"


class ApplyError(Exception):
    def __init__(self, code, message):
        Exception.__init__(self, message)
        self.code = code


def load_resource(path):
    """-> (kind, rid, body): kind 'script' or 'automation'; body is what HA's config API stores."""
    with open(path, encoding="utf-8") as fh:
        obj = json.load(fh)
    if not isinstance(obj, dict):
        raise ApplyError(1, "%s: not a JSON object" % path)
    is_script = "object_id" in obj
    is_auto = "automation_id" in obj
    if is_script == is_auto:
        raise ApplyError(1, "%s: needs exactly one of object_id / automation_id" % path)
    if is_script:
        kind, rid = "script", obj["object_id"]
    else:
        kind, rid = "automation", obj["automation_id"]
        if obj.get("id") != rid:
            raise ApplyError(1, "%s: id %r does not match automation_id %r" % (path, obj.get("id"), rid))
    if not isinstance(rid, str) or not rid or "/" in rid:
        raise ApplyError(1, "%s: invalid id %r" % (path, rid))
    body = dict((k, v) for k, v in obj.items() if k not in ("object_id", "automation_id"))
    return kind, rid, body


class HttpClient(object):
    def __init__(self, base, token, timeout=20):
        self.base = base.rstrip("/")
        self.token = token
        self.timeout = timeout

    def request(self, method, path, obj=None):
        data = None if obj is None else json.dumps(obj).encode("utf-8")
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"Authorization": "Bearer " + self.token,
                                              "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
                return resp.status, (json.loads(raw.decode("utf-8")) if raw else None)
        except urllib.error.HTTPError as err:
            # HA's config API explains a rejection in the body ({"message": ...}); keep it for the error text.
            detail = err.read().decode("utf-8", "replace")[:500]
            return err.code, {"_error_body": detail}
        except (urllib.error.URLError, OSError) as err:
            raise ApplyError(2, "transport error on %s %s: %s" % (method, path, err))


def config_path(kind, rid):
    return "/api/config/%s/config/%s" % (kind, rid)


def why(resp):
    """The server's explanation of an error response, if it sent one."""
    if isinstance(resp, dict) and resp.get("_error_body"):
        return ": %s" % resp["_error_body"]
    return ""


def backup(client, kind, rid, backup_dir, stamp):
    """Save the live config before touching it. -> backup path, or None if the resource does not exist."""
    status, current = client.request("GET", config_path(kind, rid))
    if status == 404:
        return None
    if status != 200:
        raise ApplyError(2, "GET %s -> HTTP %s%s" % (config_path(kind, rid), status, why(current)))
    if not os.path.isdir(backup_dir):
        os.makedirs(backup_dir)
    path = os.path.join(backup_dir, "%s-%s-%s.json" % (kind, rid, stamp))
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(current, fh, sort_keys=True, indent=2, ensure_ascii=False)
        fh.write("\n")
    return path


def apply_one(client, path, backup_dir, stamp, dry_run=False, delete=False, out=print):
    kind, rid, body = load_resource(path)
    saved = backup(client, kind, rid, backup_dir, stamp)
    out("%s %s.%s backup=%s" % ("DELETE" if delete else "APPLY", kind, rid, saved or "none (not present)"))
    if dry_run:
        out("  dry-run: nothing sent")
        return
    if delete:
        if saved is None:
            out("  not present: nothing to delete")
            return
        status, resp = client.request("DELETE", config_path(kind, rid))
        if status != 200:
            raise ApplyError(2, "DELETE %s -> HTTP %s%s" % (config_path(kind, rid), status, why(resp)))
        status, _ = client.request("GET", config_path(kind, rid))
        if status != 404:
            raise ApplyError(3, "%s.%s still present after DELETE (HTTP %s)" % (kind, rid, status))
        out("  deleted")
        return
    status, resp = client.request("POST", config_path(kind, rid), body)
    if status != 200:
        raise ApplyError(2, "POST %s -> HTTP %s%s" % (config_path(kind, rid), status, why(resp)))
    status, back = client.request("GET", config_path(kind, rid))
    if status != 200 or back != body:
        raise ApplyError(3, "%s.%s read-back differs from %s" % (kind, rid, path))
    out("  applied; read-back matches the file")


def read_token(path):
    with open(path, encoding="utf-8-sig") as fh:
        raw = fh.read().strip()
    token = raw.split(":", 1)[1].strip() if raw.lower().startswith("token:") else raw
    if not token:
        raise ApplyError(1, "token file is empty")
    return token


def main(argv=None, client=None, out=print):
    ap = argparse.ArgumentParser(description="Push repo-authored HA scripts/automations with backup + read-back.")
    ap.add_argument("--token-file")
    ap.add_argument("--base", default=DEFAULT_BASE)
    ap.add_argument("--backup-dir", required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--delete", action="store_true")
    ap.add_argument("files", nargs="+")
    args = ap.parse_args(argv)
    if args.dry_run and args.delete:
        out("ERROR: --dry-run and --delete are exclusive")
        return 1
    stamp = time.strftime("%Y%m%d-%H%M%S")
    try:
        if client is None:
            if not args.token_file:
                raise ApplyError(1, "--token-file is required")
            client = HttpClient(args.base, read_token(args.token_file))
        for path in args.files:
            apply_one(client, path, args.backup_dir, stamp, args.dry_run, args.delete, out)
    except ApplyError as err:
        out("ERROR: %s" % err)
        return err.code
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run** → `python tests/test_ha_apply.py -v` → Expected: all PASS.

- [ ] **Step 5: Update the py3.5 sweep** — add `"tools/ha_apply.py"` to `MODULES` and `"tests/test_ha_apply.py"` to
  `TEST_MODULES` in `tests/test_py35_compat.py`. Run: `python tests/test_py35_compat.py -v` → PASS.

- [ ] **Step 6: Commit**

```bash
git add tools/ha_apply.py tests/test_ha_apply.py tests/test_py35_compat.py
git commit -m "feat(homebrain): ha_apply — push repo HA config with backup and read-back"
```

---

### Review checkpoint (before any live task)

A fresh reviewer, on the most capable model, reviews the committed Tasks 1–5: the 9 configs, the policy tests,
`ha_apply.py` and its tests. The brief is this plan, the spec, and `git diff origin/main...HEAD`. This is the last
point where a wrong config can be caught without a live HA object to roll back. Findings are fixed and re-tested
(`python -m unittest discover -s tests -p "test_*.py"`) before Task 6. A second, short review at the very end covers
the records and docs (Task 9).

## Live stages

**Workstation preflight (once, before Task 6):**
- `python -c "import websockets; print(websockets.__version__)"` must print a version. The stage snippets use it; if
  it's missing, stop and ask the operator (don't install packages unprompted).
- If a heredoc fails from the agent's Bash tool with exit 127, the login profile is at fault (memory
  `reference_bash_profile_breaks_cli`). Run it through PowerShell as `bash --noprofile --norc -c '…'` or a script file.

**Before any live task:** the operator has approved starting the stage. The operator provides an HA long-lived token
in a local file (`$HA_TOKEN_FILE`, never inside the repo), and loads the SSH key for exporter runs
(`ssh-add ~/.ssh/id_homebrain`). Backups go to `$HOME/homebrain-backups/ha08` (outside the repo, and persistent,
unlike a session scratchpad). Every command's output is inspected before the next. **Stop on any unexpected
result** and report it; do not improvise a workaround on a live system.

**Exporter round-trip** (used at the end of every live stage — runbook `runbooks/ha-managed-state-export.md` §5):

```bash
scp ../ha/MANIFEST.json costea@192.168.1.68:ha-state/MANIFEST.json
ssh costea@192.168.1.68 'python3 ~/mass-resolver/tools/ha_export.py --manifest ~/ha-state/MANIFEST.json --out ~/ha-state/managed'
scp -r costea@192.168.1.68:ha-state/managed/. ../ha/
git add -N ../ha && git diff --stat -- ../ha && git diff -- ../ha
```

Pass condition: exit 0, and `git diff -- ../ha` shows **only** the changes expected for the stage (listed per task).
A diff in any garage file means live differs from the reviewed repo copy. Stop and investigate.

---

### Task 6: Stage 1 — gate claim, helpers, `garage_notify`, `garage_status` (not exposed), measurement

**Files:**
- Modify: `BACKLOG.md` §10 (claim), `CHANGELOG.md` (stage-1 entry)

- [ ] **Step 1: Claim the gate.** In `BACKLOG.md` §10, set the row's holder to
  **`HA-08`** (`homebrain/ha-08-garage-design`), and the status to **"CLAIMED <date> for the HA-08 garage rollout (HA-live
  + exposure; stages 1–4 per the spec §6.2)"**, keeping the prior text after "Prior:". `git diff --numstat` shows
  `1 1`. Commit `docs(homebrain): HA-08 claims the HA-live/exposure gate` and **push before any live call**.

- [ ] **Step 2: Create the helpers** (WS; run from `mass-resolver/` with the workstation Python):

```bash
python - "$HA_TOKEN_FILE" <<'PY'
import asyncio, json, sys, websockets
raw = open(sys.argv[1], encoding="utf-8-sig").read().strip()
tok = raw.split(":", 1)[1].strip() if raw.lower().startswith("token:") else raw
async def main():
    async with websockets.connect("ws://192.168.1.104:8123/api/websocket") as ws:
        await ws.recv(); await ws.send(json.dumps({"type": "auth", "access_token": tok})); await ws.recv()
        for i, msg in enumerate([
            {"type": "timer/create", "name": "garage_snooze", "duration": "01:00:00", "restore": True, "icon": "mdi:garage-alert"},
            {"type": "counter/create", "name": "garage_reminders", "initial": 0, "step": 1, "minimum": 0, "maximum": 10, "restore": True, "icon": "mdi:counter"},
        ], 1):
            msg["id"] = i; await ws.send(json.dumps(msg)); print(json.loads(await ws.recv()))
asyncio.run(main())
PY
```

Expected: two `"success": true` results. Then check `GET /api/states/timer.garage_snooze` → `idle`, and
`counter.garage_reminders` → `0`. If an entity id differs, **stop**: every file references these exact ids.

⚠️ **`timer/create` / `counter/create` are the frontend's helper-editor WS commands, not a documented public API.**
Treat this step as a live compatibility check. If either call fails (error, or `success: false`), **do not
improvise payloads.** Use the **UI fallback**: Settings → Devices & services → Helpers → *Create helper* →
**Timer**, name `garage_snooze`, duration `01:00:00`, *Restore* on, then **Counter**, name `garage_reminders`,
initial 0, step 1, minimum 0, maximum 10, *Restore* on. Re-check both entity ids and states as above, and record in
the CHANGELOG which path created them.

- [ ] **Step 3: Push the two scripts**

```bash
python tools/ha_apply.py --token-file "$HA_TOKEN_FILE" --backup-dir "$HOME/homebrain-backups/ha08" --dry-run ../ha/scripts/garage_notify.json ../ha/scripts/garage_status.json
python tools/ha_apply.py --token-file "$HA_TOKEN_FILE" --backup-dir "$HOME/homebrain-backups/ha08" ../ha/scripts/garage_notify.json ../ha/scripts/garage_status.json
```

Expected: `backup=none (not present)` for both, then `applied; read-back matches the file` for both, exit 0.

- [ ] **Step 4: Confirm nothing garage-related is exposed.** WS `homeassistant/expose_entity/list`: the exposed set is
  exactly the 14 entities of `ha/exposure/assistants.json`. `script.garage_notify` and `script.garage_status` are
  absent (`expose_new_entities` is off).

- [ ] **Step 5: Test notifications, both tags** (operator watches both phones). Call `script.garage_notify` via REST
  `POST /api/services/script/garage_notify` four times, waiting for the operator's confirmation after each:
  1. `{"message": "HA-08 test: alert with buttons", "buttons": [{"action": "GARAGE_SNOOZE_1H", "title": "Snooze 1 h"}]}` → both phones show it with one button. **Do not tap it** (no handler exists yet).
  2. `{"message": "HA-08 test: result", "tag": "garage_result", "buttons": [{"action": "GARAGE_CLOSE", "title": "Close"}]}` → shows **without any button** (the script drops them), and #1 is still visible.
  3. `{"clear": true, "tag": "garage"}` → #1 disappears and #2 stays.
  4. `{"clear": true, "tag": "garage_result"}` → #2 disappears.
  Record the result per phone. A missing button or a failed replace/clear → **stop** (spec §7).

- [ ] **Step 6: Run the status script in each real state.** `POST /api/services/script/garage_status?return_response=true`
  with the door closed → `"The garage door is closed."`. The operator opens the door; after it settles, the same call
  → `"The garage door is open — it just opened."`, and after 1+ min → `"…open for 1 minute."`.

- [ ] **Step 7: Measure the transitions (3 cycles).** Start this watcher in the background (it prints every state
  change of the door, with timestamps, for 15 min), then have the operator do **3** open→close cycles at a normal pace:

```bash
python - "$HA_TOKEN_FILE" <<'PY' > "$HOME/homebrain-backups/ha08/door-transitions.txt"
import asyncio, json, sys, time, websockets
raw = open(sys.argv[1], encoding="utf-8-sig").read().strip()
tok = raw.split(":", 1)[1].strip() if raw.lower().startswith("token:") else raw
async def main():
    async with websockets.connect("ws://192.168.1.104:8123/api/websocket") as ws:
        await ws.recv(); await ws.send(json.dumps({"type": "auth", "access_token": tok})); await ws.recv()
        await ws.send(json.dumps({"id": 1, "type": "subscribe_trigger", "trigger": {"trigger": "state", "entity_id": "cover.msg100_7982_garage_door"}}))
        end = time.time() + 900
        while time.time() < end:
            try:
                m = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            except asyncio.TimeoutError:
                continue
            v = (m.get("event") or {}).get("variables", {}).get("trigger", {})
            if v:
                fs, ts = v["from_state"], v["to_state"]
                kind = "ATTR-ONLY" if fs["state"] == ts["state"] else "STATE"
                # last_updated moves on every write; last_changed only on a state change, so it would
                # misdate attribute-only lines (e.g. obstruction-detected flipping).
                print(ts["last_updated"], kind, fs["state"], "->", ts["state"],
                      "obstruction=%s" % ts["attributes"].get("obstruction-detected"), flush=True)
asyncio.run(main())
PY
```

From the file, ignoring `ATTR-ONLY` lines when timing transitions, record per cycle: whether `opening`/`closing` appear at all, how long each lasts, and the full
travel time (closed→open settled, open→closed). **T = max(30, longest full travel + 10) seconds.** If T > 30, update
`stable_open_s` in `ha/scripts/garage_close_checked.json` **and** the constant in `test_stable_open_guard_constants`,
canonicalize, run the policy tests, and commit (`fix(homebrain): HA-08 stable-open guard T=<n>s from stage-1 measurement`)
**before Task 8**. Record whether `opening` ever lasts ≥ 60 s. If it never does, the stuck-on-opening wording is
never reached, which the spec accepts.

- [ ] **Step 8: Operator turns HA's temporary debug logging off** (Developer Tools → Actions):

```yaml
action: logger.set_level
data:
  zeroconf: warning
  homeassistant.components.zeroconf: warning
  homeassistant.components.homekit_controller: warning
  aiohomekit: warning
```

Verify: `GET /api/hassio/core/logs?lines=200` contains no new `DEBUG (MainThread) [zeroconf]` lines after the change.

- [ ] **Step 9: Exporter round-trip.** Expected diff: **none** in the two garage scripts, which now exist in the export
  exactly as authored (the manifest already listed them). The manifest's six automations do not exist in HA yet, so
  the export **exits 5**. That is expected at stage 1. Run instead with a temporary manifest limited to stage-1 resources:

```bash
# Not /tmp: inside Python on Windows that resolves to C:\tmp, which does not exist. Pass a real path as argv.
python - "$HOME/homebrain-backups/ha08/manifest-stage1.json" <<'PY'
import json, sys
m = json.load(open("../ha/MANIFEST.json", encoding="utf-8"))
m["automations"] = [a for a in m["automations"] if not a.startswith("garage_")]
open(sys.argv[1], "wb").write((json.dumps(m, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
print("wrote", sys.argv[1])
PY
scp "$HOME/homebrain-backups/ha08/manifest-stage1.json" costea@192.168.1.68:ha-state/MANIFEST.json
ssh costea@192.168.1.68 'python3 ~/mass-resolver/tools/ha_export.py --manifest ~/ha-state/MANIFEST.json --out ~/ha-state/managed'
scp costea@192.168.1.68:ha-state/managed/scripts/garage_notify.json costea@192.168.1.68:ha-state/managed/scripts/garage_status.json ../ha/scripts/
git diff --exit-code -- ../ha/scripts/garage_notify.json ../ha/scripts/garage_status.json && echo ROUNDTRIP_OK
```

Expected: `ROUNDTRIP_OK`.

- [ ] **Step 10: CHANGELOG stage-1 entry.** Add a `## <date> — HA-08 stage 1: garage helpers, notify and status scripts (not exposed)`
  entry at the top. It records: the gate claim; **both helpers by name with their full create payloads from Step 2**
  (they are outside the managed export — spec §6.3); the two scripts and the `ROUNDTRIP_OK`; the per-phone results of
  the four notification tests; the transition measurements (per cycle) and the chosen T; debug logging turned off.
  `git diff --numstat` → `N 0`. Commit `docs(homebrain): HA-08 stage 1 record` and push.

---

### Task 7: Stage 2 — alerts live, Snooze only (no *Close* anywhere)

**Files:**
- Modify: `CHANGELOG.md` (stage-2 entry)

- [ ] **Step 1: Build the stage-2 variants** (outside the repo; never committed). No button can offer *Close*, the
  handler has no close branch, and thresholds are 1 min for the test:

```bash
mkdir -p "$HOME/homebrain-backups/ha08/stage2" && python - "$HOME/homebrain-backups/ha08/stage2" <<'PY'
import json, os, sys
out = sys.argv[1]; src = "../ha/automations/"
def strip_close(node):
    if isinstance(node, dict):
        if isinstance(node.get("buttons"), list):
            node["buttons"] = [b for b in node["buttons"] if b.get("action") != "GARAGE_CLOSE"]
        for v in node.values(): strip_close(v)
    elif isinstance(node, list):
        for v in node: strip_close(v)
for name in ["garage_left_open", "garage_bedtime_check", "garage_opened_while_away", "garage_notification_action", "garage_closed_cleanup", "garage_status_lost"]:
    obj = json.load(open(src + name + ".json", encoding="utf-8"))
    strip_close(obj)
    if name == "garage_opened_while_away":
        obj["actions"][0]["data"].pop("buttons")          # its only button was Close
    if name == "garage_bedtime_check":
        obj["actions"][0]["data"].pop("buttons")
    if name == "garage_notification_action":
        obj["triggers"] = [t for t in obj["triggers"] if t["id"] != "close"]
        obj["actions"][0]["choose"] = [o for o in obj["actions"][0]["choose"] if o["conditions"][0].get("id") != "close"]
    if name == "garage_left_open":
        text = json.dumps(obj)
        for a, b, n in [('"minutes": 15', '"minutes": 1', 1), ('"/15"', '"/1"', 1), (">= 900", ">= 60", 1),
                        ("open for 15 minutes", "open for 1 minute (TEST)", 1)]:
            assert text.count(a) == n, (a, text.count(a)); text = text.replace(a, b)
        obj = json.loads(text)
    behaviour = json.dumps([obj.get("triggers"), obj.get("conditions"), obj.get("actions")])  # not description text
    assert "GARAGE_CLOSE" not in behaviour and "garage_close_checked" not in behaviour, name
    json.dump(obj, open(os.path.join(out, name + ".json"), "w", encoding="utf-8"), indent=2, ensure_ascii=False)
print("ok")
PY
```

Expected: `ok`. If any assertion fires, **stop**: the repo files changed shape since this plan was written.

- [ ] **Step 2: Push the variants**

```bash
python tools/ha_apply.py --token-file "$HA_TOKEN_FILE" --backup-dir "$HOME/homebrain-backups/ha08" "$HOME"/homebrain-backups/ha08/stage2/*.json
```

Expected: six `applied; read-back matches`, exit 0.

- [ ] **Step 3: Live checks with the operator** (door closed at start; record each result):
  1. Open the door. After ~1 min: both phones get "open for 1 minute (TEST)" with **Snooze 1 h / Snooze 3 h** only.
     Check the `garage_left_open` trace (Settings → Automations → trace): it fired ~1 min after the state became
     `open`, not after `opening` (spec §4.1; record which).
  2. Leave it open: reminders arrive on the `/1` ticks, `counter.garage_reminders` goes 1→4, and a 5th tick sends
     nothing.
  3. Close the door: the alert disappears from both phones, the counter goes to `0`, and `timer.garage_snooze` is `idle`.
  4. Open again → first alert → tap **Snooze 1 h** on one phone: the timer is `active`; no reminders for 3 ticks. Then
     set `timer.garage_snooze` to finish (`timer.finish`) → the next tick sends a reminder. Close the door.
  5. **Review Focus 1:** with the door **closed**, fire the tap event directly:
     `POST /api/events/mobile_app_notification_action` with body `{"action": "GARAGE_SNOOZE_1H"}` → the handler's
     trace shows a run whose snooze branch did not match, and `timer.garage_snooze` **stays `idle`**.
  6. **Review Focus 5:** `POST /api/events/mobile_app_notification_action` with `{"action": "GARAGE_SNOOZE_1H_X"}`
     → the handler's trace list shows **no new run**.
  7. Bedtime: temporarily set `garage_bedtime_check`'s trigger time 2 min ahead (edit the stage-2 variant file, then
     `ha_apply` it), with the door open → alert with **no** buttons; then re-apply the stage-2 variant with 21:00.
  8. Away: skip unless both phones are genuinely away. Otherwise it's covered by the Task 3 tests. Record "not exercised live".

- [ ] **Step 4: Restore production thresholds (still no *Close*).** Rebuild the variants with Step 1's script but
  **without** the `garage_left_open` threshold replacement (delete that `if` block), re-apply, and confirm that
  `garage_left_open` now reads `"minutes": 15` and `"/15"` via `GET /api/config/automation/config/garage_left_open`.

- [ ] **Step 5: CHANGELOG stage-2 entry.** Record the results of checks 1–8 (with the §4.1 trace observation), that the
  stage-2 variants (no *Close*) are what's live, and the backup paths `ha_apply` printed. Commit and push.

---

### Task 8: Stage 3 — preflight audit, close script, *Close* buttons (operator at the garage)

**Files:**
- Modify: `CHANGELOG.md` (stage-3 entry)

- [ ] **Step 1: Preflight audit (read-only; spec §6.2).** Run this over the **live** config of every script and
  automation in HA (not only the managed ones):

```bash
python - "$HA_TOKEN_FILE" <<'PY'
import json, sys, urllib.request
raw = open(sys.argv[1], encoding="utf-8-sig").read().strip()
tok = raw.split(":", 1)[1].strip() if raw.lower().startswith("token:") else raw
H = {"Authorization": "Bearer " + tok}; B = "http://192.168.1.104:8123"; DOOR = "cover.msg100_7982_garage_door"
def get(p):
    return json.loads(urllib.request.urlopen(urllib.request.Request(B + p, headers=H), timeout=20).read())
GENERIC = ("homeassistant.turn_on", "homeassistant.turn_off", "homeassistant.toggle")
def walk(n):
    if isinstance(n, dict):
        yield n
        for v in n.values():
            for s in walk(v): yield s
    elif isinstance(n, list):
        for v in n:
            for s in walk(v): yield s
# The door's device id: a UI "device action" names the device, not always the entity.
import asyncio, urllib.error, websockets
async def device_id():
    async with websockets.connect("ws://192.168.1.104:8123/api/websocket") as ws:
        await ws.recv(); await ws.send(json.dumps({"type": "auth", "access_token": tok})); await ws.recv()
        await ws.send(json.dumps({"id": 1, "type": "config/entity_registry/get", "entity_id": DOOR}))
        return json.loads(await ws.recv())["result"]["device_id"]
DEV = asyncio.run(device_id())
print("door device_id resolved:", bool(DEV))
bad, skipped, checked = [], [], 0
for s in get("/api/states"):
    eid = s["entity_id"]
    try:
        if eid.startswith("script."):
            cfg = get("/api/config/script/config/" + eid.split(".", 1)[1])
        elif eid.startswith("automation.") and s["attributes"].get("id"):
            cfg = get("/api/config/automation/config/" + s["attributes"]["id"])
        elif eid.startswith("automation."):
            skipped.append(eid + " (no id attribute)"); continue
        else:
            continue
    except urllib.error.HTTPError as e:              # YAML-defined scripts/automations are not in the config API
        skipped.append("%s (HTTP %s)" % (eid, e.code)); continue
    checked += 1
    for d in walk(cfg):
        act = d.get("action") if isinstance(d.get("action"), str) else ""
        text = json.dumps(d)
        is_device_action = ("device_id" in d and "domain" in d and "type" in d
                            and not any(k in d for k in ("condition", "trigger", "platform")))
        # Same scoping as the offline could_move_door(), but exact for device actions: live, the door's
        # device id is known, so another cover's device action is not flagged.
        ents, other = [], False
        for src in (d, d.get("target"), d.get("data")):
            if isinstance(src, dict):
                e = src.get("entity_id")
                ents += [e] if isinstance(e, str) else [str(x) for x in (e or []) if isinstance(e, list)]
                other = other or any(k in src for k in ("area_id", "device_id", "floor_id", "label_id"))
        if "trigger" not in d and "platform" not in d and (
                d.get("event") == "mobile_app_notification_action" or act == "event.fire"):
            bad.append((eid, "fires the tap event (a close with no human tap)"))
        if is_device_action:
            moves = d.get("device_id") == DEV or DOOR in text
        elif "{{" in act or "{%" in act:
            moves = True                                   # templated action name: could render to cover.open_cover
        elif act.startswith("scene."):
            moves = DOOR in text                           # scene.apply / scene.create with the door in entities
        elif act.startswith("cover.") or act in GENERIC:
            # homeassistant.turn_on on a cover opens it, so generic calls get the same tail as cover.*
            moves = (any(DOOR in x for x in ents) or other or not ents or "all" in ents
                     or any("{{" in x or "{%" in x for x in ents))
        else:
            moves = False
        calls_close = act in ("script.garage_close_checked", "script.turn_on") and "garage_close_checked" in text
        if moves and eid != "script.garage_close_checked":
            bad.append((eid, act or "device action"))
        if calls_close and eid != "automation.garage_notification_action":
            bad.append((eid, act))
print("checked:", checked, "| skipped:", len(skipped), skipped)
print("movement-path findings:", bad or "none")
PY
```

Expected: `door device_id resolved: True`, `movement-path findings: none` (the close script doesn't exist yet), and a
`skipped` list that is **empty**, or whose every entry the operator confirms is not garage-related (a skipped item
is unaudited, not clean). Then WS `homeassistant/expose_entity/list`: `cover.msg100_7982_garage_door` is **not**
exposed to any assistant. Record all three results. Any finding → **stop**.

- [ ] **Step 2: Push the close script, then its dry run**

```bash
python tools/ha_apply.py --token-file "$HA_TOKEN_FILE" --backup-dir "$HOME/homebrain-backups/ha08" ../ha/scripts/garage_close_checked.json
```

Then call `POST /api/services/script/garage_close_checked` with `{"dry_run": true}` in each state and check that both
phones receive the `garage_result` message, **without buttons**:
  - door closed → "Garage: already closed ✓"
  - operator opens it, call within T s → "Garage: door just opened — try again in a moment."
  - after T s → "Garage: would close now (dry run)." (and the **door does not move**)

- [ ] **Step 3: Push the production automations (with *Close*)**

```bash
python tools/ha_apply.py --token-file "$HA_TOKEN_FILE" --backup-dir "$HOME/homebrain-backups/ha08" ../ha/automations/garage_*.json
```

Expected: six backups (the stage-2 variants) and six `read-back matches`.

- [ ] **Step 4: One real close, operator standing at the garage.** The door has been open longer than T. The operator
  is ready to stop it with the wall button. Send a test alert with *Close*:
  `POST /api/services/script/garage_notify` `{"message": "HA-08 stage 3: tap Close", "buttons": [{"action": "GARAGE_CLOSE", "title": "Close"}]}`.
  The operator taps **Close**. Expected: the door closes; both phones show "Garage closed ✓" (tag `garage_result`),
  and it **stays** after the cleanup clears the `garage` alert. Record the time from tap to `closed`.

- [ ] **Step 5: Refusals live.**
  - Door closed → tap *Close* on a resent test alert → "Garage: already closed ✓", and the door does not move.
  - Door open > T s → the operator taps *Close* on **both** phones within 1 s → the door closes once, and exactly one
    result message arrives. The handler is `parallel`, so the second tap's call hits the close script while it's
    running and is dropped silently by `mode: single` / `max_exceeded: silent`. (Under `queued` it would have run
    ~15 s later and sent a second "already closed ✓"; that is why the handler isn't queued.)
  - Kill switch: disable `automation.garage_notification_action`, tap *Close* on a test alert with the door open →
    nothing happens. Re-enable it, and check that the automation's state is `on`.

- [ ] **Step 6: Exporter round-trip with the full manifest.** Run the round-trip (Live stages intro). Expected: exit 0
  and **no diff** in any `ha/scripts/garage_*.json` or `ha/automations/garage_*.json`; `exposure/assistants.json` is
  unchanged. Any other diff → report it; don't commit it as part of HA-08.

- [ ] **Step 7: CHANGELOG stage-3 entry.** Record the audit results, dry-run replies, the real close (tap→closed time),
  the refusal and kill-switch results, and the round-trip. Commit and push.

---

### Task 9: Stage 4 — expose the status script; docs; release the gate

**Files:**
- Modify: `ha/exposure/assistants.json` (via export), `assistant-capabilities.md`, `ONBOARDING.md`, `BACKLOG.md`, `CHANGELOG.md`

- [ ] **Step 1: Back up the exposure list** (G4b rule: fresh, timestamped, and restored only by exact path):

```bash
python - "$HA_TOKEN_FILE" "$HOME/homebrain-backups/ha08/exposure-$(date +%Y%m%d-%H%M%S).json" <<'PY'
import asyncio, json, sys, websockets
raw = open(sys.argv[1], encoding="utf-8-sig").read().strip()
tok = raw.split(":", 1)[1].strip() if raw.lower().startswith("token:") else raw
async def main():
    async with websockets.connect("ws://192.168.1.104:8123/api/websocket", max_size=None) as ws:
        await ws.recv(); await ws.send(json.dumps({"type": "auth", "access_token": tok})); await ws.recv()
        await ws.send(json.dumps({"id": 1, "type": "homeassistant/expose_entity/list"}))
        r = json.loads(await ws.recv())
        json.dump(r["result"], open(sys.argv[2], "w", encoding="utf-8"), indent=2, sort_keys=True)
        print("saved", sys.argv[2], "exposed:", sum(1 for v in r["result"]["exposed_entities"].values() if v.get("conversation")))
asyncio.run(main())
PY
```

Expected: `saved …  exposed: 14`. Quote the exact path in the CHANGELOG.

- [ ] **Step 2: Expose `script.garage_status` to `conversation` only.** WS `{"type": "homeassistant/expose_entity", "assistants": ["conversation"], "entity_ids": ["script.garage_status"], "should_expose": true}`
  → `success: true`. Re-list: exposed count is **15**, and the new one is `script.garage_status`.

- [ ] **Step 3: Update `assistant-capabilities.md`.** In "Currently exposed to ChatGPT", add after the `script.media_status` row:
  `| \`script.garage_status\` | **Garage door status** — open/closed (and for how long); **read-only**, cannot open or close the door (hard-return \`{chat_text}\`) |`.
  In "Routing rules", add: `- "Is the garage open?" / "did I close the garage?" → call \`script.garage_status\` and **relay its \`chat_text\`**. There is **no** tool to open or close the garage — say so; never claim to have done it.`

- [ ] **Step 4: Voice checks.** "Okay Nabu, is the garage open?" with the door closed, then open. The replies match
  spec §5, and the assist-pipeline debug trace (`assist_pipeline/pipeline_debug/list` + `…/get`, pipeline
  `01kxygpr39jas5hgsf28cph108`) shows `script.garage_status` was called. "Okay Nabu, close the garage door" → the
  agent says it can't, and **the door does not move**. Record the transcripts.

- [ ] **Step 5: Exporter round-trip.** Expected diff: **only** `ha/exposure/assistants.json` gains
  `"script.garage_status": {"conversation": true}`. Then run `python tests/test_ha_garage_policy.py -v`:
  `test_rule3_only_status_script_may_be_exposed` still PASSES against the new exposure file. Commit the exposure diff.

- [ ] **Step 6: Docs.**
  - `ONBOARDING.md` §4: a bullet listing the garage entities, the kill switch (`automation.garage_notification_action`),
    the two tags, and "nothing opens the door; only `script.garage_close_checked` closes it". §5 "What works": a ✅
    line for HA-08.
  - `BACKLOG.md`: `HA-08` → `done` for this scope (next action: "voice close deferred → `HA-08b`"). Add rows
    **`HA-08b`** (voice close, deferred; reason: satellite false wakes; preferred shape: fixed local phrase + phone
    confirmation) and **`INF-12`** (exporter `helpers` collection: `timer`/`counter`). Add both to the board.
  - `CHANGELOG.md`: a stage-4 entry (exposure backup path, 14→15, voice transcripts, round-trip), and a
    **Rollback** block copied from spec §6.4 with the exact commands:
    `python tools/ha_apply.py … --delete ../ha/scripts/garage_close_checked.json` etc., and the exposure restore from the
    Step 1 backup path.
  - `git diff --numstat` for each: appends are `N 0`.

- [ ] **Step 7: Release the gate.** In `BACKLOG.md` §10, set the holder to `(none)` and the status to **"FREE — released
  <date>. HA-08 garage rollout live and verified (stages 1–4); kill switch `automation.garage_notification_action`."**,
  keeping the "Prior:" history. Run the full local suite:
  `python -m unittest discover -s tests -p "test_*.py"` → Expected: all PASS (record the count). Commit
  `docs(homebrain): HA-08 live; release the gate` and push. The PR (after the pairing PR merges) carries the
  spec, this plan, the configs, the tools and the records.
