#!/usr/bin/env python3
"""Unit tests for raw WebSocket framing. Run: python tests/test_wsutil.py"""
import os, sys, json, struct, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import wsutil


class FakeSock(object):
    """Serves preloaded inbound bytes via recv(); captures outbound via sendall()."""
    def __init__(self, inbound=b""):
        self.inbound = inbound
        self.sent = b""
    def recv(self, n):
        if not self.inbound:
            return b""
        chunk = self.inbound[:n]; self.inbound = self.inbound[n:]; return chunk
    def sendall(self, data):
        self.sent += data


def server_text_frame(obj):
    """Build an UNMASKED server->client text frame (what HA/MA send)."""
    payload = json.dumps(obj).encode()
    ln = len(payload)
    if ln < 126:
        header = bytes(bytearray([0x81, ln]))
    elif ln < 65536:
        header = bytes(bytearray([0x81, 126])) + struct.pack(">H", ln)
    else:
        header = bytes(bytearray([0x81, 127])) + struct.pack(">Q", ln)
    return header + payload


class WsUtilTest(unittest.TestCase):
    def test_read_parses_server_text_frame(self):
        s = FakeSock(server_text_frame({"hello": "world", "n": 7}))
        msg = wsutil.ws_read(s, {"b": b""})
        self.assertEqual(msg, {"hello": "world", "n": 7})

    def test_read_returns_none_on_close_opcode(self):
        s = FakeSock(bytes(bytearray([0x88, 0x00])))  # FIN+close, len 0
        self.assertIsNone(wsutil.ws_read(s, {"b": b""}))

    def test_send_produces_masked_client_frame(self):
        s = FakeSock()
        wsutil.ws_send(s, {"a": 1})
        b = s.sent
        self.assertEqual(b[0], 0x81)          # FIN + text
        self.assertTrue(b[1] & 0x80)          # mask bit set (client frames must be masked)
        ln = b[1] & 0x7f
        mask = b[2:6]; masked = b[6:6 + ln]
        unmasked = bytes(bytearray(x ^ mask[i % 4] for i, x in enumerate(masked)))
        self.assertEqual(json.loads(unmasked.decode()), {"a": 1})


if __name__ == "__main__":
    unittest.main(verbosity=2)
