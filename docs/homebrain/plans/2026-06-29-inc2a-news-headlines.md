# Inc 2A — Spoken News Headlines Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> **Plan only — do NOT implement past the repo phase without the marked gate approvals. Stop at every 🔴.**
> Parent design (approved): [../2026-06-29-inc2a-news-headlines-design.md](../2026-06-29-inc2a-news-headlines-design.md)
> Pattern template: [2026-06-29-inc4a-status-now-playing.md](2026-06-29-inc4a-status-now-playing.md).
> Contracts (verified in-repo): `mass-resolver/command_result.py`, `capability.py`, `core.py`, `music.py`, `radio.py`, `radiobrowser.py`, `config.py`, `http_server.py`.

**Goal:** Add a resolver-controlled `news` capability that fetches curated public RSS, parses headlines with Python 3.5 stdlib, and returns a synchronous `CommandResult` whose headlines are spoken once via Piper and relayed to ChatGPT as a hard tool result.

**Architecture:** A new `NewsCapability(capability.Capability)` (`resolve → validate → execute → CommandResult`) registered in `core.CAPS["news"]` (removed from `core._STUBS`), backed by a small pure `newsfeed.py` fetch/parse module behind a mockable network seam. Config-driven via `news.json`. Mirrors the proven Inc 4A `StatusCapability` shape and the `radio.py`↔`radiobrowser.py` split.

**Tech Stack:** Python 3.5.2 (host runtime), stdlib only (`urllib.request`, `xml.etree.ElementTree`, `html`, `re`), stdlib `unittest`. No new third-party dependencies.

## Global Constraints

- **Python 3.5.2-safe:** no f-strings, no walrus, no `dict|dict`; use `%` / `.format()`. Stdlib `unittest` only (no pytest). `.encode("ascii","replace")` for any console/log output of feed text.
- **No new third-party dependencies.** Fetch/parse with stdlib only.
- **Repo tests must never touch the live network** — `newsfeed._http_get` is patched / fixture XML is fed directly.
- **Resolver is the SOLE TTS owner.** No `tts.speak` in any script; no `set_conversation_response`. The script relays `chat_text` as a hard tool result only.
- **Config-driven:** sources/counts/timeouts live in `news.json`, not code.
- **Additive/reversible:** new `NewsCapability` + new `newsfeed.py` + `news.json` edit + `core` registration + new (initially-unexposed) `script.news`. Existing tools/scripts/adapters must not change behavior.
- **Repo source of truth = the version-controlled mirror `docs/homebrain/mass-resolver/`** (mirrors `~costea/mass-resolver/` on the host). Repo phases edit the mirror; deploy copies the mirror to the host (gated).
- **Failures never speak:** `spoken_text=None` on every error path.
- **Secrets:** none needed (public RSS). Never print/log/stage/commit secrets. Secret-scan before any commit. No Claude/AI attribution in commits. Commit only when the user asks. Stage only the files for the task at hand.
- All test commands are run from `docs/homebrain/mass-resolver/`.

## File Structure

| File | Responsibility | Action |
|---|---|---|
| `newsfeed.py` | Pure RSS/Atom fetch + parse; stdlib-only; mockable `_http_get` seam; returns normalized `{title,link,source}`; never raises. | **Create** |
| `news.py` | `NewsCapability` (`resolve/validate/execute`); reads `news.json`, selects bucket, calls the seam, merges/caps, builds `CommandResult`. Currently a stub — **replaced**. | **Modify (replace stub)** |
| `news.json` | Config: `defaults` + `feeds` per bucket + inert `stations`. | **Modify** |
| `core.py` | Register `CAPS["news"]`; remove `"news"` from `_STUBS`; add `import news`. | **Modify** |
| `tests/test_newsfeed.py` | Unit tests for `newsfeed.parse` + `fetch_feed` (network mocked). | **Create** |
| `tests/test_news.py` | Unit tests for `NewsCapability` (seam mocked) + `_merge`. | **Create** |
| `tests/test_stubs.py` | Remove the `news` stub test (news is no longer a stub). | **Modify** |
| `tests/test_core.py` | Repoint the stub-dispatch test to `acquire`; add `news` dispatch integration tests. | **Modify** |

---

## Task 1: `newsfeed.parse` — RSS + Atom parse with cleanup

**Files:**
- Create: `docs/homebrain/mass-resolver/newsfeed.py`
- Test: `docs/homebrain/mass-resolver/tests/test_newsfeed.py`

**Interfaces:**
- Produces: `newsfeed.parse(xml_bytes) -> list[{"title": str, "link": str}]`. Returns `[]` on any parse error. Handles RSS (`<item>`) and Atom (`<entry>` with `<link href>`); titles cleaned (whitespace collapsed, HTML entities unescaped).
- Produces: `newsfeed._clean(text) -> str` (helper).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_newsfeed.py`:
```python
#!/usr/bin/env python3
"""Inc 2A newsfeed parse/fetch unit tests (network mocked). Run: python tests/test_newsfeed.py"""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import newsfeed

RSS = ('<?xml version="1.0" encoding="utf-8"?>'
       '<rss version="2.0"><channel><title>BBC</title>'
       '<item><title>Headline  One &amp; Two</title><link>http://x/1</link></item>'
       '<item><title>Second   Headline</title><link>http://x/2</link></item>'
       '</channel></rss>').encode("utf-8")

ATOM = ('<?xml version="1.0" encoding="utf-8"?>'
        '<feed xmlns="http://www.w3.org/2005/Atom">'
        '<entry><title>Atom Title</title><link href="http://a/1"/></entry>'
        '</feed>').encode("utf-8")

NONASCII = ('<?xml version="1.0" encoding="utf-8"?><rss version="2.0"><channel>'
            '<item><title>Café News</title><link>http://x</link></item>'
            '</channel></rss>').encode("utf-8")


class ParseTest(unittest.TestCase):
    def test_rss_titles_links(self):
        items = newsfeed.parse(RSS)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["title"], "Headline One & Two")   # whitespace collapsed, entity decoded
        self.assertEqual(items[0]["link"], "http://x/1")
        self.assertEqual(items[1]["title"], "Second Headline")

    def test_atom_title_and_href_link(self):
        items = newsfeed.parse(ATOM)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "Atom Title")
        self.assertEqual(items[0]["link"], "http://a/1")

    def test_nonascii_title_preserved(self):
        items = newsfeed.parse(NONASCII)
        self.assertEqual(items[0]["title"], "Café News")

    def test_malformed_xml_returns_empty(self):
        self.assertEqual(newsfeed.parse(b"not xml <<<"), [])

    def test_empty_bytes_returns_empty(self):
        self.assertEqual(newsfeed.parse(b""), [])

    def test_doctype_entity_rejected(self):
        # billion-laughs / XXE payload: must be rejected before reaching the parser.
        bomb = (b'<?xml version="1.0"?>'
                b'<!DOCTYPE lolz [<!ENTITY lol "lol">'
                b'<!ENTITY lol2 "&lol;&lol;&lol;">]>'
                b'<rss version="2.0"><channel><item><title>&lol2;</title>'
                b'<link>http://x</link></item></channel></rss>')
        self.assertEqual(newsfeed.parse(bomb), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python tests/test_newsfeed.py`
Expected: FAIL — `ImportError: No module named 'newsfeed'` (or `AttributeError: parse`).

- [ ] **Step 3: Write minimal implementation**

Create `newsfeed.py`:
```python
#!/usr/bin/env python3
# RSS/Atom news feed fetch + parse -> normalized items. Python 3.5 safe. Stdlib only.
import logging, re, html
from urllib.request import urlopen
import xml.etree.ElementTree as ET

LOG = logging.getLogger("resolver")

_ATOM = "{http://www.w3.org/2005/Atom}"


def _clean(text):
    if not text:
        return ""
    t = html.unescape(text)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def parse(xml_bytes):
    """Parse RSS or Atom bytes -> list of {title, link}. [] on any parse error.

    XML safety (stdlib-only; defusedxml is a disallowed 3rd-party dep): reject any DOCTYPE/ENTITY
    declaration before parsing. Entity-expansion (billion-laughs) and XXE both require one, and
    well-formed RSS/Atom never has one. XML keywords are case-sensitive + uppercase -> exact byte match.
    """
    raw = xml_bytes or b""
    if (b"<!DOCTYPE" in raw) or (b"<!ENTITY" in raw):
        LOG.error("newsfeed parse: rejected feed with DOCTYPE/ENTITY declaration")
        return []
    try:
        root = ET.fromstring(raw)
    except Exception as e:
        LOG.error("newsfeed parse error: %r", e)
        return []
    items = []
    # RSS 2.0: <item><title/><link/>
    for it in root.iter("item"):
        title = _clean(it.findtext("title"))
        if title:
            items.append({"title": title, "link": (it.findtext("link") or "").strip()})
    if items:
        return items
    # Atom: <entry><title/><link href=.../>
    for it in root.iter(_ATOM + "entry"):
        title = _clean(it.findtext(_ATOM + "title"))
        if not title:
            continue
        link = ""
        le = it.find(_ATOM + "link")
        if le is not None:
            link = le.get("href") or ""
        items.append({"title": title, "link": link.strip()})
    return items
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python tests/test_newsfeed.py`
Expected: PASS (6 tests OK).

- [ ] **Step 5: Commit**

```bash
git add docs/homebrain/mass-resolver/newsfeed.py docs/homebrain/mass-resolver/tests/test_newsfeed.py
git commit -m "feat(news): add newsfeed RSS/Atom parser"
```

---

## Task 2: `newsfeed.fetch_feed` + `_http_get` seam

**Files:**
- Modify: `docs/homebrain/mass-resolver/newsfeed.py`
- Test: `docs/homebrain/mass-resolver/tests/test_newsfeed.py`

**Interfaces:**
- Consumes: `newsfeed.parse` (Task 1).
- Produces: `newsfeed._http_get(url, timeout) -> bytes` (the mockable network seam — patched in tests).
- Produces: `newsfeed.fetch_feed(feed, timeout, max_items) -> list[{"title","link","source"}]`. `feed` is `{"name","url"}`. Returns `[]` on any failure (timeout/HTTP/parse) — **never raises**. Attaches `source = feed["name"]`; truncates to `max_items`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_newsfeed.py` (before the `if __name__` block):
```python
class FetchFeedTest(unittest.TestCase):
    def setUp(self):
        self._orig = newsfeed._http_get

    def tearDown(self):
        newsfeed._http_get = self._orig

    def test_success_attaches_source(self):
        newsfeed._http_get = lambda url, timeout: RSS
        items = newsfeed.fetch_feed({"name": "BBC World", "url": "http://x"}, 4.0, 10)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["source"], "BBC World")
        self.assertEqual(items[0]["title"], "Headline One & Two")

    def test_network_error_returns_empty(self):
        def boom(url, timeout):
            raise IOError("timed out")
        newsfeed._http_get = boom
        self.assertEqual(newsfeed.fetch_feed({"name": "BBC", "url": "http://x"}, 4.0, 10), [])

    def test_max_items_truncates(self):
        newsfeed._http_get = lambda url, timeout: RSS
        items = newsfeed.fetch_feed({"name": "BBC", "url": "http://x"}, 4.0, 1)
        self.assertEqual(len(items), 1)

    def test_missing_url_returns_empty(self):
        self.assertEqual(newsfeed.fetch_feed({"name": "BBC"}, 4.0, 10), [])

    def test_unparseable_body_returns_empty(self):
        newsfeed._http_get = lambda url, timeout: b"garbage <<<"
        self.assertEqual(newsfeed.fetch_feed({"name": "BBC", "url": "http://x"}, 4.0, 10), [])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python tests/test_newsfeed.py`
Expected: FAIL — `AttributeError: module 'newsfeed' has no attribute 'fetch_feed'` (and `_http_get`).

- [ ] **Step 3: Write minimal implementation**

Append to `newsfeed.py`:
```python
# Cap the feed read so an oversized/malicious payload can't exhaust memory.
# NB: 2000000 (no underscores) -- numeric underscores are a Python 3.6+ syntax error; host is 3.5.2.
_MAX_FEED_BYTES = 2000000


def _http_get(url, timeout):
    """Network seam: fetch raw bytes for a feed URL (size-capped). Patched in tests; only network call."""
    resp = urlopen(url, timeout=timeout)
    try:
        return resp.read(_MAX_FEED_BYTES)
    finally:
        resp.close()


def fetch_feed(feed, timeout, max_items):
    """Fetch + parse one feed -> [{title, link, source}]. [] on any failure; never raises."""
    feed = feed or {}
    name = feed.get("name") or "?"
    url = feed.get("url")
    if not url:
        return []
    try:
        raw = _http_get(url, timeout)
    except Exception as e:
        LOG.error("newsfeed fetch failed name=%s: %r",
                  name.encode("ascii", "replace").decode("ascii"), e)
        return []
    out = []
    for it in parse(raw)[:max_items]:
        out.append({"title": it["title"], "link": it.get("link", ""), "source": name})
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python tests/test_newsfeed.py`
Expected: PASS (11 tests OK).

- [ ] **Step 5: Commit**

```bash
git add docs/homebrain/mass-resolver/newsfeed.py docs/homebrain/mass-resolver/tests/test_newsfeed.py
git commit -m "feat(news): add newsfeed fetch_feed with mockable network seam"
```

---

## Task 3: `NewsCapability.resolve` + `validate` (bucket selection)

**Files:**
- Modify: `docs/homebrain/mass-resolver/news.py` (replace the stub)
- Test: `docs/homebrain/mass-resolver/tests/test_news.py`

**Interfaces:**
- Consumes: `capability.Capability`, `command_result` (via `capability.run`), `ctx.news_cfg`.
- Produces: `news.NewsCapability` with `name="news"`.
  - `resolve(ctx, params) -> {"bucket_key", "requested_label", "feeds", "headline_count", "feed_timeout", "max_items"}` (no network).
  - `validate(ctx, resolved) -> None | {code, reason, chat_text, spoken_text, metadata}`.
  - `news._defaults(news_cfg) -> {"headline_count","feed_timeout","max_items_per_feed"}` (helper).
- Bucket rule: absent topic/country → `"world"`; explicit matching key → that key; explicit unrecognized → `bucket_key=None` (rejected by `validate` as `not_found`).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_news.py`:
```python
#!/usr/bin/env python3
"""Inc 2A NewsCapability unit tests (fetch seam mocked). Run: python tests/test_news.py"""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import news, newsfeed, capability

CFG = {"defaults": {"headline_count": 3, "feed_timeout": 4.0, "max_items_per_feed": 10},
       "feeds": {"world": [{"name": "BBC World", "url": "http://bbc/world"}]},
       "stations": {}}


class FakeCtx(object):
    def __init__(self, news_cfg):
        self.news_cfg = news_cfg


def run(cfg, params, results=None):
    """results: dict url -> list[item]; absent urls -> []. Patches newsfeed.fetch_feed."""
    results = results or {}
    orig = newsfeed.fetch_feed
    newsfeed.fetch_feed = lambda feed, timeout, max_items: list(results.get(feed.get("url"), []))
    try:
        return capability.run(news.NewsCapability(), FakeCtx(cfg), params, "rid1")
    finally:
        newsfeed.fetch_feed = orig


class ResolveValidateTest(unittest.TestCase):
    def test_no_param_defaults_world(self):
        cap = news.NewsCapability()
        r = cap.resolve(FakeCtx(CFG), {})
        self.assertEqual(r["bucket_key"], "world")
        self.assertIsNone(r["requested_label"])
        self.assertEqual(len(r["feeds"]), 1)
        self.assertEqual(r["headline_count"], 3)

    def test_explicit_known_topic_selects_bucket(self):
        cap = news.NewsCapability()
        r = cap.resolve(FakeCtx(CFG), {"topic": "World"})
        self.assertEqual(r["bucket_key"], "world")

    def test_explicit_unknown_country_no_bucket(self):
        cap = news.NewsCapability()
        r = cap.resolve(FakeCtx(CFG), {"country": "Romania"})
        self.assertIsNone(r["bucket_key"])
        self.assertEqual(r["requested_label"], "Romania")

    def test_validate_unknown_bucket_not_found(self):
        r = run(CFG, {"country": "Romania"})
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"]["code"], "not_found")
        self.assertEqual(r["chat_text"], "I don't have Romania news set up yet.")
        self.assertIsNone(r["spoken_text"])

    def test_validate_empty_bucket_not_found(self):
        cfg = {"defaults": CFG["defaults"], "feeds": {"world": []}, "stations": {}}
        r = run(cfg, {})
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"]["code"], "not_found")
        self.assertIsNone(r["spoken_text"])

    def test_defaults_fallback_when_missing(self):
        d = news._defaults({})
        self.assertEqual(d["headline_count"], 3)
        self.assertEqual(d["feed_timeout"], 4.0)
        self.assertEqual(d["max_items_per_feed"], 10)


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python tests/test_news.py`
Expected: FAIL — `AttributeError: module 'news' has no attribute 'NewsCapability'`.

- [ ] **Step 3: Write minimal implementation**

Replace the entire contents of `news.py` with (execute is a placeholder that raises until Task 5 — but write the real `resolve`/`validate`/`_defaults` now):
```python
#!/usr/bin/env python3
# News capability: spoken headlines from curated RSS feeds. Python 3.5 safe.
import logging
import capability
import command_result as cr
import newsfeed

LOG = logging.getLogger("resolver")

_DEFAULTS = {"headline_count": 3, "feed_timeout": 4.0, "max_items_per_feed": 10}


def _defaults(news_cfg):
    d = dict(_DEFAULTS)
    d.update((news_cfg or {}).get("defaults", {}))
    return d


class NewsCapability(capability.Capability):
    name = "news"

    def resolve(self, ctx, params):
        news_cfg = ctx.news_cfg or {}
        feeds_cfg = news_cfg.get("feeds", {}) or {}
        d = _defaults(news_cfg)
        label = params.get("topic") or params.get("country")
        if label is not None:
            label = str(label).strip()
        if not label:
            bucket_key = "world"
            requested_label = None
        else:
            key = label.lower()
            if key in feeds_cfg:
                bucket_key = key
                requested_label = None
            else:
                bucket_key = None
                requested_label = label
        if bucket_key:
            feeds = feeds_cfg.get(bucket_key) or []
        else:
            feeds = []
        return {"bucket_key": bucket_key, "requested_label": requested_label,
                "feeds": feeds, "headline_count": d["headline_count"],
                "feed_timeout": d["feed_timeout"], "max_items": d["max_items_per_feed"]}

    def validate(self, ctx, resolved):
        if resolved.get("bucket_key") is None:
            lbl = resolved.get("requested_label") or "that"
            return {"code": "not_found", "reason": "bucket not configured",
                    "chat_text": "I don't have " + lbl + " news set up yet.",
                    "spoken_text": None, "metadata": {"requested": lbl.lower()}}
        if not resolved.get("feeds"):
            return {"code": "not_found", "reason": "bucket not configured",
                    "chat_text": "I don't have that news set up yet.",
                    "spoken_text": None, "metadata": {"requested": resolved.get("bucket_key")}}
        return None

    def execute(self, ctx, resolved, rid):
        raise NotImplementedError("execute lands in Task 5")
```
> Note: the `not_found` `chat_text` uses the requested label **verbatim** (e.g. `"Romania"` → "I don't have Romania news set up yet."). Do not title-case or transform it.

- [ ] **Step 4: Run test to verify it passes**

Run: `python tests/test_news.py`
Expected: PASS (6 tests OK). (The execute path is not exercised by these tests yet.)

- [ ] **Step 5: Commit**

```bash
git add docs/homebrain/mass-resolver/news.py docs/homebrain/mass-resolver/tests/test_news.py
git commit -m "feat(news): add NewsCapability resolve+validate bucket selection"
```

---

## Task 4: `news._merge` — round-robin merge, dedupe, cap

**Files:**
- Modify: `docs/homebrain/mass-resolver/news.py`
- Test: `docs/homebrain/mass-resolver/tests/test_news.py`

**Interfaces:**
- Produces: `news._merge(per_feed, cap) -> list[item]`. `per_feed` is a list of per-feed item lists. Interleaves round-robin (index 0 of each feed, then index 1, …), dedupes by lowercased `title`, caps at `cap`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_news.py` (before `if __name__`):
```python
class MergeTest(unittest.TestCase):
    def _items(self, *titles):
        return [{"title": t, "link": "", "source": "s"} for t in titles]

    def test_roundrobin_interleaves_feeds(self):
        a = self._items("A1", "A2")
        b = self._items("B1", "B2")
        merged = news._merge([a, b], 4)
        self.assertEqual([m["title"] for m in merged], ["A1", "B1", "A2", "B2"])

    def test_dedupes_by_title_case_insensitive(self):
        a = self._items("Same", "A2")
        b = self._items("same", "B2")
        merged = news._merge([a, b], 4)
        self.assertEqual([m["title"] for m in merged], ["Same", "A2", "B2"])

    def test_caps_at_count(self):
        a = self._items("A1", "A2", "A3", "A4")
        merged = news._merge([a], 2)
        self.assertEqual(len(merged), 2)

    def test_empty_returns_empty(self):
        self.assertEqual(news._merge([], 3), [])
        self.assertEqual(news._merge([[]], 3), [])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python tests/test_news.py`
Expected: FAIL — `AttributeError: module 'news' has no attribute '_merge'`.

- [ ] **Step 3: Write minimal implementation**

Add to `news.py` (module level, above the class):
```python
def _merge(per_feed, cap):
    """Round-robin across per-feed lists, dedupe by lowercased title, cap at `cap`."""
    seen = set()
    out = []
    i = 0
    more = True
    while more and len(out) < cap:
        more = False
        for lst in per_feed:
            if i < len(lst):
                more = True
                it = lst[i]
                key = (it.get("title") or "").strip().lower()
                if key and key not in seen:
                    seen.add(key)
                    out.append(it)
                    if len(out) >= cap:
                        break
        i += 1
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python tests/test_news.py`
Expected: PASS (10 tests OK).

- [ ] **Step 5: Commit**

```bash
git add docs/homebrain/mass-resolver/news.py docs/homebrain/mass-resolver/tests/test_news.py
git commit -m "feat(news): add round-robin merge/dedupe/cap helper"
```

---

## Task 5: `NewsCapability.execute` — fetch, merge, build CommandResult

**Files:**
- Modify: `docs/homebrain/mass-resolver/news.py`
- Test: `docs/homebrain/mass-resolver/tests/test_news.py`

**Interfaces:**
- Consumes: `newsfeed.fetch_feed` (Task 2), `news._merge` (Task 4), `command_result.ok/err`.
- Produces: `news._spoken(bucket, items) -> str`, `news._chat(bucket, items) -> str`, and the real `NewsCapability.execute(ctx, resolved, rid) -> CommandResult`.
- Success: `ok=true`, `spoken_text="Here are the top <bucket> headlines. <t1>. <t2>. <t3>."`, `chat_text="Top <bucket> headlines: 1) <t1> 2) <t2> 3) <t3>"`, `metadata={bucket,count,items,feeds_ok,feeds_failed}`.
- All-empty: `ok=false`, `error.code="unavailable"`, `chat_text="Sorry, I couldn't get the news right now."`, `spoken_text=None`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_news.py` (before `if __name__`):
```python
def _mk(*titles):
    return [{"title": t, "link": "http://l/" + t, "source": "BBC World"} for t in titles]

TWO_FEED_CFG = {"defaults": {"headline_count": 4, "feed_timeout": 4.0, "max_items_per_feed": 10},
                "feeds": {"world": [{"name": "F1", "url": "http://f1"},
                                    {"name": "F2", "url": "http://f2"}]},
                "stations": {}}


class ExecuteTest(unittest.TestCase):
    def test_single_feed_success_shape(self):
        r = run(CFG, {}, {"http://bbc/world": _mk("Alpha", "Bravo", "Charlie", "Delta")})
        self.assertTrue(r["ok"])
        self.assertEqual(r["intent"], "news")
        self.assertEqual(r["spoken_text"], "Here are the top world headlines. Alpha. Bravo. Charlie.")
        self.assertEqual(r["chat_text"], "Top world headlines: 1) Alpha 2) Bravo 3) Charlie")
        self.assertEqual(r["metadata"]["bucket"], "world")
        self.assertEqual(r["metadata"]["count"], 3)              # capped at headline_count=3
        self.assertEqual(r["metadata"]["feeds_ok"], 1)
        self.assertEqual(r["metadata"]["feeds_failed"], 0)
        self.assertEqual(r["metadata"]["items"][0]["source"], "BBC World")

    def test_multi_feed_merge_roundrobin(self):
        r = run(TWO_FEED_CFG, {}, {"http://f1": _mk("A1", "A2"), "http://f2": _mk("B1", "B2")})
        self.assertTrue(r["ok"])
        self.assertEqual([it["title"] for it in r["metadata"]["items"]], ["A1", "B1", "A2", "B2"])
        self.assertEqual(r["metadata"]["feeds_ok"], 2)

    def test_graceful_degrade_one_feed_fails(self):
        # F1 returns nothing (failed/empty); F2 yields -> still success.
        r = run(TWO_FEED_CFG, {}, {"http://f2": _mk("B1", "B2")})
        self.assertTrue(r["ok"])
        self.assertEqual([it["title"] for it in r["metadata"]["items"]], ["B1", "B2"])
        self.assertEqual(r["metadata"]["feeds_ok"], 1)
        self.assertEqual(r["metadata"]["feeds_failed"], 1)

    def test_all_empty_unavailable_silent(self):
        r = run(CFG, {}, {})                                    # fetch returns [] for every url
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"]["code"], "unavailable")
        self.assertEqual(r["chat_text"], "Sorry, I couldn't get the news right now.")
        self.assertIsNone(r["spoken_text"])
        self.assertEqual(r["metadata"]["count"], 0)
        self.assertEqual(r["metadata"]["feeds_ok"], 0)
        self.assertEqual(r["metadata"]["feeds_failed"], 1)

    def test_headline_count_one(self):
        cfg = {"defaults": {"headline_count": 1, "feed_timeout": 4.0, "max_items_per_feed": 10},
               "feeds": {"world": [{"name": "BBC", "url": "http://bbc/world"}]}, "stations": {}}
        r = run(cfg, {}, {"http://bbc/world": _mk("Only", "Two", "Three")})
        self.assertEqual(r["spoken_text"], "Here are the top world headlines. Only.")
        self.assertEqual(r["chat_text"], "Top world headlines: 1) Only")
        self.assertEqual(r["metadata"]["count"], 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python tests/test_news.py`
Expected: FAIL — `NotImplementedError: execute lands in Task 5`.

- [ ] **Step 3: Write minimal implementation**

In `news.py`, add the two builders (module level, above the class) and replace the `execute` stub:
```python
def _spoken(bucket, items):
    titles = [it["title"] for it in items]
    return "Here are the top " + bucket + " headlines. " + ". ".join(titles) + "."


def _chat(bucket, items):
    parts = []
    n = 1
    for it in items:
        parts.append("%d) %s" % (n, it["title"]))
        n += 1
    return "Top " + bucket + " headlines: " + " ".join(parts)
```
Replace the `execute` method body:
```python
    def execute(self, ctx, resolved, rid):
        bucket = resolved["bucket_key"]
        cap = resolved["headline_count"]
        timeout = resolved["feed_timeout"]
        max_items = resolved["max_items"]
        per_feed = []
        feeds_ok = 0
        feeds_failed = 0
        for f in resolved["feeds"]:
            items = newsfeed.fetch_feed(f, timeout, max_items)
            if items:
                feeds_ok += 1
                per_feed.append(items)
            else:
                feeds_failed += 1
        merged = _merge(per_feed, cap)
        if not merged:
            LOG.error("req=%s NEWS no headlines bucket=%s ok=%d failed=%d",
                      rid, bucket, feeds_ok, feeds_failed)
            return cr.err(self.name, rid, "unavailable", "no headlines (feeds failed/empty)",
                          "Sorry, I couldn't get the news right now.", spoken_text=None,
                          metadata={"bucket": bucket, "count": 0, "items": [],
                                    "feeds_ok": feeds_ok, "feeds_failed": feeds_failed})
        LOG.info("req=%s NEWS bucket=%s count=%d ok=%d failed=%d",
                 rid, bucket, len(merged), feeds_ok, feeds_failed)
        md = {"bucket": bucket, "count": len(merged), "items": merged,
              "feeds_ok": feeds_ok, "feeds_failed": feeds_failed}
        return cr.ok(self.name, rid, _chat(bucket, merged),
                     spoken_text=_spoken(bucket, merged), metadata=md)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python tests/test_news.py`
Expected: PASS (15 tests OK).

- [ ] **Step 5: Run the newsfeed suite too (no regression)**

Run: `python tests/test_newsfeed.py`
Expected: PASS (11 tests OK).

- [ ] **Step 6: Commit**

```bash
git add docs/homebrain/mass-resolver/news.py docs/homebrain/mass-resolver/tests/test_news.py
git commit -m "feat(news): implement NewsCapability execute (fetch/merge/result)"
```

---

## Task 6: Core wiring + `news.json` + stub-test cleanup + full suite

**Files:**
- Modify: `docs/homebrain/mass-resolver/core.py:4`, `core.py:9-19`
- Modify: `docs/homebrain/mass-resolver/news.json`
- Modify: `docs/homebrain/mass-resolver/tests/test_stubs.py`
- Modify: `docs/homebrain/mass-resolver/tests/test_core.py`

**Interfaces:**
- Consumes: `news.NewsCapability` (Tasks 3–5).
- Produces: `core.CAPS["news"]` registered; `"news"` removed from `core._STUBS`; `news.json` seeded with the BBC World feed + defaults.

- [ ] **Step 1: Write/adjust the failing tests**

(a) In `tests/test_stubs.py`, remove the news stub. Change line 5 from `import news, acquire` to:
```python
import acquire
```
and delete the `test_news_stub` method (lines 17–18). Acquire stays the only stub test.

(b) In `tests/test_core.py`, the existing `test_stub_intent_not_implemented_speaks` (lines 153–161) dispatches `"news"` — repoint it to `"acquire"` (still a stub):
```python
    # --- stub intent (acquire) ---
    def test_stub_intent_not_implemented_speaks(self):
        ma = FakeMA()
        spk = FakeSpeaker()
        ctx = FakeCtx(ma, speaker=spk)
        r = core.dispatch(ctx, "acquire", {"query": "some song"})
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"]["code"], "not_implemented")
        self.assertEqual(len(spk.said), 1)
        self.assertIn("yet", spk.said[0].lower())
```

(c) In `tests/test_core.py`, add news dispatch integration tests. First add a module-level import near the top imports and a helper, then the test class. Add after the existing imports (`import core`):
```python
import news, newsfeed
```
Add this test class before the `if __name__` block:
```python
class NewsDispatchTest(unittest.TestCase):
    NEWS_CFG = {"defaults": {"headline_count": 3, "feed_timeout": 4.0, "max_items_per_feed": 10},
                "feeds": {"world": [{"name": "BBC World", "url": "http://bbc/world"}]},
                "stations": {}}

    def _ctx(self, news_cfg):
        spk = FakeSpeaker()
        ctx = core.Ctx(ma_factory=lambda: None, ha=None, settings=FakeSettings(),
                       radio_cfg=RC, news_cfg=news_cfg, speaker=spk)
        return ctx, spk

    def test_news_registered_in_caps_not_stubs(self):
        self.assertIn("news", core.CAPS)
        self.assertIsInstance(core.CAPS["news"], news.NewsCapability)
        self.assertNotIn("news", core._STUBS)

    def test_dispatch_news_success_speaks_once(self):
        ctx, spk = self._ctx(self.NEWS_CFG)
        orig = newsfeed.fetch_feed
        newsfeed.fetch_feed = lambda feed, t, m: [{"title": "Alpha", "link": "", "source": "BBC World"},
                                                  {"title": "Bravo", "link": "", "source": "BBC World"}]
        try:
            r = core.dispatch(ctx, "news", {})
        finally:
            newsfeed.fetch_feed = orig
        self.assertTrue(r["ok"])
        self.assertEqual(r["intent"], "news")
        self.assertEqual(len(spk.said), 1)                       # headlines spoken once
        self.assertIn("headlines", spk.said[0].lower())

    def test_dispatch_news_unavailable_silent(self):
        ctx, spk = self._ctx(self.NEWS_CFG)
        orig = newsfeed.fetch_feed
        newsfeed.fetch_feed = lambda feed, t, m: []              # all feeds empty
        try:
            r = core.dispatch(ctx, "news", {})
        finally:
            newsfeed.fetch_feed = orig
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"]["code"], "unavailable")
        self.assertEqual(spk.said, [])                           # failures never speak

    def test_dispatch_news_unknown_bucket_not_found_silent(self):
        ctx, spk = self._ctx(self.NEWS_CFG)
        r = core.dispatch(ctx, "news", {"country": "Romania"})
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"]["code"], "not_found")
        self.assertEqual(spk.said, [])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python tests/test_core.py`
Expected: FAIL — `test_news_registered_in_caps_not_stubs` fails (`news` not in `CAPS`, still in `_STUBS`); `AssertionError` in the news dispatch tests (currently hits the stub "not available yet" path).

- [ ] **Step 3: Wire `core.py`**

Modify `core.py` line 4 (add `news` to the import):
```python
import music, radio, status, news, capability, command_result as cr
```
Modify the `CAPS` dict (lines 9–13) to add news:
```python
CAPS = {
    "music": music.MusicCapability(),
    "radio": radio.RadioCapability(),
    "status": status.StatusCapability(),
    "news": news.NewsCapability(),
}
```
Modify `_STUBS` (lines 16–19) to remove news (leaving acquire):
```python
_STUBS = {
    "acquire": "Acquire",
}
```

- [ ] **Step 4: Seed `news.json`**

Replace the entire contents of `news.json`:
```json
{
  "defaults": { "headline_count": 3, "feed_timeout": 4.0, "max_items_per_feed": 10 },
  "feeds": {
    "world": [
      { "name": "BBC World", "url": "http://feeds.bbci.co.uk/news/world/rss.xml" }
    ]
  },
  "stations": {}
}
```

- [ ] **Step 5: Run the changed suites to verify they pass**

Run: `python tests/test_core.py`
Expected: PASS (all CoreDispatchTest + NewsDispatchTest tests OK).
Run: `python tests/test_stubs.py`
Expected: PASS (only the acquire stub test).

- [ ] **Step 6: Run the FULL suite green**

Run (from `docs/homebrain/mass-resolver/`):
```bash
python -m unittest discover -s tests -p "test_*.py" -v
```
Expected: PASS — every test file green (existing ~160 + the new newsfeed/news tests; news no longer counted as a stub). Confirm `news.json` parses: `python -c "import json; json.load(open('news.json'))"` → no error.

- [ ] **Step 7: Commit**

```bash
git add docs/homebrain/mass-resolver/core.py docs/homebrain/mass-resolver/news.json \
        docs/homebrain/mass-resolver/tests/test_stubs.py docs/homebrain/mass-resolver/tests/test_core.py
git commit -m "feat(news): register news capability and seed news.json"
```

> **End of repo phase.** The capability is fully built and green with the network mocked. The remaining phases are live and gated — **stop for explicit approval at each 🔴.**

---

## Phase G3 — Host network-reality check (read-only)

> ### 🔴 STOP — APPROVAL REQUIRED (read-only host access / SSH)
> Confirming the host can actually reach the BBC feed on its Python 3.5.2 / old OpenSSL requires a **read-only** SSH check. **Do not SSH without explicit approval.** No deploy, no file changes, no restart in this phase.

**Goal:** prove the chosen feed is reachable + parseable from the host *before* deploying code that depends on it.

- With approval, run a **read-only** one-shot on the host (user-run or approved agent SSH), no files written:
  ```bash
  ssh costea@192.168.1.68 "python3 -c \"import urllib.request as u; d=u.urlopen('http://feeds.bbci.co.uk/news/world/rss.xml', timeout=5).read(); print('bytes', len(d))\""
  ```
- Expected: a non-trivial byte count (feed reachable over plain HTTP). Optionally pipe through a parse sanity check.
- **If unreachable:** stop and revisit the feed choice with the user (the design's honest `unavailable` path still holds, but a live first slice needs at least one reachable feed).
- **Rollback:** none — read-only, no host change.

> ### 🟡 CHECKPOINT — report reachability result; stop before deploying.

---

## Phase G4 — Host deploy + resolver restart

> ### 🔴 STOP — APPROVAL REQUIRED (deploy + restart `mass-resolver`)
> Copying files to the host and **restarting `mass-resolver`** is user-run and needs explicit approval.

**Goal:** deploy the repo mirror to the host and load it.

- Pre-deploy backup: `mkdir -p ~/mass-resolver/.inc2-bak/<ts>/` and copy current host `news.py`, `core.py` into it (note: `newsfeed.py` and the seeded `news.json` are new/changed — record the git baseline SHA).
- Deploy the file list to `~/mass-resolver/`: **`newsfeed.py` (new), `news.py` (replace stub), `news.json` (seeded), `core.py` (registration)**. Tests are not deployed.
- Verify: checksums host==mirror for the four files; modes preserved; host **Python 3.5.2 `py_compile`** clean for `newsfeed.py`, `news.py`, `core.py`; import check `news in core.CAPS`, `news not in core._STUBS`.
- **Load** requires a resolver service restart (user-run sudo, approved).
- **Validation (post-deploy):** resolver healthy, 0 startup tracebacks; `/command` health `200` with `X-Resolver-Key` / `401` without; no-regression smoke of `music`/`radio`/`find`/`status` via existing paths.
- **Rollback (live):** restore the four files from `~/mass-resolver/.inc2-bak/<ts>/` (atomic: stub `news.py` + drop `news` from `CAPS` + re-add to `_STUBS` + remove `newsfeed.py` + revert `news.json`). A restart to load the rollback is **approval-gated**. `/command`, the event adapter, `mass_sync_request`, and the existing scripts are unaffected by a news-only revert.

---

## Phase G5 — Direct `/command` validation (host, no HA script)

**Goal:** prove the deployed capability returns truthful results against real feeds and speaks correctly.

- Call `/command` with `{"intent":"news","params":{}}` (with `X-Resolver-Key`). Assert: `ok=true`, `intent=news`, `metadata.bucket="world"`, `count>=1`, `chat_text` begins `Top world headlines:`, `spoken_text` set.
- Confirm Piper **speaks the headlines exactly once** (ANNOUNCE count +1).
- Failure path (honest + silent): temporarily exercise an unreachable feed (e.g. a throwaway `news.json` bucket via a separate intent param is not available in v1 — instead simulate by confirming the all-empty branch was covered in repo tests; for live, optionally point a scratch check at a bad host) → expect `ok=false`, `error.code=unavailable`, **resolver speaks 0 times**. Do **not** mutate the deployed `news.json`; if a live failure check is desired, use a read-only scratch invocation, not an edit.
- Unknown bucket: `{"intent":"news","params":{"country":"Romania"}}` → `ok=false`, `not_found`, "I don't have Romania news set up yet.", silent.
- Auth: `200` with key, `401` without. No regression of the four existing tools.

> ### 🟡 CHECKPOINT — report `/command` results; stop before touching HA.

---

## Phase G6 — Create `script.news` on HA (not exposed)

> ### 🔴 STOP — APPROVAL REQUIRED (modify Home Assistant)
> Creating a script + reloading **modifies Home Assistant** — explicit approval required. The script is **not exposed** to any assistant in this phase.

**Goal:** create the brand-new `script.news` (hard-return relay).

- Create (not edit) `script.news` via `POST /api/config/script/config/news`: alias `Ceiling: News Headlines (resolver)`, mode `single`, **no fields**, sequence:
  ```jsonc
  [
    {"action": "rest_command.resolver_command",
     "data": {"intent": "news", "params": {}},
     "response_variable": "r", "continue_on_error": true},
    {"variables": {"resp": {"chat_text": "{{ r.content.chat_text if (r is defined and r.content is defined and r.content.chat_text is defined) else 'Sorry, I could not get the news right now.' }}"}}},
    {"stop": "done", "response_variable": "resp"}
  ]
  ```
  Then `POST /api/services/script/reload`.
- **Structural readback:** alias/mode/sequence present; calls `rest_command.resolver_command` with `intent=news`, `params={}`; `response_variable: r`; final `stop` + `response_variable: resp`; **no `tts.speak`**, **no `set_conversation_response`**, **no fields**. Confirm **NOT exposed** to `conversation`.
- **Rollback (live):** delete `script.news` + `script.reload` (brand-new → fully removed; no existing script touched). No restart.

---

## Phase G7 — Script hard-return validation (no exposure)

**Goal:** prove the script returns `{chat_text: …}` as its service response and matches `/command` ground truth.

- WS `call_service script.news` with `return_response:true`: assert response is `{chat_text: "<resolver chat_text>"}` and equals the Phase-G5 `/command` `chat_text` for the same moment. Headlines speak once via the resolver (Piper) — the script itself emits no TTS.
- Exercise the `continue_on_error` fallback (simulate `/command` briefly unreachable → graceful fallback `chat_text`, no playback).

> ### 🟡 CHECKPOINT — report G6–G7. Capability is **validated but unexposed.**

---

## Phase G8 — ChatGPT exposure (separately approved)

> ### 🔴 STOP — SEPARATE APPROVAL REQUIRED (expose a new ChatGPT tool)
> Exposure is its **own** approved step. **Do not expose in the build/validate phases.** Raw `media_player.*` / MA entities are never exposed.

On approval:
- Expose `script.news` via WS `homeassistant/expose_entity` (`assistants:["conversation"]`).
- Update `assistant-capabilities.md` **in lockstep**: remove **News** from the "Not available yet" table; add a NEWS capability row + a routing rule ("read me the news / headlines → call the news tool; relay its `chat_text`"); add a concise NEWS block to the OpenAI **Instructions** (paste in the HA UI). Tool count **12 → 13**.
- Conversational validation via `conversation.openai_conversation`: "read me the news" / "what's the news" → calls `script.news`, relays the `chat_text`; resolver speaks the headlines once; no fabrication; no regression of `play_music`/`play_radio`/`find_stations`/`media_status`. Verify the exposed set is exactly **13**.
- **Rollback (live):** un-expose via `expose_entity` + revert the `assistant-capabilities.md` / Instructions edits.

---

## Approval stop-points (summary)

| Gate | Action requiring approval |
|---|---|
| **G3 STOP** | Read-only host/SSH network-reality check |
| **G4 STOP** | Deploy resolver files to host **+ restart `mass-resolver`** |
| **G6 STOP** | Create `script.news` on HA + `script.reload` |
| **G8 STOP** | **Separately approve** exposing `script.news` to ChatGPT |
| G5 / G7 CHECKPOINT | Report + pause before advancing |

## Rollback summary (per phase)

| Phase | Rollback | Restart? |
|---|---|---|
| Repo (Tasks 1–6) | `git revert` the Inc 2A commits (restore `news.py` stub, drop `news` from `CAPS`, re-add `_STUBS`, remove `newsfeed.py`, revert `news.json`) | No |
| G3 (reachability) | None — read-only | No |
| G4 (deploy) | Restore `~/mass-resolver/.inc2-bak/<ts>/` (atomic) | **Only with explicit approval** |
| G5 (/command) | None (read-only); else G4 revert | Per G4 |
| G6 (HA script) | Delete `script.news` + `script.reload` | No |
| G7 (validation) | Delete the script (G6) | No |
| G8 (exposure) | Un-expose + revert capabilities/Instructions | No |

## Python 3.5 compatibility (carried)
No f-strings; `%`/`.format()` only. Stdlib `unittest` (no pytest); run per-file from `mass-resolver/` and via `python -m unittest discover -s tests`. No new third-party deps (`urllib`, `xml.etree`, `html`, `re` only). ASCII-safe console/log output of feed text. Host `py_compile` clean on Python 3.5.2 at G4.

## Out of scope (explicit)
Inc 2B (news-station playback — deferred); Inc 3/Lidarr; Inc 4B; YTM; RadioBrowser name tidy; any model change; any change to `play_music`/`play_radio`/`find_stations`/`media_status`, the event adapter, `mass_sync_request`, or MA/HA config beyond the one new (initially-unexposed) `script.news` and the `news.py`/`newsfeed.py`/`news.json`/`core` edits.

## Self-review
- **Spec coverage:** module layout (Approach B) → Tasks 1–6; `news.json` schema → Task 6; resolve/validate/execute → Tasks 3–5; CommandResult + TTS shape (success/unavailable/not_found, failures silent) → Tasks 3,5 + G5; `newsfeed` contract (parse RSS/Atom, `_http_get` seam, `fetch_feed` never raises) → Tasks 1–2; testing (network mocked, multi-feed merge, graceful degrade, all-empty, cap, bucket rules) → Tasks 1–6; HA script + exposure → G6/G8; phased gates → G3–G8; rollback → summary tables. No gaps.
- **Placeholder scan:** every code step shows full code; no TBD/TODO; the Task 3 `execute` is an explicit `NotImplementedError` placeholder *by design*, replaced with full code in Task 5 (not a plan placeholder).
- **Type consistency:** `fetch_feed(feed, timeout, max_items)`, `_merge(per_feed, cap)`, `_spoken(bucket, items)`, `_chat(bucket, items)`, `resolve` return keys (`bucket_key`/`requested_label`/`feeds`/`headline_count`/`feed_timeout`/`max_items`) are used identically across Tasks 3–6 and the tests. `not_found` `chat_text` is verbatim-label ("I don't have Romania news set up yet.") consistently in Task 3 impl + tests + G5.
- Repo tests never touch the network (seam patched / fixtures) ✓. Inc 2B deferred ✓. BBC World only live feed ✓. Failures silent (`spoken_text=None`) ✓.
- **XML safety (stdlib-only, no `defusedxml`):** `parse` rejects `<!DOCTYPE`/`<!ENTITY` (Task 1, with a billion-laughs test) + `_http_get` size cap `_MAX_FEED_BYTES=2000000` (Task 2). Numeric-underscore 3.6-syntax trap called out ✓.
