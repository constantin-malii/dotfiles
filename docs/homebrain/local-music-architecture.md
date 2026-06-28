# Local Music Architecture — homebrain, 2026-06-25

**Objective:** a production-quality, highly reliable, low-maintenance local music system on the ceiling speakers with **minimal external dependencies**, scaling over years. Replaces the shelved YouTube Music path ([`research-playback-lock.md`](./research-playback-lock.md) §8). Everything is **additive and reversible**. Format: **FLAC**.

## 0. Who actually needs the share (key to every decision below)

| Component | Runs on | Accesses music as |
|---|---|---|
| **Plex** | host (192.168.1.68) | **local path** — no share needed |
| **Lidarr (future)** | host | **local path** — no share needed |
| **Download automation (future)** | host | **local path** — no share needed |
| **Music Assistant** | HAOS VM (192.168.1.104) | **network share** (separate machine) |
| **Windows desktop** | your PC | **network share** (seed/manage/tag files) |

So the share has exactly **two consumers: the HAOS VM (MA) and a Windows desktop.** Everything else touches the folder locally. This is why protocol choice hinges on MA + Windows, not on Linux↔Linux speed.

```
            /media/MediaServerData/Music   (single source of truth, on host)
            ├── Plex        (local read)      → TV / phone / remote browsing
            ├── Lidarr      (local r/w, future)→ acquire + file new music
            ├── download     (local w, future)
            └── SMB share ──┬── Music Assistant (HAOS VM)  → primary playback (ceiling)
                            └── Windows desktop            → seed / tag / manage
```
MA and Plex both index the **same** folder; **neither depends on the other.**

---

## 1. Where the library lives

`/media/MediaServerData/Music/` on the host (`/dev/sda1`, 1.8 T, ~110 G free — shares the disk with the existing Movies/TV/Photo libraries). The OS disk is off-limits; the NAS (`/mnt/nas`, unmounted) is a future home for a *large* library — the layout below is mount-point-independent, so moving later is just a re-point. 110 G ≈ ~150 FLAC albums; fine for the 100–200 song foundation, plan disk/NAS expansion for a large collection.

---

## 2. Folder structure + tool compatibility

**Canonical layout (one scheme all tools are configured to produce):**
```
Music/<Album Artist>/<Album> (<Year>)/NN - <Title>.flac
Music/<Album Artist>/<Album> (<Year>)/cover.jpg
Music/<Album Artist>/<Album> (<Year>)/Disc N/NN - <Title>.flac   # multi-disc
Music/Various Artists/<Compilation> (<Year>)/...                  # Album Artist = "Various Artists"
```

| Tool | Compatible? | Note |
|---|---|---|
| Music Assistant | ✅ | parses Artist/Album/Track + reads file tags |
| Plex | ✅ | this *is* Plex's recommended music layout (`Artist/Album/Track`) |
| Lidarr | ✅ | matches its default `{Album Artist}/{Album} ({Year})/...` track format |
| Download automation | ✅ | writes into the same tree (via Lidarr/post-processing) |
| MusicBrainz Picard | ✅ | naming script set to this layout |
| Beets | ✅ | `paths` set to `$albumartist/$album ($year)/$track $title` |

**Verdict: the layout is the long-term-correct lingua franca — no change needed.** The one rule: configure Picard/Beets/Lidarr to all emit *exactly* this scheme so manual and automated additions stay consistent.

---

## 3. Metadata workflow (minimize future manual work + best voice search)

**Principle: tags live IN the FLAC files (Vorbis comments + embedded art), not in any one app's database.** Both MA and Plex read file tags for search/voice-matching; embedding makes the files the single source of truth, portable across every tool, and survives app/library rebuilds.

| Option | Role | Writes tags to files? |
|---|---|---|
| **MusicBrainz Picard** | best-in-class tagging via AcoustID fingerprint; GUI on Windows | ✅ yes |
| **Beets** | CLI import gateway; automated MusicBrainz tagging + art/lyrics plugins; scriptable | ✅ yes |
| **Lidarr** | acquisition + filing/renaming; metadata is *weaker* (organizes, doesn't fingerprint-tag well) | partial |
| **Plex metadata** | enriches Plex's own DB for browsing | ✗ (DB only) |
| **MA metadata** | enriches MA's own DB (MusicBrainz/fanart already enabled) | ✗ (DB only) |

**Recommended workflow:**
- **Foundation seed (now, 100–200 songs):** tag with **MusicBrainz Picard** (GUI on your Windows desktop — ergonomic for a curated one-time set; AcoustID gets matches right). Embed cover art.
- **Long-term (automated):** **Beets as the canonical import gateway** — every new file (from Lidarr/downloads) passes through `beet import`, which writes consistent MusicBrainz tags before it lands in `Music/`. Lidarr handles *acquisition + folder filing*; Beets guarantees *tag quality*. Plex/MA metadata DBs remain a supplementary browsing nicety on top.

**Tag once, at import — not continuously.** Each file is tagged when it enters the library (Picard manually, Beets automatically) and the tags stay in the file permanently. No recurring re-tagging job; MA/Plex just read those tags on scan. Re-tag only on a deliberate quality pass.

---

## 4. SMB vs NFS — comparison for THIS environment

Consumers of the share: **HAOS VM (MA)** + **Windows desktop**. Evaluated against your criteria:

| Criterion | SMB (Samba on host) | NFS (export on host) |
|---|---|---|
| **Windows interop** | ✅ native (Explorer, drive-map, zero setup) | ✗ NFS client only on Win Pro/Ent, clunky, poor UID mapping, weak auth |
| **Linux interop (HAOS/MA)** | ✅ MA `filesystem_smb` + HAOS SMB mounts are first-class (most common HA share type) | ✅ MA `filesystem_nfs` works too |
| **Authentication** | ✅ real user/password; scope a `music` user (RO for MA, RW for desktop/Lidarr) | ✗ host/IP-based only; real user auth needs Kerberos (complex) |
| **Simplicity (one protocol for all)** | ✅ single protocol serves Windows + VM + any phone/mac | ✗ you'd still need SMB for Windows → two protocols to maintain |
| **Reliability / maintenance** | ✅ Samba is ubiquitous, battle-tested, well-documented; fewer edge cases | ⚠ UID mapping / `root_squash` / export tuning are recurring footguns |
| **Performance** | plenty (music = ≤ a few MB/s/stream) | marginally faster/lower-CPU — **irrelevant at this bandwidth** |
| **Future automation** | share-agnostic (Lidarr/downloads are local on host) | same |
| **Backup friendliness** | identical (backup is host-side; files are local) | identical |

**Recommendation: SMB (Samba on the Ubuntu host).** Not for performance — per your guidance, the perf gap is irrelevant for audio. SMB wins on a **compelling operational basis**: a **Windows desktop is in scope**, and SMB is the *single cross-platform protocol* that serves Windows, the HAOS VM, and anything else with **real per-user authentication** and the **best-supported HAOS/MA path**. NFS's only edge (Linux↔Linux speed/CPU) doesn't matter here, and choosing NFS would force a *second* protocol (SMB) for Windows anyway — more moving parts, the opposite of the simple long-term architecture you want. **NFS has no operational advantage in this environment that outweighs SMB's single-protocol + Windows-native + authenticated simplicity.**

> ⏸ **Share protocol awaits your approval before any configuration.**

---

## 5. Plex + MA, same folder, no coupling

- **MA (primary playback):** `filesystem_smb` provider → `\\host\Music` (read-only mount). MA scans, owns its index, plays to the ceiling speakers.
- **Plex (browsing on TV/phone/remote):** add a new Plex **"Music" library** pointing at the local `/media/MediaServerData/Music` (Plex is on the host). Additive; reversible by removing the library; Plex's existing video/photo libraries untouched.
- **Independence:** both read the same files; if Plex is down MA is unaffected and vice-versa. The **folder is the single source of truth**; tags in the files keep both in sync automatically.

---

## 6. Additive & reversible (full rollback)

Each Phase-2 step, with rollback + risk, will be presented before execution. Net plan:
1. `mkdir /media/MediaServerData/Music` — new folder; risk: none; rollback: `rmdir`.
2. Host: install/configure Samba, add **one** `[Music]` share (RO for MA user, RW for desktop) — additive to a new config block; rollback: remove the share block + reload; risk: low (new service/share, nothing existing touched).
3. MA: add `filesystem_smb` provider → scans `Music/`; rollback: delete provider; risk: low (additive provider; YTM/radio/builtin untouched).
4. Plex: add a "Music" library on the local path; rollback: remove library; risk: low.
5. Seed the foundation library (Picard-tagged FLACs) into the layout.
- **Never touched:** radio, YouTube Music, existing Plex libraries, players, networking. **Local music is NOT exposed to ChatGPT until reliability is proven.**

---

## 7. Future automation — concrete plan for THIS environment (not implemented)

**Existing pieces (confirmed 2026-06-25):** indexer = **nzbgeek.info** (Newznab API + key); download client = **SABnzbd on the Synology NAS** (NAS ≈ `192.168.1.83`, Synology OUI `90:09:d0`); a Usenet provider is presumably already configured in that SABnzbd. **Missing piece = Lidarr** (orchestrator). Docker is **not** installed/usable on the Ubuntu host, and `/mnt/nas` is unmounted with no fstab entry.

**Target flow:**
```
nzbgeek (indexer) → Lidarr → SABnzbd (Synology) → Usenet provider → downloads on NAS
                       └── import/rename finished files → \\192.168.1.68\Music (host SoT)
                                   → Lidarr post-import calls MA `music/sync` → MA → ceiling
```
**Where to run Lidarr: on the Synology (Container Manager), co-located with SABnzbd** → local download handoff (no remote-path-mapping pain). Lidarr writes finished music to the host's **`Music` SMB share** (`\\192.168.1.68\Music`, auth `costea`; NAS→host is plain LAN, no macvtap issue) so files land `costea:sambashare` (setgid) and MA reads them. Config: add nzbgeek to **Prowlarr** (central indexer mgmt) or directly to Lidarr; set SABnzbd as the download client; root folder = the mounted `Music` share; **post-import hook → `music/sync`** (event-driven refresh, per §"Filesystem provider refresh behavior").
- **Beets** (optional) → tag-perfecting gateway before files enter `Music/`; **Picard** → manual/seed tagging.
- **Confirm at implementation time:** Usenet provider configured in SABnzbd; Synology model supports Docker/Container Manager; NAS IP (≈`192.168.1.83`).
- *Implement only after Stage 1/2 validation passes. Use for content you're entitled to download.*

---

## 8. Phase 2 validation matrix (run after implementation)

play track · play artist · play album · play playlist · stop · pause · resume · next · previous · volume · **startup latency** · **stop latency** · all **compared against radio**. Local music must be at least as reliable/clean as radio (the proven-good path) before Phase 3.

## 9. Phase 3 (prepare, do not implement)

If playback proves reliable, design the assistant interface. ChatGPT source preference: **1) local library → 2) radio → 3) (future) streaming.** Design only; no exposure until reliability is demonstrated.

---

## Implementation log (live)

- ✅ **Folders** created on host: `/media/MediaServerData/Music` + `/media/MediaServerData/MusicStaging`, owner `costea:sambashare`, mode `2775` (setgid; world r-x so Plex's `plex` user can read). Parent `/media/MediaServerData` is `avahi:root` 755, so creation needed sudo.
- ✅ **SMB shares** appended to `/etc/samba/smb.conf` (`[Music]`, `[MusicStaging]`, `valid users = costea`, `read only = no`), backup at `smb.conf.bak-20260625`. Samba already installed/running, listens on all interfaces. **ufw is inactive** (not enforcing) — firewall is not a factor.
- ✅ **MA Filesystem (SMB) provider** connected: `instance_id=filesystem_smb--yYrXcamj`, `host=192.168.122.1`, `share=Music`, `username=costea`, `content_type=music`, `smb_version=3.0`.
  - ⚠ **Critical topology lesson:** the MA VM's LAN IP `192.168.1.104` is **macvtap**, which *cannot reach its own host* — so `192.168.1.68` fails ("could not connect"). From the VM the host is the **libvirt NAT gateway `192.168.122.1`** (host `virbr0`). Always use `192.168.122.1` for VM→host services. (The host's `eno1`=`192.168.1.68` is only for other LAN machines, e.g. the home PC accessing the share.)
- ✅ **ARCHITECTURE PIVOT — library SoT is now the SYNOLOGY NAS.** Lidarr (installed on the Synology, `192.168.1.83:8686`) downloaded music to **`/volume1/media/music`** (SMB shared folder `media`, subfolder `music`). So the library lives on the NAS, co-located with Lidarr + SABnzbd (the single writer + the downloads). MA indexes the NAS over SMB.
- ✅ **MA Filesystem (SMB) provider → NAS:** `instance_id=filesystem_smb--kd66vco4`, `host=192.168.1.83`, `share=media`, `subfolder=music`, `username=costea`, `smb_version=3.0`. (The VM's macvtap reaches *other* LAN devices like the NAS directly — only the host needed the NAT-gateway trick. MA save validates the SMB connection synchronously and can take >10s, so a WS client must wait ~180s.)
- ◻ **Redundant:** the earlier host provider `filesystem_smb--yYrXcamj` (host `192.168.122.1`, share `Music`, empty) and the host `/media/MediaServerData/Music` folder + Samba shares are now unused — safe to remove (reversible) once we're settled on NAS-as-SoT.
- ✅ **VALIDATION PASSED (2026-06-25)** — see results below.
- ⬜ Plex "Music" library pointed at the NAS share (host mounts `\\192.168.1.83\media` → Plex library on `…/music`) — deferred until now-validated; ready to add.
- ⬜ Metadata cleanup: *Mutter* & *Reise Reise* lack `Album Artist=Rammstein` (grouped under "Various Artists"); one mis-tagged "The Dark Side of the Moon" artist — fix via Picard/Beets `Album Artist` pass.
- ⬜ Lidarr post-import → `music/sync` hook (auto-refresh). ChatGPT exposure proposal (design only).

### Validation results — local playback matrix (2026-06-25, PASS)

Indexed from NAS: **7 artists / 5 albums / 40 tracks** (Rammstein + a soundtrack release). Full matrix on `media_player.ceiling_speakers`, **0 "previous holder appears stuck" across the entire run**:

| Action | Measurement |
|---|---|
| play track / album / artist | play_call 0.08–0.48s → **playing <0.9s** |
| pause / resume | call ≤0.03s → state in ~0.45s |
| next / previous | title changes instantly (~0.01s) |
| volume_set | applied (0.30) |
| stop | call 0.02s → idle 0.45s (clean, no wedge) |
| radio baseline | startup 4.86s (vs local <1s); stop 0.45s |

⇒ Local startup beats radio ~5×; all transport sub-second; stop clean. **The Filesystem→MA→ceiling architecture is reliable.** Harness: `scratchpad/validate_local.{py,txt}`.

**Audible output confirmed** on the physical ceiling speakers (both MA universal + Squeezelite protocol players report `playing`/`powered`/vol synced). Caveats for future tests: MA "playing" ≠ audible — set a sane `volume_level` (the box sat at `0.09`/9%, near-silent); the Universal player exposes **no mute toggle** via HA (`volume_mute` → HTTP error, but it isn't muted).

## Filesystem provider refresh behavior (investigated 2026-06-25)

- **Manual sync:** WS command **`music/sync`** (confirmed valid) triggers a library sync.
- **No real-time watch:** MA does not inotify-watch filesystem providers, and SMB has no reliable change-notification — new files are NOT detected instantly.
- **Scheduled sync:** MA auto-syncs on **startup** and on a **periodic schedule** (observed scheduler cadence ~2h against YTM; same scheduler covers the filesystem provider). Exact global interval not exposed via the provider/core-music config entries that are readable over WS.
- **No per-provider scan-interval/watch setting** on `filesystem_smb` (keys are host/share/creds/content_type/smb_version/cache_mode/library_sync_*/…).

**Recommended auto-refresh design (future, NOT implemented):** event-driven — the **Lidarr post-import script calls `music/sync`** (ideally scoped to the filesystem provider instance) so newly-filed music indexes within seconds. For occasional manual drops in the interim: a single `music/sync` call. Avoid host-side inotify polling unless manual drops become frequent. This satisfies "no manual rescan" without real-time watching, which isn't available over SMB anyway.

## Validation plan (staged)

- **Stage 1:** one well-tagged album (Pink Floyd — *The Dark Side of the Moon*) → `music/sync` → full matrix (index, play track/album/artist, pause/resume/stop/next/previous, volume, startup + stop latency vs radio). Stop and investigate on any issue before more music.
- **Stage 2:** 3–5 albums → repeat matrix. Only then grow toward the permanent library.
- **Plex:** deferred until MA playback is fully validated; then added as an independent consumer of the same folder (no coupling).

## Phase 1 — ChatGPT-controllable local music (provider-agnostic) — in progress

**Provider-aware resolver (Option A), on the HOST.** Pure-HA scripts CANNOT filter by provider (the `search`/`get_library` HA actions strip provider, returning opaque `library://` URIs; the library is contaminated with 2 YTM tracks + 18 YTM playlists). So resolution runs in a small host service that uses the MA WS API (which exposes `provider_mappings`).

- **Files:** `~costea/mass-resolver/resolver.py` (Python 3.5-compatible, raw-socket MA WS client), `config.json` (non-secret), `.ma_token` (0600). Provider-preference = `["filesystem_smb"]` (Phase 7 appends here; ChatGPT-facing API never changes).
- **Resolver rule (airtight):** accept a candidate ONLY if it has an available `filesystem_smb` provider mapping; resolve to `filesystem_smb--kd66vco4://<type>/<item_id>`; reject everything else. Plays via MA WS `player_queues/play_media` (queue_id `upf8b156c25101`). Logs every decision: request_id, query, media_type, candidate, provider, uri, accepted/rejected, reason.
- **Dry-run proof (no audio):** Du Hast/track, Sehnsucht/album, Rammstein/artist → ACCEPTED (filesystem). "My Way"/track + "classic"/playlist (both YTM) → REJECTED, nothing played.
- **Live playback validated (audible, 0 lock-wedges):** track/album/artist play from `filesystem_smb://`; YTM queries rejected and do not disturb an active session. Transport via `ceiling_*` scripts: pause 0.44s, resume 0.42s, next, previous, volume, stop all clean (new `ceiling_next`/`ceiling_previous` created, not yet exposed). Note: `media_pause` issued <~1s after play may not register (stream not yet stable) — fine for real use.
- **Credentials:** dry-run + playback need only the MA token (0600 host file, never logged). The HA token is needed only for the *event/service* layer (next).
- **Service mode VALIDATED:** resolver subscribes to HA WS event `mass_play_request`; `script.play_music` fires it. End-to-end (`script.play_music` → event → resolver → MA → ceiling) confirmed for album + no-type(track) + YTM-reject, on one persistent connection, **0% CPU idle**. Bug fixed during validation: WS reader now detects EOF (was busy-looping) and answers HA ping frames with pongs (keeps the connection alive across events).
- **systemd unit** `~costea/mass-resolver/mass-resolver.service` (runs `resolver.py --serve` as costea, `Restart=always`) — deployed; **needs `sudo` to install/enable** (replaces the manual test instance).
- **Exposed to Assist/`conversation`:** `script.play_music`, `ceiling_pause/resume/stop/set_volume/volume_up/volume_down/next/previous` (all `conversation: True`). NOT the raw `media_player` (keeps ChatGPT on the guarded resolver surface).
- **Prerequisite for ChatGPT:** the OpenAI Conversation entry ("ChatGPT") has `options=null` → **HA control is OFF**; must be set to **Control Home Assistant = Assist** in its Configure dialog before ChatGPT can call the scripts.
- **Remaining:** (1) `sudo` install systemd; (2) enable ChatGPT HA control; (3) validate by real ChatGPT conversation.
- **Token rotation:** revoke the HA long-lived token (HA → Profile → Security) and/or regenerate the MA token, overwrite `~costea/mass-resolver/.ha_token` / `.ma_token` (keep `0600`), then `sudo systemctl restart mass-resolver`. The unit and config.json hold no secrets.
- **Harnesses:** `scratchpad/resolver.py`, `play_test_ws.py`, `transport_test.py`, `svc_validate.py`, `expose_scripts.py`.
- **YTM DISABLED (2026-06-27):** after repeated real-world chaos (UI-started YTM seeding the queue → `next` advancing into YTM; stale YTM resolution hijacking local playback; lock-wedges), the YouTube Music provider was disabled via the MA UI (`enabled=False`, not running). The MA WS API has no clean enable/disable (no command; `save` ignores `enabled`) → UI toggle is the way. Orphaned YTM library items remain (2 tracks, 18 playlists, now unavailable; resolver rejects them; *Remove* the provider to purge them). This makes the exposed `next`/`previous`/`resume` safe (queue can only be local). Reversible: re-enable in MA UI (cookie/auth preserved; 3 minor sync sub-options reverted to defaults during a save attempt).
- **Cleanup pending:** remove the redundant empty host provider `filesystem_smb--yYrXcamj` (host `192.168.122.1/Music`); the NAS `filesystem_smb--kd66vco4` is the real library.
- **Phase 1 VALIDATED STABLE (2026-06-27):** after disabling YTM and **clearing a stale 180-item queue** (YTM playlist interleaved with local tracks — built via the UI while YTM was enabled), the assistant path runs clean: play album/track/artist + next/previous/pause/resume/stop, **0 lock-wedges, 0 YTM plays**, all `filesystem_smb`. Root cause of the prior "no sound / ChatGPT says playing" = `play_media` with `option="play"` on the contaminated queue → `PLAY FAILED: ytmusic--7MLPoF6b is not available`. **Fix:** resolver now plays with **`option="replace"`** (fresh local queue every time, immune to stale queue state). Apply via `sudo systemctl restart mass-resolver` after redeploy. A jammed queue can be cleared with MA WS `player_queues/clear` (queue_id `upf8b156c25101`).

## Phase 2 — auto-refresh after Lidarr imports (DONE 2026-06-27)

**Flow:** Lidarr (On Release Import / On Upgrade) → HA **webhook** `lidarr_import` (`local_only`) → **automation** `automation.lidarr_import_ma_sync` fires HA event `mass_sync_request` → **resolver** (subscribed) runs MA `music/sync`. New downloads appear in MA within seconds — no manual rescan, no periodic-sync wait.

- **Components:** HA automation `lidarr_import_ma_sync` (webhook trigger → fire event); resolver subscribes to `mass_sync_request` + `handle_sync()` → `music/sync`; Lidarr **Connect → Webhook** URL `http://192.168.1.104:8123/api/webhook/lidarr_import` (POST). HA has no native MA-sync service, so the resolver (which holds the MA WS connection) performs the sync; webhook is unauthenticated by design but `local_only`.
- **Validated:** test webhook → `automation.lidarr_import_ma_sync` fired → resolver logged `sync event (source='lidarr')` + `music/sync triggered`.
- **Rollback:** delete `automation.lidarr_import_ma_sync` + the Lidarr webhook; the resolver's `mass_sync_request` subscription is otherwise harmless.

**Acquisition-breadth caveat (affects how much Phase 2 delivers):** Lidarr is **artist/album-centric** (not songs) and **nzbgeek=Usenet has thin coverage for regional (Romanian/Russian) + singles**. For breadth: add a reliable **streaming provider** (Tidal/Qobuz/Spotify — fast, vast, regional; NOT YTM's lock problem; hybrid local→streaming via the resolver's provider-preference) and/or **slskd/Soulseek** (P2P, best for individual/regional tracks). Lidarr+Usenet serves full albums of mainstream artists. (Decision pending.)

## Resolver internals — Inc 0 modular refactor (DONE 2026-06-27)

The monolithic `resolver.py` was refactored into focused modules (the original is preserved as `~costea/mass-resolver/resolver.py.orig` and git baseline `2e2bec7` — a complete standalone fallback). Source of truth is now version-controlled at `docs/homebrain/mass-resolver/` (mirrors the host). Design spec: `2026-06-27-assistant-tooling-design.md`; plan: `plans/2026-06-27-inc0-resolver-foundation.md`.

- **Module layout:** `wsutil.py` (raw WS transport) · `match.py` (pure matcher) · `config.py` (settings/secrets/logging + `config.json`/`radio.json`/`news.json`) · `maconn.py` (MA client) · `haconn.py` (HA client + `announce` TTS) · `music.py` (`resolve_music`) · `radio.py`/`news.py`/`acquire.py`/`status.py` (honest "not available yet" stubs) · `core.py` (dispatch registry + failure feedback + sync) · `resolver.py` (thin entrypoint: `build_ctx`, pure `event_to_call`, `serve`, CLI). 
- **MCP-ready boundary:** capability functions take plain args / return a plain result dict (`ok`/`intent`/`request_id`/`spoken`/`reason` + music extras), decoupled from the HA-event adapter (`event_to_call` is pure). An MCP server or the future `/volume/*` HTTP API (§11 backlog) would be a second adapter over the same functions — no rewrite.
- **Honest failure feedback (NEW):** on no-match/error `core.dispatch` calls `haconn.announce(spoken, settings)` → `tts.speak` on **`tts.piper`** (local), speaking e.g. *"Sorry, I couldn't find X in the local library."* `announce` is hardened to never raise. Observed: MA plays the announcement as an **overlay** (music keeps playing) and **temporarily boosts volume** during the clip (e.g. 24%→44%, 37%→68%), auto-reverting — tunable later if too loud. Config: `tts_service`/`tts_data` in `config.json` (commit `964e50f`).
- **Provider safety preserved:** still `filesystem_smb`-only selection; URI `filesystem_smb--kd66vco4://<type>/<item_id>`; play `option="replace"`.
- **Validation (live, host Python 3.5.2):** 49 stdlib-`unittest` tests green; dry-run + one-shot play + spoken no-match confirmed; end-to-end HA events confirmed after `systemctl restart` — `mass_play_request`→Rammstein plays (`filesystem_smb`, ~0.2–0.4 s; log format `SERVICE: event=… -> intent=music` proves modular), `mass_sync_request`→silent `music/sync`, no-match→Piper speaks. Test/restore baseline state was captured and restored each time.
- **Tests:** stdlib `unittest`, run `python tests/test_<name>.py` from `mass-resolver/` (no pytest).
- **Rollback:** `cp ~/mass-resolver/resolver.py.orig ~/mass-resolver/resolver.py && sudo systemctl restart mass-resolver` (the monolith imports no new modules).
- **Not yet exposed to ChatGPT:** the existing `script.play_music` path is unchanged and now served by the modular resolver; `radio`/`news`/`acquire`/`status` remain stubs wired to nothing (Inc 1–4).

## Requested features (backlog — not yet built)

- **Local name matching — improved 2026-06-27, more wanted (Phase 6).** Resolver matcher now normalizes punctuation (so "E-N-G-E-L" → engel), strips "<title> by <artist>", and does a conservative typo-fuzzy (difflib ≥0.86). Still missing: **semantic/translation** matching — "Angel" does not match the German "Engel" (ChatGPT should map the meaning, or add embeddings/aliases). 
- **Radio via the assistant — WORKING (2026-06-27).** ChatGPT uses `script.ceiling_play_radio` (exposed) → `play_media(media_type=radio)`. Confirmed: **Europa Plus** (not favorited) and **Hit FM** (favorited) both played. The earlier "Hit FM → nothing" was the YTM-contaminated queue at the time, not radio. **Reliable pattern: favorite the exact station** (puts it in `library://radio/...` → unambiguous), especially for ultra-common names with many radiobrowser clones. *Optional robustness (unbuilt, low priority):* route radio through the resolver so a bad/ambiguous name never stops current playback unless a station actually resolves (favorites-first, then radiobrowser top). Build only if flaky radio recurs.
- **Relative volume — FIXED 2026-06-27 (root cause via debug log).** `ceiling_volume_up`/`down` take an optional `step` percent (default 10), compute `current ± step` (clamped 0-1) via `volume_set` — verified correct (up→0.40, up15→0.55, down25→0.30, set50→0.50). **But the real bug was LLM tool-routing:** the HA conversation debug log (`logger.set_level` → `/api/hassio/core/logs`, `chat_log` lines show `Tool call: ceiling_set_volume({'volume':95})`) revealed ChatGPT was calling **`ceiling_set_volume` (absolute) and computing its own small decrement** for "volume down" (e.g. 74→72), never the relative scripts. Fix: rewrote tool descriptions to **forbid `ceiling_set_volume` for relative** ("up/down/louder/quieter/by N%") and mandate Volume Up/Down. **ACTUAL ROOT CAUSE (found via debug log, 2026-06-27): a separate LOCAL sentence-trigger automation, not ChatGPT.** The HA log showed `agent_id='sentence_trigger'` for "volume down". There is a **`automation.voice_ceiling_speakers`** (HA Assist *conversation* triggers) that handles bare phrases LOCALLY before the LLM — play/pause/resume/stop/radio, `volume {percent}`/`set volume to {percent}` (→ `vol_set`), and `volume up/down`/`louder`/`quieter` (→ `vol_up`/`vol_down`). Its vol_up/down branches used `media_player.volume_up/down` = MA's **2%** step. Only phrasings the automation didn't match (e.g. "volume up 10 percent") fell through to ChatGPT's `ceiling_volume_up/down` (10%) — hence the split behavior. **Fix:** rewrote the automation's `vol_up`/`vol_down` branches to `volume_set` current ±0.10. Verified via `/api/conversation/process`: "volume down" 0.50→0.40, "louder" 0.50→0.60. (Also un-exposed `ceiling_set_volume` from ChatGPT earlier — harmless; the automation's `vol_set` handles absolute "set to N".)

> **ARCHITECTURE NOTE — two voice layers:** (1) **`automation.voice_ceiling_speakers`** = fast LOCAL sentence-triggers for exact common phrases (play/pause/stop/radio/volume), no LLM; (2) **ChatGPT** (`conversation.openai_conversation`) = flexible fallback for everything else (the `play_music`→resolver path, fuzzy queries, etc.). HA tries local sentence-triggers first, then the LLM. When debugging voice behavior, check BOTH — and the HA conversation debug log (`logger.set_level` → `/api/hassio/core/logs`, `chat_log`/`sentence_trigger` lines) shows which layer handled a request. **Debugging tip:** `logger.set_level` (REST) + `/api/hassio/core/logs` shows exact LLM tool calls (`/api/error_log` is 404 on this HAOS).
- **Assistant feedback on play_music (Phase 6).** `play_music` is fire-and-forget (script fires an event; ChatGPT gets no result), so the assistant narrates "playing" even when nothing matched the local library. Mitigated for the common case by the resolver's **type-fallback** (2026-06-27: try hinted media_type first, then all other types — so e.g. "play Engel" tagged as artist still finds the track). True fix: resolver triggers a spoken "couldn't find X" (it has an HA WS connection → `call_service` `script.ceiling_announce`) on REJECT, and/or a synchronous result path so ChatGPT knows success/failure.

- **"What's playing?" via the assistant** (req 2026-06-27). ChatGPT should answer the current track/artist. Needs read access to now-playing — either expose `media_player.ceiling_speakers` (read) to the conversation agent, or a small `script`/intent that returns `media_title`/`media_artist`. Fits **Phase 6** (assistant intelligence). Low effort.
- **"Search & download a song/artist from Lidarr" via the assistant** (req 2026-06-27). ChatGPT triggers acquisition: a guarded `script`/resolver action → Lidarr API (`192.168.1.83:8686`) to add the artist/album + trigger a search (→ SABnzbd → nzbgeek → import → `music/sync` → library). Fits **Phase 5** (acquisition pipeline) + **Phase 6** (assistant). Must be guarded (rate/confirm) and only exposed after validation. Lidarr API key required (store 0600, never in repo).

## Inputs needed before Phase 2
1. **Approve SMB** (or override) for the share.
2. **Artist/album list** for the 100–200 song foundation (artists you actually listen to) — or a genre/era steer.
3. **How the FLACs are sourced** (you already have files? rip CDs? a downloader? provide via the Windows desktop?) — determines how they reach `Music/`.
