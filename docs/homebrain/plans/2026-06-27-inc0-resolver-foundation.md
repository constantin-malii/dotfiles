# Inc 0 — Resolver Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the monolithic homebrain `resolver.py` into small, single-responsibility modules with clean capability-function boundaries, config-driven data files, and an honest failure-feedback (TTS) path — preserving today's music + sync behavior exactly and adding stub modules for the future radio/news/acquire/status capabilities.

**Architecture:** A thin entrypoint (`resolver.py`) wires Home Assistant events to a dispatch registry in `core.py`, which calls capability functions (`music.resolve_music`, plus stubs `radio`/`news`/`acquire`/`status`) and announces honest spoken feedback on failure via `haconn`. Transport (raw WebSocket), the MA client, the HA client, the pure text matcher, and config loading each live in their own module. Capability functions take plain arguments and return a plain result dict — decoupled from the HA-event adapter so they can later be wrapped as MCP tools without a rewrite.

**Tech Stack:** Python 3.5 (host constraint — **no f-strings**, stdlib only: `socket`, `json`, `struct`, `base64`, `re`, `difflib`, `logging`, `argparse`, `uuid`). Tests use the stdlib `unittest` runner (no pytest), following the existing `docs/homebrain/test_ytm_guard.py` pattern (fakes, `python test_x.py`).

## Global Constraints

- **Python 3.5 compatibility (deployed code):** no f-strings, no `:=`, no `dict|dict` merge. Use `%`-formatting / `.format()`. (Tests run on dev-machine Python 3.12 but keep module code 3.5-safe.)
- **Secrets NEVER in repo/docs/logs:** tokens live only in `0600` costea-owned files on the host (`~/mass-resolver/.ma_token`, `.ha_token`, future `.lidarr`). Never echo a token in a command — use stdin pipes. Repo `.gitignore` already excludes `*.token`, `.ma_token`, `.ha_token`, `.lidarr`, `*.log`.
- **Additive / reversible:** the original monolithic `resolver.py` is preserved in git (commit `2e2bec7`) and on the host as `resolver.py.orig`; it is a complete standalone fallback (imports no new modules). Reverting = copy `resolver.py.orig` over `resolver.py` and restart.
- **Do NOT expose new functionality to ChatGPT until validated.** Inc 0 adds no new ChatGPT tools; stubs return honest "not available yet".
- **Do not touch** Plex, old HA Core, networking, or video libraries.
- **Service restarts are the user's action** (no passwordless sudo). The plan deploys files and asks the user to `sudo systemctl restart mass-resolver`.
- **No Claude/AI attribution** in commits or PRs. Secret-scan before every commit.
- **Repo source of truth:** `D:\repos\dotfiles\docs\homebrain\mass-resolver\` mirrors what deploys to `~costea/mass-resolver/` on host `192.168.1.68` (user `costea`). SSH needs `ssh-add ~/.ssh/id_homebrain` first (agent drops between calls); MA reachable from host at `192.168.122.10:8095`, HA at `192.168.122.10:8123`.

### Capability result contract (used by every capability + the dispatcher)

Every capability function returns a dict with this shape. Later tasks rely on these exact keys:

```
{
  "ok": bool,            # overall user-facing success (canonical success flag)
  "intent": str,         # "music" | "radio" | "news" | "acquire" | "status" | "sync"
  "request_id": str,     # 8-hex correlation id
  "spoken": str | None,  # short honest line for TTS; set on failure (and may be set on success)
  "reason": str | None,  # machine reason on failure
  # music-success extras: "uri", "provider", "candidate", "media_type", "played"
  # stubs: "not_implemented": True
}
```

**Dispatcher rule:** after calling a capability, if `not result["ok"]` and `result.get("spoken")`, announce `result["spoken"]` via `haconn` (honest failure feedback). `sync` is exempt (maintenance op, never announces).

---

## Task 1: Preserve original on host + create test scaffolding dir

**Files:**
- Create (host): `~costea/mass-resolver/resolver.py.orig` (byte copy of current live `resolver.py`)
- Create (repo): `docs/homebrain/mass-resolver/tests/__init__.py` (empty marker)

**Interfaces:**
- Produces: a guaranteed standalone fallback (`resolver.py.orig`) and a tests dir for all later `test_*.py`.

- [ ] **Step 1: Back up the live resolver on the host**

```bash
ssh-add ~/.ssh/id_homebrain
ssh costea@192.168.1.68 'cd ~/mass-resolver && cp -n resolver.py resolver.py.orig && ls -la resolver.py resolver.py.orig'
```
Expected: both files listed, identical size (12978 bytes). `-n` = no-clobber (won't overwrite an existing backup).

- [ ] **Step 2: Verify the backup is byte-identical**

```bash
ssh costea@192.168.1.68 'cd ~/mass-resolver && cmp resolver.py resolver.py.orig && echo IDENTICAL'
```
Expected: `IDENTICAL`.

- [ ] **Step 3: Create the repo tests dir marker**

Create `docs/homebrain/mass-resolver/tests/__init__.py` containing a single comment line:

```python
# Inc 0 resolver unit tests (stdlib unittest). Run each: python tests/test_<name>.py
```

- [ ] **Step 4: Commit**

```bash
git add docs/homebrain/mass-resolver/tests/__init__.py
git commit -m "test(homebrain): add resolver tests package"
```

---

## Task 2: `match.py` — pure text matcher (extract + test)

**Files:**
- Create: `docs/homebrain/mass-resolver/match.py`
- Test: `docs/homebrain/mass-resolver/tests/test_match.py`

**Interfaces:**
- Produces: `clean(s) -> str`, `compact(s) -> str`, `match_rank(query, name) -> int | None` (0=exact … 4=fuzzy, None=no match). Consumed by `music.py` (Task 7).

- [ ] **Step 1: Write the failing test**

Create `tests/test_match.py`:

```python
#!/usr/bin/env python3
"""Unit tests for the pure text matcher. Run: python tests/test_match.py"""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from match import clean, compact, match_rank


class MatchTest(unittest.TestCase):
    def test_clean_lowercases_and_strips_punctuation(self):
        self.assertEqual(clean("E-N-G-E-L!"), "e n g e l")

    def test_compact_removes_all_non_alnum(self):
        self.assertEqual(compact("E-N-G-E-L"), "engel")

    def test_exact_match_is_rank_0(self):
        self.assertEqual(match_rank("Engel", "Engel"), 0)

    def test_punctuation_insensitive_exact_is_rank_0(self):
        self.assertEqual(match_rank("E-N-G-E-L", "Engel"), 0)

    def test_prefix_is_rank_1(self):
        self.assertEqual(match_rank("Du", "Du Hast"), 1)

    def test_contains_is_rank_2(self):
        self.assertEqual(match_rank("Hast", "Du Hast"), 2)

    def test_all_tokens_present_is_rank_3(self):
        self.assertEqual(match_rank("hast du", "Du Hast Mich"), 3)

    def test_close_typo_is_rank_4(self):
        self.assertEqual(match_rank("Rammstein", "Ramstein"), 4)

    def test_title_by_artist_uses_title_only(self):
        self.assertEqual(match_rank("Engel by Rammstein", "Engel"), 0)

    def test_no_match_returns_none(self):
        self.assertIsNone(match_rank("Beethoven", "Du Hast"))

    def test_empty_name_returns_none(self):
        self.assertIsNone(match_rank("anything", ""))


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd docs/homebrain/mass-resolver && python tests/test_match.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'match'`.

- [ ] **Step 3: Write minimal implementation**

Create `match.py` (logic moved verbatim from baseline `resolver.py` lines 126–141, renamed to public names):

```python
#!/usr/bin/env python3
# Pure text matcher for the resolver. No I/O, no deps beyond stdlib. Python 3.5 safe.
import re, difflib


def clean(x):
    return re.sub(r"\s+", " ", re.sub(r"[^0-9a-z ]+", " ", (x or "").lower())).strip()


def compact(x):
    return re.sub(r"[^0-9a-z]+", "", (x or "").lower())


def match_rank(query, name):
    """Return 0(exact)..4(close typo) or None. Lower is a better match."""
    if not name:
        return None
    q = clean(query)
    qcore = q.split(" by ")[0].strip() if " by " in q else q   # "<title> by <artist>" -> title
    if not qcore:
        return None
    n = clean(name); nc = compact(name); qc = compact(qcore)
    if n == qcore or (qc and nc == qc):
        return 0
    if n.startswith(qcore) or (qc and nc.startswith(qc)):
        return 1
    if qcore in n or (qc and qc in nc):
        return 2
    if qcore.split() and all(w in n.split() for w in qcore.split()):
        return 3
    if qc and len(qc) >= 4 and difflib.SequenceMatcher(None, qc, nc).ratio() >= 0.86:
        return 4
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd docs/homebrain/mass-resolver && python tests/test_match.py`
Expected: PASS (11 tests OK).

- [ ] **Step 5: Commit**

```bash
git add docs/homebrain/mass-resolver/match.py docs/homebrain/mass-resolver/tests/test_match.py
git commit -m "refactor(homebrain): extract pure text matcher into match.py"
```

---

## Task 3: `config.py` + config data files (load settings + scaffolds)

**Files:**
- Create: `docs/homebrain/mass-resolver/config.py`
- Modify: `docs/homebrain/mass-resolver/config.json` (enrich)
- Create: `docs/homebrain/mass-resolver/radio.json` (scaffold)
- Create: `docs/homebrain/mass-resolver/news.json` (scaffold)
- Test: `docs/homebrain/mass-resolver/tests/test_config.py`

**Interfaces:**
- Produces:
  - `load_json(name, default)` — read a JSON file next to the modules.
  - `Settings` — object with attrs: `ma_host, ma_port, ha_host, ha_port, provider_preference, type_order, queue_id, ceiling_entity, event_type, sync_event_type, dry_run, announce_failures, tts_service, tts_data` (see code).
  - `load_settings(here)` — build `Settings` from `config.json`.
  - `read_secret(here, name)` — read a token file (returns None if missing).
  - `setup_logging(here)` — returns a configured `logging.Logger`.
  - `country_code(radio_cfg, name)` — map a country name to ISO code via `radio.json` aliases (used in Inc 1).
- Consumed by: `maconn` (host/port/token), `haconn` (host/port/token/tts), `core` (event names, announce flags), `music` (provider_preference, type_order, queue_id), `resolver` (everything).

- [ ] **Step 1: Write the failing test**

Create `tests/test_config.py`:

```python
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd docs/homebrain/mass-resolver && python tests/test_config.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'config'`.

- [ ] **Step 3: Write minimal implementation**

Create `config.py`:

```python
#!/usr/bin/env python3
# Config + secrets + logging loading for the resolver. Python 3.5 safe.
import os, sys, json, logging


def load_json(here, name, default):
    try:
        with open(os.path.join(here, name)) as f:
            return json.loads(f.read())
    except Exception:
        return default


def read_secret(here, name):
    try:
        with open(os.path.join(here, name)) as f:
            return f.read().strip()
    except Exception:
        return None


class Settings(object):
    def __init__(self, cfg):
        self.ma_host = cfg.get("ma_host", "192.168.122.10")
        self.ma_port = int(cfg.get("ma_port", 8095))
        ha_url = cfg.get("ha_url", "http://192.168.122.10:8123")
        self.ha_host = ha_url.split("://", 1)[-1].split(":")[0]
        self.ha_port = int(ha_url.rsplit(":", 1)[-1].split("/")[0])
        self.provider_preference = cfg.get("provider_preference", ["filesystem_smb"])
        self.type_order = cfg.get("type_order", ["artist", "album", "track", "playlist"])
        self.queue_id = cfg.get("ceiling_player_id", "upf8b156c25101")
        self.ceiling_entity = cfg.get("ceiling_entity", "media_player.ceiling_speakers")
        self.event_type = cfg.get("event_type", "mass_play_request")
        self.sync_event_type = cfg.get("sync_event_type", "mass_sync_request")
        self.dry_run = bool(cfg.get("dry_run", False))
        self.announce_failures = bool(cfg.get("announce_failures", True))
        # TTS announce service: domain.service + a template of data fields.
        # tts_data placeholders {msg}/{entity} are filled by haconn.announce().
        self.tts_service = cfg.get("tts_service", "")          # e.g. "tts.speak"
        self.tts_data = cfg.get("tts_data", {})               # e.g. {"entity_id":"tts.x","media_player_entity_id":"{entity}","message":"{msg}"}


def load_settings(here):
    return Settings(load_json(here, "config.json", {}))


def country_code(radio_cfg, name):
    codes = (radio_cfg or {}).get("country_codes", {})
    return codes.get((name or "").strip().lower())


def setup_logging(here):
    log = logging.getLogger("resolver")
    if log.handlers:
        return log
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    sh = logging.StreamHandler(sys.stdout); sh.setFormatter(fmt); log.addHandler(sh)
    try:
        fh = logging.FileHandler(os.path.join(here, "resolver.log")); fh.setFormatter(fmt); log.addHandler(fh)
    except Exception:
        pass
    return log
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd docs/homebrain/mass-resolver && python tests/test_config.py`
Expected: PASS (6 tests OK).

- [ ] **Step 5: Enrich `config.json` and add scaffolds**

Replace `config.json` with (adds future event names, announce flags, empty TTS placeholders to be filled in Task 11):

```json
{
  "ma_host": "192.168.122.10",
  "ma_port": 8095,
  "provider_preference": ["filesystem_smb"],
  "ceiling_entity": "media_player.ceiling_speakers",
  "ceiling_player_id": "upf8b156c25101",
  "ha_url": "http://192.168.122.10:8123",
  "event_type": "mass_play_request",
  "sync_event_type": "mass_sync_request",
  "announce_failures": true,
  "tts_service": "",
  "tts_data": {}
}
```

Create `radio.json` (scaffold — data only, unused until Inc 1):

```json
{
  "favorites": {},
  "aliases": {},
  "defaults": {},
  "country_codes": {
    "romania": "ro", "russia": "ru", "russian": "ru",
    "united states": "us", "usa": "us", "america": "us",
    "uk": "gb", "united kingdom": "gb", "england": "gb",
    "france": "fr", "germany": "de", "deutschland": "de",
    "italy": "it", "spain": "es", "ukraine": "ua", "moldova": "md"
  }
}
```

Create `news.json` (scaffold — data only, unused until Inc 2):

```json
{
  "feeds": { "world": [], "romania": [], "russia": [] },
  "stations": {}
}
```

- [ ] **Step 6: Commit**

```bash
git add docs/homebrain/mass-resolver/config.py docs/homebrain/mass-resolver/config.json docs/homebrain/mass-resolver/radio.json docs/homebrain/mass-resolver/news.json docs/homebrain/mass-resolver/tests/test_config.py
git commit -m "refactor(homebrain): add config loader + radio/news data scaffolds"
```

---

## Task 4: `wsutil.py` — raw WebSocket transport (extract + test)

**Files:**
- Create: `docs/homebrain/mass-resolver/wsutil.py`
- Test: `docs/homebrain/mass-resolver/tests/test_wsutil.py`

**Interfaces:**
- Produces: `ws_connect(host, port, path) -> (sock, box)`, `ws_read(sock, box) -> dict|None`, `ws_send(sock, obj) -> None`, plus internal `ws_frame`/`need`/`ws_pong`. `box` is `{"b": bytes}` carrying buffered bytes between reads.
- Consumed by: `maconn.py` (Task 5), `haconn.py` (Task 6).

- [ ] **Step 1: Write the failing test**

Create `tests/test_wsutil.py` (uses a fake socket — no network; verifies framing/masking logic):

```python
#!/usr/bin/env python3
"""Unit tests for raw WebSocket framing. Run: python tests/test_wsutil.py"""
import os, sys, json, struct, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import wsutil


class FakeSock(object):
    """Serves preloaded inbound bytes via recv(); captures outbound via sendall()."""
    def __init__(self, inbound=b""):
        self.inbound = inbound
        self.sent = b""
    def recv(self, n):
        if not self.inbound:
            return b""
        chunk = self.inbound[:n]; self.inbound = self.inbound[n:]; return chunk
    def sendall(self, data):
        self.sent += data


def server_text_frame(obj):
    """Build an UNMASKED server->client text frame (what HA/MA send)."""
    payload = json.dumps(obj).encode()
    ln = len(payload)
    if ln < 126:
        header = bytes(bytearray([0x81, ln]))
    elif ln < 65536:
        header = bytes(bytearray([0x81, 126])) + struct.pack(">H", ln)
    else:
        header = bytes(bytearray([0x81, 127])) + struct.pack(">Q", ln)
    return header + payload


class WsUtilTest(unittest.TestCase):
    def test_read_parses_server_text_frame(self):
        s = FakeSock(server_text_frame({"hello": "world", "n": 7}))
        msg = wsutil.ws_read(s, {"b": b""})
        self.assertEqual(msg, {"hello": "world", "n": 7})

    def test_read_returns_none_on_close_opcode(self):
        s = FakeSock(bytes(bytearray([0x88, 0x00])))  # FIN+close, len 0
        self.assertIsNone(wsutil.ws_read(s, {"b": b""}))

    def test_send_produces_masked_client_frame(self):
        s = FakeSock()
        wsutil.ws_send(s, {"a": 1})
        b = s.sent
        self.assertEqual(b[0], 0x81)          # FIN + text
        self.assertTrue(b[1] & 0x80)          # mask bit set (client frames must be masked)
        ln = b[1] & 0x7f
        mask = b[2:6]; masked = b[6:6 + ln]
        unmasked = bytes(bytearray(x ^ mask[i % 4] for i, x in enumerate(masked)))
        self.assertEqual(json.loads(unmasked.decode()), {"a": 1})


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd docs/homebrain/mass-resolver && python tests/test_wsutil.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'wsutil'`.

- [ ] **Step 3: Write minimal implementation**

Create `wsutil.py` (helpers moved verbatim from baseline `resolver.py` lines 47–98, renamed to public `ws_*`):

```python
#!/usr/bin/env python3
# Raw WebSocket client transport (no external deps). Python 3.5 safe.
import os, socket, base64, struct, json


def ws_connect(host, port, path):
    s = socket.create_connection((host, port), timeout=15)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    k = base64.b64encode(os.urandom(16)).decode()
    s.sendall(("GET %s HTTP/1.1\r\nHost: %s\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n" % (path, host, k)).encode())
    buf = b""
    while b"\r\n\r\n" not in buf:
        buf += s.recv(65536)
    return s, {"b": buf.split(b"\r\n\r\n", 1)[1]}


def need(s, box, n):
    while len(box["b"]) < n:
        chunk = s.recv(65536)
        if not chunk:
            raise IOError("websocket closed (EOF)")
        box["b"] += chunk


def ws_frame(s, box):
    need(s, box, 2)
    b0 = box["b"][0]; op = b0 & 0x0f; ln = box["b"][1] & 0x7f; idx = 2
    if ln == 126:
        need(s, box, 4); ln = struct.unpack(">H", box["b"][2:4])[0]; idx = 4
    elif ln == 127:
        need(s, box, 10); ln = struct.unpack(">Q", box["b"][2:10])[0]; idx = 10
    need(s, box, idx + ln)
    p = box["b"][idx:idx + ln]; box["b"] = box["b"][idx + ln:]
    return (b0 & 0x80), op, p


def ws_pong(s, payload):
    p = payload[:125]; m = os.urandom(4); ln = len(p)
    md = bytes(bytearray(x ^ m[i % 4] for i, x in enumerate(p)))
    s.sendall(b"\x8a" + bytes(bytearray([0x80 | ln])) + m + md)


def ws_read(s, box):
    data = b""
    while True:
        fin, op, p = ws_frame(s, box)
        if op == 8:
            return None          # close
        if op == 9:
            ws_pong(s, p); continue   # ping -> pong (keepalive)
        if op == 10:
            continue            # pong
        data += p
        if fin:
            try:
                return json.loads(data.decode("utf-8"))
            except Exception:
                data = b""


def ws_send(s, obj):
    d = json.dumps(obj).encode(); m = os.urandom(4)
    md = bytes(bytearray(x ^ m[i % 4] for i, x in enumerate(d))); ln = len(d)
    if ln < 126:
        s.sendall(b"\x81" + bytes(bytearray([0x80 | ln])) + m + md)
    elif ln < 65536:
        s.sendall(b"\x81" + bytes(bytearray([0x80 | 126])) + struct.pack(">H", ln) + m + md)
    else:
        s.sendall(b"\x81" + bytes(bytearray([0x80 | 127])) + struct.pack(">Q", ln) + m + md)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd docs/homebrain/mass-resolver && python tests/test_wsutil.py`
Expected: PASS (3 tests OK).

- [ ] **Step 5: Commit**

```bash
git add docs/homebrain/mass-resolver/wsutil.py docs/homebrain/mass-resolver/tests/test_wsutil.py
git commit -m "refactor(homebrain): extract raw WebSocket transport into wsutil.py"
```

---

## Task 5: `maconn.py` — Music Assistant client (extract + test)

**Files:**
- Create: `docs/homebrain/mass-resolver/maconn.py`
- Test: `docs/homebrain/mass-resolver/tests/test_maconn.py`

**Interfaces:**
- Consumes: `wsutil.ws_connect/ws_read/ws_send`.
- Produces: `class MA(host, port, token)` with `connect()`, `cmd(command, **args) -> dict|None`, `library(media_type) -> list`, `play(queue_id, uri, option="replace") -> dict|None`, `sync() -> None`, `close()`. `WS_CMD` dict mapping media types to library commands.
- Consumed by: `music.py` (Task 7), `core.sync_library` (Task 9), `resolver.py` (Task 10).

- [ ] **Step 1: Write the failing test**

Create `tests/test_maconn.py` (subclasses `MA` to stub the wire, tests result extraction):

```python
#!/usr/bin/env python3
"""Unit tests for the MA client result handling. Run: python tests/test_maconn.py"""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from maconn import MA, WS_CMD


class FakeMA(MA):
    """Overrides cmd() so no socket is used; records calls, returns canned replies."""
    def __init__(self, reply):
        MA.__init__(self, "h", 1, "tok")
        self._reply = reply
        self.calls = []
    def cmd(self, command, **args):
        self.calls.append((command, args))
        return self._reply


class MaConnTest(unittest.TestCase):
    def test_ws_cmd_has_all_media_types(self):
        self.assertEqual(set(WS_CMD), {"artist", "album", "track", "playlist"})

    def test_library_extracts_items_from_dict_result(self):
        m = FakeMA({"result": {"items": [{"name": "A"}, {"name": "B"}]}})
        self.assertEqual(m.library("artist"), [{"name": "A"}, {"name": "B"}])
        self.assertEqual(m.calls[0][0], WS_CMD["artist"])

    def test_library_extracts_list_result(self):
        m = FakeMA({"result": [{"name": "X"}]})
        self.assertEqual(m.library("track"), [{"name": "X"}])

    def test_library_handles_empty(self):
        m = FakeMA({"result": None})
        self.assertEqual(m.library("album"), [])

    def test_play_calls_play_media_with_replace(self):
        m = FakeMA({"result": {}})
        m.play("q1", "filesystem_smb--x://track/7")
        cmd, args = m.calls[0]
        self.assertEqual(cmd, "player_queues/play_media")
        self.assertEqual(args["queue_id"], "q1")
        self.assertEqual(args["media"], "filesystem_smb--x://track/7")
        self.assertEqual(args["option"], "replace")


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd docs/homebrain/mass-resolver && python tests/test_maconn.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'maconn'`.

- [ ] **Step 3: Write minimal implementation**

Create `maconn.py` (from baseline `resolver.py` lines 44–45, 100–124; `_cmd`→public `cmd`, add `sync()`):

```python
#!/usr/bin/env python3
# Music Assistant WebSocket client. Python 3.5 safe.
import wsutil

WS_CMD = {"artist": "music/artists/library_items", "album": "music/albums/library_items",
          "track": "music/tracks/library_items", "playlist": "music/playlists/library_items"}


class MA(object):
    def __init__(self, host, port, token):
        self.host = host; self.port = port; self.token = token
        self.s = None; self.box = None; self.mid = 0

    def connect(self):
        self.s, self.box = wsutil.ws_connect(self.host, self.port, "/ws"); self.s.settimeout(60)
        wsutil.ws_read(self.s, self.box)                 # server-info
        self.cmd("auth", token=self.token)

    def cmd(self, command, **args):
        self.mid += 1; mid = str(self.mid)
        wsutil.ws_send(self.s, {"command": command, "message_id": mid, "args": args})
        for _ in range(800):
            m = wsutil.ws_read(self.s, self.box)
            if m is None:
                return None
            if m.get("message_id") == mid:
                return m

    def library(self, media_type):
        r = self.cmd(WS_CMD[media_type], limit=1000)
        res = (r or {}).get("result")
        return res.get("items") if isinstance(res, dict) else (res or [])

    def play(self, queue_id, uri, option="replace"):
        # "replace" => fresh queue each time (immune to stale/contaminated queue state)
        return self.cmd("player_queues/play_media", queue_id=queue_id, media=uri, option=option)

    def sync(self):
        self.cmd("music/sync")

    def close(self):
        try:
            self.s.close()
        except Exception:
            pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd docs/homebrain/mass-resolver && python tests/test_maconn.py`
Expected: PASS (5 tests OK).

- [ ] **Step 5: Commit**

```bash
git add docs/homebrain/mass-resolver/maconn.py docs/homebrain/mass-resolver/tests/test_maconn.py
git commit -m "refactor(homebrain): extract Music Assistant client into maconn.py"
```

---

## Task 6: `haconn.py` — Home Assistant client + announce (TTS)

**Files:**
- Create: `docs/homebrain/mass-resolver/haconn.py`
- Test: `docs/homebrain/mass-resolver/tests/test_haconn.py`

**Interfaces:**
- Consumes: `wsutil`.
- Produces: `class HA(host, port, token)` with `connect()`, `subscribe(event_type, sub_id)`, `read() -> dict|None`, `call_service(domain, service, data) -> None`, `announce(message, settings)`, `close()`. `announce` is the honest failure-feedback speaker: it renders `settings.tts_data` placeholders `{msg}`/`{entity}` and calls the configured `settings.tts_service`; if `tts_service` is empty it logs and no-ops (so the resolver never crashes when TTS isn't configured yet).
- Consumed by: `core.py` (Task 9) for failure feedback; `resolver.py` (Task 10) for the event loop.

- [ ] **Step 1: Write the failing test**

Create `tests/test_haconn.py`:

```python
#!/usr/bin/env python3
"""Unit tests for the HA client service-call/announce composition. Run: python tests/test_haconn.py"""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import haconn


class FakeSettings(object):
    def __init__(self, tts_service="", tts_data=None, ceiling_entity="media_player.ceiling_speakers"):
        self.tts_service = tts_service
        self.tts_data = tts_data or {}
        self.ceiling_entity = ceiling_entity


class HaConnTest(unittest.TestCase):
    def _ha(self):
        h = haconn.HA("host", 1, "tok")
        h.sent = []
        h.call_service = lambda domain, service, data: h.sent.append((domain, service, data))
        return h

    def test_call_service_split_used_by_announce(self):
        h = self._ha()
        s = FakeSettings(tts_service="tts.speak",
                         tts_data={"entity_id": "tts.home", "media_player_entity_id": "{entity}", "message": "{msg}"})
        h.announce("Couldn't find Engel locally.", s)
        self.assertEqual(len(h.sent), 1)
        domain, service, data = h.sent[0]
        self.assertEqual(domain, "tts")
        self.assertEqual(service, "speak")
        self.assertEqual(data["message"], "Couldn't find Engel locally.")
        self.assertEqual(data["media_player_entity_id"], "media_player.ceiling_speakers")
        self.assertEqual(data["entity_id"], "tts.home")

    def test_announce_noops_when_no_tts_service(self):
        h = self._ha()
        h.announce("anything", FakeSettings(tts_service=""))
        self.assertEqual(h.sent, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd docs/homebrain/mass-resolver && python tests/test_haconn.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'haconn'`.

- [ ] **Step 3: Write minimal implementation**

Create `haconn.py` (HA connect/auth from baseline `resolver.py` lines 219–227; `call_service`/`announce` are new):

```python
#!/usr/bin/env python3
# Home Assistant WebSocket client + TTS announce (honest failure feedback). Python 3.5 safe.
import logging
import wsutil

LOG = logging.getLogger("resolver")


class HA(object):
    def __init__(self, host, port, token):
        self.host = host; self.port = port; self.token = token
        self.s = None; self.box = None; self.cmd_id = 100

    def connect(self):
        self.s, self.box = wsutil.ws_connect(self.host, self.port, "/api/websocket"); self.s.settimeout(None)
        hello = wsutil.ws_read(self.s, self.box)
        if (hello or {}).get("type") != "auth_required":
            raise RuntimeError("unexpected HA hello: %r" % hello)
        wsutil.ws_send(self.s, {"type": "auth", "access_token": self.token})
        if (wsutil.ws_read(self.s, self.box) or {}).get("type") != "auth_ok":
            raise RuntimeError("HA auth failed")

    def subscribe(self, event_type, sub_id):
        wsutil.ws_send(self.s, {"id": sub_id, "type": "subscribe_events", "event_type": event_type})
        self.read()

    def read(self):
        return wsutil.ws_read(self.s, self.box)

    def call_service(self, domain, service, data):
        self.cmd_id += 1
        wsutil.ws_send(self.s, {"id": self.cmd_id, "type": "call_service",
                                "domain": domain, "service": service, "service_data": data})

    def announce(self, message, settings):
        svc = (settings.tts_service or "").strip()
        if not svc or "." not in svc:
            LOG.info("ANNOUNCE (no tts_service configured): %s", message)
            return
        domain, service = svc.split(".", 1)
        data = {}
        for k, v in (settings.tts_data or {}).items():
            if isinstance(v, str):
                data[k] = v.replace("{msg}", message).replace("{entity}", settings.ceiling_entity)
            else:
                data[k] = v
        try:
            self.call_service(domain, service, data)
            LOG.info("ANNOUNCE via %s: %s", svc, message)
        except Exception as e:
            LOG.error("ANNOUNCE failed (%r): %s", e, message)

    def close(self):
        try:
            self.s.close()
        except Exception:
            pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd docs/homebrain/mass-resolver && python tests/test_haconn.py`
Expected: PASS (2 tests OK).

- [ ] **Step 5: Commit**

```bash
git add docs/homebrain/mass-resolver/haconn.py docs/homebrain/mass-resolver/tests/test_haconn.py
git commit -m "refactor(homebrain): add HA client with TTS announce (failure feedback)"
```

---

## Task 7: `music.py` — `resolve_music` capability (extract + test)

**Files:**
- Create: `docs/homebrain/mass-resolver/music.py`
- Test: `docs/homebrain/mass-resolver/tests/test_music.py`

**Interfaces:**
- Consumes: `match.match_rank`, `maconn.MA` / `WS_CMD`.
- Produces: `resolve_music(ma, query, media_type, settings, rid) -> result dict` (per the capability contract). On success: `ok=True, played=True, uri, provider, candidate, media_type, intent="music"`. On no local match: `ok=False, spoken="Sorry, I couldn't find <query> in the local library.", reason="no local match"`. On MA play error: `ok=False, spoken="I found <candidate>, but couldn't start playback.", reason="play failed"`. Honors `settings.dry_run` (no `play`, `played=False`, `ok=True`).
- Consumed by: `core.dispatch` (Task 9).

- [ ] **Step 1: Write the failing test**

Create `tests/test_music.py`:

```python
#!/usr/bin/env python3
"""Unit tests for resolve_music. Run: python tests/test_music.py"""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import music


class FakeSettings(object):
    provider_preference = ["filesystem_smb"]
    type_order = ["artist", "album", "track", "playlist"]
    queue_id = "q1"
    dry_run = False


class FakeMA(object):
    """library() returns canned items per type; play() records and returns a reply."""
    def __init__(self, libs, play_reply=None):
        self.libs = libs = libs = None  # placeholder, set below
        self.libs = libs
        self._libs = libs
        self.play_reply = play_reply or {"result": {}}
        self.played = []
        self._data = {}
    def set(self, data):
        self._data = data; return self
    def library(self, media_type):
        return self._data.get(media_type, [])
    def play(self, queue_id, uri, option="replace"):
        self.played.append((queue_id, uri, option)); return self.play_reply


def smb_item(name, item_id):
    return {"name": name, "provider_mappings": [
        {"provider_domain": "filesystem_smb", "provider_instance": "filesystem_smb--kd66vco4",
         "available": True, "item_id": item_id}]}


def ytm_item(name, item_id):
    return {"name": name, "uri": "ytmusic://x/" + item_id, "provider_mappings": [
        {"provider_domain": "ytmusic", "provider_instance": "ytmusic--7MLPoF6b",
         "available": True, "item_id": item_id}]}


class MusicTest(unittest.TestCase):
    def test_plays_local_artist_match(self):
        ma = FakeMA(None).set({"artist": [smb_item("Rammstein", "42")]})
        r = music.resolve_music(ma, "Rammstein", "artist", FakeSettings(), "rid1")
        self.assertTrue(r["ok"])
        self.assertTrue(r["played"])
        self.assertEqual(r["provider"], "filesystem_smb")
        self.assertEqual(r["uri"], "filesystem_smb--kd66vco4://artist/42")
        self.assertEqual(ma.played[0][1], r["uri"])

    def test_rejects_non_preferred_provider(self):
        ma = FakeMA(None).set({"artist": [ytm_item("Rammstein", "9")],
                               "album": [], "track": [], "playlist": []})
        r = music.resolve_music(ma, "Rammstein", "artist", FakeSettings(), "rid2")
        self.assertFalse(r["ok"])
        self.assertEqual(r["reason"], "no local match")
        self.assertIn("couldn't find", r["spoken"].lower())
        self.assertEqual(ma.played, [])

    def test_falls_back_to_other_types_when_hint_wrong(self):
        ma = FakeMA(None).set({"artist": [], "album": [], "track": [smb_item("Du Hast", "7")], "playlist": []})
        r = music.resolve_music(ma, "Du Hast", "artist", FakeSettings(), "rid3")
        self.assertTrue(r["ok"])
        self.assertEqual(r["media_type"], "track")

    def test_dry_run_does_not_play(self):
        s = FakeSettings(); s.dry_run = True
        ma = FakeMA(None).set({"artist": [smb_item("Rammstein", "42")]})
        r = music.resolve_music(ma, "Rammstein", "artist", s, "rid4")
        self.assertTrue(r["ok"])
        self.assertFalse(r["played"])
        self.assertEqual(ma.played, [])

    def test_play_error_reports_honest_failure(self):
        ma = FakeMA(None, play_reply={"error_code": "x", "details": "boom"}).set(
            {"artist": [smb_item("Rammstein", "42")]})
        r = music.resolve_music(ma, "Rammstein", "artist", FakeSettings(), "rid5")
        self.assertFalse(r["ok"])
        self.assertEqual(r["reason"], "play failed")
        self.assertIn("couldn't start", r["spoken"].lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd docs/homebrain/mass-resolver && python tests/test_music.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'music'`.

- [ ] **Step 3: Write minimal implementation**

Create `music.py` (logic from baseline `resolver.py` lines 143–200, restructured to return the contract dict; the dispatcher owns connect/close):

```python
#!/usr/bin/env python3
# Music capability: resolve a query to a local (preferred-provider) item and play it. Python 3.5 safe.
import logging
from match import match_rank
from maconn import WS_CMD

LOG = logging.getLogger("resolver")


def _resolve_type(ma, query, media_type, settings, rid):
    ranked = []
    for it in ma.library(media_type):
        r = match_rank(query, it.get("name"))
        if r is not None:
            ranked.append((r, it))
    ranked.sort(key=lambda t: t[0])
    for _, it in ranked:
        name = it.get("name"); maps = it.get("provider_mappings") or []
        local = None
        for m in maps:
            if m.get("provider_domain") in settings.provider_preference and m.get("available"):
                local = m; break
        if local:
            uri = "%s://%s/%s" % (local.get("provider_instance"), media_type, local.get("item_id"))
            LOG.info("req=%s query=%r media_type=%s candidate=%r provider=%s uri=%s decision=ACCEPTED",
                     rid, query, media_type, name, local.get("provider_domain"), uri)
            return {"uri": uri, "provider": local.get("provider_domain"), "candidate": name, "media_type": media_type}
        LOG.info("req=%s query=%r media_type=%s candidate=%r decision=REJECTED reason=no-preferred-mapping",
                 rid, query, media_type, name)
    return None


def resolve_music(ma, query, media_type, settings, rid):
    if media_type in WS_CMD:
        types = [media_type] + [t for t in settings.type_order if t != media_type]
    else:
        types = list(settings.type_order)
    hit = None
    for mt in types:
        hit = _resolve_type(ma, query, mt, settings, rid)
        if hit:
            break
    if not hit:
        LOG.info("req=%s query=%r decision=REJECTED reason=no-local-match", rid, query)
        return {"ok": False, "intent": "music", "request_id": rid, "reason": "no local match",
                "spoken": "Sorry, I couldn't find " + (query or "that") + " in the local library."}
    res = {"ok": True, "intent": "music", "request_id": rid, "spoken": None, "played": False}
    res.update(hit)
    if settings.dry_run:
        LOG.info("[DRY-RUN] req=%s WOULD PLAY %s (provider=%s)", rid, hit["uri"], hit["provider"])
        return res
    pr = ma.play(settings.queue_id, hit["uri"])
    if pr and "error_code" in pr:
        LOG.error("req=%s PLAY FAILED code=%s details=%s", rid, pr.get("error_code"), pr.get("details"))
        res["ok"] = False; res["reason"] = "play failed"
        res["spoken"] = "I found " + hit["candidate"] + ", but couldn't start playback."
        return res
    LOG.info("req=%s PLAYING %s (provider=%s)", rid, hit["uri"], hit["provider"])
    res["played"] = True
    return res
```

> Note on `test_music.py`: the `FakeMA.__init__` placeholder lines are intentionally simple; only `set()`, `library()`, and `play()` are exercised. The implementer may simplify `FakeMA.__init__` to `self.play_reply = play_reply or {"result": {}}; self.played = []; self._data = {}` — keep the three methods as shown.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd docs/homebrain/mass-resolver && python tests/test_music.py`
Expected: PASS (5 tests OK).

- [ ] **Step 5: Commit**

```bash
git add docs/homebrain/mass-resolver/music.py docs/homebrain/mass-resolver/tests/test_music.py
git commit -m "refactor(homebrain): extract music capability into music.py"
```

---

## Task 8: Stub capabilities — `radio.py`, `news.py`, `acquire.py`, `status.py`

**Files:**
- Create: `docs/homebrain/mass-resolver/radio.py`, `news.py`, `acquire.py`, `status.py`
- Test: `docs/homebrain/mass-resolver/tests/test_stubs.py`

**Interfaces:**
- Produces honest not-implemented capabilities returning the contract dict with `ok=False, not_implemented=True, spoken="<Capability> isn't available yet."`:
  - `radio.resolve_radio(ctx, params, rid)`
  - `news.get_news(ctx, params, rid)`
  - `acquire.acquire(ctx, params, rid)`
  - `status.status(ctx, params, rid)`
- `ctx` is a small holder the dispatcher passes (so future increments get `ma`, `ha`, `settings`, config dicts without signature churn). Inc 0 stubs ignore it.
- Consumed by: `core.dispatch` (Task 9). These are NOT wired to any HA event in Inc 0 (no ChatGPT exposure).

- [ ] **Step 1: Write the failing test**

Create `tests/test_stubs.py`:

```python
#!/usr/bin/env python3
"""Contract tests for not-yet-implemented capabilities. Run: python tests/test_stubs.py"""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import radio, news, acquire, status


class StubTest(unittest.TestCase):
    def _check(self, fn, intent):
        r = fn(None, {}, "rid")
        self.assertFalse(r["ok"])
        self.assertTrue(r["not_implemented"])
        self.assertEqual(r["intent"], intent)
        self.assertIn("yet", r["spoken"].lower())
        self.assertEqual(r["request_id"], "rid")

    def test_radio_stub(self):
        self._check(radio.resolve_radio, "radio")

    def test_news_stub(self):
        self._check(news.get_news, "news")

    def test_acquire_stub(self):
        self._check(acquire.acquire, "acquire")

    def test_status_stub(self):
        self._check(status.status, "status")


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd docs/homebrain/mass-resolver && python tests/test_stubs.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'radio'`.

- [ ] **Step 3: Write minimal implementations**

Create `radio.py`:

```python
#!/usr/bin/env python3
# Radio capability — STUB (full implementation lands in Inc 1). Python 3.5 safe.
def resolve_radio(ctx, params, rid):
    return {"ok": False, "intent": "radio", "request_id": rid, "not_implemented": True,
            "reason": "stub", "spoken": "Radio control through the assistant isn't available yet."}
```

Create `news.py`:

```python
#!/usr/bin/env python3
# News capability — STUB (full implementation lands in Inc 2). Python 3.5 safe.
def get_news(ctx, params, rid):
    return {"ok": False, "intent": "news", "request_id": rid, "not_implemented": True,
            "reason": "stub", "spoken": "News isn't available yet."}
```

Create `acquire.py`:

```python
#!/usr/bin/env python3
# Acquisition capability — STUB (full implementation lands in Inc 3). Python 3.5 safe.
def acquire(ctx, params, rid):
    return {"ok": False, "intent": "acquire", "request_id": rid, "not_implemented": True,
            "reason": "stub", "spoken": "Music acquisition isn't available yet."}
```

Create `status.py`:

```python
#!/usr/bin/env python3
# Status capability — STUB (full implementation lands in Inc 4). Python 3.5 safe.
def status(ctx, params, rid):
    return {"ok": False, "intent": "status", "request_id": rid, "not_implemented": True,
            "reason": "stub", "spoken": "Now-playing status isn't available yet."}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd docs/homebrain/mass-resolver && python tests/test_stubs.py`
Expected: PASS (4 tests OK).

- [ ] **Step 5: Commit**

```bash
git add docs/homebrain/mass-resolver/radio.py docs/homebrain/mass-resolver/news.py docs/homebrain/mass-resolver/acquire.py docs/homebrain/mass-resolver/status.py docs/homebrain/mass-resolver/tests/test_stubs.py
git commit -m "feat(homebrain): add stub radio/news/acquire/status capabilities"
```

---

## Task 9: `core.py` — dispatch registry + failure feedback + sync

**Files:**
- Create: `docs/homebrain/mass-resolver/core.py`
- Test: `docs/homebrain/mass-resolver/tests/test_core.py`

**Interfaces:**
- Consumes: `maconn.MA`, `haconn.HA`, `music.resolve_music`, the stub capabilities, `config` dicts.
- Produces:
  - `class Ctx` — holder with `ma_factory`, `ha`, `settings`, `radio_cfg`, `news_cfg`.
  - `dispatch(ctx, intent, params, rid=None) -> result` — looks up the capability by intent, runs it (opening/closing a fresh MA connection for intents that need it), and on `not result["ok"]` with a `spoken` line and `settings.announce_failures`, calls `ctx.ha.announce(spoken, settings)`. `intent="sync"` runs `sync_library` and never announces.
  - `sync_library(ctx, rid) -> result` — opens MA, calls `ma.sync()`, returns `{"ok": True, "intent": "sync", ...}`.
  - `INTENTS` — dict mapping intent name to a callable.
- Consumed by: `resolver.py` (Task 10).

- [ ] **Step 1: Write the failing test**

Create `tests/test_core.py`:

```python
#!/usr/bin/env python3
"""Unit tests for the dispatcher + failure feedback. Run: python tests/test_core.py"""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import core


class FakeSettings(object):
    provider_preference = ["filesystem_smb"]
    type_order = ["artist", "album", "track", "playlist"]
    queue_id = "q1"
    dry_run = False
    announce_failures = True
    ceiling_entity = "media_player.ceiling_speakers"
    tts_service = "tts.speak"
    tts_data = {}


class FakeHA(object):
    def __init__(self):
        self.announced = []
    def announce(self, message, settings):
        self.announced.append(message)


class FakeMA(object):
    def __init__(self, data=None, sync_ok=True):
        self._data = data or {}
        self.synced = False
    def connect(self):
        pass
    def library(self, mt):
        return self._data.get(mt, [])
    def play(self, q, uri, option="replace"):
        return {"result": {}}
    def sync(self):
        self.synced = True
    def close(self):
        pass


def smb_item(name, item_id):
    return {"name": name, "provider_mappings": [
        {"provider_domain": "filesystem_smb", "provider_instance": "fs--x",
         "available": True, "item_id": item_id}]}


class CoreTest(unittest.TestCase):
    def _ctx(self, ma):
        ha = FakeHA()
        ctx = core.Ctx(ma_factory=lambda: ma, ha=ha, settings=FakeSettings(),
                       radio_cfg={}, news_cfg={})
        return ctx, ha

    def test_music_success_does_not_announce(self):
        ctx, ha = self._ctx(FakeMA({"artist": [smb_item("Rammstein", "1")]}))
        r = core.dispatch(ctx, "music", {"query": "Rammstein", "media_type": "artist"})
        self.assertTrue(r["ok"])
        self.assertEqual(ha.announced, [])

    def test_music_failure_announces_honest_line(self):
        ctx, ha = self._ctx(FakeMA({"artist": [], "album": [], "track": [], "playlist": []}))
        r = core.dispatch(ctx, "music", {"query": "Nonexistent"})
        self.assertFalse(r["ok"])
        self.assertEqual(len(ha.announced), 1)
        self.assertIn("couldn't find", ha.announced[0].lower())

    def test_stub_intent_announces_not_available(self):
        ctx, ha = self._ctx(FakeMA())
        r = core.dispatch(ctx, "radio", {"country": "Romania"})
        self.assertFalse(r["ok"])
        self.assertEqual(len(ha.announced), 1)
        self.assertIn("yet", ha.announced[0].lower())

    def test_sync_runs_and_never_announces(self):
        ma = FakeMA()
        ctx, ha = self._ctx(ma)
        r = core.dispatch(ctx, "sync", {"source": "lidarr"})
        self.assertTrue(r["ok"])
        self.assertTrue(ma.synced)
        self.assertEqual(ha.announced, [])

    def test_unknown_intent_is_safe(self):
        ctx, ha = self._ctx(FakeMA())
        r = core.dispatch(ctx, "teleport", {})
        self.assertFalse(r["ok"])
        self.assertEqual(r["reason"], "unknown intent")

    def test_announce_suppressed_when_flag_off(self):
        ma = FakeMA({"artist": [], "album": [], "track": [], "playlist": []})
        ctx, ha = self._ctx(ma)
        ctx.settings.announce_failures = False
        core.dispatch(ctx, "music", {"query": "Nope"})
        self.assertEqual(ha.announced, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd docs/homebrain/mass-resolver && python tests/test_core.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'core'`.

- [ ] **Step 3: Write minimal implementation**

Create `core.py`:

```python
#!/usr/bin/env python3
# Dispatch registry + honest failure feedback. Python 3.5 safe.
import logging, uuid
import music, radio, news, acquire, status

LOG = logging.getLogger("resolver")


class Ctx(object):
    def __init__(self, ma_factory, ha, settings, radio_cfg, news_cfg):
        self.ma_factory = ma_factory      # callable -> a fresh MA (already constructed)
        self.ha = ha
        self.settings = settings
        self.radio_cfg = radio_cfg
        self.news_cfg = news_cfg


def _run_music(ctx, params, rid):
    ma = ctx.ma_factory()
    try:
        ma.connect()
        return music.resolve_music(ma, params.get("query"), params.get("media_type") or "",
                                   ctx.settings, rid)
    finally:
        ma.close()


def sync_library(ctx, rid):
    ma = ctx.ma_factory()
    try:
        ma.connect()
        ma.sync()
        LOG.info("SYNC: req=%s music/sync triggered", rid)
        return {"ok": True, "intent": "sync", "request_id": rid, "spoken": None}
    finally:
        ma.close()


# intent -> callable(ctx, params, rid). Stubs share the (ctx, params, rid) signature.
INTENTS = {
    "music": _run_music,
    "radio": radio.resolve_radio,
    "news": news.get_news,
    "acquire": acquire.acquire,
    "status": status.status,
}


def dispatch(ctx, intent, params, rid=None):
    rid = rid or uuid.uuid4().hex[:8]
    if intent == "sync":
        return sync_library(ctx, rid)
    fn = INTENTS.get(intent)
    if fn is None:
        LOG.error("req=%s unknown intent %r", rid, intent)
        return {"ok": False, "intent": intent, "request_id": rid, "reason": "unknown intent",
                "spoken": None}
    try:
        result = fn(ctx, params, rid)
    except Exception as e:
        LOG.error("req=%s intent=%s error: %r", rid, intent, e)
        result = {"ok": False, "intent": intent, "request_id": rid, "reason": "error",
                  "spoken": "Sorry, something went wrong."}
    if (not result.get("ok")) and result.get("spoken") and ctx.settings.announce_failures:
        ctx.ha.announce(result["spoken"], ctx.settings)
    return result
```

> Note: `_run_music` adapts the `(ctx, params, rid)` dispatcher signature to `resolve_music(ma, query, media_type, settings, rid)` and owns the MA connection lifecycle. Stub capabilities already use `(ctx, params, rid)` directly.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd docs/homebrain/mass-resolver && python tests/test_core.py`
Expected: PASS (6 tests OK).

- [ ] **Step 5: Commit**

```bash
git add docs/homebrain/mass-resolver/core.py docs/homebrain/mass-resolver/tests/test_core.py
git commit -m "feat(homebrain): add dispatch registry with honest failure feedback"
```

---

## Task 10: `resolver.py` — thin entrypoint + serve event loop (rewrite)

**Files:**
- Modify (rewrite): `docs/homebrain/mass-resolver/resolver.py`
- Test: `docs/homebrain/mass-resolver/tests/test_resolver.py`

**Interfaces:**
- Consumes: `config`, `maconn.MA`, `haconn.HA`, `core.Ctx` / `core.dispatch`.
- Produces: `build_ctx(here) -> Ctx`; `event_to_call(settings, event) -> (intent, params) | None` (pure mapping from an HA event dict to a dispatch call); `serve(here)`; `main()`. CLI preserved exactly: `--serve`, `--dry-run`, `--query`, `--media-type {"",artist,album,track,playlist}`.
- This file replaces the monolith. `resolver.py.orig` (host) and git `2e2bec7` remain the fallback.

- [ ] **Step 1: Write the failing test**

Create `tests/test_resolver.py` (tests the pure event→call mapping; serve/main are integration-validated in Task 11):

```python
#!/usr/bin/env python3
"""Unit tests for the HA-event -> dispatch mapping. Run: python tests/test_resolver.py"""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import resolver


class FakeSettings(object):
    event_type = "mass_play_request"
    sync_event_type = "mass_sync_request"


class EventMapTest(unittest.TestCase):
    def test_play_event_maps_to_music_intent(self):
        ev = {"event_type": "mass_play_request", "data": {"query": "Engel", "media_type": "track"}}
        call = resolver.event_to_call(FakeSettings(), ev)
        self.assertEqual(call, ("music", {"query": "Engel", "media_type": "track"}))

    def test_play_event_without_media_type_defaults_empty(self):
        ev = {"event_type": "mass_play_request", "data": {"query": "Engel"}}
        intent, params = resolver.event_to_call(FakeSettings(), ev)
        self.assertEqual(intent, "music")
        self.assertEqual(params["media_type"], "")

    def test_play_event_without_query_is_ignored(self):
        ev = {"event_type": "mass_play_request", "data": {}}
        self.assertIsNone(resolver.event_to_call(FakeSettings(), ev))

    def test_sync_event_maps_to_sync_intent(self):
        ev = {"event_type": "mass_sync_request", "data": {"source": "lidarr"}}
        self.assertEqual(resolver.event_to_call(FakeSettings(), ev), ("sync", {"source": "lidarr"}))

    def test_unknown_event_returns_none(self):
        ev = {"event_type": "something_else", "data": {}}
        self.assertIsNone(resolver.event_to_call(FakeSettings(), ev))


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd docs/homebrain/mass-resolver && python tests/test_resolver.py`
Expected: FAIL — `AttributeError: module 'resolver' has no attribute 'event_to_call'` (the old monolith is still present).

- [ ] **Step 3: Write the new implementation**

Replace `resolver.py` entirely with:

```python
#!/usr/bin/env python3
# Music Assistant provider-aware resolver -- thin entrypoint + HA event adapter.
# Runs on the homebrain HOST. Python 3.5 compatible (no f-strings).
#
# Capability modules: music (live), radio/news/acquire/status (stubs). Dispatch + honest
# failure feedback in core. Transport in wsutil; MA in maconn; HA in haconn; config in config.
#
# Secrets (0600, NEVER logged): ~/mass-resolver/.ma_token  ~/mass-resolver/.ha_token
#
# Modes:
#   python3 resolver.py --dry-run --query "Du Hast" --media-type track
#   python3 resolver.py --query "Rammstein" --media-type artist
#   python3 resolver.py --serve
import os, sys, json, argparse, logging, uuid, time
import config
from maconn import MA
from haconn import HA
import core

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = logging.getLogger("resolver")


def build_ctx(here):
    settings = config.load_settings(here)
    ma_token = config.read_secret(here, ".ma_token")
    radio_cfg = config.load_json(here, "radio.json", {})
    news_cfg = config.load_json(here, "news.json", {})
    ha = HA(settings.ha_host, settings.ha_port, config.read_secret(here, ".ha_token"))

    def ma_factory():
        return MA(settings.ma_host, settings.ma_port, ma_token)

    ctx = core.Ctx(ma_factory=ma_factory, ha=ha, settings=settings,
                   radio_cfg=radio_cfg, news_cfg=news_cfg)
    return ctx


def event_to_call(settings, event):
    """Pure mapping: HA event dict -> (intent, params) or None."""
    et = event.get("event_type"); data = event.get("data") or {}
    if et == settings.event_type:
        q = data.get("query")
        if not q:
            return None
        return ("music", {"query": q, "media_type": data.get("media_type") or ""})
    if et == settings.sync_event_type:
        return ("sync", {"source": data.get("source")})
    return None


def serve(here):
    ctx = build_ctx(here)
    if not ctx.ha.token:
        LOG.error("no HA token (~/mass-resolver/.ha_token)"); sys.exit(2)
    s = ctx.settings
    backoff = 2
    while True:
        try:
            ctx.ha.connect()
            ctx.ha.subscribe(s.event_type, 1)
            ctx.ha.subscribe(s.sync_event_type, 2)
            LOG.info("SERVICE: connected; subscribed to %r (play) + %r (sync); provider_preference=%s",
                     s.event_type, s.sync_event_type, s.provider_preference)
            backoff = 2
            while True:
                m = ctx.ha.read()
                if m is None:
                    raise RuntimeError("HA connection closed")
                if m.get("type") != "event":
                    continue
                ev = m.get("event") or {}
                call = event_to_call(s, ev)
                if not call:
                    continue
                intent, params = call
                LOG.info("SERVICE: event=%s -> intent=%s params=%r", ev.get("event_type"), intent, params)
                try:
                    core.dispatch(ctx, intent, params)
                except Exception as e:
                    LOG.error("SERVICE: dispatch error: %r", e)
        except Exception as e:
            LOG.error("SERVICE: connection error: %r; reconnecting in %ss", e, backoff)
            try:
                ctx.ha.close()
            except Exception:
                pass
            time.sleep(backoff); backoff = min(backoff * 2, 60)


def main():
    config.setup_logging(HERE)
    ap = argparse.ArgumentParser()
    ap.add_argument("--serve", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--query")
    ap.add_argument("--media-type", default="", choices=["", "artist", "album", "track", "playlist"])
    a = ap.parse_args()

    if a.serve:
        serve(HERE); return

    ctx = build_ctx(HERE)
    if not ctx.settings.__dict__.get("_ma_token_present", True):
        pass
    ma_token = config.read_secret(HERE, ".ma_token")
    if not ma_token:
        LOG.error("no MA token (~/mass-resolver/.ma_token)"); sys.exit(2)
    if not a.query:
        LOG.error("--query required (or use --serve)"); sys.exit(2)
    if a.dry_run:
        ctx.settings.dry_run = True
    rid = uuid.uuid4().hex[:8]
    ma = ctx.ma_factory()
    try:
        ma.connect()
        import music
        res = music.resolve_music(ma, a.query, a.media_type, ctx.settings, rid)
    finally:
        ma.close()
    # honest feedback also on the one-shot path (when announce configured)
    if (not res.get("ok")) and res.get("spoken") and ctx.settings.announce_failures:
        try:
            ctx.ha.connect(); ctx.ha.announce(res["spoken"], ctx.settings); ctx.ha.close()
        except Exception as e:
            LOG.error("one-shot announce failed: %r", e)
    print(json.dumps(res))


if __name__ == "__main__":
    main()
```

> Cleanup note for the implementer: delete the dead `if not ctx.settings.__dict__.get(...)` two lines — they are a leftover; the real MA-token guard is the `if not ma_token` check that follows. (Kept visible here only to flag the removal explicitly.)

Remove the dead lines so `main()` reads:

```python
    ctx = build_ctx(HERE)
    ma_token = config.read_secret(HERE, ".ma_token")
    if not ma_token:
        LOG.error("no MA token (~/mass-resolver/.ma_token)"); sys.exit(2)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd docs/homebrain/mass-resolver && python tests/test_resolver.py`
Expected: PASS (5 tests OK).

- [ ] **Step 5: Run the whole suite**

Run: `cd docs/homebrain/mass-resolver && for t in tests/test_*.py; do python "$t" || exit 1; done`
Expected: every file reports OK.

- [ ] **Step 6: Commit**

```bash
git add docs/homebrain/mass-resolver/resolver.py docs/homebrain/mass-resolver/tests/test_resolver.py
git commit -m "refactor(homebrain): rewrite resolver.py as thin entrypoint over modules"
```

---

## Task 11: Deploy, discover TTS, integration-validate, update docs

**Files:**
- Deploy to host: all modules + config files to `~costea/mass-resolver/`
- Modify: `docs/homebrain/mass-resolver/config.json` (fill `tts_service`/`tts_data` from discovery)
- Modify: `docs/homebrain/local-music-architecture.md` (record modular architecture + failure feedback)
- Modify: `docs/homebrain/2026-06-27-assistant-tooling-design.md` (mark Inc 0 done)

**Interfaces:**
- Consumes: everything above. Produces: a validated live modular resolver and updated docs.

- [ ] **Step 1: Deploy module + config files to the host (keep `resolver.py.orig`)**

```bash
ssh-add ~/.ssh/id_homebrain
cd docs/homebrain/mass-resolver
for f in wsutil.py match.py config.py maconn.py haconn.py music.py radio.py news.py acquire.py status.py core.py resolver.py config.json radio.json news.json; do
  cat "$f" | ssh costea@192.168.1.68 "cat > ~/mass-resolver/$f"
done
ssh costea@192.168.1.68 'cd ~/mass-resolver && python3 -c "import ast; [ast.parse(open(f).read()) for f in __import__(\"glob\").glob(\"*.py\")]; print(\"PY OK\")"'
```
Expected: `PY OK` (every module parses under the host's Python 3).

- [ ] **Step 2: Dry-run on the host (proves provider filtering, no audio)**

```bash
ssh costea@192.168.1.68 'cd ~/mass-resolver && python3 resolver.py --dry-run --query "Rammstein" --media-type artist'
```
Expected: JSON with `"ok": true`, `"provider": "filesystem_smb"`, `"played": false`, and a `filesystem_smb--...://artist/...` URI.

- [ ] **Step 3: One-shot real play of a known-local track (confirm audio on ceiling)**

```bash
ssh costea@192.168.1.68 'cd ~/mass-resolver && python3 resolver.py --query "Du Hast" --media-type track'
```
Expected: JSON `"ok": true, "played": true`; audio starts on the ceiling speakers. (Ask the user to confirm they hear it.)

- [ ] **Step 4: Discover the available TTS service and set config**

```bash
ssh costea@192.168.1.68 'cd ~/mass-resolver && python3 - <<PYEOF
import json, urllib.request
tok=open(".ha_token").read().strip()
base="http://192.168.122.10:8123"
req=urllib.request.Request(base+"/api/states", headers={"Authorization":"Bearer "+tok})
states=json.loads(urllib.request.urlopen(req,timeout=15).read())
tts=[s["entity_id"] for s in states if s["entity_id"].startswith("tts.")]
print("tts entities:", tts)
PYEOF'
```
Expected: a list like `['tts.google_translate_en_com']` (or similar). Record the first usable entity.

Then set `tts_service`/`tts_data` in the repo `config.json` using the discovered entity, e.g.:

```json
  "tts_service": "tts.speak",
  "tts_data": { "entity_id": "tts.google_translate_en_com", "media_player_entity_id": "{entity}", "message": "{msg}" }
```

Redeploy just the config: `cat config.json | ssh costea@192.168.1.68 "cat > ~/mass-resolver/config.json"`

> If no `tts.*` entity exists, leave `tts_service` empty — `announce()` then logs the honest line instead of speaking (no crash), and TTS wiring becomes a small Inc 1 follow-up. Note this outcome in the docs (Step 8).

- [ ] **Step 5: Validate honest failure feedback (no-match announces the truth)**

```bash
ssh costea@192.168.1.68 'cd ~/mass-resolver && python3 resolver.py --query "zzzznotarealsong"'
```
Expected: JSON `"ok": false, "reason": "no local match"`; if TTS configured, the ceiling speaker says "Sorry, I couldn't find zzzznotarealsong in the local library." Otherwise the log shows `ANNOUNCE (no tts_service configured): ...`.

- [ ] **Step 6: Swap the service to the modular resolver (user action)**

Ask the user to run (no passwordless sudo):

```
sudo systemctl restart mass-resolver
sudo systemctl status mass-resolver --no-pager | head -20
```
Expected: `active (running)`. Then check the log:

```bash
ssh costea@192.168.1.68 'tail -5 ~/mass-resolver/resolver.log'
```
Expected: `SERVICE: connected; subscribed to 'mass_play_request' (play) + 'mass_sync_request' (sync)`.

- [ ] **Step 7: End-to-end event validation (play + sync + failure)**

Fire the play event via HA REST (run from the host so it reaches HA at 192.168.122.10):

```bash
ssh costea@192.168.1.68 'cd ~/mass-resolver && python3 - <<PYEOF
import json, urllib.request
tok=open(".ha_token").read().strip()
base="http://192.168.122.10:8123"
def fire(ev, data):
    req=urllib.request.Request(base+"/api/events/"+ev, data=json.dumps(data).encode(),
        headers={"Authorization":"Bearer "+tok,"Content-Type":"application/json"}, method="POST")
    print(ev, "->", urllib.request.urlopen(req,timeout=15).status)
fire("mass_play_request", {"query":"Rammstein","media_type":"artist"})
fire("mass_sync_request", {"source":"manual-test"})
fire("mass_play_request", {"query":"zzzznotarealsong","media_type":""})
PYEOF'
sleep 3
ssh costea@192.168.1.68 'tail -15 ~/mass-resolver/resolver.log'
```
Expected log lines: a `PLAYING ... provider=filesystem_smb`, a `SYNC: ... music/sync triggered`, and a no-match `REJECTED reason=no-local-match` followed by an `ANNOUNCE ...` line. Confirm with the user that Rammstein played and (if TTS configured) the failure line was spoken.

- [ ] **Step 8: Update the architecture + design docs**

In `docs/homebrain/local-music-architecture.md`, add a "Resolver internals (Inc 0)" subsection documenting: the module layout (`wsutil`/`match`/`config`/`maconn`/`haconn`/`music`/`core`/`resolver` + stubs), the capability result contract, the honest failure-feedback path (and whether TTS is wired or pending), the `resolver.py.orig` fallback + revert procedure, and how to run the unit suite.

In `docs/homebrain/2026-06-27-assistant-tooling-design.md`, change the Inc 0 line in §7 to mark it **DONE** with a one-line result summary.

- [ ] **Step 9: Secret-scan and commit**

```bash
cd /d/repos/dotfiles
grep -rIn -E 'eyJ[A-Za-z0-9_-]{10}|Bearer [A-Za-z0-9]' docs/homebrain/mass-resolver/ docs/homebrain/*.md || echo "clean"
git add docs/homebrain/mass-resolver/config.json docs/homebrain/local-music-architecture.md docs/homebrain/2026-06-27-assistant-tooling-design.md
git commit -m "feat(homebrain): deploy modular resolver (Inc 0) + validate + document"
```
Expected: `clean`, then a successful commit.

---

## Self-Review

**1. Spec coverage** (against `2026-06-27-assistant-tooling-design.md`):
- §3 tool surface — transport untouched (not in scope here); content capabilities present as `music` (live) + `radio`/`news`/`acquire`/`status` (stubs). ✓ (Tasks 7, 8)
- §4 modular resolver + MCP-ready boundary — capability functions take plain args, return a plain contract dict, decoupled from the HA-event adapter (`event_to_call` is pure; `serve` is the thin adapter). ✓ (Tasks 7–10)
- §5 config-driven — `config.json` enriched + `radio.json`/`news.json` scaffolds + `config.py` loader + `country_code`. ✓ (Task 3)
- §6 honest failure feedback — `haconn.announce` + dispatcher rule + validation. ✓ (Tasks 6, 9, 11)
- §7 Inc 0 scope (refactor + config + tool set + failure feedback, original preserved, runnable until validated) — ✓ (Tasks 1–11)
- §8 no-loss — music + sync behavior preserved verbatim; `resolver.py.orig` fallback; CLI unchanged. ✓ (Tasks 1, 5, 7, 10)
- §9 constraints — Python 3.5 safe, secrets via stdin/0600/.gitignore, user restarts service, no AI attribution, secret-scan. ✓ (Global Constraints + Task 11)

**2. Placeholder scan:** No "TBD"/"handle edge cases"/"similar to". The one acknowledged dead-code fragment in Task 10 is explicitly flagged with exact removal instructions. ✓

**3. Type consistency:** Capability contract keys (`ok`, `intent`, `request_id`, `spoken`, `reason`, `not_implemented`, music extras) are used identically across `music.py`, the stubs, and `core.dispatch`. `MA` methods (`connect`/`cmd`/`library`/`play`/`sync`/`close`) match between `maconn.py`, `music.py` test fakes, and `core.py`. `HA` methods (`connect`/`subscribe`/`read`/`call_service`/`announce`/`close`) match between `haconn.py`, `core.py`, and `resolver.py`. `wsutil` public names (`ws_connect`/`ws_read`/`ws_send`/`ws_frame`/`need`/`ws_pong`) match across `maconn`/`haconn`. ✓
