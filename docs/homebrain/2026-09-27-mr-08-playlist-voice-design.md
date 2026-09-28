# MR-08 — Play curated playlists by voice (aliases + shuffle)

> **Status:** design, awaiting operator review. **Track:** MR (resolver). **Live surface:** resolver only — no HA
> script, automation, exposure or ChatGPT-tool change. **Relates to:** `MR-Inc4B` (sleep timer + shuffle/repeat +
> queue) — this item delivers *playlist* shuffle only; general shuffle/repeat/queue control stays in Inc4B.

## 1. Intent (agreed with the operator, 2026-09-27)

- **Goal:** "Okay Nabu, play Costea mix" plays that playlist on the ceiling; "Okay Nabu, shuffle Costea mix" plays
  it shuffled.
- **Model:** like radio favourites — playlists are found by their own name *and* by friendly spoken aliases that
  tolerate speech-to-text mangling.
- **Scope decided:** playlists the operator curates = **Music Assistant playlists** (created in MA, provider
  `builtin`) **and `.m3u` files** in the music share (provider `filesystem_smb`). **Not** MA's automatic playlists
  (random / recently added / favourites / infinite mix) — maybe later.
- **Shuffle decided:** in order by default; shuffled when the phrase asks for it.
- **Aliases decided:** automatic loose matching of the real name **plus** an optional alias table in resolver
  config (survives renames, edited on request).
- **Local-only rule unchanged:** only local, available tracks are ever played.

## 2. Problem today (verified 2026-09-27)

`music._resolve_type` accepts an item only if one of its provider mappings is in
`settings.provider_preference` (`["filesystem_smb"]`). Resolver dry-runs on the host:

- `costea-playlist` (`.m3u`, `filesystem_smb`) → `decision=ACCEPTED`.
- `my music - costea (local)` (MA playlist, `builtin`) → `decision=REJECTED reason=no-preferred-mapping`,
  although all 8 of its tracks are local FLAC/MP3 files.

Also found: **a dry-run can speak on the live ceiling.** The one-shot CLI (`resolver.py --query … --dry-run`) calls
`ha.announce` on a failure, and `core.dispatch` (the `/command` path, lines 100-105) speaks any failure's
`spoken_text` when `announce_failures` is on, regardless of `dry_run`. Observed 2026-09-27: a CLI dry-run of an
unmatched query logged `ANNOUNCE via tts.speak: Sorry, I couldn't find …`.

## 3. Design

### 3.1 Flow inside `MusicCapability.resolve`

1. **Normalise the phrase.** Case-insensitive, whole-word, edges only:
   - a leading `shuffle ` / `shuffled ` or a trailing ` on shuffle` / ` shuffled` → `shuffle_requested=True`, stripped;
   - a leading `the ` + trailing ` playlist` (or just ` playlist`) is stripped **when** `media_type=playlist` or an
     alias check follows (the agent sends "Costea mix playlist").
   - Empty remainder → no match (no guessing). **Fallback:** if the normalised query resolves to nothing, retry once
     with the **original** phrase and shuffle off, so a title like "Shuffle" (Bombay Bicycle Club) still plays.
2. **Playlist alias lookup.** New provider-neutral `favorites.match_alias(aliases, query)` → `(key, target)` or
   `None`; `resolve_alias` becomes a thin wrapper over it so radio behaviour is **unchanged** (existing radio tests
   guard it). For playlists the match is **exact on the normalised phrase** (and its compacted form, for spelled-out
   letters) — **not** substring: music queries span the whole library, and a short alias like "chill" must not
   swallow "Chill Out by X". List STT variants as separate alias keys instead. On a hit: query := target,
   **`types = ["playlist"]` only** (no fall-through to artist/album/track).
   - The alias target must match a playlist name **exactly** (normalised, rank 0) — never fuzzy — so a renamed or
     deleted target cannot land on a different playlist. No exact target → `not_found`, logged
     `alias-target-missing` (the alias maps a *name*; after a rename the alias is updated, it does not "survive").
3. **Resolution** — existing type order (`artist, album, track, playlist`, or the requested type first; `[playlist]`
   only after an alias hit). For `playlist`, a candidate is acceptable when either:
   - it has an available `filesystem_smb` mapping (today's behaviour, unchanged), **or**
   - it is a **curated MA playlist**: a `builtin` mapping whose `item_id` is **all digits**. MA's automatic lists
     use named ids (`random_tracks`, `infinite_mix`, …) and are therefore excluded without a config list, including
     any added by a future MA upgrade. Tracks are fetched **only for the top-ranked** such candidate, capped at
     **500**, and counted for an available `filesystem_smb` mapping:
     - **all local** → play the playlist URI;
     - **some local** → play **only the local tracks** (in playlist order);
     - **none local** → `resolve` returns a `rejected_no_local` marker (so `validate` can say *why*), unless another
       candidate/type matches.
   - Known limitation (not changed, to avoid regressing today's ranking): without an alias or the word "playlist",
     `playlist` is still tried last, so a fuzzy artist/track match wins over an exact playlist name. Aliases and
     "…playlist" cover the voice use case.
4. **Execute** (playlist hits only — artist/album/track plays are **unchanged**, no shuffle call):
   - set the queue shuffle **before** `play_media`, explicitly on or off (so the first track is already shuffled and
     an old state never leaks); a shuffle-call failure is logged and noted in `chat_text`, never a play failure;
   - `player_queues/play_media` with `option=replace`: the playlist URI, or the local-track URI list;
   - metadata keeps **`md["uri"]` a string** (the playlist URI) — `core.dispatch` feeds it to
     `interaction.note_playback`, which lowercases it — and puts a track list, if any, in `md["uris"]`;
   - **dry-run:** no shuffle call, no play, nothing spoken (see 3.5).

### 3.2 Config (`config.json`, non-secret)

```json
"playlist_aliases": {"costea mix": "my music - costea (local)", "costea mics": "my music - costea (local)"}
```

Optional; absent or empty → no aliases (no code change needed to disable). Read with `getattr(settings, …, default)`
so existing test fakes (`FakeSettings` in `test_core`/`test_music`) keep working unchanged.

### 3.3 Responses (CommandResult contract unchanged; success stays silent)

| Situation | `spoken_text` | `chat_text` | code |
|---|---|---|---|
| Playlist plays, all local | — | "Playing Costea mix." / "Playing Costea mix, shuffled." | ok |
| Mixed playlist | — | "Playing Costea mix — 6 of 8 tracks; 2 aren't in your local library yet." | ok |
| MA playlist, no local tracks (and nothing else matches) | "Costea mix has no songs in the local library yet." | same | not_found |
| No match | (unchanged) "Sorry, I couldn't find X in the local library." | (unchanged) | not_found |
| MA refuses to start | (unchanged) | (unchanged) | play_failed |
| Shuffle toggle fails after start | — | "Playing X (couldn't turn on shuffle)." | ok |

The spoken/chat name is the phrase the user used (alias key or the query), not the raw playlist name.
The "no songs in the local library" line is chosen by `validate` from the `rejected_no_local` marker; an alias whose
target is missing uses the ordinary "couldn't find" line. Log lines keep today's format and add `alias=…`,
`shuffle=…`, `local=N/M`, `alias-target-missing`.

### 3.4 Units touched

- `music.py` — normalisation + fallback, alias step, curated-playlist acceptance + local counting, execute changes.
- `maconn.py` — `playlist_tracks(item_id, provider, limit)`, `play(..., uris=list)`, `set_shuffle(queue_id, bool)`.
- `config.py` — load `playlist_aliases` (optional).
- `favorites.py` — factor `match_alias(aliases, query)`; `resolve_alias` wraps it (radio unchanged).
- `core.py` — do not speak when `params.dry_run` is set (fixes the `/command` dry-run).
- `resolver.py` — CLI: small `_should_announce(res, settings, dry_run)` helper (testable seam); never on dry-run.
- `tests/` — new `test_playlist.py` (+ additions to `test_core.py`, `test_config.py`, `test_favorites`/radio).

### 3.5 Dry-run is silent everywhere

Both the CLI and `/command` dry-runs must never speak, play, or touch shuffle — on success or failure. Deploy step 5
relies on this and runs only **after** the fix is live.

## 4. Testing

- **TDD** with the existing fake MA. New tests cover:
  - normalisation: leading/trailing shuffle, "…playlist" stripped, mid-phrase "shuffle" untouched, empty remainder;
    the title "Shuffle" still plays via the original-phrase fallback;
  - aliases: exact hit forces playlist-only; alias beats a same-named artist; an alias whose playlist is missing or
    has no local tracks returns `not_found` and does **not** fall through to an artist; a renamed target does not
    fuzzy-match a different playlist; a short alias does not hijack a longer unrelated query;
  - curated MA playlist (numeric id) accepted; each automatic list (named id) rejected;
  - all-local → playlist URI; mixed → local-track list in `md["uris"]`, `md["uri"]` still a string, note in chat;
    none-local → `not_found` with the "no songs" line; track fetch only for the top candidate, capped;
  - shuffle set **before** play, explicitly off when not requested; shuffle failure still ok; artist/album/track
    plays make **no** shuffle call;
  - through `core.dispatch`: a mixed-playlist play still sets the interaction playback flag;
  - dry-run (CLI via `_should_announce`, and `/command` via `core.dispatch`): never speaks, plays or shuffles;
  - existing fakes without the new attribute still pass; radio alias behaviour unchanged.
- **Whole existing suite green** (radio, news, interaction, status, config, core).
- **Mutation check:** break in turn the numeric-id rule, the local counting, the shuffle-off call, the dry-run guard
  and the alias playlist-only restriction; a test must fail for each.

## 5. Deploy and verification (operator-gated)

1. Claim the live gate (doc commit, per BACKLOG §8–9).
2. Timestamped backup of the resolver files on the host (`~/mass-resolver/.bak/<ts>/`).
3. Copy changed `*.py` + `config.json` (with the `costea mix` alias).
4. **Operator** restarts: `! ssh -t costea@192.168.1.68 'sudo systemctl restart mass-resolver'`.
5. Dry-runs **only after** the dry-run fix is deployed (§3.5): alias, curated MA playlist, `.m3u`, unknown — confirm
   in the log that nothing was announced.
6. **Live test with the operator present:** "Okay Nabu, play Costea mix" (in order), then "…shuffle Costea mix".
   Verified by resolver log (`PLAYING … shuffle=`), MA queue state (`shuffle_enabled`), and by ear.
7. CHANGELOG entry; update ONBOARDING current state + `assistant-capabilities.md`; release the live gate. Docs and
   code in separate commits.

**Rollback:** restore `.bak/<ts>/` and restart (≈1 min). Aliases alone: empty `playlist_aliases`.

## 6. Out of scope

MA automatic playlists; YouTube Music or any streaming playlist; a dedicated `shuffle` field on `script.play_music`
(add only if in-phrase detection proves unreliable in practice); repeat/queue control (Inc4B); Plex/remote
listening.

## 7. Risks and assumptions to verify during implementation

- The agent passes the user's words through as `query` (documented behaviour); if it drops "shuffle", shuffle won't
  trigger — detected in the live test, remedy is the out-of-scope field.
- Exact MA API shapes (`music/playlists/playlist_tracks` paging, `player_queues/play_media` accepting a URI list,
  the shuffle command name `player_queues/shuffle`) are confirmed against the running MA before coding the adapter.
- The curated-playlist mapping is expected to be `builtin` with a numeric `item_id` (observed: auto lists use named
  ids); confirmed on the live playlist `my music - costea (local)` (item_id 28) before relying on it.
- Setting shuffle before `play_media(replace)`: confirm on the live MA that the new queue honours it (otherwise set it
  immediately after and accept that the first track is unshuffled — record which).
- Review: an independent agent review (2026-09-27) found the dry-run speaking on `/command`, the list-URI breakage
  of `note_playback`, the alias fall-through and fuzzy-target risks, and shuffle-after-start; all folded in above.
