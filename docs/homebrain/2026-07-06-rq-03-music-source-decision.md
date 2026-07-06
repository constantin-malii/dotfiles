# RQ-03 — Music-Source Direction Decision

> **Decision record / research only. No implementation, no purchase, no subscription, no live change.**
> Settles the music-source direction that informs the `acquire` capability (**MR-Inc3**) and the
> resolver's music-provider preference list. Inputs: `local-music-architecture.md` (esp. the
> "acquisition-breadth caveat"), `2026-06-27-assistant-tooling-design.md` §7/§10,
> `research-playback-lock.md` / ONBOARDING §8–§13 (YTM outcome), CHANGELOG, BACKLOG. External facts
> verified via web 2026-07-06 (sources inline; confidence marked).
>
> Track: **RQ** · Item: **RQ-03** (`research → decision`) · Branch:
> `homebrain/rq-03-music-source-decision` · Locale: **CA / Edmonton**. Live gate (BACKLOG §10) left
> **FREE** — this doc claims no gate and changes nothing live. **Unblocks MR-Inc3.**

---

## 1. Context — why now

- **Local music + radio are the proven-reliable paths.** Local FLAC (on the Synology NAS, indexed by MA
  `filesystem_smb--kd66vco4`) plays in **<1 s, ~5× faster than radio, 0 lock-wedges**
  (`local-music-architecture.md` validation 2026-06-25). Radio is reliable. Both are exposed via the
  resolver (F1-R).
- **YTM is shelved** (RQ-01): the stop-wedge (HTTP/1.0 root cause) + ~95–150 s cold-start + queue
  contamination made it un-exposable; the provider is **disabled** in MA. This is the cautionary tale
  for *any* live-streaming playback on this Squeezelite stack.
- **Acquisition auto-refresh is already built** (`local-music-architecture.md` Phase 2): Lidarr import →
  HA webhook → `mass_sync_request` → resolver `music/sync`. Lidarr runs on the **Synology**
  (`192.168.1.83:8686`) with **SABnzbd + nzbgeek (Usenet)**.
- **`acquire` (MR-Inc3) is blocked on this decision.** It is the guarded ChatGPT-facing "get me this
  song/artist" action; its backend (what it can actually fetch) depends on the source direction chosen
  here.

**The gap that forces the decision** (`local-music-architecture.md` line 220, "acquisition-breadth
caveat"): Lidarr is **artist/album-centric** and **nzbgeek/Usenet is thin on regional (Romanian /
Russian) music and singles** — which is exactly what this household listens to (Romania→ro, Russia→ru
radio aliases; regional focus). So the current pipeline serves *mainstream albums* well and *regional
tracks / singles* poorly.

## 2. What is actually being decided

Two separable questions, plus a config consequence:

- **Q-A — Acquisition breadth** (how the *local* FLAC library gets filled): Usenet-only vs add Soulseek
  vs other. Output is always **owned FLAC on the NAS**, played via the proven local path.
- **Q-B — Live streaming provider** (a *playback* source in MA, hybrid local→streaming): add
  Tidal/Qobuz/Deezer/Spotify, or not.
- **Config consequence** — the resolver's **music-provider preference** (`config.json`,
  `["filesystem_smb"]` today; §5 of the tooling design says providers are appended here).

## 3. Decision criteria (weighted for the stated objective)

The `local-music-architecture.md` objective is *"production-quality, highly reliable, low-maintenance,
minimal external dependencies, FLAC, scaling over years."* Criteria, in priority order:

| # | Criterion | Why it matters here |
|---|---|---|
| C1 | **Playback reliability on this stack** | The Squeezelite/HTTP-1.0 stop-wedge is unresolved (RQ-01/RQ-02). Local FLAC is proven clean; any live stream carries residual wedge/latency risk. |
| C2 | **Regional coverage (Romanian + Russian + singles)** | The actual gap and the household's actual listening. |
| C3 | **Minimal external dependencies / local ownership** | Stated objective; keeps the playback path off the cloud and subscription-free. |
| C4 | **Low maintenance** | Set-and-forget; survives service churn; FLAC tags in files. |
| C5 | **FLAC / quality** | House format is FLAC. |
| C6 | **Cost** | Recurring subscription vs one-time/zero. |
| C7 | **Fits the existing pipeline** | Reuse Lidarr + the built `music/sync` auto-refresh; run where Docker exists (Synology), not the Docker-less Ubuntu host. |

## 4. Options

### A. Lidarr + Usenet (nzbgeek/SABnzbd) — **already in place**
Mainstream full albums, hands-off, lands as FLAC on the NAS, auto-syncs to MA. **Weak on regional +
singles** (the gap). Keep it — it is the mainstream-album workhorse.

### B. Add Soulseek via **Soularr + slskd** (acquisition) — **recommended addition**
Soularr is a Python bridge that reads Lidarr "wanted" items, downloads them from Soulseek via slskd, and
tells Lidarr to import — hands-off ([soularr](https://github.com/mrusse/soularr),
[guide](https://prompts.brightcoding.dev/blog/unlocking-the-power-of-music-how-to-connect-lidarr-with-soulseek-for-seamless-downloads)).
- **C2 — best regional/singles coverage:** Soulseek's P2P catalog is deep on Eastern-European / Russian
  music and individual tracks — precisely where Usenet is thin.
- **C1/C3/C5 — lands as owned FLAC on the NAS → played via the proven local path**, no cloud in playback,
  subscription-free.
- **C7 — fits the pipeline:** it hangs off the **existing Lidarr** as a second download route; Lidarr's
  import → `music/sync` auto-refresh already works.
- **Constraint:** Soularr + slskd want **Docker** — run them on the **Synology (Container Manager)**
  alongside Lidarr/SABnzbd (the Ubuntu host has no Docker). Legal: **only for content you're entitled to
  download** (already flagged in `local-music-architecture.md` §7).

### C. Live streaming provider (Tidal / Qobuz / Deezer / Spotify)
MA supports all of these in 2.x ([MA music sources](https://www.music-assistant.io/music-providers/)).
Instant vast catalog, no storage/tagging. But against the criteria:
- **C1 — unproven on this stack.** Every streaming provider plays through the **same Squeezelite/HTTP-1.0
  path that wedges**. Tidal/Qobuz resolve *faster* than YTM (no deno/PO-token/cookie cold-start), so risk
  is **lower than YTM but not zero** — the root stop-wedge is unfixed upstream (RQ-02).
- **C2 — regional gaps:** **Qobuz does not cover Romania** and is Western/classical-jazz focused
  ([Qobuz countries](https://help.qobuz.com/en/articles/10128-where-is-qobuz-available)); Tidal/Deezer
  reach Romania; **no Western streamer reliably carries Russian catalog in 2026**
  ([comparison](https://freeyourmusic.com/blog/best-music-streaming-services)). So streaming **cannot
  close the Russian gap** — the exact need.
- **C3/C6 — a cloud dependency + recurring subscription**, against the "minimal external dependencies"
  objective.
- If ever added later, **Deezer or Tidal** (Romania-available, FLAC) beat Qobuz (no Romania); Spotify is
  lossy. Quality: Tidal/Qobuz HiRes FLAC, Deezer HiFi (CD-quality FLAC).

### D. Revive YTM — **no.** Shelved by RQ-01 (stop-wedge + latency); keep disabled.

## 5. Comparison

| Criterion | A. Usenet (have) | **B. Soulseek (Soularr+slskd)** | C. Streaming | D. YTM |
|---|---|---|---|---|
| C1 Playback reliability | ✅ local (proven) | ✅ local (proven) | ⚠ residual wedge/latency risk | ❌ shelved |
| C2 Regional + singles | ⚠ thin | ✅ **best (RO/RU/singles)** | ⚠ RO partial, **RU none** | (n/a) |
| C3 Minimal deps / local | ✅ | ✅ | ❌ cloud | ❌ cloud |
| C4 Low maintenance | ✅ | ✅ (hands-off after setup) | ✅ | ❌ cookie churn |
| C5 FLAC | ✅ | ✅ | ✅ (Deezer/Tidal/Qobuz) | ✗ |
| C6 Cost | ✅ (have) | ✅ free | ❌ subscription | — |
| C7 Fits pipeline | ✅ | ✅ (2nd Lidarr route, Synology) | ➖ new provider | ✗ disabled |

## 6. Recommendation + rationale

**Direction: local-first. Fill the regional/singles gap by adding Soulseek (Soularr + slskd) alongside
the existing Lidarr + Usenet. Do NOT add a live streaming provider now. Keep YTM shelved. Keep the
resolver's music-provider preference `filesystem_smb`-only.**

- **Why B (primary):** it is the *only* option that closes the actual gap (regional Romanian/**Russian** +
  singles) **and** keeps every played track as owned FLAC on the proven-reliable local path — no
  subscription, no cloud in the playback path, and it reuses the existing Lidarr + `music/sync` plumbing.
  Streaming structurally *cannot* close the Russian gap (C2), and adds exactly the cloud dependency + a
  reliability class (C1) that this project spent RQ-01/RQ-02 learning to avoid.
- **Keep A:** Lidarr + Usenet stays the mainstream-album path. Lidarr becomes the single orchestrator
  with **two download routes** — SABnzbd/Usenet (albums) + slskd/Soulseek (regional/singles).
- **Defer C:** revisit a streaming provider only if (1) the local + Soulseek path leaves a real,
  demonstrated gap, **and** (2) MA→Squeezelite streaming reliability is proven on this stack. If added
  then, prefer **Deezer or Tidal** (Romania + FLAC) over Qobuz; note it still won't cover Russian catalog.

## 7. Consequences — what this unblocks / sets

- **Unblocks MR-Inc3 (`acquire`)** — its backend is now defined: a **guarded Lidarr add+search** (artist/
  album), with Lidarr wired to **both** download clients, so one `acquire` call can pull mainstream albums
  (Usenet) *and* regional singles (Soulseek). Design `acquire` against Lidarr's API (`192.168.1.83:8686`,
  key stored `0600`, never in repo), rate-limited/confirmed, exposed only after validation.
- **Resolver provider-preference stays `["filesystem_smb"]`** — all acquired music is local FLAC; no
  provider-preference change. (If streaming is ever added, append it *after* filesystem so local always
  wins.)
- **No change to the proven local + radio playback paths**; YTM stays disabled.

## 8. Open questions / follow-ups

- **Q1 — Synology Docker:** confirm the Synology model runs Container Manager and can host **slskd +
  Soularr** next to Lidarr/SABnzbd (implementation-time check; the Ubuntu host has no Docker).
- **Q2 — Entitlement/legal:** Soulseek is P2P — use only for content you're entitled to download
  (as already noted in `local-music-architecture.md` §7). Owner acknowledgement before build.
- **Q3 — `acquire` scope (MR-Inc3):** album/artist only (Lidarr-native) first, or also a per-track path?
  Track-level regional fetch is the Soulseek strength — decide the tool's parameter surface at MR-Inc3
  design.
- **Q4 — Streaming trial (optional, later):** if desired, a time-boxed Deezer/Tidal trial to characterize
  MA→Squeezelite reliability before any commitment — not now.
- **Q5 — Russian catalog:** confirmed **not** served by Western streaming (2026); Soulseek/owned files are
  the realistic route. No action beyond B.

## 9. What this document does NOT do

- **No purchase / subscription / trial** — no streaming account created; no cart/checkout.
- **No install or config** — no slskd/Soularr/Lidarr/MA/HA change; no Docker container created; no host or
  Synology change; no resolver `config.json` edit.
- **No exposure** — `acquire` is not built or exposed; no `conversation` change; gpt-4o-mini unchanged.
- **No gate opened/closed** — decision record only; BACKLOG §10 left **FREE**.
- **No BACKLOG row status change beyond a next-action note** (INF-owned board; §9) — proposed separately.
- **No secrets** — Lidarr/slskd API keys are `0600` host/NAS files at implementation, never in repo.

---

> **Rollback for this document:** `git revert` on `homebrain/rq-03-music-source-decision`, or delete this
> file. No secrets, no implementation, no exposure, no purchase; live gate left FREE.
