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



class StateResponse(object):
    def __init__(self, status, body):
        self.status = status
        self._body = body

    def read(self):
        return self._body


class StateConnection(object):
    """Self-contained fake for get_entity_state.

    Deliberately NOT an extension of FakeHTTPConnection: that fake has no response body (its
    FakeResponse.read returns b""), and get_entity_state json-parses what it reads. Monkeypatching
    the shared fake -- as CallServiceRestTest.test_non_2xx_raises does -- would put every other
    test using it in the blast radius for no benefit.
    """

    created = []
    status = 200
    body = b'{"entity_id": "switch.x", "state": "on", "attributes": {"volume_level": 0.4}}'

    def __init__(self, host, port, timeout=None):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.requests = []
        self.closed = False
        StateConnection.created.append(self)

    def request(self, method, path, body=None, headers=None):
        self.requests.append({"method": method, "path": path, "body": body,
                              "headers": headers or {}})

    def getresponse(self):
        return StateResponse(StateConnection.status, StateConnection.body)

    def close(self):
        self.closed = True


class GetEntityStateTimeoutTest(unittest.TestCase):
    """AN-01 Task 7: deadline clipping needs a per-call timeout (design 6.5).

    get_entity_state is the read used by every clip poll and by the mic-mute confirmation, so it is
    the call most likely to be started with only a fraction of a phase budget left. With the timeout
    hardcoded at 10s there was no way to clip it.

    The default stays 10s, so the existing callers -- _duck, _restore, _resume, _pause, _volume,
    _say's captures and polls -- are unchanged.
    """

    def setUp(self):
        StateConnection.created = []
        StateConnection.status = 200
        StateConnection.body = (b'{"entity_id": "switch.x", "state": "on", '
                                b'"attributes": {"volume_level": 0.4}}')
        self._real = haconn.http.client.HTTPConnection
        haconn.http.client.HTTPConnection = StateConnection
        self.addCleanup(self._restore)

    def _restore(self):
        haconn.http.client.HTTPConnection = self._real

    def test_default_is_still_10s(self):
        haconn.HA("host", 1, "tok").get_entity_state("switch.x")
        self.assertEqual(StateConnection.created[0].timeout, 10)

    def test_explicit_timeout_is_passed_to_the_connection(self):
        haconn.HA("host", 1, "tok").get_entity_state("switch.x", timeout=2.5)
        self.assertEqual(StateConnection.created[0].timeout, 2.5)

    def test_a_clipped_timeout_below_one_second_is_honoured(self):
        # design 6.5 clips to the remaining deadline, which is routinely sub-second near the floor.
        haconn.HA("host", 1, "tok").get_entity_state("switch.x", timeout=0.5)
        self.assertEqual(StateConnection.created[0].timeout, 0.5)

    def test_still_returns_the_parsed_state(self):
        d = haconn.HA("host", 1, "tok").get_entity_state("switch.x")
        self.assertEqual(d["state"], "on")
        self.assertEqual(d["attributes"]["volume_level"], 0.4)

    def test_still_requests_the_right_path_with_bearer_and_accept(self):
        haconn.HA("host", 1, "tok").get_entity_state("media_player.ceiling_speakers")
        req = StateConnection.created[0].requests[0]
        self.assertEqual(req["method"], "GET")
        self.assertEqual(req["path"], "/api/states/media_player.ceiling_speakers")
        self.assertEqual(req["headers"]["Authorization"], "Bearer tok")
        self.assertEqual(req["headers"]["Accept"], "application/json")

    def test_non_200_still_raises(self):
        StateConnection.status = 404
        self.assertRaises(IOError,
                          haconn.HA("host", 1, "tok").get_entity_state, "switch.nope")

    def test_the_connection_is_closed_even_when_it_raises(self):
        StateConnection.status = 500
        self.assertRaises(IOError,
                          haconn.HA("host", 1, "tok").get_entity_state, "switch.x")
        self.assertTrue(StateConnection.created[0].closed)

    def test_never_touches_the_shared_websocket(self):
        # Same rule as call_service_rest: a fresh per-call connection, so this is safe from the
        # HTTP server thread and never interleaves with the subscribe_events read loop.
        ha = haconn.HA("host", 1, "tok")
        self.assertIsNone(ha.s)
        ha.get_entity_state("switch.x", timeout=1)
        self.assertIsNone(ha.s)



class ResolveMediaSourceTest(unittest.TestCase):
    """AN-01 Task 8: media-source:// -> an absolute, MA-fetchable URL.

    Why it exists: MA rejects media-source:// outright and cannot fetch HA's authenticated
    /media/local/... paths. HA's own resolver hands back a SIGNED path, which is the only form MA
    can fetch -- proven at AN-1, where the corrected URI played on the ceiling.

    Two hard rules this class pins:
      * a FRESH WebSocket per call. media_source/resolve_media has no REST route, and self.s is the
        shared subscribe_events socket -- reusing it would interleave with that read loop.
      * the returned URL is a BEARER CREDENTIAL and must never be logged.
    """

    GOOD = "media-source://media_source/local/timer_chime.wav"
    DOTTED = "media-source://media_source/local/./timer_chime.wav"
    SIGNED = "/media/local/timer_chime.wav?authSig=REDACTED-NOT-A-REAL-SIGNATURE"

    def setUp(self):
        self.sent = []
        self.connects = []
        self.closed = []
        self.reads = [{"type": "auth_required"},
                      {"type": "auth_ok"},
                      {"id": 1, "type": "result", "success": True,
                       "result": {"url": self.SIGNED, "mime_type": "audio/x-wav"}}]
        outer = self

        class FakeSock(object):
            def close(self):
                outer.closed.append(True)

        def fake_connect(host, port, path, timeout=15):
            outer.connects.append({"host": host, "port": port, "path": path, "timeout": timeout})
            return FakeSock(), {"b": b""}

        def fake_send(sock, obj):
            outer.sent.append(obj)

        def fake_read(sock, box):
            return outer.reads.pop(0) if outer.reads else None

        for name, fn in (("ws_connect", fake_connect), ("ws_send", fake_send),
                         ("ws_read", fake_read)):
            real = getattr(haconn.wsutil, name)
            setattr(haconn.wsutil, name, fn)
            self.addCleanup(setattr, haconn.wsutil, name, real)

        self.ha = haconn.HA("192.168.122.10", 8123, "tok")

    # ---- happy path ---------------------------------------------------------

    def test_sends_the_resolve_command_and_returns_an_absolute_url(self):
        url = self.ha.resolve_media_source(self.GOOD)
        self.assertEqual(url, "http://192.168.122.10:8123" + self.SIGNED)
        self.assertIn({"id": 1, "type": "media_source/resolve_media",
                       "media_content_id": self.GOOD}, self.sent)

    def test_authenticates_before_resolving(self):
        self.ha.resolve_media_source(self.GOOD)
        self.assertEqual(self.sent[0]["type"], "auth")
        self.assertEqual(self.sent[0]["access_token"], "tok")
        self.assertEqual(self.sent[1]["type"], "media_source/resolve_media")

    def test_connects_to_the_websocket_path(self):
        self.ha.resolve_media_source(self.GOOD)
        self.assertEqual(self.connects[0]["path"], "/api/websocket")
        self.assertEqual(self.connects[0]["host"], "192.168.122.10")
        self.assertEqual(self.connects[0]["port"], 8123)

    # ---- URL normalisation --------------------------------------------------

    def test_an_absolute_url_is_returned_unchanged(self):
        self.reads[-1]["result"]["url"] = "http://1.2.3.4:8123/m.wav?authSig=REDACTED"
        self.assertEqual(self.ha.resolve_media_source(self.GOOD),
                         "http://1.2.3.4:8123/m.wav?authSig=REDACTED")

    def test_a_relative_url_is_absolutised_against_the_internal_base(self):
        # HA returns a RELATIVE signed path; MA cannot fetch that.
        url = self.ha.resolve_media_source(self.GOOD)
        self.assertTrue(url.startswith("http://192.168.122.10:8123/"))

    # ---- the './' trap ------------------------------------------------------

    def test_a_dotted_uri_is_normalised_before_it_is_sent(self):
        # AN-1 root cause: HA signs the UN-normalised path but returns a NORMALISED url, so a './'
        # segment yields a signature that cannot validate against the url it is attached to.
        # Normalising here means a caller pasting the media-browser form still gets a working url.
        self.ha.resolve_media_source(self.DOTTED)
        sent = [m for m in self.sent if m.get("type") == "media_source/resolve_media"][0]
        self.assertEqual(sent["media_content_id"], self.GOOD)
        self.assertNotIn("/./", sent["media_content_id"])

    # ---- timeout propagation -----------------------------------------------

    def test_the_timeout_is_passed_through_to_ws_connect(self):
        # design 6.5: without this the call cannot be clipped to a phase deadline at all.
        self.ha.resolve_media_source(self.GOOD, timeout=4)
        self.assertEqual(self.connects[0]["timeout"], 4)

    def test_the_default_timeout_is_10s(self):
        self.ha.resolve_media_source(self.GOOD)
        self.assertEqual(self.connects[0]["timeout"], 10)

    # ---- connection isolation ----------------------------------------------

    def test_never_touches_the_shared_websocket(self):
        sentinel = object()
        self.ha.s = sentinel
        self.ha.resolve_media_source(self.GOOD)
        self.assertIs(self.ha.s, sentinel)

    # ---- failure modes ------------------------------------------------------

    def test_missing_url_raises_rather_than_returning_none(self):
        self.reads[-1]["result"] = {"mime_type": "audio/x-wav"}
        self.assertRaises(IOError, self.ha.resolve_media_source, self.GOOD)

    def test_a_non_http_result_is_rejected(self):
        self.reads[-1]["result"]["url"] = "ftp://nope/x.wav"
        self.assertRaises(IOError, self.ha.resolve_media_source, self.GOOD)

    def test_an_unsuccessful_result_raises(self):
        self.reads[-1] = {"id": 1, "type": "result", "success": False,
                          "error": {"code": "not_found", "message": "no such media"}}
        self.assertRaises(IOError, self.ha.resolve_media_source, self.GOOD)

    def test_a_bad_hello_raises(self):
        self.reads[0] = {"type": "something_else"}
        self.assertRaises(IOError, self.ha.resolve_media_source, self.GOOD)

    def test_failed_auth_raises(self):
        self.reads[1] = {"type": "auth_invalid"}
        self.assertRaises(IOError, self.ha.resolve_media_source, self.GOOD)

    # ---- cleanup ------------------------------------------------------------

    def test_closes_its_connection_on_success(self):
        self.ha.resolve_media_source(self.GOOD)
        self.assertEqual(len(self.closed), 1)

    def test_closes_its_connection_on_failure(self):
        self.reads[-1]["result"] = {}
        self.assertRaises(IOError, self.ha.resolve_media_source, self.GOOD)
        self.assertEqual(len(self.closed), 1)

    # ---- the signed URL must never be logged --------------------------------

    def test_the_signed_url_is_never_logged(self):
        import logging
        recs = []

        class Grab(logging.Handler):
            def emit(self, r):
                try:
                    recs.append(r.getMessage())
                except Exception:
                    recs.append("<unformattable>")

        log = logging.getLogger("resolver")
        h = Grab()
        log.addHandler(h)
        self.addCleanup(log.removeHandler, h)
        old = log.level
        log.setLevel(logging.DEBUG)
        self.addCleanup(log.setLevel, old)

        self.ha.resolve_media_source(self.GOOD)
        self.assertTrue(recs, "expected at least one log record, so this test is not vacuous")
        for m in recs:
            self.assertNotIn("authSig", m)
            self.assertNotIn(self.SIGNED, m)
            self.assertNotIn("REDACTED-NOT-A-REAL-SIGNATURE", m)

    def test_a_failure_does_not_log_the_signed_url_either(self):
        import logging
        recs = []

        class Grab(logging.Handler):
            def emit(self, r):
                try:
                    recs.append(r.getMessage())
                except Exception:
                    recs.append("<unformattable>")

        log = logging.getLogger("resolver")
        h = Grab()
        log.addHandler(h)
        self.addCleanup(log.removeHandler, h)
        old = log.level
        log.setLevel(logging.DEBUG)
        self.addCleanup(log.setLevel, old)

        self.reads[-1]["result"]["url"] = "ftp://nope/x.wav?authSig=REDACTED-NOT-A-REAL-SIGNATURE"
        self.assertRaises(IOError, self.ha.resolve_media_source, self.GOOD)
        for m in recs:
            self.assertNotIn("authSig", m)
            self.assertNotIn("REDACTED-NOT-A-REAL-SIGNATURE", m)


if __name__ == "__main__":
    unittest.main(verbosity=2)
