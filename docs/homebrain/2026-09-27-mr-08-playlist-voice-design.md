# MR-08 — Play curated playlists by voice (with aliases)

> **Status:** design, revised after two independent reviews; awaiting operator review. **Track:** MR (resolver).
> **Live surface:** resolver only — no HA script, automation, exposure or ChatGPT-tool change.
> **Follow-up:** `MR-08b` — shuffle via an explicit `shuffle` field on `script.play_music` (§7). **Relates to:**
> `MR-Inc4B` (sleep timer + shuffle/repeat + queue).

## 1. Intent (agreed with the operator, 2026-09-27)

- **Goal:** "Okay Nabu, play Costea mix" plays that playlist on the ceiling.
- **Model:** like radio favourites — a playlist is found by its own name *and* by friendly spoken aliases.
- **Scope:** playlists the operator curates = **Music Assistant playlists** (created in MA) **and `.m3u` files** in
  the music share. **Not** MA's automatic playlists (random / recently added / favourites / infinite mix).
- **Aliases:** automatic loose matching of the real name **plus** an optional alias table in resolver config,
  updated on request (an alias maps a *name*; after a rename the alias is updated).
- **Local-only rule unchanged:** only local, available tracks are played.
- **Shuffle:** deferred to `MR-08b` (operator decision: the agent's `query` is described as a plain title/name, so
  an in-phrase "shuffle" would likely be dropped; a proper field needs an HA change).

## 2. Problem today (verified 2026-09-27)

`music._resolve_type` accepts an item only if one of its provider mappings is in `settings.provider_preference`
(`["filesystem_smb"]`). Host dry-runs: `costea-playlist` (`.m3u`) → `ACCEPTED`; `my music - costea (local)` (MA
playlist, `builtin`, 8 local tracks) → `REJECTED reason=no-preferred-mapping`.

**A dry-run can speak on the live ceiling:** the one-shot CLI (`resolver.py --query … --dry-run`) calls
`ha.announce` on a failure, and `core.dispatch` (lines 100-105, the `/command` path) speaks any `spoken_text` when
`announce_failures` is on, regardless of dry-run. Observed 2026-09-27 (`ANNOUNCE via tts.speak: Sorry, I couldn't
find …` from a CLI dry-run).

## 3. Design

"Normalised" throughout = `match.clean()` then, for the compacted comparison, `match.compact()` — so case,
punctuation and apostrophes ("Costea's mix") behave predictably.

### 3.1 Flow inside `MusicCapability.resolve`

1. **Normalise the phrase.** Strip a leading `the ` and a trailing ` playlist` (whole word, edges only). If a
   trailing ` playlist` was present, `playlist` is tried **first** in the type order (like `media_type=playlist`
   does today). Empty remainder → no match.
2. **Alias lookup.** New provider-neutral `favorites.match_alias(aliases, query)` → `(key, target)` or `None`;
   `resolve_alias` becomes a thin wrapper over it so radio behaviour is unchanged (existing radio tests guard it).
   For playlists the match is **exact** on the normalised phrase or its compacted form (spelled-out letters) — **no
   substring**, so a short alias like "chill" cannot swallow "Chill Out by X"; STT variants are listed as extra
   keys. On a hit: query := target and **`types = ["playlist"]` only** — never falls through to artist/album/track.
   The target must match a playlist name **exactly** (normalised) — never fuzzy — so a renamed/deleted target can't
   land on a different playlist. No exact target → `not_found`, logged `alias-target-missing`.
3. **Resolution** — the existing type order (`artist, album, track, playlist`; the requested/first type moved to the
   front; `[playlist]` only after an alias hit). Each type's library is fetched **once per resolve** (cached) so
   nothing is re-scanned. For `playlist`, a candidate is acceptable when either:
   - it has an available `filesystem_smb` mapping — `.m3u`, **today's behaviour, unchanged**; or
   - it is a **curated MA playlist**: a `builtin` mapping whose `item_id` is **all digits**. MA's automatic lists
     use named ids (`random_tracks`, `infinite_mix`, …) and are excluded without a config list, including any a
     future MA version adds. Tracks are fetched **only for the top-ranked** curated candidate, capped at **500**,
     keeping those with an available `filesystem_smb` mapping (playlist order).
     - **≥1 local track** → accepted; it will play **only those local tracks** (see 3.1-4).
     - **0 local tracks** → `resolve` returns a `rejected_no_local` marker. Because tracks are fetched only for the
       top curated candidate and `playlist` is searched last, "another candidate matches" means in practice only an
       `.m3u` of a similar name.
   - **Known limitation (kept, to avoid regressing today's ranking):** without an alias or "…playlist", `playlist`
     is still tried last, so a fuzzy artist/track match wins over an exact playlist name. Aliases and "…playlist"
     cover the voice use case.
4. **Execute.**
   - Curated MA playlist → `player_queues/play_media(option=replace)` with the **local-track URI list** — always,
     even when every track is local. Playing the playlist URI would let MA pick a source per track (a library track
     that also has a YouTube Music mapping could stream from YTM); the list guarantees local playback and gives one
     code path.
   - `.m3u`, artist, album, track → unchanged.
   - Metadata: **`md["uri"]` stays a string** (the playlist URI) — `core.dispatch` passes it to
     `interaction.note_playback`, which lowercases it for the reply-clip guard — and the list goes in `md["uris"]`.
   - Dry-run: no play, nothing spoken (3.4).

### 3.2 Config (`config.json`, non-secret)

```json
"playlist_aliases": {"costea mix": "my music - costea (local)", "costea mics": "my music - costea (local)"}
```

Optional; absent/empty → no aliases. Read with `getattr(settings, "playlist_aliases", {})` so the existing test
fakes (`FakeSettings` in `test_core`/`test_music`) keep working.

### 3.3 Responses (CommandResult contract unchanged; success stays silent)

| Situation | `spoken_text` | `chat_text` | code |
|---|---|---|---|
| Curated/`.m3u` playlist plays, all local | — | "Playing Costea mix." | ok |
| Curated playlist, some tracks not local | — | "Playing Costea mix — 6 of 8 tracks; 2 aren't in your local library yet." | ok |
| Curated playlist, no local tracks (nothing else matches) | "Costea mix has no songs in the local library yet." | same | not_found |
| No match / alias target missing | (unchanged) "Sorry, I couldn't find X in the local library." | (unchanged) | not_found |
| MA refuses to start | (unchanged) | (unchanged) | play_failed |

The name used is the phrase the user said (alias key or query). `validate` picks the "no songs" line from the
`rejected_no_local` marker. Logs keep today's format and add `alias=…`, `local=N/M`, `alias-target-missing`.

### 3.4 Dry-run is silent everywhere

- `core.dispatch`: do not speak when **`params.dry_run` or `settings.dry_run`** is set (music already honours both).
  **Cross-capability effect:** radio `find` dry-runs, which today speak even on success, also go silent — intended;
  covered by a new radio test.
- `resolver.py` CLI: a small `_should_announce(res, settings, dry_run)` helper (testable seam) that is never true on
  dry-run.
- Deploy step 5 relies on this and runs only **after** the fix is live.

### 3.5 Units touched

- `music.py` — normalisation, alias step, library cache, curated-playlist acceptance + local list, execute path.
- `maconn.py` — `playlist_tracks(item_id, provider, limit)`, `play(..., uris=list)`.
- `config.py` — optional `playlist_aliases`.
- `favorites.py` — factor `match_alias(aliases, query)`; `resolve_alias` wraps it.
- `core.py` — dry-run speak guard. `resolver.py` — `_should_announce` helper.
- `tests/` — new `test_playlist.py`; additions to `test_core.py`, `test_config.py`, radio/favorites tests.

## 4. Testing

- **TDD** with the existing fake MA. New tests:
  - normalisation: "the … playlist" stripped; trailing "playlist" moves playlist first; empty remainder;
    `clean`/`compact` equivalence ("Costea's mix" = "costeas mix");
  - aliases: exact hit forces playlist-only; beats a same-named artist; alias to a missing or no-local playlist →
    `not_found`, **no** fall-through to an artist; a renamed target does not fuzzy-match another playlist; a short
    alias does not hijack a longer unrelated query; compacted (spelled-out) key matches;
  - curated MA playlist (numeric id) accepted; each automatic list (named id) rejected;
  - curated playlist always plays the local-track list (all-local and mixed), `md["uri"]` a string, `md["uris"]`
    the list, mixed → note in `chat_text`; none-local → `not_found` with the "no songs" line; tracks fetched only for
    the top candidate and capped; library fetched once per resolve;
  - through `core.dispatch`: a curated-playlist play sets the interaction playback flag;
  - dry-run: `core.dispatch` (params and settings flags) and CLI `_should_announce` never speak; radio `find`
    dry-run silent;
  - existing fakes without `playlist_aliases` pass; radio alias behaviour unchanged.
- **Whole existing suite green** (radio, news, interaction, status, config, core).
- **Mutation check:** break in turn the numeric-id rule, the local-track filter, the alias playlist-only restriction,
  the exact-target rule and the dry-run guard; a test must fail for each.

## 5. Deploy and verification (operator-gated)

1. Claim the live gate (doc commit, per BACKLOG §8–9).
2. Timestamped backup of the resolver files on the host (`~/mass-resolver/.bak/<ts>/`).
3. Copy changed `*.py`. For `config.json`: **diff host vs repo first** and merge only the `playlist_aliases` key, so
   host-only settings survive.
4. **Operator** restarts: `! ssh -t costea@192.168.1.68 'sudo systemctl restart mass-resolver'`.
5. Dry-runs **only after** step 4: alias, curated MA playlist, `.m3u`, unknown — confirm in the log that nothing was
   announced.
6. **Live test with the operator present:** "Okay Nabu, play Costea mix". Verified by the resolver log (`PLAYING …
   local=8/8`), the MA queue (8 local items), and by ear.
7. CHANGELOG; update ONBOARDING current state + `assistant-capabilities.md`; release the live gate. Docs and code in
   separate commits.

**Rollback:** restore `.bak/<ts>/` and restart (≈1 min). Aliases alone: empty `playlist_aliases`.

## 6. Known limitation — resume of a mixed playlist (operator decision: document)

After a satellite reply interrupts playback, `interaction._resume` (interaction.py ~408) replays the remembered
`md["uri"]` via HA `music_assistant.play_media`. For a curated playlist that is the **playlist URI**, so a resume
plays the whole playlist through MA's own source choice — including any non-local tracks (and possibly a YTM
source). Curated playlists are all-local in practice, so this is documented rather than fixed here; a follow-up
gives resume a local-only reference (a re-resolvable resolver query or the stored local URI list).

## 7. Out of scope → follow-ups

- **`MR-08b` shuffle:** add an explicit `shuffle` boolean to `script.play_music` (gated HA script + tool change,
  per-script backup). Design notes carried over from review: set shuffle **before** `play_media`; set it
  **explicitly on every music play** (off unless a shuffled playlist was asked for) because it is a persistent MA
  queue setting that would otherwise leak into later album/artist plays; a failed shuffle call is non-fatal and
  reported as "couldn't set shuffle".
- Resume local-only fix (§6). MA automatic playlists. YTM/streaming playlists. Repeat/queue (Inc4B). Plex/remote.

## 8. To confirm during implementation

- MA API shapes on the running version: `music/playlists/playlist_tracks` (paging — note it ignored a `page` arg in a
  2026-09-27 probe), `player_queues/play_media` accepting a URI list.
- Curated playlist mapping = `builtin` + numeric `item_id` — confirm on `my music - costea (local)` (item_id 28).

**Reviews:** an independent agent review and a peer-session review (both 2026-09-27) found the `/command` dry-run
speaking, the list-URI risk to `note_playback`, alias fall-through and fuzzy targets, shuffle leakage and the
agent dropping "shuffle", resume replaying non-local tracks, and a possible YTM source when playing a playlist URI;
all are addressed above or recorded as decisions.
