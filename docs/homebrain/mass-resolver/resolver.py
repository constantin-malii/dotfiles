#!/usr/bin/env python3
# Music Assistant provider-aware resolver (Phase 1, Option A) -- runs on the homebrain HOST.
# Python 3.5 compatible (no f-strings). Raw-socket WebSocket clients for MA + HA.
#
# Phase 1 guarantee: ONLY items backed by the filesystem_smb (local NAS) provider may be
# resolved/played. YTM (or any non-preferred provider) is never selected.
#
# Secrets (0600, costea-owned, NEVER logged):  ~/mass-resolver/.ma_token  ~/mass-resolver/.ha_token
# Non-secret settings: ~/mass-resolver/config.json
#
# Modes:
#   python3 resolver.py --dry-run --query "Du Hast" --media-type track   # prove filtering, no audio
#   python3 resolver.py --query "Rammstein" --media-type artist          # one-shot play
#   python3 resolver.py --serve                                          # subscribe to HA events
import os, sys, json, socket, base64, struct, argparse, logging, uuid, time, re, difflib

HERE = os.path.dirname(os.path.abspath(__file__))
def _read(path, default=None):
    try:
        with open(path) as f: return f.read().strip()
    except Exception: return default

CFG = json.loads(_read(os.path.join(HERE, "config.json"), "{}"))
MA_HOST = CFG.get("ma_host", "192.168.122.10"); MA_PORT = int(CFG.get("ma_port", 8095))
HA_HOST = (CFG.get("ha_url", "http://192.168.122.10:8123").split("://", 1)[-1].split(":")[0])
HA_PORT = int(CFG.get("ha_url", "http://192.168.122.10:8123").rsplit(":", 1)[-1].split("/")[0])
PROVIDER_PREFERENCE = CFG.get("provider_preference", ["filesystem_smb"])
TYPE_ORDER = CFG.get("type_order", ["artist", "album", "track", "playlist"])
QUEUE_ID = CFG.get("ceiling_player_id", "upf8b156c25101")
EVENT_TYPE = CFG.get("event_type", "mass_play_request")
SYNC_EVENT_TYPE = CFG.get("sync_event_type", "mass_sync_request")
MA_TOKEN = _read(os.path.join(HERE, ".ma_token"))
HA_TOKEN = _read(os.path.join(HERE, ".ha_token"))

LOG = logging.getLogger("resolver")
def _setup_logging():
    LOG.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    sh = logging.StreamHandler(sys.stdout); sh.setFormatter(fmt); LOG.addHandler(sh)
    try:
        fh = logging.FileHandler(os.path.join(HERE, "resolver.log")); fh.setFormatter(fmt); LOG.addHandler(fh)
    except Exception: pass

WS_CMD = {"artist": "music/artists/library_items", "album": "music/albums/library_items",
          "track": "music/tracks/library_items", "playlist": "music/playlists/library_items"}

# ---------- generic raw WebSocket helpers ----------
def _ws_connect(host, port, path):
    s = socket.create_connection((host, port), timeout=15)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    k = base64.b64encode(os.urandom(16)).decode()
    s.sendall(("GET %s HTTP/1.1\r\nHost: %s\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n" % (path, host, k)).encode())
    buf = b""
    while b"\r\n\r\n" not in buf: buf += s.recv(65536)
    return s, {"b": buf.split(b"\r\n\r\n", 1)[1]}

def _need(s, box, n):
    while len(box["b"]) < n:
        chunk = s.recv(65536)
        if not chunk: raise IOError("websocket closed (EOF)")
        box["b"] += chunk

def _ws_frame(s, box):
    _need(s, box, 2)
    b0 = box["b"][0]; op = b0 & 0x0f; ln = box["b"][1] & 0x7f; idx = 2
    if ln == 126:
        _need(s, box, 4); ln = struct.unpack(">H", box["b"][2:4])[0]; idx = 4
    elif ln == 127:
        _need(s, box, 10); ln = struct.unpack(">Q", box["b"][2:10])[0]; idx = 10
    _need(s, box, idx + ln)
    p = box["b"][idx:idx + ln]; box["b"] = box["b"][idx + ln:]; return (b0 & 0x80), op, p

def _ws_pong(s, payload):
    p = payload[:125]; m = os.urandom(4); ln = len(p)
    md = bytes(bytearray(x ^ m[i % 4] for i, x in enumerate(p)))
    s.sendall(b"\x8a" + bytes(bytearray([0x80 | ln])) + m + md)

def _ws_read(s, box):
    data = b""
    while True:
        fin, op, p = _ws_frame(s, box)
        if op == 8: return None          # close
        if op == 9: _ws_pong(s, p); continue   # ping -> pong (keepalive)
        if op == 10: continue            # pong
        data += p
        if fin:
            try: return json.loads(data.decode("utf-8"))
            except Exception: data = b""

def _ws_send(s, obj):
    d = json.dumps(obj).encode(); m = os.urandom(4)
    md = bytes(bytearray(x ^ m[i % 4] for i, x in enumerate(d))); ln = len(d)
    if ln < 126:
        s.sendall(b"\x81" + bytes(bytearray([0x80 | ln])) + m + md)
    elif ln < 65536:
        s.sendall(b"\x81" + bytes(bytearray([0x80 | 126])) + struct.pack(">H", ln) + m + md)
    else:
        s.sendall(b"\x81" + bytes(bytearray([0x80 | 127])) + struct.pack(">Q", ln) + m + md)

# ---------- Music Assistant ----------
class MA(object):
    def __init__(self, host, port, token):
        self.host = host; self.port = port; self.token = token; self.s = None; self.box = None; self.mid = 0
    def connect(self):
        self.s, self.box = _ws_connect(self.host, self.port, "/ws"); self.s.settimeout(60)
        _ws_read(self.s, self.box)                 # server-info
        self._cmd("auth", token=self.token)
    def _cmd(self, command, **args):
        self.mid += 1; mid = str(self.mid)
        _ws_send(self.s, {"command": command, "message_id": mid, "args": args})
        for _ in range(800):
            m = _ws_read(self.s, self.box)
            if m is None: return None
            if m.get("message_id") == mid: return m
    def library(self, media_type):
        r = self._cmd(WS_CMD[media_type], limit=1000)
        res = (r or {}).get("result")
        return res.get("items") if isinstance(res, dict) else (res or [])
    def play(self, queue_id, uri, option="replace"):
        # "replace" => each play_music yields a fresh queue (immune to stale/contaminated queue state)
        return self._cmd("player_queues/play_media", queue_id=queue_id, media=uri, option=option)
    def close(self):
        try: self.s.close()
        except Exception: pass

def _clean(x):
    return re.sub(r"\s+", " ", re.sub(r"[^0-9a-z ]+", " ", (x or "").lower())).strip()
def _compact(x):
    return re.sub(r"[^0-9a-z]+", "", (x or "").lower())
def _match_rank(query, name):
    if not name: return None
    q = _clean(query)
    qcore = q.split(" by ")[0].strip() if " by " in q else q   # "<title> by <artist>" -> title
    if not qcore: return None
    n = _clean(name); nc = _compact(name); qc = _compact(qcore)
    if n == qcore or (qc and nc == qc): return 0           # exact (punctuation-insensitive; e.g. "E-N-G-E-L"->engel)
    if n.startswith(qcore) or (qc and nc.startswith(qc)): return 1
    if qcore in n or (qc and qc in nc): return 2
    if qcore.split() and all(w in n.split() for w in qcore.split()): return 3
    if qc and len(qc) >= 4 and difflib.SequenceMatcher(None, qc, nc).ratio() >= 0.86: return 4  # close typo
    return None

def resolve_type(ma, query, media_type, rid):
    items = ma.library(media_type)
    ranked = []
    for it in items:
        r = _match_rank(query, it.get("name"))
        if r is not None: ranked.append((r, it))
    ranked.sort(key=lambda t: t[0])
    for _, it in ranked:
        name = it.get("name"); maps = it.get("provider_mappings") or []
        local = None
        for m in maps:
            if m.get("provider_domain") in PROVIDER_PREFERENCE and m.get("available"):
                local = m; break
        if local:
            uri = "%s://%s/%s" % (local.get("provider_instance"), media_type, local.get("item_id"))
            LOG.info("req=%s query=%r media_type=%s candidate=%r provider=%s uri=%s decision=ACCEPTED reason=%s",
                     rid, query, media_type, name, local.get("provider_domain"), uri, "preferred-provider mapping available")
            return {"accepted": True, "uri": uri, "provider": local.get("provider_domain"), "candidate": name, "media_type": media_type}
        else:
            LOG.info("req=%s query=%r media_type=%s candidate=%r provider=%s uri=%s decision=REJECTED reason=%s",
                     rid, query, media_type, name, [m.get("provider_domain") for m in maps], it.get("uri"),
                     "no preferred-provider (%s) mapping" % ",".join(PROVIDER_PREFERENCE))
    return None

def resolve_any(ma, query, media_type, rid):
    # try the hinted type first (if any), then fall back to all other types --
    # so a wrong media_type guess from the assistant never blocks a real match.
    if media_type in WS_CMD:
        types = [media_type] + [t for t in TYPE_ORDER if t != media_type]
    else:
        types = list(TYPE_ORDER)
    for mt in types:
        r = resolve_type(ma, query, mt, rid)
        if r: return r
    LOG.info("req=%s query=%r media_type=%s decision=REJECTED reason=%s", rid, query, media_type or "(any)",
             "no preferred-provider match in any type %s" % types)
    return {"accepted": False, "reason": "no local match"}

def handle_request(query, media_type, dry_run=False):
    rid = uuid.uuid4().hex[:8]
    ma = MA(MA_HOST, MA_PORT, MA_TOKEN)
    try:
        ma.connect()
        res = resolve_any(ma, query, media_type, rid); res["request_id"] = rid
        if res.get("accepted"):
            if dry_run:
                LOG.info("[DRY-RUN] req=%s WOULD PLAY %s (provider=%s)", rid, res["uri"], res["provider"])
            else:
                pr = ma.play(QUEUE_ID, res["uri"])
                if pr and "error_code" in pr:
                    LOG.error("req=%s PLAY FAILED code=%s details=%s", rid, pr.get("error_code"), pr.get("details")); res["played"] = False
                else:
                    LOG.info("req=%s PLAYING %s (provider=%s)", rid, res["uri"], res["provider"]); res["played"] = True
        else:
            LOG.info("req=%s NOTHING PLAYED (%s)", rid, res.get("reason"))
        return res
    finally:
        ma.close()

def handle_sync():
    rid = uuid.uuid4().hex[:8]
    ma = MA(MA_HOST, MA_PORT, MA_TOKEN)
    try:
        ma.connect()
        ma._cmd("music/sync")
        LOG.info("SYNC: req=%s music/sync triggered (Lidarr import)", rid)
    finally:
        ma.close()

# ---------- Home Assistant event subscription (service mode) ----------
def serve():
    if not HA_TOKEN:
        LOG.error("no HA token (~/mass-resolver/.ha_token)"); sys.exit(2)
    backoff = 2
    while True:
        try:
            s, box = _ws_connect(HA_HOST, HA_PORT, "/api/websocket"); s.settimeout(None)
            hello = _ws_read(s, box)
            if (hello or {}).get("type") != "auth_required":
                raise RuntimeError("unexpected HA hello: %r" % hello)
            _ws_send(s, {"type": "auth", "access_token": HA_TOKEN})
            if (_ws_read(s, box) or {}).get("type") != "auth_ok":
                raise RuntimeError("HA auth failed")
            _ws_send(s, {"id": 1, "type": "subscribe_events", "event_type": EVENT_TYPE}); _ws_read(s, box)
            _ws_send(s, {"id": 2, "type": "subscribe_events", "event_type": SYNC_EVENT_TYPE}); _ws_read(s, box)
            LOG.info("SERVICE: connected; subscribed to %r (play) + %r (sync); provider_preference=%s", EVENT_TYPE, SYNC_EVENT_TYPE, PROVIDER_PREFERENCE)
            backoff = 2
            while True:
                m = _ws_read(s, box)
                if m is None: raise RuntimeError("HA connection closed")
                if m.get("type") == "event":
                    ev = m.get("event") or {}; et = ev.get("event_type"); data = ev.get("data") or {}
                    if et == EVENT_TYPE:
                        q = data.get("query"); mt = data.get("media_type") or ""
                        LOG.info("SERVICE: play event query=%r media_type=%r", q, mt)
                        if q:
                            try: handle_request(q, mt, dry_run=bool(CFG.get("dry_run", False)))
                            except Exception as e: LOG.error("SERVICE: handle_request error: %r", e)
                    elif et == SYNC_EVENT_TYPE:
                        LOG.info("SERVICE: sync event (source=%r)", data.get("source"))
                        try: handle_sync()
                        except Exception as e: LOG.error("SERVICE: handle_sync error: %r", e)
        except Exception as e:
            LOG.error("SERVICE: connection error: %r; reconnecting in %ss", e, backoff)
            time.sleep(backoff); backoff = min(backoff * 2, 60)

def main():
    _setup_logging()
    ap = argparse.ArgumentParser()
    ap.add_argument("--serve", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--query")
    ap.add_argument("--media-type", default="", choices=["", "artist", "album", "track", "playlist"])
    a = ap.parse_args()
    if not MA_TOKEN:
        LOG.error("no MA token (~/mass-resolver/.ma_token)"); sys.exit(2)
    if a.serve:
        serve(); return
    if not a.query:
        LOG.error("--query required (or use --serve)"); sys.exit(2)
    res = handle_request(a.query, a.media_type, dry_run=a.dry_run)
    print(json.dumps(res))

if __name__ == "__main__":
    main()
