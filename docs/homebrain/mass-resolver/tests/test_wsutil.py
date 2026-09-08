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



class TimeoutFakeSock(object):
    """Records the socket-level calls ws_connect makes, and serves a handshake response."""

    def __init__(self, outer, inbound):
        self.outer = outer
        self.inbound = inbound
        self.sent = b""

    def setsockopt(self, *a):
        self.outer.calls.append(("setsockopt", a[:2]))

    def settimeout(self, t):
        self.outer.calls.append(("settimeout", t))

    def sendall(self, b):
        self.sent += b

    def recv(self, n):
        out, self.inbound = self.inbound[:n], self.inbound[n:]
        return out


class WsConnectTimeoutTest(unittest.TestCase):
    """AN-01 Task 6: ws_connect must accept a timeout so a WS call can be bounded at all.

    Why this exists: haconn.resolve_media_source (AN-01 Task 8) is called from a phase that holds a
    deadline, and design 6.5 requires blocking calls to be clipped to what is left of it. With the
    timeout hardcoded, a nearly-expired phase would still block on the full 15s default.

    The default stays 15s, and both existing callers (haconn.connect -> settimeout(None),
    maconn.connect -> settimeout(60)) override the socket timeout immediately afterwards, so their
    behaviour is unchanged either way.
    """

    HANDSHAKE = b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n\r\nLEFTOVER"

    def setUp(self):
        self.calls = []
        self.created = []
        self.real_create = wsutil.socket.create_connection

        def fake_create(addr, timeout=None):
            self.created.append((addr, timeout))
            return TimeoutFakeSock(self, self.HANDSHAKE)

        wsutil.socket.create_connection = fake_create
        self.addCleanup(setattr, wsutil.socket, "create_connection", self.real_create)

    def test_default_is_still_15s(self):
        wsutil.ws_connect("h", 1, "/ws")
        self.assertEqual(self.created, [(("h", 1), 15)])

    def test_default_is_also_applied_to_the_handshake_read(self):
        wsutil.ws_connect("h", 1, "/ws")
        self.assertIn(("settimeout", 15), self.calls)

    def test_explicit_timeout_reaches_the_connect(self):
        wsutil.ws_connect("h", 1, "/ws", timeout=3)
        self.assertEqual(self.created, [(("h", 1), 3)])

    def test_explicit_timeout_is_also_applied_to_the_handshake_read(self):
        # The connect timeout does not bound the recv loop below it, so a slow peer could hold the
        # handshake open past the caller's budget. The parameter must reach both.
        wsutil.ws_connect("h", 1, "/ws", timeout=3)
        self.assertIn(("settimeout", 3), self.calls)

    def test_keepalive_is_still_set(self):
        wsutil.ws_connect("h", 1, "/ws", timeout=3)
        self.assertIn(("setsockopt", (wsutil.socket.SOL_SOCKET, wsutil.socket.SO_KEEPALIVE)),
                      self.calls)

    def test_handshake_is_still_parsed_and_leftover_bytes_returned(self):
        # Guards the refactor: the recv loop and the header/body split must be untouched.
        s, box = wsutil.ws_connect("h", 1, "/ws", timeout=3)
        self.assertEqual(box["b"], b"LEFTOVER")
        self.assertIn(b"GET /ws HTTP/1.1", s.sent)
        self.assertIn(b"Sec-WebSocket-Version: 13", s.sent)


if __name__ == "__main__":
    unittest.main(verbosity=2)
