#!/usr/bin/env python3
"""INF-09 HA managed-state exporter. Run: python tests/test_ha_export.py

Entirely offline: the network layer is injected as FakeClient, so no test reaches Home
Assistant. Fixtures are inline dicts -- they stand in for recorded API responses and stay
readable next to the assertion that uses them.
"""
import json, os, shutil, subprocess, sys, tempfile, unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_RESOLVER = os.path.dirname(_HERE)
_TOOLS = os.path.join(_RESOLVER, "tools")
sys.path.insert(0, _RESOLVER)
sys.path.insert(0, _TOOLS)
import ha_export


# --------------------------------------------------------------------------- fixtures

SCRIPT_PLAY_RADIO = {
    "alias": "Ceiling: Play Radio (resolver)",
    "description": "Play a radio station on the ceiling speakers.",
    "mode": "single",
    "fields": {
        "station": {
            "name": "Station",
            "description": "Station name, VERBATIM as the user said it.",
            "required": False,
            "selector": {"text": {}},
        },
    },
    # Behavioural subtree: preserved losslessly, list order untouched.
    "sequence": [
        {"action": "rest_command.resolver_command",
         "data": {"intent": "radio", "params": {"mode": "play", "station": "{{ station }}"}},
         "response_variable": "r"},
        {"stop": "done", "response_variable": "resp"},
    ],
}

AUTOMATION_VOICE = {
    "id": "voice_ceiling_speakers",
    "alias": u"Voice — Ceiling Speakers",
    "mode": "queued",
    "triggers": [
        {"platform": "conversation", "id": "play_favorite",
         "command": ["play [the] russian songs", "put on [the] russian songs"]},
        {"platform": "conversation", "id": "stop", "command": ["stop", "stop [the] music"]},
    ],
    "conditions": [],
    "actions": [
        {"choose": [
            {"conditions": [{"condition": "template",
                             "value_template": "{{ trigger.id=='stop' }}"}],
             "sequence": [{"action": "media_player.media_pause",
                           "target": {"entity_id": "media_player.ceiling_speakers"}}]},
        ]},
    ],
}

SELECT_STATE = {
    "entity_id": "select.respeaker_living_room_finished_speaking_detection",
    "state": "default",
    "attributes": {"options": ["relaxed", "aggressive", "default"],
                   "friendly_name": "reSpeaker Living Room Finished speaking detection"},
    "last_changed": "2026-09-06T16:53:35.378994+00:00",
    "last_updated": "2026-09-06T16:53:35.378994+00:00",
    "last_reported": "2026-09-06T16:53:35.378994+00:00",
    "context": {"id": "01M1VT7G0JRMBFGF71FVD72FPT", "parent_id": None, "user_id": "4749dd84"},
}

PIPELINES = {
    "preferred_pipeline": "01kxygpr39jas5hgsf28cph108",
    "pipelines": [
        {"id": "01kxygpr39jas5hgsf28cph108", "name": "Living Room Voice",
         "conversation_engine": "conversation.openai_conversation", "conversation_language": "en",
         "stt_engine": "stt.faster_whisper", "stt_language": "en",
         "tts_engine": "tts.piper", "tts_voice": "en_US-amy", "tts_language": "en",
         "wake_word_entity": None, "wake_word_id": None, "prefer_local_intents": True},
    ],
}

EXPOSURE = {
    "script.play_radio": {"conversation": {"should_expose": True}},
    "media_player.ceiling_speakers": {"conversation": {"should_expose": False}},
}

MANIFEST = {
    "ha_version_expected": "2026.6.4",
    "scripts": ["play_radio"],
    "automations": ["voice_ceiling_speakers"],
    "pipelines": ["01kxygpr39jas5hgsf28cph108"],
    "satellite_entities": ["select.respeaker_living_room_finished_speaking_detection"],
}


def states_list():
    return [
        {"entity_id": "script.play_radio", "state": "off", "attributes": {}},
        {"entity_id": "automation.voice_ceiling_speakers", "state": "on",
         "attributes": {"id": "voice_ceiling_speakers"}},
        dict(SELECT_STATE),
    ]


class FakeClient(object):
    """Injected IO shell. Nothing here touches a socket."""

    def __init__(self, states=None, scripts=None, automations=None, pipelines=None,
                 exposure=None, version="2026.6.4", route_status=None, raise_on=None):
        self.states = states_list() if states is None else states
        self.scripts = {"play_radio": json.loads(json.dumps(SCRIPT_PLAY_RADIO))} \
            if scripts is None else scripts
        self.automations = {"voice_ceiling_speakers": json.loads(json.dumps(AUTOMATION_VOICE))} \
            if automations is None else automations
        self.pipelines = json.loads(json.dumps(PIPELINES)) if pipelines is None else pipelines
        self.exposure = json.loads(json.dumps(EXPOSURE)) if exposure is None else exposure
        self.version = version
        self.route_status = route_status or {}     # path-prefix -> status to force
        self.raise_on = raise_on                   # path-prefix that raises a bare Exception
        self.closed = False

    def rest_get(self, path):
        if self.raise_on and path.startswith(self.raise_on):
            raise RuntimeError("simulated transport blow-up")
        for prefix, status in self.route_status.items():
            if path.startswith(prefix):
                return (status, None, "forced %s" % status)
        if path == "/api/config":
            return (200, {"version": self.version}, None)
        if path == "/api/states":
            return (200, self.states, None)
        if path.startswith("/api/config/script/config/"):
            name = path.rsplit("/", 1)[1]
            if name in self.scripts:
                return (200, self.scripts[name], None)
            return (404, None, "not found")
        if path.startswith("/api/config/automation/config/"):
            name = path.rsplit("/", 1)[1]
            if name in self.automations:
                return (200, self.automations[name], None)
            return (404, None, "not found")
        return (404, None, "unrouted")

    def ws_call(self, message):
        kind = message.get("type")
        if kind == "assist_pipeline/pipeline/list":
            return {"success": True, "result": self.pipelines}
        if kind == "homeassistant/expose_entity/list":
            return {"success": True, "result": self.exposure}
        return {"success": False, "error": {"message": "unknown command"}}

    def close(self):
        self.closed = True


class ExportCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="inf09-")
        self.out = os.path.join(self.tmp, "ha")
        self.raw = os.path.join(self.tmp, "raw")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_export(self, client=None, **kw):
        return ha_export.run_export(client or FakeClient(), kw.pop("manifest", MANIFEST),
                                    self.out, self.raw, **kw)

    def read_out(self):
        found = {}
        for root, _dirs, names in os.walk(self.out):
            for name in names:
                full = os.path.join(root, name)
                rel = os.path.relpath(full, self.out).replace(os.sep, "/")
                with open(full, "rb") as handle:
                    found[rel] = handle.read()
        return found

    def residue(self):
        parent = os.path.dirname(os.path.abspath(self.out))
        return sorted(n for n in os.listdir(parent) if n.startswith(".tmp-"))


# --------------------------------------------------------------------------- determinism

class DeterminismTest(ExportCase):
    def test_same_input_renders_identical_bytes(self):
        first = ha_export.render(SCRIPT_PLAY_RADIO)
        second = ha_export.render(json.loads(json.dumps(SCRIPT_PLAY_RADIO)))
        self.assertEqual(first, second)

    def test_hash_seed_independence_across_processes(self):
        # PYTHONHASHSEED is fixed at interpreter startup, so changing it in-process proves
        # nothing. Each seed gets its own interpreter, with the environment COPIED first so the
        # child keeps PATH and friends.
        code = ("import json, sys;"
                "sys.path.insert(0, %r);"
                "import ha_export;"
                "sys.stdout.write(ha_export.render(json.loads(sys.stdin.read())).decode('utf-8'))"
                % _TOOLS)
        payload = json.dumps(SCRIPT_PLAY_RADIO)
        outputs = []
        for seed in ("0", "1", "12345"):
            env = os.environ.copy()
            env["PYTHONHASHSEED"] = seed
            proc = subprocess.Popen([sys.executable, "-c", code], env=env,
                                    stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE)
            out, err = proc.communicate(payload.encode("utf-8"))
            self.assertEqual(proc.returncode, 0, err.decode("utf-8", "replace"))
            outputs.append(out)
        self.assertEqual(len(set(outputs)), 1, "render() is not hash-order independent")

    def test_two_exports_of_the_same_state_are_byte_identical(self):
        self.run_export()
        first = self.read_out()
        self.run_export()
        self.assertEqual(first, self.read_out())


# --------------------------------------------------------------------------- secrets

class SecretMustFailTest(unittest.TestCase):
    def scan(self, obj, literals=()):
        return ha_export.scan_secrets(obj, literals)

    def test_bearer_token_in_a_sequence(self):
        payload = {"sequence": [{"data": {"headers": {"X": "Bearer abc123def456"}}}]}
        self.assertTrue(self.scan(payload))

    def test_jwt_anywhere(self):
        jwt = "eyJhbGciOi.eyJzdWIiOi.SflKxwRJSM"
        self.assertTrue(self.scan({"sequence": [{"note": jwt}]}))

    def test_sensitive_key_name(self):
        for key in ("password", "api_key", "client_secret", "authorization"):
            self.assertTrue(self.scan({key: "anything"}), key)

    def test_pem_private_key(self):
        self.assertTrue(self.scan({"blob": "-----BEGIN RSA PRIVATE KEY-----\nAAAA"}))

    def test_url_embedded_credentials(self):
        self.assertTrue(self.scan({"uri": "smb://user:hunter2@192.168.1.83/share"}))

    def test_literal_on_host_secret_even_at_an_exempt_path(self):
        # `uri` is exempt from the ENTROPY rule; the literal rule is never exempt.
        token = "abcdefghijklmnopqrstuvwxyz012345"
        found = self.scan({"uri": "http://x/?t=" + token}, literals=(token,))
        self.assertEqual([rule for _p, rule in found], ["literal-secret"])

    def test_finding_never_carries_the_value(self):
        secret = "Bearer supersecretvalue123"
        found = ha_export.scan_secrets({"headers": {"auth_header": secret}})
        self.assertTrue(found)
        for path, rule in found:
            self.assertNotIn("supersecretvalue123", path)
            self.assertNotIn("supersecretvalue123", rule)


class SecretMustPassTest(unittest.TestCase):
    """These are real shapes from this system. A naive entropy rule rejects every one of them,
    and the exporter would never produce output at all."""

    def test_real_identifier_shapes_are_not_secrets(self):
        payload = {
            "preferred_pipeline": "01kxygpr39jas5hgsf28cph108",       # ULID, 26 chars
            "id": "3f2504e0-4f89-11d3-9a0c-0305e82c3301",             # UUID
            "device_id": "4749dd8432374726998965b2d90c1bc4",          # 32-hex
            "entity_id": "media_player.ceiling_speakers",
            "media_content_id": "library://radio/17",
            "conversation_engine": "conversation.openai_conversation",
        }
        self.assertEqual(ha_export.scan_secrets(payload), [])

    def test_ordinary_config_text_is_not_a_secret(self):
        payload = {"alias": u"Voice — Ceiling Speakers",
                   "command": ["play [the] russian songs"],
                   "value_template": "{{ trigger.id=='stop' }}"}
        self.assertEqual(ha_export.scan_secrets(payload), [])

    def test_a_real_export_is_clean(self):
        raw = {"scripts": {"play_radio": SCRIPT_PLAY_RADIO},
               "automations": {"voice_ceiling_speakers": AUTOMATION_VOICE},
               "satellite": {"x": SELECT_STATE}, "pipelines": PIPELINES, "exposure": EXPOSURE}
        self.assertEqual(ha_export.scan_secrets(raw), [])


# --------------------------------------------------------------------------- envelope/subtree

class EnvelopeVersusSubtreeTest(ExportCase):
    def test_unknown_envelope_key_fails_closed(self):
        script = json.loads(json.dumps(SCRIPT_PLAY_RADIO))
        script["brand_new_ha_key"] = 1
        client = FakeClient(scripts={"play_radio": script})
        with self.assertRaises(ha_export.ExportError) as caught:
            self.run_export(client)
        self.assertEqual(caught.exception.code, ha_export.EXIT_SCHEMA)
        self.assertFalse(os.path.exists(self.out))

    def test_novel_nested_action_is_preserved_structurally(self):
        script = json.loads(json.dumps(SCRIPT_PLAY_RADIO))
        novel = {"some_future_action": {"deep": [{"nested": {"thing": [1, 2, 3]}}]}}
        script["sequence"].append(novel)
        client = FakeClient(scripts={"play_radio": script})
        self.run_export(client)
        written = json.loads(self.read_out()["scripts/play_radio.json"].decode("utf-8"))
        self.assertEqual(written["sequence"][-1], novel)

    def test_sequence_list_order_is_preserved(self):
        # Reordering a sequence is a behaviour change wearing a clean diff.
        self.run_export()
        written = json.loads(self.read_out()["scripts/play_radio.json"].decode("utf-8"))
        actions = [step.get("action") or step.get("stop") for step in written["sequence"]]
        self.assertEqual(actions, ["rest_command.resolver_command", "done"])

    def test_secret_buried_deep_in_a_preserved_subtree_is_still_caught(self):
        script = json.loads(json.dumps(SCRIPT_PLAY_RADIO))
        script["sequence"].append({"a": {"b": {"c": [{"d": {"password": "hunter2"}}]}}})
        client = FakeClient(scripts={"play_radio": script})
        with self.assertRaises(ha_export.ExportError) as caught:
            self.run_export(client)
        self.assertEqual(caught.exception.code, ha_export.EXIT_SECRET)
        self.assertFalse(os.path.exists(self.out))

    def test_unknown_field_metadata_key_fails_closed(self):
        script = json.loads(json.dumps(SCRIPT_PLAY_RADIO))
        script["fields"]["station"]["unexpected"] = True
        client = FakeClient(scripts={"play_radio": script})
        with self.assertRaises(ha_export.ExportError) as caught:
            self.run_export(client)
        self.assertEqual(caught.exception.code, ha_export.EXIT_SCHEMA)

    def test_selector_is_lossless(self):
        script = json.loads(json.dumps(SCRIPT_PLAY_RADIO))
        script["fields"]["station"]["selector"] = {"select": {"options": ["a"], "custom_x": 1}}
        client = FakeClient(scripts={"play_radio": script})
        self.run_export(client)
        written = json.loads(self.read_out()["scripts/play_radio.json"].decode("utf-8"))
        self.assertEqual(written["fields"]["station"]["selector"],
                         {"select": {"options": ["a"], "custom_x": 1}})


# --------------------------------------------------------------------------- normalization

class NormalizationTest(ExportCase):
    def test_runtime_metadata_is_stripped(self):
        self.run_export()
        blob = self.read_out()[
            "satellite/select.respeaker_living_room_finished_speaking_detection.json"]
        written = json.loads(blob.decode("utf-8"))
        for key in ha_export.RUNTIME_STATE_KEYS:
            self.assertNotIn(key, written)
        self.assertEqual(written["state"], "default")

    def test_options_are_sorted(self):
        self.run_export()
        blob = self.read_out()[
            "satellite/select.respeaker_living_room_finished_speaking_detection.json"]
        written = json.loads(blob.decode("utf-8"))
        self.assertEqual(written["options"], ["aggressive", "default", "relaxed"])

    def test_cyrillic_survives_unescaped(self):
        script = json.loads(json.dumps(SCRIPT_PLAY_RADIO))
        script["description"] = u"Радио Русские"
        client = FakeClient(scripts={"play_radio": script})
        self.run_export(client)
        raw_bytes = self.read_out()["scripts/play_radio.json"]
        self.assertIn(u"Радио".encode("utf-8"), raw_bytes)
        self.assertNotIn(b"\\u0420", raw_bytes)

    def test_output_is_lf_with_trailing_newline(self):
        self.run_export()
        blob = self.read_out()["meta.json"]
        self.assertNotIn(b"\r\n", blob)
        self.assertTrue(blob.endswith(b"\n"))

    def test_meta_carries_version_but_no_timestamp(self):
        # A timestamp would churn every export and destroy the signal these files exist to give.
        self.run_export()
        meta = json.loads(self.read_out()["meta.json"].decode("utf-8"))
        self.assertEqual(meta["ha_version"], "2026.6.4")
        self.assertEqual(sorted(meta.keys()), ["exporter_version", "ha_version"])

    def test_exposure_is_sorted_and_flags_only(self):
        self.run_export()
        written = json.loads(self.read_out()["exposure/conversation.json"].decode("utf-8"))
        entities = written["exposed_entities"]
        self.assertEqual(sorted(entities.keys()), list(sorted(entities.keys())))
        self.assertEqual(entities["script.play_radio"], {"conversation": True})


# --------------------------------------------------------------------------- failure modes

class FailureModeTest(ExportCase):
    def test_missing_managed_resource(self):
        manifest = dict(MANIFEST)
        manifest["scripts"] = ["play_radio", "does_not_exist"]
        with self.assertRaises(ha_export.ExportError) as caught:
            self.run_export(manifest=manifest)
        self.assertEqual(caught.exception.code, ha_export.EXIT_MISSING)

    def test_missing_managed_pipeline(self):
        # Pipelines arrive as a list, not addressed by id, so an id that does not exist would
        # otherwise export nothing for it and still report success.
        manifest = dict(MANIFEST)
        manifest["pipelines"] = ["01kxygpr39jas5hgsf28cph108", "01nosuchpipelineidatall000"]
        with self.assertRaises(ha_export.ExportError) as caught:
            self.run_export(manifest=manifest)
        self.assertEqual(caught.exception.code, ha_export.EXIT_MISSING)
        self.assertFalse(os.path.exists(self.out))

    def test_strict_inventory_flags_unmanaged_resources(self):
        states = states_list() + [{"entity_id": "script.other", "state": "off", "attributes": {}}]
        client = FakeClient(states=states, scripts={
            "play_radio": json.loads(json.dumps(SCRIPT_PLAY_RADIO))})
        with self.assertRaises(ha_export.ExportError) as caught:
            self.run_export(client, strict_inventory=True)
        self.assertEqual(caught.exception.code, ha_export.EXIT_MISSING)

    def test_unmanaged_resources_are_reported_without_strict(self):
        states = states_list() + [{"entity_id": "script.other", "state": "off", "attributes": {}}]
        client = FakeClient(states=states)
        summary = self.run_export(client)
        self.assertEqual(summary["unmanaged"]["scripts"], ["other"])

    def test_dead_frontend_route_is_a_capability_failure_not_missing(self):
        # HA's own inventory says the script exists, so a 404 on the undocumented config route
        # means the ROUTE is gone -- exactly the version-coupling risk. Must not be reported as
        # a missing resource.
        client = FakeClient(route_status={"/api/config/script/config/": 404})
        with self.assertRaises(ha_export.ExportError) as caught:
            self.run_export(client)
        self.assertEqual(caught.exception.code, ha_export.EXIT_CAPABILITY)

    def test_transport_failure_on_config(self):
        client = FakeClient(route_status={"/api/config": 500})
        with self.assertRaises(ha_export.ExportError) as caught:
            self.run_export(client)
        self.assertEqual(caught.exception.code, ha_export.EXIT_TRANSPORT)

    def test_unsupported_websocket_command_is_a_capability_failure(self):
        client = FakeClient()
        client.ws_call = lambda message: {"success": False, "error": {"message": "unknown"}}
        with self.assertRaises(ha_export.ExportError) as caught:
            self.run_export(client)
        self.assertEqual(caught.exception.code, ha_export.EXIT_CAPABILITY)

    def test_partial_api_failure_writes_nothing(self):
        client = FakeClient(raise_on="/api/config/automation/config/")
        self.assertRaises(Exception, self.run_export, client)
        self.assertFalse(os.path.exists(self.out))
        self.assertEqual(self.residue(), [])

    def test_probe_only_writes_nothing(self):
        summary = self.run_export(probe_only=True)
        self.assertTrue(summary["probe_only"])
        self.assertFalse(summary["written"])
        self.assertFalse(os.path.exists(self.out))
        self.assertFalse(os.path.exists(os.path.join(self.raw, summary["stamp"])))


class PriorStateIsPreservedTest(ExportCase):
    """Every failure path must leave a previous successful export byte-identical."""

    def _good_then(self, client, **kw):
        self.run_export(stamp="20260101T000000Z")
        before = self.read_out()
        try:
            self.run_export(client, stamp="20260102T000000Z", **kw)
        except Exception:
            pass
        return before, self.read_out()

    def test_schema_failure_preserves_prior_export(self):
        script = json.loads(json.dumps(SCRIPT_PLAY_RADIO))
        script["surprise"] = 1
        before, after = self._good_then(FakeClient(scripts={"play_radio": script}))
        self.assertEqual(before, after)
        self.assertEqual(self.residue(), [])

    def test_secret_failure_preserves_prior_export(self):
        script = json.loads(json.dumps(SCRIPT_PLAY_RADIO))
        script["sequence"].append({"data": {"password": "hunter2"}})
        before, after = self._good_then(FakeClient(scripts={"play_radio": script}))
        self.assertEqual(before, after)
        self.assertEqual(self.residue(), [])

    def test_transport_failure_preserves_prior_export(self):
        before, after = self._good_then(FakeClient(route_status={"/api/states": 503}))
        self.assertEqual(before, after)
        self.assertEqual(self.residue(), [])

    def test_missing_resource_preserves_prior_export(self):
        manifest = dict(MANIFEST)
        manifest["automations"] = ["voice_ceiling_speakers", "ghost"]
        before, after = self._good_then(FakeClient(), manifest=manifest)
        self.assertEqual(before, after)


# --------------------------------------------------------------------------- transaction

class PromotionTest(ExportCase):
    def test_deletion_handling_replaces_the_tree_wholesale(self):
        self.run_export()
        self.assertIn("scripts/play_radio.json", self.read_out())
        manifest = dict(MANIFEST)
        manifest["scripts"] = []
        self.run_export(FakeClient(scripts={}), manifest=manifest)
        self.assertNotIn("scripts/play_radio.json", self.read_out())

    def test_normal_exception_during_promotion_restores_immediately(self):
        self.run_export(stamp="20260101T000000Z")
        before = self.read_out()
        staged = tempfile.mkdtemp(dir=self.tmp)
        real_rename = ha_export.os.rename

        # Fail EVERY attempt to promote the staged tree, so rename_retry exhausts its retries;
        # the restore rename (prev -> out) must still be allowed through.
        def flaky(src, dst):
            if os.path.abspath(src) == os.path.abspath(staged):
                raise OSError("simulated failure promoting the staged tree")
            return real_rename(src, dst)

        ha_export.os.rename = flaky
        try:
            self.assertRaises(OSError, ha_export.promote_canonical,
                              staged, self.out, "20260102T000000Z")
        finally:
            ha_export.os.rename = real_rename
        self.assertEqual(before, self.read_out())

    def test_interrupted_promotion_is_recovered_on_next_run(self):
        # Simulate an actual crash: <out> renamed away, process dies before the second rename.
        self.run_export(stamp="20260101T000000Z")
        before = self.read_out()
        prev = ha_export.prev_dir_for(self.out, "20260102T000000Z")
        os.rename(self.out, prev)
        self.assertFalse(os.path.exists(self.out))

        message = ha_export.recover_orphan(self.out)
        self.assertIsNotNone(message)
        self.assertIn("recovered", message)
        self.assertEqual(before, self.read_out())

    def test_recover_orphan_is_a_no_op_when_out_exists(self):
        self.run_export()
        self.assertIsNone(ha_export.recover_orphan(self.out))

    def test_raw_is_promoted_and_pruned(self):
        for index in range(4):
            self.run_export(stamp="2026010%dT000000Z" % (index + 1), keep_raw=2)
        kept = sorted(n for n in os.listdir(self.raw) if not n.startswith("."))
        self.assertEqual(kept, ["20260103T000000Z", "20260104T000000Z"])

    def test_raw_holds_unfiltered_payloads(self):
        # Raw is the forensic/source snapshot: runtime metadata that canonical strips is retained.
        self.run_export(stamp="20260101T000000Z")
        path = os.path.join(self.raw, "20260101T000000Z", "satellite",
                            "select.respeaker_living_room_finished_speaking_detection.json")
        with open(path, "rb") as handle:
            blob = json.loads(handle.read().decode("utf-8"))
        self.assertIn("last_changed", blob)

    @unittest.skipUnless(os.name == "posix", "POSIX modes; the dev machine is Windows")
    def test_raw_permissions_are_restrictive(self):
        self.run_export(stamp="20260101T000000Z")
        raw_run = os.path.join(self.raw, "20260101T000000Z")
        self.assertEqual(os.stat(raw_run).st_mode & 0o777, 0o700)
        one = os.path.join(raw_run, "pipelines.json")
        self.assertEqual(os.stat(one).st_mode & 0o777, 0o600)


class ExitCodeTest(unittest.TestCase):
    def test_codes_are_distinct(self):
        codes = [ha_export.EXIT_OK, ha_export.EXIT_USAGE, ha_export.EXIT_TRANSPORT,
                 ha_export.EXIT_CAPABILITY, ha_export.EXIT_SCHEMA, ha_export.EXIT_MISSING,
                 ha_export.EXIT_SECRET, ha_export.EXIT_PARTIAL]
        self.assertEqual(len(set(codes)), len(codes))

    def test_no_allow_unknown_fields_escape_hatch(self):
        # Removed deliberately: an export that omits data while reporting success is worse than
        # one that refuses to run.
        text = ha_export.build_parser().format_help()
        self.assertNotIn("allow-unknown-fields", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
