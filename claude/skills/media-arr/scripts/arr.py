#!/usr/bin/env python3
"""arr.py - small client for the home NAS media stack (Radarr, Sonarr, Lidarr, SABnzbd).

Read-only by default. The only write path is `send`, which requires --confirm.
Keys are never printed. Output is unbuffered so background runs show progress live.

Usage (run with `python -u scripts/arr.py ...`):
  arr.py status  [app|all]                 version + health for one or all apps
  arr.py queue   <radarr|sonarr|lidarr>    queue rows with state and the reason each is stuck
  arr.py check-paths                       systemic causes: SAB category dirs, what each app's user can see, root-folder health
  arr.py movies  [--genre G] [--min-imdb X] [--have|--missing] [--title T]   Radarr library filter
  arr.py get     <app> <endpoint> [k=v ..] [--out FILE]   raw GET as JSON (e.g. `get radarr movie/lookup term=dune`)
  arr.py send    <app> <METHOD> <endpoint> <json|@file> --confirm   raw write (POST/PUT/DELETE)
  arr.py poll    <app> [minutes]           one status line per minute: running commands, queue size, SAB speed
  arr.py audit   [--sizes] [--top N]       read-only health review of the whole stack: disk, config gaps, stuck
                                           queue rows, untracked library folders (--sizes walks them: slow),
                                           wanted-list churn (series that are searched but never found), SAB warnings

Keys: ~/.config/media-arr/credentials  (lines `radarr=KEY`, `sonarr=KEY`, `lidarr=KEY`, `sabnzbd=KEY`; chmod 600),
      or env MEDIA_ARR_<APP>_KEY, or MEDIA_ARR_KEYDIR=<dir> holding `.<app>_auth` files (`key:<value>`).
"""
import json, os, sys, time, urllib.error, urllib.parse, urllib.request

HOST = os.environ.get("MEDIA_ARR_HOST", "192.168.1.83")
APPS = {  # SynoCommunity packages on the Synology; Radarr is NOT on its default 7878
    "radarr": {"port": 8310, "api": "/api/v3"},
    "sonarr": {"port": 8989, "api": "/api/v3"},
    "lidarr": {"port": 8686, "api": "/api/v1"},
    "sabnzbd": {"port": 8080, "api": "/api"},
}
TIMEOUT = int(os.environ.get("MEDIA_ARR_TIMEOUT", "180"))  # NAS gets slow under download/unpack load


try:  # keep Cyrillic/Romanian/accented titles readable on Windows consoles and in redirected logs
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def out(s=""):
    print(s, flush=True)


def key(app):
    env = os.environ.get(f"MEDIA_ARR_{app.upper()}_KEY")
    if env:
        return env.strip()
    cred = os.path.expanduser(os.environ.get("MEDIA_ARR_CREDENTIALS", "~/.config/media-arr/credentials"))
    if os.path.exists(cred):
        for line in open(cred, encoding="utf-8-sig"):
            k, _, v = line.strip().partition("=")
            if k.strip().lower() == app and v.strip():
                return v.strip()
    kd = os.environ.get("MEDIA_ARR_KEYDIR")
    if kd:
        p = os.path.join(kd, f".{app}_auth")
        if os.path.exists(p):
            raw = open(p, encoding="utf-8-sig").read().strip()
            return raw.split(":", 1)[1].strip() if raw.lower().startswith("key:") else raw
    sys.exit(f"no API key for {app}: add `{app}=<key>` to {cred} (see SKILL.md 'Keys')")


def base(app):
    a = APPS[app]
    return f"http://{HOST}:{a['port']}{a['api']}"


def get(app, endpoint="", **params):
    if app == "sabnzbd":
        params.update(output="json", apikey=key(app))
        url = f"{base(app)}?{urllib.parse.urlencode(params)}"
        headers = {}
    else:
        url = f"{base(app)}/{endpoint}" + (("?" + urllib.parse.urlencode(params)) if params else "")
        headers = {"X-Api-Key": key(app)}
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=TIMEOUT) as r:
            body = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:  # never echo the URL: SAB carries its key in the query
        sys.exit(f"HTTP {e.code} from {app} {endpoint or params.get('mode')}: {e.read().decode()[:300]}")
    except (TimeoutError, urllib.error.URLError, OSError) as e:
        sys.exit(f"{app} {endpoint or params.get('mode')}: no answer within {TIMEOUT}s ({type(e).__name__}). The NAS is "
                 f"probably busy (SAB unpacking / Lidarr refresh): ask the user to pause SABnzbd, or retry with "
                 f"MEDIA_ARR_TIMEOUT=600. Large lists (movie/series) are the slowest calls.")
    return json.loads(body) if body.strip() else None


def send(app, method, endpoint, body):
    req = urllib.request.Request(f"{base(app)}/{endpoint}", method=method,
                                 data=None if body is None else json.dumps(body).encode(),
                                 headers={"X-Api-Key": key(app), "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            txt = r.read().decode()
            return json.loads(txt) if txt.strip() else {"status": r.status}
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP {e.code} on {method} {endpoint}: {e.read().decode()[:600]}")


def cmd_status(which="all"):
    for app in (APPS if which == "all" else [which]):
        try:
            if app == "sabnzbd":
                q = get(app, mode="queue")["queue"]
                out(f"sabnzbd {get(app, mode='version').get('version')} | {q['status']} {q.get('speed')}B/s jobs={q.get('noofslots')} paused={q.get('paused')}")
                continue
            s = get(app, "system/status")
            out(f"{app} {s.get('version')} ({base(app)})")
            for h in get(app, "health"):
                out(f"   [{h['type']}] {h['source']}: {h['message'][:160]}")
        except SystemExit as e:
            out(f"{app}: {e}")


def reasons(r):
    return sorted({m for s in r.get("statusMessages") or [] for m in s.get("messages") or []})


def cmd_queue(app):
    inc = {"radarr": {"includeMovie": "true"}, "sonarr": {"includeSeries": "true", "includeEpisode": "true"},
           "lidarr": {"includeArtist": "true", "includeAlbum": "true"}}[app]
    recs = get(app, "queue", pageSize=500, **inc)["records"]
    out(f"{app} queue: {len(recs)}")
    for r in recs:
        who = (r.get("movie") or {}).get("title") or (r.get("series") or {}).get("title") or (r.get("artist") or {}).get("artistName") or "?"
        size, left = r.get("size") or 0, r.get("sizeleft") or 0
        pct = f"{100 * (size - left) / size:.0f}%" if size else "-"
        out(f" - {who} | {r.get('title', '')[:60]} | {r.get('status')}/{r.get('trackedDownloadState')} {pct} "
            f"left {r.get('timeleft') or '-'} | {r.get('errorMessage') or ''} {reasons(r)[:2]} | downloadId={r.get('downloadId')}")


def cmd_movies(args):
    """Radarr library filter: movies [--genre G] [--min-imdb X] [--have|--missing] [--title T]"""
    opt = {"genre": None, "min-imdb": 0.0, "title": None}
    have = None
    it = iter(args)
    for a in it:
        if a == "--have":
            have = True
        elif a == "--missing":
            have = False
        elif a.startswith("--") and a[2:] in opt:
            opt[a[2:]] = next(it)
        else:
            sys.exit(f"unknown option {a}")
    rows = []
    for m in get("radarr", "movie"):
        imdb = ((m.get("ratings") or {}).get("imdb") or {}).get("value")
        genres = [g.lower() for g in m.get("genres") or []]
        if opt["genre"] and not any(opt["genre"].lower() in g for g in genres):
            continue
        if float(opt["min-imdb"]) and (imdb or 0) < float(opt["min-imdb"]):
            continue
        if have is not None and bool(m.get("hasFile")) != have:
            continue
        if opt["title"] and opt["title"].lower() not in m["title"].lower():
            continue
        rows.append((imdb or 0, m))
    for imdb, m in sorted(rows, key=lambda x: -x[0]):
        q = ((m.get("movieFile") or {}).get("quality") or {}).get("quality", {}).get("name", "-")
        out(f"{imdb or '-':>4} | {m['title']} ({m.get('year')}) | {'have ' + q if m.get('hasFile') else 'missing'} | {', '.join(m.get('genres') or [])}")
    out(f"-- {len(rows)} match(es)")


def cmd_check_paths():
    """The systemic checks to run BEFORE touching any stuck queue."""
    misc = get("sabnzbd", mode="get_config", section="misc")["config"]["misc"]
    complete = misc.get("complete_dir")
    out(f"SAB complete_dir = {complete}   (must NOT be a library folder like /volume1/media)")
    cats = get("sabnzbd", mode="get_config", section="categories")["config"]["categories"]
    for c in cats:
        d = c.get("dir") or ""
        eff = d if d.startswith("/") else (f"{complete.rstrip('/')}/{d}" if d else complete)
        flag = "  <-- inside library!" if eff.startswith("/volume1/media") else ""
        out(f"  category {c['name']:9} dir={d!r:45} -> {eff}{flag}")
    for app in ("radarr", "sonarr", "lidarr"):
        try:
            for dc in get(app, "downloadclient"):
                cat = next((f.get("value") for f in dc["fields"] if f["name"].endswith("Category")), None)
                out(f"{app}: download client {dc['name']} category={cat}")
            for p in ("/volume1/sabnzbd-downloads/", f"{complete.rstrip('/')}/"):
                r = get(app, "filesystem", path=p, includeFiles="false")
                names = [d["name"] for d in r.get("directories", [])]
                out(f"   {app} user sees {p}: {names[:8] if names else 'NOTHING (DSM share permission for sc-' + app + ' missing?)'}")
            for h in get(app, "health"):
                if any(k in h["source"] for k in ("RootFolder", "RemotePath", "DownloadClient")):
                    out(f"   [{h['type']}] {h['source']}: {h['message'][:160]}")
        except SystemExit as e:
            out(f"{app}: {e}")


def cmd_poll(app, minutes=60):
    for _ in range(int(minutes)):
        try:
            cmds = [c for c in get(app, "command") if c["status"] in ("started", "queued")]
            counts = {}
            for c in cmds:
                counts[c["name"]] = counts.get(c["name"], 0) + 1
            running = [(c.get("message") or c["name"])[:50] for c in cmds if c["status"] == "started"]
            q = len(get(app, "queue", pageSize=1)["records"]) if app != "sabnzbd" else "-"
            s = get("sabnzbd", mode="queue")["queue"]
            out(f"{time.strftime('%H:%M')} pending={counts} running={running[:2]} queue={q} | SAB {s['status']} {s.get('speed')}B/s jobs={s.get('noofslots')}")
            if not cmds:
                out("nothing pending - done")
                return
        except SystemExit as e:
            out(f"{time.strftime('%H:%M')} poll error: {e}")
        time.sleep(60)


VIDEO_EXT = (".mkv", ".mp4", ".avi", ".m2ts", ".iso", ".mov", ".wmv", ".vob", ".ts", ".m4v")
GB = 1e9


def fs_walk(app, path, max_depth=4):
    """Size a folder through the app's filesystem API (the only view of the NAS we have).

    Two traps, both hit in practice: without a trailing slash the API answers with the PARENT listing, and
    an odd path can do the same - so the path is always normalised and nothing outside it is ever followed.
    Returns {"bytes", "files", "video": [(name, bytes)], "truncated"}.
    """
    acc = {"bytes": 0, "files": 0, "video": [], "truncated": False}

    def walk(p, depth):
        p = p.rstrip("/") + "/"
        r = get(app, "filesystem", path=p, includeFiles="true") or {}
        for f in r.get("files") or []:
            if not (f.get("path") or p).startswith(p):
                continue
            acc["bytes"] += f.get("size") or 0
            acc["files"] += 1
            if f.get("name", "").lower().endswith(VIDEO_EXT):
                acc["video"].append((f["name"], f.get("size") or 0))
        subs = [d for d in r.get("directories") or [] if d.get("path", "").startswith(p) and d["path"].rstrip("/") != p.rstrip("/")]
        if depth >= max_depth and subs:
            acc["truncated"] = True
            return
        for d in subs:
            walk(d["path"], depth + 1)

    walk(path, 0)
    return acc


def classify_unmapped(name, acc):
    if acc["files"] == 0:
        return "empty"
    if name.startswith(("_UNPACK_", "_FAILED_")):
        return "leftover download"
    if not acc["video"]:
        return "no video"
    return "content"


def cmd_audit(args):
    """Read-only review of the whole stack. Writes nothing; every finding names the fix."""
    sizes, top = "--sizes" in args, 15
    if "--top" in args:
        top = int(args[args.index("--top") + 1])
    findings = []

    def flag(msg):
        findings.append(msg)
        out(f"   !! {msg}")

    out("== health")
    cmd_status("all")

    out("== disk")
    try:
        for d in get("radarr", "diskspace"):
            if d.get("totalSpace", 0) > 100 * GB:
                free, total = d["freeSpace"] / GB, d["totalSpace"] / GB
                out(f"   {d['path']}: free {free:,.0f} / {total:,.0f} GB ({100 * free / total:.0f}%)")
                if free < 200:  # GB. SAB's floor is 50 GB; below 200 one 4K season fills the volume
                    flag(f"{d['path']} only {free:,.0f} GB free - check #recycle and the *-recycle folders first")
    except SystemExit as e:
        out(f"   diskspace: {e}")

    out("== config gaps")
    for app in ("radarr", "sonarr", "lidarr"):
        try:
            mm = get(app, "config/mediamanagement")
            if not mm.get("recycleBin"):
                flag(f"{app}: no recycle bin - deletes are immediate (Settings > Media Management)")
            if not mm.get("deleteEmptyFolders"):
                flag(f"{app}: deleteEmptyFolders off - every upgrade/delete leaves an empty husk behind")
            for h in get(app, "health"):
                if h["type"] != "ok" and "AllowedHosts" not in h["source"]:
                    flag(f"{app} health {h['type']}: {h['source']}: {h['message'][:120]}")
        except SystemExit as e:
            out(f"   {app}: {e}")
    try:
        misc = get("sabnzbd", mode="get_config", section="misc")["config"]["misc"]
        for k in ("download_free", "complete_free"):
            if not misc.get(k):
                flag(f"SAB {k} blank - SAB will fill the volume to zero; set e.g. 50G (set_config section=misc keyword={k} value=50G)")
        if str(misc.get("complete_dir", "")).startswith("/volume1/media"):
            flag("SAB complete_dir is inside the library - run check-paths")
    except SystemExit as e:
        out(f"   sabnzbd: {e}")

    out("== stuck queue rows")
    for app in ("radarr", "sonarr", "lidarr"):
        try:
            recs = get(app, "queue", pageSize=500)["records"]
            stuck = [r for r in recs if r.get("status") != "downloading" or r.get("trackedDownloadState") not in ("downloading", "importPending", "importing")]
            out(f"   {app}: {len(recs)} rows, {len(stuck)} stuck")
            for r in stuck:
                flag(f"{app} queue: {r.get('title', '')[:50]} {r.get('status')}/{r.get('trackedDownloadState')} {(r.get('errorMessage') or '')[:60]} {reasons(r)[:1]}")
        except SystemExit as e:
            out(f"   {app}: {e}")

    out("== untracked folders inside the libraries" + ("" if sizes else "  (add --sizes to measure them)"))
    for app in ("radarr", "sonarr"):
        try:
            for root in get(app, "rootfolder"):
                um = root.get("unmappedFolders") or []
                out(f"   {app} {root['path']}: {len(um)} unmapped folder(s)")
                if not sizes:
                    for u in um[:top]:
                        out(f"      {u['name'][:80]}")
                    continue
                rows = []
                for u in um:
                    acc = fs_walk(app, u["path"])
                    rows.append((acc["bytes"], classify_unmapped(u["name"], acc), u["name"], acc))
                by = {}
                for b, kind, _, _ in rows:
                    n, g = by.get(kind, (0, 0))
                    by[kind] = (n + 1, g + b)
                for kind, (n, g) in sorted(by.items(), key=lambda x: -x[1][1]):
                    out(f"      {kind:18} {n:3} folder(s) {g / GB:8.1f} GB")
                for b, kind, name, acc in sorted(rows, key=lambda x: -x[0])[:top]:
                    big = max(acc["video"], key=lambda v: v[1])[0][:50] if acc["video"] else "-"
                    out(f"      {b / GB:7.2f} GB {acc['files']:4} files {kind:18} {name[:55]}  | {big}{' (depth-limited)' if acc['truncated'] else ''}")
                total = sum(r[0] for r in rows)
                if total > 20 * GB:
                    flag(f"{app}: {total / GB:,.0f} GB in {len(um)} folders no app manages - import the keepers, delete the rest in File Station")
        except SystemExit as e:
            out(f"   {app}: {e}")

    out("== wanted-list churn (searched every RSS cycle, never found)")
    try:
        today = time.strftime("%Y-%m-%d")
        recs = get("sonarr", "wanted/missing", pageSize=1000, includeSeries="true")["records"]
        aired = [e for e in recs if (e.get("airDateUtc") or "9")[:10] <= today]
        by = {}
        for e in aired:
            t = (e.get("series") or {}).get("title") or f"series {e.get('seriesId')}"
            by[t] = by.get(t, 0) + 1
        out(f"   sonarr: {len(aired)} aired episodes missing across {len(by)} series")
        for t, n in sorted(by.items(), key=lambda x: -x[1])[:top]:
            out(f"      {n:4} {t}")
            if n >= 20:
                flag(f"sonarr: {n} missing episodes of '{t}' - if it is not on Usenet, unmonitor it to stop burning indexer quota")
        recs = get("radarr", "wanted/missing", pageSize=1000)["records"]
        avail = [m for m in recs if m.get("isAvailable")]
        out(f"   radarr: {len(recs)} missing movies, {len(avail)} already released (the rest are unreleased, fine)")
    except SystemExit as e:
        out(f"   wanted: {e}")

    out("== SAB warnings")
    try:
        st = get("sabnzbd", mode="fullstatus")["status"]
        out(f"   loadavg {st.get('loadavg')}")
        warns = st.get("warnings") or []
        kinds = {}
        for w in warns:
            k = (w.get("type"), w.get("text", "")[:50])
            kinds[k] = kinds.get(k, 0) + 1
        for (typ, txt), n in sorted(kinds.items(), key=lambda x: -x[1])[:top]:
            out(f"   {n:3}x {typ} {txt}")
            if typ == "ERROR" and "SQL" in txt:
                flag("SAB 'SQL Command Failed' - database locked under NAS load; keep heavy imports and SAB unpacks from overlapping")
    except SystemExit as e:
        out(f"   sabnzbd: {e}")

    out(f"== {len(findings)} finding(s)")
    for f in findings:
        out(f" - {f}")


def main(argv):
    if len(argv) < 2 or argv[1] in ("-h", "--help"):
        out(__doc__); return
    c = argv[1]
    if c == "status":
        cmd_status(argv[2] if len(argv) > 2 else "all")
    elif c == "queue":
        cmd_queue(argv[2])
    elif c == "check-paths":
        cmd_check_paths()
    elif c == "get":
        rest = argv[4:]
        dest = None
        if "--out" in rest:
            i = rest.index("--out")
            dest = rest[i + 1]
            rest = rest[:i] + rest[i + 2:]
        params = dict(a.split("=", 1) for a in rest)
        res = get(argv[2], "" if argv[2] == "sabnzbd" else argv[3], **({**params, "mode": argv[3]} if argv[2] == "sabnzbd" else params))
        text = json.dumps(res, indent=1, ensure_ascii=False)
        if dest:  # large payloads (e.g. the whole movie list) belong in a file, not the terminal
            open(dest, "w", encoding="utf-8").write(text)
            out(f"wrote {len(text)} chars to {dest}")
        else:
            out(text)
    elif c == "movies":
        cmd_movies(argv[2:])
    elif c == "send":
        if "--confirm" not in argv:
            sys.exit("refusing to write without --confirm (show the user the dry-run first)")
        args = [a for a in argv[2:] if a != "--confirm"]
        app, method, endpoint = args[0], args[1].upper(), args[2]
        body = None
        if len(args) > 3:
            body = json.load(open(args[3][1:], encoding="utf-8")) if args[3].startswith("@") else json.loads(args[3])
        out(json.dumps(send(app, method, endpoint, body), indent=1)[:20000])
    elif c == "poll":
        cmd_poll(argv[2], argv[3] if len(argv) > 3 else 60)
    elif c == "audit":
        cmd_audit(argv[2:])
    else:
        sys.exit(f"unknown command {c}; see --help")


if __name__ == "__main__":
    main(sys.argv)
