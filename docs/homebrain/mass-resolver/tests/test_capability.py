#!/usr/bin/env python3
"""Run: python tests/test_capability.py"""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import capability, command_result as cr


class FakeCap(capability.Capability):
    name = "music"
    def __init__(self, resolved=None, invalid=None, boom=False, exec_result=None):
        self._resolved = resolved; self._invalid = invalid; self._boom = boom; self._exec = exec_result
    def resolve(self, ctx, params):
        if self._boom:
            raise RuntimeError("kaboom")
        return self._resolved
    def validate(self, ctx, resolved):
        return self._invalid
    def execute(self, ctx, resolved, rid):
        return self._exec


class CapabilityTest(unittest.TestCase):
    def test_validate_failure_short_circuits(self):
        cap = FakeCap(resolved={"x": 1}, invalid={"code": "not_found", "reason": "nope",
                                                  "chat_text": "Not found.", "spoken_text": "Couldn't find it."})
        r = capability.run(cap, None, {}, "r1")
        self.assertFalse(r["ok"]); self.assertEqual(r["error"]["code"], "not_found")
        self.assertEqual(r["chat_text"], "Not found."); self.assertEqual(r["spoken_text"], "Couldn't find it.")

    def test_execute_runs_when_valid(self):
        good = cr.ok("music", "r2", "Playing.", spoken_text="Playing.")
        cap = FakeCap(resolved={"x": 1}, invalid=None, exec_result=good)
        r = capability.run(cap, None, {}, "r2")
        self.assertTrue(r["ok"]); self.assertEqual(r["chat_text"], "Playing.")

    def test_exception_becomes_upstream_error(self):
        cap = FakeCap(boom=True)
        r = capability.run(cap, None, {}, "r3")
        self.assertFalse(r["ok"]); self.assertEqual(r["error"]["code"], "upstream_error")
        self.assertTrue(r["chat_text"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
