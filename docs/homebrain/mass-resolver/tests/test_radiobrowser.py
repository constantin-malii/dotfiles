#!/usr/bin/env python3
"""Run: python tests/test_radiobrowser.py"""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import radiobrowser as rb


def rb_station(uuid, name):
    return {"item_id": uuid, "provider": "radiobrowser", "name": name,
            "uri": "radiobrowser://radio/" + uuid, "media_type": "radio",
            "provider_mappings": [{"provider_domain": "radiobrowser", "available": True}]}


def lib_station(n, name):
    return {"item_id": str(n), "provider": "library", "name": name,
            "uri": "library://radio/" + str(n), "media_type": "radio",
            "provider_mappings": [{"provider_domain": "radiobrowser", "available": True}]}


BACK = {"item_id": "back", "name": "..", "media_type": "folder", "is_playable": False}


class FakeMA(object):
    def __init__(self, browse_items=None, search_radio=None):
        self._browse = browse_items or []
        self._search = search_radio or []
        self.calls = []
    def cmd(self, command, **args):
        self.calls.append((command, args))
        if command == "music/browse":
            return {"result": {"items": self._browse}}
        if command == "music/search":
            return {"result": {"radio": self._search}}
        return None


class RadioBrowserTest(unittest.TestCase):
    def test_norm_name_strips(self):
        self.assertEqual(rb.norm_name("\n RADIO X \n"), "RADIO X")

    def test_station_from_radiobrowser_item(self):
        st = rb.station_from_item(rb_station("u1", " Jazz FM "))
        self.assertEqual(st, {"name": "Jazz FM", "uri": "radiobrowser://radio/u1", "source": "radiobrowser"})

    def test_station_from_library_item_is_favorite_source(self):
        st = rb.station_from_item(lib_station(2, "101 SMOOTH JAZZ"))
        self.assertEqual(st["source"], "favorite")
        self.assertEqual(st["uri"], "library://radio/2")

    def test_station_from_back_or_folder_is_none(self):
        self.assertIsNone(rb.station_from_item(BACK))
        self.assertIsNone(rb.station_from_item({"item_id": "x", "media_type": "folder"}))

    def test_station_unavailable_is_none(self):
        bad = rb_station("u2", "Dead"); bad["provider_mappings"] = [{"provider_domain": "radiobrowser", "available": False}]
        self.assertIsNone(rb.station_from_item(bad))

    def test_browse_filters_back_and_limits(self):
        ma = FakeMA(browse_items=[BACK, rb_station("u1", "A"), rb_station("u2", "B"), rb_station("u3", "C")])
        out = rb.browse(ma, "radiobrowser://category/country/ro", 2)
        self.assertEqual([s["name"] for s in out], ["A", "B"])
        self.assertEqual(ma.calls[0], ("music/browse", {"path": "radiobrowser://category/country/ro"}))

    def test_search_uses_music_search(self):
        ma = FakeMA(search_radio=[lib_station(2, "101 SMOOTH JAZZ"), rb_station("u9", "Jazz Gumbo")])
        out = rb.search(ma, "jazz", 5)
        self.assertEqual(out[0]["source"], "favorite")
        self.assertEqual(out[1]["name"], "Jazz Gumbo")
        cmd, args = ma.calls[0]
        self.assertEqual(cmd, "music/search")
        self.assertEqual(args["media_types"], ["radio"])

    def test_convenience_wrappers_build_paths(self):
        ma = FakeMA(browse_items=[rb_station("u1", "A")])
        rb.country_stations(ma, "ro", 5); rb.genre_stations(ma, "jazz", 5); rb.language_stations(ma, "ru", 5)
        paths = [a["path"] for c, a in ma.calls if c == "music/browse"]
        self.assertEqual(paths, ["radiobrowser://category/country/ro",
                                 "radiobrowser://category/tag/jazz",
                                 "radiobrowser://category/language/ru"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
