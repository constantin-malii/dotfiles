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
