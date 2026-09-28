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
    else:
        sys.exit(f"unknown command {c}; see --help")


if __name__ == "__main__":
    main(sys.argv)
