#!/usr/bin/env python3
"""Unit tests for the HA client service-call/announce composition. Run: python tests/test_haconn.py"""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import haconn


class FakeSettings(object):
    def __init__(self, tts_service="", tts_data=None, ceiling_entity="media_player.ceiling_speakers"):
        self.tts_service = tts_service
        self.tts_data = tts_data or {}
        self.ceiling_entity = ceiling_entity


class HaConnTest(unittest.TestCase):
    def _ha(self):
        h = haconn.HA("host", 1, "tok")
        h.sent = []
        h.call_service = lambda domain, service, data: h.sent.append((domain, service, data))
        return h

    def test_call_service_split_used_by_announce(self):
        h = self._ha()
        s = FakeSettings(tts_service="tts.speak",
                         tts_data={"entity_id": "tts.home", "media_player_entity_id": "{entity}", "message": "{msg}"})
        h.announce("Couldn't find Engel locally.", s)
        self.assertEqual(len(h.sent), 1)
        domain, service, data = h.sent[0]
        self.assertEqual(domain, "tts")
        self.assertEqual(service, "speak")
        self.assertEqual(data["message"], "Couldn't find Engel locally.")
        self.assertEqual(data["media_player_entity_id"], "media_player.ceiling_speakers")
        self.assertEqual(data["entity_id"], "tts.home")

    def test_announce_noops_when_no_tts_service(self):
        h = self._ha()
        h.announce("anything", FakeSettings(tts_service=""))
        self.assertEqual(h.sent, [])

    def test_announce_noops_when_service_part_missing(self):
        h = self._ha()
        h.announce("x", FakeSettings(tts_service="tts"))    # no dot -> no service
        h.announce("y", FakeSettings(tts_service="tts."))   # trailing dot -> empty service
        self.assertEqual(h.sent, [])

    def test_announce_survives_none_ceiling_entity(self):
        h = self._ha()
        s = FakeSettings(tts_service="tts.speak",
                         tts_data={"media_player_entity_id": "{entity}", "message": "{msg}"},
                         ceiling_entity=None)
        h.announce("hello", s)   # must not raise
        self.assertEqual(len(h.sent), 1)
        _, _, data = h.sent[0]
        self.assertEqual(data["media_player_entity_id"], "")   # None entity renders to empty string
        self.assertEqual(data["message"], "hello")

    def test_announce_propagates_send_failure(self):
        h = self._ha()
        def boom(domain, service, data):
            raise BrokenPipeError(32, "Broken pipe")
        h.call_service = boom
        s = FakeSettings(tts_service="tts.speak",
                         tts_data={"media_player_entity_id": "{entity}", "message": "{msg}"})
        with self.assertRaises(BrokenPipeError):
            h.announce("hello", s)


class SendLockTest(unittest.TestCase):
    def test_call_service_holds_lock_during_send(self):
        ha = haconn.HA("h", 1, "tok")
        held = {"during_send": None}
        class FakeSock(object):
            def sendall(self, b):
                held["during_send"] = ha._send_lock.locked()
        ha.s = FakeSock()
        ha.call_service("media_player", "volume_set", {"entity_id": "x", "volume_level": 0.1})
        self.assertTrue(held["during_send"])          # lock held while sending
        self.assertFalse(ha._send_lock.locked())      # released after


class FakeResponse(object):
    def __init__(self, status):
        self.status = status
    def read(self):
        return b""


class FakeHTTPConnection(object):
    created = []

    def __init__(self, host, port, timeout=None):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.requests = []
        self.status = 200
        FakeHTTPConnection.created.append(self)

    def request(self, method, path, body=None, headers=None):
        self.requests.append({"method": method, "path": path, "body": body, "headers": headers})

    def getresponse(self):
        return FakeResponse(self.status)

    def close(self):
        pass


class CallServiceRestTest(unittest.TestCase):
    def setUp(self):
        FakeHTTPConnection.created = []
        self._real_conn = haconn.http.client.HTTPConnection
        haconn.http.client.HTTPConnection = FakeHTTPConnection
        self.addCleanup(self._restore)

    def _restore(self):
        haconn.http.client.HTTPConnection = self._real_conn

    def test_posts_correct_method_and_path(self):
        ha = haconn.HA("host", 1, "tok")
        ha.call_service_rest("media_player", "volume_set", {"entity_id": "x", "volume_level": 0.1})
        conn = FakeHTTPConnection.created[0]
        req = conn.requests[0]
        self.assertEqual(req["method"], "POST")
        self.assertEqual(req["path"], "/api/services/media_player/volume_set")

    def test_sends_bearer_auth_and_json_content_type(self):
        ha = haconn.HA("host", 1, "tok")
        ha.call_service_rest("media_player", "volume_set", {"entity_id": "x", "volume_level": 0.1})
        req = FakeHTTPConnection.created[0].requests[0]
        self.assertEqual(req["headers"]["Authorization"], "Bearer tok")
        self.assertEqual(req["headers"]["Content-Type"], "application/json")

    def test_non_2xx_raises(self):
        ha = haconn.HA("host", 1, "tok")
        FakeHTTPConnection.created = []
        orig_init = FakeHTTPConnection.__init__
        def init_with_bad_status(self, host, port, timeout=None):
            orig_init(self, host, port, timeout)
            self.status = 500
        FakeHTTPConnection.__init__ = init_with_bad_status
        try:
            with self.assertRaises(Exception):
                ha.call_service_rest("media_player", "volume_set", {"entity_id": "x", "volume_level": 0.1})
        finally:
            FakeHTTPConnection.__init__ = orig_init

    def test_never_touches_shared_websocket(self):
        ha = haconn.HA("host", 1, "tok")
        self.assertIsNone(ha.s)
        ha.call_service_rest("media_player", "volume_set", {"entity_id": "x", "volume_level": 0.1})
        self.assertIsNone(ha.s)

    def test_timeout_parameter_is_passed_to_connection(self):
        ha = haconn.HA("host", 1, "tok")
        FakeHTTPConnection.created = []
        ha.call_service_rest("media_player", "volume_set", {"entity_id": "x", "volume_level": 0.1}, timeout=30)
        self.assertEqual(FakeHTTPConnection.created[0].timeout, 30)

    def test_timeout_defaults_to_5_when_omitted(self):
        ha = haconn.HA("host", 1, "tok")
        FakeHTTPConnection.created = []
        ha.call_service_rest("media_player", "volume_set", {"entity_id": "x", "volume_level": 0.1})
        self.assertEqual(FakeHTTPConnection.created[0].timeout, 5)



class TtsGetUrlTest(unittest.TestCase):
    """The ceiling cannot be handed a sentence -- only a clip URL -- because MA's announce path is
    broken on this player. HA's /api/tts_get_url turns text into that URL."""

    def _ha(self, reply):
        h = haconn.HA("host", 1, "tok")
        h.posted = []
        h._post_json = lambda path, data, timeout=10: (h.posted.append((path, data)) or reply)
        return h

    def test_posts_engine_and_message_and_returns_the_url(self):
        h = self._ha({"url": "http://192.168.122.10:8123/api/tts_proxy/abc.mp3", "path": "/x"})
        url = h.tts_get_url("tts.piper", "Your timer is finished.")
        self.assertEqual(url, "http://192.168.122.10:8123/api/tts_proxy/abc.mp3")
        self.assertEqual(len(h.posted), 1)
        path, data = h.posted[0]
        self.assertEqual(path, "/api/tts_get_url")
        self.assertEqual(data["engine_id"], "tts.piper")
        self.assertEqual(data["message"], "Your timer is finished.")

    def test_missing_url_raises_rather_than_returning_none(self):
        h = self._ha({"path": "/x"})          # no url key
        self.assertRaises(IOError, h.tts_get_url, "tts.piper", "hello")



class TtsGetUrlAbsoluteTest(unittest.TestCase):
    def _ha(self, reply):
        h = haconn.HA("host", 1, "tok")
        h._post_json = lambda path, data, timeout=10: reply
        return h

    def test_relative_url_is_rejected(self):
        # A scheme-less url normalises to "//host/..." which MA cannot fetch; the failure would
        # otherwise surface only as a start-poll timeout, far from its cause.
        h = self._ha({"url": "/api/tts_proxy/abc.mp3"})
        self.assertRaises(IOError, h.tts_get_url, "tts.piper", "hello")


if __name__ == "__main__":
    unittest.main(verbosity=2)
