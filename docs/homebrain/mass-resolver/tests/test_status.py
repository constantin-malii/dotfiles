#!/usr/bin/env python3
"""Inc 4A Status / Now-Playing unit tests. Run: python tests/test_status.py

Fixtures are derived from the Phase-2 HA Developer Tools -> States captures (sanitized):
docs/homebrain/2026-06-29-inc4a-status-now-playing-design.md (design SS2 mapping table).
"""
import os, sys, threading, unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import capability, status, core, haconn


def st(state, **attrs):
    return {"state": state, "attributes": dict(attrs)}


# --- Phase-2 captures -----------------------------------------------------------------------------
# Capture 1 - radio playing (note: no media_artist present).
RADIO_PLAYING = st("playing", volume_level=0.27, media_content_id="library://radio/2",
                   media_content_type="music", media_title="Euge Groove",
                   media_album_name="101 SMOOTH JAZZ", source="Music Assistant Queue")
# Capture 2 - idle after radio: retains stale media_title/artist/album.
IDLE_AFTER_RADIO = st("idle", volume_level=0.27, media_content_id="library://radio/2",
                      media_content_type="music", media_title="Blue Glide",
                      media_album_name="101 SMOOTH JAZZ", media_artist="Sapphire Horizon",
                      source="Music Assistant Queue")
# Capture 3 - paused radio with retained metadata.
PAUSED_RADIO = st("paused", volume_level=0.27, media_content_id="library://radio/2",
                  media_content_type="music", media_title="Blue Glide",
                  media_artist="Sapphire Horizon", media_album_name="101 SMOOTH JAZZ",
                  source="Music Assistant Queue")
# Capture 4 - track/music playing with artist "[unknown]".
TRACK_PLAYING = st("playing", volume_level=0.27, media_content_id="library://track/41",
                   media_content_type="music", media_title="Gde Belomora Dostati",
                   media_artist="[unknown]", source="Music Assistant Queue")
# Synthetic states.
OFF = st("off", volume_level=0.27, media_content_id="library://radio/2", media_title="Blue Glide")
UNAVAILABLE = st("unavailable")


class FakeHA(object):
    """Stubs the isolated read-only HA state read (Phase 4 wires this to an HA REST GET)."""
    def __init__(self, state=None, boom=None):
        self._state = state
        self._boom = boom

    def get_entity_state(self, entity_id):
        if self._boom is not None:
            raise self._boom
        return self._state


class FakeSettings(object):
    ceiling_entity = "media_player.ceiling_speakers"
    announce_failures = True


class FakeSpeaker(object):
    def __init__(self):
        self.said = []
    def speak(self, text):
        if text:
            self.said.append(text)


class FakeCtx(object):
    def __init__(self, ha):
        self.ha = ha
        self.settings = FakeSettings()


def run_status(ha_state=None, boom=None):
    ctx = FakeCtx(FakeHA(state=ha_state, boom=boom))
    return capability.run(status.StatusCapability(), ctx, {}, "rid1")


# --- Normalizer (pure) ----------------------------------------------------------------------------
class NormalizeTest(unittest.TestCase):
    def test_radio_playing(self):
        m = status.normalize_status(RADIO_PLAYING)
        self.assertEqual(m["player_state"], "playing")
        self.assertEqual(m["content_kind"], "radio")
        self.assertEqual(m["station"], "101 SMOOTH JAZZ")   # media_album_name = station
        self.assertEqual(m["title"], "Euge Groove")
        self.assertIsNone(m["artist"])                      # absent in Capture 1
        self.assertEqual(m["volume_percent"], 27)

    def test_track_playing_unknown_artist(self):
        m = status.normalize_status(TRACK_PLAYING)
        self.assertEqual(m["content_kind"], "track")
        self.assertEqual(m["title"], "Gde Belomora Dostati")
        self.assertIsNone(m["artist"])                      # "[unknown]" -> None
        self.assertIsNone(m["album"])
        self.assertEqual(m["volume_percent"], 27)

    def test_content_type_is_not_the_discriminator(self):
        # media_content_type is "music" for BOTH; only media_content_id prefix decides.
        self.assertEqual(status.normalize_status(RADIO_PLAYING)["content_kind"], "radio")
        self.assertEqual(status.normalize_status(TRACK_PLAYING)["content_kind"], "track")

    def test_paused_reports_paused_metadata_no_discriminator(self):
        m = status.normalize_status(PAUSED_RADIO)
        self.assertEqual(m["player_state"], "paused")
        self.assertEqual(m["content_kind"], "none")         # discriminator only while playing
        self.assertEqual(m["title"], "Blue Glide")
        self.assertEqual(m["artist"], "Sapphire Horizon")
        self.assertIsNone(m["station"])

    def test_idle_ignores_stale_metadata(self):
        m = status.normalize_status(IDLE_AFTER_RADIO)
        self.assertEqual(m["player_state"], "idle")
        self.assertEqual(m["content_kind"], "none")
        self.assertIsNone(m["title"]); self.assertIsNone(m["artist"])
        self.assertIsNone(m["station"]); self.assertIsNone(m["album"])

    def test_off_is_nothing_playing_and_available(self):
        m = status.normalize_status(OFF)
        self.assertEqual(m["player_state"], "off")
        self.assertEqual(m["content_kind"], "none")
        self.assertTrue(m["available"])
        self.assertIsNone(m["title"])

    def test_unavailable_state(self):
        m = status.normalize_status(UNAVAILABLE)
        self.assertEqual(m["player_state"], "unavailable")
        self.assertFalse(m["available"])
        self.assertEqual(m["content_kind"], "none")

    def test_missing_content_id_while_playing_with_title(self):
        m = status.normalize_status(st("playing", volume_level=0.5,
                                       media_title="Some Song", media_artist="Some Artist"))
        self.assertEqual(m["content_kind"], "unknown")      # not fabricated as radio/track
        self.assertEqual(m["title"], "Some Song")
        self.assertEqual(m["artist"], "Some Artist")

    def test_missing_content_id_and_title_while_playing(self):
        m = status.normalize_status(st("playing", volume_level=0.5))
        self.assertEqual(m["content_kind"], "unknown")
        self.assertIsNone(m["title"])

    # volume edges
    def test_volume_null(self):
        m = status.normalize_status(st("idle"))
        self.assertIsNone(m["volume_level"]); self.assertIsNone(m["volume_percent"])

    def test_volume_zero(self):
        m = status.normalize_status(st("playing", volume_level=0.0,
                                       media_content_id="library://track/1", media_title="x"))
        self.assertEqual(m["volume_percent"], 0)

    def test_volume_near_silent(self):
        m = status.normalize_status(st("playing", volume_level=0.09,
                                       media_content_id="library://track/1", media_title="x"))
        self.assertEqual(m["volume_percent"], 9)

    def test_volume_round_half_up(self):
        m = status.normalize_status(st("playing", volume_level=0.355,
                                       media_content_id="library://track/1", media_title="x"))
        self.assertEqual(m["volume_percent"], 36)

    def test_artist_normalization(self):
        self.assertIsNone(status._norm_artist("[unknown]"))
        self.assertIsNone(status._norm_artist("[UNKNOWN]"))
        self.assertIsNone(status._norm_artist("   "))
        self.assertIsNone(status._norm_artist(None))
        self.assertEqual(status._norm_artist("  Rammstein "), "Rammstein")


# --- chat_text builder (pure) ---------------------------------------------------------------------
class ChatTextTest(unittest.TestCase):
    def test_radio(self):
        self.assertEqual(status.build_chat_text(status.normalize_status(RADIO_PLAYING)),
                         "Playing 101 SMOOTH JAZZ at 27% volume.")

    def test_track_no_by_for_unknown_artist(self):
        txt = status.build_chat_text(status.normalize_status(TRACK_PLAYING))
        self.assertEqual(txt, 'Playing "Gde Belomora Dostati" at 27% volume.')
        self.assertNotIn(" by ", txt)

    def test_track_with_artist(self):
        m = status.normalize_status(st("playing", volume_level=0.35,
                                       media_content_id="library://track/1",
                                       media_title="Du Hast", media_artist="Rammstein"))
        self.assertEqual(status.build_chat_text(m), 'Playing "Du Hast" by Rammstein at 35% volume.')

    def test_paused_says_paused_not_playing(self):
        txt = status.build_chat_text(status.normalize_status(PAUSED_RADIO))
        self.assertIn("paused", txt.lower())
        self.assertNotIn("Playing", txt)

    def test_idle(self):
        self.assertEqual(status.build_chat_text(status.normalize_status(IDLE_AFTER_RADIO)),
                         "Nothing is playing right now.")

    def test_off(self):
        self.assertEqual(status.build_chat_text(status.normalize_status(OFF)),
                         "Nothing is playing right now.")

    def test_unavailable(self):
        self.assertIn("unavailable",
                      status.build_chat_text(status.normalize_status(UNAVAILABLE)).lower())


# --- Capability (resolve -> validate -> execute -> CommandResult) ---------------------------------
class CapabilityTest(unittest.TestCase):
    def test_playing_track_ok_silent(self):
        r = run_status(TRACK_PLAYING)
        self.assertTrue(r["ok"]); self.assertEqual(r["intent"], "status")
        self.assertIsNone(r["error"]); self.assertIsNone(r["spoken_text"])
        self.assertEqual(r["metadata"]["content_kind"], "track")
        self.assertEqual(r["chat_text"], 'Playing "Gde Belomora Dostati" at 27% volume.')

    def test_playing_radio_ok_silent(self):
        r = run_status(RADIO_PLAYING)
        self.assertTrue(r["ok"]); self.assertIsNone(r["spoken_text"])
        self.assertEqual(r["metadata"]["content_kind"], "radio")
        self.assertEqual(r["metadata"]["station"], "101 SMOOTH JAZZ")

    def test_idle_ok_silent_nothing_playing(self):
        r = run_status(IDLE_AFTER_RADIO)
        self.assertTrue(r["ok"]); self.assertIsNone(r["spoken_text"])
        self.assertEqual(r["chat_text"], "Nothing is playing right now.")

    def test_paused_ok_silent(self):
        r = run_status(PAUSED_RADIO)
        self.assertTrue(r["ok"]); self.assertIsNone(r["spoken_text"])
        self.assertIn("paused", r["chat_text"].lower())

    def test_read_failure_unavailable_silent(self):
        r = run_status(boom=RuntimeError("connection refused"))
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"]["code"], "unavailable")
        self.assertIsNone(r["spoken_text"])
        self.assertFalse(r["metadata"]["available"])

    def test_none_state_unavailable_silent(self):
        r = run_status(ha_state=None)            # FakeHA returns None
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"]["code"], "unavailable")
        self.assertIsNone(r["spoken_text"])

    def test_success_and_error_both_silent(self):
        self.assertIsNone(run_status(RADIO_PLAYING)["spoken_text"])
        self.assertIsNone(run_status(boom=RuntimeError("x"))["spoken_text"])


# --- core wiring (Phase 4) ------------------------------------------------------------------------
class CoreWiringTest(unittest.TestCase):
    def test_status_registered_in_caps_not_stubs(self):
        self.assertIn("status", core.CAPS)
        self.assertIsInstance(core.CAPS["status"], status.StatusCapability)
        self.assertNotIn("status", core._STUBS)

    def _ctx(self, ha):
        spk = FakeSpeaker()
        ctx = core.Ctx(ma_factory=lambda: None, ha=ha, settings=FakeSettings(),
                       radio_cfg={}, news_cfg={}, speaker=spk)
        return ctx, spk

    def test_dispatch_routes_status_to_capability_silent(self):
        ctx, spk = self._ctx(FakeHA(state=TRACK_PLAYING))
        r = core.dispatch(ctx, "status", {})
        self.assertTrue(r["ok"])
        self.assertEqual(r["intent"], "status")
        self.assertEqual(r["metadata"]["content_kind"], "track")
        self.assertEqual(spk.said, [])                      # spoken_text=None -> nothing spoken

    def test_dispatch_status_read_failure_unavailable_silent(self):
        ctx, spk = self._ctx(FakeHA(boom=RuntimeError("conn refused")))
        r = core.dispatch(ctx, "status", {})
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"]["code"], "unavailable")
        self.assertEqual(spk.said, [])                      # silent even on error (spoken_text=None)


# --- haconn HA REST reader (Phase 4) --------------------------------------------------------------
_STATES_BODY = (
    '{"entity_id": "media_player.ceiling_speakers", "state": "playing", '
    '"attributes": {"volume_level": 0.27, "media_content_id": "library://track/41", '
    '"media_content_type": "music", "media_title": "Du Hast", "media_artist": "Rammstein"}}'
).encode("utf-8")


class _StubHAHandler(BaseHTTPRequestHandler):
    captured = {}
    def do_GET(self):
        _StubHAHandler.captured = {"path": self.path,
                                   "auth": self.headers.get("Authorization")}
        if self.path == "/api/states/media_player.ceiling_speakers":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(_STATES_BODY)
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'{"message":"Entity not found."}')
    def log_message(self, *a):
        pass


class HARestReaderTest(unittest.TestCase):
    def setUp(self):
        _StubHAHandler.captured = {}
        self.srv = HTTPServer(("127.0.0.1", 0), _StubHAHandler)
        self.port = self.srv.server_address[1]
        self.t = threading.Thread(target=self.srv.serve_forever)
        self.t.daemon = True
        self.t.start()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()

    def test_reader_success_returns_state_and_sends_bearer(self):
        ha = haconn.HA("127.0.0.1", self.port, "test-token")
        state = ha.get_entity_state("media_player.ceiling_speakers")
        self.assertEqual(state["state"], "playing")
        self.assertEqual(state["attributes"]["media_content_id"], "library://track/41")
        # correct REST path + Bearer header was sent (token value is a throwaway test token)
        self.assertEqual(_StubHAHandler.captured["path"], "/api/states/media_player.ceiling_speakers")
        self.assertEqual(_StubHAHandler.captured["auth"], "Bearer test-token")

    def test_reader_non_200_raises(self):
        ha = haconn.HA("127.0.0.1", self.port, "test-token")
        with self.assertRaises(Exception):
            ha.get_entity_state("media_player.does_not_exist")

    def test_capability_over_real_reader_ok(self):
        ha = haconn.HA("127.0.0.1", self.port, "test-token")
        r = capability.run(status.StatusCapability(), FakeCtx(ha), {}, "rid")
        self.assertTrue(r["ok"])
        self.assertEqual(r["metadata"]["content_kind"], "track")
        self.assertEqual(r["chat_text"], 'Playing "Du Hast" by Rammstein at 27% volume.')
        self.assertIsNone(r["spoken_text"])

    def test_capability_read_failure_maps_to_unavailable(self):
        # Point at a closed port (server shut down) -> connection refused -> unavailable.
        self.srv.shutdown(); self.srv.server_close()
        ha = haconn.HA("127.0.0.1", self.port, "test-token")
        r = capability.run(status.StatusCapability(), FakeCtx(ha), {}, "rid")
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"]["code"], "unavailable")
        self.assertIsNone(r["spoken_text"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
