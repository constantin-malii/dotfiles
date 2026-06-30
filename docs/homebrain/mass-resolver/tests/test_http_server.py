#!/usr/bin/env python3
"""Run: python tests/test_http_server.py"""
import os, sys, json, threading, unittest
import urllib.request, urllib.error
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import http_server, command_result as cr


def fake_dispatch(intent, params):
    if intent == "music":
        return cr.ok("music", "r", "Playing.", spoken_text="Playing.", metadata={"q": params.get("query")})
    return cr.err(intent, "r", "not_implemented", "stub", "Not available yet.")


class HttpServerTest(unittest.TestCase):
    def setUp(self):
        self.srv = http_server.serve_http("127.0.0.1", 0, fake_dispatch, secret="s3cr3t")
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever).start()
    def tearDown(self):
        self.srv.shutdown(); self.srv.server_close()
    def _post(self, body, key="s3cr3t"):
        h = {"Content-Type": "application/json"}
        if key is not None: h["X-Resolver-Key"] = key
        req = urllib.request.Request("http://127.0.0.1:%d/command" % self.port, data=json.dumps(body).encode(), headers=h, method="POST")
        try:
            return 200, json.loads(urllib.request.urlopen(req, timeout=5).read().decode())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode())

    def test_ok(self):
        code, r = self._post({"intent": "music", "params": {"query": "X"}})
        self.assertEqual(code, 200); self.assertTrue(r["ok"]); self.assertEqual(r["metadata"]["q"], "X")
    def test_missing_intent_400(self):
        code, r = self._post({"params": {}})
        self.assertEqual(code, 400); self.assertEqual(r["error"]["code"], "invalid_input")
    def test_bad_secret_401(self):
        code, r = self._post({"intent": "music"}, key="wrong")
        self.assertEqual(code, 401); self.assertEqual(r["error"]["code"], "unauthorized")

    def test_no_secret_server_allows(self):
        """Server with secret=None allows requests without key header."""
        self.srv.shutdown(); self.srv.server_close()
        self.srv = http_server.serve_http("127.0.0.1", 0, fake_dispatch, secret=None)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever).start()
        code, r = self._post({"intent": "music", "params": {"query": "test"}}, key=None)
        self.assertEqual(code, 200); self.assertTrue(r["ok"])

    def test_malformed_body_400(self):
        """Malformed JSON body returns 400 with invalid_input error."""
        h = {"Content-Type": "application/json", "X-Resolver-Key": "s3cr3t"}
        req = urllib.request.Request("http://127.0.0.1:%d/command" % self.port, data=b"not json", headers=h, method="POST")
        try:
            urllib.request.urlopen(req, timeout=5)
            self.fail("Expected HTTPError")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 400)
            r = json.loads(e.read().decode())
            self.assertEqual(r["error"]["code"], "invalid_input")

    def test_non_dict_json_400(self):
        """JSON array (non-dict) returns 400 with invalid_input error."""
        code, r = self._post([1, 2, 3])
        self.assertEqual(code, 400); self.assertEqual(r["error"]["code"], "invalid_input")


if __name__ == "__main__":
    unittest.main(verbosity=2)
