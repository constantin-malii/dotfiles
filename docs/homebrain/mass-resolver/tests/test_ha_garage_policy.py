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
    if "{{" in act or "{%" in act:
        return True           # a templated action name could render to cover.open_cover
    if act.startswith("scene."):
        return DOOR in json.dumps(d)   # scene.apply / scene.create with entities: {door: open}
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
                # GENERIC_MOVES too: homeassistant.turn_on/toggle on a cover opens it, and the close script is
                # not exempt here (rule 2's test skips it; this one must not).
                self.assertNotIn(d.get("action"), FORBIDDEN_MOVES | GENERIC_MOVES,
                                 "%s: %s could open/move the door" % (label, d))

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


def ha_slugify(text):
    """HA's entity-id slug for a plain ASCII alias: lowercase, runs of non-alphanumerics -> '_', trimmed."""
    out, prev_us = [], False
    for ch in text.lower():
        if ("a" <= ch <= "z") or ("0" <= ch <= "9"):
            out.append(ch)
            prev_us = False
        elif not prev_us:
            out.append("_")
            prev_us = True
    return "".join(out).strip("_")


def option_by_message(close_obj, prefix):
    for opt in close_obj["sequence"][1]["choose"]:
        if opt["sequence"][0]["data"]["message"].startswith(prefix):
            return opt
    raise AssertionError("no refusal starting %r" % prefix)


@unittest.skipUnless(os.path.isdir(HA), "ha/ tree not present")
class ReviewFixesTest(unittest.TestCase):
    """Gaps found by the pre-live review (2026-09-29): each pins a bug the earlier tests passed against."""

    def test_automation_entity_ids_will_equal_their_ids(self):
        # HA derives automation.<entity_id> from the alias at creation, not from "id". The kill switch
        # (automation.garage_notification_action) and the status boot marker depend on these names.
        for name in AUTOMATIONS:
            self.assertEqual(ha_slugify(auto(name)["alias"]), name, "alias of %s must slugify to its id" % name)

    def test_close_script_has_exactly_one_moving_action_the_close(self):
        moving = moving_actions(load("scripts", "garage_close_checked")[1])
        self.assertEqual([d.get("action") for d in moving], ["cover.close_cover"])

    def test_could_move_door_sees_scenes_and_templated_action_names(self):
        self.assertTrue(could_move_door({"action": "scene.apply", "data": {"entities": {DOOR: "open"}}}))
        self.assertTrue(could_move_door({"action": "scene.create", "data": {"scene_id": "x", "entities": {DOOR: {"state": "open"}}}}))
        self.assertTrue(could_move_door({"action": "{{ 'cover.open_cover' }}", "target": {"entity_id": "cover.x"}}))
        self.assertFalse(could_move_door({"action": "scene.apply", "data": {"entities": {"light.porch": "on"}}}))

    def test_nothing_fires_the_button_event(self):
        # Firing mobile_app_notification_action with GARAGE_CLOSE would close the door with no human tap.
        for label, obj in all_managed():
            for d in walk(obj):
                if "trigger" in d or "platform" in d:
                    continue
                self.assertNotEqual(d.get("event"), "mobile_app_notification_action", "%s fires the tap event" % label)
                self.assertNotEqual(d.get("action"), "event.fire", label)

    def test_garage_close_id_appears_only_in_buttons_and_the_handler_trigger(self):
        for label, obj in all_managed():
            # Identity within THIS loaded copy: the handler's own trigger dicts are the one permitted place.
            handler_trigger_dicts = ([id(x) for x in walk(obj["triggers"])]
                                     if label == "automations/garage_notification_action.json" else [])
            for d in walk(obj):
                if "GARAGE_CLOSE" not in [v for v in d.values() if isinstance(v, str)]:
                    continue
                is_button = sorted(d) == ["action", "title"]
                self.assertTrue(is_button or id(d) in handler_trigger_dicts,
                                "%s: GARAGE_CLOSE outside a button or the handler trigger: %r" % (label, d))

    def test_close_script_guard_templates_are_exact(self):
        c = load("scripts", "garage_close_checked")[1]
        self.assertEqual(option_by_message(c, "Garage is stuck")["conditions"][0]["value_template"],
                         "{{ st in ['opening', 'closing'] and age_s > stuck_s }}")
        self.assertEqual(option_by_message(c, "Garage: obstruction detected")["conditions"][0]["value_template"],
                         "{{ obstructed }}")
        self.assertEqual(option_by_message(c, "Garage: door just opened")["conditions"][0]["value_template"],
                         "{{ age_s < stable_open_s }}")
        self.assertEqual(c["sequence"][0]["variables"]["obstructed"],
                         "{{ state_attr('cover.msg100_7982_garage_door', 'obstruction-detected') in [true, 'true', 'True', 'on'] }}")

    def test_handler_maps_each_button_to_its_own_branch(self):
        a = auto("garage_notification_action")
        mapping = dict((t["event_data"]["action"], t["id"]) for t in a["triggers"])
        self.assertEqual(mapping, {"GARAGE_CLOSE": "close", "GARAGE_SNOOZE_1H": "snooze_1h", "GARAGE_SNOOZE_3H": "snooze_3h"})
        branches = a["actions"][0]["choose"]
        close = [b for b in branches if "garage_close_checked" in json.dumps(b["sequence"])]
        self.assertEqual(len(close), 1)
        self.assertEqual(close[0]["conditions"], [{"condition": "trigger", "id": "close"}])
        snooze = [b for b in branches if "timer.start" in json.dumps(b["sequence"])]
        self.assertEqual(len(snooze), 1)
        self.assertEqual(snooze[0]["conditions"][0], {"condition": "trigger", "id": ["snooze_1h", "snooze_3h"]})

    def test_cleanup_cancels_snooze_and_resets_counter(self):
        then = auto("garage_closed_cleanup")["actions"][0]["then"]
        self.assertIn({"action": "timer.cancel", "target": {"entity_id": "timer.garage_snooze"}}, then)
        self.assertIn({"action": "counter.reset", "target": {"entity_id": "counter.garage_reminders"}}, then)

    def test_away_templates_are_exact(self):
        conds = auto("garage_opened_while_away")["conditions"]
        want = "{%% set p = states.person.%s %%}{{ p is not none and p.state not in ['home', 'unknown', 'unavailable'] and (as_timestamp(now()) - as_timestamp(p.last_changed)) >= 300 }}"
        self.assertEqual([c["value_template"] for c in conds], [want % "costea", want % "vio"])


if __name__ == "__main__":
    unittest.main()
