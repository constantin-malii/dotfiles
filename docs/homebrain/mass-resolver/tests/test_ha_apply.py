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

    def test_same_resource_twice_in_one_run_is_refused_before_any_call(self):
        # One timestamp per run: a second push of the same id would overwrite the first backup with the
        # already-pushed state, losing the true original.
        a = self.write("a.json", {"object_id": "garage_notify", "alias": "a"})
        b = self.write("b.json", {"object_id": "garage_notify", "alias": "b"})
        c = FakeClient()
        self.assertEqual(self.run_main([a, b], c), 1)
        self.assertEqual(c.calls, [], "refused before touching HA")
        self.assertIn("more than once", self.lines[-1])

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
