# Inc 2A — Spoken News Headlines (Design)

**Date:** 2026-06-29
**Status:** **Approved design (pre-implementation).** Full Inc 2 News surface designed; **only Inc 2A
(spoken RSS headlines) is implemented** this increment. Stop for approval at each gate before host
access, HA changes, restarts, or exposure.
**Related:** [assistant-tooling-design.md](2026-06-27-assistant-tooling-design.md) (umbrella §4
`news — get_news(country, topic, mode)`, §5 `news.json`, §7 Inc 2), [F1
design](2026-06-28-F1-synchronous-command-result-design.md) (§2 `CommandResult`, §3 capability
lifecycle), [F1-R addendum](2026-06-28-F1-R-chatgpt-tool-result-relay-design.md) (hard tool return),
[Inc 4A design](2026-06-29-inc4a-status-now-playing-design.md) + [Inc 4A
plan](plans/2026-06-29-inc4a-status-now-playing.md) (the latest proven capability pattern),
[assistant-capabilities.md](assistant-capabilities.md), [ONBOARDING.md](ONBOARDING.md).
**Build reference / plan:** [plans/2026-06-29-inc2a-news-headlines.md](plans/2026-06-29-inc2a-news-headlines.md).

## Locked decisions (approved 2026-06-29)
1. **First slice = Inc 2A: spoken world-news headlines** from curated public RSS, fetched + parsed with
   Python 3.5 **stdlib only** (`urllib` + `xml.etree`). No API key, no new third-party dependency, no
   secrets.
2. **Inc 2B (news-station playback) is DEFERRED.** The existing `play_radio` already plays stations by
   **genre** (`radiobrowser://category/tag/<tag>`) and **country**; `"news"` is just a genre tag, so
   "play news radio" / "play Romanian news radio" is already covered today. Rebuilding it in `news.py`
   would duplicate RadioBrowser logic. Captured here as a follow-up slice; **not built** in Inc 2A. *(The
   radio-news-genre claim will be verified live before any future reliance; it is not relied on by 2A.)*
3. **Coverage = World / English only** (one `world` bucket). Expand to more buckets/languages later as a
   pure `news.json` data edit — no code change.
4. **Headline count = configurable in `news.json`, default 3.**
5. **Verbatim feed titles** (cleaned of whitespace / HTML entities). No summarization, no LLM.
6. **Feed = BBC World only** (`http://feeds.bbci.co.uk/news/world/rss.xml` — plain HTTP, TLS-safe on the
   host's old Python/OpenSSL). Reachability from the host is verified at a gated read-only check before
   deploy; multi-feed merge + graceful degradation are built and tested from day one regardless.
7. **Module structure = Approach B:** `news.py` (`NewsCapability`) + `newsfeed.py` (pure stdlib
   fetch/parse seam). Keep `newsfeed.py` small; do not split further unless tests prove the need.

---

## 1. Scope

Inc 2 in the umbrella roadmap is "News — `news.json` sources; stations + headlines/TTS." This increment
designs the **full surface** (headline mode + station mode) and **implements only Inc 2A** (spoken
headlines). Inc 2B (curated news-station playback) is **deferred** (decision 2) and recorded as a
follow-up slice.

The priority is the **deterministic executor**: fetch curated RSS → parse → normalize → merge/cap →
return a reliable `CommandResult`. The language layer stays thin (ChatGPT + the tool description map
"read me the news" / "what's the news" onto the `news` tool).

---

## 2. Module layout (Approach B)

```
news.py      — NewsCapability(capability.Capability): resolve -> validate -> execute -> CommandResult.
               Normalizes params + config (resolve), checks the configured bucket/feeds (validate),
               and performs fetch/parse/merge/cap + builds the result (execute). Reads news.json; sets
               spoken_text (Piper) + chat_text (hard tool return). No raw network / XML in this file.
newsfeed.py  — pure RSS/Atom source client, stdlib only: urllib fetch (explicit timeout) + xml.etree
               parse + whitespace/entity cleanup -> normalized {title, link, source}. No Home Assistant
               or resolver imports / side effects. Network behind a mockable seam so unit tests use
               fixture XML and never touch the live network.
news.json    — config/data: defaults + feeds per bucket (+ inert "stations" placeholder for 2B).
```

This mirrors the established `radio.py` (capability) ↔ `radiobrowser.py` (source client) +
`favorites.py` split, and the Inc 4A `status.py` capability shape.

**Core wiring (real-code shape, mirrors Inc 4A):**
- `news.py` currently is a **legacy stub** (`get_news(ctx, params, rid)` returning an old-style dict,
  wired only via `core._STUBS`). Inc 2A **replaces it** with `class NewsCapability(capability.Capability)`
  (`name="news"`).
- `core.py`: add `import news`; set `CAPS["news"] = news.NewsCapability()`; **remove `"news"` from
  `_STUBS`**.
- The HTTP `/command` adapter (`http_server.py`) already routes any registered intent to `dispatch`, so
  **no adapter change** is required once `news` is in `CAPS`.
- **No legacy event-path wrapper** for news (no `mass_news_request` event adapter) — news is a
  request/response capability invoked via `/command`, like Inc 4A status.

---

## 3. `news.json` schema

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

- **`defaults.headline_count`** — number of headlines spoken/relayed (default **3**; tunable with no code
  change). **`defaults.feed_timeout`** — per-feed fetch timeout in seconds. **`defaults.max_items_per_feed`**
  — cap on items parsed per feed (bounds parse work; merge then caps globally at `headline_count`).
- **`feeds`** — bucket name → list of `{name, url}`. `name` is the human source label (attribution +
  logging). A multi-feed bucket is just a longer list. Only **`world`** is curated/live in v1.
- **`stations`** — stays `{}` in v1; reserved for the deferred Inc 2B station path. Ignored by 2A code.

This extends the existing scaffold (`{"feeds": {"world":[], "romania":[], "russia":[]}, "stations":{}}`)
by (a) populating `world` with BBC, (b) adding the `defaults` block, and (c) using `{name,url}` feed
objects instead of bare URL strings. The previously-empty `romania`/`russia` keys are **removed** in v1
(coverage is World/English-only); they return as data edits when those languages are curated. (An empty
or unconfigured bucket is handled honestly — see §4.)

---

## 4. `NewsCapability` lifecycle

### `resolve(ctx, params)` — normalize params + config only (no network)
- Read `news_cfg = ctx.news_cfg or {}`; pull `defaults` (`headline_count`, `feed_timeout`,
  `max_items_per_feed`) with safe fallbacks.
- **Bucket selection (decision 2 of the change-set):**
  - Determine the **requested label** = `params.get("topic")` or `params.get("country")` (lowercased,
    trimmed), if either was supplied.
  - **No topic/country supplied** → `bucket_key = "world"`, `requested_label = None` (the default bucket).
  - **Explicit label supplied:**
    - if it matches a key in `feeds` → `bucket_key = <that key>`.
    - if it does **not** match any configured bucket → `bucket_key = None`, keep `requested_label`
      (so `validate` rejects it honestly — we do **not** silently fall back to `world` for an explicit
      unsupported request).
- Return `{bucket_key, requested_label, feeds: feeds.get(bucket_key) or [], headline_count,
  feed_timeout, max_items}`. **No fetching in resolve.**

### `validate(ctx, resolved)` — check the configured bucket/feeds
- If `bucket_key is None` (explicit unrecognized topic/country) → **`not_found`**, honest message
  `"I don't have <Label> news set up yet."` (`<Label>` = the requested label, title-cased; generic
  `"that"` if somehow absent). `spoken_text=None` (failures do not speak — see §5).
- Else if the selected bucket has **zero configured feeds** → **`not_found`**, `"I don't have that news
  set up yet."`, `spoken_text=None`.
- Else → `None` (proceed to execute).

### `execute(ctx, resolved, rid)` — fetch / parse / merge / cap → `CommandResult`
1. For each feed in `resolved["feeds"]`: call `newsfeed.fetch_feed(feed, feed_timeout, max_items)`.
   This returns a normalized `[{title, link, source}]` or **`[]` on any failure** (never raises). Track
   `feeds_ok` / `feeds_failed` counts.
2. **Merge:** round-robin across the per-feed item lists (so every source is represented when there are
   several), **dedupe** by normalized lowercased title, **cap** at `headline_count`.
3. **≥ 1 headline →** `cr.ok` (success result, §5).
4. **0 headlines** (every feed failed/empty) → `cr.err(self.name, rid, "unavailable", reason,
   chat_text, spoken_text=None, metadata=...)` (§5).

**Graceful degradation (tested with multiple feeds even though v1 seeds one):** a single feed timing
out / HTTP-erroring / returning unparseable XML contributes `[]`; the request still **succeeds** if any
other feed yields items. Only an **all-empty** outcome is a failure.

---

## 5. `CommandResult` + TTS shape

Follows the live F1 contract (`command_result.ok()/err()` → `{ok, intent, request_id, spoken_text,
chat_text, error, metadata, actions}`; `err()` rejects codes outside the enum). `intent = "news"`.

News **speaks on success** (unlike silent Inc 4A status) — the same dual-output as `find_stations`:
the resolver speaks `spoken_text` via Piper (`core.dispatch` is the sole TTS owner and speaks an `ok`
result's `spoken_text`), and ChatGPT relays `chat_text`. The ChatGPT pipeline's own TTS is off, so
there is no double audio (proven with `find_stations`).

**Failures never speak.** Both error paths set `spoken_text = None`, so a "what's the news?" query can
never speak an RSS/network error into the room. ChatGPT relays the honest `chat_text` as the only
feedback. (This is the deliberate difference from music's spoken no-match: news errors are silent.)

### Success (headlines found)
```json
{
  "ok": true, "intent": "news", "request_id": "ab12cd34",
  "spoken_text": "Here are the top world headlines. <title1>. <title2>. <title3>.",
  "chat_text": "Top world headlines: 1) <title1> 2) <title2> 3) <title3>",
  "error": null,
  "metadata": {
    "bucket": "world", "count": 3,
    "items": [ {"title": "<title1>", "link": "<url1>", "source": "BBC World"},
               {"title": "<title2>", "link": "<url2>", "source": "BBC World"},
               {"title": "<title3>", "link": "<url3>", "source": "BBC World"} ],
    "feeds_ok": 1, "feeds_failed": 0
  },
  "actions": []
}
```
- **`spoken_text`**: `"Here are the top <bucket> headlines. "` + verbatim titles joined by `". "` + `"."`
  (Piper-friendly; for the `world` bucket this is exactly *"Here are the top world headlines. …"*).
- **`chat_text`**: `"Top <bucket> headlines: "` + `"1) <t1> 2) <t2> 3) <t3>"` (relayed verbatim by
  ChatGPT).
- **`metadata`**: `bucket`, `count`, `items` (each `{title, link, source}`), `feeds_ok`, `feeds_failed`.
- Spoken length stays sane via the `headline_count` cap (default 3 verbatim titles).

### No headlines / fetch failure (all feeds failed or empty)
```json
{ "ok": false, "intent": "news", "spoken_text": null,
  "chat_text": "Sorry, I couldn't get the news right now.",
  "error": { "code": "unavailable", "reason": "no headlines (feeds failed/empty)" },
  "metadata": { "bucket": "world", "count": 0, "items": [], "feeds_ok": 0, "feeds_failed": 1 },
  "actions": [] }
```

### Bucket not configured (explicit unrecognized topic/country, or empty bucket)
```json
{ "ok": false, "intent": "news", "spoken_text": null,
  "chat_text": "I don't have Romanian news set up yet.",
  "error": { "code": "not_found", "reason": "bucket not configured" },
  "metadata": { "requested": "romania" }, "actions": [] }
```

**Field rules.** `ok` = `true` only when ≥1 headline was assembled. `error.code` ∈ the live enum:
**`unavailable`** (feeds unreachable / all empty) and **`not_found`** (bucket not configured). No
`invalid_input` (no params to reject in v1). `spoken_text = None` on **all** error paths.

---

## 6. `newsfeed.py` contract (pure, stdlib-only, mockable seam)

- **`_http_get(url, timeout)`** — the **mockable network seam**: `urllib.request.urlopen(url,
  timeout=timeout)` → response bytes, **capped at `_MAX_FEED_BYTES` (2000000 ≈ 2 MB)** via
  `resp.read(_MAX_FEED_BYTES)` so an oversized/malicious payload can't exhaust memory. Unit tests patch
  this; it is the *only* place that touches the network. *(Note: write `2000000`, not `2_000_000` —
  numeric underscores are a Python 3.6+ syntax error and the host runs 3.5.2.)*
- **`parse(xml_bytes)` → `[{title, link}]`** — handles **RSS** (`channel/item` with `<title>`/`<link>`)
  and **Atom** (`feed/entry` with `<title>` and `<link href=...>`). Cleans each title: collapse
  whitespace, `html.unescape` HTML entities. Returns `[]` on any parse error.
  - **XML safety (stdlib-only defense-in-depth).** `defusedxml` is a third-party dependency and is
    **disallowed by the no-new-deps constraint**, so instead `parse` **rejects (returns `[]`) any input
    containing a `<!DOCTYPE` or `<!ENTITY` declaration** *before* it reaches the expat parser. Both the
    billion-laughs / quadratic-blowup entity-expansion DoS and XXE require such a declaration, and
    well-formed RSS/Atom feeds never contain one (XML keywords are case-sensitive + always uppercase, so
    a plain byte search is exact). `xml.etree` additionally does **not** resolve *external* entities by
    default. Combined with the `_http_get` size cap, this bounds parser exposure with no new dependency.
- **`fetch_feed(feed, timeout, max_items)` → `[{title, link, source}]`** — composes `_http_get` +
  `parse`, attaches `source = feed["name"]`, truncates to `max_items`. Returns **`[]` on any exception**
  (timeout / HTTP error / parse error), logging the failure. **Never raises** (this is what makes
  graceful degradation possible).
- **No HA / resolver imports**, no side effects. Non-ASCII titles are handled as unicode; any console/log
  output of titles uses `.encode("ascii", "replace")` (Windows-console + host-console safety).

---

## 7. Testing (repo, TDD, stdlib `unittest`, network fully mocked)

`python tests/test_newsfeed.py` and `python tests/test_news.py` from `mass-resolver/`, plus the full
suite. **No test touches the live network** — `_http_get` is patched / fixture XML is fed directly.

**`tests/test_newsfeed.py`:** RSS parse → titles/links; Atom parse (`<link href>`); whitespace + HTML
entity cleanup; non-ASCII title preserved; malformed/empty XML → `[]`; **`<!DOCTYPE`/`<!ENTITY` payload
rejected → `[]`** (billion-laughs / XXE guard); `_http_get` patched to raise (timeout/HTTP) →
`fetch_feed` returns `[]`; `max_items` truncation; `source` attached from feed name.

**`tests/test_news.py`:** single-feed success (fixture) → correct `spoken_text`/`chat_text`/`metadata`;
**multi-feed merge** (round-robin) + **dedupe by title**; **one feed fails, another succeeds →
graceful-degrade success** with `feeds_ok=1, feeds_failed=1`; **all feeds empty/failed → `unavailable`,
`spoken_text=None`**; `headline_count` cap/truncation; **no param → `world`**; **explicit unrecognized
topic/country → `not_found`** with "I don't have <Label> news set up yet." and `spoken_text=None`;
**empty configured bucket → `not_found`**; `CommandResult` shape (`ok/spoken_text/chat_text/metadata/
error`). Update `tests/test_stubs.py` (news removed from `_STUBS`).

**Exit criteria:** every row green on a 3.5-compatible interpreter; full suite green.

---

## 8. HA tool + exposure

### New `script.news` (created only at the gated step)
Brand-new **`script.news`** (proposed alias `Ceiling: News Headlines (resolver)`), **no fields** in v1
(world default), hard-return pattern:
```jsonc
[
  {"action": "rest_command.resolver_command",
   "data": {"intent": "news", "params": {}},
   "response_variable": "r", "continue_on_error": true},
  {"variables": {"resp": {"chat_text": "{{ r.content.chat_text if (r is defined and r.content is defined and r.content.chat_text is defined) else 'Sorry, I could not get the news right now.' }}"}}},
  {"stop": "done", "response_variable": "resp"}
]
```
- **No `set_conversation_response`. No `tts.speak`.** Resolver stays the sole TTS owner (it speaks the
  headlines via Piper on success; the script only relays `chat_text`). Reuses the live
  `rest_command.resolver_command` (30 s, `X-Resolver-Key`) — **no new HA REST command, no agent-
  instruction change, no event adapter.**

### Exposure (separate, explicitly-approved gate — not in the build phases)
On approval: expose `script.news` to the `conversation` assistant; update `assistant-capabilities.md`
(remove **News** from the "Not available yet" table, add a **NEWS** capability line + routing rule + a
concise Instructions block) **in lockstep**; tool count **12 → 13**. Raw `media_player.*` / MA entities
remain unexposed.

---

## 9. Phased gates (mirror Inc 4A / Inc 1)

| Phase | What | Location | Gate |
|---|---|---|---|
| 1 | Design doc (this) | repo | none |
| 2 | Repo TDD: `newsfeed.py` + `NewsCapability` + `core` wiring + `news.json`; full suite green; network mocked | repo | none |
| 3 | **Host network-reality check** (read-only: confirm the host reaches the BBC feed on its Python 3.5.2 / old OpenSSL; record status + a sample title count) | host | 🔴 read-only host/SSH — approval |
| 4 | Host deploy (`news.py`, `newsfeed.py`, `news.json`, `core.py`) + resolver restart; timestamped `.inc2-bak/` backup; `py_compile` clean; `/command` 200/401; no-regression smoke of music/radio/find/status | host | 🔴 deploy + restart — approval |
| 5 | Direct `/command` (`intent=news`): truthful `CommandResult`; headlines **speak once** via Piper; failure path honest + **silent**; no regression | host | read-only validate |
| 6 | Create `script.news` + `script.reload`; structural readback (hard return `{chat_text}`, **no `tts.speak`**, **no `set_conversation_response`**, no fields); **not exposed** | HA | 🔴 modify HA — approval |
| 7 | Script hard-return (`return_response=true`) `{chat_text}` == Phase-5 `/command` `chat_text` | host/HA | validate |
| 8 | **Expose** `script.news`; update `assistant-capabilities.md` + Instructions in lockstep (12 → 13); conversational validation | HA | 🔴 SEPARATE exposure approval |

---

## 10. Rollback

- **Repo (atomic):** `git revert` of the Inc 2A commit — restore the `news.py` stub, **drop `news` from
  `core.CAPS`**, **re-add `"news"` to `core._STUBS`**, remove `newsfeed.py`, revert `news.json`. (A
  half-revert that leaves `core` referencing a missing handler is invalid — revert all together.)
- **Host (live):** restore from the timestamped `~/mass-resolver/.inc2-bak/<ts>/` backup. A resolver
  restart to load the rollback is **approval-gated** (user-run), never automatic. `/command`, the event
  adapter, `mass_sync_request`, and the existing scripts are unaffected by a news-only revert.
- **HA:** `script.news` is brand-new → **delete it + `script.reload`** (no existing script touched). No
  resolver rollback is needed for a script-only failure (`/command` is independent).
- **Exposure:** un-expose via `homeassistant/expose_entity` + revert the `assistant-capabilities.md` /
  Instructions edits.

---

## 11. Out of scope (explicit)

Inc 2B (curated news-station playback — **deferred**; `play_radio` already covers news stations by
genre/country); Inc 3 / Lidarr acquisition; Inc 4B (sleep timer, shuffle favorites); YouTube Music; the
RadioBrowser station-name tidy backlog item; any model change (gpt-4o-mini stays); any
transport/volume/PCL work; and any change to `play_music` / `play_radio` / `find_stations` /
`media_status`, the event adapter, `mass_sync_request`, or MA/HA config **beyond** creating the one new
(initially-unexposed) `script.news` and the `news.py` / `newsfeed.py` / `news.json` + `core`-registration
edits.

---

## 12. Risks & unknowns

- **Host network reachability / old TLS (the one real unknown).** Ubuntu 16.04 / Python 3.5.2 has an old
  OpenSSL; modern HTTPS feeds may fail cert/TLS. BBC's feed is plain **HTTP**, sidestepping TLS, and
  egress reachability is confirmed at the **Phase-3 read-only gate** before deploy. If even the HTTP
  feed is unreachable from the host, the honest `unavailable` path still applies and we revisit feed
  choice with the user.
- **Piper length.** Capped by `headline_count` (default 3 verbatim titles) — a sane spoken clip.
- **Feed format drift.** `newsfeed.parse` handles RSS + Atom and returns `[]` on anything unparseable →
  graceful degrade, never a crash.
- **Untrusted XML (XXE / billion-laughs).** Mitigated stdlib-only (no `defusedxml`, per the no-new-deps
  constraint): `parse` rejects any `<!DOCTYPE`/`<!ENTITY` declaration before parsing, `_http_get` caps
  the read at ~2 MB, and `xml.etree` does not resolve external entities by default (§6). Feeds are
  curated/trusted (BBC) regardless; this is defense-in-depth.
- **Model routing.** gpt-4o-mini must pick `news` for "read me the news"; mitigated by a clear tool
  description + Instructions block at the (separate) exposure gate. No model change.
- **Latency.** One small HTTP GET with a per-feed timeout, well under the 30 s `rest_command` budget.

## Self-review
- Approach B (capability + small stdlib seam); `newsfeed.py` not split further ✓.
- resolve = normalize only; validate = bucket/feed check; execute = fetch/parse/merge/cap + build ✓.
- Bucket fallback: absent param → world; **explicit unrecognized → `not_found`** (no silent world
  fallback) with honest "I don't have <Label> news set up yet." ✓.
- Unavailable: `ok=false`, `error.code="unavailable"`, `chat_text="Sorry, I couldn't get the news right
  now."`, **`spoken_text=null`** (failures don't speak) ✓.
- Success wording + metadata (`bucket`, `count`, `items{title,link,source}`, `feeds_ok`, `feeds_failed`)
  ✓.
- Inc 2B deferred ✓; BBC World only live feed ✓; multi-feed merge + graceful degrade built & tested ✓.
- Real-code shape: `NewsCapability` + `CAPS` add + `_STUBS` removal; atomic rollback; restart never
  implied automatic ✓.
- Repo tests never hit the network (mockable seam) ✓; Python 3.5-safe (no f-strings, stdlib `unittest`,
  ascii-safe console) ✓.
- Exposure stops at validated-but-unexposed; ChatGPT exposure is a separate approved gate ✓.
- **No implementation performed — design only.**
