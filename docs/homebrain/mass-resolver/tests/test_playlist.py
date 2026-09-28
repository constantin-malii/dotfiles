#!/usr/bin/env python3
"""MR-08: curated playlists, aliases, phrase handling. Run: python -m unittest tests.test_playlist -v"""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import capability
import music


class FakeSettings(object):
    provider_preference = ["filesystem_smb"]
    type_order = ["artist", "album", "track", "playlist"]
    queue_id = "q1"
    dry_run = False
    playlist_aliases = {}


class FakeMA(object):
    def __init__(self, data=None, tracks=None):
        self._data = data or {}
        self._tracks = tracks or {}          # playlist item_id -> [track dicts]
        self.played = []
        self.track_calls = []
        self.track_limits = []
        self.library_calls = []
        self.s = object()
    def connect(self):
        self.s = object()
    def close(self):
        self.s = None
    def library(self, mt):
        self.library_calls.append(mt)
        return self._data.get(mt, [])
    def playlist_tracks(self, item_id, provider="library", limit=None):
        # No default cap here: the cap must come from music.py, or the cap test proves nothing.
        self.track_calls.append(str(item_id))
        self.track_limits.append(limit)
        items = list(self._tracks.get(str(item_id), []))
        return items if limit is None else items[:limit]
    def play(self, q, media, option="replace"):
        self.played.append(media); return {"result": {}}


class FakeCtx(object):
    def __init__(self, ma, settings=None):
        self._ma = ma
        self.settings = settings or FakeSettings()
    def ma_factory(self):
        return self._ma


def smb(name, item_id):
    return {"name": name, "provider_mappings": [
        {"provider_domain": "filesystem_smb", "provider_instance": "filesystem_smb--kd66vco4",
         "available": True, "item_id": item_id}]}


def ytm_track(name, item_id):
    return {"name": name, "provider_mappings": [
        {"provider_domain": "ytmusic", "provider_instance": "ytmusic--x", "available": True, "item_id": item_id}]}


def curated(name, item_id):
    # Shape observed live (probe 2026-09-27): builtin mapping id = the playlist NAME, library id numeric.
    return {"name": name, "item_id": item_id, "uri": "library://playlist/" + item_id,
            "is_editable": True, "is_dynamic": False, "provider_mappings": [
        {"provider_domain": "builtin", "provider_instance": "builtin", "available": True, "item_id": name}]}


def auto(name, named_id, dynamic=False):
    # MA's automatic lists: builtin, non-editable (infinite_mix* are also dynamic).
    return {"name": name, "item_id": "9", "uri": "library://playlist/9",
            "is_editable": False, "is_dynamic": dynamic, "provider_mappings": [
        {"provider_domain": "builtin", "provider_instance": "builtin", "available": True, "item_id": named_id}]}


def run(ma, query, media_type="", settings=None, dry_run=False):
    p = {"query": query, "media_type": media_type, "_rid": "t"}
    if dry_run:
        p["dry_run"] = True
    return capability.run(music.MusicCapability(), FakeCtx(ma, settings), p, "t")


EIGHT = [smb("t%d" % i, "p/%d.flac" % i) for i in range(8)]


class CuratedPlaylistTest(unittest.TestCase):
    def test_curated_all_local_plays_track_list_not_playlist_uri(self):
        ma = FakeMA({"playlist": [curated("my music - costea (local)", "28")]}, {"28": EIGHT})
        r = run(ma, "my music - costea (local)", "playlist")
        self.assertTrue(r["ok"])
        self.assertEqual(len(ma.played), 1)
        self.assertIsInstance(ma.played[0], list)
        self.assertEqual(len(ma.played[0]), 8)
        self.assertEqual(ma.played[0][0], "filesystem_smb--kd66vco4://track/p/0.flac")
        md = r["metadata"]
        self.assertEqual(md["uri"], "library://playlist/28")          # string, for note_playback
        self.assertEqual(len(md["uris"]), 8)

    def test_mixed_plays_only_local_tracks_with_note(self):
        tracks = EIGHT[:6] + [ytm_track("y1", "a"), ytm_track("y2", "b")]
        ma = FakeMA({"playlist": [curated("mix", "5")]}, {"5": tracks})
        r = run(ma, "mix", "playlist")
        self.assertTrue(r["ok"])
        self.assertEqual(len(ma.played[0]), 6)
        self.assertIn("6 of 8 tracks", r["chat_text"])
        self.assertIn("2 aren't in your local library yet", r["chat_text"])
        self.assertIsNone(r["spoken_text"])

    def test_no_local_tracks_is_not_found_with_no_songs_line(self):
        ma = FakeMA({"playlist": [curated("yt only", "6")]}, {"6": [ytm_track("y", "a")]})
        r = run(ma, "yt only", "playlist")
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"]["code"], "not_found")
        self.assertIn("has no songs in the local library yet", r["spoken_text"])
        self.assertEqual(ma.played, [])

    def test_automatic_non_editable_playlists_are_never_curated(self):
        # Includes a name-like id, so the rule cannot be "mapping id looks like a name".
        for named in ("random_tracks", "recently_played", "Some Future Auto List"):
            ma = FakeMA({"playlist": [auto("Random Artist", named)]}, {"9": EIGHT})
            r = run(ma, "Random Artist", "playlist")
            self.assertFalse(r["ok"], named)
            self.assertEqual(ma.track_calls, [], named)

    def test_editable_but_dynamic_playlist_is_never_curated(self):
        pl = auto("Infinite Mix (library)", "infinite_mix", dynamic=True)
        pl["is_editable"] = True                      # a future MA marking a dynamic list editable
        ma = FakeMA({"playlist": [pl]}, {"9": EIGHT})
        r = run(ma, "Infinite Mix (library)", "playlist")
        self.assertFalse(r["ok"])
        self.assertEqual(ma.track_calls, [])

    def test_missing_is_editable_fails_closed(self):
        pl = curated("mix", "5")
        del pl["is_editable"]                         # e.g. a future MA renames the field
        ma = FakeMA({"playlist": [pl]}, {"5": EIGHT})
        r = run(ma, "mix", "playlist")
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"]["code"], "not_found")
        self.assertEqual(ma.track_calls, [])

    def test_missing_is_dynamic_fails_closed(self):
        pl = curated("mix", "5")
        del pl["is_dynamic"]                          # editable, but we cannot tell it is not dynamic
        ma = FakeMA({"playlist": [pl]}, {"5": EIGHT})
        r = run(ma, "mix", "playlist")
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"]["code"], "not_found")
        self.assertEqual(ma.track_calls, [])

    def test_m3u_playlist_unchanged(self):
        ma = FakeMA({"playlist": [smb("costea-playlist", "costea-playlist.m3u")]})
        r = run(ma, "costea-playlist", "playlist")
        self.assertTrue(r["ok"])
        self.assertEqual(ma.played, ["filesystem_smb--kd66vco4://playlist/costea-playlist.m3u"])
        self.assertNotIn("uris", r["metadata"])

    def test_tracks_fetched_only_for_top_curated_candidate(self):
        ma = FakeMA({"playlist": [curated("mix a", "1"), curated("mix ab", "2")]},
                    {"1": [ytm_track("y", "a")], "2": EIGHT})
        run(ma, "mix a", "playlist")
        self.assertEqual(ma.track_calls, ["1"])

    def test_track_list_capped(self):
        many = [smb("t%d" % i, "p/%d" % i) for i in range(music.PLAYLIST_TRACK_CAP + 50)]
        ma = FakeMA({"playlist": [curated("big", "3")]}, {"3": many})
        run(ma, "big", "playlist")
        self.assertEqual(ma.track_limits, [music.PLAYLIST_TRACK_CAP])
        self.assertEqual(len(ma.played[0]), music.PLAYLIST_TRACK_CAP)

    def test_curated_mapping_id_differing_from_library_id_fetches_by_library_id(self):
        # MA need not keep the builtin mapping id equal to the library id; the fetch uses provider
        # "library", so it must pass the library id.
        pl = curated("mix", "5")
        pl["provider_mappings"][0]["item_id"] = "77"
        ma = FakeMA({"playlist": [pl]}, {"5": EIGHT, "77": [ytm_track("wrong", "w")]})
        r = run(ma, "mix", "playlist")
        self.assertTrue(r["ok"])
        self.assertEqual(ma.track_calls, ["5"])
        self.assertEqual(len(ma.played[0]), 8)

    def test_artist_play_never_fetches_playlist_tracks(self):
        ma = FakeMA({"artist": [smb("Rammstein", "42")]})
        r = run(ma, "Rammstein", "artist")
        self.assertTrue(r["ok"])
        self.assertEqual(ma.track_calls, [])
        self.assertEqual(ma.played, ["filesystem_smb--kd66vco4://artist/42"])


if __name__ == "__main__":
    unittest.main()
