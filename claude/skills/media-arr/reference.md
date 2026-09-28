# media-arr reference — recipes and gotchas

All endpoints are relative to the app base in SKILL.md (`/api/v3` Radarr/Sonarr, `/api/v1` Lidarr). Auth header
`X-Api-Key`. SABnzbd: `GET /api?mode=...&output=json&apikey=...` (never echo that URL).

## Diagnose
- Health: `GET health`; force a recheck: `POST command {"name":"CheckHealth"}`.
- What the app's **own user** can see: `GET filesystem?path=/volume1/...&includeFiles=true` — the only way to test DSM
  permissions from outside.
- Reveal the run-as user without changing anything: PUT `config/mediamanagement` with `recycleBin` set to a
  non-existent path → 400 "not writable by user 'sc-xxx'"; nothing is saved.
- Why a release was rejected: `GET release?movieId=|episodeId=|albumId=` (interactive search; read-only, grabs
  nothing, uses indexer API quota) → `approved`, `rejections`.
- Why something was grabbed: `GET history/series?seriesId=` → `data.seriesMatchType` (`Id` vs `Title`),
  `data.tvdbId` (indexer's, often wrong), `sourceTitle`.
- Queue row reasons: `statusMessages[].messages`, `errorMessage`, `trackedDownloadState`.
- "Stale" missing movies: sweep `release?movieId=` for each monitored/available/no-file movie, then bucket by
  rejection. The big systemic one was the profile **language = English**: every foreign film's correct release
  was "English is wanted, but found X". Fixed by setting it to `Original` (id -2); dubs still get rejected.
- **Pace bulk searches.** NZBgeek resets connections under bursts (~100 back-to-back searches): Radarr then
  backs the indexer off and later searches log "0 active indexers" and silently grab nothing. Check the log
  for that line after any bulk `MoviesSearch`; `POST indexer/testall` clears the backoff. Search one movie
  at a time with ~20 s gaps.
- Calling `arr.py` from Git Bash: args starting with `/` get rewritten to `C:/Program Files/Git/...`
  (`MSYS_NO_PATHCONV=1`, or call it from a Python `subprocess`), and files written by Windows Python have CRLF
  — `for i in $(cat ids.txt)` then yields `12\r`.

## Queue actions
- Untrack only (files untouched): `DELETE queue/{id}?removeFromClient=false&blocklist=<bool>&skipRedownload=true`.
- Failed download (partials in `incomplete/` only): `removeFromClient=true&blocklist=true&skipRedownload=true`, then
  search: `EpisodeSearch {episodeIds}`, `MoviesSearch {movieIds}`, `AlbumSearch {albumIds}`, `SeasonSearch {seriesId,seasonNumber}`.
- "Download wasn't grabbed by X, skipping" = stale SAB history the app won't auto-handle → remove + search.
- Grab a specific release: `POST release {"guid","indexerId"}` (bypasses profile rejections — pick deliberately).

## Manual import
1. Scan: Sonarr `GET manualimport?downloadId=<queue.downloadId>&filterExistingFiles=true` (**not seriesId**);
   Radarr `GET manualimport?folder=<path>` (a single **file** path works too and detects quality).
2. Radarr needing a movie: `POST manualimport [{path, movieId, quality: <scanned>, languages, indexerFlags}]` (reprocess).
3. Import: `POST command {"name":"ManualImport","importMode":"move","files":[{path, movieId | seriesId+episodeIds,
   quality, languages, releaseGroup, indexerFlags, downloadId}]}` — it does **not** re-check rejections; filter first.
4. Safety filter used successfully: file episode ∈ the queue item's episode; path inside the download folder; no
   "sample" in name and size > ~300 MB (episodes) / 0.3 GB (movies); only benign rejection allowed:
   "Unable to determine if file is a sample" on a full-size file (mediainfo couldn't read runtime).
5. Rescan can link a **sample** as a movie's file when a folder holds both — check `movieFile.size` afterwards.
6. No queue row left (SAB history entry gone) → `downloadId` scan is impossible; scan the download **folder** instead.
   Names Radarr can't parse (e.g. `LOTR.The.Two.Towers…`) come back "Unknown Movie": reprocess with the movieId.
7. **"database is locked" under NAS load** (log: `MovieService failed while processing [MovieFileAddedEvent]`) leaves a
   movie with a moviefile record (`GET moviefile?movieId=`) but `movieFileId=0` / `hasFile=false`. `RescanMovie`,
   `RefreshMovie` and `PUT movie` with `movieFileId` do NOT fix it. Unmonitor the movie (else Radarr may grab a
   duplicate), have the user delete the file in Radarr so it lands in the recycle bin (or move it out in File Station),
   then ManualImport it back (re-add the movie first if it was deleted too) — verified fix. Keep NAS load low (SAB
   paused) while doing heavy imports; the lock came from parallel downloads + Lidarr refreshes + API calls.

## Bringing existing files under an *arr (no moves)
- Radarr: `GET parse?title=<folder>` → `GET movie/lookup?term="title year"`; accept only exact normalized title
  (incl. alternate/original titles) + exact year. `POST movie {…lookup, path:<existing folder>, monitored:false,
  addOptions:{searchForMovie:false, monitor:"none"}}` → `RefreshMovie` → monitor only those with `hasFile`.
  Radarr does not rename files found by rescan.
- Lidarr: `GET album/lookup?term="artist album"` → `POST album {…lookup, monitored:true, addOptions:{searchForNewAlbum:false},
  artist:{…, monitorNewItems:"none", addOptions:{monitor:"none"}}}`. Adding an artist triggers a long `RefreshArtist`
  (whole discography) — busy, not stuck; poll it.

## Profiles in use
- Radarr "HD 1080p" / Sonarr "HD 1080p": WEB 720p, Bluray-720p, HDTV-1080p, WEB 1080p, Bluray-1080p; cutoff WEB 1080p;
  upgrades off. New series/movies should use it. Radarr's has language **Original** (was English, which blocked
  every foreign film). Sonarr v4 has no profile language (only custom formats; none defined) — any language passes.
- Radarr size limits: Bluray-1080p max raised 55 → 100 MB/min (pref 95) to match the other 720p/1080p qualities;
  55 rejected normal 6–9 GB encodes. Sonarr's are 125–155 MB/min, fine.
- Lidarr "default": Lossless + High Quality Lossy + Unknown (Unknown `minSize`=180). Metadata "Standard" (albums) or
  "Playlist" (albums, EPs, singles, soundtracks). Only wanted albums monitored; `monitorNewItems:none`.
- Recycle bins: `/volume1/media/{radarr,sonarr,lidarr}-recycle` (30 days). `/volume1/media/#recycle` is Synology's
  share bin and does NOT catch app deletes.
- Sonarr release profile "The Hunt 2015: reject Apple 2026" (tag `the-hunt-bbc`, ignored `ATVP`,`2026`).

## SABnzbd
- `set_config`: `mode=set_config&section=misc&keyword=K&value=V` (lists comma-separated). Categories via
  `section=categories`. Backup: `mode=config&name=create_backup` → `backup_dir`.
- Applied: abort password-protected and unwanted extensions (`exe,com,bat,cmd,scr,pif,lnk,vbs,js,msi`),
  `ignore_samples=1`. Sorting off (the *arrs rename).
- Tuned for the 2-HDD DS224+ (2 GB RAM): server connections 50 → 25 (`section=servers&keyword=<server name>
  &connections=25`), `direct_unpack=0`, `pause_on_post_processing=1`. Slow downloads were disk-seek bound, not
  CPU or line: DSM showed CPU 4%, load ~30, ~35 MB/s scattered reads (SAB par2 repair plus Drive, Office,
  Photos, Plex, the *arrs, swap). With downloads and repairs taking turns: 2–5 MB/s → ~21 MB/s.
- `mode=fullstatus` gives `loadavg` and per-server warnings — the first check when downloads are slow.
- Provider is Newsgroup Ninja (Highwinds). "Aborted, cannot be completed" and heavy repairs are missing articles
  there; a backup block account on a different backbone (server priority 1) is the fix, not another indexer.
- Individual jobs can be paused while the queue isn't ("Idle" with jobs) — check slot `status`.

## Indexers
- NZBgeek only (priority 25, RSS on). Tried NZBFinder: free accounts get **no API** (error 102, "premium
  member"), so it can't be added to the *arrs; Basic is $15/yr. Web-searching 8 missing Russian/Soviet titles:
  NZBgeek 0, NZBFinder 1 (Petrov's Flu) — Usenet barely carries them, so another indexer helps only a little.
- A one-off find on an indexer's website works without API: download the .nzb, add it to SAB with the `movies`
  category, then manual-import it (Radarr won't auto-import a download it didn't grab).
- A backup indexer should get priority ~40 and `enableRss:false` so a small daily quota survives. Adding one via
  API: take the `Newznab` schema's preset (e.g. `NZBFinder.ws`), set `apiKey`, POST `indexer`. The POST tests
  the key and returns 400 on failure, so nothing half-added is left behind.

## HomeBrain links (don't break)
- Lidarr "On Import" → HA webhook `lidarr_import` → resolver `music/sync` → Music Assistant rescans
  `/volume1/media/music` (SMB). Imports that move music trigger an MA resync — expected.
- MA read access: run a script **on the HomeBrain host** that reads `~/mass-resolver/.ma_token` itself
  (`ssh costea@192.168.1.68 'python3 -' < script.py`, Python 3.5, WS `http://192.168.122.10:8095/ws`). See
  docs/homebrain/ONBOARDING.md §3. The YouTube Music provider in MA is disabled; public YTM playlists can be read with
  `ytmusicapi` (no login) instead.

## Performance
The NAS slows badly while SAB unpacks: API calls can take 30–60 s. Use ≥180 s timeouts, avoid polling
`movie`/`series` lists repeatedly, prefer `queue`/`command`/`{item}/{id}`. Ask the user to pause SAB for heavy API work.
