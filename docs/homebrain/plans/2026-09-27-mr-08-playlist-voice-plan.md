# MR-08 Play Curated Playlists by Voice — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** "Okay Nabu, play Costea mix" plays a curated Music Assistant playlist (or `.m3u`) on the ceiling, found by
name or by an exact alias, always from local files; dry-runs never speak.

**Architecture:** All changes are inside the host-side `mass-resolver` (Python 3.5). `MusicCapability.resolve`
gains an alias step and curated-MA-playlist acceptance (numeric `builtin` id → play its local-track URI list); the
existing resolution of artists/albums/tracks/`.m3u` is untouched. `core.dispatch` and the CLI stop speaking on
dry-runs. No HA script, automation, exposure or ChatGPT-tool change.

**Tech Stack:** Python 3.5-compatible stdlib, `unittest`, raw-socket MA WebSocket client (`maconn.py`).

**Spec:** `docs/homebrain/2026-09-27-mr-08-playlist-voice-design.md` (approved by the operator 2026-09-27;
reviewed by an independent agent and by peer session `dotfiles-61`). Read it before starting.

## Global Constraints

- Python **3.5** syntax only in resolver modules — no f-strings, no `_` numeric separators
  (`tests/test_py35_compat.py` parses every module and fails otherwise).
- All work in the worktree `D:\repos\dotfiles\.claude\worktrees\mr-playlist-voice`, branch
  `homebrain/mr-playlist-voice`; resolver code lives in `docs/homebrain/mass-resolver/`.
- Run tests from `docs/homebrain/mass-resolver/`: full suite `python -m unittest discover -s tests -t .`
  (baseline at plan time: **844 tests OK, 2 skipped**); one module `python -m unittest tests.test_playlist -v`.
- Success stays **silent** (`spoken_text=None`); CommandResult contract unchanged.
- `md["uri"]` is always a **string**; a curated playlist's track list goes in `md["uris"]`.
- New settings are read with `getattr(settings, "playlist_aliases", None) or {}` — existing fakes lack them.
- Commits: no AI attribution; code and docs in separate commits.
- **Live host (Task 1 read-only probe, Task 7 deploy) only with explicit operator approval at that step**; the
  operator runs the `sudo` restart. `main` is protected — everything lands via PR (BACKLOG §8).

## Review Focus

1. **"the …" titles must rank as today** — "the wall" must still pick the album "The Wall" over "Wall of Sound"
   (phrase resolved unstripped). Test in Task 4.
2. **An alias must never play something else** — a missing/renamed target or a no-local playlist returns
   `not_found`, never an artist and never a different playlist. Tests in Task 4.
3. **MA's automatic playlists must never be treated as curated** (named ids like `random_tracks`), including
   ones a future MA adds. Test in Task 3.
4. **A curated playlist must play only local tracks** even when all are local (no playlist-URI play). Test in Task 3.
5. **A dry-run must never speak or play**, on `/command` (params or settings flag) and on the CLI. Tests in Task 5.

---

### Task 1: Live read-only probe of the MA shapes (no code)

Confirms spec §8 assumptions before code depends on them. **Read-only; runs a script on the host over SSH using
the documented on-host token method.** CLAUDE.md allows SSH only on a specific ask: **before Step 2, ask the operator
for this read-only check and wait for a yes** — this plan is not that approval. `id_homebrain` has a passphrase and
must already be loaded in the ssh-agent (adopt `~/.ssh/agent.env`; never kill the agent), or `BatchMode` fails.

**Not checked here:** spec §8's "`player_queues/play_media` accepts a list of URIs" cannot be probed read-only (it
starts playback). The first live play in Task 7 Step 7 is that check, and it is a STOP condition there.

**Files:**
- Create (scratch, not committed): `C:\Users\CONSTA~1\AppData\Local\Temp\claude\D--repos-dotfiles\f665b45e-08ed-4da2-8ee3-0144e3f39ce4\scratchpad\mr08_probe.py`

**Interfaces:** Produces facts recorded in the task's commit message for Tasks 2–3: the curated playlist mapping
(`provider_domain`, `item_id`), whether `music/playlists/playlist_tracks` returns a list or `{"items": …}` and
whether it arrives as `partial` chunks, and a local track's mapping fields.

- [ ] **Step 1: Write the probe** (Python 3.5, runs on the host; never prints the token)

```python
# Runs ON the homebrain host. Read-only. Prints shapes needed by MR-08.
import json, os, sys
sys.path.insert(0, os.path.expanduser("~/mass-resolver"))
import maconn, config
here = os.path.expanduser("~/mass-resolver")
s = config.load_settings(here)
ma = maconn.MA(s.ma_host, s.ma_port, config.read_secret(here, ".ma_token"))
ma.connect()
pls = ma.library("playlist")
for p in pls:
    if p.get("name") in ("my music - costea (local)", "costea-playlist", "Random Artist (from library)"):
        print("PLAYLIST", json.dumps({"name": p.get("name"), "item_id": p.get("item_id"), "uri": p.get("uri"),
              "provider": p.get("provider"), "mappings": p.get("provider_mappings")})[:600])
r = ma.cmd("music/playlists/playlist_tracks", item_id="28", provider_instance_id_or_domain="library")
print("TRACKS raw keys:", sorted((r or {}).keys()), "partial:", (r or {}).get("partial"))
res = (r or {}).get("result")
items = res.get("items") if isinstance(res, dict) else (res or [])
print("TRACKS type:", type(res).__name__, "count:", len(items))
if items:
    print("TRACK0", json.dumps({"name": items[0].get("name"), "mappings": items[0].get("provider_mappings")})[:600])
ma.close()
```

- [ ] **Step 2: Run it on the host**

Run (Git Bash): `ssh -o BatchMode=yes costea@192.168.1.68 'python3 -' < <scratchpad>/mr08_probe.py`
Expected: `PLAYLIST` lines for the three playlists; `TRACKS type: list count: 8` (or `dict`); `partial: None`
(or `True`); `TRACK0` showing a `filesystem_smb` mapping with `provider_instance`, `item_id`, `available`.

- [ ] **Step 3: Record the facts and adapt if needed**

If the curated mapping is **not** `builtin` + numeric `item_id`, or tracks arrive as `partial` chunks, STOP and
report to the operator before Task 3 (the design depends on both). Otherwise record the observed values as an empty
commit so the evidence travels with the branch:

```bash
git commit --allow-empty -m "chore(mr-08): probe confirms MA playlist shapes

curated playlist 28 mapping: <provider_domain>/<item_id>; playlist_tracks returns <list|dict>, partial=<value>,
<N> tracks; local track mapping: filesystem_smb provider_instance=<value>, item_id=<value>, available=<value>"
```

---

### Task 2: `favorites.match_alias` (radio behaviour unchanged) + `playlist_aliases` setting + `MA.playlist_tracks`

**Files:**
- Modify: `docs/homebrain/mass-resolver/favorites.py:45-78`
- Modify: `docs/homebrain/mass-resolver/config.py:36` (add one line after `self.dry_run`)
- Modify: `docs/homebrain/mass-resolver/maconn.py:29-36` (add a method)
- Test: `docs/homebrain/mass-resolver/tests/test_favorites.py`, `tests/test_config.py`, `tests/test_maconn.py`

**Interfaces:**
- Produces: `favorites.match_alias(aliases, query, substring=False) -> (key, target) | None` (key in its original
  casing); `favorites.resolve_alias(radio_cfg, query) -> str` (unchanged behaviour);
  `Settings.playlist_aliases: dict` (default `{}`);
  `MA.playlist_tracks(item_id, provider="library", limit=500) -> list` of track dicts.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_favorites.py` (inside a new class):

```python
class MatchAliasTest(unittest.TestCase):
    A = {"Costea Mix": "my music - costea (local)", "costea mics": "my music - costea (local)"}

    def test_exact_hit_returns_original_key_and_target(self):
        self.assertEqual(favorites.match_alias(self.A, "costea mix"), ("Costea Mix", "my music - costea (local)"))

    def test_compacted_exact_hit(self):
        self.assertEqual(favorites.match_alias(self.A, "Costea-Mix")[0], "Costea Mix")

    def test_no_substring_by_default(self):
        self.assertIsNone(favorites.match_alias(self.A, "play costea mix loud"))

    def test_substring_mode_finds_key_inside_query(self):
        self.assertEqual(favorites.match_alias(self.A, "play costea mix loud", substring=True)[0], "Costea Mix")

    def test_empty_inputs(self):
        self.assertIsNone(favorites.match_alias({}, "costea mix"))
        self.assertIsNone(favorites.match_alias(self.A, ""))
```

Append to `tests/test_config.py` (inside the existing settings test class, next to the provider_preference tests):

```python
    def test_playlist_aliases_default_empty(self):
        self.assertEqual(config.Settings({}).playlist_aliases, {})

    def test_playlist_aliases_loaded(self):
        s = config.Settings({"playlist_aliases": {"costea mix": "my music - costea (local)"}})
        self.assertEqual(s.playlist_aliases, {"costea mix": "my music - costea (local)"})
```

Append to `tests/test_maconn.py`:

```python
class PlaylistTracksTest(unittest.TestCase):
    def _ma(self, reply):
        m = MA("h", 1, "t")                 # test_maconn imports `from maconn import MA, WS_CMD`
        m.calls = []
        def cmd(command, **a):
            m.calls.append((command, a)); return reply
        m.cmd = cmd
        return m

    def test_list_result(self):
        m = self._ma({"result": [{"name": "a"}, {"name": "b"}]})
        self.assertEqual([t["name"] for t in m.playlist_tracks(28)], ["a", "b"])
        self.assertEqual(m.calls[0], ("music/playlists/playlist_tracks",
                                      {"item_id": "28", "provider_instance_id_or_domain": "library"}))

    def test_items_dict_result_and_cap(self):
        m = self._ma({"result": {"items": [{"name": str(i)} for i in range(10)]}})
        self.assertEqual(len(m.playlist_tracks("28", limit=3)), 3)

    def test_no_reply_is_empty(self):
        self.assertEqual(self._ma(None).playlist_tracks(28), [])
```

(Check the imports at the top of each test file: `favorites`, `config`, `maconn` must be imported; add
`import favorites` / `import maconn` if missing.)

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m unittest tests.test_favorites tests.test_config tests.test_maconn -v`
Expected: FAIL — `AttributeError: module 'favorites' has no attribute 'match_alias'`, `'Settings' object has no
attribute 'playlist_aliases'`, `'MA' object has no attribute 'playlist_tracks'`.

- [ ] **Step 3: Implement** — replace `resolve_alias` in `favorites.py` (lines 45-78) with:

```python
def match_alias(aliases, query, substring=False):
    """Provider-neutral alias match -> (key, target) or None. `key` keeps its configured casing.

    Exact first (case-insensitive, then compacted so "Costea-Mix" == "costea mix"). With
    substring=True (radio only) an alias key is also looked for INSIDE the query, longest key first,
    because radio station arguments arrive noisy and over-long. Playlists use the exact form only:
    a music query spans the whole library and a short alias must not swallow an unrelated title."""
    q = (query or "").strip()
    if not q or not aliases:
        return None
    lowered = {}
    for k, v in aliases.items():
        lowered[k.lower()] = (k, v)
    ql = q.lower()
    if ql in lowered:                       # exact alias, the cheap and unambiguous case
        return lowered[ql]
    qc = compact(ql)
    # Longest key first so the most specific alias wins; then alphabetical, so equal-length keys
    # resolve the same way on every run rather than inheriting dict order.
    ordered = sorted(lowered.keys(), key=lambda x: (-len(x), x))
    if not substring:
        for k in ordered:
            if qc and compact(k) == qc:
                return lowered[k]
        return None
    for k in ordered:
        kc = compact(k)
        if len(kc) < _MIN_ALIAS_KEY:
            continue
        if k in ql or (kc and kc in qc):
            LOG.info("radio alias matched %r inside %r -> %r", k, q, lowered[k][1])
            return lowered[k]
    return None


def resolve_alias(radio_cfg, query):
    """Map a spoken/STT-mangled station name onto its canonical name via radio.json `aliases`
    (returns the query unchanged when there is no alias). Exposed so the MA/RadioBrowser search
    can use the SAME canonical name as the local favorites match -- otherwise an alias only ever
    helps stations that happen to be listed in radio.json. Substring matching, keys shorter than 4
    chars skipped (they would fire on ordinary words) -- see match_alias."""
    q = (query or "").strip()
    hit = match_alias(_alias_map(radio_cfg), q, substring=True)
    return hit[1] if hit else q
```

In `config.py`, after line 36 (`self.dry_run = …`) add:

```python
        # MR-08: spoken playlist nicknames -> exact playlist name (exact-match only; see music.py).
        self.playlist_aliases = cfg.get("playlist_aliases", {}) or {}
```

In `maconn.py`, after `library()` add:

```python
    def playlist_tracks(self, item_id, provider="library", limit=500):
        """Tracks of a library playlist (MR-08). Capped: a huge playlist must not make the
        synchronous tool path slow."""
        r = self.cmd("music/playlists/playlist_tracks", item_id=str(item_id),
                     provider_instance_id_or_domain=provider)
        res = (r or {}).get("result")
        items = res.get("items") if isinstance(res, dict) else (res or [])
        return list(items)[:limit]
```

- [ ] **Step 4: Run them to verify they pass, plus the radio suites (radio behaviour must be unchanged)**

Run: `python -m unittest tests.test_favorites tests.test_config tests.test_maconn tests.test_radio tests.test_radio_config -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add docs/homebrain/mass-resolver/favorites.py docs/homebrain/mass-resolver/config.py docs/homebrain/mass-resolver/maconn.py docs/homebrain/mass-resolver/tests/test_favorites.py docs/homebrain/mass-resolver/tests/test_config.py docs/homebrain/mass-resolver/tests/test_maconn.py
git commit -m "feat(resolver): provider-neutral alias matcher, playlist_aliases setting, MA.playlist_tracks"
```

---

### Task 3: Curated MA playlists resolve to their local-track list

**Files:**
- Modify: `docs/homebrain/mass-resolver/music.py:1-32` (helpers + `_resolve_type`), `:35-58` (`resolve` types loop)
- Create: `docs/homebrain/mass-resolver/tests/test_playlist.py`

**Interfaces:**
- Consumes: `MA.playlist_tracks(item_id, provider="library", limit=500)` (Task 2).
- Produces (used by Task 4): in `music.py` —
  `PLAYLIST_TRACK_CAP = 500`;
  `_resolve_type(ma, query, media_type, settings, rid, lib, exact=False) -> (hit_or_None, no_local_name_or_None)`;
  `_resolve_all(ma, query, types, settings, rid, lib) -> (hit_or_None, no_local_name_or_None)`;
  `_types(settings, first) -> list`. A curated hit is
  `{"uri": str, "uris": [str], "provider": "builtin", "candidate": str, "media_type": "playlist", "local": int, "total": int}`.

- [ ] **Step 1: Write the failing tests** — create `tests/test_playlist.py`:

```python
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
    return {"name": name, "item_id": item_id, "uri": "library://playlist/" + item_id, "provider_mappings": [
        {"provider_domain": "builtin", "provider_instance": "builtin", "available": True, "item_id": item_id}]}


def auto(name, named_id):
    return {"name": name, "item_id": "9", "uri": "library://playlist/9", "provider_mappings": [
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

    def test_automatic_named_id_playlists_are_never_curated(self):
        for named in ("random_tracks", "infinite_mix", "some_future_auto_list"):
            ma = FakeMA({"playlist": [auto("Random Artist", named)]}, {"9": EIGHT})
            r = run(ma, "Random Artist", "playlist")
            self.assertFalse(r["ok"], named)
            self.assertEqual(ma.track_calls, [], named)

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

    def test_artist_play_never_fetches_playlist_tracks(self):
        ma = FakeMA({"artist": [smb("Rammstein", "42")]})
        r = run(ma, "Rammstein", "artist")
        self.assertTrue(r["ok"])
        self.assertEqual(ma.track_calls, [])
        self.assertEqual(ma.played, ["filesystem_smb--kd66vco4://artist/42"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m unittest tests.test_playlist -v`
Expected: FAIL — curated tests fail (`REJECTED reason=no-preferred-mapping`, `ok` False / no list played);
`PLAYLIST_TRACK_CAP` AttributeError. (`test_m3u_playlist_unchanged` and `test_artist_play…` may already pass.)

- [ ] **Step 3: Implement** — replace `music.py` lines 1-58 (imports through the end of `resolve`) with:

```python
#!/usr/bin/env python3
# Music capability: resolve a query to a local (preferred-provider) item and play it. Python 3.5 safe.
import logging
import capability
import command_result as cr
import favorites
from match import match_rank, clean
from maconn import WS_CMD

LOG = logging.getLogger("resolver")

# A curated playlist is played as its local-track list; cap it so a huge playlist cannot stall
# the synchronous tool path (one play_media call, one playlist_tracks fetch).
PLAYLIST_TRACK_CAP = 500


def _local_mapping(it, settings):
    for m in it.get("provider_mappings") or []:
        if m.get("provider_domain") in settings.provider_preference and m.get("available"):
            return m
    return None


def _curated_mapping(it):
    """A playlist the operator made in Music Assistant: a `builtin` mapping with a NUMERIC id.
    MA's automatic lists (random_tracks, infinite_mix, ...) use named ids, so they -- and any a
    future MA version adds -- are never treated as curated."""
    for m in it.get("provider_mappings") or []:
        if m.get("provider_domain") == "builtin" and str(m.get("item_id") or "").isdigit():
            return m
    return None


def _library(ma, media_type, lib):
    """Each type's library is fetched once per resolve (lib is the per-request cache)."""
    if media_type not in lib:
        lib[media_type] = ma.library(media_type)
    return lib[media_type]


def _curated_tracks(ma, it, settings):
    """(local track uris in playlist order, total track count). Local = an available
    preferred-provider mapping; the list is always used, even when every track is local, so MA
    never picks a non-local source for a library track (spec 3.1-4)."""
    tracks = ma.playlist_tracks(it.get("item_id"), limit=PLAYLIST_TRACK_CAP)
    uris = []
    for t in tracks:
        m = _local_mapping(t, settings)
        if m:
            uris.append("%s://track/%s" % (m.get("provider_instance"), m.get("item_id")))
    return uris, len(tracks)


def _resolve_type(ma, query, media_type, settings, rid, lib, exact=False):
    """-> (hit or None, name of a curated playlist rejected for having no local tracks, or None).
    exact=True accepts only match_rank 0 (alias targets must never fuzzy-match)."""
    ranked = []
    for it in _library(ma, media_type, lib):
        r = match_rank(query, it.get("name"))
        if r is not None and (r == 0 or not exact):
            ranked.append((r, it))
    ranked.sort(key=lambda t: t[0])
    curated_tried = False
    no_local = None
    for _, it in ranked:
        name = it.get("name")
        local = _local_mapping(it, settings)
        if local:
            uri = "%s://%s/%s" % (local.get("provider_instance"), media_type, local.get("item_id"))
            LOG.info("req=%s query=%r media_type=%s candidate=%r provider=%s uri=%s decision=ACCEPTED",
                     rid, query, media_type, name, local.get("provider_domain"), uri)
            return {"uri": uri, "provider": local.get("provider_domain"), "candidate": name,
                    "media_type": media_type}, None
        if media_type == "playlist" and not curated_tried and _curated_mapping(it):
            curated_tried = True                # tracks are fetched for the top curated candidate only
            uris, total = _curated_tracks(ma, it, settings)
            if uris:
                puri = it.get("uri") or ("library://playlist/%s" % it.get("item_id"))
                LOG.info("req=%s query=%r media_type=playlist candidate=%r provider=builtin uri=%s "
                         "local=%d/%d decision=ACCEPTED", rid, query, name, puri, len(uris), total)
                return {"uri": puri, "uris": uris, "provider": "builtin", "candidate": name,
                        "media_type": "playlist", "local": len(uris), "total": total}, None
            no_local = name
            LOG.info("req=%s query=%r media_type=playlist candidate=%r local=0/%d decision=REJECTED "
                     "reason=no-local-tracks", rid, query, name, total)
            continue
        LOG.info("req=%s query=%r media_type=%s candidate=%r decision=REJECTED reason=no-preferred-mapping",
                 rid, query, media_type, name)
    return None, no_local


def _resolve_all(ma, query, types, settings, rid, lib):
    no_local = None
    for t in types:
        hit, nl = _resolve_type(ma, query, t, settings, rid, lib)
        if hit:
            return hit, None
        no_local = no_local or nl
    return None, no_local


def _types(settings, first):
    order = list(settings.type_order)
    if first in WS_CMD:
        return [first] + [t for t in order if t != first]
    return order


class MusicCapability(capability.Capability):
    name = "music"

    def resolve(self, ctx, params):
        ma = ctx.ma_factory()
        if getattr(ma, "s", None) is None:
            ma.connect()
        try:
            q = params.get("query")
            mt = params.get("media_type") or ""
            hit, nl = _resolve_all(ma, q, _types(ctx.settings, mt), ctx.settings, params.get("_rid", ""), {})
            dry_run = params.get("dry_run") or ctx.settings.dry_run
            return {"ma": ma, "query": q, "hit": hit, "no_local": nl, "alias": None, "note": None,
                    "dry_run": dry_run}
        except Exception:
            ma.close()
            raise
```

Then replace `validate` and `execute` (old lines 60-96) with:

```python
    def validate(self, ctx, resolved):
        if resolved.get("hit"):
            return None
        resolved["ma"].close()
        if resolved.get("no_local"):
            name = resolved.get("alias") or resolved["no_local"]
            msg = name + " has no songs in the local library yet."
            return {"code": "not_found", "reason": "no local tracks", "chat_text": msg, "spoken_text": msg,
                    "metadata": {"query": resolved.get("query")}}
        q = resolved.get("alias") or resolved.get("query") or "that"
        return {"code": "not_found", "reason": "no local match",
                "chat_text": q + " isn't in your local library yet.",
                "spoken_text": "Sorry, I couldn't find " + q + " in the local library.",
                "metadata": {"query": q}}

    def execute(self, ctx, resolved, rid):
        ma = resolved["ma"]
        hit = resolved["hit"]
        display = resolved.get("alias") or hit["candidate"]
        try:
            md = {"uri": hit["uri"], "provider": hit["provider"],
                  "candidate": hit["candidate"], "media_type": hit["media_type"]}
            if "uris" in hit:
                md["uris"] = hit["uris"]; md["local"] = hit["local"]; md["total"] = hit["total"]
            if resolved["dry_run"]:
                md["played"] = False
                LOG.info("[DRY-RUN] req=%s WOULD PLAY %s (provider=%s)", rid, hit["uri"], hit["provider"])
                return cr.ok(self.name, rid, "Would play " + display + ".", spoken_text=None, metadata=md)
            pr = ma.play(ctx.settings.queue_id, hit.get("uris") or hit["uri"])
            if pr and "error_code" in pr:
                md["played"] = False
                LOG.error("req=%s PLAY FAILED for %s code=%s details=%r (MA refused the play; "
                          "resolution was fine)", rid, hit["uri"], pr.get("error_code"),
                          pr.get("details") or pr.get("error") or pr.get("message"))
                return cr.err(self.name, rid, "play_failed", "play failed",
                              "I found " + display + ", but couldn't start it.",
                              spoken_text="I found " + display + ", but couldn't start playback.",
                              metadata=md)
            md["played"] = True
            LOG.info("req=%s PLAYING %s (provider=%s)", rid, hit["uri"], hit["provider"])
            text = "Playing " + display
            if "uris" in hit and hit["local"] < hit["total"]:
                text += " \u2014 %d of %d tracks; %d aren't in your local library yet" % (
                    hit["local"], hit["total"], hit["total"] - hit["local"])
            if resolved.get("note") == "shuffle":
                text += " (shuffle isn't supported yet)"
            return cr.ok(self.name, rid, text + ".", spoken_text=None, metadata=md)
        finally:
            ma.close()
```

(Leave `resolve_music` at the bottom unchanged.)

- [ ] **Step 4: Run the new tests and the existing music/core suites**

Run: `python -m unittest tests.test_playlist tests.test_music tests.test_core -v`
Expected: all PASS (existing music/core behaviour unchanged).

- [ ] **Step 5: Commit**

```bash
git add docs/homebrain/mass-resolver/music.py docs/homebrain/mass-resolver/tests/test_playlist.py
git commit -m "feat(resolver): play curated Music Assistant playlists as their local-track list"
```

---

### Task 4: Aliases, trailing "playlist", shuffle-word tolerance

**Files:**
- Modify: `docs/homebrain/mass-resolver/music.py` — add `_strip_edges` and `_lookup` above `class MusicCapability`,
  and replace the body of `resolve` (from Task 3).
- Test: `docs/homebrain/mass-resolver/tests/test_playlist.py` (append a class)

**Interfaces:**
- Consumes: `favorites.match_alias` (Task 2); `_resolve_type`, `_resolve_all`, `_types` (Task 3).
- Produces: `_strip_edges(phrase) -> (stripped_clean_str, had_playlist_suffix_bool)`;
  `_lookup(ma, phrase, media_type, settings, rid, lib) -> (hit, no_local_name, alias_key_or_None)`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_playlist.py` (before `if __name__`):

```python
def with_aliases(aliases):
    s = FakeSettings(); s.playlist_aliases = aliases; return s


ALIASES = {"costea mix": "my music - costea (local)", "chill": "chill set"}


class AliasAndPhraseTest(unittest.TestCase):
    def lib(self):
        return {"artist": [smb("Costea Mix", "a1")],
                "playlist": [curated("my music - costea (local)", "28"), smb("costea-playlist", "c.m3u")]}

    def test_alias_forces_playlist_and_beats_same_named_artist(self):
        ma = FakeMA(self.lib(), {"28": EIGHT})
        r = run(ma, "Costea mix", settings=with_aliases(ALIASES))
        self.assertTrue(r["ok"])
        self.assertEqual(r["metadata"]["uri"], "library://playlist/28")
        self.assertEqual(r["chat_text"], "Playing costea mix.")

    def test_alias_to_missing_target_is_not_found_and_never_an_artist(self):
        lib = self.lib(); lib["playlist"] = [smb("costea-playlist", "c.m3u")]   # target renamed away
        # An artist named exactly like the target, and one named like the phrase ("Costea Mix"):
        # neither may play, whichever way a broken alias branch falls through.
        lib["artist"] = [smb("Costea Mix", "a1"), smb("my music - costea (local)", "a2")]
        ma = FakeMA(lib)
        r = run(ma, "costea mix", settings=with_aliases(ALIASES))
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"]["code"], "not_found")
        self.assertEqual(ma.played, [])

    def test_alias_to_no_local_playlist_is_not_found(self):
        ma = FakeMA(self.lib(), {"28": [ytm_track("y", "a")]})
        r = run(ma, "costea mix", settings=with_aliases(ALIASES))
        self.assertFalse(r["ok"])
        self.assertIn("costea mix has no songs", r["spoken_text"])
        self.assertEqual(ma.played, [])

    def test_alias_target_never_fuzzy_matches_another_playlist(self):
        lib = {"playlist": [curated("my music - costea (local) old", "27")]}
        ma = FakeMA(lib, {"27": EIGHT})
        r = run(ma, "costea mix", settings=with_aliases(ALIASES))
        self.assertFalse(r["ok"])
        self.assertEqual(ma.track_calls, [])

    def test_short_alias_does_not_hijack_longer_query(self):
        ma = FakeMA({"album": [smb("Chill Out", "al1")], "playlist": [curated("chill set", "4")]}, {"4": EIGHT})
        r = run(ma, "chill out", settings=with_aliases(ALIASES))
        self.assertTrue(r["ok"])
        self.assertEqual(r["metadata"]["media_type"], "album")

    def test_the_prefix_does_not_change_todays_ranking(self):
        ma = FakeMA({"album": [smb("Wall of Sound", "w1"), smb("The Wall", "w2")]})
        r = run(ma, "the wall", "album")
        self.assertTrue(r["ok"])
        self.assertEqual(r["metadata"]["candidate"], "The Wall")

    def test_trailing_playlist_word_is_stripped_and_playlist_tried_first(self):
        ma = FakeMA({"artist": [smb("costea-playlist band", "b1")],
                     "playlist": [smb("costea-playlist", "c.m3u")]})
        r = run(ma, "costea-playlist playlist")
        self.assertTrue(r["ok"])
        self.assertEqual(r["metadata"]["media_type"], "playlist")

    def test_only_the_word_playlist_is_no_match(self):
        ma = FakeMA(self.lib(), {"28": EIGHT})
        r = run(ma, "playlist")
        self.assertFalse(r["ok"])
        self.assertEqual(ma.played, [])

    def test_apostrophes_and_punctuation_match_alias(self):
        ma = FakeMA(self.lib(), {"28": EIGHT})
        r = run(ma, "Costea's-mix", settings=with_aliases({"costeas mix": "my music - costea (local)"}))
        self.assertTrue(r["ok"])

    def test_shuffle_word_is_tolerated_and_noted(self):
        ma = FakeMA(self.lib(), {"28": EIGHT})
        r = run(ma, "shuffle Costea mix", settings=with_aliases(ALIASES))
        self.assertTrue(r["ok"])
        self.assertIn("(shuffle isn't supported yet)", r["chat_text"])

    def test_title_starting_with_shuffle_still_resolves_unstripped(self):
        # Unstripped first: "shuffle the deck" must play the track of that name, not "The Deck"
        # (which a strip-first order would pick) and without the shuffle note.
        ma = FakeMA({"track": [smb("The Deck", "d1"), smb("Shuffle the Deck", "s1")]})
        r = run(ma, "shuffle the deck")
        self.assertTrue(r["ok"])
        self.assertEqual(r["metadata"]["candidate"], "Shuffle the Deck")
        self.assertNotIn("shuffle isn't supported", r["chat_text"])

    def test_library_fetched_once_per_type_across_shuffle_retry(self):
        # "shuffle nothing here" misses, then is retried stripped: without the per-resolve cache
        # every type's library would be fetched twice.
        ma = FakeMA(self.lib(), {"28": EIGHT})
        run(ma, "shuffle nothing here")
        self.assertEqual(len(ma.library_calls), len(set(ma.library_calls)))
        self.assertEqual(len(ma.library_calls), 4)

    def test_dry_run_plays_nothing(self):
        ma = FakeMA(self.lib(), {"28": EIGHT})
        r = run(ma, "costea mix", settings=with_aliases(ALIASES), dry_run=True)
        self.assertTrue(r["ok"])
        self.assertEqual(ma.played, [])
        self.assertIsNone(r["spoken_text"])
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m unittest tests.test_playlist.AliasAndPhraseTest -v`
Expected: FAIL — alias tests fail (alias not applied, "Costea Mix" artist plays), trailing-playlist and shuffle
tests fail.

- [ ] **Step 3: Implement** — in `music.py`, add above `class MusicCapability`:

```python
def _strip_edges(phrase):
    """(stripped, had_playlist_suffix). Leading 'the ' and trailing ' playlist' removed, whole words,
    on the clean() form. Used ONLY for the alias lookup and when the phrase ends in 'playlist' --
    ordinary queries resolve unstripped so today's ranking is unchanged ("the wall")."""
    c = clean(phrase)
    had = False
    if c == "playlist" or c.endswith(" playlist"):
        c = c[:-len("playlist")].strip()
        had = True
    if c.startswith("the "):
        c = c[len("the "):].strip()
    return c, had


def _lookup(ma, phrase, media_type, settings, rid, lib):
    """One attempt for a phrase -> (hit, no_local_name, alias_key or None).
    1) exact alias -> playlist only, exact target; 2) trailing 'playlist' -> stripped form, playlist
    first; 3) otherwise today's resolution of the unstripped phrase."""
    stripped, had_playlist = _strip_edges(phrase)
    aliases = getattr(settings, "playlist_aliases", None) or {}
    a = favorites.match_alias(aliases, stripped) if (aliases and stripped) else None
    if a:
        key, target = a
        hit, nl = _resolve_type(ma, target, "playlist", settings, rid, lib, exact=True)
        if hit or nl:
            LOG.info("req=%s alias=%r -> %r", rid, key, target)
        else:
            LOG.info("req=%s alias=%r target=%r decision=REJECTED reason=alias-target-missing", rid, key, target)
        return hit, nl, key
    if had_playlist:
        if not stripped:
            return None, None, None
        hit, nl = _resolve_all(ma, stripped, _types(settings, "playlist"), settings, rid, lib)
        return hit, nl, None
    hit, nl = _resolve_all(ma, phrase, _types(settings, media_type), settings, rid, lib)
    return hit, nl, None
```

Replace the `try:` body of `resolve` with:

```python
        try:
            q = params.get("query") or ""
            mt = params.get("media_type") or ""
            rid = params.get("_rid", "")
            lib = {}
            note = None
            hit, nl, alias = _lookup(ma, q, mt, ctx.settings, rid, lib)
            if not hit and not nl and alias is None:
                c = clean(q)
                if c.startswith("shuffle "):        # shuffle is MR-08b; tolerate the word meanwhile
                    hit, nl, alias = _lookup(ma, c[len("shuffle "):], mt, ctx.settings, rid, lib)
                    if hit:
                        note = "shuffle"
            dry_run = params.get("dry_run") or ctx.settings.dry_run
            return {"ma": ma, "query": q, "hit": hit, "no_local": nl, "alias": alias, "note": note,
                    "dry_run": dry_run}
```

- [ ] **Step 4: Run the whole playlist module plus music/core**

Run: `python -m unittest tests.test_playlist tests.test_music tests.test_core -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add docs/homebrain/mass-resolver/music.py docs/homebrain/mass-resolver/tests/test_playlist.py
git commit -m "feat(resolver): exact playlist aliases, trailing 'playlist', tolerate 'shuffle' until MR-08b"
```

---

### Task 5: Dry-runs never speak (`/command` and CLI)

**Files:**
- Modify: `docs/homebrain/mass-resolver/core.py:98-105`
- Modify: `docs/homebrain/mass-resolver/resolver.py:183-188` (+ a helper above `main`)
- Test: `docs/homebrain/mass-resolver/tests/test_core.py`, `tests/test_resolver.py`

**Interfaces:**
- Produces: `resolver._should_announce(res, settings, dry_run) -> bool`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_core.py` (new class, before `if __name__`):

```python
class DryRunSilenceTest(unittest.TestCase):
    def test_music_not_found_dry_run_param_is_silent(self):
        ma = FakeMA(data={"artist": [], "album": [], "track": [], "playlist": []})
        spk = FakeSpeaker()
        r = core.dispatch(FakeCtx(ma, speaker=spk), "music", {"query": "Nonexistent", "dry_run": True})
        self.assertFalse(r["ok"])
        self.assertEqual(spk.said, [])

    def test_music_not_found_settings_dry_run_is_silent(self):
        ma = FakeMA(data={"artist": [], "album": [], "track": [], "playlist": []})
        spk = FakeSpeaker()
        s = FakeSettings(); s.dry_run = True
        r = core.dispatch(FakeCtx(ma, speaker=spk, settings=s), "music", {"query": "Nonexistent"})
        self.assertFalse(r["ok"])
        self.assertEqual(spk.said, [])

    def test_radio_find_dry_run_is_silent(self):          # cross-capability effect, intended (spec 3.4)
        ma = FakeMA(search=[rb_item("u%d" % i, "Jazz %d" % i) for i in range(4)])
        spk = FakeSpeaker()
        r = core.dispatch(FakeCtx(ma, speaker=spk), "radio", {"mode": "find", "genre": "jazz", "dry_run": True})
        self.assertTrue(r["ok"])
        self.assertEqual(spk.said, [])

    def test_not_found_without_dry_run_still_speaks(self):
        ma = FakeMA(data={"artist": [], "album": [], "track": [], "playlist": []})
        spk = FakeSpeaker()
        core.dispatch(FakeCtx(ma, speaker=spk), "music", {"query": "Nonexistent"})
        self.assertEqual(len(spk.said), 1)
```

Append to `tests/test_resolver.py` (new class):

```python
class ShouldAnnounceTest(unittest.TestCase):
    class S(object):
        announce_failures = True

    def test_failure_announces(self):
        self.assertTrue(resolver._should_announce({"ok": False, "spoken": "x"}, self.S(), False))

    def test_dry_run_never_announces(self):
        self.assertFalse(resolver._should_announce({"ok": False, "spoken": "x"}, self.S(), True))

    def test_success_or_no_text_or_disabled_never_announces(self):
        self.assertFalse(resolver._should_announce({"ok": True, "spoken": "x"}, self.S(), False))
        self.assertFalse(resolver._should_announce({"ok": False, "spoken": None}, self.S(), False))
        s = self.S(); s.announce_failures = False
        self.assertFalse(resolver._should_announce({"ok": False, "spoken": "x"}, s, False))
```

(`tests/test_resolver.py` must import `resolver`; add `import resolver` if missing.)

- [ ] **Step 2: Run to verify they fail**

Run: `python -m unittest tests.test_core.DryRunSilenceTest tests.test_resolver.ShouldAnnounceTest -v`
Expected: FAIL — dry-run tests see one spoken line; `resolver` has no `_should_announce`.

- [ ] **Step 3: Implement** — in `core.py`, replace lines 98-105 with:

```python
    # Single TTS owner: speak via Speaker when spoken_text is present and conditions met.
    # Exception: during a satellite turn the pipeline speaks the reply, so stand down (no double-speak).
    # A dry-run never speaks -- request flag or the settings-wide flag (MR-08 spec 3.4).
    spk = result.get("spoken_text")
    dry = bool((params or {}).get("dry_run")) or bool(getattr(ctx.settings, "dry_run", False))
    if spk and ctx.speaker is not None and not dry:
        if _satellite_turn_in_flight(ctx):
            LOG.info("req=%s ANNOUNCE suppressed: satellite turn in flight; the pipeline speaks the reply", rid)
        elif result.get("ok") or ctx.settings.announce_failures:
            ctx.speaker.speak(spk)
    elif spk and dry:
        LOG.info("req=%s ANNOUNCE suppressed: dry-run", rid)
```

In `resolver.py`, add above `def main():`

```python
def _should_announce(res, settings, dry_run):
    """One-shot CLI failure announce. Never on a dry-run (MR-08 spec 3.4)."""
    return (not dry_run) and (not res.get("ok")) and bool(res.get("spoken")) and bool(settings.announce_failures)
```

and replace line 184 (`if (not res.get("ok")) and res.get("spoken") and ctx.settings.announce_failures:`) with:

```python
    if _should_announce(res, ctx.settings, a.dry_run or ctx.settings.dry_run):
```

- [ ] **Step 4: Run tests**

Run: `python -m unittest tests.test_core tests.test_resolver tests.test_radio -v`
Expected: all PASS. If an existing test asserted that a dry-run speaks, it encoded the bug this task fixes —
report it in the task summary with the test name rather than silently changing it.

- [ ] **Step 5: Commit**

```bash
git add docs/homebrain/mass-resolver/core.py docs/homebrain/mass-resolver/resolver.py docs/homebrain/mass-resolver/tests/test_core.py docs/homebrain/mass-resolver/tests/test_resolver.py
git commit -m "fix(resolver): dry-runs never speak on /command or the CLI"
```

---

### Task 6: Integration through `core.dispatch`, full suite, Python 3.5 check, mutation check

**Files:**
- Test: `docs/homebrain/mass-resolver/tests/test_playlist.py` (append a class)

- [ ] **Step 1: Write the integration test** — append to `tests/test_playlist.py`:

```python
import core


class DispatchIntegrationTest(unittest.TestCase):
    class Interaction(object):
        def __init__(self):
            self.noted = []
        def note_playback(self, ctx, zone, uri):
            self.noted.append((zone, uri))

    class Speaker(object):
        def __init__(self):
            self.said = []
        def speak(self, t):
            self.said.append(t)

    def test_curated_play_sets_playback_flag_with_string_uri(self):
        ma = FakeMA({"playlist": [curated("my music - costea (local)", "28")]}, {"28": EIGHT})
        s = FakeSettings(); s.ceiling_entity = "media_player.ceiling_speakers"; s.announce_failures = True
        s.playlist_aliases = ALIASES
        ctx = FakeCtx(ma, s); ctx.speaker = self.Speaker(); ctx.radio_cfg = {}; ctx.news_cfg = {}
        fake = self.Interaction()
        saved = core.CAPS.get("interaction")
        core.CAPS["interaction"] = fake
        try:
            r = core.dispatch(ctx, "music", {"query": "costea mix"})
        finally:
            if saved is None:
                core.CAPS.pop("interaction", None)
            else:
                core.CAPS["interaction"] = saved
        self.assertTrue(r["ok"])
        self.assertEqual(fake.noted, [("media_player.ceiling_speakers", "library://playlist/28")])
        self.assertEqual(ctx.speaker.said, [])
```

(If `core.dispatch` needs further ctx attributes, copy them from `tests/test_core.py::FakeCtx`.)

- [ ] **Step 2: Run it** — `python -m unittest tests.test_playlist.DispatchIntegrationTest -v` → PASS.

- [ ] **Step 3: Full suite + Python 3.5 syntax sweep**

Run: `python -m unittest discover -s tests -t .`
Expected: `OK` with 844 + the new tests (≈ 880), 2 skipped, including `test_py35_compat`.

- [ ] **Step 4: Mutation check** — one at a time, make the change, run the named module, confirm ≥1 FAIL, then
revert with `git checkout -- <file>`:

| Mutation (in `music.py` unless noted) | Run | Must fail |
|---|---|---|
| `_curated_mapping`: drop `and str(...).isdigit()` | `tests.test_playlist` | `test_automatic_named_id_playlists_are_never_curated` |
| `_curated_tracks`: append every track's uri, local or not | `tests.test_playlist` | `test_mixed_plays_only_local_tracks_with_note` |
| `_lookup` alias branch: call `_resolve_all(ma, target, _types(settings, "playlist"), ...)` instead of `_resolve_type(... exact=True)` | `tests.test_playlist` | `test_alias_to_missing_target_is_not_found_and_never_an_artist` (artist named like the target) |
| `_lookup` alias branch: on a miss, fall through to resolving the phrase instead of `return hit, nl, key` | `tests.test_playlist` | `test_alias_to_missing_target_is_not_found_and_never_an_artist` ("Costea Mix" artist) |
| `_resolve_type`: ignore `exact` | `tests.test_playlist` | `test_alias_target_never_fuzzy_matches_another_playlist` |
| `_curated_tracks`: drop `limit=PLAYLIST_TRACK_CAP` | `tests.test_playlist` | `test_track_list_capped` |
| `resolve`: try the `shuffle `-stripped phrase first | `tests.test_playlist` | `test_title_starting_with_shuffle_still_resolves_unstripped` |
| `core.py`: remove `and not dry` | `tests.test_core` | `test_music_not_found_dry_run_param_is_silent` |

Record the table's outcome (all eight caught) in the commit message. A mutation that survives means its test
does not pin the behaviour — fix the test, not the table.

- [ ] **Step 5: Commit**

```bash
git add docs/homebrain/mass-resolver/tests/test_playlist.py
git commit -m "test(resolver): MR-08 dispatch integration; full suite green; mutation check 8/8 caught"
```

- [ ] **Step 6: Whole-branch review** — request a fresh code review of `main..HEAD` (resolver code + tests) before
any deploy; fix findings with the same TDD loop.

---

### Task 7: Deploy (operator-gated — stop and ask before Step 1)

Every step from Step 2 touches the live host. Ask the operator for explicit approval to start; the operator performs
the restart. `main` is protected (BACKLOG §8): every change below lands through a PR. `gh pr create` fails on this
machine (gh uses the personal token) — push the branch and open the PR from the browser URL git prints.
Replace `<ts>` with the timestamp printed in Step 2.

- [ ] **Step 1: Claim the live gate in the §10 register** — per BACKLOG §10 ("record the track ID + branch here in
the claiming PR"). Edit the `host-live / HA-live / exposure` row of `docs/homebrain/BACKLOG.md` §10: Holder
`MR-08 (homebrain/mr-playlist-voice)`, Status `CLAIMED <date> for the MR-08 resolver deploy`. BACKLOG is CRLF — match
its line endings and check `git diff --numstat` shows only the lines you meant. Commit
(`docs(homebrain): claim the live gate for MR-08`), push, open the PR, and **wait until it is merged** before Step 2.
If the row is not FREE, stop — another track holds the gate. Do **not** touch `CHANGELOG.md` here (§9: one writer,
entry added at merge).

- [ ] **Step 2: Back up the host files, including the tests**

```bash
ssh costea@192.168.1.68 'cd ~/mass-resolver && ts=$(date +%Y%m%d-%H%M%S) && mkdir -p .bak/$ts && cp music.py maconn.py favorites.py config.py core.py resolver.py config.json .bak/$ts/ && cp -r tests .bak/$ts/tests && echo $ts'
```

Also record the current announce count for Step 6: `ssh costea@192.168.1.68 'grep -c "ANNOUNCE via" ~/mass-resolver/resolver.log'`.

- [ ] **Step 3: Copy code and tests; run the suite on the host's Python 3.5.2 before the restart**

```bash
cd docs/homebrain/mass-resolver
scp music.py maconn.py favorites.py config.py core.py resolver.py costea@192.168.1.68:mass-resolver/
scp -r tests costea@192.168.1.68:mass-resolver/
ssh costea@192.168.1.68 'cd ~/mass-resolver && python3 --version && python3 -m unittest discover -s tests -t . 2>&1 | tail -3'
```

Expected: `Python 3.5.2`, then `OK` (compare the count with the last deploy's 487 host tests plus the new ones; host
skips may differ from Windows). `test_py35_compat` only parses syntax — this run is the real 3.5 check. **Any failure:
STOP**, restore from `.bak/<ts>` (rollback below) — the service is still running the old code, so nothing is live yet.

- [ ] **Step 4: Merge the alias config by value, not by key**

Compare the host `config.json` with the repo's by **value** (the repo mirror must not drift):

```bash
scp costea@192.168.1.68:mass-resolver/config.json "$SCRATCH/host_config.json"   # $SCRATCH = this session's scratchpad
python -c "import json,sys; h=json.load(open(sys.argv[1])); r=json.load(open('config.json')); print('differ:', sorted(k for k in set(h)|set(r) if h.get(k)!=r.get(k)))" "$SCRATCH/host_config.json"
```

Expected: `differ: []` (or only keys you can explain). An unexplained difference: STOP and ask the operator which
side is right. (`config.json` holds no secrets — tokens live in dot-files — but print key names only, as above.)
Then add **only** the alias key on the host, ASCII-safe (non-interactive ssh on 16.04 may run in an ASCII locale):

```bash
ssh costea@192.168.1.68 'cd ~/mass-resolver && python3 - <<EOF
import json
c = json.load(open("config.json"))
c["playlist_aliases"] = {"costea mix": "my music - costea (local)", "costea mics": "my music - costea (local)"}
open("config.json", "w").write(json.dumps(c, indent=2, ensure_ascii=True) + "\n")
print("aliases:", c["playlist_aliases"])
EOF'
```

Mirror the same key into the repo `config.json` and run `python -m unittest tests.test_config -v`
(`ShippedAnnounceConfigTest` asserts against the repo file and must stay green), then commit separately
(`chore(resolver): MR-08 playlist alias config`).

- [ ] **Step 5: Operator restarts the service** — ask them to run:
`! ssh -t costea@192.168.1.68 'sudo systemctl restart mass-resolver'`
then confirm it is up: `ssh costea@192.168.1.68 'tail -n 5 ~/mass-resolver/resolver.log'` shows
`SERVICE: connected`, and the runbook health check (`runbooks/quick-connect-and-health-check.md`) gives
`good_key=200` / `no_key=401`.

- [ ] **Step 6: Dry-runs on both paths (only now, after the dry-run fix is live)**

CLI (legacy `resolve_music`):

```bash
ssh costea@192.168.1.68 'cd ~/mass-resolver && for q in "costea mix" "my music - costea (local)" "costea-playlist playlist" "no such thing xyz"; do python3 resolver.py --dry-run --query "$q" | tail -1; done'
```

Expected JSON: the first two `"ok": true` with `"local": 8, "total": 8` and `"played": false`; the third
`"ok": true` with the `.m3u` URI; the last `"ok": false`.

`/command` (the path that spoke on 2026-09-27; secret read on the host, never printed):

```bash
ssh costea@192.168.1.68 'SEK=$(cat ~/mass-resolver/.http_secret); curl -s -m20 -H "X-Resolver-Key: $SEK" -H "Content-Type: application/json" -d "{\"intent\":\"music\",\"params\":{\"query\":\"no such thing xyz\",\"dry_run\":true}}" http://192.168.122.1:8770/command; echo; grep -c "ANNOUNCE via" ~/mass-resolver/resolver.log'
```

Expected: a CommandResult with `"ok": false`, `not_found`; the log shows `ANNOUNCE suppressed: dry-run`; and the
`ANNOUNCE via` count **equals** the Step 2 value. A higher count: STOP and roll back — the fix is not live.

- [ ] **Step 7: Live test with the operator present**

1. Operator: "Okay Nabu, play Costea mix" → log shows `alias='costea mix'` and `PLAYING library://playlist/28`;
   MA queue holds 8 local items (MA UI, or a read-only queue query); operator hears it. **This is also the first
   test that `play_media` accepts a URI list** (spec §8, not probeable in Task 1). If MA refuses it (the log shows
   `PLAY FAILED`, Nabu says "couldn't start playback"): STOP, roll back, and report — the design needs a different
   play call.
2. Mid-playlist, operator asks Nabu any question → afterwards check the MA queue: **still 8 items** (clears spec
   §6's concern) or **only the current track** (confirms it; MR-08c stays widened). Record which.

- [ ] **Step 8: Docs, release the gate, merge** — in the track's merge PR: the `CHANGELOG.md` entry (§9: added at
merge — what shipped, the dry-run fix, host and local test counts, the Step 7.2 result); `ONBOARDING.md` current
state; `assistant-capabilities.md` (playlists by name/alias; shuffle not yet); BACKLOG `MR-08` → done and, per Step
7.2, confirm or narrow `MR-08c`; and the §10 register row released (Holder *(none)*, Status `FREE — released
<date>` with the host test count and the rollback path `.bak/<ts>`). Docs in a commit separate from code. Push, open
the PR from the browser URL; after merge, remove the worktree.

**Rollback (any step after 3):** `ssh costea@192.168.1.68 'cd ~/mass-resolver && cp .bak/<ts>/*.py .bak/<ts>/config.json . && rm -rf tests && cp -r .bak/<ts>/tests tests'`
then the operator restarts again (skip the restart if Step 5 has not happened yet). Aliases only: set
`"playlist_aliases": {}` in the host `config.json` and restart. Release the §10 row as `FREE — rolled back` via PR.
