# Inc 1 — Radio: Design Spec

**Date:** 2026-06-27
**Status:** Approved design (pre-implementation)
**Related:** [assistant-tooling-design.md](2026-06-27-assistant-tooling-design.md) (umbrella),
[local-music-architecture.md](local-music-architecture.md), [assistant-capabilities.md](assistant-capabilities.md),
plan: [plans/2026-06-27-inc1-radio.md](plans/2026-06-27-inc1-radio.md)

## Goal

Make radio a first-class, resolver-controlled capability: play stations by **name**, **country/place**,
**genre**, or **language**, and **discover** stations ("find jazz stations"). Favorites-first for
reliability, RadioBrowser for breadth, honest spoken feedback, and config-driven via `radio.json`.

## Approved decisions (refinements)

1. **Favorites first, then RadioBrowser.**
2. **"country radio" = the country-music genre** (a bare genre word → genre).
3. **Nationality/place phrases ("Romanian radio", "in Russia") → country/language.**
4. **Discovery speaks the top 3** stations; may log/return up to 5 internally.
5. **Route radio through the resolver**; keep the existing `script.ceiling_play_radio` as a working
   fallback until the new path passes validation.
6. **`radio.json` is the data source** for favorites, aliases, countries, languages, genre synonyms,
   and defaults.
7. **Dry-run validation mode** proves candidate selection/rejection with no sound, before any audible
   playback.
8. **Do not expose** the new radio capability to ChatGPT until direct resolver tests pass.

## RadioBrowser API contract (verified on host 2026-06-27)

MA's `radiobrowser` provider, via `music/browse` (arg `path`) and `music/search`:

- **Countries:** `radiobrowser://category/country` → folder items
  `{item_id: "<iso2>", name: "<English country>", path: "radiobrowser://category/country/<iso2>", media_type: "folder", is_playable: false}` (242 of them).
- **Country stations:** `radiobrowser://category/country/<iso2>` → items; the first is a `back` folder
  (`item_id == "back"`, skip it); station items are `{item_id: "<uuid>", name: "<station>",
  uri: "radiobrowser://radio/<uuid>", media_type: "radio", provider_mappings: [{provider_domain:
  "radiobrowser", available: true, ...}]}`.
- **Genres (tags):** `radiobrowser://category/tag` → 101 folders `{item_id: "<tag>", name: "<TAG>",
  path: ".../tag/<tag>"}`; stations at `radiobrowser://category/tag/<tag>`.
- **Languages:** `radiobrowser://category/language` → folders; stations at `.../language/<code>`.
- **Popularity:** `radiobrowser://popularity/popular` and `.../votes` → flat, ranked station lists
  (~1001).
- **Search:** `music/search {search_query, media_types: ["radio"], limit}` → result dict; `result["radio"]`
  is a ranked list mixing `provider:"library"` (favorites) first when they match, then
  `provider:"radiobrowser"`. Items share the station shape above (favorites' `uri` is
  `library://radio/<n>`).
- **Normalization:** station `name` may have leading/trailing whitespace/newlines — strip it. Treat an
  item as a playable station iff `media_type == "radio"`, `item_id != "back"`, and some
  `provider_mappings` entry has `available: true`.
- **Play:** `player_queues/play_media {queue_id, media: <uri>, option: "replace"}` with either
  `library://radio/<n>` (favorites) or `radiobrowser://radio/<uuid>`. *(Direct radiobrowser play is
  verified in the dry-run/validation tasks.)*
- **Ranking note (v1 limitation):** country/tag/language browse lists are NOT returned in popularity
  order and carry no vote count in the item. v1 uses favorites-first, then browse order (capped). A
  later increment may rank the fallback by cross-referencing `popularity/*`.

## `radio.json` data model

```json
{
  "favorites": [
    {"name": "101 SMOOTH JAZZ", "uri": "library://radio/2", "country": "us", "language": "en", "genres": ["jazz", "smooth jazz", "relax"]}
  ],
  "aliases": {"hit fm": "Hit FM (UKraine) - 128kb/s", "nashe": "Nashe Radio"},
  "country_codes": {"romania": "ro", "romanian": "ro", "russia": "ru", "russian": "ru", "ukraine": "ua", "ukrainian": "ua", "usa": "us", "america": "us", "uk": "gb", "england": "gb", "germany": "de", "france": "fr"},
  "languages": {"russian": "ru", "romanian": "ro", "english": "en", "ukrainian": "uk", "french": "fr", "german": "de"},
  "genre_synonyms": {"jazz": ["jazz", "smooth jazz"], "country": ["country"], "news": ["news", "talk", "actualitati"], "pop": ["pop", "top 40", "hits"], "rock": ["rock"], "relax": ["relax", "chillout", "ambient", "lounge"], "retro": ["retro", "oldies", "80s", "90s"], "dance": ["dance", "house", "electronic"]}
}
```

- All 17 current favorites are tagged (country/language/genres) in the plan.
- `country_codes` and `languages` map both place names and nationality words to codes.
- `genre_synonyms` maps a spoken genre to a canonical RadioBrowser tag + synonyms; favorites match on
  any synonym.
- `defaults` (optional) → `find_internal` (5), `find_speak` (3), `fallback_browse_limit` (10).

## Resolution algorithm — `radio.handle(ctx, params, rid)`

Params: `mode` ("play" | "find"), exactly one target of `station` (name) / `country` / `language` /
`genre`, and `dry_run` (bool).

1. **Classify the target** from which param is set.
2. **Build an ordered candidate list (favorites first):**
   - **name:** favorites whose name or alias matches (`match.match_rank`); then `music/search(name)`
     radio results.
   - **country:** resolve to ISO code via `country_codes`; favorites with `country == code`; then
     browse `category/country/<code>`.
   - **genre:** resolve to canonical tag + synonyms via `genre_synonyms`; favorites whose `genres`
     intersect; then browse `category/tag/<tag>`.
   - **language:** resolve via `languages`; favorites with `language == code`; then browse
     `category/language/<code>`.
   - Normalize names, drop `back`/unavailable, dedupe by uri, cap to `find_internal` (5).
3. **mode = play:** choose `candidates[0]`.
   - none → `ok=False`, `spoken="I couldn't find a station for <target>."` (honest failure).
   - `dry_run` → log the ranked candidates + chosen + reason; `ok=True, played=False`; **no play, no
     announce**.
   - else → `play_media(uri, option="replace")`; `ok=True, played=True` (no success announce — the
     station starts audibly; ChatGPT gives the text confirm).
4. **mode = find:** take top `find_speak` (3) for speech, log up to `find_internal` (5).
   - some → `ok=True`, `spoken="I found A, B and C."`, `speak_success=True`.
   - none → `ok=False`, `spoken="I couldn't find any stations for <target>."`.

## Capability result contract (extends Inc 0)

Same dict as Inc 0 (`ok`/`intent`/`request_id`/`spoken`/`reason` + extras). Adds:
- `speak_success` (bool) — when true, the dispatcher announces `spoken` even though `ok` is true
  (used by `find` to speak the list). `core.dispatch` gains: announce `spoken` when
  `speak_success` is set (success speech), else announce on failure as today.
- play extras: `uri`, `station`, `source` ("favorite" | "radiobrowser"), `played`.

## Tool surface (additive; NOT exposed to ChatGPT until validated)

- **Event:** `mass_radio_request` with data `{mode, station, country, language, genre, dry_run}`.
- **Resolver:** `event_to_call` maps it to `("radio", {...})`; `serve` subscribes (id 3); `core`
  routes intent `radio` → `radio.handle`.
- **HA scripts (created, left UNexposed to `conversation`):** `script.play_radio`
  (fields: station, country, genre, language) → fires `mass_radio_request` mode=play;
  `script.find_stations` (fields: genre, country) → mode=find. The existing `script.ceiling_play_radio`
  stays exposed and working as the fallback.
- **CLI (for dry-run + tests):** `resolver.py --radio --mode play|find [--station S | --country C |
  --genre G | --language L] [--dry-run]`.

## Build order

Per the plan ([plans/2026-06-27-inc1-radio.md](plans/2026-06-27-inc1-radio.md)): config/data → a
fakeable RadioBrowser client → favorites matching → the `radio` capability → `core` speak-success →
`resolver` wiring/CLI → deploy + **dry-run** validation → audible validation → expose to ChatGPT.
Repo-only TDD tasks run via subagents; host/deploy/restart/expose tasks stop for explicit approval.

## Constraints (carried from project rules)

- Python 3.5-safe; secrets only in 0600 files, never logged; additive/reversible; user runs sudo /
  restarts; no AI attribution in commits; secret-scan before commits; **do not expose new
  functionality to ChatGPT until validated** (here: until direct resolver dry-run + audible tests pass).
