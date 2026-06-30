#!/usr/bin/env python3
"""Run: python tests/test_command_result.py"""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import command_result as cr


class CommandResultTest(unittest.TestCase):
    def test_ok_shape(self):
        r = cr.ok("music", "r1", "Playing Du Hast.", spoken_text="Playing Du Hast.", metadata={"uri": "x"})
        self.assertTrue(r["ok"]); self.assertIsNone(r["error"])
        self.assertEqual(r["intent"], "music"); self.assertEqual(r["request_id"], "r1")
        self.assertEqual(r["chat_text"], "Playing Du Hast.")
        self.assertEqual(r["spoken_text"], "Playing Du Hast.")
        self.assertEqual(r["metadata"], {"uri": "x"}); self.assertEqual(r["actions"], [])

    def test_err_shape_and_code(self):
        r = cr.err("music", "r2", "not_found", "no match for X", "X isn't in your library yet.",
                   spoken_text="Sorry, I couldn't find X.")
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"], {"code": "not_found", "reason": "no match for X"})
        self.assertIn(r["error"]["code"], cr.ERROR_CODES)
        self.assertEqual(r["chat_text"], "X isn't in your library yet.")

    def test_err_rejects_unknown_code(self):
        self.assertRaises(ValueError, cr.err, "music", "r", "bogus", "x", "y")

    def test_from_legacy_success(self):
        leg = {"ok": True, "intent": "music", "request_id": "r3", "spoken": None, "played": True,
               "uri": "u", "provider": "filesystem_smb", "candidate": "Du Hast", "media_type": "track"}
        r = cr.from_legacy(leg)
        self.assertTrue(r["ok"]); self.assertEqual(r["intent"], "music")
        self.assertEqual(r["metadata"]["uri"], "u"); self.assertEqual(r["metadata"]["played"], True)
        self.assertTrue(r["chat_text"])  # chat_text always present

    def test_from_legacy_failure_maps_reason_to_error(self):
        leg = {"ok": False, "intent": "music", "request_id": "r4", "reason": "no local match",
               "spoken": "Sorry, I couldn't find My Way in the local library."}
        r = cr.from_legacy(leg)
        self.assertFalse(r["ok"]); self.assertEqual(r["error"]["reason"], "no local match")
        self.assertEqual(r["error"]["code"], "not_found")
        self.assertEqual(r["spoken_text"], leg["spoken"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
