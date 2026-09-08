#!/usr/bin/env python3
"""Unit tests for config loading. Run: python tests/test_config.py"""
import os, sys, json, tempfile, shutil, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config


class ConfigTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="cfg_")
        self.addCleanup(shutil.rmtree, self.d, ignore_errors=True)

    def _write(self, name, obj):
        with open(os.path.join(self.d, name), "w") as f:
            json.dump(obj, f)

    def test_defaults_when_file_missing(self):
        s = config.load_settings(self.d)
        self.assertEqual(s.ma_host, "192.168.122.10")
        self.assertEqual(s.ma_port, 8095)
        self.assertEqual(s.provider_preference, ["filesystem_smb"])
        self.assertEqual(s.event_type, "mass_play_request")
        self.assertTrue(s.announce_failures)

    def test_ha_url_split_into_host_and_port(self):
        self._write("config.json", {"ha_url": "http://10.0.0.5:9123"})
        s = config.load_settings(self.d)
        self.assertEqual(s.ha_host, "10.0.0.5")
        self.assertEqual(s.ha_port, 9123)

    def test_overrides_are_applied(self):
        self._write("config.json", {"ma_port": 9999, "provider_preference": ["filesystem_smb", "spotify"]})
        s = config.load_settings(self.d)
        self.assertEqual(s.ma_port, 9999)
        self.assertEqual(s.provider_preference, ["filesystem_smb", "spotify"])

    def test_read_secret_missing_returns_none(self):
        self.assertIsNone(config.read_secret(self.d, ".ma_token"))

    def test_read_secret_strips_whitespace(self):
        with open(os.path.join(self.d, ".ma_token"), "w") as f:
            f.write("  tok123\n")
        self.assertEqual(config.read_secret(self.d, ".ma_token"), "tok123")

    def test_country_code_alias_lookup(self):
        radio = {"country_codes": {"romania": "ro", "russia": "ru"}}
        self.assertEqual(config.country_code(radio, "Romania"), "ro")
        self.assertEqual(config.country_code(radio, "RUSSIA"), "ru")
        self.assertIsNone(config.country_code(radio, "Atlantis"))


class InteractionTunablesTest(unittest.TestCase):
    def test_defaults(self):
        s = config.Settings({})
        self.assertEqual(s.interaction_floor, 15)
        self.assertEqual(s.fade_ms, 0)
        self.assertEqual(s.max_duck_timeout, 120000)
        self.assertTrue(s.interaction_ignore_when_idle)

    def test_overrides(self):
        s = config.Settings({"interaction_floor": 25, "fade_ms": 200,
                             "max_duck_timeout": 30000, "interaction_ignore_when_idle": False})
        self.assertEqual(s.interaction_floor, 25)
        self.assertEqual(s.fade_ms, 200)
        self.assertEqual(s.max_duck_timeout, 30000)
        self.assertFalse(s.interaction_ignore_when_idle)


class SayTunablesTest(unittest.TestCase):
    def test_defaults(self):
        s = config.Settings({})
        self.assertAlmostEqual(s.reply_volume, 0.40)
        self.assertEqual(s.say_start_timeout_ms, 5000)
        self.assertEqual(s.say_reply_timeout_ms, 180000)   # long knowledge-agent replies
        self.assertEqual(s.say_poll_ms, 500)
        self.assertEqual(s.say_internal_base, "192.168.122.10:8123")
        self.assertTrue(s.say_owns_restore)
        self.assertEqual(s.say_call_timeout_ms, 20000)      # MA play_media outruns the 5s REST default
        self.assertEqual(s.say_double_speak_window_ms, 8000)
        self.assertEqual(s.say_blank_cid_grace_ms, 8000)
        self.assertTrue(s.suppress_announce_during_interaction)
        self.assertEqual(s.interaction_turn_window_ms, 30000)

    def test_overrides(self):
        s = config.Settings({
            "reply_volume": 0.55,
            "say_start_timeout_ms": 7000,
            "say_reply_timeout_ms": 40000,
            "say_poll_ms": 250,
            "say_internal_base": "10.0.0.5:8123",
            "say_owns_restore": False,
            "say_call_timeout_ms": 12000,
            "say_double_speak_window_ms": 3000,
            "suppress_announce_during_interaction": False,
            "interaction_turn_window_ms": 9000,
        })
        self.assertAlmostEqual(s.reply_volume, 0.55)
        self.assertEqual(s.say_start_timeout_ms, 7000)
        self.assertEqual(s.say_reply_timeout_ms, 40000)
        self.assertEqual(s.say_poll_ms, 250)
        self.assertEqual(s.say_internal_base, "10.0.0.5:8123")
        self.assertFalse(s.say_owns_restore)
        self.assertEqual(s.say_call_timeout_ms, 12000)
        self.assertEqual(s.say_double_speak_window_ms, 3000)
        self.assertFalse(s.suppress_announce_during_interaction)
        self.assertEqual(s.interaction_turn_window_ms, 9000)

    def test_say_announce_timeout_ms_retired(self):
        s = config.Settings({})
        self.assertFalse(hasattr(s, "say_announce_timeout_ms"))



class TtsEngineSettingTest(unittest.TestCase):
    """say_text picks the TTS engine from settings. The setting has to EXIST in config, or the
    hardcoded fallback silently wins and the knob is unreachable -- which also blocks giving the
    resolver the same voice the Assist pipeline uses."""

    def test_default_is_piper(self):
        self.assertEqual(config.Settings({}).tts_engine, "tts.piper")

    def test_engine_is_overridable(self):
        self.assertEqual(config.Settings({"tts_engine": "tts.other"}).tts_engine, "tts.other")



class AnnounceTunablesTest(unittest.TestCase):
    """AN-01 Task 9: the announce mode's tunables (design 6.2 and 6.5).

    Two values here are measurements, not guesses:
      * announce_mic_mute_entity is D1, settled at AN-2.
      * announce_mic_confirm_timeout_ms is sized from the measured 255ms read-back latency.
    """

    CHIME = "media-source://media_source/local/timer_chime.wav"

    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="cfg_")
        self.addCleanup(shutil.rmtree, self.d, ignore_errors=True)

    def _write(self, obj):
        with open(os.path.join(self.d, "config.json"), "w") as f:
            json.dump(obj, f)

    def test_defaults(self):
        s = config.load_settings(self.d)
        self.assertEqual(s.announce_volume, 0.80)
        self.assertEqual(s.announce_prefix, "")
        self.assertEqual(s.announce_max_prefix_chars, 40)
        self.assertEqual(s.announce_chime_uri, self.CHIME)
        self.assertEqual(s.announce_mic_mute_entity, "")
        self.assertTrue(s.announce_require_mic_mute)
        self.assertEqual(s.announce_mic_confirm_timeout_ms, 2000)
        self.assertEqual(s.announce_mic_confirm_poll_ms, 250)
        self.assertEqual(s.announce_mic_deadman_ms, 0)
        self.assertEqual(s.announce_volume_deadman_ms, 0)
        self.assertEqual(s.announce_volume_deadman_retries, 3)
        self.assertEqual(s.announce_chime_finish_timeout_ms, 15000)
        self.assertEqual(s.announce_message_finish_timeout_ms, 45000)
        self.assertEqual(s.announce_max_chars, 300)
        self.assertEqual(s.announce_min_call_timeout_ms, 500)

    def test_the_chime_default_has_no_dot_segment(self):
        # AN-1 root cause: a './' makes HA sign the un-normalised path while returning a normalised
        # url, so the signature cannot validate. This default must never carry one again.
        s = config.load_settings(self.d)
        self.assertNotIn("/./", s.announce_chime_uri)

    def test_overrides(self):
        self._write({"announce_volume": 0.55, "announce_prefix": "Attention.",
                     "announce_chime_uri": "", "announce_require_mic_mute": False,
                     "announce_max_chars": 120, "announce_mic_confirm_timeout_ms": 4000,
                     "announce_mic_mute_entity": "switch.other",
                     "announce_volume_deadman_retries": 1})
        s = config.load_settings(self.d)
        self.assertEqual(s.announce_volume, 0.55)
        self.assertEqual(s.announce_prefix, "Attention.")
        self.assertEqual(s.announce_chime_uri, "")
        self.assertFalse(s.announce_require_mic_mute)
        self.assertEqual(s.announce_max_chars, 120)
        self.assertEqual(s.announce_mic_confirm_timeout_ms, 4000)
        self.assertEqual(s.announce_mic_mute_entity, "switch.other")
        self.assertEqual(s.announce_volume_deadman_retries, 1)

    def test_require_mic_mute_can_be_switched_off_by_config(self):
        # It is the fail-safe for requirement 7, so the escape hatch must actually work.
        self._write({"announce_require_mic_mute": False})
        self.assertFalse(config.load_settings(self.d).announce_require_mic_mute)


class ShippedAnnounceConfigTest(unittest.TestCase):
    """Assertions against the REAL config.json that gets deployed, not a temp dir."""

    def _shipped(self):
        here = os.path.dirname(os.path.dirname(os.path.abspath(config.__file__)))
        return config.load_settings(os.path.join(here, "mass-resolver"))

    def test_announce_volume_is_above_reply_volume(self):
        # Guards against an edit quietly making announcements quieter than ordinary replies.
        s = self._shipped()
        self.assertGreater(s.announce_volume, s.reply_volume)

    def test_the_mic_mute_entity_is_the_settled_D1_value(self):
        # D1, settled at AN-2 2026-09-07. An empty value makes every announcement refuse.
        s = self._shipped()
        self.assertEqual(s.announce_mic_mute_entity,
                         "switch.respeaker_living_room_microphone_mute")

    def test_the_shipped_chime_uri_has_no_dot_segment(self):
        self.assertNotIn("/./", self._shipped().announce_chime_uri)

    def test_the_confirm_budget_clears_the_measured_readback_latency(self):
        # AN-2 measured 255ms for the switch to report back, in both directions. The budget must
        # leave real headroom; too tight and every announcement refuses.
        s = self._shipped()
        self.assertGreaterEqual(s.announce_mic_confirm_timeout_ms, 4 * 255)

    def test_the_confirm_poll_fits_inside_the_confirm_budget(self):
        s = self._shipped()
        self.assertLess(s.announce_mic_confirm_poll_ms, s.announce_mic_confirm_timeout_ms)

    def test_the_engineered_phase_budget_stays_under_the_rest_command_timeout(self):
        # design 6.5: an arithmetic self-consistency check as timeouts are tuned. It does NOT claim
        # the budget bounds wall-clock duration -- a socket timeout is a per-operation inactivity
        # timeout, not a request deadline.
        s = self._shipped()
        start = s.say_start_timeout_ms
        call = s.say_call_timeout_ms
        budget_ms = (10000 + 10000 + 10000 + 5000 + s.announce_mic_confirm_timeout_ms
                     + 5000 + 5000
                     + call + start + s.announce_chime_finish_timeout_ms
                     + call + start + s.announce_message_finish_timeout_ms
                     + 5000 + call + 5000
                     + 5 * s.announce_min_call_timeout_ms)
        self.assertLess(budget_ms / 1000.0, 200.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
