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
        for name in SCRIPTS:
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


if __name__ == "__main__":
    unittest.main()
