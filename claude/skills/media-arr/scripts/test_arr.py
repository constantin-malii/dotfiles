"""Stub test for arr.py `movies` filter + UTF-8 output. Replaces arr.get with fake data (no network)."""
import io, sys, contextlib
import os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import arr

FAKE = [
    {"title": "Interstellar", "year": 2014, "genres": ["Adventure", "Science Fiction"], "hasFile": True,
     "ratings": {"imdb": {"value": 8.7}}, "movieFile": {"quality": {"quality": {"name": "Bluray-1080p"}}}},
    {"title": "Dune: Part Two", "year": 2024, "genres": ["Science Fiction"], "hasFile": False, "ratings": {"imdb": {"value": 8.4}}},
    {"title": "Source Code", "year": 2011, "genres": ["Thriller", "Science Fiction"], "hasFile": True,
     "ratings": {"imdb": {"value": 7.5}}, "movieFile": {"quality": {"quality": {"name": "WEBDL-1080p"}}}},
    {"title": "Léon: The Professional", "year": 1994, "genres": ["Crime"], "hasFile": True, "ratings": {"imdb": {"value": 8.5}}},
    {"title": "Иван Васильевич меняет профессию", "year": 1973, "genres": ["Comedy", "Science Fiction"], "hasFile": True, "ratings": {}},
]
arr.get = lambda app, endpoint="", **p: FAKE if (app, endpoint) == ("radarr", "movie") else sys.exit("unexpected call")


def run(args):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        arr.cmd_movies(args)
    return buf.getvalue()


checks = []
o = run(["--genre", "science fiction", "--min-imdb", "7.5", "--have"])
checks.append(("sci-fi >=7.5 have -> Interstellar, Source Code only",
               "Interstellar" in o and "Source Code" in o and "Dune" not in o and "Иван" not in o and "2 match" in o))
o = run(["--genre", "science fiction", "--missing"])
checks.append(("missing -> Dune only", "Dune: Part Two" in o and "Interstellar" not in o and "1 match" in o))
o = run(["--title", "Иван"])
checks.append(("Cyrillic title search + output intact", "Иван Васильевич" in o and "?" not in o.split("|")[1]))
o = run(["--title", "Léon"])
checks.append(("accented title intact", "Léon: The Professional" in o))
try:
    run(["--bogus"])
    checks.append(("unknown option rejected", False))
except SystemExit as e:
    checks.append(("unknown option rejected", "unknown option" in str(e)))

# ---- audit: a fake stack with one of every gap we have met for real --------------------------------------------
LIB = "/volume1/media/movies/"
FS = {  # the filesystem API keyed by the exact path asked for; a path WITHOUT trailing slash returns the parent
    LIB: {"parent": "/volume1/media/", "directories": [{"name": "Husk", "path": LIB + "Husk/"}, {"name": "Old Rip", "path": LIB + "Old Rip/"}],
          "files": [{"name": "stray.mkv", "path": LIB + "stray.mkv", "size": 99 * 10**9}]},
    LIB + "Husk/": {"parent": LIB, "directories": [], "files": []},
    LIB + "Old Rip/": {"parent": LIB, "directories": [{"name": "Subs", "path": LIB + "Old Rip/Subs/"}],
                       "files": [{"name": "old.avi", "path": LIB + "Old Rip/old.avi", "size": 2 * 10**9}]},
    LIB + "Old Rip/Subs/": {"parent": LIB + "Old Rip/", "directories": [], "files": [{"name": "en.srt", "path": LIB + "Old Rip/Subs/en.srt", "size": 1000}]},
}
asked = []


def fake_get(app, endpoint="", **p):
    if app == "sabnzbd":  # one blob serves every mode: callers pick the key they need
        return {"queue": {"status": "Idle", "speed": "0", "noofslots": 0, "paused": False}, "version": "5",
                "config": {"misc": {"download_free": "", "complete_free": "50G", "complete_dir": "/volume1/sabnzbd-downloads/complete"}},
                "status": {"loadavg": "1 | 1 | 1", "warnings": [{"type": "ERROR", "text": "SQL Command Failed, see log"}] * 3}}
    if endpoint == "system/status":
        return {"version": "x"}
    if endpoint == "health":
        return [{"type": "warning", "source": "AllowedHostsCheck", "message": "ignored"}]
    if endpoint == "diskspace":
        return [{"path": "/volume1", "freeSpace": 300 * 10**9, "totalSpace": 7600 * 10**9}, {"path": "/", "freeSpace": 1, "totalSpace": 8 * 10**9}]
    if endpoint == "config/mediamanagement":
        return {"recycleBin": "/volume1/media/x-recycle", "deleteEmptyFolders": app != "sonarr"}
    if endpoint == "queue":
        return {"records": [{"title": "Fine", "status": "downloading", "trackedDownloadState": "downloading"},
                            {"title": "Blocked", "status": "completed", "trackedDownloadState": "importBlocked",
                             "statusMessages": [{"messages": ["Manual Import required"]}]}] if app == "radarr" else []}
    if endpoint == "rootfolder":
        return [{"path": LIB, "unmappedFolders": [{"name": "Husk", "path": LIB + "Husk"}, {"name": "Old Rip", "path": LIB + "Old Rip"}]}] if app == "radarr" else []
    if endpoint == "filesystem":
        asked.append(p["path"])
        return FS[p["path"]]
    if endpoint == "wanted/missing":
        if app == "sonarr":
            return {"records": [{"seriesId": 1, "airDateUtc": "2020-01-01T00:00:00Z", "series": {"title": "YouTube Show"}}] * 25
                    + [{"seriesId": 2, "airDateUtc": "2999-01-01T00:00:00Z", "series": {"title": "Future"}}]}
        return {"records": [{"title": "A", "isAvailable": True}, {"title": "B", "isAvailable": False}]}
    sys.exit(f"unexpected call {app} {endpoint} {p}")


arr.get = fake_get
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    arr.cmd_audit(["--sizes", "--top", "5"])
o = buf.getvalue()
checks.append(("audit: every filesystem call carries a trailing slash", all(a.endswith("/") for a in asked)))
checks.append(("audit: husk classified empty, rip sized from its own files only (2.0 GB, not the 99 GB stray in the parent)",
               "empty" in o and "2.00 GB    2 files content" in o))
checks.append(("audit: depth walk reached the Subs folder", LIB + "Old Rip/Subs/" in asked))
checks.append(("audit: sonarr deleteEmptyFolders flagged, radarr/lidarr not", "sonarr: deleteEmptyFolders off" in o and "radarr: deleteEmptyFolders off" not in o))
checks.append(("audit: blank SAB download_free flagged, complete_free not", "SAB download_free blank" in o and "complete_free blank" not in o))
checks.append(("audit: stuck import-blocked row flagged, downloading row not", "Blocked completed/importBlocked" in o and "Fine" not in o.split("stuck queue rows")[1].split("untracked")[0]))
checks.append(("audit: 25 aired-missing episodes of one series flagged, unaired ignored", "25 missing episodes of 'YouTube Show'" in o and "Future" not in o))
checks.append(("audit: radarr missing split released/unreleased", "2 missing movies, 1 already released" in o))
checks.append(("audit: SAB SQL errors flagged once, AllowedHosts not a finding", "SQL Command Failed" in o and "AllowedHosts" not in o.split("finding(s)")[1]))
checks.append(("audit: 300 GB free is not a disk finding, the 8 GB system disk is ignored", "GB free" not in o.split("finding(s)")[1]))

for name, ok in checks:
    print(("PASS " if ok else "FAIL ") + name)
sys.exit(0 if all(ok for _, ok in checks) else 1)
