---
name: media-arr
description: Use when working with the home media stack on the Synology NAS — Radarr, Sonarr, Lidarr, SABnzbd or Plex — e.g. checking downloads, searching or adding movies/series/albums, stuck or failed queue items, "import blocked", "does not appear to exist", wrong episodes, searches that grab nothing, or library cleanup.
---

# Media *arr stack (home NAS)

## Overview
Radarr/Sonarr/Lidarr/SABnzbd run as **SynoCommunity packages on the Synology DS224+ at 192.168.1.83** (not Docker).
Generic *arr API knowledge is fine; what goes wrong is this setup's non-defaults and systemic causes. Read
`reference.md` before any write.

| App | URL | Runs as |
|---|---|---|
| Radarr 5.x | `http://192.168.1.83:8310` (**not 7878**) | `sc-radarr` |
| Sonarr 4.x | `:8989` | `sc-sonarr` |
| Lidarr 3.x (API **v1**) | `:8686` | `sc-lidarr` |
| SABnzbd 5.x | `:8080` | — |
| Plex (live) | NAS `:32400` (1.41, Quick Sync incl. HEVC). The Ubuntu host's Plex 1.18 is unclaimed/orphaned. | |

Library `/volume1/media/{movies,tvshows,music}`; downloads `/volume1/sabnzbd-downloads/complete/{movies,tvshows,music}`.

## Keys
`~/.config/media-arr/credentials` (chmod 600), one `app=KEY` line each (`radarr`, `sonarr`, `lidarr`, `sabnzbd`).
Missing → ask the user for it (Settings → General → Security → API Key; SABnzbd needs the full API Key, not the NZB
key). Never read keys out of an app's web page, never print them, never put them on a command line.

## Tool
`python -u scripts/arr.py --help` — `status`, `queue <app>`, `check-paths`, `movies --genre G --min-imdb X --have`,
`get … [--out FILE]`, `poll`, and `send … --confirm` (the only write path). Always `-u`; start `poll <app>` beside any
wait over ~2 min. After editing `arr.py`, run `python scripts/test_arr.py` (offline stub test).

## Before fixing any stuck queue: run `check-paths`
Mass "import blocked / sample / root folder" items are nearly always systemic. Fix the cause first:
- **SAB category dir inside the library** (a category with an absolute path overrides `complete_dir`).
- **`sc-<app>` can't list `/volume1/sabnzbd-downloads`** → "directory does not appear to exist": DSM Control Panel →
  Shared Folder → `sabnzbd-downloads` → Permissions → *System internal user* → Read/Write. The user does this.
- **"Not on your server(s)"** = Usenet provider takedowns, not config.

## Rules
- Read-only first; show a dry-run table; write only after the user agrees.
- **No library file deletes via API** (the permission classifier blocks them). Give the user exact UI steps.
- `removeFromClient=true` only for **failed** downloads — on completed ones it deletes the files.
- Nothing deleted that might be the only copy; duplicates are reported, the user decides.
- Quality preference: 1080p-ish ("not super good, not bad"), Lossless or MP3 ~320 for music.

## Common mistakes (details + recipes in reference.md)
| Symptom | Real cause / fix |
|---|---|
| Can't reach Radarr | Port 8310 |
| Sonarr manual import grabs wrong episodes | `manualimport?folder=&seriesId=` scans the **series folder**; scan by `downloadId` |
| Radarr `manualimport?movieId=` → HTTP 500 | Scan folder, then `POST manualimport` (reprocess) with movieId + scanned quality |
| Lidarr grabs nothing even with MP3 allowed | Scene MP3 names parse as **Unknown** → allow Unknown with `qualitydefinition` Unknown `minSize` ≈180 |
| Episodes from a same-name show | Title match on RSS; tag + release profile ignoring the other show's markers (e.g. `ATVP`, year) |
| Season pack removal 404s | One download = many rows; first DELETE removes it |
