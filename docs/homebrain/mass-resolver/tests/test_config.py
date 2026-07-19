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
        self.assertEqual(s.say_reply_timeout_ms, 30000)
        self.assertEqual(s.say_poll_ms, 500)
        self.assertEqual(s.say_internal_base, "192.168.122.10:8123")
        self.assertTrue(s.say_owns_restore)

    def test_overrides(self):
        s = config.Settings({
            "reply_volume": 0.55,
            "say_start_timeout_ms": 7000,
            "say_reply_timeout_ms": 40000,
            "say_poll_ms": 250,
            "say_internal_base": "10.0.0.5:8123",
            "say_owns_restore": False,
        })
        self.assertAlmostEqual(s.reply_volume, 0.55)
        self.assertEqual(s.say_start_timeout_ms, 7000)
        self.assertEqual(s.say_reply_timeout_ms, 40000)
        self.assertEqual(s.say_poll_ms, 250)
        self.assertEqual(s.say_internal_base, "10.0.0.5:8123")
        self.assertFalse(s.say_owns_restore)

    def test_say_announce_timeout_ms_retired(self):
        s = config.Settings({})
        self.assertFalse(hasattr(s, "say_announce_timeout_ms"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
